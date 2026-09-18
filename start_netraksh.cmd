@echo off
setlocal

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
set "PYTHON=%ROOT%\venv\Scripts\python.exe"
set "FRONTEND=%ROOT%\frontend"
set "VIDEO=%ROOT%\demo\videos\vtest.avi"
set "BACKEND_URL=http://127.0.0.1:8443"

echo ========================================================
echo  NETRAKSH local SIH demo launcher
echo ========================================================

if not exist "%PYTHON%" (
  echo ERROR: Project virtual environment was not found:
  echo        %PYTHON%
  exit /b 1
)
if not exist "%FRONTEND%\package.json" (
  echo ERROR: Frontend package.json was not found.
  exit /b 1
)
if not exist "%VIDEO%" (
  echo ERROR: Bootstrap surveillance video was not found:
  echo        %VIDEO%
  exit /b 1
)
where npm.cmd >nul 2>&1
if errorlevel 1 (
  echo ERROR: npm.cmd is not available on PATH.
  exit /b 1
)

echo [1/4] Backend       http://127.0.0.1:8443
start "NETRAKSH Backend" cmd /k "cd /d "%ROOT%" && set "PYTHONPATH=%ROOT%" && "%PYTHON%" -m uvicorn backend.main:app --host 127.0.0.1 --port 8443"

echo [2/4] Frontend      http://127.0.0.1:5173
start "NETRAKSH Frontend" cmd /k "cd /d "%FRONTEND%" && npm.cmd run dev -- --host 127.0.0.1 --port 5173"

echo Waiting briefly for the backend before starting edge workers...
timeout /t 5 /nobreak >nul

echo [3/4] Edge worker   cam-border-01
start "NETRAKSH Edge - cam-border-01" cmd /k "cd /d "%ROOT%" && set "PYTHONPATH=%ROOT%" && set "SYNC_INTERVAL_SECONDS=2" && "%PYTHON%" edge\demo_runner.py --camera-id cam-border-01 --video-source "%VIDEO%" --backend-url %BACKEND_URL%"

echo [4/4] Edge worker   cam-checkpoint-01
start "NETRAKSH Edge - cam-checkpoint-01" cmd /k "cd /d "%ROOT%" && set "PYTHONPATH=%ROOT%" && set "SYNC_INTERVAL_SECONDS=2" && "%PYTHON%" edge\demo_runner.py --camera-id cam-checkpoint-01 --video-source "%VIDEO%" --backend-url %BACKEND_URL%"

echo.
echo All four services were launched in separate windows.
echo Login:    http://127.0.0.1:5173/login
echo Backend:  http://127.0.0.1:8443
echo.
echo The workers use the repository's labelled demo surveillance clip until
echo Dashboard ADD VIDEO supplies a new real upload session. Close each named
echo service window to stop it; this launcher never kills unrelated processes.

endlocal
