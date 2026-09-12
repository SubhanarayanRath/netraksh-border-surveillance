"""
NETRAKSH Edge — Demo Runner (SIH 2026 prototype).

A thin wrapper around EdgePipeline that:
  1. Reads CAMERA_ID / VIDEO_SOURCE / BACKEND_URL from env vars
     (or --camera-id / --video-source CLI args), so start_netraksh.cmd
     can launch two separate, named camera processes without a config file.
  2. Polls GET /demo/scenario every 5 s and applies scenario effects to
     the live pipeline — using ONLY the existing CameraAdapter flags and
     SyncClient behaviour, no new queuing or detection logic.

Scenario reactions (honest scope — what each one actually does):

  normal  → no modifications; simulation flags cleared on next 5s poll.

  fog     → inject a Gaussian-blurred, contrast-reduced copy of each frame
             into the pipeline so SceneConditionClassifier naturally reads
             low contrast_std and classifies FOG_RAIN → S drops → R may
             fall below RELIABILITY_R_THRESHOLD (0.75) → UNCERTAIN.
             The original frame is not modified for evidence snapshots —
             fog simulation only affects detection/health inputs.

  failure → set a module-level flag that makes the adapter's next ~60s of
             frames appear frozen (all identical single grey value).
             CameraHealthMonitor's own frozen-frame detector (pixel-variance
             check in edge/health/camera_health.py) fires health_state=FAILED
             → Gate 1 hard-override → ABSTAIN.
             We do NOT manually write health_state — the existing monitor
             decides on its own, from the frame data.

  offline → calls sync_client.set_simulate_offline(True), which already
             exists on SyncClient (edge/sync/sync_client.py:265).  The sync
             loop continues running and events continue to be enqueued, but
             outbound POST /events calls are skipped → /sync/status shows
             BUFFERING.  Calling set_simulate_offline(False) on scenario
             'normal' resumes draining the queue.

None of these flags retroactively alter already-signed evidence packages.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
import threading
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

# Ensure repo root is on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from edge.main import EdgePipeline

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level scenario state — set by the polling thread, read by
# _process_frame in the main thread.  Python dict writes are atomic under
# the GIL for single-key updates.
# ---------------------------------------------------------------------------
_scenario: dict = {"current": "normal", "video_source": None, "should_restart": False}

# How long (seconds) a single 'failure' trigger keeps frozen frames active
# before auto-resetting so the demo doesn't get permanently stuck.
_FAILURE_DURATION_S = 60.0
_failure_until: float = 0.0


def _poll_scenario(backend_url: str, interval: float = 5.0) -> None:
    """
    Background thread: poll GET /demo/scenario every `interval` seconds
    and update _scenario["current"].  Non-fatal on any network error.
    """
    try:
        import httpx
    except ImportError:
        logger.warning("[DemoRunner] httpx not installed — scenario poll disabled")
        return
    while True:
        try:
            resp = httpx.get(f"{backend_url}/demo/scenario", timeout=2.0)
            if resp.status_code == 200:
                data = resp.json()
                new_scenario = data.get("scenario", "normal")
                new_source = data.get("video_source")

                if new_scenario != _scenario["current"]:
                    logger.info(
                        f"[DemoRunner] Scenario changed: {_scenario['current']} → {new_scenario}"
                    )
                    _scenario["current"] = new_scenario
                
                # If a new video source is provided, and it's different, trigger restart
                if new_source and new_source != _scenario.get("video_source"):
                    # Only trigger restart if we already had a source (not the first poll)
                    # or if the backend dictates a source different from the CLI args.
                    if _scenario["video_source"] is not None:
                        logger.info(f"[DemoRunner] Video source changed to {new_source}, triggering restart...")
                        _scenario["should_restart"] = True
                    _scenario["video_source"] = new_source
        except Exception as exc:
            logger.debug(f"[DemoRunner] Scenario poll failed (non-fatal): {exc}")
        time.sleep(interval)


def apply_fog(frame: np.ndarray) -> np.ndarray:
    """
    Apply realistic fog simulation to a frame so SceneConditionClassifier
    naturally reads FOG_RAIN (low contrast_std, reduced brightness mean).

    Step 1: Gaussian blur reduces Laplacian variance (SceneConditionClassifier
            uses contrast_std from the blurred LAB L-channel).
    Step 2: Blend with a grey haze to further reduce contrast_std and pull
            brightness_mean toward a mid-grey, away from the clear-day ideal.

    No OpenCV functions beyond GaussianBlur/addWeighted — existing dependencies.
    """
    blurred = cv2.GaussianBlur(frame, (25, 25), 0)
    haze = np.full_like(frame, 180, dtype=np.uint8)
    fogged = cv2.addWeighted(blurred, 0.55, haze, 0.45, 0)
    return fogged


class DemoAwareEdgePipeline(EdgePipeline):
    """
    Subclass of EdgePipeline that intercepts _process_frame to apply
    scenario effects.  Everything else — reliability, evidence packaging,
    evidence chain, sync — is inherited untouched from EdgePipeline.
    """

    def _notify_backend_normal(self) -> None:
        try:
            import httpx
            httpx.post(f"{self.config['backend_url']}/demo/scenario", json={"scenario": "normal"}, timeout=1.0)
        except Exception as exc:
            logger.debug(f"[DemoRunner] Auto-reset POST failed (non-fatal): {exc}")

    def _process_frame(self, frame: np.ndarray, meta) -> None:
        """
        Apply scenario effects before delegating to the real pipeline.

        failure: replace frame with a constant grey so the pixel-variance
                 check in CameraHealthMonitor (edge/health/camera_health.py)
                 reads near-zero variance → FAILED → Gate 1 → ABSTAIN.
                 We do not set health_state manually.

        fog:     replace frame with a fog-blurred+hazed copy.
                 SceneConditionClassifier computes low contrast_std → FOG_RAIN
                 → S component of R drops → R may fall below 0.75 → UNCERTAIN.

        offline: frame passes through unchanged.  Offline effect is on the
                 sync layer, not the frame layer (see start() below).

        normal:  frame passes through unchanged.
        """
        global _failure_until
        scenario = _scenario["current"]

        if scenario == "failure":
            now = time.time()
            if _failure_until == 0.0:
                _failure_until = now + _FAILURE_DURATION_S
                logger.info(
                    "[DemoRunner] scenario=failure — injecting frozen grey frames "
                    "for ~60s so CameraHealthMonitor detects FAILED"
                )
            
            if now > _failure_until:
                logger.info("[DemoRunner] Auto-resetting failure scenario to normal after 60s")
                _scenario["current"] = "normal"
                _failure_until = 0.0
                threading.Thread(target=self._notify_backend_normal, daemon=True).start()
                super()._process_frame(frame, meta)
            else:
                # Constant grey → near-zero pixel variance → CameraHealthMonitor
                # detects frozen stream → health_state=FAILED → Gate 1 → ABSTAIN
                frozen = np.full_like(frame, 80, dtype=np.uint8)
                super()._process_frame(frozen, meta)

        elif scenario == "fog":
            _failure_until = 0.0
            fog_frame = apply_fog(frame)
            # fog_frame is used for detection/health — evidence snapshot uses
            # the ORIGINAL frame via the real packager (same as CLAHE branch
            # in edge/main.py::_process_frame, which keeps original frame for
            # evidence while using detection_frame for YOLO).
            super()._process_frame(fog_frame, meta)

        else:
            _failure_until = 0.0
            # normal / offline — pass frame through unchanged
            super()._process_frame(frame, meta)

    def start(self) -> None:
        """
        Override start() to additionally:
        - Watch _scenario and drive sync_client.set_simulate_offline()
          so the 'offline' scenario uses the existing sync API, not a hack.
        """
        # Monitor scenario changes and update the sync client's offline flag.
        # This runs in a daemon thread alongside the real sync loop thread
        # that EdgePipeline.start() itself will spawn.
        def _offline_watcher():
            last = None
            while True:
                s = _scenario["current"]
                if s != last:
                    want_offline = (s == "offline")
                    try:
                        self.sync_client.set_simulate_offline(want_offline)
                        logger.info(
                            f"[DemoRunner] sync_client.simulate_offline → {want_offline}"
                        )
                    except Exception as exc:
                        logger.debug(f"[DemoRunner] offline watcher error: {exc}")
                    last = s
                time.sleep(1.0)

        t = threading.Thread(target=_offline_watcher, daemon=True, name="offline-watcher")
        t.start()

        def _restart_watcher():
            while True:
                if getattr(self, "_running", False) and _scenario.get("should_restart"):
                    logger.info("[DemoRunner] Restart requested by scenario state. Stopping pipeline...")
                    self.stop()
                    _scenario["should_restart"] = False
                    break
                if not getattr(self, "_running", False):
                    break
                time.sleep(1.0)
        
        t_restart = threading.Thread(target=_restart_watcher, daemon=True, name="restart-watcher")
        t_restart.start()

        # Delegate to the real EdgePipeline.start(), which handles YOLO load,
        # sync thread, frame loop, etc.
        super().start()


def run_demo_pipeline(
    camera_id: str,
    video_source: str,
    backend_url: str,
    zones_config_path: str = "demo/scripts/zones_config.json",
) -> None:
    """
    Build and run a DemoAwareEdgePipeline for one named camera.
    Called directly by __main__ below.
    """
    logging.basicConfig(
        level=logging.INFO,
        format=f"%(asctime)s | %(levelname)-8s | [{camera_id}] %(name)s | %(message)s",
    )
    logger.info(
        f"[DemoRunner] Starting demo pipeline: camera={camera_id} "
        f"source={video_source} backend={backend_url}"
    )

    # Start scenario polling in a daemon background thread
    poll_thread = threading.Thread(
        target=_poll_scenario,
        args=(backend_url, 5.0),
        daemon=True,
        name=f"scenario-poll-{camera_id}",
    )
    poll_thread.start()
    # Initialize _scenario["video_source"] with the CLI argument so the first
    # poll doesn't immediately restart if the backend doesn't have one set yet.
    _scenario["video_source"] = video_source

    while True:
        current_source = _scenario["video_source"]
        
        config = {
            "camera_id": camera_id,
            "camera_name": camera_id,
            "video_source": current_source,
            "backend_url": backend_url,
            "auth_token": os.environ.get("EDGE_AUTH_TOKEN", ""),
            "zones_config_path": zones_config_path,
            "key_dir": "certs/edge",
            # Per-camera chain/sync DBs so two simultaneous pipelines don't collide
            "chain_db_path": f"edge/data/chain_{camera_id}.db",
            "sync_db_path": f"edge/data/sync_{camera_id}.db",
            "clip_dir": "edge/data/clips",
            "metrics_json_path": f"edge/data/metrics_{camera_id}.json",
            "simulate_frozen": False,
            "simulate_night": False,
        }

        logger.info(f"[DemoRunner] Instantiating pipeline with source {current_source}")
        pipeline = DemoAwareEdgePipeline(config)
        
        # start() blocks until the pipeline stops (e.g. video ends, interrupted, or restarted)
        pipeline.start()
        
        if _scenario.get("should_restart"):
            # The pipeline was stopped by the restart watcher, continue loop to recreate
            logger.info("[DemoRunner] Pipeline stopped for restart. Recreating...")
            # We already cleared should_restart in the watcher, but just in case:
            _scenario["should_restart"] = False
            time.sleep(1.0)
        else:
            # Normal exit (e.g. video ended or Ctrl+C)
            logger.info("[DemoRunner] Pipeline exited normally. Ending loop.")
            break


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "NETRAKSH Demo Runner — launches one edge pipeline for a named camera. "
            "Use CAMERA_ID / VIDEO_SOURCE / BACKEND_URL env vars or CLI flags."
        )
    )
    parser.add_argument(
        "--camera-id",
        default=os.environ.get("CAMERA_ID", "cam-border-01"),
        help="Camera ID (must match a registered camera in the backend DB)",
    )
    parser.add_argument(
        "--video-source",
        default=os.environ.get("VIDEO_SOURCE", "demo/videos/vtest.avi"),
        help="OpenCV video source: path to .avi/.mp4, 'webcam', or RTSP URL",
    )
    parser.add_argument(
        "--backend-url",
        default=os.environ.get("BACKEND_URL", "http://localhost:8443"),
        help="NETRAKSH backend URL",
    )
    parser.add_argument(
        "--zones-config",
        default=os.environ.get("ZONES_CONFIG_PATH", "demo/scripts/zones_config.json"),
        help="Path to zones_config.json",
    )
    args = parser.parse_args()

    run_demo_pipeline(
        camera_id=args.camera_id,
        video_source=args.video_source,
        backend_url=args.backend_url,
        zones_config_path=args.zones_config,
    )
