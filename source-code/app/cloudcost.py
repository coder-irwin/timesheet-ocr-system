"""Hidden cost page: what this project costs on Google Cloud, this month and last.

Two sources, clearly labelled:
  exact     -- Google's own billing export into BigQuery (dataset `billing` in the
               production project). This is the invoice, to the paisa: list price,
               discounts, credits and tax, per SKU, per day. It lags real time by
               a few hours, which is normal for Google.
  estimate  -- until the export has data: list prices for the resources we know
               we run (VM, disk, static IP, snapshots), multiplied by hours since
               each was created. Marked ESTIMATE in the UI; never shown as exact.

The page is served at /cost (no link anywhere in the UI); it sits behind the same
login gate as the rest. Everything is read-only.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import time
from typing import Any

PROJECT = os.getenv("TS_GCP_PROJECT", "timesheet-ocr-prod")
DATASET = os.getenv("TS_BILLING_DATASET", "billing")
CACHE_S = 600
_cache: dict[str, Any] = {"t": 0, "data": None}

# asia-south1 list prices, INR, 2026-09 (used only for the ESTIMATE path)
LIST_INR = {
    "e2-standard-4 (4 vCPU, 16 GB)": 0.1928 * 83.5,     # USD/h -> INR/h
    "pd-balanced 100 GB": 0.10 * 100 * 83.5 / 730,      # USD/GB-month -> INR/h
    "static external IP": 0.005 * 83.5,
    "snapshot storage (~30 GB)": 0.026 * 30 * 83.5 / 730,
}


def _bq(sql: str) -> list[dict] | None:
    """Run a BigQuery query via the bq CLI if it exists; None on any failure."""
    try:
        out = subprocess.run(
            ["bq", "--project_id", PROJECT, "query", "--use_legacy_sql=false",
             "--format=json", "--quiet", sql],
            capture_output=True, text=True, timeout=60)
        if out.returncode != 0:
            return None
        return json.loads(out.stdout or "[]")
    except Exception:                                          # noqa: BLE001
        return None


def _export_table() -> str | None:
    rows = _bq(f"SELECT table_name FROM `{PROJECT}.{DATASET}.INFORMATION_SCHEMA.TABLES` "
               f"WHERE table_name LIKE 'gcp_billing_export_v1_%' LIMIT 1")
    return rows[0]["table_name"] if rows else None


def exact() -> dict | None:
    t = _export_table()
    if not t:
        return None
    tbl = f"`{PROJECT}.{DATASET}.{t}`"
    base = (f"FROM {tbl} WHERE project.id = '{PROJECT}'")
    month = _bq(f"""
      SELECT FORMAT_DATE('%Y-%m', DATE(usage_start_time, 'Asia/Kolkata')) AS month,
             ROUND(SUM(cost), 2) AS cost,
             ROUND(SUM(IFNULL((SELECT SUM(c.amount) FROM UNNEST(credits) c), 0)), 2) AS credits,
             ROUND(SUM(cost) + SUM(IFNULL((SELECT SUM(c.amount) FROM UNNEST(credits) c), 0)), 2) AS net,
             ANY_VALUE(currency) AS currency
      {base} GROUP BY month ORDER BY month DESC LIMIT 3""") or []
    by_sku = _bq(f"""
      SELECT service.description AS service, sku.description AS sku,
             ROUND(SUM(cost) + SUM(IFNULL((SELECT SUM(c.amount) FROM UNNEST(credits) c), 0)), 2) AS net
      {base} AND DATE(usage_start_time, 'Asia/Kolkata') >= DATE_TRUNC(CURRENT_DATE('Asia/Kolkata'), MONTH)
      GROUP BY service, sku HAVING net <> 0 ORDER BY net DESC LIMIT 25""") or []
    daily = _bq(f"""
      SELECT DATE(usage_start_time, 'Asia/Kolkata') AS day,
             ROUND(SUM(cost) + SUM(IFNULL((SELECT SUM(c.amount) FROM UNNEST(credits) c), 0)), 2) AS net
      {base} AND DATE(usage_start_time, 'Asia/Kolkata') >= DATE_SUB(CURRENT_DATE('Asia/Kolkata'), INTERVAL 31 DAY)
      GROUP BY day ORDER BY day""") or []
    latest = _bq(f"SELECT MAX(export_time) AS t {base}") or [{}]
    return {"source": "exact", "table": t, "months": month, "by_sku": by_sku, "daily": daily,
            "export_as_of": latest[0].get("t")}


def estimate() -> dict:
    """List-price estimate from resource creation times. Never presented as exact."""
    try:
        vm = subprocess.run(["gcloud", "compute", "instances", "describe", "timesheet-prod",
                             "--zone=asia-south1-a", f"--project={PROJECT}",
                             "--format=value(creationTimestamp,status)"],
                            capture_output=True, text=True, timeout=30).stdout.strip().split("\t")
        created = dt.datetime.fromisoformat(vm[0].replace("Z", "+00:00")) if vm and vm[0] else None
        status = vm[1] if len(vm) > 1 else "?"
    except Exception:                                          # noqa: BLE001
        created, status = None, "?"
    if created is None:
        # No cloud identity here (inside the container): do not guess a
        # month's worth of hours. Report zero and let the collector fill it.
        return {"source": "estimate", "vm_status": "unknown (no cloud access from here)", "vm_created": None,
                "hours_running": 0.0, "lines": [], "inr_this_month_so_far": 0.0,
                "inr_full_month_at_list": round(sum(v * 730 for v in LIST_INR.values()), 0),
                "note": "Figures appear once the host-side collector has run (every 10 minutes)."}
    now = dt.datetime.now(dt.timezone.utc)
    hours = max(0.0, (now - created).total_seconds() / 3600) if created else 0.0
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    hours_month = max(0.0, (now - max(created or month_start, month_start)).total_seconds() / 3600)
    lines = []
    for name, inr_h in LIST_INR.items():
        run_h = hours_month if (status == "RUNNING" or "IP" in name or "GB" in name) else 0.0
        lines.append({"item": name, "inr_per_hour": round(inr_h, 2), "hours_this_month": round(run_h, 1),
                      "inr_this_month": round(inr_h * run_h, 2)})
    total = round(sum(l["inr_this_month"] for l in lines), 2)
    full_month = round(sum(v * 730 for v in LIST_INR.values()), 0)
    return {"source": "estimate", "vm_status": status, "vm_created": created.isoformat() if created else None,
            "hours_running": round(hours, 1), "lines": lines, "inr_this_month_so_far": total,
            "inr_full_month_at_list": full_month,
            "note": "List prices, before Google's sustained-use discount (up to 30% on the VM) and any credits. "
                    "Switch on the billing export to replace this with exact figures."}


def snapshot() -> dict:
    if time.time() - _cache["t"] < CACHE_S and _cache["data"]:
        return _cache["data"]
    # In production the container has no cloud credentials: a host-side
    # collector (gcp/cost_collector.sh, cron every 10 min) writes the same
    # structure to <data>/cloud_cost.json using the VM's own identity.
    from . import config
    f = config.DATA_DIR / "cloud_cost.json"
    if f.exists() and time.time() - f.stat().st_mtime < 3 * 3600:
        try:
            data = json.loads(f.read_text())
            data["via"] = "collector"
            _cache.update(t=time.time(), data=data)
            return data
        except Exception:                                      # noqa: BLE001
            pass
    ex = exact()
    data = {"project": PROJECT, "generated": dt.datetime.now().isoformat(timespec="seconds"),
            "exact": ex, "estimate": estimate(),
            "export_setup": None if ex else {
                "why": "Google only lets the billing export be switched on in the console, not by API.",
                "steps": ["Console → Billing → 'New Billing Account' → Billing export → BigQuery export",
                          "Standard usage cost: Edit settings → project 'timesheet-ocr-prod', dataset 'billing' → Save",
                          "Within a few hours this page switches from ESTIMATE to EXACT on its own."]}}
    _cache.update(t=time.time(), data=data)
    return data
