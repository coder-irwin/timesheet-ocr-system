# Production on GCP — runbook

## Deploy (first time, ~15 min)
    cd ~/ocr_production
    TEAM_PASS='choose-a-strong-one' CLIENT_PASS='another-strong-one' ./gcp/deploy_gcp.sh
Creates project `timesheet-ocr-prod` on "New Billing Account", a static IP, firewall (443/80 public, SSH only
through Google IAP), an e2-standard-4 VM in Mumbai with 100 GB, daily snapshots (7 kept), uploads the amd64
image, and starts the app behind Caddy with HTTPS (Let's Encrypt on <ip>.nip.io) and two logins: `team`, `client`.
Override anything with env vars: PROJ, ZONE, MACHINE, DISK_GB, SITE (your own domain, pointed at the IP first).

## Daily
    gcloud compute ssh timesheet-prod --zone=asia-south1-a --tunnel-through-iap
    cd ~/timesheet-app && sudo docker compose ps          # health
    sudo docker compose logs -f timesheet                  # app log
Exports and the database live in ~/timesheet-app/data on the VM (snapshotted nightly).

## Upgrade to a new build
    gcloud compute scp --zone=asia-south1-a --tunnel-through-iap timesheet-app/timesheet-app-amd64.tar.gz timesheet-prod:~/timesheet-app/
    ssh in, then: sudo docker load -i timesheet-app-amd64.tar.gz && sudo docker compose -f docker-compose.yml -f gcp/docker-compose.prod.yml --env-file config.env --env-file .env up -d

## Change a password
    ssh in, then: sudo docker run --rm caddy:2 caddy hash-password --plaintext 'new' -> paste into .env -> sudo docker compose restart caddy

## Decisions (quality first, cap Rs 10,000/month)
- Header VLM ON (qwen3-vl:4b via Ollama on the VM's CPU): names on hard handwritten headers keep the measured 98%; a hard page takes 1-2 min, a 150-page batch ~1 h. A GPU (+$250/mo) would break the cap.
- e2-standard-4 (16 GB) so the 4.6 GB model and 2 OCR workers fit. TS_WORKERS=2, TS_OCR_THREADS=2.
- Data uploaded: roster.csv + designations.csv only (what the app needs). Client timesheets arrive through the UI.
- Billing budget alert at 80% and 100% of the cap on the billing account.

## Cost (asia-south1, list): e2-standard-4 ~$98 (~$70 with sustained-use discount) + 100 GB disk $10 + static IP $3 + snapshots ~$4 + egress ~$2 = ~$115/month.
## Turn it off when idle:  gcloud compute instances stop timesheet-prod --zone=asia-south1-a   (disk + IP keep costing ~$13/month)

## LIVE (deployed 21 Sep 2026, 00:20 IST)
- URL: https://<your-static-ip>.nip.io   (project timesheet-ocr-prod, VM timesheet-prod, asia-south1-a) — running 2.5.0 / pipeline v38-no-cls-drift-window since 6 Oct 2026 17:45 IST
- Logins: `team` and `client` — passwords in gcp/.logins.txt (never commit; chmod 600)
- Smoke test: a 79-page GSPL PDF uploaded twice; 158 pages processed, 0 errors, ~8 pages/min with the VLM on;
  the duplicate batch resolved from cache instantly; page 63 matched the hand-graded local result exactly.
- Known behaviour: in the first 2–3 minutes of a large upload (model loading + OCR on 4 vCPU) the UI can be slow to
  answer; it recovers on its own. Docker may mark the app "unhealthy" during that window; it is not down.
- Two fixes made during deploy and folded into deploy_gcp.sh: bcrypt hashes need `$` doubled in .env; compose must be
  given BOTH env files (--env-file config.env --env-file .env).


## Hidden cost page — /cost (no link in the UI; same login)
Shows this project's Google Cloud cost ONLY (every query filters project.id = timesheet-ocr-prod).
Two sources, labelled on the page: EXACT (Google's billing export -> BigQuery dataset `billing`, to the paisa,
incl. discounts/credits/tax, lags a few hours) or ESTIMATE (list prices x hours, before the ~30% sustained-use
discount). A host cron (gcp/cost_collector.py, every 10 min) writes data/cloud_cost.json; the app only reads it.

TWO ONE-TIME STEPS to make it exact (account owner only):
 1. Give the VM permission to read billing data (about 1 minute of downtime). Run the three gcloud commands in
    gcp/enable_cost_scope.sh (stop the VM, set its service-account scope to cloud-platform, start it).
    BigQuery read roles are already granted to the VM's service account.
 2. Switch on the export in the Google console (there is no API for this):
    Billing -> "New Billing Account" -> Billing export -> BigQuery export -> Standard usage cost -> Edit settings
    -> project timesheet-ocr-prod, dataset billing -> Save. The dataset already exists.
Within a few hours the page flips from ESTIMATE to EXACT by itself. Budget alert (Rs 10,000, 80%/100%) is already set.

## Overlay files mounted into the image (keep docker-compose.prod.yml in step)
validate, rowconf, main, db, cloudcost, export_designs, pipeline, generic_grid, ocr_engine, clocks + index.html, cost.html.
ALWAYS scp a new overlay file to the VM BEFORE adding its mount: Docker turns a bind-mount of a missing host
path into an empty DIRECTORY, which is how the app went down for 4 minutes on 21 Sep. After `up -d`, check:
    sudo docker exec timesheet-app sh -c 'for f in pipeline rowconf generic_grid ocr_engine clocks; do wc -c < /app/app/$f.py; done'
and confirm /api/health reports the PIPELINE_VERSION you just shipped.

## Per-person logins (added 21 Sep)
Each person gets their own login; every edit, upload, re-read and download is stamped with their name in the
change history and the Audit sheet. Manage from the ocr_production folder (needs gcloud access):
    ./gcp/user.sh add  <name>            # generates a password, prints it once, records it in gcp/.logins.txt
    ./gcp/user.sh add  <name> <password> # choose the password yourself
    ./gcp/user.sh remove <name>
    ./gcp/user.sh list
Names: letters, digits, dot, dash, underscore. Passwords are stored only as bcrypt hashes in gcp/users.caddy on the
server. Adding or removing restarts the login gate (2 seconds); the app itself is untouched.
The two original logins `team` and `client` still work; remove `client` once the client's people have their own.

## Page lock (added 21 Sep)
Only one person can edit a page at a time. Others see "👤 name is checking this page" and a read-only view; their
save is refused with a clear message. A lock lets go when the person saves, opens another page, or closes the tab,
and expires by itself after 5 minutes of inactivity. Nothing to manage.
Deploy note: when copying overlay files, confirm each upload succeeded BEFORE recreating containers; a missing file
becomes an empty directory mount and the app will not start (fix: sudo rm -rf the path, re-upload, up -d again).
