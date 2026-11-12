@echo off
REM Show what the application is reporting. Read-only. Press Ctrl+C to exit.
cd /d "%~dp0"
docker compose --env-file config.env logs --tail=100 -f
