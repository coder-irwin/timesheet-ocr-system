#!/usr/bin/env bash
# Restart the Timesheet application.
#
# Run this after editing config.env -- settings changes only take effect on a
# restart.
set -euo pipefail
cd "$(dirname "$0")"
docker compose --env-file config.env up -d --force-recreate
PORT="$(grep -E '^TS_PORT=' config.env | cut -d= -f2 | tr -d '[:space:]')"
echo "Restarted with the current settings from config.env."
echo "Open http://<this-server's-address>:${PORT:-8077}"
