#!/usr/bin/env bash
# Manage per-person logins on the production server. Run from the ocr_production folder.
#   ./gcp/user.sh add  <name> [password]     add a person (password generated if omitted; printed once)
#   ./gcp/user.sh remove <name>
#   ./gcp/user.sh list
# Names: letters, digits, dot, dash, underscore. Passwords are stored only as bcrypt hashes.
set -euo pipefail
Z="${ZONE:-asia-south1-a}"; P="${PROJ:-timesheet-ocr-prod}"; VM="${VM:-timesheet-prod}"
ssh_run(){ gcloud compute ssh "$VM" --zone="$Z" --project="$P" --tunnel-through-iap --quiet --command="$1" 2>&1 | grep -v "NumPy\|increasing_the_tcp\|^WARNING\|^$"; }
cmd="${1:-list}"; name="${2:-}"
case "$cmd" in
  add)
    [[ "$name" =~ ^[A-Za-z0-9._-]{2,40}$ ]] || { echo "bad name"; exit 1; }
    pass="${3:-$(openssl rand -base64 18 | tr -d '/+=' | cut -c1-14)}"
    ssh_run "cd ~/timesheet-app && H=\$(sudo docker run --rm caddy:2 caddy hash-password --plaintext '$pass') && (grep -v '^$name ' gcp/users.caddy 2>/dev/null; echo \"$name \$H\") > gcp/users.tmp && mv gcp/users.tmp gcp/users.caddy && sudo docker compose -f docker-compose.yml -f gcp/docker-compose.prod.yml --env-file config.env --env-file .env restart caddy >/dev/null 2>&1 && echo "login gate restarted""
    echo "login for $name: $pass"; printf "%s: %s\n" "$name" "$pass" >> gcp/.logins.txt ;;
  remove)
    ssh_run "cd ~/timesheet-app && grep -v '^$name ' gcp/users.caddy > gcp/users.tmp; mv gcp/users.tmp gcp/users.caddy && sudo docker compose -f docker-compose.yml -f gcp/docker-compose.prod.yml --env-file config.env --env-file .env restart caddy >/dev/null 2>&1 && echo removed"
    sed -i '' "/^$name: /d" gcp/.logins.txt 2>/dev/null || true ;;
  list) ssh_run "cut -d' ' -f1 ~/timesheet-app/gcp/users.caddy" ;;
  *) echo "usage: $0 add|remove|list [name] [password]"; exit 1 ;;
esac
