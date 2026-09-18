"""
NETRAKSH Edge — Camera Adapter (Layer 1 / Ingestion).
Supports: local video file, RTSP URL, webcam (index).
Implements WP-4.1 RTSP Resilience: background thread, explicit state machine,
bounded DROP_OLDEST queue, stall detection, and exponential backoff.
"""
from __future__ import annotations

import logging
import os
import queue
import random
import re
import threading
import time
from typing import Generator, Optional, Tuple

import cv2
import numpy as np

from shared.constants import StreamState

logger = logging.getLogger(__name__)


def sanitize_url(url: str) -> str:
    """Redact username and password from an RTSP or HTTP URL."""
    if not isinstance(url, str):
        return url
    # Match scheme://user:pass@host/path
    return re.sub(r'(?<=://)[^/:]+:[^/@]+@', '***:***@', url)


class FrameMetadata:
    __slots__ = ("frame_index", "timestamp", "video_time_seconds", "fps_declared", "width", "height", "source")

    def __init__(self, frame_index: int, timestamp: float, video_time_seconds: float, fps_declared: float,
                 width: int, height: int, source: str):
        self.frame_index = frame_index
        self.timestamp = timestamp  # received_at
        self.video_time_seconds = video_time_seconds
        self.fps_declared = fps_declared
        self.width = width
        self.height = height
        self.source = source


class CameraAdapter:
    """
    Wraps OpenCV VideoCapture in a background thread for resilience.
    Implements a robust state machine and exponential backoff.
    """

    def __init__(
        self,
        source: Optional[str] = None,
        simulate_frozen: bool = False,
        simulate_night: bool = False,
        target_fps: Optional[float] = None,
        max_queue_depth: int = 30,
        frame_stall_timeout_seconds: float = 10.0,
        min_reconnect_delay: float = 2.0,
        max_reconnect_delay: float = 60.0,
        max_reconnect_attempts: int = -1,  # -1 for infinite
        reconnect_jitter: float = 1.0,
        loop_video: bool = True,
    ):
        self.source_str = source or os.environ.get("VIDEO_SOURCE", "0")
        self.simulate_frozen = simulate_frozen or os.environ.get("SIMULATE_FROZEN_CAMERA", "").lower() == "true"
        self.simulate_night = simulate_night or os.environ.get("SIMULATE_NIGHT_CONDITION", "").lower() == "true"
        self._fps_declared: float = target_fps or 25.0
        self._width: int = 640
        self._height: int = 480
        self._frozen_frame: Optional[np.ndarray] = None
        self.loop_video = loop_video
        self._eof_reached = False

        # WP-4.1 State & Queue
        self._state = StreamState.INITIALIZING
        self._state_lock = threading.Lock()
        self._queue: queue.Queue[Tuple[np.ndarray, FrameMetadata]] = queue.Queue(maxsize=max_queue_depth)
        self._stop_event = threading.Event()
        self._reader_thread: Optional[threading.Thread] = None

        # Reconnect config
        self._stall_timeout = frame_stall_timeout_seconds
        self._min_delay = min_reconnect_delay
        self._max_delay = max_reconnect_delay
        self._max_attempts = max_reconnect_attempts
        self._jitter = reconnect_jitter

        # Telemetry
        self.frames_received = 0
        self.frames_dropped = 0
        self.last_frame_time = 0.0

    @property
    def state(self) -> StreamState:
        with self._state_lock:
            return self._state

    @property
    def eof_reached(self) -> bool:
        """True only when a finite file source has been fully consumed."""
        return self._eof_reached

    def _set_state(self, new_state: StreamState):
        with self._state_lock:
            if self._state != new_state:
                logger.info(f"[Adapter] State transition: {self._state.value} -> {new_state.value}")
                self._state = new_state

    def _resolve_source(self):
        s = self.source_str
        if s == "webcam" or s == "0":
            return 0
        if s == "sample_video":
            for root, _, files in os.walk("demo/videos"):
                for f in files:
                    if f.endswith((".mp4", ".avi", ".mov")):
                        return os.path.join(root, f)
            logger.warning("No sample video found in demo/videos/; falling back to webcam")
            return 0
        return s

    def start(self) -> None:
        """Start the background reader thread."""
        if self._reader_thread is not None and self._reader_thread.is_alive():
            return
        self._eof_reached = False
        self._stop_event.clear()
        self._reader_thread = threading.Thread(
            target=self._reader_loop,
            name="CameraReader",
            daemon=True
        )
        self._reader_thread.start()

    def stop(self) -> None:
        """Signal the reader thread to stop."""
        self._stop_event.set()
        self._set_state(StreamState.STOPPED)

    def join(self, timeout: Optional[float] = 5.0) -> None:
        """Wait for the reader thread to exit cleanly."""
        if self._reader_thread is not None:
            self._reader_thread.join(timeout=timeout)
            if self._reader_thread.is_alive():
                logger.error("[Adapter] Reader thread failed to join within timeout (decoder may be hanging).")
            self._reader_thread = None

    def _reader_loop(self) -> None:
        """Background thread loop owning the VideoCapture."""
        cap = None
        attempt = 0
        first_frame_received = False
        is_video_file = str(self._resolve_source()).endswith((".mp4", ".avi", ".mov"))

        while not self._stop_event.is_set():
            if self.state in (StreamState.INITIALIZING, StreamState.RECONNECTING):
                src = self._resolve_source()
                safe_src = sanitize_url(str(src))
                logger.info(f"[Adapter] Opening source: {safe_src}")
                
                try:
                    cap = cv2.VideoCapture(src)
                except Exception as e:
                    logger.error(f"[Adapter] cv2.VideoCapture exception: {e}")
                    cap = None
                
                if cap is not None and cap.isOpened():
                    self._fps_declared = cap.get(cv2.CAP_PROP_FPS) or 25.0
                    self._width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                    self._height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                    self._set_state(StreamState.CONNECTED)
                    attempt = 0
                    first_frame_received = False
                    self.last_frame_time = 0.0 # reset on new connection
                else:
                    if cap is not None:
                        cap.release()
                        cap = None
                    
                    attempt += 1
                    if self._max_attempts != -1 and attempt > self._max_attempts:
                        logger.error("[Adapter] Max reconnect attempts reached.")
                        self._set_state(StreamState.FAILED)
                        break
                    
                    # Exponential backoff with bounded jitter
                    delay_base = min(self._max_delay, self._min_delay * (2 ** (attempt - 1)))
                    jitter_val = random.uniform(0, self._jitter)
                    delay = min(self._max_delay, delay_base + jitter_val)
                    
                    self._set_state(StreamState.RECONNECTING)
                    logger.warning(f"[Adapter] Open failed. Waiting {delay:.2f}s before retry {attempt}...")
                    self._stop_event.wait(delay)
                    continue

            if self.state == StreamState.CONNECTED:
                try:
                    ret, frame = cap.read()
                except Exception as e:
                    logger.error(f"[Adapter] Decoder exception during read: {e}")
                    ret = False

                now = time.time()

                if not ret:
                    if is_video_file:
                        if self.loop_video:
                            # Legacy/demo camera sources may intentionally loop.
                            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                            continue
                        logger.info("[Adapter] End of finite video source reached.")
                        self._eof_reached = True
                        break
                    else:
                        logger.warning("[Adapter] Read failed (stream ended or connection lost).")
                        self._set_state(StreamState.STALLING)
                        cap.release()
                        cap = None
                        self._set_state(StreamState.RECONNECTING)
                        continue

                # Successful read
                if not first_frame_received:
                    first_frame_received = True

                self.last_frame_time = now
                self.frames_received += 1

                # Frame simulations
                if self.simulate_frozen:
                    if self._frozen_frame is None:
                        self._frozen_frame = frame.copy()
                    frame = self._frozen_frame.copy()
                if self.simulate_night:
                    frame = cv2.convertScaleAbs(frame, alpha=0.15, beta=0)

                meta = FrameMetadata(
                    frame_index=self.frames_received,
                    timestamp=now,
                    video_time_seconds=cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0,
                    fps_declared=self._fps_declared,
                    width=frame.shape[1],
                    height=frame.shape[0],
                    source=self.source_str,
                )

                # Push to bounded queue with DROP_OLDEST policy
                try:
                    self._queue.put_nowait((frame, meta))
                except queue.Full:
                    try:
                        self._queue.get_nowait()
                        self.frames_dropped += 1
                    except queue.Empty:
                        pass
                    try:
                        self._queue.put_nowait((frame, meta))
                    except queue.Full:
                        pass
                
                # Naive pacing if it's a file
                if is_video_file:
                    time.sleep(1.0 / self._fps_declared)

            elif self.state == StreamState.STALLING:
                # Should not be reached during normal read loop unless transitioning,
                # but handled for safety.
                cap.release()
                cap = None
                self._set_state(StreamState.RECONNECTING)
                
            # Stall detection
            if self.state == StreamState.CONNECTED and first_frame_received:
                if time.time() - self.last_frame_time > self._stall_timeout:
                    logger.warning("[Adapter] Frame stall detected.")
                    self._set_state(StreamState.STALLING)
                    if cap is not None:
                        cap.release()
                        cap = None
                    self._set_state(StreamState.RECONNECTING)

        # Cleanup on exit
        if cap is not None:
            cap.release()

    def get_frame(self, timeout: float = 0.1) -> Tuple[Optional[np.ndarray], Optional[FrameMetadata]]:
        """
        Pop the oldest buffered frame. Non-blocking bounded wait.
        """
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None, None

    def frames(self) -> Generator[Tuple[np.ndarray, FrameMetadata], None, None]:
        """
        Legacy generator interface, preserved for compatibility if needed.
        Will block until stopped.
        """
        self.start()
        while not self._stop_event.is_set():
            frame, meta = self.get_frame(timeout=0.5)
            if frame is not None and meta is not None:
                yield frame, meta
        self.join()

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *_):
        self.stop()
        self.join()
