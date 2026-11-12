#!/usr/bin/env bash
# Stop the VM when nobody has actually used it for IDLE_HOURS.
#
# Runs ON the VM from cron every 15 minutes. Three guards must all agree before
# anything stops -- a false stop during a client's upload costs far more than a
# few hours of idle compute.
#
#   1. No work in flight. /api/health reports queue_depth and progress.active.
#   2. No HUMAN ACTION in the idle window, read from the audit table.
#   3. gcloud can actually stop the instance (see enable_cost_scope.sh).
#
# Why the audit table and not the web log. The public IP is probed constantly
# by internet scanners, so "any request" never goes quiet. Caddy's user_id
# marks authenticated requests -- but the UI polls every 1.5 seconds, so a
# browser tab left open overnight produced 9,286 "authenticated" requests
# against only 260 real actions. A tab nobody is looking at is not usage.
# The audit table records what a PERSON did: created a batch, saved a page,
# corrected a field, downloaded an export. That is the honest signal.
set -uo pipefail

IDLE_HOURS="${IDLE_HOURS:-3}"
ZONE="${ZONE:-asia-south1-a}"
NAME="${NAME:-timesheet-prod}"
STATE_LOG="${STATE_LOG:-$HOME/timesheet-app/data/autosleep.log}"

say() { echo "$(date -Is) $*" >> "$STATE_LOG"; }

health=$(sudo docker exec timesheet-app sh -c \
  'curl -s --max-time 10 http://127.0.0.1:8077/api/health' 2>/dev/null || echo '')
if [ -z "$health" ]; then
  say "SKIP app not answering health -- not safe to judge idleness"; exit 0
fi
if echo "$health" | grep -q '"active":true'; then
  say "SKIP a batch is being processed"; exit 0
fi
qd=$(echo "$health" | sed -n 's/.*"queue_depth":\([0-9]*\).*/\1/p')
if [ -n "$qd" ] && [ "${qd:-0}" -gt 0 ]; then
  say "SKIP queue_depth=$qd"; exit 0
fi

# Human actions only. 'system' is the extractor logging its own work, so it is
# excluded -- otherwise the machine would keep itself awake.
recent=$(sudo docker exec -i timesheet-app python - "$IDLE_HOURS" <<'PY' 2>/dev/null || echo ERR
import sqlite3, sys, time
hours = float(sys.argv[1])
c = sqlite3.connect("/data/timesheets.db")
n = c.execute("SELECT COUNT(*) FROM audit WHERE actor != 'system' AND ts > ?",
              (time.time() - hours * 3600,)).fetchone()[0]
print(n)
PY
)
case "${recent:-}" in (*[!0-9]*|"") recent=ERR ;; esac
if [ "$recent" = "ERR" ]; then
  say "SKIP could not read the audit table"; exit 0
fi
if [ "${recent:-1}" -gt 0 ]; then
  say "SKIP $recent human action(s) in the last ${IDLE_HOURS}h"; exit 0
fi

say "IDLE ${IDLE_HOURS}h, nothing in flight -> shutting down cleanly"

# --- close the database properly before the machine goes away --------------
#
# The database runs in WAL mode, so recent commits may still be sitting in
# timesheets.db-wal rather than the main file. A hard instance stop would
# leave them there; SQLite does recover a WAL on next open, but the honest
# way to protect data is not to rely on recovery. TRUNCATE folds the WAL into
# the database and empties it, so what lands on the disk is a complete file.
sudo docker exec timesheet-app python -c "
import sqlite3
c = sqlite3.connect('/data/timesheets.db')
c.execute('PRAGMA wal_checkpoint(TRUNCATE)')
c.close()
" >>"$STATE_LOG" 2>&1 && say "  database checkpointed" || say "  WARNING checkpoint failed"

# Stop the containers so every process gets SIGTERM and flushes, rather than
# being cut off when the VM powers down.
( cd "$HOME/timesheet-app" && sudo docker compose     -f docker-compose.yml -f gcp/docker-compose.prod.yml     --env-file config.env --env-file .env stop ) >>"$STATE_LOG" 2>&1   && say "  containers stopped cleanly" || say "  WARNING container stop failed"

if ! gcloud compute instances stop "$NAME" --zone "$ZONE" --quiet >>"$STATE_LOG" 2>&1; then
  say "FAILED to stop -- the VM service account lacks compute scope."
  say "       Run gcp/enable_cost_scope.sh once to grant it."
fi
