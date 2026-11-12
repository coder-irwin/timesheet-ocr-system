@echo off
REM Double-click to start the Timesheet Digitiser on Windows.
REM Everything runs on this computer - no internet connection is used.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Python environment missing. Run:  python -m venv .venv ^&^& .venv\Scripts\pip install -r requirements.txt
  pause
  exit /b 1
)
start "" http://127.0.0.1:8077
.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8077
pause
