import pytest
import numpy as np
from shared.constants import SceneCondition, CameraHealthState, HealthReason
from edge.health.camera_health import CameraHealthMonitor
from edge.condition.scene_condition import SceneConditionClassifier
from shared.schemas import CameraHealthReport, SceneConditionReport

def test_camera_health_graceful_degradation():
    monitor = CameraHealthMonitor(camera_id="test_cam")
    
    # 1. Normal frame
    normal_frame = np.random.randint(0, 256, (480, 640, 3), dtype=np.uint8)
    report = monitor.analyze_frame(normal_frame)
    assert report.health_state == CameraHealthState.OK
    
    # 2. Frozen frames (Zero variance across time)
    # Feed the exact same frame multiple times to trigger frozen stream
    frozen_frame = np.ones((480, 640, 3), dtype=np.uint8) * 128
    for _ in range(monitor.history_size + 1):
        report = monitor.analyze_frame(frozen_frame)
    
    assert report.health_state == CameraHealthState.FAILED
    assert report.health_reason == HealthReason.FROZEN_STREAM

    # 3. Corrupted / Blank frame (zero variance spatially)
    blank_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    report = monitor.analyze_frame(blank_frame)
    # The monitor might need history to recover or will immediately flag spatial variance failure
    assert report.health_state in [CameraHealthState.FAILED, CameraHealthState.DEGRADED]

def test_scene_condition_graceful_degradation():
    classifier = SceneConditionClassifier()
    
    # 1. Normal frame
    normal_frame = np.random.randint(50, 200, (480, 640, 3), dtype=np.uint8)
    report = classifier.analyze(normal_frame)
    assert report.condition == SceneCondition.CLEAR_DAY
    
    # 2. Fog / Low Contrast (Uniform gray)
    fog_frame = np.ones((480, 640, 3), dtype=np.uint8) * 128
    # Add minimal noise so it's not perfectly zero variance, but low enough for fog
    fog_frame = fog_frame + np.random.randint(-2, 3, (480, 640, 3), dtype=np.uint8)
    report = classifier.analyze(fog_frame)
    assert report.condition == SceneCondition.FOG_RAIN
    
    # 3. Low Light Night (Very dark)
    dark_frame = np.random.randint(0, 20, (480, 640, 3), dtype=np.uint8)
    report = classifier.analyze(dark_frame)
    assert report.condition == SceneCondition.LOW_LIGHT_NIGHT

    # 4. Glare (Extreme bright spot)
    glare_frame = np.random.randint(50, 150, (480, 640, 3), dtype=np.uint8)
    glare_frame[200:300, 300:400] = 255 # Blown out highlight
    report = classifier.analyze(glare_frame)
    assert report.condition == SceneCondition.GLARE
