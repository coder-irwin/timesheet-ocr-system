@echo off
REM Restart the Timesheet application.
REM Run this after editing config.env -- changes only apply on restart.
cd /d "%~dp0"
docker compose --env-file config.env up -d --force-recreate
echo Restarted with the current settings from config.env.
pause
