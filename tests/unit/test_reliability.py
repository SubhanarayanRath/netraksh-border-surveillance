"""
NETRAKSH — Unit tests for the Hybrid Reliability Decision Layer.
These are the most critical tests in the system — the core correctness guarantee.
All branches must pass.
"""
import pytest

from shared.constants import CameraHealthState, DecisionState, HealthReason, SceneCondition
from shared.schemas import CameraHealthReport, SceneConditionReport
from edge.reliability.decision import (
    make_reliability_decision,
    make_abstain,
    make_uncertain,
    RELIABILITY_R_THRESHOLD,
    RELIABILITY_WEIGHT_D,
    RELIABILITY_WEIGHT_T,
    RELIABILITY_WEIGHT_S,
    RELIABILITY_WEIGHT_H,
)
from datetime import datetime


def _health(state: CameraHealthState, reason: HealthReason = HealthReason.OK) -> CameraHealthReport:
    return CameraHealthReport(
        camera_id="test-cam",
        health_state=state,
        health_reason=reason,
        health_timestamp=datetime.utcnow(),
    )


def _condition(cond: SceneCondition = SceneCondition.CLEAR_DAY) -> SceneConditionReport:
    return SceneConditionReport(
        camera_id="test-cam",
        condition=cond,
        brightness_mean=128.0,
        contrast_std=50.0,
        glare_fraction=0.01,
    )


THRESHOLD = 0.45  # example calibrated threshold


class TestGate1HealthFailed:
    """Gate 1: FAILED → always ABSTAIN regardless of gates 2/3."""

    def test_failed_clear_day_high_confidence(self):
        """Even with perfect conditions and high confidence, FAILED = ABSTAIN."""
        result = make_reliability_decision(
            health_report=_health(CameraHealthState.FAILED, HealthReason.FROZEN_STREAM),
            condition_report=_condition(SceneCondition.CLEAR_DAY),
            detector_confidence=0.99,
            calibration_threshold=THRESHOLD,
        )
        assert result.decision_state == DecisionState.ABSTAIN
        assert "CAMERA_FAILED" in result.decision_reason
        assert result.camera_health == CameraHealthState.FAILED

    def test_failed_night_zero_confidence(self):
        result = make_reliability_decision(
            health_report=_health(CameraHealthState.FAILED, HealthReason.STREAM_UNAVAILABLE),
            condition_report=_condition(SceneCondition.LOW_LIGHT_NIGHT),
            detector_confidence=0.0,
            calibration_threshold=0.30,
        )
        assert result.decision_state == DecisionState.ABSTAIN

    def test_failed_fog_medium_confidence(self):
        result = make_reliability_decision(
            health_report=_health(CameraHealthState.FAILED, HealthReason.CLOCK_DRIFT),
            condition_report=_condition(SceneCondition.FOG_RAIN),
            detector_confidence=0.50,
            calibration_threshold=0.35,
        )
        assert result.decision_state == DecisionState.ABSTAIN

    def test_failed_reason_in_decision_reason(self):
        """Decision reason must include the health failure reason for explainability."""
        result = make_reliability_decision(
            health_report=_health(CameraHealthState.FAILED, HealthReason.FROZEN_STREAM),
            condition_report=_condition(),
            detector_confidence=0.95,
            calibration_threshold=THRESHOLD,
        )
        assert "frozen_stream" in result.decision_reason.lower() or "FROZEN" in result.decision_reason


class TestHybridEngineBasicBanding:
    """
    Below Gate 1: R = wD*D + wT*T + wS*S + wH*H, banded against
    RELIABILITY_R_THRESHOLD. `_condition()`'s default fixture
    (brightness=128, contrast=50, glare=0.01) scores S≈0.933, and T defaults
    to a neutral 1.0 when the caller passes no track context — these tests
    don't pass temporal_score, matching every existing call site that
    hasn't been upgraded to compute it yet.
    """

    def test_below_threshold_returns_uncertain(self):
        result = make_reliability_decision(
            health_report=_health(CameraHealthState.OK),
            condition_report=_condition(SceneCondition.CLEAR_DAY),
            detector_confidence=0.30,
            calibration_threshold=THRESHOLD,
        )
        assert result.decision_state == DecisionState.UNCERTAIN
        # applied_threshold still echoes what was passed in, for context/display —
        # it no longer drives the DETECTED/UNCERTAIN split (RELIABILITY_R_THRESHOLD does).
        assert result.applied_threshold == THRESHOLD

    def test_exactly_at_old_threshold_still_detects_under_new_formula(self):
        """Coincidence worth locking in with a test: D=0.45 with the default
        S/H/T context happens to land R just above RELIABILITY_R_THRESHOLD
        (0.75) too, so this boundary case keeps its original DETECTED outcome."""
        result = make_reliability_decision(
            health_report=_health(CameraHealthState.OK),
            condition_report=_condition(SceneCondition.CLEAR_DAY),
            detector_confidence=THRESHOLD,  # 0.45
            calibration_threshold=THRESHOLD,
        )
        assert result.decision_state == DecisionState.DETECTED

    def test_above_threshold_ok_camera_returns_detected(self):
        result = make_reliability_decision(
            health_report=_health(CameraHealthState.OK),
            condition_report=_condition(SceneCondition.CLEAR_DAY),
            detector_confidence=0.80,
            calibration_threshold=THRESHOLD,
        )
        assert result.decision_state == DecisionState.DETECTED
        assert result.camera_health == CameraHealthState.OK

    def test_above_threshold_degraded_camera_returns_detected_flagged(self):
        """DEGRADED camera (H=0.5 instead of 1.0) with strong confidence can
        still reach DETECTED — flagged — because D/T/S together still clear
        RELIABILITY_R_THRESHOLD despite the lower H contribution."""
        result = make_reliability_decision(
            health_report=_health(CameraHealthState.DEGRADED, HealthReason.EXCESSIVE_BLUR),
            condition_report=_condition(SceneCondition.CLEAR_DAY),
            detector_confidence=0.80,
            calibration_threshold=THRESHOLD,
        )
        assert result.decision_state == DecisionState.DETECTED
        assert result.camera_health == CameraHealthState.DEGRADED
        assert "DEGRADED" in result.decision_reason

    def test_r_below_threshold_reason_reports_all_four_factors(self):
        result = make_reliability_decision(
            health_report=_health(CameraHealthState.OK),
            condition_report=_condition(SceneCondition.CLEAR_DAY),
            detector_confidence=0.10,
            calibration_threshold=THRESHOLD,
        )
        assert result.decision_state == DecisionState.UNCERTAIN
        for factor in ("D=", "T=", "S=", "H="):
            assert factor in result.decision_reason


class TestHybridEngineIntentionalNightBehaviorChange:
    """
    INTENTIONAL BEHAVIOR CHANGE from the original 3-gate cascade: a lower
    per-condition confidence threshold used to make night detections easier
    to accept. Under the Hybrid Engine, degraded scene quality instead
    REDUCES R (via S), making night detections require the SAME evidentiary
    bar as day, not an easier one — consistent with the project's own thesis
    that the system should trust itself LESS under degraded conditions, not
    accept weaker evidence as normal. See docs/ARCHITECTURE.md.

    This replaces the old `test_night_condition_uses_lower_threshold`, whose
    premise (a lower threshold makes night detection easier) is exactly what
    this change retires.
    """

    def test_moderate_night_confidence_that_used_to_detect_is_now_uncertain(self):
        """Same inputs as the retired test: confidence=0.35 with a
        night-specific (lower) calibration_threshold=0.30 used to DETECT.
        Under the hybrid formula it correctly requires more evidence."""
        result = make_reliability_decision(
            health_report=_health(CameraHealthState.OK),
            condition_report=_condition(SceneCondition.LOW_LIGHT_NIGHT),
            detector_confidence=0.35,
            calibration_threshold=0.30,
        )
        assert result.decision_state == DecisionState.UNCERTAIN
        assert result.scene_condition == SceneCondition.LOW_LIGHT_NIGHT

    def test_low_night_confidence_remains_uncertain(self):
        """This boundary case's outcome is unchanged by the new formula."""
        result = make_reliability_decision(
            health_report=_health(CameraHealthState.OK),
            condition_report=_condition(SceneCondition.LOW_LIGHT_NIGHT),
            detector_confidence=0.20,
            calibration_threshold=0.30,
        )
        assert result.decision_state == DecisionState.UNCERTAIN

    def test_strong_night_confidence_still_detects(self):
        """The bar isn't impossible at night — sufficiently strong confidence
        (or, in the real pipeline, sustained temporal confirmation raising T)
        still clears RELIABILITY_R_THRESHOLD."""
        result = make_reliability_decision(
            health_report=_health(CameraHealthState.OK),
            condition_report=_condition(SceneCondition.LOW_LIGHT_NIGHT),
            detector_confidence=0.95,
            calibration_threshold=0.30,
        )
        assert result.decision_state == DecisionState.DETECTED


class TestWeatherExplainedBlurDoesNotDoublePenalize:
    """
    Real fix for a real, measured failure mode (docs/PERFORMANCE_REPORT.md's
    "Reliability Engine behavior under real night/fog conditions"): a real
    fog/night scene genuinely reduces both S (via its own contrast/
    brightness measurement) AND the camera health monitor's Laplacian blur
    score, which used to also halve H — double-counting one real
    visual-softening signal as two independent penalties. All four cases
    below share D=0.50, T=1.0 (default), and the same S fixture (S≈0.933)
    — chosen so DETECTED vs UNCERTAIN is decided purely by whether H is
    penalized, isolating exactly what this fix changes.
    """

    def test_excessive_blur_during_fog_is_not_health_penalized(self):
        result = make_reliability_decision(
            health_report=_health(CameraHealthState.DEGRADED, HealthReason.EXCESSIVE_BLUR),
            condition_report=_condition(SceneCondition.FOG_RAIN),
            detector_confidence=0.50,
            calibration_threshold=THRESHOLD,
        )
        assert result.decision_state == DecisionState.DETECTED

    def test_excessive_blur_during_night_is_not_health_penalized(self):
        result = make_reliability_decision(
            health_report=_health(CameraHealthState.DEGRADED, HealthReason.EXCESSIVE_BLUR),
            condition_report=_condition(SceneCondition.LOW_LIGHT_NIGHT),
            detector_confidence=0.50,
            calibration_threshold=THRESHOLD,
        )
        assert result.decision_state == DecisionState.DETECTED

    def test_excessive_blur_during_clear_day_is_still_fully_penalized(self):
        """The exemption is scoped to weather conditions only — the same
        blur during CLEAR_DAY has no scene-quality explanation for it (more
        likely a genuinely dirty/defocused lens), so H stays fully
        penalized, exactly as before this fix."""
        result = make_reliability_decision(
            health_report=_health(CameraHealthState.DEGRADED, HealthReason.EXCESSIVE_BLUR),
            condition_report=_condition(SceneCondition.CLEAR_DAY),
            detector_confidence=0.50,
            calibration_threshold=THRESHOLD,
        )
        assert result.decision_state == DecisionState.UNCERTAIN

    def test_other_degraded_reasons_during_fog_are_still_fully_penalized(self):
        """The exemption is scoped to EXCESSIVE_BLUR specifically — a health
        problem unrelated to weather (e.g. a frozen stream) happening to
        coincide with a foggy scene is still a real, independent problem and
        must still penalize H."""
        result = make_reliability_decision(
            health_report=_health(CameraHealthState.DEGRADED, HealthReason.FROZEN_STREAM),
            condition_report=_condition(SceneCondition.FOG_RAIN),
            detector_confidence=0.50,
            calibration_threshold=THRESHOLD,
        )
        assert result.decision_state == DecisionState.UNCERTAIN


class TestHybridEngineTemporalScore:
    """T (temporal_score) is a real input to R, not decoration — a borderline
    case can flip between UNCERTAIN and DETECTED purely based on it."""

    def test_low_temporal_score_can_tip_borderline_case_to_uncertain(self):
        result = make_reliability_decision(
            health_report=_health(CameraHealthState.OK),
            condition_report=_condition(SceneCondition.CLEAR_DAY),
            detector_confidence=0.50,
            calibration_threshold=THRESHOLD,
            temporal_score=0.0,
        )
        assert result.decision_state == DecisionState.UNCERTAIN

    def test_high_temporal_score_can_tip_same_borderline_case_to_detected(self):
        result = make_reliability_decision(
            health_report=_health(CameraHealthState.OK),
            condition_report=_condition(SceneCondition.CLEAR_DAY),
            detector_confidence=0.50,
            calibration_threshold=THRESHOLD,
            temporal_score=1.0,
        )
        assert result.decision_state == DecisionState.DETECTED

    def test_default_temporal_score_is_neutral_one(self):
        """Callers that haven't been upgraded to compute T (or have no track
        context, e.g. an abandoned-object event) must see identical behavior
        to explicitly passing temporal_score=1.0."""
        kwargs = dict(
            health_report=_health(CameraHealthState.OK),
            condition_report=_condition(SceneCondition.CLEAR_DAY),
            detector_confidence=0.50,
            calibration_threshold=THRESHOLD,
        )
        default_result = make_reliability_decision(**kwargs)
        explicit_result = make_reliability_decision(**kwargs, temporal_score=1.0)
        assert default_result.decision_state == explicit_result.decision_state


class TestHybridEngineWeightsAreConfigured:
    def test_weights_sum_to_one(self):
        """Not enforced at runtime (env-overridable), but the shipped
        defaults must be a real weighted average, not something that silently
        under- or over-counts the four factors."""
        total = RELIABILITY_WEIGHT_D + RELIABILITY_WEIGHT_T + RELIABILITY_WEIGHT_S + RELIABILITY_WEIGHT_H
        assert abs(total - 1.0) < 1e-9

    def test_detector_confidence_carries_the_largest_weight(self):
        """D is the actual object-presence signal — it must not be diluted
        below any single modulating factor."""
        assert RELIABILITY_WEIGHT_D > RELIABILITY_WEIGHT_T
        assert RELIABILITY_WEIGHT_D > RELIABILITY_WEIGHT_S
        assert RELIABILITY_WEIGHT_D > RELIABILITY_WEIGHT_H


class TestDecisionFields:
    """All decisions must populate required fields."""

    def test_abstain_has_required_fields(self):
        result = make_reliability_decision(
            health_report=_health(CameraHealthState.FAILED),
            condition_report=_condition(),
            detector_confidence=0.99,
            calibration_threshold=THRESHOLD,
        )
        assert result.decision_state is not None
        assert result.decision_reason is not None
        assert result.camera_health is not None
        assert result.scene_condition is not None

    def test_detected_has_threshold(self):
        result = make_reliability_decision(
            health_report=_health(CameraHealthState.OK),
            condition_report=_condition(),
            detector_confidence=0.80,
            calibration_threshold=THRESHOLD,
        )
        assert result.applied_threshold == THRESHOLD
        assert result.detector_confidence == 0.80

    def test_decision_reason_always_non_empty(self):
        for state, conf, threshold, health in [
            (DecisionState.ABSTAIN, 0.99, 0.45, CameraHealthState.FAILED),
            (DecisionState.UNCERTAIN, 0.20, 0.45, CameraHealthState.OK),
            (DecisionState.DETECTED, 0.80, 0.45, CameraHealthState.OK),
        ]:
            result = make_reliability_decision(
                health_report=_health(health),
                condition_report=_condition(),
                detector_confidence=conf,
                calibration_threshold=threshold,
            )
            assert len(result.decision_reason) > 5, f"Empty reason for {state}"


class TestConvenienceConstructors:
    def test_make_abstain(self):
        result = make_abstain("cam-1", "STREAM_DEAD", SceneCondition.CLEAR_DAY)
        assert result.decision_state == DecisionState.ABSTAIN
        assert result.camera_health == CameraHealthState.FAILED

    def test_make_uncertain(self):
        result = make_uncertain(SceneCondition.FOG_RAIN, 0.25, 0.35)
        assert result.decision_state == DecisionState.UNCERTAIN


class TestSchemaLockedFields:
    """Phase 2 acceptance: all locked evidence package fields must be present."""

    def test_evidence_package_has_all_locked_fields(self):
        from shared.schemas import EvidencePackage
        from datetime import datetime
        ep = EvidencePackage(
            event_id="evt-001",
            camera_id="cam-001",
            timestamp=datetime.utcnow(),
            zone_id="zone-001",
            detection_class="person",
            confidence=0.75,
            scene_condition="CLEAR_DAY",
            camera_health_state="OK",
            decision_state="DETECTED",
        )
        locked_fields = [
            "event_id", "camera_id", "timestamp", "zone_id",
            "detection_class", "confidence", "scene_condition",
            "camera_health_state", "decision_state", "evidence_clip_ref",
            "hash", "signature",
        ]
        for field in locked_fields:
            assert hasattr(ep, field), f"Missing locked field: {field}"

    def test_evidence_package_signable_fields_excludes_crypto(self):
        from shared.schemas import EvidencePackage
        ep = EvidencePackage(
            event_id="evt-001",
            camera_id="cam-001",
            timestamp=datetime.utcnow(),
            zone_id="zone-001",
            detection_class="person",
            confidence=0.75,
            scene_condition="CLEAR_DAY",
            camera_health_state="OK",
            decision_state="DETECTED",
            hash="deadbeef",
            signature="cafebabe",
        )
        signable = ep.get_signable_fields()
        assert "hash" not in signable
        assert "signature" not in signable
        assert "event_id" in signable
        assert "camera_id" in signable

    def test_zone_schema_has_adjacent_command_id(self):
        from shared.schemas import ZoneSchema, Polygon, Point
        z = ZoneSchema(
            zone_id="z1",
            camera_id="c1",
            name="Fence",
            zone_type="fence",
            polygon=Polygon(points=[Point(x=0, y=0), Point(x=1, y=0), Point(x=1, y=1)]),
            owning_command_id="COMMAND_A",
            adjacent_command_id="COMMAND_B",
        )
        assert z.adjacent_command_id == "COMMAND_B"

    def test_on_chain_transaction_has_locked_fields(self):
        from shared.schemas import AlertIssuedTransaction
        from shared.constants import Severity
        tx = AlertIssuedTransaction(
            alert_id="alert-001",
            evidence_package_hash="abc123",
            severity=Severity.HIGH,
            zone_id="zone-001",
            issuing_command_id="COMMAND_A",
            timestamp=datetime.utcnow(),
        )
        on_chain_fields = [
            "alert_id", "evidence_package_hash", "severity",
            "zone_id", "issuing_command_id", "timestamp"
        ]
        for field in on_chain_fields:
            assert hasattr(tx, field), f"Missing on-chain locked field: {field}"
