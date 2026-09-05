"""
NETRAKSH Edge — Hybrid Reliability Decision Layer (Layer 5).
Implements the architecture v4 §8 HYBRID design (approved to replace the
original 3-gate categorical cascade's Gate 3 — see docs/ARCHITECTURE.md's
"Hybrid Reliability Engine" changelog entry for the full history and the
one existing test this intentionally changed the outcome of).

Gate 1 (Health, hard override — UNCHANGED from the original design):
  health == FAILED -> ABSTAIN, reason CAMERA_FAILED, stop.
  A weighted sum alone cannot guarantee this: a dead camera with an
  otherwise-plausible reading could still cross an Uncertain threshold under
  pure weighting. This stays a categorical, non-negotiable check specifically
  so that can never happen.

Below Gate 1 — weighted-sum Reliability score:
  R = wD*D + wT*T + wS*S + wH*H
  IF R < RELIABILITY_R_THRESHOLD: UNCERTAIN
  ELIF health == DEGRADED:        DETECTED (flagged — degraded-camera context)
  ELSE:                            DETECTED

  D = detector_confidence      (raw YOLO confidence for this frame's detection)
  T = temporal_score           (edge.temporal.track_features.TrackFeatureTracker;
                                defaults to a neutral 1.0 when no track context
                                is available — e.g. an abandoned-object event
                                whose track has already disappeared)
  S = scene quality             derived from SceneConditionReport's raw signals
  H = camera health quality     derived from CameraHealthReport.health_state

ABSTAIN remains reserved for Gate 1 only — this preserves the existing,
testable distinction between "the sensor is broken" (Abstain) and "the
evidence is weak" (Uncertain).

All weights, RELIABILITY_R_THRESHOLD, and the S/H scoring functions are
hand-picked heuristic defaults, NOT calibrated against labeled data — see
docs/LIMITATIONS.md and docs/ADR-TEMPORAL.md. They are environment-
overridable so a future calibration run (in the same spirit as
edge/detection/calibration.py's isotonic/Platt fitting) can update them
without a code change.

INTENTIONAL BEHAVIOR CHANGE from the original cascade: a degraded scene
condition now REDUCES R (via S) rather than lowering the acceptance bar the
way the old per-condition confidence threshold did. This is deliberate — the
project's own thesis is that the system should trust itself LESS under
degraded conditions, not accept weaker evidence as if it were normal. See
docs/ARCHITECTURE.md for the full rationale and the one test this changed.

Reliability and severity remain SEPARATE CONCEPTS.
A high-severity-looking event from a FAILED camera is still ABSTAIN.
"""
from __future__ import annotations

import logging
import os

from shared.constants import (
    CameraHealthState,
    DecisionState,
    FOG_CONTRAST_THRESHOLD,
    HealthReason,
    SceneCondition,
)
from shared.schemas import CameraHealthReport, ReliabilityDecision, SceneConditionReport

logger = logging.getLogger(__name__)

# --- Hybrid Reliability Engine weights and threshold (architecture v4 §8) ---
# HEURISTIC DEFAULTS — hand-picked starting point, ship-day-one values, NOT
# calibrated against labeled data. D carries the most weight because it is
# the actual object-presence signal; T/S/H are equal-weighted modulators.
# RELIABILITY_R_THRESHOLD=0.75 is inherited from the project's original
# reliability-formula convention (R>=0.75 -> DETECTED), now serving as the
# sole DETECTED cutoff since ABSTAIN is Gate 1's exclusive domain.
RELIABILITY_WEIGHT_D = float(os.environ.get("RELIABILITY_WEIGHT_D", "0.40"))
RELIABILITY_WEIGHT_T = float(os.environ.get("RELIABILITY_WEIGHT_T", "0.20"))
RELIABILITY_WEIGHT_S = float(os.environ.get("RELIABILITY_WEIGHT_S", "0.20"))
RELIABILITY_WEIGHT_H = float(os.environ.get("RELIABILITY_WEIGHT_H", "0.20"))
RELIABILITY_R_THRESHOLD = float(os.environ.get("RELIABILITY_R_THRESHOLD", "0.75"))

# Scene-quality (S) scoring reference points — same spirit as the thresholds
# in shared/constants.py, hand-picked and clearly labeled as such.
_SCENE_BRIGHTNESS_IDEAL = 128.0
_SCENE_CONTRAST_GOOD = 60.0
_SCENE_GLARE_BAD = 0.30

# Real finding this fixes (docs/PERFORMANCE_REPORT.md's "Reliability Engine
# behavior under real night/fog conditions"): even after the H double-penalty
# fix above, 29% of genuine fog crossings still missed RELIABILITY_R_THRESHOLD
# — because contrast_score judged FOG_RAIN frames against _SCENE_CONTRAST_GOOD
# (60.0), a clear-day ideal. But `contrast_std < FOG_CONTRAST_THRESHOLD` is
# LITERALLY the real rule SceneConditionClassifier already uses to call a
# scene FOG_RAIN in the first place (edge/condition/scene_condition.py) — so
# every frame classified FOG_RAIN is, by definition, already below 60, and
# judging it against 60 anyway scores it as "badly foggy" even when it is
# merely "typically foggy for what got it classified as fog at all." This
# reuses that SAME real, already-existing constant as FOG_RAIN's own
# contrast reference instead — not a new, unjustified number — so a frame at
# the actual boundary of "is this foggy" scores a full contrast_score, and a
# frame foggier than that (which does mean something concretely worse: low
# contrast well beyond the classification threshold itself) still scores
# proportionally lower. CLEAR_DAY/GLARE/LOW_LIGHT_NIGHT are unaffected —
# LOW_LIGHT_NIGHT's real driver measured in this project's data is brightness
# (contrast_score wasn't what suppressed its DETECTED rate — see
# docs/PERFORMANCE_REPORT.md), so it keeps the clear-day contrast reference.
_SCENE_CONTRAST_GOOD_BY_CONDITION = {
    SceneCondition.FOG_RAIN: FOG_CONTRAST_THRESHOLD,
}

# Health-quality (H) scoring. FAILED is never looked up here — Gate 1
# handles it exclusively, before this table would ever be consulted.
_HEALTH_QUALITY_SCORE = {
    CameraHealthState.OK: 1.0,
    CameraHealthState.DEGRADED: 0.5,
}

# Real finding this fixes (docs/PERFORMANCE_REPORT.md's "Reliability Engine
# behavior under real night/fog conditions", docs/LIMITATIONS.md): under a
# real, honest fog measurement, 0/52 genuine crossings cleared
# RELIABILITY_R_THRESHOLD. Root cause — a double penalty, not two
# independent ones: fog/low-light genuinely reduces image contrast/
# brightness, which S already measures and penalizes directly, AND
# genuinely reduces the Laplacian blur score edge/health/camera_health.py
# uses for its OWN, unrelated purpose (detecting a broken/dirty/defocused
# camera) — so the SAME real visual-softening signal was silently counted
# twice, once as S and again as H, for conditions where it isn't actually
# two independent problems. FROZEN_STREAM, ABNORMAL_EXPOSURE, FPS_DEGRADED,
# CLOCK_DRIFT, and STREAM_UNAVAILABLE are genuinely independent of scene
# condition and are NOT touched by this — only EXCESSIVE_BLUR specifically
# coinciding with a scene already classified FOG_RAIN or LOW_LIGHT_NIGHT.
_WEATHER_EXPLAINED_BLUR_CONDITIONS = frozenset({SceneCondition.FOG_RAIN, SceneCondition.LOW_LIGHT_NIGHT})


def _scene_quality_score(condition_report: SceneConditionReport) -> float:
    """Mode-A heuristic scene-quality score S in [0,1], derived from the same
    raw brightness/contrast/glare signals SceneConditionClassifier already
    computes. NOT calibrated — see docs/LIMITATIONS.md.

    contrast_score's reference point is per-condition (see
    _SCENE_CONTRAST_GOOD_BY_CONDITION above) for FOG_RAIN specifically, to
    avoid judging an inherently-lower-contrast condition against a clear-day
    ideal it was never going to meet by definition.
    """
    brightness_score = 1.0 - min(
        abs(condition_report.brightness_mean - _SCENE_BRIGHTNESS_IDEAL) / _SCENE_BRIGHTNESS_IDEAL, 1.0
    )
    contrast_good = _SCENE_CONTRAST_GOOD_BY_CONDITION.get(condition_report.condition, _SCENE_CONTRAST_GOOD)
    contrast_score = min(condition_report.contrast_std / contrast_good, 1.0)
    glare_score = 1.0 - min(condition_report.glare_fraction / _SCENE_GLARE_BAD, 1.0)
    return max(0.0, min(1.0, (brightness_score + contrast_score + glare_score) / 3.0))


def _health_quality_score(
    health_report: CameraHealthReport, condition_report: SceneConditionReport
) -> float:
    """Mode-A heuristic health-quality score H in [0,1]. Only OK/DEGRADED are
    scored here — FAILED is handled exclusively by Gate 1 before this is
    ever reached.

    One deliberate exception (see _WEATHER_EXPLAINED_BLUR_CONDITIONS above
    for the real, measured failure mode this fixes): when the ONLY reason
    health is DEGRADED is EXCESSIVE_BLUR, and the scene is independently
    classified FOG_RAIN or LOW_LIGHT_NIGHT, H is scored as healthy (1.0)
    instead of the usual 0.5 — S already penalizes this exact real signal,
    so this avoids double-counting one real degradation as two. Any OTHER
    DEGRADED reason still fully penalizes H exactly as before — those are
    genuinely independent hardware/pipeline problems S has no signal for.
    """
    if (
        health_report.health_state == CameraHealthState.DEGRADED
        and health_report.health_reason == HealthReason.EXCESSIVE_BLUR
        and condition_report.condition in _WEATHER_EXPLAINED_BLUR_CONDITIONS
    ):
        return 1.0
    return _HEALTH_QUALITY_SCORE.get(health_report.health_state, 0.5)


def make_reliability_decision(
    health_report: CameraHealthReport,
    condition_report: SceneConditionReport,
    detector_confidence: float,
    calibration_threshold: float,
    temporal_score: float = 1.0,
) -> ReliabilityDecision:
    """
    The one function that implements the Hybrid Reliability Engine.
    This is a pure function — no side effects, fully unit-testable.

    Args:
        health_report: output of Gate 1 (Camera Health Monitor)
        condition_report: output of Gate 2 (Scene Condition Classifier)
        detector_confidence: raw confidence from YOLO for the highest-confidence
                             detection in this frame (0.0 if no detection) — this is D
        calibration_threshold: per-condition confidence threshold from
                             edge.detection.calibration — still controls what
                             YOLO itself reports as a candidate detection at
                             all, and is echoed into `applied_threshold` for
                             context, but no longer directly gates the
                             DETECTED/UNCERTAIN banding (RELIABILITY_R_THRESHOLD
                             does that now)
        temporal_score: T in [0,1] from edge.temporal.track_features.
                             TrackFeatureTracker. Defaults to a neutral 1.0
                             when no track context is available (e.g. an
                             abandoned-object event whose track has already
                             disappeared) or the caller hasn't computed one.

    Returns:
        ReliabilityDecision with decision_state, decision_reason, and context
    """
    # === GATE 1: Camera Health (hard override, unchanged) ===
    if health_report.health_state == CameraHealthState.FAILED:
        reason = f"CAMERA_FAILED:{health_report.health_reason}"
        logger.warning(
            f"[Reliability] ABSTAIN — Gate 1 FAILED "
            f"(camera={health_report.camera_id}, reason={health_report.health_reason})"
        )
        return ReliabilityDecision(
            decision_state=DecisionState.ABSTAIN,
            decision_reason=reason,
            camera_health=CameraHealthState.FAILED,
            scene_condition=condition_report.condition,
            detector_confidence=detector_confidence,
            applied_threshold=calibration_threshold,
        )

    # === Hybrid Reliability Engine: weighted-sum R ===
    condition = condition_report.condition
    d = max(0.0, min(1.0, detector_confidence))
    t = max(0.0, min(1.0, temporal_score))
    s = _scene_quality_score(condition_report)
    h = _health_quality_score(health_report, condition_report)

    r = (
        RELIABILITY_WEIGHT_D * d
        + RELIABILITY_WEIGHT_T * t
        + RELIABILITY_WEIGHT_S * s
        + RELIABILITY_WEIGHT_H * h
    )
    factor_detail = f"D={d:.2f},T={t:.2f},S={s:.2f},H={h:.2f}"

    if r < RELIABILITY_R_THRESHOLD:
        reason = f"R_BELOW_THRESHOLD:R={r:.3f}<{RELIABILITY_R_THRESHOLD:.3f} ({factor_detail})"
        logger.debug(f"[Reliability] UNCERTAIN — {reason}")
        return ReliabilityDecision(
            decision_state=DecisionState.UNCERTAIN,
            decision_reason=reason,
            camera_health=health_report.health_state,
            scene_condition=condition,
            detector_confidence=detector_confidence,
            applied_threshold=calibration_threshold,
        )

    # R above threshold — DETECTED, flag health context
    if health_report.health_state == CameraHealthState.DEGRADED:
        reason = (
            f"R_ABOVE_THRESHOLD_DEGRADED_CAMERA:R={r:.3f}>={RELIABILITY_R_THRESHOLD:.3f} "
            f"({factor_detail}),health={health_report.health_reason}"
        )
        logger.info(f"[Reliability] DETECTED (DEGRADED CAMERA) — R={r:.3f}, health={health_report.health_reason}")
        return ReliabilityDecision(
            decision_state=DecisionState.DETECTED,
            decision_reason=reason,
            camera_health=CameraHealthState.DEGRADED,
            scene_condition=condition,
            detector_confidence=detector_confidence,
            applied_threshold=calibration_threshold,
        )

    # Full DETECTED
    reason = f"R_ABOVE_THRESHOLD:R={r:.3f}>={RELIABILITY_R_THRESHOLD:.3f} ({factor_detail})"
    logger.info(f"[Reliability] DETECTED — R={r:.3f}")
    return ReliabilityDecision(
        decision_state=DecisionState.DETECTED,
        decision_reason=reason,
        camera_health=CameraHealthState.OK,
        scene_condition=condition,
        detector_confidence=detector_confidence,
        applied_threshold=calibration_threshold,
    )


def make_abstain(camera_id: str, reason: str, condition: SceneCondition = SceneCondition.CLEAR_DAY) -> ReliabilityDecision:
    """Convenience constructor for ABSTAIN without running full gate logic."""
    return ReliabilityDecision(
        decision_state=DecisionState.ABSTAIN,
        decision_reason=reason,
        camera_health=CameraHealthState.FAILED,
        scene_condition=condition,
        detector_confidence=0.0,
        applied_threshold=0.0,
    )


def make_uncertain(condition: SceneCondition, confidence: float, threshold: float) -> ReliabilityDecision:
    """Convenience constructor for UNCERTAIN (e.g. night motion fallback)."""
    return ReliabilityDecision(
        decision_state=DecisionState.UNCERTAIN,
        decision_reason=f"MOVEMENT_DETECTED_CLASS_UNCERTAIN:{condition}",
        camera_health=CameraHealthState.OK,
        scene_condition=condition,
        detector_confidence=confidence,
        applied_threshold=threshold,
    )
