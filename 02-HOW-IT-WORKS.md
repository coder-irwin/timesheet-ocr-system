# 02 — How It Works

The architecture, the processing stages, and the ideas that hold it together.
Read `01-WHAT-THIS-IS.md` first if you have not.

---

## 1. The shape of the thing

```
   Browser  ──upload──>  FastAPI (app/main.py)
                              │
                              │  one job per page, on a worker thread
                              ▼
                      pipeline.process_page()
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
   PRE-OCR               READING               POST-OCR
   preprocess.py         ocr_engine.py         reconcile.py
                         aarvi_form.py         validate.py
                         generic_grid.py       rowconf.py
                              │
                              ▼
                       SQLite (app/db.py)
                              │
                     ┌────────┴────────┐
                     ▼                 ▼
              Review screen       Excel export
              (web/index.html)   (export_designs.py)
```

Three stages, in a deliberate order. Each one exists because the stage before
it cannot solve the problem alone.

---

## 2. Stage one — pre-OCR: make the page readable

`app/preprocess.py`

A PDF or photograph becomes exactly one normalised PNG per page. Four
operations, in this order:

1. **Rasterise.** PDFs are turned into images with `pypdfium2`, which needs no
   external binary — important for a self-contained deployment.
2. **Deskew.** A tilted photo is straightened, but only within ±15 degrees
   (`TS_MAX_DESKEW_DEG`). Deliberately narrow: a wider search starts "fixing"
   pages that were never crooked. Pages rotated a full 90 or 180 degrees are
   handled later, by a different mechanism, for reasons explained in §4.
3. **Flatten and equalise.** Shadow gradients from phone photos are flattened,
   then local contrast is raised (CLAHE) so faint pencil survives.
4. **Resize** to a long edge of 1,600 pixels (`TS_PAGE_LONG_EDGE`).

That resolution choice is worth knowing about, because it is a trap this
project fell into. Raising it to 2,400 appeared to improve handwriting accuracy
from 83.6% to 87.1%. It did not. It was compensating for a *different* defect
(see §3). Once that defect was fixed, 1,600 scored better than 2,400 *and* ran
faster. The lesson, recorded in the decision log, is that an improvement which
is really a workaround for an unfound bug will mislead you about everything
downstream.

---

## 3. Stage two — reading: text, then structure

### 3.1 Getting text off the page

`app/ocr_engine.py`

RapidOCR with the PP-OCRv6 models returns a list of text boxes, each with its
position on the page and a confidence score. Everything downstream works from
this list of positioned text, never from the image again.

**One setting here matters more than anything else in the system:**

```python
OCR_USE_CLS = os.getenv("TS_OCR_USE_CLS", "0") == "1"   # default OFF
```

RapidOCR includes an "angle classifier" that decides whether each text box is
upside down. On short numeric cells — exactly what a timesheet is full of — it
guesses wrong often. It was turning `09:00` into `00:60`. Switching it off
moved clock-time accuracy from 83.6% to 93.8%, a single-line change worth more
than ten points.

**Do not turn it back on** without running the full measurement suite. It is
pinned by `tools/guard.py` for this reason.

### 3.2 Turning text into a record

Two readers, tried in order.

**The profile reader** (`app/aarvi_form.py`, `app/form_profiles.py`) is the
primary one. It works by *anchors*: it looks for known labels ("NAME OF
EMPLOYEE", "DESIGNATION", "TOTAL"), finds where they sit on this particular
page, and then reads the values positioned relative to them. Because the
anchors are found per page rather than assumed at fixed coordinates, the same
profile tolerates a sheet that is shifted, scaled or slightly rotated.

`app/form_profiles.py` holds one anchor set per form family. Adding support
for a new client's layout usually means adding a profile here, not writing new
code — see `11-HOW-TO-EXTEND-IT.md`.

**The structural reader** (`app/generic_grid.py`) is the fallback, and it is
the more interesting piece of engineering. It finds the day grid on a sheet it
has never seen, without knowing the client at all. It does this by looking for
the longest run of consecutive day numbers across the page, clustering text by
position into rows and columns, and then reading each cell by *nearest column
centre*.

That phrase matters. The earlier version padded each column by half its width
and took the first match. On one real client sheet, day 24's column claimed
day 25's mark and then discarded it, so the 25th went missing for every
employee on the sheet. The client noticed before we did. Nearest-centre
assignment fixed it and took those sheets from 98.9% to 100%.

The structural reader also handles two things the profile reader cannot:

- **Several workers on one sheet.** A horizontal sheet can carry 33 people. One
  uploaded image becomes one page record per person.
- **Periods that cross a month boundary.** A sheet covering 21 March to 20
  April has a day axis that runs 21…31, 1…20. Exactly one month boundary is
  allowed in a run, which is enough for every real case seen and tight enough
  not to invent runs out of noise.

When both readers produce something, the structural result wins if the profile
result is weak. That rule alone recovered 33 employees on a single page.

### 3.3 Rescues, paid for only by pages that already failed

Three recovery paths exist, and all three are gated so that a page which reads
fine never pays for them:

- **Orientation rescue.** `preprocess` only deskews ±15°, so a sheet scanned
  sideways is never straightened, and on such a page every learned column
  position is meaningless. On the HO dataset, 207 of 247 pages produced no
  employee name at all. The fix re-reads the page at the other three
  orientations and keeps whichever finds the most anchors.
- **High-resolution rescue.** A page that produced too little text is re-read
  at higher resolution.
- **The header model** (`app/vlm_header.py`). For a handwritten header the OCR
  cannot resolve, a locally-hosted vision model reads just the header block.
  Optional, off by default locally, on in production. Local-only address; the
  page never leaves the machine.

All rescue work runs under a time budget (`RESCUE_BUDGET_S`) so one pathological
page cannot stall a batch.

---

## 4. Stage three — post-OCR: decide whether to believe it

This stage is what separates this system from a bare OCR script, and it is
where most of the engineering effort went.

### 4.1 Reconcile — repair using what the page says about itself

`app/reconcile.py`

A timesheet is partly self-describing. It states its own totals. It has a
month, so it has a known number of days and known weekday positions. The
reconciler uses these internal facts to repair the grid: if the sheet says 26
days present and 26 cells read as present, that is corroboration. If it says 26
and 24 were read, two cells are wrong or missing and the discrepancy is
recorded rather than smoothed over.

### 4.2 Validate — the rules

`app/validate.py`

Named checks, each producing an issue with a severity (`block`, `warn`, `info`):

- day rows must sum to the stated monthly total
- hours must be internally consistent; overtime cannot duplicate the total
- no impossible day (nobody works 20 hours)
- the identity must resolve against the master roster
- weekly offs should land on a consistent weekday — this is a *placement*
  check, and it is how the system detects a day axis that has slipped

One rule here carries a warning. `UNCOMPUTABLE_IS_NOT_FAILED = True` stops the
system blocking a page whose checksums simply cannot be computed because the
sheet does not state a total. That removed about half the false alarms. It also
briefly let two pages pass as `clean` while 15 of their 30 days were wrong,
which is the worst possible failure for this system. The fix was not to revert
it but to add the separate requirement that an unread row blocks `clean`
(`UNREAD_ROW_BLOCKS_CLEAN`). Both flags must stay as they are.

### 4.3 Row confidence — per-row verdicts

`app/rowconf.py`

Every day row gets a score and a verdict:

| Field | Meaning |
|---|---|
| `_row_conf` | A float. How much to trust this row |
| `_review` | `ok`, `review`, or `must_fix` |
| `_review_why` | A list of named reasons, so the UI can explain itself |

A `must_fix` row prevents the whole page from being called `clean`.

### 4.4 Page status

Three values, computed in `pipeline._page_status()`:

| Status | Meaning |
|---|---|
| `clean` | Read **and** corroborated against the sheet's own totals. No unread rows, no `must_fix` row |
| `review_optional` | Read, with something minor worth a glance |
| `needs_review` | Something must be looked at before this is trusted |

---

## 5. Two ideas that run through everything

### An unread cell is never credited

When scoring, truth and output are normalised by **different** functions, on
purpose:

```python
def truth_norm(v):   # an empty cell on the SHEET means a weekly off
    return "W" if v in ("S", "") else v

def got_norm(v):     # an empty cell in the OUTPUT means we did not read it
    return "W" if v == "S" else v
```

The asymmetry is the whole point. If the output side also mapped blank to "W",
then every cell the reader failed to see would score as a correct weekly off,
and accuracy would rise as the reader got worse. This exact mistake has been
made twice in this project's history — both times in the measurement code, not
the product — and both times it produced a flattering number that was wrong.

### Truth never comes from the system under test

Ground truth is derived from sources independent of the OCR: the PDF's own
embedded text layer, the client's own typed spreadsheets, or hand-grading
against the paper. Never from a previous run of the pipeline.

---

## 6. Supporting machinery

**Content-addressed cache.** Results are keyed on the page's hash *plus* the
pipeline version, so a re-upload of the same scan is instant, and a version
bump invalidates everything automatically.

This cache has its own hazard, worth knowing before you touch `process_page`.
The cached branch rejoins the common code with a different set of local
variables defined, and **every offline test harness passes `force=True`**, so
none of them exercises it. A defect once lived there across seven releases
while all tests were green. `tools/guard.py` now reads a real page twice,
specifically to cover this.

**Storage.** SQLite in WAL mode (`app/db.py`). Tables: `batch`, `page`,
`audit`, `page_lock`. The audit table is append-only.

**Page locking.** One person edits a page at a time. Others see who holds it
and get a read-only view. Locks expire after five minutes of inactivity.

**Identity.** When deployed, Caddy authenticates and passes the signed-in
username to the application in an `X-Remote-User` header, which it *sets*
rather than appends — so a browser cannot claim to be someone else. Every
upload, edit and export is stamped with that name.

---

## 7. Configuration

Nothing important is hard-coded. `app/config.py` reads everything from the
environment, so one build runs in every environment. The full annotated list is
in `source-code/deploy/config.env`. The settings that change behaviour most:

| Setting | Default | Effect |
|---|---|---|
| `TS_PAGE_LONG_EDGE` | 1600 | Working resolution. See §2 before changing |
| `TS_OCR_USE_CLS` | 0 (off) | The angle classifier. See §3.1. Leave off |
| `TS_VLM_HEADER` | 0 local, 1 production | The handwritten-header model |
| `TS_WORKERS` | 2 | Pages read in parallel |
| `TS_ROSTER_MIN_SCORE` | 82 | How close a name must match the roster |
| `TS_SUM_TOLERANCE_PCT` | 0.02 | Tolerance when comparing totals |
| `TS_DATA_DIR` | `/data` | Where everything written lives |

---

## Next

- Module-by-module detail: `07-CODE-REFERENCE.md`
- Before changing extraction: `06-ACCURACY-AND-TESTING.md`
- Why a particular choice was made: `09-DESIGN-DECISIONS.md`
