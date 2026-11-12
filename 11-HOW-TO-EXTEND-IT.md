# 11 — How to Extend It

The four things you are most likely to need to do, and where each one belongs.

**Before changing anything that affects extraction, read
`06-ACCURACY-AND-TESTING.md`.** It is short and it will save you from the two
most expensive mistakes available in this codebase.

---

## 1. Supporting a new client's form layout

This is by far the most common extension, and it is usually a **data change,
not a code change.**

### Why this is the right place

Measured at scale: **56% of pages failed because their summary labels were not
found at all.** Not misread — absent. Those pages were not the AARVI ENCON form
the original anchor set was written for; they were Samsung sheets, KBR weekly
sheets, and other client layouts.

That was the single largest source of lost accuracy — larger than handwriting,
page warping and OCR quality combined. And it is not a research problem. Each
layout is a dictionary of labels.

### How a profile works

`app/form_profiles.py` holds one `FormProfile` per form family:

```python
@dataclass(frozen=True)
class FormProfile:
    key: str                                   # short identifier
    label: str                                 # human name
    signature: tuple[str, ...]                 # strings unique to this layout
    header_anchors: tuple[Anchor, ...]         # where the header fields are
    summary_anchors: tuple[Anchor, ...]        # where the totals are
    column_anchors: dict[str, tuple[str, ...]] # the day-grid columns
    split_fields: dict[str, tuple[str, ...]]   # cells packing several numbers
    notes: str = ""
```

Detection scores the page's text against every profile's signature and takes
the best match. Deliberately simple and inspectable: adding a layout means
appending a dictionary, not retraining anything.

Three profiles ship: AARVI ENCON (the dominant family, covering IOCL, ADANI,
SAFEARTH and most others), Samsung, and KBR.

### Steps

1. **Collect examples.** Ten or more pages of the new layout. Without several,
   you will tune to one page's quirks.

2. **See what the reader actually sees.** Do not guess at the labels:

   ```bash
   ./.venv/bin/python tools/probe_nogrid.py <path-to-page>
   ```

   Other useful probes: `probe_orientation.py` (is it simply rotated?),
   `probe_generic_coverage.py` (can the structural reader already reach it?).

3. **Check whether you need a profile at all.** The structural reader
   (`generic_grid.py`) handles many unseen layouts already. If it reads the
   grid correctly and only the header fields are missing, you need header
   anchors only.

4. **Write the profile.** Copy the closest existing one. For `signature`, pick
   strings that appear on this layout **and nowhere else** — a client name in
   the title block is usually ideal. A signature that also matches AARVI sheets
   will mis-route thousands of pages.

5. **Add it to `PROFILES`.**

6. **Measure.** Run the fast harness, then the full guard:

   ```bash
   make fast
   ./.venv/bin/python tools/guard.py
   ```

   You are checking two things: that the new layout now reads, **and that
   nothing else moved.** A new signature that steals pages from another profile
   will show up as a drop elsewhere.

7. **Build truth for it** so it can be scored in future, ideally from the PDF's
   own text layer — `tools/isgec_truth.py` is the pattern to copy.

8. **Record it** in the decision log with the measured before and after.

### The mistake to avoid

Do **not** add a global rule to handle one layout's quirk. This was tried three
times (D-096 to D-098) for difficult HO layouts. Each fix worked on its target
page and damaged the wider population — one took accuracy from 93.8% to 89.7%.
All three are in the code behind flags set to `False` with their measurements.

Per-layout behaviour belongs in a profile. That is what profiles are for.

---

## 2. Changing the Excel output

`app/export_designs.py` (679 lines) holds six designs. The one the client sees
produces six worksheets: `Timesheet Detail`, `Invoice`, `Attendance`, `Audit`,
`Payroll_Import`, `Dashboard`.

To change a layout or add one:

1. Find the design function in `export_designs.py`.
2. Register it so it appears in `GET /api/export-designs`.
3. Verify by exporting and **opening the file**, not by reading the code.

Worth knowing: the end-to-end test parses the `Attendance` sheet by locating a
header row containing `Employee Name` and then columns labelled `1` to `31`. If
you restructure that sheet, update `tools/e2e_prod_test.py` or it will report a
false failure.

The shipped designs are sensible but were not derived from AARVI's own payroll
templates. If their system expects a specific column order, this is where it
changes.

---

## 3. Adding a validation rule

`app/validate.py`. Rules produce issues with a severity:

| Severity | Effect |
|---|---|
| `block` | Page becomes `needs_review` |
| `warn` | Page becomes `review_optional` |
| `info` | Recorded, no status effect |

Steps:

1. Write the check as its own function returning issues.
2. Give the issue a stable `code` — the UI and the harnesses key off it.
3. Write the `message` for the reviewer, not for a developer. Say what is wrong
   and what to look at.
4. **Measure the false-alarm rate.** This is the step people skip. A rule that
   flags correct pages trains reviewers to ignore flags, which is worse than
   having no rule. `tools/probe_false_alarms.py` exists precisely to answer
   "which validation rule blocks pages that were read perfectly?"
5. Run the guard. A new blocking rule changes the `clean` rate, and the guard
   will tell you by how much.

Put it behind a flag defaulting to the measured-better value, as the existing
rules are.

---

## 4. Changing extraction or OCR

The highest-risk area. Both serious regressions in this project's history came
from here.

```bash
# 1. Baseline
./.venv/bin/python tools/guard.py

# 2. Change ONE thing

# 3. If you touched OCR or preprocessing, recapture the frozen text first
make freeze        # ~8 min

# 4. Measure what you aimed at
make fast          # ~1 s

# 5. Measure what you did NOT aim at
./.venv/bin/python tools/guard.py

# 6. Keep or revert — completely, every edit, not just the flag

# 7. Record it, with numbers, in the decision log

# 8. Bump PIPELINE_VERSION in app/pipeline.py
```

Step 8 is not optional. Results are cached on page hash plus pipeline version.
Without the bump, already-processed pages return their old answer and your
change will appear to do nothing.

Step 5 is the one that matters. Check the **rows wrong and unflagged** count
specifically. If it moved up, your change is bad regardless of what the
headline accuracy did.

---

## 5. Where things live

| I want to… | Go to |
|---|---|
| Support a new client layout | `app/form_profiles.py` |
| Change how a field is located | `app/aarvi_form.py` |
| Change grid detection on unknown sheets | `app/generic_grid.py` |
| Change image handling | `app/preprocess.py` |
| Change OCR settings | `app/ocr_engine.py` |
| Add or change a validation rule | `app/validate.py` |
| Change what counts as a confident row | `app/rowconf.py` |
| Change `clean` / `needs_review` logic | `app/pipeline.py`, `_page_status()` |
| Change the Excel output | `app/export_designs.py` |
| Add an HTTP endpoint | `app/main.py` |
| Change the review screen | `web/index.html` |
| Change a default setting | `app/config.py`, or an environment variable |
| Add a field to the database | `app/db.py` |

---

## 6. House style

Worth matching, because it is a large part of why the codebase is navigable:

**Comments say why, not what.** The code says what it does. The comments record
the measurement that justified it, often with the numbers and the decision
identifier.

**Measured decisions are flags with their evidence attached:**

```python
NUMERIC_CELL_IS_PRESENT = False  # D-086: measured, no gain (+1 cell). OFF.
```

**Rejected work stays in the code, turned off, with its numbers.** That is what
stops the next person rediscovering it.

**Module docstrings explain why the module exists** before explaining what it
does. `app/form_profiles.py` is the model to follow.
