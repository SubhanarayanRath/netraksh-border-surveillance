"""
NETRAKSH Edge — YOLO + ByteTrack detection and tracking (Layer 3 / Gate 3).
Uses YOLOv8n for person/vehicle detection.
ByteTrack (via ultralytics) for multi-object tracking.
Confidence threshold is bucket-calibrated (not global).
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

from shared.constants import DecisionState, DetectionClass, SceneCondition
from shared.schemas import BoundingBox, Point, TrackData

logger = logging.getLogger(__name__)

# YOLO class ID mappings (COCO)
_YOLO_CLASS_MAP: Dict[int, DetectionClass] = {
    0: DetectionClass.PERSON,
    1: DetectionClass.PERSON,   # bicycle — treated as person for MVP
    2: DetectionClass.VEHICLE,  # car
    3: DetectionClass.VEHICLE,  # motorcycle
    5: DetectionClass.VEHICLE,  # bus
    7: DetectionClass.VEHICLE,  # truck
}

# Border-tuned ByteTrack config (architecture v4 §4 — Track Continuity Guard):
# same as ultralytics' bundled bytetrack.yaml except a larger track_buffer.
# Resolved as an absolute path so it works regardless of the process's CWD.
_DEFAULT_TRACKER_CONFIG = str(
    Path(__file__).resolve().parent.parent / "config" / "bytetrack_border.yaml"
)


class DetectionTracker:
    """
    Wraps Ultralytics YOLO (yolov8n) + ByteTrack.
    Returns tracked objects for each frame.
    """

    def __init__(
        self,
        model_size: str = "yolov8n.pt",
        device: str = "cpu",
        tracker_config: Optional[str] = None,
    ):
        self.model_size = model_size
        self.device = device
        # Falls back to the border-tuned config (edge/config/bytetrack_border.yaml)
        # if the given/default path doesn't exist, and further to ultralytics'
        # own bundled "bytetrack.yaml" if even that is missing — never silently
        # crashes the pipeline over a missing tracker config file.
        config = tracker_config or _DEFAULT_TRACKER_CONFIG
        if not os.path.exists(config):
            logger.warning(
                f"[Detector] Tracker config not found at {config}; "
                f"falling back to ultralytics' bundled bytetrack.yaml (default track_buffer)"
            )
            config = "bytetrack.yaml"
        self.tracker_config = config
        self._model = None
        self._fps_measurements: List[float] = []
        self._last_fps_report = time.time()

    def load(self) -> None:
        """Load YOLO model. Called once at startup."""
        try:
            from ultralytics import YOLO
            logger.info(f"[Detector] Loading {self.model_size} on {self.device}...")
            self._model = YOLO(self.model_size)
            # Warm up
            dummy = np.zeros((640, 640, 3), dtype=np.uint8)
            self._model.predict(dummy, verbose=False, device=self.device)
            logger.info("[Detector] Model loaded and warmed up")
        except Exception as exc:
            logger.error(f"[Detector] Failed to load model: {exc}")
            raise

    def detect_and_track(
        self,
        frame: np.ndarray,
        condition: SceneCondition,
        confidence_threshold: float,
        existing_trajectories: Optional[Dict[int, List[Point]]] = None,
    ) -> List[TrackData]:
        """
        Run YOLO inference + ByteTrack association.
        Returns a list of TrackData objects (one per tracked object).
        """
        if self._model is None:
            raise RuntimeError("Model not loaded. Call load() first.")

        t_start = time.perf_counter()

        try:
            results = self._model.track(
                frame,
                persist=True,
                conf=confidence_threshold,
                device=self.device,
                tracker=self.tracker_config,
                verbose=False,
                classes=list(_YOLO_CLASS_MAP.keys()),
            )
        except Exception as exc:
            logger.error(f"[Detector] Inference error: {exc}")
            return []

        t_end = time.perf_counter()
        elapsed = t_end - t_start
        self._fps_measurements.append(1.0 / elapsed if elapsed > 0 else 0)

        tracks: List[TrackData] = []
        if results and results[0].boxes is not None:
            boxes = results[0].boxes
            for i in range(len(boxes)):
                try:
                    cls_id = int(boxes.cls[i].item())
                    if cls_id not in _YOLO_CLASS_MAP:
                        continue
                    conf = float(boxes.conf[i].item())
                    if conf < confidence_threshold:
                        continue

                    track_id_tensor = boxes.id
                    track_id = int(track_id_tensor[i].item()) if track_id_tensor is not None else i

                    xyxy = boxes.xyxy[i].tolist()
                    bbox = BoundingBox(x1=xyxy[0], y1=xyxy[1], x2=xyxy[2], y2=xyxy[3])

                    # Maintain trajectory
                    traj = []
                    if existing_trajectories and track_id in existing_trajectories:
                        traj = list(existing_trajectories[track_id])
                    traj.append(bbox.centroid)
                    if len(traj) > 50:  # cap trajectory length
                        traj = traj[-50:]

                    tracks.append(TrackData(
                        track_id=track_id,
                        detection_class=_YOLO_CLASS_MAP[cls_id],
                        bbox=bbox,
                        confidence=conf,
                        trajectory=traj,
                    ))
                except Exception as exc:
                    logger.debug(f"[Detector] Error parsing detection {i}: {exc}")
                    continue

        # Log FPS every 5 seconds
        if time.time() - self._last_fps_report > 5.0 and self._fps_measurements:
            avg_fps = sum(self._fps_measurements) / len(self._fps_measurements)
            logger.info(f"[Detector] Inference FPS (avg last {len(self._fps_measurements)} frames): {avg_fps:.1f}")
            self._fps_measurements.clear()
            self._last_fps_report = time.time()

        return tracks

    def get_avg_fps(self) -> float:
        if not self._fps_measurements:
            return 0.0
        return sum(self._fps_measurements) / len(self._fps_measurements)


class NightMotionFallback:
    """
    Frame-differencing motion fallback for LOW_LIGHT_NIGHT when detector
    confidence collapses below threshold. Emits 'movement_detected_but_class_uncertain'
    events rather than DETECTED — honest about what we know.
    """

    def __init__(self):
        self._prev_gray: Optional[np.ndarray] = None

    def detect_motion(self, frame: np.ndarray, min_area: int = 500) -> bool:
        """Returns True if significant motion detected (but cannot classify)."""
        gray = np.array(frame, dtype=np.uint8)
        if len(gray.shape) == 3:
            import cv2
            gray = cv2.cvtColor(gray, cv2.COLOR_BGR2GRAY)
        import cv2
        gray = cv2.GaussianBlur(gray, (21, 21), 0)

        if self._prev_gray is None:
            self._prev_gray = gray
            return False

        diff = cv2.absdiff(self._prev_gray, gray)
        _, thresh = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)
        dilated = cv2.dilate(thresh, None, iterations=2)
        contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        self._prev_gray = gray

        return any(cv2.contourArea(c) > min_area for c in contours)
