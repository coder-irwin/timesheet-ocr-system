#!/usr/bin/env bash
# ============================================================================
#  Timesheet OCR — one-command server setup
#
#  Run this ON the server, after copying the files across. It does everything:
#  installs Docker, installs the handwriting helper, sets up your login,
#  obtains the HTTPS certificate and starts the application.
#
#      ./setup-server.sh
#
#  It asks you three questions and prints exactly what to do next. If anything
#  fails it stops and tells you what went wrong in plain language, rather than
#  leaving a half-working server.
# ============================================================================
set -euo pipefail

say()  { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
ok()   { printf '    \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '    \033[33m!\033[0m %s\n' "$*"; }
die()  { printf '\n\033[1;31mSTOPPED: %s\033[0m\n\n' "$*" >&2; exit 1; }

APP="$HOME/timesheet-app"
[ -d "$APP" ] || die "I cannot find $APP.
    You need to copy the files to this server first.
    See Step 4 of GUIDE-B-PUT-IT-ONLINE.md."

# ---------------------------------------------------------------------------
say "Step 1 of 7 — checking this server"
# ---------------------------------------------------------------------------
MEM_MB=$(free -m 2>/dev/null | awk '/^Mem:/{print $2}' || echo 0)
CPUS=$(nproc 2>/dev/null || echo 0)
DISK_GB=$(df -BG --output=avail / 2>/dev/null | tail -1 | tr -dc '0-9' || echo 0)
ok "processors: $CPUS    memory: ${MEM_MB} MB    free disk: ${DISK_GB} GB"
USE_HELPER=1
if [ "$MEM_MB" -lt 14000 ]; then
  warn "Less than 14 GB of memory. The handwriting helper needs about 4 GB"
  warn "on top of the application, so I will leave it switched OFF."
  warn "Everything still works; handwritten names read slightly less well."
  USE_HELPER=0
fi
[ "$DISK_GB" -lt 15 ] && die "Only ${DISK_GB} GB of disk free. You need at least 20 GB."

# ---------------------------------------------------------------------------
say "Step 2 of 7 — installing Docker"
# ---------------------------------------------------------------------------
if command -v docker >/dev/null 2>&1; then
  ok "Docker is already installed ($(docker --version | cut -d, -f1))"
else
  curl -fsSL https://get.docker.com | sh >/dev/null 2>&1 || die "Docker install failed. Are you online?"
  sudo usermod -aG docker "$USER" 2>/dev/null || true
  ok "Docker installed"
fi
DOCKER="docker"; docker ps >/dev/null 2>&1 || DOCKER="sudo docker"
$DOCKER compose version >/dev/null 2>&1 || die "The Docker Compose plugin is missing.
    On Ubuntu: sudo apt-get install -y docker-compose-plugin"
ok "Docker is working"

# ---------------------------------------------------------------------------
say "Step 3 of 7 — the handwriting helper (optional)"
# ---------------------------------------------------------------------------
if [ "$USE_HELPER" = "1" ]; then
  if command -v ollama >/dev/null 2>&1 && ollama list 2>/dev/null | grep -q qwen3-vl; then
    ok "already installed"
  else
    command -v ollama >/dev/null 2>&1 || curl -fsSL https://ollama.com/install.sh | sh >/dev/null 2>&1
    sudo mkdir -p /etc/systemd/system/ollama.service.d
    printf '[Service]\nEnvironment=OLLAMA_HOST=0.0.0.0:11434\nEnvironment=OLLAMA_KEEP_ALIVE=2h\n' \
      | sudo tee /etc/systemd/system/ollama.service.d/override.conf >/dev/null
    sudo systemctl daemon-reload; sudo systemctl restart ollama
    printf '    waiting for it to start'
    for _ in $(seq 1 90); do curl -sf http://127.0.0.1:11434/api/tags >/dev/null 2>&1 && break; printf '.'; sleep 2; done
    printf '\n'
    echo "    downloading the handwriting model (about 3.3 GB, a few minutes)..."
    ollama pull qwen3-vl:4b >/dev/null 2>&1 || true
    if ollama list 2>/dev/null | grep -q qwen3-vl; then
      ok "handwriting helper ready"
    else
      warn "The download did not finish. Carrying on without it."
      warn "You can run 'ollama pull qwen3-vl:4b' later and restart."
      USE_HELPER=0
    fi
  fi
else
  ok "skipped (not enough memory on this server)"
fi

# ---------------------------------------------------------------------------
say "Step 4 of 7 — loading the application"
# ---------------------------------------------------------------------------
cd "$APP"
if [ -f timesheet-app-amd64.tar.gz ]; then
  $DOCKER load -i timesheet-app-amd64.tar.gz >/dev/null
  IMG=$($DOCKER images --format '{{.Repository}}:{{.Tag}}' | grep '^timesheet-app:' | head -1)
  [ -n "$IMG" ] || die "The file loaded but no timesheet-app image appeared."
  $DOCKER tag "$IMG" timesheet-app:2.0.0
  ok "loaded $IMG"
elif $DOCKER images --format '{{.Repository}}:{{.Tag}}' | grep -q '^timesheet-app:2.0.0$'; then
  ok "already loaded"
else
  die "I cannot find timesheet-app-amd64.tar.gz in $APP.
    That is the application itself. See Step 3 of GUIDE-B-PUT-IT-ONLINE.md."
fi

# ---------------------------------------------------------------------------
say "Step 5 of 7 — your web address"
# ---------------------------------------------------------------------------
IP=$(curl -s --max-time 10 https://api.ipify.org 2>/dev/null || true)
[ -n "$IP" ] || IP=$(hostname -I 2>/dev/null | awk '{print $1}')
echo
echo "    This server's public address is: $IP"
echo
echo "    If you own a web address (like timesheets.yourcompany.com) and have"
echo "    pointed it at $IP, type it below."
echo "    Otherwise just press ENTER and I will use $IP.nip.io, which works"
echo "    straight away and still gives you a proper padlock in the browser."
echo
read -r -p "    Web address [$IP.nip.io]: " SITE
SITE="${SITE:-$IP.nip.io}"
ok "using https://$SITE"

# ---------------------------------------------------------------------------
say "Step 6 of 7 — your login"
# ---------------------------------------------------------------------------
mkdir -p gcp
if [ -s gcp/users.caddy ]; then
  ok "logins already set up ($(wc -l < gcp/users.caddy | tr -d ' ') account(s))"
else
  echo
  read -r -p "    Choose a username [team]: " U; U="${U:-team}"
  while :; do
    read -r -s -p "    Choose a password (at least 10 characters): " P1; echo
    [ ${#P1} -lt 10 ] && { echo "    Too short, try again."; continue; }
    read -r -s -p "    Type it again: " P2; echo
    [ "$P1" = "$P2" ] && break || echo "    They did not match, try again."
  done
  HASH=$($DOCKER run --rm caddy:2 caddy hash-password --plaintext "$P1" 2>/dev/null) \
    || die "Could not scramble the password. Is Docker working?"
  printf '%s %s\n' "$U" "$HASH" > gcp/users.caddy
  chmod 600 gcp/users.caddy
  ok "login created for '$U' (the password is stored scrambled, never in plain text)"
  unset P1 P2
fi

# ---------------------------------------------------------------------------
say "Step 7 of 7 — starting up"
# ---------------------------------------------------------------------------
# These two must exist BEFORE Docker starts, or it creates empty folders in
# their place and the application refuses to run. This is the single most
# common thing that goes wrong.
[ -d overlay/app ] || die "The 'overlay' folder is missing from $APP.
    Copy it across and run this again. Without it the application cannot start."
[ -s gcp/Caddyfile ] || die "gcp/Caddyfile is missing from $APP."
[ -s gcp/docker-compose.prod.yml ] || die "gcp/docker-compose.prod.yml is missing."
ok "all required files are present"

printf 'SITE=%s\nTEAM_HASH=unused\nCLIENT_HASH=unused\n' "$SITE" > .env
sed -i.bak "s/^TS_VLM_HEADER=.*/TS_VLM_HEADER=$USE_HELPER/" config.env 2>/dev/null || true
ok "settings written (handwriting helper: $([ "$USE_HELPER" = 1 ] && echo ON || echo OFF))"

$DOCKER compose -f docker-compose.yml -f gcp/docker-compose.prod.yml \
  --env-file config.env --env-file .env up -d
printf '    starting'
for _ in $(seq 1 40); do
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "https://$SITE/" 2>/dev/null || echo 000)
  [ "$code" = "401" ] && break
  printf '.'; sleep 5
done
printf '\n'

echo
if [ "${code:-000}" = "401" ]; then
  printf '\033[1;32m'
  cat <<EOT
  ========================================================================
   IT IS LIVE
  ========================================================================
EOT
  printf '\033[0m'
  echo "   Open this in a browser:   https://$SITE"
  echo "   Sign in with the username and password you just chose."
  echo
  echo "   The '401' you may see from a tool is correct — it means the login"
  echo "   gate is working and refusing visitors who have not signed in."
else
  printf '\033[1;33m'
  echo "  Not answering yet (got '${code:-no reply}')."
  printf '\033[0m'
  echo "   This is usually one of two things:"
  echo
  echo "   1. The certificate is still being issued. Wait two minutes and open"
  echo "      https://$SITE in a browser."
  echo "   2. Ports 80 and 443 are not open to the internet on this server."
  echo "      Open them in your provider's firewall, then run:"
  echo "         $DOCKER compose -f docker-compose.yml -f gcp/docker-compose.prod.yml \\"
  echo "           --env-file config.env --env-file .env restart"
  echo
  echo "   To see what the gatekeeper is complaining about:"
  echo "      $DOCKER compose logs caddy | tail -30"
fi
echo
echo "   Useful later:"
echo "     $DOCKER compose ps                       is it running?"
echo "     $DOCKER compose logs -f timesheet        watch the application"
echo "     ./gcp/user.sh add <name>                 add another person"
echo
