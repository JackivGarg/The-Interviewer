@echo off
echo ====================================
echo   The Interviewer - Starting Servers
echo ====================================
echo.

echo [1/2] Starting Backend (FastAPI + Uvicorn)...
REM Run via python backend\main.py so the __main__ block's
REM ws_ping_interval=None / ws_ping_timeout=None is respected.
REM CLI flags --ws-ping-interval 0 do NOT disable pings (0 means 0.0s, not None).
start "Backend Server" cmd /k "cd /d %~dp0 && set PYTHONPATH=%%cd%% && venv\Scripts\python backend\main.py"

echo Waiting 4 seconds for backend to initialize...
timeout /t 4 /nobreak > nul

echo [2/2] Starting Frontend (Streamlit)...
start "Frontend Server" cmd /k "cd /d %~dp0 && venv\Scripts\streamlit run frontend/app.py"

echo.
echo Both servers started!
echo Backend:  http://localhost:8000
echo Frontend: http://localhost:8501
echo.
echo You can close this window.
pause
