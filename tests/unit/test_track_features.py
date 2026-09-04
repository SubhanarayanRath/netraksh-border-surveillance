"""
NETRAKSH — Unit tests for edge/temporal/track_features.py
(Temporal Evidence Intelligence, Mode A — architecture v4 §7, ADR-001).
"""
import math

from edge.temporal.track_features import TrackFeatureTracker
from shared.schemas import Point


def _straight_line(n=10, step=5.0):
    """A perfectly straight, constant-speed path — maximally smooth and consistent."""
    return [Point(x=float(i * step), y=0.0) for i in range(n)]


def _stationary(n=10):
    """A track that never moves."""
    return [Point(x=10.0, y=10.0) for _ in range(n)]


def _zigzag(n=10, step=5.0):
    """An erratic path that reverses direction every point."""
    pts = []
    x = 0.0
    direction = 1
    for i in range(n):
        x += step * direction
        pts.append(Point(x=x, y=0.0 if i % 2 == 0 else 20.0))
        direction *= -1
    return pts


class TestTrackAge:
    def test_first_observation_has_zero_age(self):
        t = TrackFeatureTracker()
        assert t.get_track_age_seconds(1, now=100.0) is None
        t.compute(1, [], now=100.0)
        assert t.get_track_age_seconds(1, now=100.0) == 0.0

    def test_age_grows_with_time(self):
        t = TrackFeatureTracker()
        t.compute(1, [], now=100.0)
        assert t.get_track_age_seconds(1, now=103.0) == 3.0

    def test_forget_clears_track_state(self):
        t = TrackFeatureTracker()
        t.compute(1, [], now=100.0)
        assert t.get_tracked_count() == 1
        t.forget(1)
        assert t.get_tracked_count() == 0
        assert t.get_track_age_seconds(1, now=200.0) is None

    def test_different_tracks_have_independent_age(self):
        t = TrackFeatureTracker()
        t.compute(1, [], now=100.0)
        t.compute(2, [], now=105.0)
        assert t.get_track_age_seconds(1, now=110.0) == 10.0
        assert t.get_track_age_seconds(2, now=110.0) == 5.0


class TestComputeReturnsBoundedScore:
    def test_score_is_between_zero_and_one(self):
        t = TrackFeatureTracker()
        for traj in (_straight_line(), _stationary(), _zigzag(), []):
            score = t.compute(1, traj, now=0.0)
            assert 0.0 <= score <= 1.0

    def test_empty_trajectory_does_not_crash(self):
        t = TrackFeatureTracker()
        score = t.compute(1, [], now=0.0)
        assert 0.0 <= score <= 1.0


class TestPathSmoothnessAndSpeedConsistency:
    def test_straight_line_scores_higher_than_zigzag(self):
        # Prime age via a first call at t=0, then measure at t=10 (past the
        # default 5s saturation) so age contributes equally and only the
        # path shape/speed difference can explain the score gap.
        t1 = TrackFeatureTracker()
        t1.compute(1, [], now=0.0)
        straight_score = t1.compute(1, _straight_line(n=20), now=10.0)

        t2 = TrackFeatureTracker()
        t2.compute(2, [], now=0.0)
        zigzag_score = t2.compute(2, _zigzag(n=20), now=10.0)

        assert straight_score > zigzag_score

    def test_stationary_track_is_not_penalized(self):
        """A perfectly still object (e.g. an abandoned bag) must score highly —
        stationarity is strong temporal consistency, not noise."""
        t = TrackFeatureTracker()
        t.compute(1, [], now=0.0)
        score = t.compute(1, _stationary(n=20), now=10.0)
        assert score > 0.9

    def test_too_few_points_does_not_penalize(self):
        """Fewer than the minimum points for smoothness/speed must not drag
        the score down — there simply isn't enough evidence yet either way."""
        t = TrackFeatureTracker()
        score = t.compute(1, [Point(x=0.0, y=0.0)], now=0.0)
        assert score >= 0.5  # age=0 contributes 0, but smoothness/speed default to 1.0 (not 0)


class TestAgeSaturation:
    def test_age_score_saturates_at_configured_duration(self):
        t = TrackFeatureTracker(age_saturation_seconds=2.0)
        t.compute(1, [], now=0.0)
        # At exactly the saturation point with a maximally consistent (stationary) path,
        # the score should be at or very near 1.0.
        score = t.compute(1, _stationary(n=5), now=2.0)
        assert score > 0.95

    def test_age_score_partial_before_saturation(self):
        t = TrackFeatureTracker(age_saturation_seconds=10.0)
        t.compute(1, [], now=0.0)
        score_early = t.compute(1, _stationary(n=5), now=1.0)   # 10% of saturation
        score_late = t.compute(1, _stationary(n=5), now=9.0)    # 90% of saturation
        assert score_late > score_early
