#!/bin/bash
# Double-click this file to start the Timesheet Digitiser.
# Everything runs on this computer -- no internet connection is used.
cd "$(dirname "$0")" || exit 1

if [ ! -x .venv/bin/python ]; then
  echo "Python environment missing. Run:  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
  read -r -p "Press Enter to close..."
  exit 1
fi

PORT=8077
# Free the port if a previous run is still holding it.
lsof -ti tcp:$PORT | xargs kill -9 2>/dev/null

echo "Starting Timesheet Digitiser on http://127.0.0.1:$PORT"
( sleep 3; open "http://127.0.0.1:$PORT" ) &
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port $PORT
