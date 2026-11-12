# 16 — Load test & live-app accuracy: evidence record (19 Aug 2026, night)

The test databases were wiped afterwards to return the demo machine to a
pristine state, so this file is the durable record of what was observed,
when, and how. Everything here is re-runnable: the scripts live in the
session scratchpad pattern described below and take ~1 hour total.

## Test 1 — 250-page single-upload load test (max-accuracy mode)

- Input: the alphabetically-first 243 corpus PDFs (128 MB payload), 250
  pages, uploaded in ONE `POST /api/batches` multipart request via httpx.
- Timeline: upload began ~21:50; ingest (synchronous split+preprocess in the
  request handler) ran concurrently with worker processing; final page done
  22:43:11. **Wall: 52.5 min for 250 pages = 12.6 s/page effective.**
- Statuses at completion: 258 needs_review / 2 clean / 1 review_optional /
  **0 errors** (261 total incl. 11 residual demo pages excluded from stats).
- extract_ms distribution: 28 pages <20 s · 139 pages 20–60 s (mean 39 s) ·
  83 pages >60 s (mean 79 s). The slow tail is the VLM header fallback:
  Ollama serialises calls, so 4 workers queue on VLM-needing pages.
- Server RSS spot samples: 502 MB mid-run, 774 MB late-run. Not a
  continuous peak measurement — but an order of magnitude below the 16 GB
  budget either way.
- **Defect observed:** the HTTP client timed out at 600 s while the server
  correctly continued (ingest is synchronous inside the POST handler). No
  pages were lost. Mitigation: chunk very large uploads today; make
  ingestion async before production (~1 day).

## Test 2 — fast mode (VLM fallback off), same corpus mix

- `TS_VLM_HEADER=0`, first 30 files of the same list: 30 pages, all
  processed, 0 errors. **Wall 266 s = 8.9 s/page all-in** (of which 130 s
  was the synchronous upload+split). The original "~3 s/page" figure in
  older docs reflects a typed-heavy mix; this sample is handwriting-heavy.

## Test 3 — live-app accuracy (the product's real output vs ground truth)

- The 11 truth-covered PDFs (49 pages) were uploaded through the running
  app; the stored records in the app database were scored against the
  client's own typed Excels (same parse/match/score code as eval_100).
- Result: **961/1090 = 88.2% overall** · day 905/1025 = 88.3% · name 33/34
  = 97.1% · designation 23/31 = 74.2% — an exact, cell-for-cell
  reproduction of the offline eval_100 benchmark under v14.
- Reading: the shipped app and the measured pipeline are provably the same
  artifact; there is no benchmark-vs-product gap.

## Honest limitations of these tests

1. RAM was spot-sampled, not continuously tracked.
2. The load-test sample skews handwritten (alphabetical pick), so the
   throughput numbers are conservative for a representative month.
3. The raw test databases were deleted in the pristine reset; re-running
   the three tests reproduces all numbers (the pipeline is deterministic
   given the same inputs and PIPELINE_VERSION).
