#!/usr/bin/env bash
# Show what the application is reporting.
#
# This is the first thing to run if something is not working. Press Ctrl+C to
# stop watching. Nothing here changes anything -- it is read-only.
set -euo pipefail
cd "$(dirname "$0")"
echo "Showing the last 100 messages, then following live. Press Ctrl+C to exit."
echo "-----------------------------------------------------------------------"
docker compose --env-file config.env logs --tail=100 -f
