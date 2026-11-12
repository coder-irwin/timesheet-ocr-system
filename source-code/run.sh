#!/usr/bin/env bash
# Timesheet Extraction & Validation -- macOS/Linux launcher.
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -x ".venv/bin/python" ]; then
  echo "[1/3] Creating Python environment (first run only)..."
  python3 -m venv .venv
  echo "[2/3] Installing dependencies..."
  ./.venv/bin/pip install --upgrade pip -q
  ./.venv/bin/pip install -r requirements.txt
else
  echo "[1/3] Environment found."; echo "[2/3] Skipping install."
fi
echo "[3/3] Starting server on http://127.0.0.1:8077"
exec ./.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8077
