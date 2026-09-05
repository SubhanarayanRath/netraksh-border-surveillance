"""
NETRAKSH Edge — Main Pipeline.
Integrates all layers in the correct order:
  Layer 1: Camera ingestion (adapter)
  Layer 2: Health monitor (Gate 1) + Scene condition (Gate 2)
  Layer 3: YOLO + ByteTrack detection (Gate 3)
  Layer 4: Task modules (fence, behavior, ANPR, face)
  Layer 5: Reliability decision (3-gate)
  Layer 6: Evidence packaging + hash-chain
  Layer 7: Store-and-forward sync

Each event fired by a task module goes through the full reliability stack.
Zero detections also generate periodic health heartbeat events.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent.parent))

from edge.condition.preprocessing import enhance_for_detection
from edge.condition.scene_condition import SceneConditionClassifier
from edge.detection.adaptive_gate import AdaptiveComputeGate
from edge.detection.calibration import CalibrationModule
from edge.detection.detector import DetectionTracker, NightMotionFallback
from edge.evidence.packager import EdgeKeyManager, EvidenceChainStore, EvidencePackager
from edge.health.camera_health import CameraHealthMonitor
from edge.ingestion.camera_adapter import CameraAdapter
from edge.instrumentation.metrics import PipelineMetrics
from edge.reliability.decision import make_abstain, make_reliability_decision, make_uncertain
from edge.rules.modules import (
    ANPRModule,
    BehaviorModule,
    FaceDetectionModule,
    LineCrossingModule,
    VirtualFenceModule,
    load_zones,
)
from edge.sync.sync_client import SyncClient
from edge.temporal.event_verifier import EventVerifier
from edge.temporal.track_features import TrackFeatureTracker
from edge.tracking.continuity_guard import TrackContinuityGuard
from edge.tracking.continuity_guard import compute_histogram as compute_track_histogram
from shared.constants import (
    NIGHT_MOTION_COOLDOWN_SECONDS,
    CameraHealthState,
    DecisionState,
    DetectionClass,
    EventType,
    SceneCondition,
    Severity,
)

logger = logging.getLogger(__name__)


def determine_severity(event: dict, reliability) -> Severity:
    """Heuristic severity assignment for MVP."""
    et = str(event.get("event_type", ""))
    if "FENCE_CROSSING" in et:
        direction = str(event.get("direction", ""))
        if "OUTSIDE_TO_RESTRICTED" in direction:
            return Severity.HIGH
        return Severity.MEDIUM
    if "LINE_CROSSING" in et:
        # Unlike a fence polygon, a line has no inherent inside/outside, so
        # neither A_TO_B nor B_TO_A can be assumed to be "the bad direction"
        # without zone-specific configuration this module doesn't have —
        # MEDIUM reflects "a real crossing happened," not "a specific
        # direction is confirmed dangerous."
        return Severity.MEDIUM
    if "LOITERING" in et:
        dwell = event.get("rule_value", 0)
        return Severity.HIGH if dwell > 60 else Severity.MEDIUM
    if "ABANDONED" in et:
        return Severity.HIGH
    if "ANPR" in et:
        return Severity.MEDIUM
    if "FACE" in et:
        return Severity.LOW
    if "MOVEMENT_UNCLASSIFIED" in et:
        # Night-motion fallback (architecture v4 §3): honestly LOW — this is
        # "something moved, class unknown," never a confirmed detection.
        return Severity.LOW
    return Severity.LOW


class EdgePipeline:
    """
    Main edge pipeline. Runs all layers per-frame.
    """

    def __init__(self, config: dict):
        self.config = config
        self.camera_id = config["camera_id"]
        self.camera_name = config.get("camera_name", self.camera_id)
        self.zone_config_path = config.get("zones_config_path", "demo/scripts/zones_config.json")
        self._running = False

        # Initialize all layers
        logger.info(f"[Pipeline] Initializing edge pipeline for camera {self.camera_id}...")

        # Layer 1: Camera adapter
        self.adapter = CameraAdapter(
            source=config.get("video_source"),
            simulate_frozen=config.get("simulate_frozen", False),
            simulate_night=config.get("simulate_night", False),
        )

        # Layer 2: Health + Condition
        self.health_monitor = CameraHealthMonitor(
            camera_id=self.camera_id,
            fps_declared=config.get("fps_declared", 25.0),
        )
        self.condition_classifier = SceneConditionClassifier(camera_id=self.camera_id)

        # Layer 3: Detection + calibration
        self.calibration = CalibrationModule(
            calibration_path=config.get("calibration_path")
        )
        self.detector = DetectionTracker(
            model_size=config.get("model_size", "yolov8n.pt"),
            device=config.get("device", "cpu"),
        )
        self.adaptive_gate = AdaptiveComputeGate()

        # Night-motion fallback (architecture v4 §3) — was implemented but
        # never wired into the pipeline before this change; see
        # docs/ARCHITECTURE.md's changelog entry for the fix.
        self.night_motion_fallback = NightMotionFallback()
        self._last_night_motion_emit_time = 0.0

        # Load zones
        self.zones = load_zones(self.zone_config_path)
        logger.info(f"[Pipeline] Loaded {len(self.zones)} zones from {self.zone_config_path}")

        # Layer 4: Task modules
        self.fence_module = VirtualFenceModule(self.zones)
        self.line_module = LineCrossingModule(self.zones)
        self.behavior_module = BehaviorModule(self.zones)
        self.anpr_module = ANPRModule(self.zones)
        self.face_module = FaceDetectionModule(self.zones)

        # Layer 6: Evidence
        key_dir = config.get("key_dir", "certs/edge")
        self.key_manager = EdgeKeyManager(
            private_key_path=os.path.join(key_dir, f"{self.camera_id}.key"),
            public_key_path=os.path.join(key_dir, f"{self.camera_id}.pub"),
        )
        self.key_manager.load_or_generate()

        chain_path = config.get("chain_db_path", f"edge/data/chain_{self.camera_id}.db")
        self.chain_store = EvidenceChainStore(chain_path)
        self.packager = EvidencePackager(
            camera_id=self.camera_id,
            key_manager=self.key_manager,
            chain_store=self.chain_store,
            clip_storage_dir=config.get("clip_dir", "edge/data/clips"),
        )

        # Layer 7: Sync
        self.sync_client = SyncClient(
            edge_device_id=self.camera_id,
            backend_url=config.get("backend_url", "http://localhost:8443"),
            db_path=config.get("sync_db_path", f"edge/data/sync_{self.camera_id}.db"),
            auth_token=config.get("auth_token", ""),
            ca_cert_path=config.get("ca_cert_path"),
            client_cert_path=config.get("client_cert_path"),
            client_key_path=config.get("client_key_path"),
        )

        # Track trajectories for ByteTrack
        self._trajectories: Dict[int, List] = {}
        # Track last default zone for events without specific zone
        self._default_zone_id = self.zones[0].zone_id if self.zones else "zone-default"

        # Layer 4.5: Event Verification state machine (architecture v4 §9).
        # Evidence is now packaged only once a candidate is promoted to
        # VERIFIED/ALERTED here — not the instant a task module fires.
        self.event_verifier = EventVerifier()
        self._verify_tick = 0

        # Temporal Evidence Intelligence, Mode A (architecture v4 §7, ADR-001).
        # Feeds the `temporal_score` (T) input to the Hybrid Reliability
        # Engine (edge/reliability/decision.py).
        self.track_feature_tracker = TrackFeatureTracker()

        # Track Continuity Guard (architecture v4 §4) — classical-CV
        # re-association of a track lost to brief occlusion. See
        # edge/tracking/continuity_guard.py.
        self.continuity_guard = TrackContinuityGuard()
        self._known_track_ids: set = set()
        self._track_last_snapshot: Dict[int, dict] = {}

        # Performance instrumentation (architecture v4 §15, MUST HAVE).
        # Real, locally-measured latency/FPS/resource numbers — never invented.
        self.metrics = PipelineMetrics()
        self._metrics_report_interval = config.get("metrics_report_interval_seconds", 10.0)
        self._metrics_json_path = config.get(
            "metrics_json_path", os.path.join("edge", "data", f"metrics_{self.camera_id}.json")
        )

    def start(self) -> None:
        """
        Start the pipeline. Loads model, opens camera, then runs frame loop.
        Sync runs in a background thread.
        """
        logger.info(f"[Pipeline] Loading YOLO model...")
        self.detector.load()

        # Start sync in background thread
        sync_thread = threading.Thread(
            target=self.sync_client.run_sync_loop,
            daemon=True,
            name=f"sync-{self.camera_id}",
        )
        sync_thread.start()
        logger.info("[Pipeline] Sync thread started")

        self._running = True
        logger.info(f"[Pipeline] Starting frame loop for camera {self.camera_id}")

        try:
            self._run_frame_loop()
        except KeyboardInterrupt:
            logger.info("[Pipeline] Interrupted by user")
        finally:
            self._running = False
            self.adapter.release()

    def _run_frame_loop(self) -> None:
        """Main frame processing loop."""
        frame_skip = self.config.get("frame_skip", 1)  # process every Nth frame
        frame_count = 0
        last_health_report_time = 0.0
        last_metrics_report_time = 0.0

        with self.adapter:
            for frame, meta in self.adapter.frames():
                if not self._running:
                    break

                frame_count += 1
                if frame_count % frame_skip != 0:
                    continue

                self._process_frame(frame, meta)
                if time.time() - last_health_report_time > 5.0:
                    last_health_report_time = time.time()
                    self._report_camera_health()
                if time.time() - last_metrics_report_time > self._metrics_report_interval:
                    last_metrics_report_time = time.time()
                    self._report_metrics()

    def _report_camera_health(self) -> None:
        """
        Push a periodic real health snapshot to the backend
        (POST /cameras/{id}/health), independent of any detection event —
        this is what actually populates the Camera Health Matrix dashboard
        page's per-camera FPS/blur/exposure/drift readings.

        Before this method existed, `last_health_report_time` was threaded
        through `_process_frame`'s signature every frame but never actually
        read there — a dead timer implying a heartbeat that was never sent,
        despite this module's docstring claiming one existed. CameraHealth
        rows were never written by any code path (see docs/LIMITATIONS.md).

        Best-effort only, same posture as SyncClient's offline tolerance —
        a failed POST here must never interrupt the frame loop. This is
        NOT routed through the offline sync queue (unlike events): it's a
        best-effort heartbeat, not evidence: losing one is fine, and the
        next one is only 5 seconds away.
        """
        health = getattr(self, "_last_health", None)
        if health is None:
            return
        try:
            import httpx
            httpx.post(
                f"{self.sync_client.backend_url}/cameras/{self.camera_id}/health",
                content=health.model_dump_json(),
                headers={"Content-Type": "application/json"},
                timeout=3.0,
            )
        except Exception as exc:
            logger.debug(f"[Health] Periodic health report failed (non-fatal): {exc}")

    def _apply_continuity_guard(self, tracks: List, frame) -> List:
        """
        For every track ID not seen before, ask the Continuity Guard whether
        it matches something recently lost (histogram + spatial proximity).
        On a match, the new detection's track_id AND trajectory are rewritten
        in place to the old, recognized identity — logged, not silent — so
        every downstream consumer (trajectory store, T-feature age tracking,
        VirtualFenceModule's zone-membership state, BehaviorModule's
        dwell/stationary tracking) resumes exactly where it left off.
        """
        now = time.time()
        for track in tracks:
            if track.track_id in self._known_track_ids:
                continue
            histogram = compute_track_histogram(frame, track.bbox)
            match = self.continuity_guard.resolve_new_track(histogram, track.bbox.centroid, now)
            if match is not None:
                matched_id, matched_trajectory = match
                logger.info(
                    f"[Pipeline] Track {track.track_id} re-associated with recently-lost "
                    f"track {matched_id} by Continuity Guard — resuming its history"
                )
                track.track_id = matched_id
                track.trajectory = list(matched_trajectory) + list(track.trajectory)
            self._known_track_ids.add(track.track_id)
        return tracks

    def _process_frame(self, frame, meta) -> None:
        """Process a single frame through the full pipeline."""
        import numpy as np

        self._verify_tick += 1

        # --- Performance instrumentation: t0 (frame received) ---
        t_frame_start = time.perf_counter()

        # === Layer 2: Gate 1 — Camera Health ===
        health = self.health_monitor.update(frame, meta.timestamp)
        self._last_health = health

        # === Layer 2: Gate 2 — Scene Condition ===
        condition = self.condition_classifier.classify(frame)

        t_health_condition = time.perf_counter()

        # If camera FAILED, emit ABSTAIN heartbeat and stop
        if health.health_state == CameraHealthState.FAILED:
            reliability = make_abstain(self.camera_id, health.health_reason, condition.condition)
            self._emit_event(
                track=None,
                reliability=reliability,
                health=health,
                condition=condition,
                zone_id=self._default_zone_id,
                overrides={},
                frame=None,  # Don't waste disk on failed camera snapshots
            )
            t_frame_end = time.perf_counter()
            self.metrics.record_frame(
                health_condition_ms=(t_health_condition - t_frame_start) * 1000.0,
                detection_tracking_ms=0.0,
                event_processing_ms=(t_frame_end - t_health_condition) * 1000.0,
                total_frame_ms=(t_frame_end - t_frame_start) * 1000.0,
            )
            return

        # === Layer 2.5: Adaptive Compute Gate (architecture v4 §6) ===
        # Skip full YOLO inference on genuinely idle frames (no motion, no
        # active track, no pending candidate) to save compute — reuses Gate
        # 1's own frame-difference variance, no new per-frame cost. Never
        # skips a frame that already has something being tracked (see
        # edge/detection/adaptive_gate.py's module docstring for why that's
        # what makes this safe for ByteTrack's continuity).
        run_inference = self.adaptive_gate.should_run_inference(
            frame_variance=health.frame_variance,
            has_active_tracks=bool(self._trajectories),
            has_pending_candidates=self.event_verifier.get_pending_count() > 0,
        )

        # === Layer 3: Gate 3 — YOLO + ByteTrack ===
        calibrated_threshold = self.calibration.get_threshold(condition.condition)

        if run_inference:
            # CLAHE preprocessing (architecture v4 §3): a SEPARATE enhanced
            # copy for LOW_LIGHT_NIGHT/FOG_RAIN, detector input only — health,
            # condition, evidence snapshots, and ANPR/face crops all keep
            # using the original `frame` so their measurements stay honest.
            detection_frame = enhance_for_detection(frame, condition.condition)
            try:
                tracks = self.detector.detect_and_track(
                    detection_frame, condition.condition, calibrated_threshold,
                    existing_trajectories=self._trajectories,
                )
            except Exception as exc:
                logger.error(f"[Pipeline] Detector error: {exc}")
                tracks = []
        else:
            tracks = []

        t_detection_tracking = time.perf_counter()

        # === Layer 3.5: Track Continuity Guard (architecture v4 §4) ===
        # Re-associates a brand-new ByteTrack ID with a recently-lost one via
        # color-histogram + spatial proximity — classical CV, no learned
        # Re-ID — BEFORE anything else (trajectory, T-feature age, task
        # modules) sees the track. Every downstream consumer keyed by
        # track_id therefore resumes its prior state automatically once a
        # re-association happens, with no further changes needed.
        tracks = self._apply_continuity_guard(tracks, frame)
        for expired_id in self.continuity_guard.expire_stale(time.time()):
            self.track_feature_tracker.forget(expired_id)

        # Update trajectory state + snapshot each active track's appearance
        # (histogram + centroid) so the Continuity Guard has something to
        # match against the moment this track is later lost.
        #
        # track_feature_tracker.observe() is called here UNCONDITIONALLY for
        # every active track, every frame — a real, measured bug fix (see
        # edge/temporal/track_features.py's class docstring and
        # docs/PERFORMANCE_REPORT.md's "Reliability Engine behavior" section):
        # this class's `_first_seen` bookkeeping must be registered as soon
        # as a track is first observed, not only when some task module
        # module later happens to fire an event for it (temporal_score_for()
        # below only calls `compute()` inside those event-triggered
        # branches) — a fence-crossing event, which by its nature usually
        # fires exactly once per track at the crossing transition, would
        # otherwise ALWAYS see age_seconds=0.0 on that one call, regardless
        # of how long the track had genuinely already been tracked.
        for t in tracks:
            self._trajectories[t.track_id] = t.trajectory
            self._track_last_snapshot[t.track_id] = {
                "histogram": compute_track_histogram(frame, t.bbox),
                "centroid": t.bbox.centroid,
            }
            self.track_feature_tracker.observe(t.track_id, time.time())

        # Clean up stale trajectories — hand off to the Continuity Guard's
        # lost pool (with a grace window) instead of forgetting immediately.
        active_ids = {t.track_id for t in tracks}
        stale = [k for k in self._trajectories if k not in active_ids]
        for k in stale[:20]:  # Cap cleanup per frame
            snapshot = self._track_last_snapshot.get(k)
            if snapshot is not None and snapshot["histogram"] is not None:
                self.continuity_guard.remember_lost(
                    k, snapshot["histogram"], snapshot["centroid"],
                    self._trajectories.get(k, []), time.time(),
                )
            else:
                # Nothing usable to re-match against later — forget now
                # rather than leak state waiting for a match that can't happen.
                self.track_feature_tracker.forget(k)
            del self._trajectories[k]
            self._known_track_ids.discard(k)
            self._track_last_snapshot.pop(k, None)

        # === Layer 3.6: Night-Motion Fallback (architecture v4 §3) ===
        # NightMotionFallback existed in edge/detection/detector.py but was
        # never called from anywhere — dead code until this change. Only
        # checked on frames we actually ran inference on (skipping this on
        # an Adaptive-Compute-Gate-skipped frame would be redundant: that
        # gate already agreed no motion was present via a different signal)
        # and only when YOLO found nothing at all — this is explicitly a
        # fallback for when the detector has no answer, not a second opinion
        # on top of a real detection.
        if (
            run_inference
            and condition.condition == SceneCondition.LOW_LIGHT_NIGHT
            and not tracks
            and self.night_motion_fallback.detect_motion(frame)
            and (time.time() - self._last_night_motion_emit_time) >= NIGHT_MOTION_COOLDOWN_SECONDS
        ):
            self._last_night_motion_emit_time = time.time()
            movement_reliability = make_uncertain(condition.condition, confidence=0.0, threshold=calibrated_threshold)
            movement_event = {
                "event_type": EventType.MOVEMENT_UNCLASSIFIED,
                "zone_id": self._default_zone_id,
                "track_id": None,
                "detection_class": DetectionClass.UNKNOWN,
                "confidence": 0.0,
                "severity": determine_severity(
                    {"event_type": EventType.MOVEMENT_UNCLASSIFIED}, movement_reliability
                ).value,
            }
            # Emitted directly, NOT through the Event Verifier: an UNCERTAIN
            # decision_state can never satisfy the verifier's confirmation
            # requirement (it only counts DETECTED frames), so routing this
            # through submit_candidate would silently produce zero evidence,
            # defeating the entire point of surfacing it. The cooldown above
            # is this path's own, simpler debounce instead.
            self._emit_event(
                track=None, reliability=movement_reliability, health=health, condition=condition,
                zone_id=self._default_zone_id, overrides=movement_event, frame=frame,
            )
            logger.info("[Pipeline] Night-motion fallback: unclassified movement detected, UNCERTAIN evidence emitted")

        # === Layer 4: Task Modules -> Layer 4.5: Event Verification ===
        # A task module firing is only a CANDIDATE (architecture v4 §9).
        # Evidence is packaged and an alert raised only once the Event
        # Verifier promotes a candidate to VERIFIED/ALERTED — see
        # edge/temporal/event_verifier.py. This is the concrete mechanism
        # that stops a single noisy frame from becoming a security alert.
        tick = self._verify_tick
        observed_keys_this_tick: set = set()
        now = time.time()

        def temporal_score_for(track) -> float:
            """T input to the Hybrid Reliability Engine. Neutral (1.0) when
            there's no track to compute it from — e.g. an abandoned-object
            event whose track has already disappeared by the time it fires."""
            if track is None:
                return 1.0
            return self.track_feature_tracker.compute(track.track_id, track.trajectory, now)

        def submit_candidate(event_dict: dict, reliability, track) -> None:
            event_type = event_dict["event_type"]
            event_type_value = event_type.value if hasattr(event_type, "value") else str(event_type)
            zone_id = event_dict.get("zone_id", self._default_zone_id)
            key = EventVerifier.make_key(self.camera_id, event_dict.get("track_id"), event_type_value, zone_id)
            observed_keys_this_tick.add(key)
            _state, verified_payload = self.event_verifier.observe(
                key, event_type_value, event_dict, tick,
                reliability.decision_state == DecisionState.DETECTED,
            )
            if verified_payload is not None:
                verified_payload["severity"] = determine_severity(verified_payload, reliability).value
                self._emit_event(track, reliability, health, condition,
                                 zone_id=verified_payload.get("zone_id", self._default_zone_id),
                                 overrides=verified_payload, frame=frame)

        # Real pixel dimensions of THIS frame — zone polygons (fence, line,
        # loitering, checkpoint, verification) are authored in normalized
        # 0-1 coordinates (see edge/rules/modules.py::normalize_point); this
        # is what makes that comparison actually correct regardless of the
        # camera's resolution, instead of comparing raw pixels against an
        # undefined unit.
        frame_height, frame_width = frame.shape[:2]

        # Run behavior module (operates on all active tracks)
        behavior_events = self.behavior_module.update(tracks, frame_width, frame_height)
        for be in behavior_events:
            track = next((t for t in tracks if t.track_id == be.get("track_id")), None)
            conf = be.get("confidence", 0.0)
            reliability = make_reliability_decision(
                health, condition, conf, calibrated_threshold,
                temporal_score=temporal_score_for(track),
            )
            submit_candidate(be, reliability, track)

        for track in tracks:
            # Fence crossing
            fence_event = self.fence_module.check(track, frame_width, frame_height)
            if fence_event:
                reliability = make_reliability_decision(
                    health, condition, track.confidence, calibrated_threshold,
                    temporal_score=temporal_score_for(track),
                )
                submit_candidate(fence_event, reliability, track)

            # Line crossing
            line_event = self.line_module.check(track, frame_width, frame_height)
            if line_event:
                reliability = make_reliability_decision(
                    health, condition, track.confidence, calibrated_threshold,
                    temporal_score=temporal_score_for(track),
                )
                submit_candidate(line_event, reliability, track)

            # ANPR
            anpr_result = self.anpr_module.process(track, frame)
            if anpr_result:
                reliability = make_reliability_decision(
                    health, condition, track.confidence, calibrated_threshold,
                    temporal_score=temporal_score_for(track),
                )
                submit_candidate(anpr_result, reliability, track)

            # Face detection
            face_result = self.face_module.detect(track, frame)
            if face_result:
                reliability = make_reliability_decision(
                    health, condition, track.confidence, calibrated_threshold,
                    temporal_score=temporal_score_for(track),
                )
                submit_candidate(face_result, reliability, track)

        # Re-check candidates awaiting >1 confirmation (fence crossing, line
        # crossing) that were NOT touched above this tick — i.e. the task
        # module fired once on a past frame at the crossing transition and
        # is now silent, but the track may still be on the new side and
        # needs re-confirming on subsequent frames.
        active_by_track_id = {t.track_id: t for t in tracks}
        for key, payload in self.event_verifier.get_pending_by_type("VIRTUAL_FENCE_CROSSING"):
            if key in observed_keys_this_tick:
                continue
            track = active_by_track_id.get(payload.get("track_id"))
            if track is None:
                continue  # track lost — expire_stale() below will age this out
            expected_inside = str(payload.get("direction", "")).endswith("OUTSIDE_TO_RESTRICTED")
            if self.fence_module.get_track_zone(track.track_id, payload.get("zone_id", self._default_zone_id)) != expected_inside:
                continue  # bounced back before confirmation — do not reconfirm
            reliability = make_reliability_decision(
                health, condition, track.confidence, calibrated_threshold,
                temporal_score=temporal_score_for(track),
            )
            submit_candidate(dict(payload), reliability, track)

        for key, payload in self.event_verifier.get_pending_by_type("LINE_CROSSING"):
            if key in observed_keys_this_tick:
                continue
            track = active_by_track_id.get(payload.get("track_id"))
            if track is None:
                continue  # track lost — expire_stale() below will age this out
            expected_side = -1 if str(payload.get("direction", "")).endswith("A_TO_B") else 1
            if self.line_module.get_track_side(track.track_id, payload.get("zone_id", self._default_zone_id)) != expected_side:
                continue  # bounced back before confirmation — do not reconfirm
            reliability = make_reliability_decision(
                health, condition, track.confidence, calibrated_threshold,
                temporal_score=temporal_score_for(track),
            )
            submit_candidate(dict(payload), reliability, track)

        self.event_verifier.expire_stale(tick)

        # --- Performance instrumentation: frame complete ---
        t_frame_end = time.perf_counter()
        self.metrics.record_frame(
            health_condition_ms=(t_health_condition - t_frame_start) * 1000.0,
            detection_tracking_ms=(t_detection_tracking - t_health_condition) * 1000.0,
            event_processing_ms=(t_frame_end - t_detection_tracking) * 1000.0,
            total_frame_ms=(t_frame_end - t_frame_start) * 1000.0,
        )

    def _emit_event(self, track, reliability, health, condition, zone_id, overrides, frame) -> None:
        """Package and enqueue an event for sync."""
        t_start = time.perf_counter()
        try:
            ep, seq_num = self.packager.package(
                track=track,
                reliability=reliability,
                health=health,
                condition=condition,
                zone_id=zone_id,
                event_overrides=overrides,
                frame=frame,
            )
            t_packaged = time.perf_counter()
            self.sync_client.enqueue(ep, seq_num)
            t_enqueued = time.perf_counter()

            # --- Performance instrumentation: decision-to-enqueue latency ---
            timing = dict(getattr(self.packager, "last_timing", {}))
            timing["enqueue_ms"] = (t_enqueued - t_packaged) * 1000.0
            timing["total_event_ms"] = (t_enqueued - t_start) * 1000.0
            self.metrics.record_event(**{
                k: v for k, v in timing.items() if k in PipelineMetrics.EVENT_STAGES
            })

            logger.info(
                f"[Pipeline] Event {ep.event_id[:8]}... "
                f"decision={ep.decision_state} "
                f"seq={seq_num} "
                f"queue_depth={self.sync_client.get_queue_depth()} "
                f"latency={timing['total_event_ms']:.1f}ms"
            )
        except Exception as exc:
            logger.error(f"[Pipeline] Failed to emit event: {exc}")

    def _report_metrics(self) -> None:
        """
        Log and persist the real, locally-measured pipeline performance
        summary (architecture v4 §15). Every number here comes from an
        actual perf_counter() reading taken during this run — nothing in
        this method is estimated or invented.
        """
        self.metrics.sample_resources()
        summary = self.metrics.summary()
        fr = summary["frames"]["total_frame_ms"]
        ev = summary["events"]["total_event_ms"]
        gate_stats = self.adaptive_gate.get_stats()
        logger.info(
            f"[Metrics] fps={summary['fps']:.1f} "
            f"frame_mean={fr['mean_ms']:.1f}ms frame_p95={fr['p95_ms']:.1f}ms (n={fr['count']}) "
            f"event_mean={ev['mean_ms']:.1f}ms event_p95={ev['p95_ms']:.1f}ms (n={ev['count']}) "
            f"alerts={summary['alerts_generated']} "
            f"cpu={summary['cpu_percent']} rss_mb={summary['rss_mb']} "
            f"gate={gate_stats['state']} inference_skip_ratio={gate_stats['skip_ratio']:.1%} "
            f"(run={gate_stats['frames_run']},skipped={gate_stats['frames_skipped']})"
        )
        self.metrics.dump_json(self._metrics_json_path, extra={"adaptive_gate": gate_stats})

        # Push the same real summary to the backend (POST /system/metrics),
        # independent of local disk persistence above — before this, the
        # summary was written only to a local JSON file and never reached
        # the backend at all, so the Performance dashboard page had nothing
        # to show. Best-effort, same posture as _report_camera_health: a
        # failed POST here must never interrupt the frame loop, and this is
        # NOT routed through the offline sync queue — it's a heartbeat, not
        # evidence.
        try:
            import httpx
            httpx.post(
                f"{self.sync_client.backend_url}/system/metrics",
                json={
                    "edge_device_id": self.camera_id,
                    "uptime_seconds": summary["uptime_seconds"],
                    "fps": summary["fps"],
                    "frames": summary["frames"],
                    "events": summary["events"],
                    "alerts_generated": summary["alerts_generated"],
                    "cpu_percent": summary["cpu_percent"],
                    "rss_mb": summary["rss_mb"],
                    "psutil_available": summary["psutil_available"],
                    "adaptive_gate": gate_stats,
                },
                timeout=3.0,
            )
        except Exception as exc:
            logger.debug(f"[Metrics] Backend report failed (non-fatal): {exc}")

    def stop(self) -> None:
        self._running = False


def run_edge(config_path: Optional[str] = None) -> None:
    """CLI entry point: load config and run the edge pipeline."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )

    # Load config
    config = {}
    if config_path and os.path.exists(config_path):
        with open(config_path) as f:
            config = json.load(f)
    else:
        # Default config from environment
        config = {
            "camera_id": os.environ.get("EDGE_DEVICE_ID", "edge-001"),
            "video_source": os.environ.get("VIDEO_SOURCE", "0"),
            "backend_url": os.environ.get("BACKEND_URL", "http://localhost:8443"),
            "auth_token": os.environ.get("EDGE_AUTH_TOKEN", ""),
            "simulate_frozen": os.environ.get("SIMULATE_FROZEN_CAMERA", "").lower() == "true",
            "simulate_night": os.environ.get("SIMULATE_NIGHT_CONDITION", "").lower() == "true",
            "zones_config_path": os.environ.get("ZONES_CONFIG_PATH", "demo/scripts/zones_config.json"),
            "key_dir": "certs/edge",
            "chain_db_path": "edge/data/chain.db",
            "sync_db_path": "edge/data/sync.db",
            "clip_dir": "edge/data/clips",
        }

    pipeline = EdgePipeline(config)
    pipeline.start()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="NETRAKSH Edge Pipeline")
    parser.add_argument("--config", help="Path to edge config JSON")
    args = parser.parse_args()
    run_edge(args.config)
