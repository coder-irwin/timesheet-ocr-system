@echo off
REM Timesheet Extraction ^& Validation -- one-time installer (Windows).
REM
REM Run this ONCE by double-clicking it, the first time you set up the
REM application. Afterwards use start.bat / stop.bat / restart.bat.

setlocal enabledelayedexpansion
cd /d "%~dp0"

set IMAGE_TAG=timesheet-app:2.0.0

echo ===============================================================
echo  Timesheet Extraction ^& Validation -- installer
echo ===============================================================
echo.

REM --- 1. Is Docker installed and running? ---------------------------------
where docker >nul 2>&1
if errorlevel 1 (
  echo PROBLEM: Docker is not installed on this machine.
  echo.
  echo Install "Docker Desktop" from https://www.docker.com/products/docker-desktop
  echo then run this file again.
  pause
  exit /b 1
)

docker info >nul 2>&1
if errorlevel 1 (
  echo PROBLEM: Docker is installed but not running.
  echo.
  echo Start "Docker Desktop" from the Start Menu, wait until it says
  echo "Engine running", then run this file again.
  pause
  exit /b 1
)
echo [1/5] Docker is installed and running.                            OK

REM --- 2. Which processor? --------------------------------------------------
set VARIANT=amd64
if /i "%PROCESSOR_ARCHITECTURE%"=="ARM64" set VARIANT=arm64
echo [2/5] Processor: %PROCESSOR_ARCHITECTURE% -^> using %VARIANT% version.        OK

set IMAGE_TAR=timesheet-app-%VARIANT%.tar.gz
set LOADED_TAG=timesheet-app:2.0.0-%VARIANT%

REM --- 3. Load the matching image ------------------------------------------
if not exist "%IMAGE_TAR%" (
  echo PROBLEM: "%IMAGE_TAR%" is missing from this folder.
  echo          The package is incomplete -- please request it again.
  pause
  exit /b 1
)

docker image inspect %IMAGE_TAG% >nul 2>&1
if errorlevel 1 (
  echo [3/5] Loading the %VARIANT% application into Docker ^(takes a minute^)...
  docker load -i "%IMAGE_TAR%"
  if errorlevel 1 (
    echo PROBLEM: loading the application failed. See the message above.
    pause
    exit /b 1
  )
  docker tag %LOADED_TAG% %IMAGE_TAG%
) else (
  echo [3/5] Application already loaded.                                 OK
)

REM --- 4. Data folder -------------------------------------------------------
if not exist "data" mkdir data
if not exist "data\roster.csv" (
  echo [4/5] WARNING: data\roster.csv is missing. The application will start,
  echo       but cannot match employee names until a roster is uploaded.
) else (
  echo [4/5] Employee roster found.                                      OK
)

REM --- 5. Start -------------------------------------------------------------
echo [5/5] Starting the application...
docker compose --env-file config.env up -d
if errorlevel 1 (
  echo PROBLEM: the application failed to start. See the message above,
  echo          and check TROUBLESHOOTING.md.
  pause
  exit /b 1
)

set TS_PORT=8077
for /f "usebackq tokens=1,2 delims==" %%A in ("config.env") do (
  if "%%A"=="TS_PORT" set TS_PORT=%%B
)

echo.
echo       Waiting for it to answer...
timeout /t 25 /nobreak >nul

curl -fsS http://127.0.0.1:!TS_PORT!/api/health >nul 2>&1
if errorlevel 1 (
  echo.
  echo The application was started but is not answering yet. It may need
  echo another minute. Check with logs.bat, and see TROUBLESHOOTING.md.
  pause
  exit /b 1
)

echo.
echo ===============================================================
echo  SUCCESS -- the application is running.
echo ===============================================================
echo.
echo  Open it in a web browser at:
echo.
echo      http://^<this-server's-address^>:!TS_PORT!
echo.
echo  From this machine itself, that is:
echo      http://localhost:!TS_PORT!
echo.
echo  Next step: follow "Step 5" in START-HERE.md to confirm it works,
echo  using the 10 sample timesheets in the demo folder.
echo.
echo  It will start automatically whenever this machine reboots.
echo    Stop it:     stop.bat
echo    Restart it:  restart.bat
echo    See logs:    logs.bat
echo.
pause
