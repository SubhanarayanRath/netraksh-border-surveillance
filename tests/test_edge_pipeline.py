import pytest
import cv2
from edge.reliability.decision import HybridReliabilityEngine
from edge.health.camera_health import CameraHealthMonitor
from edge.condition.scene_condition import SceneConditionClassifier
from shared.constants import CameraHealthState, SceneCondition

def test_edge_reliability_engine_bounds():
    engine = HybridReliabilityEngine(camera_id="cam_01")
    
    # 1. Provide a mix of detections and track persistence
    # D: Detection Confidence (0.8)
    # T: Tracking persistence (0.9)
    # S: Scene Condition (CLEAR_DAY = 1.0)
    # H: Health State (OK = 1.0)
    
    r_score = engine.compute(
        detection_confidence=0.8,
        track_persistence_ratio=0.9,
        scene_condition=SceneCondition.CLEAR_DAY,
        camera_health=CameraHealthState.OK
    )
    
    # R = 0.40(D) + 0.20(T) + 0.20(S) + 0.20(H)
    # R = 0.40(0.8) + 0.20(0.9) + 0.20(1.0) + 0.20(1.0)
    # R = 0.32 + 0.18 + 0.20 + 0.20 = 0.90
    
    assert 0.0 <= r_score <= 1.0
    assert abs(r_score - 0.90) < 0.01

def test_edge_engine_failure_gates():
    engine = HybridReliabilityEngine(camera_id="cam_01")
    
    # Test Gate 1: FAILED health forces ABSTAIN (or 0.0)
    r_score = engine.compute(
        detection_confidence=0.9,
        track_persistence_ratio=1.0,
        scene_condition=SceneCondition.CLEAR_DAY,
        camera_health=CameraHealthState.FAILED
    )
    assert r_score == 0.0
