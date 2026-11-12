@echo off
REM Stop the Timesheet application.
REM Your data is NOT deleted -- everything in the "data" folder stays as it is.
cd /d "%~dp0"
docker compose --env-file config.env down
echo Stopped. Your data in the "data" folder is untouched.
echo Start it again with start.bat
pause
