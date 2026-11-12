#!/usr/bin/env bash
# Assemble a deployable staging directory from this repository.
#
#   ./deployment/prepare-deploy.sh                 # stage only
#   ./deployment/prepare-deploy.sh --build-image   # stage + build the amd64 image
#
# WHY THIS EXISTS
# ---------------
# deploy_gcp.sh and restore.sh were written against the original working
# directory, which looked like this:
#
#     ocr_production/
#       gcp/              the scripts
#       timesheet-app/    the app bundle: image tarball, compose, config, data/
#
# This repository is organised for reading, not for deploying:
#
#     <repo>/
#       deployment/       the scripts            (was gcp/)
#       source-code/      the app + deploy/      (was timesheet-app/)
#       reference-data/   roster + fixtures
#
# So deploy_gcp.sh's APP_DIR resolves to a directory that does not exist, and
# every path it copies from is somewhere else. Rather than rewrite a deploy
# script that has been proven in a real deployment, this script builds the
# layout it expects. Run it once, then deploy from the staging directory.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STAGE="${STAGE:-$ROOT/_deploy-staging}"
BUILD_IMAGE=0
[ "${1:-}" = "--build-image" ] && BUILD_IMAGE=1

step(){ printf '\n\033[1;34m== %s\033[0m\n' "$*"; }

step "1/5 staging layout at $STAGE"
rm -rf "$STAGE"
mkdir -p "$STAGE/timesheet-app/data" "$STAGE/gcp"

step "2/5 the app bundle (-> timesheet-app/)"
cp "$ROOT/source-code/deploy/docker-compose.yml" \
   "$ROOT/source-code/deploy/config.env" \
   "$ROOT/source-code/deploy/install.sh" \
   "$ROOT/source-code/deploy/START-HERE.md" \
   "$ROOT/source-code/deploy/TROUBLESHOOTING.md" "$STAGE/timesheet-app/"
echo "  compose, config.env, install.sh and the operator docs"

step "3/5 reference data the app needs at runtime (-> timesheet-app/data/)"
if [ -f "$ROOT/reference-data/roster.csv" ]; then
  cp "$ROOT/reference-data/roster.csv" "$ROOT/reference-data/designations.csv" "$STAGE/timesheet-app/data/"
  echo "  roster.csv ($(( $(wc -l < "$ROOT/reference-data/roster.csv") - 1 )) employees) + designations.csv"
else
  echo "  NOT FOUND: reference-data/roster.csv"
  echo "  This public repository excludes employee data. Obtain roster.csv and"
  echo "  designations.csv from the data owner and place them in:"
  echo "    $STAGE/timesheet-app/data/"
  echo "  The app runs without them, but cannot match any identity."
fi

step "4/5 the deployment scripts and config (-> gcp/)"
# deploy_gcp.sh reads $APP_DIR/../gcp/{Caddyfile,docker-compose.prod.yml}
cp "$ROOT/deployment/"*.sh "$ROOT/deployment/"*.py "$ROOT/deployment/Caddyfile" \
   "$ROOT/deployment/docker-compose.prod.yml" "$ROOT/deployment/users.caddy.example" "$STAGE/gcp/" 2>/dev/null || true
cp -R "$ROOT/deployment/overlay" "$STAGE/gcp/../overlay"
chmod +x "$STAGE/gcp/"*.sh
# setup-server.sh runs ON the server; it must travel with the rest.
cp "$ROOT/deployment/setup-server.sh" "$STAGE/gcp/" 2>/dev/null || true
echo "  $(ls "$STAGE/gcp" | wc -l | tr -d ' ') files, plus the application overlay"

step "5/5 the image"
if [ "$BUILD_IMAGE" = "1" ]; then
  command -v docker >/dev/null || { echo "docker not found"; exit 1; }
  ( cd "$ROOT/source-code" && docker build --platform linux/amd64 -t timesheet-app:2.5.0-amd64 . )
  docker save timesheet-app:2.5.0-amd64 | gzip > "$STAGE/timesheet-app/timesheet-app-amd64.tar.gz"
  echo "  built: $(du -h "$STAGE/timesheet-app/timesheet-app-amd64.tar.gz" | cut -f1)"
else
  echo "  SKIPPED. Re-run with --build-image, or build it yourself:"
  echo "    cd source-code && docker build --platform linux/amd64 -t timesheet-app:2.5.0-amd64 ."
  echo "    docker save timesheet-app:2.5.0-amd64 | gzip > $STAGE/timesheet-app/timesheet-app-amd64.tar.gz"
fi

# The restore bundle restore.sh expects: data/ + overlay/ + gcp/users.caddy.
step "bonus: restore bundle skeleton"
BUNDLE="$STAGE/restore-bundle"
rm -rf "$BUNDLE"; mkdir -p "$BUNDLE/data" "$BUNDLE/gcp"
cp "$ROOT/reference-data/roster.csv" "$ROOT/reference-data/designations.csv" "$BUNDLE/data/"
cp -R "$ROOT/deployment/overlay" "$BUNDLE/overlay"
cp "$ROOT/deployment/users.caddy.example" "$BUNDLE/gcp/users.caddy.example"
echo "  staged at $BUNDLE"
echo "  Create gcp/users.caddy from the example (one 'name hash' per line), then:"
echo "    tar -czf restore.tgz -C $BUNDLE ."

cat <<EOT

$(printf '\033[1;32m')READY$(printf '\033[0m')  Deploy with:

  cd "$STAGE/gcp"
  PROJ=your-project-id BILLING=XXXXXX-XXXXXX-XXXXXX \\
  TEAM_PASS='...' CLIENT_PASS='...' ./deploy_gcp.sh

  # then, mandatory -- deploy alone leaves the containers unable to start:
  ./restore.sh /path/to/restore.tgz

  # then verify (32 checks):
  cd "$ROOT/source-code" && ./.venv/bin/python tools/e2e_prod_test.py --url https://<site>

See 04-DEPLOY-TO-CLOUD.md for what each step does and why restore.sh is required.
EOT
