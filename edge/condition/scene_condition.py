"""
NETRAKSH Edge — Scene Condition Classifier (Gate 2).
Classifies the current visual scene into one of four buckets:
  CLEAR_DAY | LOW_LIGHT_NIGHT | FOG_RAIN | GLARE

Uses pure OpenCV heuristics — no model required for MVP.
Each bucket corresponds to a different calibrated confidence threshold in Gate 3.

A single global threshold is provably wrong across day/night/fog — this is why
condition classification exists as its own gate.
"""
from __future__ import annotations

import logging

import cv2
import numpy as np

from shared.constants import (
    BRIGHTNESS_GLARE_THRESHOLD,
    BRIGHTNESS_NIGHT_THRESHOLD,
    FOG_CONTRAST_THRESHOLD,
    SceneCondition,
)
from shared.schemas import SceneConditionReport

logger = logging.getLogger(__name__)


class SceneConditionClassifier:
    """
    Stateless classifier. Returns a SceneConditionReport per frame.
    """

    def __init__(self, camera_id: str):
        self.camera_id = camera_id

    def classify(self, frame: np.ndarray) -> SceneConditionReport:
        """
        Classify scene condition from a single frame.
        Priority order (matches what reduces detector reliability most severely):
          1. GLARE (destroys object boundaries)
          2. FOG_RAIN (reduces contrast globally)
          3. LOW_LIGHT_NIGHT (reduces brightness)
          4. CLEAR_DAY (default)
        """
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        brightness_mean = float(np.mean(gray))
        contrast_std = float(np.std(gray))

        # Glare: high mean AND very high peak histogram fraction
        hist = cv2.calcHist([gray], [0], None, [256], [0, 256])
        glare_fraction = float(np.sum(hist[230:]) / gray.size)

        condition = self._decide(brightness_mean, contrast_std, glare_fraction)

        report = SceneConditionReport(
            camera_id=self.camera_id,
            condition=condition,
            brightness_mean=brightness_mean,
            contrast_std=contrast_std,
            glare_fraction=glare_fraction,
        )

        logger.debug(
            f"[Condition] {self.camera_id}: {condition} "
            f"(brightness={brightness_mean:.1f}, contrast={contrast_std:.1f}, "
            f"glare={glare_fraction:.3f})"
        )
        return report

    def _decide(
        self,
        brightness: float,
        contrast: float,
        glare_fraction: float,
    ) -> SceneCondition:
        # 1. Glare (washed-out, over-bright)
        if brightness > BRIGHTNESS_GLARE_THRESHOLD or glare_fraction > 0.15:
            return SceneCondition.GLARE

        # 2. Fog/rain: low contrast even though not dark
        if contrast < FOG_CONTRAST_THRESHOLD and brightness > BRIGHTNESS_NIGHT_THRESHOLD:
            return SceneCondition.FOG_RAIN

        # 3. Night / low-light: dark frame
        if brightness < BRIGHTNESS_NIGHT_THRESHOLD:
            return SceneCondition.LOW_LIGHT_NIGHT

        # 4. Default
        return SceneCondition.CLEAR_DAY
