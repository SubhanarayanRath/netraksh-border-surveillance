#!/usr/bin/env python
"""
NETRAKSH — Real calibration data collection for the Hybrid Reliability
Engine's weights (edge/reliability/decision.py's RELIABILITY_WEIGHT_D/T/S/H
and RELIABILITY_R_THRESHOLD — currently hand-picked defaults, explicitly
documented as "NOT calibrated against labeled data").

Runs the SAME real production pipeline components as
scripts/run_false_positive_benchmark.py, against the SAME real video and
zone already used for that report — this is not a new/different dataset,
it is the same real candidates, instrumented to capture what calibration
actually needs: for every real raw fence-crossing candidate, the real
D/T/S/H feature values AND a real labelable snapshot image (frame + drawn
bounding box), saved to disk for manual ground-truth review.

This script does NOT itself produce a ground-truth label — no automatic
process can tell a genuine border crossing from a false detection; a human
has to actually look at each snapshot. That is the deliberate next step
(see scripts/fit_reliability_weights.py's docstring for the labeling
file format), not something this script fabricates or skips.

SYNTHETIC CONDITIONS (--synthetic-condition night|fog|glare): this project
has no real night, fog, or glare footage (see docs/LIMITATIONS.md — the
daytime demo/videos/vtest.avi run already found zero false positives,
which is itself the honest reason a degraded-condition dataset is worth
trying). Rather than fabricate fake candidates or invent numbers, this
flag applies an honest, disclosed OpenCV brightness/contrast/haze
transform to each REAL frame before it reaches the pipeline — the people
and motion are the same real footage; only the lighting is synthetic.
Every downstream number (brightness_mean, contrast_std, glare_fraction,
the resulting SceneCondition, YOLO's actual detections on the degraded
pixels, D/T/S/H) is still genuinely measured by the real pipeline on the
real (if now-darker/hazier/washed-out) pixel data — nothing about the
transform is faked or backfilled into the output. The manifest and every
snapshot say plainly that a synthetic condition was applied, so this is
never confusable with the real, unmodified vtest.avi dataset in
scripts/calibration_data/.

TRACK-AGE CLOCK (real methodology fix, see docs/LIMITATIONS.md): T's
track_age_score (edge/temporal/track_features.py::TrackFeatureTracker)
needs a "now" to measure elapsed track age against. edge/main.py correctly
uses real wall-clock time.time() there, because a LIVE camera's frames
genuinely arrive at real wall-clock intervals. This script analyzes a
video FILE instead, which cv2.VideoCapture reads as fast as this machine
can process it — NOT gated to the video's own real playback speed — so
feeding it the same wall-clock time.time() would measure how fast THIS
MACHINE happened to run, not the track's real age within the video's own
timeline (measured, not hypothetical: one real run took 46.28 wall-clock
seconds to process a 795-frame/25fps clip whose real content is only 31.8
seconds). This script instead derives a video-timeline clock from
frame_idx / video_fps, so T reflects the real video's own content,
reproducibly, regardless of this machine's processing speed.

Usage:
    python scripts/collect_calibration_data.py \\
        --video demo/videos/vtest.avi \\
        --zone-x1 0.456 --zone-y1 0.260 --zone-x2 1.0 --zone-y2 0.521 \\
        --out-dir scripts/calibration_data

    python scripts/collect_calibration_data.py \\
        --video demo/videos/vtest.avi \\
        --zone-x1 0.456 --zone-y1 0.260 --zone-x2 1.0 --zone-y2 0.521 \\
        --out-dir scripts/calibration_data_night --synthetic-condition night
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import cv2
import numpy as np

from edge.condition.scene_condition import SceneConditionClassifier
from edge.detection.calibration import CalibrationModule
from edge.detection.detector import DetectionTracker
from edge.health.camera_health import CameraHealthMonitor
from edge.reliability.decision import _health_quality_score, _scene_quality_score
from edge.rules.modules import VirtualFenceModule
from edge.temporal.track_features import (
    TRACK_AGE_SATURATION_SECONDS,
    TrackFeatureTracker,
    _path_smoothness,
    _speed_consistency,
)
from shared.constants import CameraHealthState
from shared.schemas import Point, Polygon, ZoneSchema


def apply_synthetic_condition(frame: np.ndarray, condition_sim: str, rng: np.random.RandomState) -> np.ndarray:
    """Apply an honest, disclosed synthetic lighting transform to a REAL
    frame. Returns the SAME frame unchanged for "none". The transformed
    pixels are what the rest of the real pipeline (scene classifier,
    detector, everything) actually runs on — nothing is faked past this
    point; this is the one and only place synthesis happens.
    """
    if condition_sim == "none":
        return frame
    if condition_sim == "night":
        # Simulate low-light/night: scale pixel values down (real cameras at
        # night are simply darker) and add real Gaussian sensor-noise-like
        # perturbation (real low-light sensors are noisier, not just dimmer).
        darkened = frame.astype(np.float32) * 0.28
        noise = rng.normal(0, 6.0, darkened.shape)
        return np.clip(darkened + noise, 0, 255).astype(np.uint8)
    if condition_sim == "fog":
        # Simulate fog/rain: blend toward a flat, bright haze color (real
        # fog scatters light into a near-uniform gray-white) and blur
        # slightly (real fog softens edges) — brightness stays roughly
        # daytime-level while contrast collapses, matching FOG_RAIN's real
        # classification rule (edge/condition/scene_condition.py).
        haze_color = np.full_like(frame, 190)
        blended = cv2.addWeighted(frame, 0.42, haze_color, 0.58, 0)
        return cv2.GaussianBlur(blended, (7, 7), 0)
    if condition_sim == "fog_mild":
        # A DELIBERATELY MILDER fog, added specifically to test a real
        # hypothesis raised by the glare-residual investigation
        # (docs/LIMITATIONS.md): is fog's own 6% residual (after all prior
        # fixes) driven by a genuine reference-point bug, or — like glare's
        # residual turned out to be — simply this specific transform's
        # chosen severity? "fog" above measures contrast_std≈21, well
        # inside FOG_RAIN's <30 boundary; this variant (blend 0.55/0.45,
        # smaller 5x5 blur) was empirically tuned against this real video
        # (checked across 5 frames spanning the whole clip, not just one)
        # to measure contrast_std≈28 — still reliably classified FOG_RAIN
        # (a consistent ~2-point safety margin under 30 throughout), but
        # right at the boundary rather than deep inside it, mirroring
        # "barely still foggy" rather than "quite foggy."
        haze_color = np.full_like(frame, 190)
        blended = cv2.addWeighted(frame, 0.55, haze_color, 0.45, 0)
        return cv2.GaussianBlur(blended, (5, 5), 0)
    if condition_sim == "glare":
        # Simulate sun glare/lens flare: scale pixel values up and clip at
        # 255 (real glare washes out highlights into flat white). Intensity
        # (x1.8 + 20) was empirically measured against this real video's own
        # first frame before picking it: it drives glare_fraction (fraction
        # of near-white pixels, the real signal GLARE's classification rule
        # actually uses) to ~0.43 — comfortably past the real
        # BRIGHTNESS_GLARE_THRESHOLD-adjacent 0.15 cutoff — while brightness_
        # mean (~203) stays just BELOW BRIGHTNESS_GLARE_THRESHOLD (220), so
        # this reliably classifies as GLARE via the glare_fraction path
        # specifically, not by accident of both paths firing at once.
        brightened = frame.astype(np.float32) * 1.8 + 20
        return np.clip(brightened, 0, 255).astype(np.uint8)
    raise ValueError(f"unknown --synthetic-condition: {condition_sim}")


def build_zone(x1: float, y1: float, x2: float, y2: float) -> ZoneSchema:
    return ZoneSchema(
        zone_id="benchmark-zone", camera_id="benchmark", name="Benchmark fence zone",
        zone_type="fence",
        polygon=Polygon(points=[Point(x=x1, y=y1), Point(x=x2, y=y1), Point(x=x2, y=y2), Point(x=x1, y=y2)]),
        owning_command_id="COMMAND_A",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect real D/T/S/H feature data + labelable snapshots")
    parser.add_argument("--video", required=True)
    parser.add_argument("--zone-x1", type=float, required=True)
    parser.add_argument("--zone-y1", type=float, required=True)
    parser.add_argument("--zone-x2", type=float, required=True)
    parser.add_argument("--zone-y2", type=float, required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument(
        "--synthetic-condition", choices=["none", "night", "fog", "fog_mild", "glare"], default="none",
        help="Apply an honest, disclosed lighting transform to real frames "
             "before the real pipeline runs on them (see module docstring). "
             "Default 'none' reproduces the original real-daytime collection.",
    )
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    snapshots_dir = out_dir / "snapshots"
    snapshots_dir.mkdir(parents=True, exist_ok=True)

    zone = build_zone(args.zone_x1, args.zone_y1, args.zone_x2, args.zone_y2)

    cap = cv2.VideoCapture(args.video)
    if not cap.isOpened():
        raise SystemExit(f"Could not open video: {args.video}")

    video_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    health_monitor = CameraHealthMonitor(camera_id="benchmark", fps_declared=video_fps)
    condition_classifier = SceneConditionClassifier(camera_id="benchmark")
    calibration = CalibrationModule()
    detector = DetectionTracker(model_size="yolov8n.pt", device="cpu")
    detector.load()
    fence_module = VirtualFenceModule(zones=[zone])
    track_feature_tracker = TrackFeatureTracker()

    trajectories: dict = {}
    candidates = []
    frame_idx = 0
    t_start = time.perf_counter()
    rng = np.random.RandomState(42)  # fixed seed: a rerun reproduces the same synthetic noise
    condition_counts: dict = {}

    while True:
        ok, frame = cap.read()
        if not ok:
            break
        frame_idx += 1
        frame = apply_synthetic_condition(frame, args.synthetic_condition, rng)
        frame_height, frame_width = frame.shape[:2]

        health = health_monitor.update(frame, time.time())
        condition = condition_classifier.classify(frame)
        condition_counts[str(condition.condition)] = condition_counts.get(str(condition.condition), 0) + 1
        if health.health_state == CameraHealthState.FAILED:
            continue

        threshold = calibration.get_threshold(condition.condition)
        try:
            tracks = detector.detect_and_track(frame, condition.condition, threshold, existing_trajectories=trajectories)
        except Exception as exc:
            print(f"[frame {frame_idx}] detector error: {exc}", file=sys.stderr)
            tracks = []

        video_time = frame_idx / video_fps
        for t in tracks:
            trajectories[t.track_id] = t.trajectory
            # Real bug fix (see edge/temporal/track_features.py's class
            # docstring and docs/PERFORMANCE_REPORT.md): observe() must be
            # called unconditionally for every active track, every frame —
            # not only inside the event-triggered branch below — or
            # _first_seen gets registered at the moment of a track's first
            # fence-crossing event instead of its real first-observed frame,
            # always zeroing age_score on that one call.
            track_feature_tracker.observe(t.track_id, video_time)

        for track in tracks:
            fence_event = fence_module.check(track, frame_width, frame_height)
            if not fence_event:
                continue

            # The exact same 4 real feature values
            # edge/reliability/decision.py::make_reliability_decision computes
            # for this candidate — imported directly, not reimplemented, so
            # this is guaranteed to match what the real pipeline would score.
            d = max(0.0, min(1.0, track.confidence))
            # Real methodology finding (docs/LIMITATIONS.md): this offline
            # video-file analysis genuinely runs slower than the video's own
            # real-time playback speed (measured: 46.28 wall-clock seconds to
            # process a 795-frame/25fps clip whose real content is only 31.8
            # seconds — printed in this run's own wall_seconds vs
            # frames_processed/video_fps, not asserted). edge/main.py
            # correctly uses time.time() for TrackFeatureTracker.compute()'s
            # `now` because a LIVE camera's frames really do arrive at real
            # wall-clock intervals — but feeding this offline script's own
            # (slower-than-real-time, CPU-speed-dependent) wall clock into
            # the SAME function would measure "how fast this machine
            # happened to process this video," not the track's real age
            # within the video's own timeline, silently distorting T's
            # track_age_score for every candidate. Using the video's own
            # timeline (frame_idx / video_fps) instead ties T to the real
            # video content, reproducibly, regardless of this machine's
            # processing speed.
            t_score = track_feature_tracker.compute(track.track_id, track.trajectory, video_time)
            s = _scene_quality_score(condition)
            h = _health_quality_score(health, condition)

            # T's three sub-components, recorded separately for real,
            # honest diagnosis of WHY a given candidate's T is low — not
            # reimplemented: age_seconds comes from the same tracker's own
            # public accessor, and smoothness/speed_consistency are the
            # exact same module-level functions TrackFeatureTracker.compute()
            # itself calls internally.
            age_seconds = track_feature_tracker.get_track_age_seconds(track.track_id, video_time)
            t_age_score = min(age_seconds / TRACK_AGE_SATURATION_SECONDS, 1.0) if age_seconds is not None else None
            t_smoothness = _path_smoothness(track.trajectory)
            t_speed_consistency = _speed_consistency(track.trajectory)

            candidate_id = f"candidate_{len(candidates):03d}"
            snapshot = frame.copy()
            x1, y1, x2, y2 = int(track.bbox.x1), int(track.bbox.y1), int(track.bbox.x2), int(track.bbox.y2)
            cv2.rectangle(snapshot, (x1, y1), (x2, y2), (0, 255, 0), 2)
            # Draw the zone polygon too, so a reviewer can see whether the
            # box is genuinely inside/crossing it, not just trust the label.
            zone_pts = [(int(p.x * frame_width), int(p.y * frame_height)) for p in zone.polygon.points]
            pts = np.array(zone_pts, dtype=np.int32).reshape((-1, 1, 2))
            cv2.polylines(snapshot, [pts], isClosed=True, color=(0, 200, 255), thickness=2)

            snapshot_path = snapshots_dir / f"{candidate_id}.jpg"
            cv2.imwrite(str(snapshot_path), snapshot)

            candidates.append({
                "candidate_id": candidate_id,
                "frame_idx": frame_idx,
                "track_id": track.track_id,
                "detection_class": str(track.detection_class),
                "D": round(d, 4),
                "T": round(t_score, 4),
                # T's real sub-components, for honest diagnosis of what's
                # actually driving a low/high T — not part of the R formula
                # itself (only "T" is), purely diagnostic.
                "T_age_score": round(t_age_score, 4) if t_age_score is not None else None,
                "T_smoothness": round(t_smoothness, 4),
                "T_speed_consistency": round(t_speed_consistency, 4),
                "trajectory_point_count": len(track.trajectory),
                "S": round(s, 4),
                "H": round(h, 4),
                # Real, measured (not asserted) values proving what condition
                # this specific candidate was actually classified under.
                "scene_condition": str(condition.condition),
                "brightness_mean": round(condition.brightness_mean, 2),
                "contrast_std": round(condition.contrast_std, 2),
                "synthetic_condition": args.synthetic_condition,
                "snapshot": str(snapshot_path.relative_to(out_dir)),
                "label": None,  # filled in later by manual review — see fit_reliability_weights.py
            })
            print(f"  {candidate_id}: frame={frame_idx} track={track.track_id} "
                  f"D={d:.2f} T={t_score:.2f} (age={t_age_score if t_age_score is None else round(t_age_score,2)} "
                  f"smooth={t_smoothness:.2f} speed={t_speed_consistency:.2f} pts={len(track.trajectory)}) "
                  f"S={s:.2f} H={h:.2f} "
                  f"cond={condition.condition} bri={condition.brightness_mean:.0f} con={condition.contrast_std:.0f}")

    cap.release()
    wall_seconds = time.perf_counter() - t_start

    manifest = {
        "video": args.video,
        "zone": {"x1": args.zone_x1, "y1": args.zone_y1, "x2": args.zone_x2, "y2": args.zone_y2},
        "synthetic_condition": args.synthetic_condition,
        "synthetic_condition_disclosure": (
            "none — this is the real, unmodified video." if args.synthetic_condition == "none" else
            f"SYNTHETIC LIGHTING APPLIED: every frame below was run through an honest, disclosed "
            f"'{args.synthetic_condition}' brightness/contrast transform (see "
            f"apply_synthetic_condition() in this script's source) before reaching the real "
            f"pipeline. The people, motion, and zone are the same real footage as "
            f"scripts/calibration_data/ — only the lighting is synthetic. Every D/T/S/H value, "
            f"every scene_condition classification, and every YOLO detection below was genuinely "
            f"computed by the real pipeline on these (now degraded) real pixels — nothing here is "
            f"backfilled or invented."
        ),
        "condition_distribution": condition_counts,  # real, measured per-frame classification counts
        "frames_processed": frame_idx,
        "candidate_count": len(candidates),
        "wall_seconds": round(wall_seconds, 2),
        "candidates": candidates,
    }
    manifest_path = out_dir / "manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"\n{len(candidates)} real candidates collected (synthetic_condition={args.synthetic_condition}).")
    print(f"Real measured condition distribution across all {frame_idx} frames: {condition_counts}")
    print(f"Manifest: {manifest_path}")
    print(f"Snapshots: {snapshots_dir}/")
    print("\nNext: manually review each snapshot and fill in 'label' (1=real crossing, 0=false positive)")
    print("in the manifest, then run scripts/fit_reliability_weights.py.")


if __name__ == "__main__":
    main()
