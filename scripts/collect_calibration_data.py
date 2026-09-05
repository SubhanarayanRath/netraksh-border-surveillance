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

Usage:
    python scripts/collect_calibration_data.py \\
        --video demo/videos/vtest.avi \\
        --zone-x1 0.456 --zone-y1 0.260 --zone-x2 1.0 --zone-y2 0.521 \\
        --out-dir scripts/calibration_data
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
from edge.temporal.track_features import TrackFeatureTracker
from shared.constants import CameraHealthState
from shared.schemas import Point, Polygon, ZoneSchema


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
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    snapshots_dir = out_dir / "snapshots"
    snapshots_dir.mkdir(parents=True, exist_ok=True)

    zone = build_zone(args.zone_x1, args.zone_y1, args.zone_x2, args.zone_y2)

    cap = cv2.VideoCapture(args.video)
    if not cap.isOpened():
        raise SystemExit(f"Could not open video: {args.video}")

    health_monitor = CameraHealthMonitor(camera_id="benchmark", fps_declared=cap.get(cv2.CAP_PROP_FPS) or 25.0)
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

    while True:
        ok, frame = cap.read()
        if not ok:
            break
        frame_idx += 1
        frame_height, frame_width = frame.shape[:2]

        health = health_monitor.update(frame, time.time())
        condition = condition_classifier.classify(frame)
        if health.health_state == CameraHealthState.FAILED:
            continue

        threshold = calibration.get_threshold(condition.condition)
        try:
            tracks = detector.detect_and_track(frame, condition.condition, threshold, existing_trajectories=trajectories)
        except Exception as exc:
            print(f"[frame {frame_idx}] detector error: {exc}", file=sys.stderr)
            tracks = []

        for t in tracks:
            trajectories[t.track_id] = t.trajectory

        for track in tracks:
            fence_event = fence_module.check(track, frame_width, frame_height)
            if not fence_event:
                continue

            # The exact same 4 real feature values
            # edge/reliability/decision.py::make_reliability_decision computes
            # for this candidate — imported directly, not reimplemented, so
            # this is guaranteed to match what the real pipeline would score.
            d = max(0.0, min(1.0, track.confidence))
            t_score = track_feature_tracker.compute(track.track_id, track.trajectory, time.time())
            s = _scene_quality_score(condition)
            h = _health_quality_score(health)

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
                "S": round(s, 4),
                "H": round(h, 4),
                "snapshot": str(snapshot_path.relative_to(out_dir)),
                "label": None,  # filled in later by manual review — see fit_reliability_weights.py
            })
            print(f"  {candidate_id}: frame={frame_idx} track={track.track_id} D={d:.2f} T={t_score:.2f} S={s:.2f} H={h:.2f}")

    cap.release()
    wall_seconds = time.perf_counter() - t_start

    manifest = {
        "video": args.video,
        "zone": {"x1": args.zone_x1, "y1": args.zone_y1, "x2": args.zone_x2, "y2": args.zone_y2},
        "frames_processed": frame_idx,
        "candidate_count": len(candidates),
        "wall_seconds": round(wall_seconds, 2),
        "candidates": candidates,
    }
    manifest_path = out_dir / "manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"\n{len(candidates)} real candidates collected.")
    print(f"Manifest: {manifest_path}")
    print(f"Snapshots: {snapshots_dir}/")
    print("\nNext: manually review each snapshot and fill in 'label' (1=real crossing, 0=false positive)")
    print("in the manifest, then run scripts/fit_reliability_weights.py.")


if __name__ == "__main__":
    main()
