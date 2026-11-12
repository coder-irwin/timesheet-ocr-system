#!/usr/bin/env bash
#
# Timesheet Extraction & Validation -- one-time installer (Linux / Mac).
#
# Run this ONCE, the first time you set the application up:
#
#     ./install.sh
#
# It works out what kind of processor this server has, loads the matching
# version of the application, starts it, and waits until it confirms the
# application is genuinely responding.
#
# Afterwards use start.sh / stop.sh / restart.sh for day-to-day running.

set -euo pipefail
cd "$(dirname "$0")"

IMAGE_TAG="timesheet-app:2.0.0"

echo "==============================================================="
echo " Timesheet Extraction & Validation -- installer"
echo "==============================================================="
echo

# --- 1. Is Docker installed and usable? -------------------------------------
if ! command -v docker >/dev/null 2>&1; then
  echo "PROBLEM: Docker is not installed on this server."
  echo
  echo "Docker is the only thing this application needs. Ask your IT team to"
  echo "install it, or see 'Step 2' in START-HERE.md."
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "PROBLEM: Docker is installed but is not running (or this user is not"
  echo "         allowed to use it)."
  echo
  echo "  Try:  sudo systemctl start docker"
  echo "  If it says 'permission denied', see TROUBLESHOOTING.md."
  exit 1
fi
echo "[1/5] Docker is installed and running.                            OK"

# --- 2. Which processor does this server have? ------------------------------
ARCH="$(uname -m)"
case "$ARCH" in
  x86_64|amd64)
    VARIANT="amd64"
    echo "[2/5] Processor: Intel/AMD (${ARCH}).                             OK"
    ;;
  aarch64|arm64)
    VARIANT="arm64"
    echo "[2/5] Processor: ARM (${ARCH}).                                   OK"
    ;;
  *)
    echo "PROBLEM: unrecognised processor type '${ARCH}'."
    echo "         This package contains Intel/AMD and ARM versions only."
    exit 1
    ;;
esac

IMAGE_TAR="timesheet-app-${VARIANT}.tar.gz"
LOADED_TAG="timesheet-app:2.0.0-${VARIANT}"

# --- 3. Load the matching application image ---------------------------------
if [ ! -f "$IMAGE_TAR" ]; then
  echo "PROBLEM: '$IMAGE_TAR' is missing from this folder."
  echo "         The package is incomplete -- please request it again."
  exit 1
fi

if docker image inspect "$IMAGE_TAG" >/dev/null 2>&1; then
  echo "[3/5] Application already loaded.                                 OK"
else
  echo "[3/5] Loading the ${VARIANT} application into Docker (takes a minute)..."
  docker load -i "$IMAGE_TAR"
  docker tag "$LOADED_TAG" "$IMAGE_TAG"
  echo "      Loaded.                                                     OK"
fi

# --- 4. Check the data folder -----------------------------------------------
mkdir -p data
if [ ! -f "data/roster.csv" ]; then
  echo "[4/5] WARNING: data/roster.csv is missing. The application will start,"
  echo "      but it cannot match employee names until a roster is uploaded"
  echo "      through the web page."
else
  ROWS=$(( $(wc -l < data/roster.csv) - 1 ))
  echo "[4/5] Employee roster found (${ROWS} employees).                OK"
fi

# --- 5. Start it -------------------------------------------------------------
echo "[5/5] Starting the application..."
docker compose --env-file config.env up -d

PORT="$(grep -E '^TS_PORT=' config.env | cut -d= -f2 | tr -d '[:space:]')"
PORT="${PORT:-8077}"

printf "      Waiting for it to answer"
for _ in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:${PORT}/api/health" >/dev/null 2>&1; then
    echo
    echo
    echo "==============================================================="
    echo " SUCCESS -- the application is running."
    echo "==============================================================="
    echo
    echo " Open it in a web browser at:"
    echo
    echo "     http://<this-server's-address>:${PORT}"
    echo
    echo " From this server itself, that is:"
    echo "     http://localhost:${PORT}"
    echo
    echo " Next step: follow 'Step 5' in START-HERE.md to confirm it works,"
    echo " using the 10 sample timesheets in the demo folder."
    echo
    echo " It will now start automatically whenever the server reboots."
    echo "   Stop it:     ./stop.sh"
    echo "   Restart it:  ./restart.sh"
    echo "   See logs:    ./logs.sh"
    echo
    exit 0
  fi
  printf "."
  sleep 2
done

echo
echo "PROBLEM: the application started but is not answering after 2 minutes."
echo "Run  ./logs.sh  to see what it reported, then see TROUBLESHOOTING.md."
exit 1
