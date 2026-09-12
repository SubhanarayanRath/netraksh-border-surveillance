@echo off
setlocal

echo ========================================================
echo  NETRAKSH - Pointing Edge Cameras to Render Cloud
echo ========================================================

set PYTHON=py
set PYTHONPATH=%cd%
set BACKEND_URL=https://netraksh.onrender.com

echo.
echo [1/2] Starting Edge Pipeline A: cam-border-01
echo       Sending data to: %BACKEND_URL%
start "NETRAKSH-cam-border-01" /b cmd /c "%PYTHON% edge/demo_runner.py --camera-id cam-border-01 --video-source demo/videos/vtest.avi --backend-url %BACKEND_URL% > render_cam_border_01.log 2>&1"

timeout /t 15 /nobreak > nul

echo [2/2] Starting Edge Pipeline B: cam-checkpoint-01
start "NETRAKSH-cam-checkpoint-01" /b cmd /c "%PYTHON% edge/demo_runner.py --camera-id cam-checkpoint-01 --video-source demo/videos/vtest.avi --backend-url %BACKEND_URL% > render_cam_checkpoint_01.log 2>&1"

echo.
echo ========================================================
echo  Edge Cameras are running in the background!
echo  Check https://netraksh.onrender.com/ to see live events.
echo ========================================================
echo  Press any key to stop sending data to Render...
pause > nul

echo Stopping NETRAKSH edge processes...
wmic process where "commandline like '%%edge/demo_runner.py%%'" call terminate > nul 2>&1
echo Done.

endlocal
