#!/usr/bin/env bash
# Wake the production VM and wait until the app is actually answering.
#
#   ./gcp/wake.sh
#
# Run this before a demo. Cold start is 2-5 minutes: the VM boots, Docker
# starts, the OCR models load and Ollama loads a 4.6 GB model. The script does
# not return until /api/health answers, so when it prints READY the system
# really is ready -- which is the point of having it rather than clicking
# Start and hoping.
set -uo pipefail
ZONE="${ZONE:-asia-south1-a}"
NAME="${NAME:-timesheet-prod}"

state=$(gcloud compute instances describe "$NAME" --zone "$ZONE" --format='value(status)')
echo "current state: $state"
if [ "$state" != "RUNNING" ]; then
  echo "starting $NAME ..."
  gcloud compute instances start "$NAME" --zone "$ZONE" --quiet
fi

echo "waiting for the application to answer (this takes 2-5 minutes) ..."
for i in $(seq 1 60); do
  if gcloud compute ssh "$NAME" --zone "$ZONE" --tunnel-through-iap --command \
      "sudo docker compose -f ~/timesheet-app/docker-compose.yml -f ~/timesheet-app/gcp/docker-compose.prod.yml --env-file ~/timesheet-app/config.env --env-file ~/timesheet-app/.env up -d >/dev/null 2>&1; sudo docker exec timesheet-app sh -c 'curl -sf --max-time 10 http://127.0.0.1:8077/api/health'" 2>/dev/null | grep -q '"ocr_ready":true'; then
    echo
    echo "READY  https://YOUR-STATIC-IP.nip.io"
    exit 0
  fi
  printf '.'
  sleep 15
done
echo
echo "still not answering after 15 minutes -- check: gcloud compute ssh $NAME --zone $ZONE --tunnel-through-iap"
exit 1
