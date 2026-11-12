#!/usr/bin/env bash
# Restore a production backup onto a freshly deployed VM, and bring the app up
# on the overlay code that was actually live.
#
#   ./gcp/restore.sh /path/to/ocr-prod-final-backup.tgz
#
# Why this exists. deploy_gcp.sh builds a BLANK production box: it uploads the
# image, the compose files and roster/designations, and nothing else. It does
# NOT upload overlay/ or gcp/users.caddy, yet gcp/docker-compose.prod.yml
# bind-mounts 13 overlay files and the Caddyfile does `import users.caddy`.
# Two consequences, both of which have bitten this project:
#
#   * A bind-mount whose host path is missing is turned by Docker into an empty
#     DIRECTORY, not an error. The container then imports a directory where a
#     module should be. That is how the app went down for 4 minutes on
#     21 Sep 2026, and it is silent -- the version string still looks right.
#   * Caddy will not start at all without users.caddy, so the whole site 502s.
#
# So this script always clears the mount points first, puts the real files in
# place, and only then starts compose. It verifies the running container is
# serving the overlay (by byte size) and reports the live PIPELINE_VERSION,
# because "it started" is not the same as "it is running the right code".
set -euo pipefail

TGZ="${1:?usage: ./gcp/restore.sh /path/to/backup.tgz}"
ZONE="${ZONE:-asia-south1-a}"
VM="${VM:-timesheet-prod}"
# Resolved from the VM itself, so this works whatever the SSH user is called.
REMOTE=""   # set after the first ssh call below

step(){ printf '\n\033[1;34m== %s\033[0m\n' "$*"; }
ssh_vm(){ gcloud compute ssh "$VM" --zone="$ZONE" --tunnel-through-iap --command="$1"; }
REMOTE="$(gcloud compute ssh "$VM" --zone="$ZONE" --tunnel-through-iap --command='echo $HOME' 2>/dev/null | tr -d "\r")/timesheet-app"
[ -n "$REMOTE" ] || { echo "could not resolve the app directory on $VM"; exit 1; }
echo "app directory on the VM: $REMOTE"

[ -f "$TGZ" ] || { echo "no such file: $TGZ"; exit 1; }

step "1/6 upload the restore bundle ($(du -h "$TGZ" | cut -f1))"
gcloud compute scp --zone="$ZONE" --tunnel-through-iap "$TGZ" "$VM":/tmp/restore.tgz

step "2/6 stop the app (leave Caddy's cert cache alone)"
ssh_vm "cd $REMOTE && sudo docker compose -f docker-compose.yml -f gcp/docker-compose.prod.yml --env-file config.env --env-file .env stop || true"

step "3/6 clear every overlay mount point, then restore"
# Remove whatever is at each mount point -- empty dir or stale file -- so the
# extract below lands a real file there.
ssh_vm "sudo rm -rf $REMOTE/overlay $REMOTE/gcp/users.caddy &&
        sudo mkdir -p $REMOTE/data $REMOTE/overlay $REMOTE/gcp &&
        sudo tar -xzf /tmp/restore.tgz -C $REMOTE &&
        sudo chown -R \$(id -u):\$(id -g) $REMOTE/data $REMOTE/overlay 2>/dev/null || true;
        echo 'restored:'; sudo find $REMOTE/overlay -type f | wc -l; echo 'overlay files'"

step "4/6 verify the restore BEFORE starting anything"
ssh_vm "set -e
  for f in pipeline validate rowconf generic_grid ocr_engine clocks aarvi_form main db; do
    test -f $REMOTE/overlay/app/\$f.py || { echo \"MISSING overlay/app/\$f.py\"; exit 1; }
  done
  test -s $REMOTE/gcp/users.caddy || { echo 'MISSING gcp/users.caddy'; exit 1; }
  test -s $REMOTE/data/timesheets.db || { echo 'MISSING data/timesheets.db'; exit 1; }
  echo 'overlay + users.caddy + database all present'
  grep -o 'PIPELINE_VERSION = \"[^\"]*\"' $REMOTE/overlay/app/pipeline.py"

step "5/6 start the app"
ssh_vm "cd $REMOTE && sudo docker compose -f docker-compose.yml -f gcp/docker-compose.prod.yml --env-file config.env --env-file .env up -d && sleep 25 && sudo docker compose ps"

step "6/6 confirm the CONTAINER is serving the overlay, not an empty dir"
ssh_vm "echo '--- overlay byte sizes as the container sees them ---'
  for f in pipeline rowconf generic_grid ocr_engine clocks validate; do
    printf '  %-14s ' \$f
    sudo docker exec timesheet-app sh -c \"wc -c < /app/app/\$f.py\" 2>/dev/null || echo 'UNREADABLE (empty dir?)'
  done
  echo '--- version the running app reports ---'
  sudo docker exec timesheet-app sh -c 'wget -qO- http://127.0.0.1:8077/api/health' 2>/dev/null | head -c 400; echo"

echo
echo "Restore done. Now run the end-to-end test from the repo:"
echo "  ./.venv/bin/python tools/e2e_prod_test.py --url https://<ip>.nip.io"
