import json
import time
import subprocess
from fastapi import FastAPI, Request
import uvicorn
import threading

app = FastAPI()

capture_data = {
    "telemetry": [],
    "events": []
}

start_time = time.time()

@app.post("/system/telemetry")
async def capture_telemetry(request: Request):
    payload = await request.json()
    t = time.time() - start_time
    capture_data["telemetry"].append({"time": t, "payload": payload})
    return {"status": "ok"}

@app.post("/events")
async def capture_events(request: Request):
    payload = await request.json()
    t = time.time() - start_time
    capture_data["events"].append({"time": t, "payload": payload})
    return {"status": "ok"}

@app.put("/cameras/{cam_id}/public-key")
async def capture_pubkey(cam_id: str, request: Request):
    return {"status": "ok"}

@app.post("/cameras/{cam_id}/health")
async def capture_health(cam_id: str, request: Request):
    return {"status": "ok"}

def run_server():
    uvicorn.run(app, host="127.0.0.1", port=8444)

if __name__ == "__main__":
    t = threading.Thread(target=run_server, daemon=True)
    t.start()
    time.sleep(2)
    
    print("Starting demo_runner.py...")
    # Run demo_runner.py and wait for it to finish (or wait 80 seconds)
    p = subprocess.Popen([
        "python", "edge/demo_runner.py",
        "--backend-url", "http://127.0.0.1:8444",
        "--video-source", "demo/videos/vtest.avi"
    ])
    
    # Wait for the video length (~79 seconds)
    time.sleep(85)
    p.terminate()
    
    with open("backend/mock_vtest_data.json", "w") as f:
        json.dump(capture_data, f)
    
    print("Saved capture data!")
