#!/usr/bin/env bash
# Owner runs this once. Gives the production VM permission to read this project's billing data (about 1 min downtime).
set -e
Z="${ZONE:-asia-south1-a}"; P="${PROJ:-timesheet-ocr-prod}"; VM="${VM:-timesheet-prod}"; SA=YOUR-PROJECT-NUMBER-compute@developer.gserviceaccount.com
gcloud compute instances stop $VM --zone=$Z --project=$P --quiet
gcloud compute instances set-service-account $VM --zone=$Z --project=$P --service-account=$SA --scopes=https://www.googleapis.com/auth/cloud-platform
gcloud compute instances start $VM --zone=$Z --project=$P --quiet
echo "done; the app comes back on its own (restart: unless-stopped). The cost collector runs within 10 minutes."
