import logging
import queue
import time
from unittest import mock
import pytest

from edge.ingestion.camera_adapter import CameraAdapter, sanitize_url
from shared.constants import StreamState


def test_sanitize_url():
    assert sanitize_url("rtsp://admin:password123@192.168.1.10:554/stream") == "rtsp://***:***@192.168.1.10:554/stream"
    assert sanitize_url("rtsp://admin:pass%20word@192.168.1.10/stream") == "rtsp://***:***@192.168.1.10/stream"
    assert sanitize_url("http://user:pass@localhost") == "http://***:***@localhost"
    assert sanitize_url("rtsp://192.168.1.10/stream") == "rtsp://192.168.1.10/stream"
    assert sanitize_url("0") == "0"


@mock.patch("edge.ingestion.camera_adapter.cv2.VideoCapture")
def test_initial_connection_success(mock_vc):
    # Test 1: initial connection success
    mock_cap = mock.MagicMock()
    mock_cap.isOpened.return_value = True
    mock_cap.read.return_value = (True, mock.MagicMock())
    mock_vc.return_value = mock_cap

    adapter = CameraAdapter(source="rtsp://test", min_reconnect_delay=0.01, max_reconnect_delay=0.1)
    adapter.start()
    
    time.sleep(0.1)
    assert adapter.state == StreamState.CONNECTED
    
    adapter.stop()
    adapter.join()


@mock.patch("edge.ingestion.camera_adapter.cv2.VideoCapture")
def test_initial_connection_failure(mock_vc):
    # Test 2: initial connection failure
    mock_cap = mock.MagicMock()
    mock_cap.isOpened.return_value = False
    mock_vc.return_value = mock_cap

    adapter = CameraAdapter(source="rtsp://test", min_reconnect_delay=0.01, max_reconnect_delay=0.1)
    adapter.start()
    
    time.sleep(0.05)
    assert adapter.state == StreamState.RECONNECTING
    
    adapter.stop()
    adapter.join()


@mock.patch("edge.ingestion.camera_adapter.cv2.VideoCapture")
def test_queue_boundedness_and_drop_oldest(mock_vc):
    # Test 11, 12: queue boundedness, DROP_OLDEST behavior
    mock_cap = mock.MagicMock()
    mock_cap.isOpened.return_value = True
    
    # Generate distinct frames
    def side_effect():
        return True, mock.MagicMock()
    
    mock_cap.read.side_effect = side_effect
    mock_vc.return_value = mock_cap

    adapter = CameraAdapter(source="rtsp://test", max_queue_depth=5)
    adapter.start()
    
    time.sleep(0.2)
    adapter.stop()
    adapter.join()
    
    assert adapter.frames_received > 5
    assert adapter.frames_dropped > 0
    assert adapter._queue.qsize() <= 5


@mock.patch("edge.ingestion.camera_adapter.cv2.VideoCapture")
def test_stall_detection(mock_vc):
    # Test 5, 9: stall detection after first frame
    mock_cap = mock.MagicMock()
    mock_cap.isOpened.return_value = True
    
    call_count = [0]
    def read_side_effect():
        call_count[0] += 1
        if call_count[0] <= 1:
            return True, mock.MagicMock()
        # Simulate stall by returning True but doing nothing or sleeping
        time.sleep(0.2)
        return True, mock.MagicMock()
    
    mock_cap.read.side_effect = read_side_effect
    mock_vc.return_value = mock_cap

    adapter = CameraAdapter(source="rtsp://test", frame_stall_timeout_seconds=0.1)
    adapter.start()
    
    # Wait for the first frame and then the stall
    time.sleep(0.3)
    assert adapter.state in (StreamState.STALLING, StreamState.RECONNECTING)
    
    adapter.stop()
    adapter.join()


@mock.patch("edge.ingestion.camera_adapter.cv2.VideoCapture")
def test_reconnect_success_after_failure(mock_vc):
    # Test 3: reconnect success
    mock_cap_fail = mock.MagicMock()
    mock_cap_fail.isOpened.return_value = False
    
    mock_cap_success = mock.MagicMock()
    mock_cap_success.isOpened.return_value = True
    mock_cap_success.read.return_value = (True, mock.MagicMock())
    
    mock_vc.side_effect = [mock_cap_fail, mock_cap_success]

    adapter = CameraAdapter(source="rtsp://test", min_reconnect_delay=0.01, max_reconnect_delay=0.1)
    adapter.start()
    
    time.sleep(0.1)
    assert adapter.state == StreamState.CONNECTED
    
    adapter.stop()
    adapter.join()


@mock.patch("edge.ingestion.camera_adapter.cv2.VideoCapture")
def test_decoder_exception(mock_vc):
    # Test 14: decoder exception
    mock_cap = mock.MagicMock()
    mock_cap.isOpened.return_value = True
    mock_cap.read.side_effect = Exception("Decoder failure")
    mock_vc.return_value = mock_cap

    adapter = CameraAdapter(source="rtsp://test", min_reconnect_delay=0.01, max_reconnect_delay=0.1)
    adapter.start()
    
    time.sleep(0.1)
    # The exception should be caught, read fails, transitions to stalling/reconnecting
    assert adapter.state in (StreamState.STALLING, StreamState.RECONNECTING)
    
    adapter.stop()
    adapter.join()


def test_queue_timeout_behavior():
    # Test 13: queue timeout behavior
    adapter = CameraAdapter(source="rtsp://test")
    # Don't start the thread
    frame, meta = adapter.get_frame(timeout=0.01)
    assert frame is None
    assert meta is None
