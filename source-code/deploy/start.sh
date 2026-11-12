#!/usr/bin/env bash
# Start the Timesheet application.
set -euo pipefail
cd "$(dirname "$0")"
docker compose --env-file config.env up -d
PORT="$(grep -E '^TS_PORT=' config.env | cut -d= -f2 | tr -d '[:space:]')"
echo "Started. Open http://<this-server's-address>:${PORT:-8077}"
