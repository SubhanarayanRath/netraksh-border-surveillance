import os
import time
import httpx
import json

def trigger_synthetic_event():
    # Target the backend directly for E2E polling test
    backend_url = os.environ.get("BACKEND_URL", "http://localhost:8443")
    
    payload = {
        "event_id": f"synthetic_{int(time.time())}",
        "camera_id": "edge-001",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "zone_id": "zone_1",
        "detection_class": "person",
        "confidence": 0.95,
        "scene_condition": "CLEAR_DAY",
        "camera_health_state": "OK",
        "decision_state": "DETECTED",
        "clip_ref": "vtest_clip_1",
        "reliability_score": 0.88,
        "is_corroborated": False
    }

    # Simulate the sync client hitting the internal webhook/sync endpoint
    # Depending on the backend routes, this pushes directly to the database
    # Assuming /api/sync/events exists based on E2E pipeline structures
    try:
        response = httpx.post(f"{backend_url}/api/sync/events", json=[payload])
        if response.status_code in [200, 201, 202]:
            print(f"✅ Successfully injected synthetic event: {payload['event_id']}")
            return payload['event_id']
        else:
            print(f"❌ Failed to inject event: {response.status_code} {response.text}")
            return None
    except Exception as e:
        print(f"❌ Connection error during injection: {e}")
        return None

def poll_for_event(event_id, timeout=30):
    backend_url = os.environ.get("BACKEND_URL", "http://localhost:8443")
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        try:
            # Assumes an admin token is available or this route is mocked for tests
            # Real tests would authenticate first.
            response = httpx.get(f"{backend_url}/api/events/{event_id}")
            if response.status_code == 200:
                print(f"✅ Event {event_id} verified on backend! Latency: {time.time() - start_time:.2f}s")
                return True
        except Exception:
            pass
        
        time.sleep(2)
        
    print(f"❌ Timeout waiting for event {event_id} to surface.")
    return False

if __name__ == "__main__":
    print("Starting E2E Injection and Polling...")
    evt_id = trigger_synthetic_event()
    if evt_id:
        poll_for_event(evt_id)
