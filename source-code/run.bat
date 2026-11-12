@echo off
REM ===================================================================
REM  Timesheet Extraction & Validation  --  Windows launcher
REM  Target: 16 GB RAM / 512 GB Windows laptop, CPU only, no GPU.
REM  Everything runs locally. No cloud, no API keys, no per-page cost.
REM ===================================================================
setlocal

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [1/3] Creating Python environment ^(first run only^)...
    python -m venv .venv
    if errorlevel 1 (
        echo.
        echo ERROR: Python was not found.
        echo Install Python 3.11 or 3.12 from python.org and tick
        echo "Add Python to PATH" during installation, then run this again.
        pause
        exit /b 1
    )
    echo [2/3] Installing dependencies ^(a few minutes, first run only^)...
    .venv\Scripts\python.exe -m pip install --upgrade pip -q
    .venv\Scripts\python.exe -m pip install -r requirements.txt
    if errorlevel 1 (
        echo ERROR: dependency installation failed. See messages above.
        pause
        exit /b 1
    )
) else (
    echo [1/3] Environment found.
    echo [2/3] Skipping install.
)

echo [3/3] Starting server...
echo.
echo    Open your browser at:  http://127.0.0.1:8077
echo    Press Ctrl+C in this window to stop.
echo.

start "" http://127.0.0.1:8077
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8077

endlocal
