@echo off
echo ========================================================
echo Starting NETRAKSH Command Center (SIH 2026 Prototype)
echo ========================================================

:: 1. Start the backend in the background (which now serves the built frontend)
echo Starting Backend API and Frontend Server...
set PYTHONPATH=%cd%
start /b cmd /c "C:\Users\hp\AppData\Local\Programs\Python\Python314\python.exe -m uvicorn backend.main:app --host 0.0.0.0 --port 8443 > backend.log 2>&1"

:: 2. Wait for backend to be ready
timeout /t 3 /nobreak > nul

:: 3. Start the simulated edge node
echo Starting Edge Node Simulator (edge-001)...
set EDGE_DEVICE_ID=edge-001
start /b cmd /c "C:\Users\hp\AppData\Local\Programs\Python\Python314\python.exe edge\main.py > edge.log 2>&1"

echo.
echo ========================================================
echo SYSTEM DEPLOYED SUCCESSFULLY
echo.
echo Access the NETRAKSH Border Intelligence Unit at:
echo http://localhost:8443
echo.
echo Logs are being written to backend.log and edge.log
echo Press any key to stop all services...
pause > nul

:: 4. Stop all spawned processes
taskkill /F /IM python.exe > nul 2>&1
echo Services stopped.
