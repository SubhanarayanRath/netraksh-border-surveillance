# NETRAKSH Command Center — SIH 2026 Prototype

NETRAKSH is an edge-based, offline-first perimeter surveillance and reliability system.

This repository contains the prototype implementation created for SIH 2026. It demonstrates a complete end-to-end pipeline from video ingestion and detection to cryptographic evidence packaging and store-and-forward syncing to a centralized dashboard.

## Demo Scope & Architecture

This is a **CPU-only software prototype**. It runs entirely on local compute without requiring specialized hardware (no Jetson, no TensorRT, no dedicated GPUs). 

**What is actually implemented:**
*   **Edge Pipeline:** Runs YOLOv8n object detection on a CPU, followed by ByteTrack for tracking.
*   **Reliability Engine:** Calculates a dynamic reliability score (`R = 0.40D + 0.20T + 0.20S + 0.20H`) taking into account detection confidence, track continuity, scene conditions (e.g., fog), and hardware health (e.g., frozen frames).
*   **Two-Camera Corroboration:** The architecture is built to support multiple cameras. The demo instantiates 2 parallel edge pipelines (`cam-border-01` and `cam-checkpoint-01`). If both cameras detect the same class within a plausible travel-time window, the event receives a cross-camera temporal/spatial corroboration boost (`Tc`). *Note: This is strictly spatial/temporal plausibility, not identity re-identification.*
*   **Cryptographic Evidence:** Every event is packaged at the edge with its source frame, hashed (SHA-256), and appended to a local SQLite hash-chain ledger to guarantee temporal sequence integrity.
*   **Offline-First Sync:** If the network fails, events queue locally on the edge. When connectivity is restored, they are uploaded in priority-order (HIGH severity first).
*   **Dashboard UI:** A React frontend for monitoring camera health, viewing events, triggering integrity verification, and simulating scenarios.

**What is NOT claimed:**
*   No live physical cameras are used in the demo. Both edge pipelines ingest from a local `vtest.avi` video file to guarantee repeatable detections during judging. The adapter supports RTSP out-of-the-box, but the demo strictly uses static video.
*   No GPU hardware acceleration. All performance metrics shown in the dashboard are real `perf_counter()` timings measured on the local CPU prototype.

## How to  Run the Demo

**Prerequisites:**
- Python 3.10+ installed and on your `PATH`.
- Node.js / npm installed (if you need to rebuild the frontend, though `frontend/dist` is served directly).
- Dependencies installed: `pip install -r requirements.txt`

**Start the System:**
Simply run the included batch script from the repository root:
```bash
start_netraksh.cmd
```
This script will:
1. Start the FastAPI backend and serve the frontend UI on port 8443.
2. Launch Edge Pipeline A (`cam-border-01`).
3. Pause for 15 seconds (to create realistic temporal separation for corroboration).
4. Launch Edge Pipeline B (`cam-checkpoint-01`).

**Access the Dashboard:**
- Main Dashboard: [http://localhost:8443/](http://localhost:8443/)
- Camera Health: [http://localhost:8443/camera-health](http://localhost:8443/camera-health)
- Performance Metrics: [http://localhost:8443/performance](http://localhost:8443/performance)
- Evidence Vault: [http://localhost:8443/evidence](http://localhost:8443/evidence)

## Demo Scenarios

The frontend includes a **Demo Scenario Control** sidebar that allows you to dynamically alter the state of the running edge pipelines to prove resilience:
1.  **Normal Ops:** Full YOLO detection → R score calculation → DETECTED events.
2.  **Dense Fog:** Injects Gaussian blur + haze into the frame. The `SceneConditionClassifier` detects low contrast (`FOG_RAIN`), lowering the `S` variable in the reliability formula, often producing `UNCERTAIN` events.
3.  **Sensor Failure:** Injects static grey frames. The `CameraHealthMonitor` detects zero pixel variance, marks the camera as `FAILED`, and Gate 1 immediately overrides the decision to `ABSTAIN` (bypassing R calculation entirely).
4.  **Offline State:** Instructs the edge sync client to simulate a network outage. Events are queued in local SQLite storage and the dashboard sync status changes to `BUFFERING`. Clicking "Normal Ops" restores the connection, draining the queue in priority-order.

## Contingencies
If you experience issues launching the demo, please refer to [CONTINGENCY.md](CONTINGENCY.md) for manual fallback commands and troubleshooting steps.
