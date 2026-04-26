@echo off
echo ==============================================
echo        Starting The Interviewer Project
echo ==============================================

echo [1/2] Starting Backend API on port 8000...
start "Interviewer Backend" cmd /k "cd /d %~dp0 && set PYTHONPATH=%%cd%% && venv\Scripts\python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --ws wsproto"

echo Waiting 4 seconds for backend to initialize...
timeout /t 4 /nobreak > nul

echo [2/2] Starting Frontend UI...
start "Interviewer Frontend" cmd /k "cd /d %~dp0 && venv\Scripts\streamlit run frontend/app.py"

echo.
echo Both servers are starting in separate windows!
echo Backend:  http://localhost:8000
echo Frontend: http://localhost:8501
echo.
echo You can close this window.
pause
