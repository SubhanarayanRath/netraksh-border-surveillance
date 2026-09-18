@echo off
setlocal

echo ========================================================
echo  NETRAKSH Command Center — SIH 2026 Prototype
echo  CPU-only prototype: no Jetson / GPU / TensorRT
echo ========================================================

set PYTHON=py
set PYTHONPATH=%cd%
set BACKEND_URL=http://localhost:8000
set SYNC_INTERVAL_SECONDS=2

:: -------------------------------------------------------
:: 1. Start the backend
:: -------------------------------------------------------
echo.
echo [1/3] Starting Backend Server on port 8000...
start "NETRAKSH-Backend" /b cmd /c "%PYTHON% -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 > backend.log 2>&1"

:: Wait for backend to initialise
timeout /t 4 /nobreak > nul
echo      Backend ready. Logs: backend.log

:: -------------------------------------------------------
:: 2. Start Camera Pipeline A — cam-border-01
:: -------------------------------------------------------
echo.
echo [2/3] Starting Edge Pipeline A: cam-border-01 (Border Post Alpha)
echo       Source: demo/videos/uploaded_demo.mp4  [DEMO FEED — not a live RTSP camera]
set CAMERA_ID=cam-border-01
set VIDEO_SOURCE=demo/videos/uploaded_demo.mp4
start "NETRAKSH-cam-border-01" /b cmd /c "%PYTHON% edge/demo_runner.py --camera-id cam-border-01 --video-source demo/videos/uploaded_demo.mp4 --backend-url %BACKEND_URL% > edge_cam_border_01.log 2>&1"

:: Brief stagger so both pipelines don't hammer the model load simultaneously,
:: and more importantly, so cam-checkpoint-01 is delayed behind cam-border-01.
:: This ensures cross-camera corroboration isn't just matching identical frames 
:: at exactly the same timestamp (which looks fake), but actually shows real Δt.
timeout /t 15 /nobreak > nul

:: -------------------------------------------------------
:: 3. Start Camera Pipeline B — cam-checkpoint-01
:: -------------------------------------------------------
echo [3/3] Starting Edge Pipeline B: cam-checkpoint-01 (Checkpoint Bravo)
echo       Source: demo/videos/uploaded_demo.mp4  [DEMO FEED — same video, independent pipeline]
start "NETRAKSH-cam-checkpoint-01" /b cmd /c "%PYTHON% edge/demo_runner.py --camera-id cam-checkpoint-01 --video-source demo/videos/uploaded_demo.mp4 --backend-url %BACKEND_URL% > edge_cam_checkpoint_01.log 2>&1"

echo.
echo ========================================================
echo  SYSTEM DEPLOYED
echo.
echo  Dashboard:  http://localhost:8443
echo  Cameras:    cam-border-01 (Border Post Alpha)
echo              cam-checkpoint-01 (Checkpoint Bravo)
echo  Logs:       backend.log
echo              edge_cam_border_01.log
echo              edge_cam_checkpoint_01.log
echo.
echo  Both camera feeds are demo video files (vtest.avi).
echo  Cross-camera corroboration fires automatically when
echo  both cameras detect the same class within the time window.
echo.
echo  Demo Scenario Control (in the browser sidebar):
echo    Normal    -^> full pipeline, DETECTED events
echo    Dense Fog -^> degraded S, may produce UNCERTAIN
echo    Failure   -^> ABSTAIN via Gate 1 (frozen frame)
echo    Offline   -^> local queue, header shows BUFFERING
echo.
echo  Press any key to STOP all services...
pause > nul

:: -------------------------------------------------------
:: 4. Graceful shutdown
:: -------------------------------------------------------
echo Stopping all NETRAKSH processes...
taskkill /F /IM python.exe /FI "WINDOWTITLE eq NETRAKSH-*" > nul 2>&1
:: If the windows were started with /b they might not have titles, fallback:
wmic process where "commandline like '%%backend.main:app%%' or commandline like '%%edge/demo_runner.py%%'" call terminate > nul 2>&1
echo Done.

endlocal
