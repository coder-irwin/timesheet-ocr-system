"""Central configuration. Everything is env-overridable so the same build runs
on the 16GB CPU-only demo laptop and on a bigger box later without code changes.
"""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("TS_DATA_DIR", BASE_DIR / "data"))
UPLOAD_DIR = DATA_DIR / "uploads"      # original files exactly as received
PAGE_DIR = DATA_DIR / "pages"          # one normalised PNG per page
CACHE_DIR = DATA_DIR / "cache"         # extraction results keyed by content hash
EXPORT_DIR = DATA_DIR / "exports"
DB_PATH = Path(os.getenv("TS_DB_PATH", DATA_DIR / "timesheets.db"))

for _d in (UPLOAD_DIR, PAGE_DIR, CACHE_DIR, EXPORT_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# --- Model / extraction -------------------------------------------------
# qwen3-vl:4b is the default deliberately: :8b at Q4_K_M wants ~12GB and will
# swap on a 16GB Windows laptop once the OS takes its 3-4GB. Swap via env only
# when the machine has headroom or a GPU.
OLLAMA_URL = os.getenv("TS_OLLAMA_URL", "http://127.0.0.1:11434")
VLM_MODEL = os.getenv("TS_VLM_MODEL", "qwen3-vl:4b")
VLM_TIMEOUT_S = float(os.getenv("TS_VLM_TIMEOUT_S", "600"))

# Dual-pass consensus. Self-reported per-field confidence from a VLM is a
# generated token, not a calibrated probability -- it reads high on confidently
# wrong values. We instead run the extraction twice and treat *disagreement*
# between passes as the uncertainty signal. That is a measured signal.
DUAL_PASS = os.getenv("TS_DUAL_PASS", "1") not in ("0", "false", "False")

# The summary block is read in its own call that never sees the day grid, so the
# model cannot "helpfully" derive the total from the rows it just produced. If
# it could, the row-sum checksum would validate against itself and catch nothing.
INDEPENDENT_SUMMARY_PASS = os.getenv("TS_INDEPENDENT_SUMMARY", "1") not in ("0", "false", "False")

# --- Preprocessing ------------------------------------------------------
# Long-edge target for the normalised page. Bigger reads handwriting better but
# costs prefill time quadratically-ish on CPU; 1600 is the tested compromise.
PAGE_LONG_EDGE = int(os.getenv("TS_PAGE_LONG_EDGE", "1600"))
# Landscape sheets pack 30 day-columns across the page instead of down it, so
# a cell is a few pixels wide at 1600 and OCR destroys it. Measured on a SHELL
# sheet: the day-number header read 4 of 30 correctly at 1600 and 30 of 30 at
# 2400. Applied only when the page is meaningfully wider than tall, so the
# portrait AARVI pages keep exactly the resolution they were tuned at.
LANDSCAPE_LONG_EDGE = int(os.getenv("TS_LANDSCAPE_LONG_EDGE", "2600"))
LANDSCAPE_ASPECT_MIN = float(os.getenv("TS_LANDSCAPE_ASPECT_MIN", "1.25"))
# Resolution of the high-detail twin kept for the extraction rescue path. Used
# only when a page yields nothing at the normal size -- some clients put a
# 30-column table on a portrait page, where the aspect rule cannot help.
HIRES_LONG_EDGE = int(os.getenv("TS_HIRES_LONG_EDGE", "2600"))
# Hard ceiling on the per-page RESCUE work (extra orientations, a high-detail
# re-read). Rescues only run on pages that already produced nothing, but a
# 500-document batch cannot afford an unbounded ladder on each of them: five
# OCR passes on a failing page turns a 15-minute batch into hours. When the
# budget is spent the page is returned as-is and flagged for review, which is
# the correct outcome anyway -- a reviewer looks at it either way.
RESCUE_BUDGET_S = float(os.getenv("TS_RESCUE_BUDGET_S", "45"))
MAX_DESKEW_DEG = float(os.getenv("TS_MAX_DESKEW_DEG", "15"))

# --- Validation ---------------------------------------------------------
OT_HOURS_MAX_PER_DAY = float(os.getenv("TS_OT_MAX_DAY", "12"))
NORMAL_HOURS_MAX_PER_DAY = float(os.getenv("TS_NORMAL_MAX_DAY", "12"))
HOURS_TOLERANCE = float(os.getenv("TS_HOURS_TOLERANCE", "0.01"))
# Tolerance for MONTHLY hour sums, as a fraction of the stated total.
# Reading noise accumulates across ~30 handwritten cells; see validate._close_sum.
SUM_TOLERANCE_FRACTION = float(os.getenv("TS_SUM_TOLERANCE_PCT", "0.02"))
# Roster match: reject when the top two candidates score too close together.
# A confident match to the *wrong* employee is the invoice-freezing error, so
# ambiguity must flag rather than silently pick the nearest name.
ROSTER_MIN_SCORE = float(os.getenv("TS_ROSTER_MIN_SCORE", "82"))
ROSTER_MIN_MARGIN = float(os.getenv("TS_ROSTER_MIN_MARGIN", "6"))

APP_TITLE = "Timesheet Extraction & Validation"

# --- optional VLM fallback ------------------------------------------------
# Uses a local Ollama + qwen3-vl:4b to re-read the header block when the
# rule-based extractor fails on it. Costs ~24 s on the pages that need it, so
# it is opt-out via env for throughput-critical runs. Fully local; if Ollama is
# not running the pipeline simply skips it.
VLM_HEADER_FALLBACK = os.getenv("TS_VLM_HEADER", "1") not in ("0", "false", "False")
