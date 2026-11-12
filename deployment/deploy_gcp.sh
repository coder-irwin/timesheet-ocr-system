#!/usr/bin/env bash
# One-shot production deploy of the Timesheet app to a new GCP VM.
# Run from the ocr_production folder:   ./gcp/deploy_gcp.sh
# Idempotent: re-running skips what already exists.
set -euo pipefail
PROJ="${PROJ:-timesheet-ocr-prod}"
BILLING="${BILLING:?set BILLING=XXXXXX-XXXXXX-XXXXXX (your Cloud Billing account id; find it with: gcloud billing accounts list)}"
ZONE="${ZONE:-asia-south1-a}"; REGION="asia-south1"
VM="${VM:-timesheet-prod}"; MACHINE="${MACHINE:-e2-standard-4}"; DISK_GB="${DISK_GB:-100}"
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)/timesheet-app"
TEAM_PASS="${TEAM_PASS:?set TEAM_PASS=... (login for your team)}"
CLIENT_PASS="${CLIENT_PASS:?set CLIENT_PASS=... (login for the client)}"

step(){ printf '\n\033[1;34m== %s\033[0m\n' "$*"; }

step "1/8 project + billing + APIs"
gcloud projects describe "$PROJ" >/dev/null 2>&1 || gcloud projects create "$PROJ" --name="Timesheet OCR Production"
# Only link if not already linked. Re-linking an already-billed project fails with
# FAILED_PRECONDITION "Cloud billing quota exceeded" (the account has a cap on link
# operations), which aborted a redeploy on 10 Nov 2026 even though billing was fine.
if ! gcloud billing projects describe "$PROJ" --format='value(billingEnabled)' 2>/dev/null | grep -qi true; then
  gcloud billing projects link "$PROJ" --billing-account="$BILLING" >/dev/null
else
  echo "  billing already enabled on $PROJ — skipping link"
fi
gcloud config set project "$PROJ" >/dev/null
gcloud services enable compute.googleapis.com >/dev/null

step "2/8 static IP"
gcloud compute addresses describe "$VM-ip" --region="$REGION" >/dev/null 2>&1 || gcloud compute addresses create "$VM-ip" --region="$REGION"
IP=$(gcloud compute addresses describe "$VM-ip" --region="$REGION" --format='value(address)')
SITE="${SITE:-$IP.nip.io}"; echo "  site: https://$SITE"

step "3/8 firewall: only 80/443 from the internet, SSH via IAP"
gcloud compute firewall-rules describe allow-web >/dev/null 2>&1 || gcloud compute firewall-rules create allow-web --allow=tcp:80,tcp:443 --target-tags=timesheet --quiet
gcloud compute firewall-rules describe allow-iap-ssh >/dev/null 2>&1 || gcloud compute firewall-rules create allow-iap-ssh --allow=tcp:22 --source-ranges=35.235.240.0/20 --target-tags=timesheet --quiet

step "4/8 VM ($MACHINE, ${DISK_GB} GB, $ZONE)"
gcloud compute instances describe "$VM" --zone="$ZONE" >/dev/null 2>&1 || gcloud compute instances create "$VM" \
  --zone="$ZONE" --machine-type="$MACHINE" --image-family=ubuntu-2404-lts-amd64 --image-project=ubuntu-os-cloud \
  --boot-disk-size="${DISK_GB}GB" --boot-disk-type=pd-balanced --address="$VM-ip" --tags=timesheet \
  --metadata=startup-script='#!/bin/bash
    if ! command -v docker >/dev/null; then curl -fsSL https://get.docker.com | sh; fi
    if ! command -v ollama >/dev/null; then
      curl -fsSL https://ollama.com/install.sh | sh
      mkdir -p /etc/systemd/system/ollama.service.d
      printf "[Service]\nEnvironment=OLLAMA_HOST=0.0.0.0:11434\nEnvironment=OLLAMA_KEEP_ALIVE=2h\nEnvironment=OLLAMA_NUM_PARALLEL=2\n" > /etc/systemd/system/ollama.service.d/override.conf
      systemctl daemon-reload; systemctl restart ollama
    fi
    # Wait for the Ollama API to actually answer before pulling. A bare
    # "sleep 5" lost this race on 10 Nov 2026: the pull failed with the
    # service not yet listening, nothing checked the exit status, and
    # /var/tmp/provisioned was touched anyway -- so the VM came up looking
    # healthy with NO header model, which silently costs name accuracy.
    for i in $(seq 1 90); do curl -sf http://127.0.0.1:11434/api/tags >/dev/null 2>&1 && break; sleep 2; done
    for i in 1 2 3; do
      ollama list 2>/dev/null | grep -q qwen3-vl && break
      ollama pull qwen3-vl:4b && break
      sleep 15
    done
    # Only claim provisioned if the model is genuinely present. The deploy
    # script polls this flag, so a missing model now blocks the deploy
    # loudly instead of shipping a half-working VM.
    if ollama list 2>/dev/null | grep -q qwen3-vl; then touch /var/tmp/provisioned; fi'
echo "  waiting for the VM to boot, install Docker + Ollama and pull the 3 GB header model (~5 min)..."
for i in $(seq 1 40); do gcloud compute ssh "$VM" --zone="$ZONE" --tunnel-through-iap --command='test -f /var/tmp/provisioned && docker --version && ollama list | grep -q qwen3-vl' 2>/dev/null && break; sleep 20; done

step "5/8 daily snapshot schedule (7 kept)"
gcloud compute resource-policies describe daily-snap --region="$REGION" >/dev/null 2>&1 || gcloud compute resource-policies create snapshot-schedule daily-snap --region="$REGION" --max-retention-days=7 --on-source-disk-delete=keep-auto-snapshots --daily-schedule --start-time=20:00
gcloud compute disks add-resource-policies "$VM" --zone="$ZONE" --resource-policies=daily-snap 2>/dev/null || true

step "6/8 upload the app (amd64 image + config, ~330 MB)"
gcloud compute ssh "$VM" --zone="$ZONE" --tunnel-through-iap --command='mkdir -p ~/timesheet-app/gcp ~/timesheet-app/data'
gcloud compute scp --zone="$ZONE" --tunnel-through-iap --recurse \
  "$APP_DIR/timesheet-app-amd64.tar.gz" "$APP_DIR/docker-compose.yml" "$APP_DIR/config.env" "$APP_DIR/install.sh" \
  "$APP_DIR/START-HERE.md" "$APP_DIR/TROUBLESHOOTING.md" "$APP_DIR/data" "$VM":~/timesheet-app/   # data/ = roster + designation vocabulary only
gcloud compute scp --zone="$ZONE" --tunnel-through-iap "$APP_DIR/../gcp/Caddyfile" "$APP_DIR/../gcp/docker-compose.prod.yml" "$VM":~/timesheet-app/gcp/

step "7/8 install image, hash passwords, start app + Caddy"
gcloud compute ssh "$VM" --zone="$ZONE" --tunnel-through-iap --command="
  cd ~/timesheet-app && sudo docker load -i timesheet-app-amd64.tar.gz | tail -1 &&
  sudo docker tag timesheet-app:2.0.0-amd64 timesheet-app:2.0.0 2>/dev/null || sudo docker tag \$(sudo docker images --format '{{.Repository}}:{{.Tag}}' | grep timesheet-app | head -1) timesheet-app:2.0.0 &&
  TEAM_HASH=\$(sudo docker run --rm caddy:2 caddy hash-password --plaintext '$TEAM_PASS') &&
  CLIENT_HASH=\$(sudo docker run --rm caddy:2 caddy hash-password --plaintext '$CLIENT_PASS') &&
  printf 'SITE=$SITE\nTEAM_HASH=%s\nCLIENT_HASH=%s\n' \"\$TEAM_HASH\" \"\$CLIENT_HASH\" > .env &&
  sudo docker compose -f docker-compose.yml -f gcp/docker-compose.prod.yml --env-file config.env --env-file .env up -d &&
  sleep 20 && sudo docker compose ps"

step "7b budget alert (80% and 100% of the monthly cap)"
CUR=$(gcloud billing accounts describe "$BILLING" --format='value(currencyCode)' 2>/dev/null || echo INR)
if [ "$CUR" = "INR" ]; then AMT=10000; else AMT=115; fi
gcloud services enable billingbudgets.googleapis.com >/dev/null 2>&1 || true
gcloud billing budgets list --billing-account="$BILLING" --format='value(displayName)' 2>/dev/null | grep -q '^timesheet-prod-cap$' || \
  gcloud billing budgets create --billing-account="$BILLING" --display-name=timesheet-prod-cap --budget-amount="${AMT}${CUR}" \
    --filter-projects="projects/$PROJ" --threshold-rule=percent=0.8 --threshold-rule=percent=1.0 2>/dev/null || echo "  (budget alert not created -- create it in the console: Billing > Budgets, ${AMT} ${CUR})"

step "8/8 verify"
for i in $(seq 1 12); do curl -fsS -u "team:$TEAM_PASS" "https://$SITE/api/health" && break; sleep 10; done
echo; echo "DONE  ->  https://$SITE   (users: team / client)"
