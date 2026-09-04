"""
NETRAKSH Edge — CLAHE Preprocessing (architecture v4 §3).
Applies CLAHE (Contrast Limited Adaptive Histogram Equalization) to the
luminance channel of a frame before detection, ONLY when the Scene Condition
Engine has already classified the scene as LOW_LIGHT_NIGHT or FOG_RAIN.

This produces a SEPARATE, enhanced copy used only as the detector's input —
camera health monitoring, scene condition classification, evidence
snapshots, and ANPR/face crops all continue to use the original,
unmodified frame. Enhancing before classification would make a genuinely
dark/foggy scene measure as better than it is, corrupting the very signal
(S in the Hybrid Reliability Engine, edge/reliability/decision.py) that
depends on being honest about scene quality.

Explicitly a MITIGATION, not a fix: the detector is still COCO-pretrained,
not night/fog-trained. CLAHE improves local contrast for the detector's
existing weights; it does not add information the sensor didn't capture,
and it does not close the underlying training-data gap. See
docs/LIMITATIONS.md.
"""
from __future__ import annotations

import logging
from typing import Tuple

import numpy as np

from shared.constants import SceneCondition

logger = logging.getLogger(__name__)

_CLAHE_CONDITIONS = frozenset({SceneCondition.LOW_LIGHT_NIGHT, SceneCondition.FOG_RAIN})

# Hand-picked defaults matching the commonly-cited starting point for CLAHE
# on natural images — not calibrated against this project's own footage.
# See docs/LIMITATIONS.md.
DEFAULT_CLIP_LIMIT = 2.0
DEFAULT_TILE_GRID_SIZE: Tuple[int, int] = (8, 8)


def enhance_for_detection(
    frame: np.ndarray,
    condition: SceneCondition,
    clip_limit: float = DEFAULT_CLIP_LIMIT,
    tile_grid_size: Tuple[int, int] = DEFAULT_TILE_GRID_SIZE,
) -> np.ndarray:
    """
    Returns a CLAHE-enhanced copy of `frame` for LOW_LIGHT_NIGHT/FOG_RAIN
    conditions, or `frame` itself (same object, unmodified) otherwise.
    Never mutates the input in place.
    """
    if condition not in _CLAHE_CONDITIONS:
        return frame

    import cv2

    lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
    l_channel, a_channel, b_channel = cv2.split(lab)

    clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=tile_grid_size)
    l_enhanced = clahe.apply(l_channel)

    enhanced_lab = cv2.merge((l_enhanced, a_channel, b_channel))
    return cv2.cvtColor(enhanced_lab, cv2.COLOR_LAB2BGR)
