@echo off
rem Self-contained tests (in-memory database, no MongoDB needed)
cd /d "%~dp0"
call backend\venv\Scripts\activate
python -m pytest tests -q
pause
