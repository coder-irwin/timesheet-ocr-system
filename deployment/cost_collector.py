#!/usr/bin/env python3
"""Runs ON THE VM (cron, every 10 min). Uses the VM's identity + the bq/gcloud
CLIs to compute this project's exact cost from Google's billing export and
writes ~/timesheet-app/data/cloud_cost.json for the app's hidden /cost page.
Falls back to a list-price estimate until the export has data."""
import sys, os, json, datetime as dt, importlib.util
HOME = os.path.expanduser("~/timesheet-app")
os.environ.setdefault("TS_DATA_DIR", os.path.join(HOME, "data"))
spec = importlib.util.spec_from_file_location("cloudcost", os.path.join(HOME, "overlay", "app", "cloudcost.py"))
cloudcost = importlib.util.module_from_spec(spec)
# the module imports `from . import config` lazily inside snapshot(); we only call exact()/estimate()
spec.loader.exec_module(cloudcost)
ex = cloudcost.exact()
data = {"project": cloudcost.PROJECT, "generated": dt.datetime.now().isoformat(timespec="seconds"),
        "exact": ex, "estimate": cloudcost.estimate(),
        "export_setup": None if ex else {
            "why": "Google only lets the billing export be switched on in the console, not by API.",
            "steps": ["Console → Billing → 'New Billing Account' → Billing export → BigQuery export",
                      "Standard usage cost: Edit settings → project 'timesheet-ocr-prod', dataset 'billing' → Save",
                      "Within a few hours this page switches from ESTIMATE to EXACT on its own."]}}
out = os.path.join(os.environ["TS_DATA_DIR"], "cloud_cost.json")
tmp = out + ".tmp"; open(tmp, "w").write(json.dumps(data, default=str)); os.replace(tmp, out)
print(dt.datetime.now().isoformat(timespec="seconds"), "wrote", out, "source", "exact" if ex else "estimate")
