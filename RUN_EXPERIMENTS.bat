@echo off
rem Run AFTER START.bat is up (both windows open). Produces results\results.md, figures and paper_text.md
cd /d "%~dp0"
call backend\venv\Scripts\activate
python experiments\run_experiments.py
pause
