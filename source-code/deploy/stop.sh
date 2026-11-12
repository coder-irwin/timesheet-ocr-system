#!/usr/bin/env bash
# Stop the Timesheet application.
#
# Your data is NOT deleted -- the roster, uploaded documents, database and
# exports all live in the "data" folder and stay exactly as they are.
set -euo pipefail
cd "$(dirname "$0")"
docker compose --env-file config.env down
echo "Stopped. Your data in the 'data' folder is untouched."
echo "Start it again with ./start.sh"
