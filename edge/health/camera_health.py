"""
NETRAKSH Edge — Camera Health Monitor (Gate 1).
Determines camera health state BEFORE any detector runs.

Checks:
  1. Frozen / repeated frames: frame-difference variance
  2. Blur / defocus: Laplacian variance
  3. Abnormal exposure: histogram clipping fraction
  4. FPS consistency: measured FPS vs declared
  5. Timestamp drift: system clock vs frame timestamp

Output: CameraHealthReport with state OK / DEGRADED / FAILED and specific reason.

A FAILED camera IMMEDIATELY causes the reliability layer to emit ABSTAIN.
The system never silently interprets a dead camera as "no activity".
"""
from __future__ import annotations

import time
import logging
from collections import deque
from datetime import datetime
from typing import Deque, Optional, Tuple

import cv2
import numpy as np

from shared.constants import (
    BLUR_LAPLACIAN_THRESHOLD,
    CLOCK_DRIFT_DEGRADED_SECONDS,
    CLOCK_DRIFT_FAILED_SECONDS,
    EXPOSURE_CLIPPING_THRESHOLD,
    FPS_DEGRADED_RATIO,
    FROZEN_FRAME_VARIANCE_THRESHOLD,
    CameraHealthState,
    HealthReason,
)
from shared.schemas import CameraHealthReport

logger = logging.getLogger(__name__)


class CameraHealthMonitor:
    """
    Runs on every frame batch. Maintains a rolling window of recent frames
    and metrics to detect health degradation.
    """

    def __init__(
        self,
        camera_id: str,
        fps_declared: float = 25.0,
        window_size: int = 10,
    ):
        self.camera_id = camera_id
        self.fps_declared = fps_declared
        self._recent_frames: Deque[np.ndarray] = deque(maxlen=window_size)
        self._frame_times: Deque[float] = deque(maxlen=window_size)
        self._last_report_time: float = 0.0
        self._report_interval: float = 2.0  # seconds between health reports

    def update(self, frame: np.ndarray, frame_timestamp: float) -> CameraHealthReport:
        """
        Process one frame and return a health report.
        This is called every frame; reporting is rate-limited for efficiency.
        """
        self._recent_frames.append(frame.copy())
        self._frame_times.append(frame_timestamp)

        state, reason, metrics = self._evaluate()

        return CameraHealthReport(
            camera_id=self.camera_id,
            health_state=state,
            health_reason=reason,
            health_timestamp=datetime.utcnow(),
            fps_actual=metrics.get("fps_actual"),
            fps_declared=self.fps_declared,
            drift_seconds=metrics.get("drift_seconds"),
            blur_score=metrics.get("blur_score"),
            exposure_clip_fraction=metrics.get("exposure_clip_fraction"),
            frame_variance=metrics.get("frame_variance"),
        )

    def _evaluate(self) -> Tuple[CameraHealthState, HealthReason, dict]:
        metrics: dict = {}
        frame = self._recent_frames[-1]

        # --- Check 1: Stream availability (trivial — we got a frame so it's present) ---
        # If we're here we have a frame; unavailability is caught in the adapter

        # --- Check 2: Frozen frame detection ---
        if len(self._recent_frames) >= 2:
            diff = cv2.absdiff(
                cv2.cvtColor(self._recent_frames[-1], cv2.COLOR_BGR2GRAY),
                cv2.cvtColor(self._recent_frames[-2], cv2.COLOR_BGR2GRAY),
            )
            variance = float(np.var(diff))
            metrics["frame_variance"] = variance
            if variance < FROZEN_FRAME_VARIANCE_THRESHOLD:
                logger.warning(f"[Health] Camera {self.camera_id}: FROZEN (variance={variance:.2f})")
                return CameraHealthState.FAILED, HealthReason.FROZEN_STREAM, metrics

        # --- Check 3: Blur / defocus (Laplacian variance) ---
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        blur_score = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        metrics["blur_score"] = blur_score
        if blur_score < BLUR_LAPLACIAN_THRESHOLD:
            logger.debug(f"[Health] Camera {self.camera_id}: blur score={blur_score:.1f} < {BLUR_LAPLACIAN_THRESHOLD}")
            # Excessive blur = DEGRADED (not FAILED — could be fog/night, not necessarily broken)
            return CameraHealthState.DEGRADED, HealthReason.EXCESSIVE_BLUR, metrics

        # --- Check 4: Exposure (histogram clipping) ---
        hist = cv2.calcHist([gray], [0], None, [256], [0, 256])
        total_pixels = gray.size
        # Over-exposed: too many pixels at 255
        overexposed_fraction = float(hist[255][0]) / total_pixels
        # Under-exposed: too many pixels at 0
        underexposed_fraction = float(hist[0][0]) / total_pixels
        clip_fraction = max(overexposed_fraction, underexposed_fraction)
        metrics["exposure_clip_fraction"] = clip_fraction
        if clip_fraction > EXPOSURE_CLIPPING_THRESHOLD:
            logger.debug(f"[Health] Camera {self.camera_id}: abnormal exposure clip={clip_fraction:.3f}")
            return CameraHealthState.DEGRADED, HealthReason.ABNORMAL_EXPOSURE, metrics

        # --- Check 5: FPS consistency ---
        if len(self._frame_times) >= 5:
            intervals = [
                self._frame_times[i] - self._frame_times[i - 1]
                for i in range(1, len(self._frame_times))
            ]
            avg_interval = sum(intervals) / len(intervals)
            fps_actual = 1.0 / avg_interval if avg_interval > 0 else 0.0
            metrics["fps_actual"] = fps_actual
            fps_ratio = fps_actual / self.fps_declared if self.fps_declared > 0 else 1.0
            if fps_ratio < FPS_DEGRADED_RATIO:
                logger.debug(f"[Health] Camera {self.camera_id}: FPS degraded (actual={fps_actual:.1f}, declared={self.fps_declared})")
                return CameraHealthState.DEGRADED, HealthReason.FPS_DEGRADED, metrics
        else:
            metrics["fps_actual"] = self.fps_declared  # not enough data yet

        # --- Check 6: Timestamp drift ---
        # Compare system time to frame timestamp (opportunistic NTP check)
        now = time.time()
        drift = abs(now - self._frame_times[-1])
        metrics["drift_seconds"] = drift
        if drift > CLOCK_DRIFT_FAILED_SECONDS:
            logger.warning(f"[Health] Camera {self.camera_id}: CLOCK DRIFT CRITICAL drift={drift:.1f}s")
            return CameraHealthState.FAILED, HealthReason.CLOCK_DRIFT, metrics
        if drift > CLOCK_DRIFT_DEGRADED_SECONDS:
            logger.warning(f"[Health] Camera {self.camera_id}: clock drift={drift:.1f}s (DEGRADED)")
            return CameraHealthState.DEGRADED, HealthReason.CLOCK_DRIFT, metrics

        # --- All checks passed ---
        return CameraHealthState.OK, HealthReason.OK, metrics
