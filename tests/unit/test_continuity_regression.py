"""
Phase 7.4.5: Continuity Identity Hardening Regression Test
"""
import pytest
import time
import numpy as np
from shared.schemas import BoundingBox, Point
from edge.tracking.continuity_guard import TrackContinuityGuard
from edge.main import EdgePipeline

class DummyTrack:
    def __init__(self, track_id):
        self.track_id = track_id
        self.bbox = BoundingBox(x1=10, y1=10, x2=20, y2=20, confidence=0.9)
        self.trajectory = [self.bbox.centroid]

def test_duplicate_reassociation_loop(monkeypatch):
    """
    Test that a native tracker ID repeatedly observed is mapped consistently
    and does not trigger multiple re-associations for the same ID.
    """
    # Mock pipeline
    monkeypatch.setattr("edge.main.EdgePipeline.__init__", lambda self: None)
    pipeline = EdgePipeline()
    pipeline.continuity_guard = TrackContinuityGuard()
    pipeline._known_track_ids = set()
    pipeline._track_id_map = {}
    
    # Simulate a lost track 50
    now = time.time()
    dummy_hist = np.zeros((30, 32), dtype=np.float32)
    pipeline.continuity_guard.remember_lost(
        track_id=50,
        histogram=dummy_hist,
        centroid=Point(x=15, y=15),
        trajectory=[],
        now=now
    )
    
    # Mock compute_histogram to return the dummy_hist
    monkeypatch.setattr("edge.main.compute_track_histogram", lambda f, b: dummy_hist)
    
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    
    # Frame 1: ByteTrack yields track 58.
    track_f1 = DummyTrack(58)
    processed_tracks = pipeline._apply_continuity_guard([track_f1], frame)
    
    # Track 58 should have been mapped to 50
    assert processed_tracks[0].track_id == 50
    assert 58 in pipeline._track_id_map
    assert pipeline._track_id_map[58] == 50
    
    # Frame 2: ByteTrack STILL yields native track 58
    track_f2 = DummyTrack(58)
    
    # Spy on resolve_new_track to ensure it is NOT called again
    called = []
    original_resolve = pipeline.continuity_guard.resolve_new_track
    def mock_resolve(*args, **kwargs):
        called.append(True)
        return original_resolve(*args, **kwargs)
    pipeline.continuity_guard.resolve_new_track = mock_resolve
    
    processed_tracks_2 = pipeline._apply_continuity_guard([track_f2], frame)
    
    # Assert resolve was NOT called
    assert not called, "ContinuityGuard was called again for a known native ID!"
    
    # Track 58 should remain mapped to 50
    assert processed_tracks_2[0].track_id == 50
