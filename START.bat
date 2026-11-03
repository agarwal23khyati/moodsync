@echo off
title MoodSync
cd /d "%~dp0backend"
if not exist .env copy .env.example .env >nul
if not exist venv (
  echo Setting up Python environment, first run only...
  python -m venv venv
)
call venv\Scripts\activate
pip install -q -r requirements.txt
rem agent service (Styling / Task / Music / Recipe agents) in its own window
start "MoodSync agents (port 8001)" cmd /k "cd /d %~dp0backend && call venv\Scripts\activate && python -m uvicorn agent_service:app --port 8001"
timeout /t 4 >nul
start "" cmd /c "timeout /t 3 >nul & start http://localhost:8000"
python -m uvicorn main:app --port 8000
pause
