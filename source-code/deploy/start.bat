@echo off
REM Start the Timesheet application.
cd /d "%~dp0"
docker compose --env-file config.env up -d
echo Started. Open the address shown in START-HERE.md in your browser.
pause
