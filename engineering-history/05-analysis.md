# Consolidated Analysis

> Everything measured so far, what it means, and what is still unknown.
> Written 2026-08-12. Read this first.

---

## 1. Status: what is and is not done

### Working and verified end-to-end

| Component | Evidence |
|---|---|
| Upload → preprocess → OCR → extract → validate → review → Excel | 12 real client pages processed through the running server |
| Excel export | 3 sheets (Timesheets / Daily / Exceptions), 30 daily rows, 6 exceptions, correct employee data |
| Content-addressed cache | 9 of 12 pages served in **1 ms** vs 20–40 s fresh |
| Validation engine | Found **genuine defects** in the client's own paperwork (§4) |
| Audit log | Every field correction recorded with actor + timestamp |
| Windows launcher | `run.bat`, no admin rights, no GPU, no DB server |

### Not done

| Gap | Why it matters |
|---|---|
| **Accuracy vs the 63 ground-truth pairs never measured** | The single biggest missing number. We have 63 folders containing both the scanned PDF *and* the human-typed Excel. That is a free, real accuracy benchmark and it has not been run. |
| **Employee roster not built** | The biggest available accuracy lever. OCR fails on handwritten names; a 3,000-person closed list would resolve them. |
| Handwritten day-grid extraction is weak | Headers/summaries extract well; hand-filled grids need review |
| Excel export is a sensible default, not the client's exact format | Their real template is in the corpus, unmapped |
| Multi-employee sheet layouts unhandled | IOCL/Avaada Excel files are one row per employee × days as columns |
| Thresholds rest on 5 hand-labelled pages | Enough to decide on, not enough to publish |
| No dewarping | Measured as low-priority (§3.3), but not zero |
| No automated tests | |

**Bottom line: the system works and is demonstrable. It is not production-validated.**

---

## 2. The data (measured, not estimated)

`tools/survey.py` + `tools/classify_corpus.py` over `Timesheet - Delhi 2026-2027`:

| | |
|---|---|
| PDFs | 708 (≈2,527 pages, avg 3.2/PDF) |
| Excel files | 289 |
| Client folders | 34 |
| Folders with **both** PDF and Excel | **63** |

### Three planning assumptions the data disproved

1. **Not 12–15 templates — 34 clients.** But most share one base *AARVI ENCON*
   form, so the real variation is fill-style and period, not 34 layouts. Less
   work than feared, but the plan's number was wrong in both directions.
2. **Handwriting is the minority case, not the primary one.** ~75% of pages are
   typed/printed. The plan was built around the hardest 16%.
3. **The output format was never unknown.** The client's own typed Excel files
   sit beside the scanned PDFs. The plan listed this as an open question and as
   a "silent scope bomb"; it was already answered in the data.

### Page routing split

| Route | Pages | Share | Cost/page | Accuracy |
|---|---:|---:|---|---|
| Born-digital PDF | 206 | 8% | ~0 ms | 100% by construction |
| Printed scan | 1,907 | 75% | ~6 s | high |
| Handwritten scan | 414 | 16% | slow | the hard case |

**Consequence:** ~**8–23 machine-hours/month** instead of 100–250. This is what
makes a 16 GB CPU-only laptop a viable production machine.

---

## 3. Engine benchmark — the decisive measurements

Five engines, same 5 hand-labelled pages, same metric (share of
invoice-critical values correctly read, with positional proximity required).
Hardware: **Apple M4 / 24 GB** — the target Windows laptop is 1.5–3× slower.

| Engine | Printed | **Handwritten** | s/page |
|---|---:|---:|---:|
| **RapidOCR (PP-OCRv6 / ONNX)** | 79% | **50%** | **5.7** |
| Qwen3-VL 4B (VLM) | 79% | 30% | **563** |
| glm-ocr 1.1B (VLM) | 74% | **0%** | 66 |
| Tesseract 5 | 70% | **0%** | **1.6** |
| EasyOCR | 63% | **0%** | 11.0 |

### 3.1 The headline: a vision model is NOT the answer here

This is the most commercially important finding in the project, and it is the
opposite of the industry default.

- **Qwen3-VL is worse than plain OCR at handwriting** — 30% vs 50% — while
  being **~100× slower** (563 s vs 5.7 s per page).
- **glm-ocr, a model built specifically for OCR, returned nothing at all** on
  the handwritten page.
- Only **RapidOCR reads any handwriting**. Every other engine scored a flat 0%.

The original architecture proposed "VLM with per-template JSON schema" as the
extractor, with a fallback. **The measurement does not support that.** A VLM-first
design would be roughly two orders of magnitude more expensive and *less*
accurate on exactly the pages it was supposed to rescue.

At 2,527 pages/month, Qwen3-VL alone would need **>200 machine-hours** just for
the OCR pass — before the target laptop's slowdown factor.

### 3.2 The false result we nearly published

Qwen3-VL initially scored **0% on every page**, including the one page every
other engine read at 100%. That implausibility triggered an investigation rather
than a write-up.

It was **our harness bug**: Qwen3-VL is a reasoning model, and the raw Ollama
response showed `response: len=0` alongside `thinking: len=5027` containing a
**correct** reading of the page (`EMPLOYEE ID: 20000001`, `SAWRABH RAJ`). It had
exhausted the token budget while thinking. Fixed with `think: False` and a 4×
larger budget; the corrected score is 30%/79%.

> **Transferable lesson:** an implausibly *bad* benchmark number deserves the
> same scrutiny as an implausibly good one. "Qwen3-VL cannot read timesheets"
> would have been flatly untrue.

### 3.3 Secondary findings

- **Tesseract is 3.5× faster than RapidOCR** (1.6 s vs 5.7 s) and only 9 points
  behind on printed pages. For a known-all-printed workload it would be the
  rational choice. It loses here solely on the handwriting column.
- **Page warping costs less than expected.** The curved phone-scanner capture
  (`SAFEARTH01`) still scored 75% on RapidOCR. Geometric distortion is not the
  dominant error source — handwriting is. Dewarping was therefore deprioritised.
- **What OCR fails at on handwriting is *names*, not numbers.** On IOCL30 the
  missed fields were employee name, code, designation and month — four of five
  are free text. The numeric grid read substantially better. This is a
  convenient failure mode: names are recoverable from a closed roster, and
  numbers are protected by arithmetic checksums.

---

## 4. The validation engine works on real defects

The strongest evidence that the "validation, not extraction" thesis is correct.

On `ADANI02 / ADN901 APR 2026` the engine reported, unprompted:

```
BLOCKING
  • Counted 24 present days in the grid but the sheet states 26.
  • Stated total normal hours could not be read, so the row-sum checksum
    cannot be applied to this page.
  • Day 24: normal hours 42.0 is outside 0-12.
```

All three are **genuine defects in the client's own paperwork**:

- The present-day count really is inconsistent — a human had already noticed and
  scrawled `25+3+2 = 30` at the bottom of the page by hand.
- Total Man Hours and Total OT really are blank on the form.
- Day 24 really does read `0.42` where every other row reads `10:00`.

The system found in seconds what a human had struggled with in pen.

### The noise lesson

Before the hour-repair fix, this page produced **40 issues, 20 blocking** —
because OCR drops the thin colon in `10:00`, yielding `1000`, which failed the
0–12 bounds check on *every row*. The one real issue was buried in twenty false
ones.

After the fix: **6 issues, 3 blocking, all genuine.**

> This is the difference between a validation engine and an alarm that gets
> muted. The client's stated complaint — *"reviewing it takes as long as doing
> it"* — is exactly what a noisy validator recreates.

---

## 5. Architectural decisions, with the evidence

| Decision | Evidence |
|---|---|
| **OCR-first, not VLM-first** | VLM is 100× slower and worse at handwriting (§3.1) |
| **RapidOCR as the engine** | Only engine scoring >0% on handwriting (§3) |
| **Anchor-based extraction, not fixed coordinates or grid cells** | Grid detection succeeds on flat scans, **fails on curved pages** (52 rows but 2 columns on SAFEARTH01). Anchors survive warp because a value is always beside its own label. |
| **Route by OCR confidence, not pixel statistics** | Two pixel-based classifiers failed; ink statistics were fooled by an employee photo and signature images, mislabelling 145 typed files as handwritten. Confidence p25 separates cleanly: 0.777 handwritten vs ≥0.993 typed. |
| **Infer date format from column behaviour** | Formats vary (`01.04.2026`, `06/21/2026`, `0\|4\|26`). Assuming one collapsed all 30 SAFEARTH rows onto "day 6". The day component is the one that varies down the column. |
| **SQLite, not PostgreSQL** | A DB server is an install step and a demo failure mode. 3,000 pages/month is far below SQLite's limits. |
| **Vanilla JS, no React** | No npm, no build step, no toolchain to break in a 24-hour window. |
| **Dewarping deprioritised** | Warped page still scored 75% (§3.3). |

---

## 6. Bugs found and fixed (worth knowing about)

| Bug | Symptom | Cause |
|---|---|---|
| OpenCV 5 API change | Every page failed preprocessing | `HoughLinesP` returns `(N,4)` in OpenCV 5 vs `(N,1,4)` in 4.x. Code now handles both — the deployment laptop may install either. |
| Persistence crash | All 12 pages marked `error` **despite successful extraction** | `set_page_result` called `list()` on integers in the new analysis dict. Extraction was fine; only the save failed. |
| Wrong fuzzy scorer | `employee_code` always `None` | `partial_ratio` matched "EMPLOYEE CODE" against "EMPLOYEE NAME" on the shared word. Switched to `token_set_ratio` + a length guard. |
| Date-position assumption | All rows collapsed to one day | See §5. |
| Hour colon loss | 20 false bounds violations per page | `10:00` → `1000`. See §4. |
| Benchmark harness | Qwen3-VL scored a false 0% | See §3.2. |

---

## 7. What to do next, in priority order

1. **Measure accuracy against the 63 ground-truth pairs.** This is the number
   that decides whether the system is deliverable, and the data is already
   sitting on disk. Nothing else should be quoted to the client before it.
2. **Build the employee roster.** Extractable from names already present in the
   289 Excel files. Directly attacks the field class OCR most reliably fails on.
3. **Map the client's real Excel output format** from the corpus.
4. **Improve handwritten day-grid extraction** — currently the weakest link.
5. **Expand the labelled set** from 5 pages to ~50 before publishing any
   benchmark externally.

---

## 8. Honest limitations

- All timings are from an **M4/24 GB**; the target Windows laptop is materially
  slower. Divide throughput by roughly 1.5–3.
- Engine comparison rests on **5 hand-labelled pages**. Sufficient to choose an
  engine (the gaps are large), insufficient to publish.
- `field_recall` is a **generous** metric: it asks whether a value could be read
  at all, ignoring whether the extraction pipeline assigns it to the right
  field. Real end-to-end accuracy will be lower than these numbers.
- One measurement artefact is known and unresolved: `SAMS01`'s four totals were
  missed by *every* engine, which indicts the proximity-label list for that
  layout rather than the engines.
