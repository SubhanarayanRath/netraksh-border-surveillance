"""
NETRAKSH Edge — Camera Adapter (Layer 1 / Ingestion).
Supports: local video file, RTSP URL, webcam (index).
Simulated frozen-frame mode for demo: SIMULATE_FROZEN_CAMERA=true.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Generator, Optional, Tuple

import cv2
import numpy as np

logger = logging.getLogger(__name__)


class FrameMetadata:
    __slots__ = ("frame_index", "timestamp", "video_time_seconds", "fps_declared", "width", "height", "source")

    def __init__(self, frame_index: int, timestamp: float, video_time_seconds: float, fps_declared: float,
                 width: int, height: int, source: str):
        self.frame_index = frame_index
        self.timestamp = timestamp
        self.video_time_seconds = video_time_seconds
        self.fps_declared = fps_declared
        self.width = width
        self.height = height
        self.source = source


class CameraAdapter:
    """
    Wraps OpenCV VideoCapture. Provides a frame generator with metadata.
    VIDEO_SOURCE env var controls the source.
    Emits (frame: np.ndarray, metadata: FrameMetadata) tuples.
    """

    def __init__(
        self,
        source: Optional[str] = None,
        simulate_frozen: bool = False,
        simulate_night: bool = False,
        target_fps: Optional[float] = None,
    ):
        self.source_str = source or os.environ.get("VIDEO_SOURCE", "0")
        self.simulate_frozen = simulate_frozen or os.environ.get("SIMULATE_FROZEN_CAMERA", "").lower() == "true"
        self.simulate_night = simulate_night or os.environ.get("SIMULATE_NIGHT_CONDITION", "").lower() == "true"
        self._cap: Optional[cv2.VideoCapture] = None
        self._fps_declared: float = target_fps or 25.0
        self._width: int = 640
        self._height: int = 480
        self._frozen_frame: Optional[np.ndarray] = None

    def open(self) -> bool:
        src = self._resolve_source()
        self._cap = cv2.VideoCapture(src)
        if not self._cap.isOpened():
            logger.error(f"Cannot open video source: {self.source_str}")
            return False
        self._fps_declared = self._cap.get(cv2.CAP_PROP_FPS) or 25.0
        self._width = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self._height = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        logger.info(f"Camera opened: source={self.source_str}, fps={self._fps_declared}, "
                    f"resolution={self._width}x{self._height}")
        return True

    def _resolve_source(self):
        s = self.source_str
        if s == "webcam" or s == "0":
            return 0
        if s == "sample_video":
            # Look for any mp4 in demo/videos/
            for root, _, files in os.walk("demo/videos"):
                for f in files:
                    if f.endswith((".mp4", ".avi", ".mov")):
                        return os.path.join(root, f)
            logger.warning("No sample video found in demo/videos/; falling back to webcam")
            return 0
        return s

    def frames(self) -> Generator[Tuple[np.ndarray, FrameMetadata], None, None]:
        if self._cap is None:
            if not self.open():
                return

        frame_index = 0
        start_real_time = time.time()
        start_video_msec = self._cap.get(cv2.CAP_PROP_POS_MSEC) if self._cap else 0.0

        while True:
            ret, frame = self._cap.read()
            if not ret:
                # End of file — loop for demo purposes
                self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                start_real_time = time.time()
                start_video_msec = 0.0
                ret, frame = self._cap.read()
                if not ret:
                    logger.warning("Cannot read frame — stream ended")
                    break

            if self._cap:
                current_msec = self._cap.get(cv2.CAP_PROP_POS_MSEC)
                expected_msec = start_video_msec + ((time.time() - start_real_time) * 1000.0)
                
                # If we are behind real time, drop the frame and read the next one to catch up
                if current_msec < expected_msec - 50:
                    continue
                # If we are ahead of real time, wait
                elif current_msec > expected_msec + 10:
                    time.sleep((current_msec - expected_msec) / 1000.0)

            # Frozen camera simulation: always return the first frame
            if self.simulate_frozen:
                if self._frozen_frame is None:
                    self._frozen_frame = frame.copy()
                frame = self._frozen_frame.copy()

            # Night simulation: darken the frame
            if self.simulate_night:
                frame = cv2.convertScaleAbs(frame, alpha=0.15, beta=0)

            meta = FrameMetadata(
                frame_index=frame_index,
                timestamp=time.time(),
                video_time_seconds=self._cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0 if self._cap else 0.0,
                fps_declared=self._fps_declared,
                width=frame.shape[1],
                height=frame.shape[0],
                source=self.source_str,
            )
            yield frame, meta
            frame_index += 1

    def release(self) -> None:
        if self._cap:
            self._cap.release()
            self._cap = None

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *_):
        self.release()
