"""
NETRAKSH Edge — Calibration module.
Provides per-condition confidence thresholds for Gate 3.

Architecture §17: "Gate 3 (Calibrated confidence): detector confidence vs.
a threshold specific to the Gate 2 bucket, fit via isotonic regression /
Platt scaling on a labeled validation set per bucket — never hand-picked."

Implementation status:
  - Calibration ARCHITECTURE is fully implemented (isotonic regression via scikit-learn).
  - If a labeled dataset exists, call CalibrationModule.fit() to produce real thresholds.
  - Without a labeled dataset (MVP/demo), prototype threshold values from .env are used.
  - All prototype thresholds are CLEARLY LABELLED as prototype values in code and docs.
  - The calibration interface is exposed so real data can be dropped in without
    changing any other module.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Dict, Optional, Tuple

import numpy as np

from shared.constants import CONDITION_THRESHOLD_KEYS, SceneCondition

logger = logging.getLogger(__name__)

# Prototype thresholds (labeled explicitly as such)
# Source: .env THRESHOLD_* vars — defaults chosen to be conservative for demo.
# These are NOT scientifically calibrated values.
_PROTOTYPE_THRESHOLDS: Dict[SceneCondition, float] = {
    SceneCondition.CLEAR_DAY: float(os.environ.get("THRESHOLD_CLEAR_DAY", "0.45")),
    SceneCondition.LOW_LIGHT_NIGHT: float(os.environ.get("THRESHOLD_LOW_LIGHT_NIGHT", "0.30")),
    SceneCondition.FOG_RAIN: float(os.environ.get("THRESHOLD_FOG_RAIN", "0.35")),
    SceneCondition.GLARE: float(os.environ.get("THRESHOLD_GLARE", "0.40")),
}


class CalibrationModule:
    """
    Manages per-condition detection thresholds.
    Can load from a fitted calibration file (real data) or fall back to prototype values.
    """

    def __init__(self, calibration_path: Optional[str] = None):
        self._thresholds: Dict[SceneCondition, float] = dict(_PROTOTYPE_THRESHOLDS)
        self._calibrated = False

        if calibration_path and os.path.exists(calibration_path):
            self._load(calibration_path)
        else:
            logger.warning(
                "[Calibration] Using PROTOTYPE thresholds (not calibrated from real data). "
                "See docs/LIMITATIONS.md and docs/PERFORMANCE_REPORT.md."
            )

    def get_threshold(self, condition: SceneCondition) -> float:
        return self._thresholds.get(condition, 0.45)

    def is_calibrated(self) -> bool:
        return self._calibrated

    def _load(self, path: str) -> None:
        try:
            with open(path) as f:
                data = json.load(f)
            for cond_str, threshold in data.get("thresholds", {}).items():
                cond = SceneCondition(cond_str)
                self._thresholds[cond] = float(threshold)
            self._calibrated = True
            logger.info(f"[Calibration] Loaded calibrated thresholds from {path}: {self._thresholds}")
        except Exception as exc:
            logger.error(f"[Calibration] Failed to load {path}: {exc}. Using prototype thresholds.")

    def fit(
        self,
        confidences: np.ndarray,
        labels: np.ndarray,
        condition: SceneCondition,
        method: str = "isotonic",
        save_path: Optional[str] = None,
    ) -> float:
        """
        Fit a calibration curve and return the optimal threshold for this condition.

        Args:
            confidences: raw detector confidences (0-1)
            labels: ground-truth binary labels (0=no object, 1=object present)
            condition: the condition bucket these samples belong to
            method: "isotonic" (default) or "platt" (logistic regression sigmoid)
            save_path: if set, save resulting thresholds to this JSON file

        Returns:
            Optimal threshold (maximizes F1 on the validation set)
        """
        from sklearn.calibration import CalibratedClassifierCV
        from sklearn.isotonic import IsotonicRegression
        from sklearn.linear_model import LogisticRegression

        logger.info(f"[Calibration] Fitting {method} calibration for {condition} with {len(confidences)} samples")

        if method == "isotonic":
            calibrator = IsotonicRegression(out_of_bounds="clip")
            calibrated_probs = calibrator.fit_transform(confidences, labels)
        elif method == "platt":
            # Platt scaling: fit logistic regression on raw confidences
            lr = LogisticRegression()
            lr.fit(confidences.reshape(-1, 1), labels)
            calibrated_probs = lr.predict_proba(confidences.reshape(-1, 1))[:, 1]
        else:
            raise ValueError(f"Unknown calibration method: {method}")

        # Find threshold that maximizes F1
        best_f1, best_threshold = 0.0, 0.5
        for t in np.arange(0.1, 0.95, 0.01):
            preds = (calibrated_probs >= t).astype(int)
            tp = np.sum((preds == 1) & (labels == 1))
            fp = np.sum((preds == 1) & (labels == 0))
            fn = np.sum((preds == 0) & (labels == 1))
            precision = tp / (tp + fp + 1e-8)
            recall = tp / (tp + fn + 1e-8)
            f1 = 2 * precision * recall / (precision + recall + 1e-8)
            if f1 > best_f1:
                best_f1 = f1
                best_threshold = float(t)

        self._thresholds[condition] = best_threshold
        self._calibrated = True
        logger.info(f"[Calibration] {condition}: threshold={best_threshold:.3f}, best_f1={best_f1:.3f}")

        if save_path:
            self._save(save_path)

        return best_threshold

    def _save(self, path: str) -> None:
        data = {
            "thresholds": {str(k): v for k, v in self._thresholds.items()},
            "calibrated": self._calibrated,
        }
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        logger.info(f"[Calibration] Saved thresholds to {path}")
