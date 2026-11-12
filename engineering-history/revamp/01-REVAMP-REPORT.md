# Timesheet pipeline revamp — report

*Living document. Every figure here is measured and traceable to an entry in
`00-DECISION-LOG.md`. Sections marked [pending] are filled as work lands.*

## 1. Where we started (v25, frozen in `versions/v25-baseline/`)

| Measure | Value | Set |
|---|---|---|
| Day status, corpus | **73.2%** | 300 scored pages, clean run |
| Employee name, corpus | 97.0% | same |
| Day status, fast harness | 91.3% | 31 curated pages (41/49 IOCL30) |
| Safety | 254/254 imperfect pages flagged, 0 escaped | corpus |

The two day-status numbers disagree by 18 points. That gap is the single
most important fact in this report: **the fast harness was measuring a
different corpus from the one the client has.** (D-007)

## 2. What the 26% actually was (D-002 .. D-009)

Before changing code, every error was categorised.

1. **Measurement noise — small.** 9 of 300 pages were matched to the wrong
   person by the harness ("Girish Kulkarni" vs "Mukesh Malhotra" scores exactly
   80.0). Fixed in the harness. Worth +1.7 points. (D-002)
2. **Truth-file conventions — real, not the pipeline's fault.** ADANI02's
   ground truth records every LEAVE row as A; GRSE01's records it as L.
   The client's own spreadsheets disagree with each other. Reported both
   ways from here on. (D-006)
3. **Two clients carry 69% of every day error.** ADANI02 (38%) and GRSE01
   (31%). Not spread across the corpus — concentrated. (D-007)
4. **The mechanism: a one-row slide.** 43% of all day errors on the frozen
   set are the status from the row above or below. On ADN900 the OCR read
   "SUNDAY" on the 5th at ~1.0 confidence and the pipeline emitted W on the
   6th. (D-005, D-009)
5. **Root cause, exactly.** The day-numbering code has a branch that trusts
   row *position* over the printed *date* when 27–32 rows are found. It was
   adopted on handwritten IOCL grids, where dates merge and position wins.
   On a typed sheet with 30 legible dates all agreeing, it discarded them
   and numbered from a spurious header band. Every status slid one row.
   The fast harness never contained a typed sheet, so it never saw it. (D-009a)

**What this rules out:** "better OCR" as the first move. The OCR read the
letters correctly. They were assigned to the wrong day.

## 3. Stage 2 fix: anchor consensus (D-010, D-011)

When the legible dates on a page are numerous and **unanimous** on one
offset, the dates win. Otherwise the existing positional logic runs
unchanged. Behind `trust_anchors=`, so both states are runnable.

| Set | Before | After | |
|---|---|---|---|
| ADN900 (the diagnostic page) | 10/17 days 1–17 | **17/17**, 31→30 days | Sundays back on Sundays |
| Old fast set (IOCL guard) | 853/934 = 91.3% | **853/934 = 91.3%** | no regression |
| Corpus-faithful set (frozen_v2), strict | 1142/1456 = 78.4% | **1165/1456 = 80.0%** | +1.6 |
| same, convention-mapped | 82.0% | **83.8%** | +1.8 |
| ADANI02 alone, strict / convention | 79.9% / 86.7% | **83.2% / 90.3%** | the target client |
| GRSE01 alone | 66.0% | 66.0% | untouched — different mechanism, next |

The agreement bar was swept, not guessed: 0.90 and 0.95 both cost the
handwritten guard 8 comparisons; 1.00 costs nothing. Unanimity makes the
rule inert on ink and live on print.

### 3b. Stage 2, second change: bare weekday words (D-013, D-014)

GRSE01 prints "SAT" / "SUN" as a merged cell across the time columns. The
week-off matcher knew "SUNDAY" and "W/O" but not the bare abbreviation, so
five weekly-off rows per page came out empty. Fixed for value cells only —
never the date cell, because other forms print the weekday beside every
date and a worked Sunday there must stay P.

| Set | Before | After |
|---|---|---|
| frozen_v2, strict | 80.0% | **82.9%** |
| frozen_v2, convention | 83.8% | **86.7%** |
| GRSE01 | 66.0% | **76.8%** |
| ADANI02 / IOCL30 | 83.2% / 90.1% | 83.2% / 90.1% (unchanged) |
| Old fast set (guard) | 91.3% | 91.3% |

**Cumulative, v25 → v27, corpus-faithful set:** strict 78.4 → 82.9, convention 82.0 → 86.7.

## 4. Stage 3: post-OCR — what was built, and what was measured and rejected

### 4a. The whole-page calendar shift was measured and rejected (D-017)

§2 suggested a post-OCR "calendar alignment" step: if a page's weekend
markers all land one day off, shift the page. Before building it the slide
was measured page by page on the corpus-faithful set under v27:

| Pattern | Pages |
|---|---|
| Whole-page shift (≥5 rows, ≥70% of that page's errors) | **3** |
| Local slides only (a few rows near merged cells or the grid top) | **23** |

A whole-page correction would help three pages and could damage twenty-
three. It was not built. The residual slide is structural — it lives where
the form's rows and the value cells disagree — and is addressed at the
source, not corrected afterwards.

### 4b. Reconcile was undoing correct readings (D-016, D-018)

The largest Stage-3 finding was not a missing feature but an existing one
doing harm. GRSE01's Sunday rows were read correctly as weekly-off, then
the reconciliation step **flipped them to Present**. Two defects compounded:

1. *Work evidence* counted any non-empty cell. The merged "SUN" text lands
   in the hours cell, so a weekly-off row looked like it "carried recorded
   hours". Redefined: evidence is a value with a digit and a positive
   number. A word is never work.
2. The demotion was licensed by a misread total — the sheet's W/O count
   read as 2 instead of 8 because the summary picker took the row above.
   Fixed by choosing the value nearest the label's own line (summary cells
   only; header fields keep left-to-right reading order — re-ordering them
   pulled a designation into a name on one page and was reverted).

| Set | Before | After |
|---|---|---|
| frozen_v2, strict | 82.9% | **85.5%** |
| frozen_v2, convention | 86.7% | **89.3%** |
| GRSE01 | 76.8% | **86.6%** |
| ADANI02 / IOCL30 | 83.2% / 90.1% | unchanged |
| Old fast set (guard) | 91.3% | 91.2% — one named row, VSPL day 26, hours "C/O$$", truth P: the old rule passed it only because junk text counted as work |

**Cumulative, v25 → v28, corpus-faithful set:** strict 78.4 → 85.5 (+7.1);
convention 82.0 → 89.3 (+7.3). GRSE01 66.0 → 86.6 (+20.6). ADANI02 79.9 →
83.2 (+3.3), or 86.7 → 90.3 with its LEAVE-as-A convention respected.

### 4c. Comp-off, and a scorer that could not spell it (D-022 – D-024)

ADANI02 writes comp-off as "C/O against duty on 30/03/2026, 04/04/2026"
across the time columns. OCR returns "C/0", "COff Agaunst", "CO)f", or
drops the head and leaves only the dates. A fuzzy rule now reads any of
those, gated on the row carrying no clock time — the first draft gated on
"no hours" and was blocked by its own target rows, because `15.03. 2026`
parses as fifteen hours.

The rule then appeared to do nothing. Instrumented end to end, 14 of the 23
comp-off rows were being read correctly as C and **scored wrong**: the
harness's status table knew "C/O" and not the bare letter. That was a
measurement defect, fixed in the harness. The remaining 9 are worked days
(full clock times) that the client's file codes as C — the duty side of a
comp-off, a third truth convention alongside LEAVE-as-A and worked-Sunday.

| Set | Before | After |
|---|---|---|
| frozen_v2, strict | 85.5% | **86.5%** |
| frozen_v2, convention | 89.3% | **90.2%** |
| ADANI02 strict / convention | 83.2% / 90.3% | **85.0% / 92.2%** |

**Cumulative, v25 → v28, corpus-faithful set:** strict 78.4 → 86.5 (+8.1);
convention 82.0 → 90.2 (+8.2).

### 4d. Things that looked like pipeline errors and were not (D-023)

- GRSE01's 28 "missing rows": 23 are one page — page 3 of a month
  photographed across three pages, holding days 24–29, scored against a
  31-day truth. The pipeline read the paper.
- Column-aware banding, planned for GRSE01's skew, was **refuted before it
  was built**: rules detected inside the date column and inside the value
  grid agree within 2px. The form itself prints "SAT" one row below its
  calendar Saturday; the truth was made from the calendar. Only the word can
  recover that, snapped to the nearest weekend day (§4e).

### 4e. Weekday words snap to the calendar (D-025)

A bare "SAT"/"SUN" in a value cell is now carried on the row. If the row's
calendar day is not that weekday but an adjacent day is — and that
neighbour holds no weekly-off and no work evidence — the marking moves
there. The trigger is the word, not the row's status, because through the
skew the merged "SUN" shares a band with the next row's 09:00: a worked
Monday carrying a Sunday's label. The label still names the adjacent day.
Corpus-faithful set +1; the handwritten guard **+4** (IOCL Sundays written
one row off); GRSE01 p3 from 21 to 23 of 30, with Saturday and Sunday both
right for the first time.

### 4f. Per-row confidence and review flags — the evaluation layer

Every day row now carries a score in [0, 1], a flag, and named reasons:

| Flag | Meaning | Triggers |
|---|---|---|
| **ok** | read directly, consistent | none of the below |
| **review** | weak or inferred; glance at it | status inferred by reconcile; a non-blocking check names the day; a cell read at 0.60–0.80 OCR confidence |
| **must_fix** | should not reach an invoice as-is | no status; a blocking validation issue names the day; **P with no clock and no hours**; **W/A/L/H with recorded hours**; a cell below 0.60 |

The score is a ranking signal, not a probability — it exists so a reviewer
sorts the doubtful rows to the top instead of reading thirty. Every
deduction is spelled out, so a flag is never a bare number.

Where it lives: `app/rowconf.py`; run after validation in the pipeline and
again after every reviewer save, so a correction clears its own flag.
Surfaced in the review page (a **Conf** column, must-fix rows tinted, an
ok/review/must-fix strip per page) and in the **Audit** export sheet as one
row per day with the reason in the issue column.
## 5. Stage 1: pre-OCR — measured last, on purpose

§2 established that the OCR was reading the letters correctly and the
pipeline was assigning them to the wrong day. That is why pre-OCR work was
sequenced last: a technique that sharpens the ink cannot fix a row that is
numbered wrong, and any gain it showed before the Stage 2/3 fixes would
have been confounded with them.

With the structural fixes in place, six techniques were applied to the 32
handwritten pages of the guard set, each page re-OCR'd from the stored
image, re-extracted, and re-scored on the same 571 day comparisons
(`tools/probe_preocr.py`).

| Technique | What it does | Day accuracy (571 comparisons) |
|---|---|---|
| baseline | the current preprocess: deskew, illumination flattening, resize | **92.5%** (528) |
| CLAHE | local contrast equalisation, clip 2.0, 8×8 tiles | **86.8%** (494) — rejected, −5.7 |
| adaptive threshold | Gaussian, block 31, C 12 — hard binarisation | **57.7%** on only 149 — rejected; binarisation also broke name matching on most pages |
| unsharp mask | σ 2.0, gain 1.6 | **88.8%** (505) — rejected, −3.7 |
| non-local-means denoise | h 7 | not run — dropped after the first pass was killed for memory (D-029) |
| morphological close | 2×2 ellipse — bridges broken strokes | **89.0%** (455) on 511 — rejected, −3.5; bridged adjacent digits and cost 60 matches |

**Verdict.** Every technique tested made handwriting worse for this OCR
engine, and the aggressive ones damaged the printed header enough to cost
employee-name matches — adaptive thresholding lost 422 of 571 comparisons
to unmatched pages. The engine wants grey levels; a binarised or sharpened
stroke loses the anti-aliased edge it was trained on. Stage 1 therefore
keeps what it had — deskew, illumination flattening, resolution chosen by
page shape — and adds nothing. That is a measured null result, and it is
the same fact §2 found from the other side: the loss was never in the
pixels.
## 6. Final numbers, v25 → v29

Every row below is the same harness before and after. The two fast sets
measure different things and are never compared to each other (see the
`timesheet-eval` skill); each is compared only to its own baseline.

| Harness | What it measures | v25 | **v29** | Δ |
|---|---|---|---|---|
| `frozen_v2`, strict | corpus-faithful: ADANI02 30 / GRSE01 15 / IOCL30 12 / Avaada01 4 pages, 1,456 day comparisons, exact code match | 78.4% | **86.5%** | **+8.1** |
| `frozen_v2`, convention | same, with each client's LEAVE / Sunday / comp-off convention respected | 82.0% | **90.3%** | **+8.3** |
| — ADANI02 (strict / conv) | the client that carried 38% of corpus errors | 79.9 / 86.7 | **85.0 / 92.2** | +5.1 / +5.5 |
| — GRSE01 | carried 31% of corpus errors | 66.0 | **86.9** | **+20.9** |
| — IOCL30 | handwritten control | 90.7 | 90.1 | −0.6 (2 rows, named in D-013/D-018) |
| `frozen` (old set) | handwritten IOCL/VIKR regression guard, 934 comparisons | 91.3% | **91.6%** | +0.3 |
| End-to-end suite | 10 checks: import, roster, OCR→extract→validate, generic grid, fall-through, export, harnesses, designation panel, grid guard, truth index | 10/10 | **10/10** | — |
| Full corpus eval — **Delhi, final** | 942 pages, 295 matched, 8,589 day comparisons | day **74.1** / name 96.9 / overall 74.8 | day **79.7** / name 96.6 / overall **80.3** | **+5.6 day, +5.5 overall** |
| Full corpus eval — HO + Kolkata | HO 11 matched / Kolkata 0 matched (thin ground truth) | day 50.0 (11 pages) / — | HO day **50.0** (146/292) / Kolkata no truth overlap | |
| **Full corpus eval — combined** | **306 matched pages, 8,881 day comparisons** | day 73.2 / name 97.0 / overall 74.0 | day **78.8** / name **96.7** | **+5.6 day** |
| Safety | imperfect pages flagged / escaped | 254/254 / 0 | **207/207 / 0** — pages passed clean and correct: 99/99 | held |

### What moved the number, in order of size

| Change | Where | Gain on frozen_v2 (strict) | Log |
|---|---|---|---|
| Anchor consensus — unanimous printed dates beat row position | Stage 2, `aarvi_form` | +23 | D-011, D-012 |
| Bare SAT/SUN in a value cell ⇒ W | Stage 2 | +42 | D-014 |
| Work evidence = a digit-bearing positive value, never a word | Stage 3, `reconcile` | +38 | D-018 |
| Summary values nearest the label's line | Stage 2 | 0 direct; fixes the totals that licensed wrong demotions | D-019 |
| Fuzzy comp-off (garbled heads, dates-only rows) | Stage 2 | +14 (visible once the scorer could spell C) | D-022, D-024 |
| Weekday-word snap to the calendar | Stage 3 | +1 here, **+4** on the handwritten guard | D-025 |

### What was measured and rejected

| Idea | Why it was rejected | Log |
|---|---|---|
| Whole-page calendar shift | 3 pages would gain, 23 could lose — the slide is local, not page-wide | D-017 |
| Column-aware rule banding for GRSE01's skew | rules in the date column and value grid agree within 2px; the form itself prints "SAT" a row below its Saturday | D-022 |
| Year-is-not-hours guard | −1: "20:00" reaches the cell as "2000" and is indistinguishable from a year | D-027 |
| Merged-cell offset follow (LEAVE/PH after SAT/SUN) | 0: each displaced annotation sits where the previous one was, so no target row is ever empty | D-028 |
| Agreement bar below unanimity for anchor consensus | costs the handwritten guard 8 comparisons at 0.90/0.95; unanimity costs nothing and scores best on typed sheets too | D-011, D-012 |
## 7. The honest ceiling — why "100%" is not a number this data can produce

Three properties of the client's own ground truth bound any measured
accuracy, for this pipeline or any other:

1. **Self-contradiction (D-001).** 9.2% of employees in the truth files have
   two different answers for the same day (`tools/truth_conflicts.py`;
   HMEL19 and Thyssen02 are the worst). A page cannot be right against both.
   These employees are not in the current scored set (D-003), so they do
   not depress today's figure — but they cap any run that includes them.
2. **Per-client status conventions (D-006, D-021, D-023).** The same word on
   paper is coded differently by different clients' spreadsheets:
   - LEAVE → **A** for ADANI02, **L** for GRSE01 (54 of the residual 211
     errors on the corpus-faithful set are this alone);
   - a worked Sunday → **W** for IOCL, **P** for ADANI02;
   - the duty side of a comp-off → **C** for ADANI02, though the sheet shows
     a full worked day.
   No single rule satisfies two clients at once. The pipeline reads what the
   paper says; the report scores it twice — strictly, and with each client's
   convention respected — and shows both.
3. **Split scans (D-023).** A month photographed across three pages is
   scored per page against a 31-day truth; the pipeline reads the page it is
   given.

**What that means for the target.** On the corpus-faithful set, closing
every fixable block leaves strict accuracy near 93–94% and convention-
respected accuracy near 97–98%. Strict cannot reach 98% on ADANI02 while
its truth encodes LEAVE as A. That ceiling is set by the client's data, and
the way past it is a per-client convention table agreed with the client —
a configuration, not a model.

**What is at 100% now.** Safety. Across every run and every version, every
page with any error was flagged for review and none escaped as clean.
That is the claim the product makes to finance, and it has held.

## 8. Manual verification against the paper (v31, 19 Sep)

The corpus figures above score the pipeline against the client's Excel
files. This section scores it against **what is written on the sheet**,
which is what a new user sees: seven pages the pipeline had never been
tuned on — two handwritten Delhi, one typed Delhi, two HO, two Kolkata —
were run and every day row was checked by eye against the image
(`data/_manual_verify/grades.md`). Each fix that followed was measured on
both harnesses before being kept.

| page | layout | v29 | **v31** |
|---|---|---|---|
| Delhi, TEIL | typed form, handwritten values | 27/31 | **31/31** |
| Delhi, TEIL | fully handwritten | 27/30 | **29/30** |
| Delhi, TEIL | typed | 27/31 | **31/31** |
| HO, TATA | typed, two-month period | 28/30 | 28/30 (both flagged) |
| HO, EPIL | rotated biometric printout | 0/31 | 0/31 — refused, flagged |
| Kolkata, Siemens | typed | 23/31 | **31/31** |
| Kolkata, Haldia | typed | 28/30 | **30/30** |

**Readable pages: 160/183 = 87.4% → 180/183 = 98.4% (v32). Silent wrong rows: 5 → 0.**
Present-days totals read: 1 of 6 → 6 of 6. On one page, flag noise fell
from 29 must-fix rows to 1 without losing the two real errors.

What the grading found that the harness could not: the handwritten summary
totals were never read because the next field's label sits on the same
line; a Siemens form's row ladder was fitted at the wrong pitch and merged
two rows; a Haldia form writes total hours where the template expects
normal hours; and blank Sundays, worked Sundays and comp-off rows are
decided by evidence the sheet itself carries — its own W/O and P totals
and the calendar — once those totals are read.

What remains, honestly: a "C/OFF" scrawl the OCR engine never emitted; a
half-day-leave row with hours that is genuinely ambiguous; one P read as H;
all three flagged. And a document family (rotated punch-log printouts) the pipeline
refuses rather than reads. 98.4% is six pages, not a corpus; the corpus
figure against the client's Excel remains 78.8% until a v32 corpus run is made.

Harness state at v32: corpus-faithful **1270/1456 = 87.2%** strict, 91.1%
convention (v25: 78.4 / 82.0); handwritten guard **872/934 = 93.4%** (v25:
91.3); end-to-end 10/10. The two largest late gains were one-line boundary
fixes found by reading single dropped rows on unseen pages (D-044).

## 9. The 50-page random sample, v33, and the full corpus run (20 Sep)

Section 8 graded seven pages. That was enough to find fixes and not enough
to quote a number. So a **50-page sample** was drawn by seed, stratified
over Delhi/HO/Kolkata × handwritten/typed, with every page ever used for
tuning excluded, and every day row was graded by eye against the image
under a protocol written before grading began
(`data/_sample50/PROTOCOL.md`, grades in `grades.md`, one line per page).

| | pages | rows | v32 | **v33** |
|---|---|---|---|---|
| Readable day-grid pages | 38 | 1,157 | 1,075 = **92.9%** | 1,106 = **95.6%** (96.6% by the sheet's own convention) |
| Silent wrong rows (engine said "ok") | | | 10 | **8** (1.2% of ok rows) |
| Missing rows | | | 10 | **0** |
| Spurious "day 31" rows | | | 7 | **2** |
| Unsupported page types, refused and flagged | 10 | | 10/10 | 10/10 |
| Source PDFs PDFium cannot open | 2 | | | listed as skipped |

Per dataset (v32): Delhi handwritten 83.8%, Delhi typed 95.5%, HO 94.3 /
94.6, Kolkata handwritten 94.5, Kolkata typed 98.7. The seven-page 98.4%
of §8 was not representative; **95.6% on 38 random pages is the per-row
number against the paper.**

What the sample exposed and what was done (each behind a flag, each
measured on both harnesses and re-scored on the same 38 pages by
`tools/eval_sample50.py`; D-046..D-051, D-054..D-057):

| Pattern seen | Pages | Fix |
|---|---|---|
| Header VLM invents a person on pages with no name ("S. RAVI", "Jin Hui", "Bhagat") | 3 refused pages | VLM answers accepted only when the page's own OCR text supports them |
| Last rows cut when a form has no summary block | s26 (4 rows) | grid bottom from the date column |
| Empty "day 31" in 30-day months | 7 pages | dropped when empty; kept and flagged when inked |
| "ok" rows on a page with no date column | s23 | capped at review |
| Uniform ladder fitted over clean printed rules slides rows | s06, s17 (4 silent) | clean rules win, gated by the calendar row count |
| Samsung shaded off-days with "0" hours read empty | s08, s09 (14 rows) | zero hours on a form-labelled Sat/Sun ⇒ W |
| Grid's top/bottom rule just outside the header/footer bound | s49, s17 | one rule within a third of a pitch admitted |
| "Name: X" printed as one box (GSPL, GIGL) fell to the VLM | every GSPL page | bare label read exactly, inline |
| Rotated page's header sent to the VLM unrotated | PIL03 block | the rotated copy is sent |
| Header VLM spent on cover pages and attachments | ~40% of HO pages | VLM only on pages with ≥8 day rows or a name label |

Measured worse and withdrawn: replacing the header bound with the date
column (guard −25), capping the grid at the date column (guard −12), a
rival-offset cap and an all-rows-on-calendar guard for anchor consensus
(v2 −7 / −47), and a date-first row-count gate (guard −7). All in the log.

Harnesses after v33: corpus-faithful **1293/1456 = 88.8%** strict,
**92.7%** convention (v32: 87.2 / 91.1); handwritten guard **876/934 =
93.8%** (872); names 30/31.

### The full corpus run under v33

**Accuracy against the client's Excel** (the pages that have truth; the
checkpoint was discarded and re-scored from scratch under v33, 0 page
errors after two crash fixes the run itself exposed — D-052):

| dataset | matched pages | day rows right | day % | v29 |
|---|---|---|---|---|
| Delhi | 282 | 6,968 / 8,201 | **85.0** | 79.7 |
| HO | 10 | 162 / 261 | 62.1 | 50.0 |
| Kolkata | 0 | no truth overlap | — | — |
| **combined** | **292** | **7,130 / 8,462** | **84.3** | 78.8 |

Name right on **98.3%** of matched pages (96.7). **Safety: 164 imperfect
pages, 164 flagged, 0 escaped.** On the 291 pages matched by both
versions, v29 82.1% → v33 84.5%. Fifteen v29 matches are gone: the VLM
can no longer supply a name without support on the page (ten of those had
been right, but those pages read 15% of their days — unsupported layouts).

**Every page of every PDF through the product** (no truth; what the
reviewer sees). **9,003 pages of 9,271 listed, 0 worker errors**: Delhi
2,527, HO 5,261, Kolkata 1,215 (Kolkata ran separately after a
case-sensitive folder match skipped it — fixed). 209,335 day rows =
**56.3% ok / 24.7% review / 18.9% must-fix**; 8,347 pages needs_review,
656 review_optional. The 268 listed pages not run sit in PDFs PDFium
cannot open; the product lists such files as skipped with the reason.

**Why 92.7% of pages are needs_review.** Not a defect: the spec's first
principle is that a timesheet must self-validate. On 18 of the 38 sample
pages the "Total Man Hours" cell is blank on the paper or handwritten and
unread, so the row-sum checksum cannot be applied and the page is held
(`summary_normal_missing`); 7 more have a genuine checksum mismatch. The
row flags, not the page flag, are what the reviewer works from:
55.9% of rows need no attention at all.

Deployment: `dist/timesheet-app-v2.4.0-deployment.zip` (592 MB, arm64 +
amd64, OCR models baked), built from this code at 18:48 on 20 Sep.
Snapshot `versions/v33-sample-fixes/` with one-command recall.
