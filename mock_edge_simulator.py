import os
import time
import httpx
import random
import uuid

# This script runs entirely in the background on Render to simulate Edge devices 24/7.
backend_url = f"http://localhost:{os.environ.get('PORT', '8443')}"
print(f"Mock Edge Simulator starting. Targeting {backend_url}")

# Wait for backend to boot up
time.sleep(10)

cameras = ["cam-border-01", "cam-checkpoint-01"]
conditions = ["CLEAR_DAY", "FOG_RAIN", "CLEAR_DAY", "CLEAR_DAY"]
states = ["DETECTED", "DETECTED", "UNCERTAIN", "DETECTED"]

while True:
    try:
        # Sleep randomly between 5 to 15 seconds to simulate real-world arrival times
        time.sleep(random.uniform(5.0, 15.0))
        
        # Decide if we generate a corroborated event (both cameras see the same thing)
        corroborate = random.random() > 0.5
        
        track_num = random.randint(1, 100)
        timestamp_a = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        confidence = round(random.uniform(0.70, 0.98), 2)
        score = round(random.uniform(0.75, 0.95), 2)
        condition = random.choice(conditions)
        decision = "UNCERTAIN" if condition == "FOG_RAIN" else random.choice(states)
        
        payload_a = {
            "event_id": str(uuid.uuid4()),
            "camera_id": "cam-border-01",
            "timestamp": timestamp_a,
            "zone_id": "sector_alpha",
            "detection_class": "person",
            "confidence": confidence,
            "scene_condition": condition,
            "camera_health_state": "OK",
            "decision_state": decision,
            "clip_ref": f"demo_clip_{track_num}",
            "reliability_score": score,
            "is_corroborated": False
        }
        
        events_to_send = [payload_a]
        
        if corroborate:
            # Generate the corroborating event for camera B slightly delayed
            payload_b = payload_a.copy()
            payload_b["event_id"] = str(uuid.uuid4())
            payload_b["camera_id"] = "cam-checkpoint-01"
            # Add a slight delay (e.g. they crossed the checkpoint a bit later)
            payload_b["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + random.randint(2, 5)))
            # Corroborate flag is set by the backend usually, but we simulate the events arriving
            events_to_send.append(payload_b)
        
        response = httpx.post(f"{backend_url}/api/sync/events", json=events_to_send)
        if response.status_code in [200, 201, 202]:
            print(f"Injected {len(events_to_send)} simulated events")
        else:
            print(f"Failed to inject: {response.status_code} - {response.text}")
            
    except Exception as e:
        print(f"Simulator error: {e}")
