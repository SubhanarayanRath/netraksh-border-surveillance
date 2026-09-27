import pytest
from fastapi.testclient import TestClient
from backend.main import app
from backend.api.dashboard import _demo_state, _videos_dir
from backend.config import settings
import os
import shutil
import uuid

settings.EDGE_AUTH_TOKEN = "test-token"

client = TestClient(app)

def test_edge_download_authentication():
    # Attempt download without token
    resp = client.get("/api/dashboard/video/edge-download")
    assert resp.status_code in [401, 403], f"Expected auth failure, got {resp.status_code}"

    # Attempt download with incorrect token
    resp = client.get("/api/dashboard/video/edge-download", headers={"Authorization": "Bearer BAD_TOKEN"})
    assert resp.status_code in [401, 403], f"Expected auth failure, got {resp.status_code}"

def test_edge_download_missing_video():
    # Clear the demo state
    _demo_state["video_source"] = None
    
    auth_header = {"Authorization": f"Bearer {settings.EDGE_AUTH_TOKEN}"}
    resp = client.get("/api/dashboard/video/edge-download", headers=auth_header)
    assert resp.status_code == 404, "Expected 404 when no video exists"

def test_edge_download_success(tmp_path):
    vdir = _videos_dir()
    vdir.mkdir(parents=True, exist_ok=True)
    
    # Create a mock video file
    test_uuid = str(uuid.uuid4())
    test_filename = f"uploaded_{test_uuid}.mp4"
    test_filepath = vdir / test_filename
    
    with open(test_filepath, "wb") as f:
        f.write(b"mock video data")
        
    _demo_state["video_source"] = f"demo/videos/{test_filename}"
    
    auth_header = {"Authorization": f"Bearer {settings.EDGE_AUTH_TOKEN}"}
    resp = client.get("/api/dashboard/video/edge-download", headers=auth_header)
    assert resp.status_code == 200, "Expected 200 OK"
    assert resp.content == b"mock video data"
    
    # Clean up
    if test_filepath.exists():
        os.remove(test_filepath)
