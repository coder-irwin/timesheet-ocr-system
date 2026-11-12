# v39 backlog — defects found by the 6 Oct 2026 corpus run

Ranked by how much each would move the numbers, not by how interesting it is.
Every item names the evidence it came from, so none of them is a hunch.

Measured state when this list was written (pipeline v38-no-cls-drift-window,
1,006 of 1,218 pages scored, Delhi complete, HO starting):

    day status           7,269 / 8,802 = 82.6%   (Delhi only -- the hardest site)
    employee name        98.0%
    pages with a wrong day that were flagged   155 / 155
    pages with a wrong day NOT flagged           0      <- the promise, holding
    pages scored          303     pages perfect  148 (49%)

---

## 1. Almost nothing is passed as clean  — BIGGEST PRODUCT ISSUE

    page status of 303 scored pages:  needs_review 298 · review_optional 2 · clean 3

The system is *safe* but barely *labour-saving*. The commercial case rests on a
reviewer being able to skip the confident pages; at 1% clean there is nothing to
skip, and the client reads "check everything, but with colours".

This is not the same problem as accuracy. 148 of those 303 pages were read
PERFECTLY and still went to review. Something is raising a blocking issue on
pages that are entirely correct.

Next step: group the scored pages by which validation issue blocked them. The
suspicion is one or two over-eager rules (most likely the man-hours checksum
against sheets that state a total the rows were never meant to sum to)
accounting for most of the 298. Until that is counted, do NOT loosen any rule --
loosening the wrong one costs the zero in the line above, which is the one thing
that must not move.

## 2. The loss is concentrated in three client layouts

    61 pages (20% of those scored) carry 1,156 of the 1,533 wrong days = 75%
    worst folders:  ADANI02 Adani Infra 19 pages · GRSE01 Garden Reach 17 ·
                    Avaada01 Giriraj Renewable 9

45 of the 61 worst pages come from three folders. Per-layout work on those three
would move the corpus figure further than any amount of general tuning, and the
general tuning risks the pages that already work. Half the scored pages are
already perfect.

## 3. Form furniture is being read as the employee's name

    read name 'Status As On Date'
    read name 'Status ft As On Date:'
    read name 'RAMESH CHANDRA'

The header reader is returning a label where a person should be. On these pages
the sheet is attributed to nobody, so it cannot reach a roster match or a payroll
row. Same class as the already-fixed "CONTRACTOR NAME:- AARVI ENCON LTD." defect
on the SHELL sheets (generic_grid.looks_like_label), so the existing guard
probably just needs to cover the header path too.

## 4. Rows merge on dense layouts (carried over from D-074)

Cells come back holding several rows' values ('4 4 4'), after which every day
below is read off the wrong row and slides against the calendar. Currently
mitigated by refusing to call those rows confident, which turned 15 silent
errors into 2 -- but the rows are still read wrong, and 270 extra rows per
1,157 now go to review because of it. The real fix is row segmentation driven by
the printed rules rather than ink clustering.

## 5. Truth coverage, not a defect — but it limits what can be claimed

    689 pages could not be matched to a ground-truth row
    470 of them from ONE folder (Technip Energies, April 2026)

These pages were read; they could not be scored, because the client's own
spreadsheet has no row for them. Worth asking the client for the missing truth
rather than engineering anything. It also means the corpus figure is measured on
a subset that under-represents that client.

---

## Deliberately NOT on this list

**Raising page resolution.** Measured and rejected: with the angle classifier
fixed, 1600px (93.8% on clock times) beats 2400px (93.2%). The earlier apparent
gain was the classifier flipping fewer large glyphs. See D-073.

**The clock-grammar repair layer.** Built, measured, rejected: it doubled
genuinely wrong readings, 19 to 38. Kept in the tree switched off. See D-072.

---

# RUN COMPLETE — 6 Oct 2026, 1,218 pages in 4h20m, 0 crashes

    day status      7,527 / 9,745 = 77.2%     (v33 was 84.3% on 292 matched pages)
    employee name   98.2%
    matched pages   338                        (v33 matched 292)
    pages with a wrong day that were flagged   185 / 185
    pages with a wrong day NOT flagged           0

The headline fell, and it is NOT a reading regression. 46 more pages now match
truth because names are read better, and 42 of the matched pages produce
**zero day rows** — a total extraction failure on three specific layouts. Those
42 pages contribute 1,075 compared days, every one scored wrong, 11% of the
whole denominator.

    all matched pages                 7,527 / 9,745 = 77.2%
    excluding the 42 zero-day pages   7,527 / 8,670 = 86.8%
        Delhi excluding them  86.8%
        HO    excluding them  86.9%

The two sites agree to within a tenth of a point once the broken layouts are
removed, which is the sign that 86.8% is the real figure for pages the system
can read at all, and that the rest is three bugs rather than general weakness.

## 6. Three layouts produce NOTHING — highest-value fix in this document

    SHELL02 Shell Hazira        22 pages
    GRSE01  Garden Reach        16 pages
    Petrofac / Avaada / Solarium / Shell04   1 each

Three *different* causes, confirmed by probing one page of each:

**(a) Petrofac — attendance is marked `1`, not `P`.** The sheet writes `1` for
present, `WO` for weekly off, `PH` for public holiday. `WO` and `PH` already
map correctly; `_cell_status("1")` returns None, so no band reaches MIN_RUN,
no block is produced, and the page yields nothing while reading the employee's
name perfectly.
Fix: a digit `1` should count as present *only* in a day column of a band that
already contains at least one recognised status token. The sheet declares its
own vocabulary; read that rather than hardcoding a client.
Do NOT map `1 -> P` globally — `1` is also a day number, an overtime value and
a count.

**(b) GRSE01 — no day axis is found at all.** `find_day_axis` returns None, so
there is nothing to read. Needs its own diagnosis; the header is probably not
a run of day numbers in the form the finder expects.

**(c) SHELL02 — the axis IS found (24 days) and a block IS produced, and the
day cells read cleanly (`P` x19, `L` x5, `S` x2), yet zero days match truth.**
24 days found on a 31-day month points at a day-offset or a wrong truth row
rather than a reading failure. Diagnose before touching anything.

Clearing (a) and (b) alone would return ~38 pages and roughly 970 days to the
measurement, and move the corpus figure from 77.2% towards 86.8%.

## 7. HO and Kolkata are barely measurable — fix the TRUTH, not the code

    Delhi    942 pages ->  303 matched
    HO       247 pages ->   35 matched
    Kolkata   29 pages ->    0 matched

v33 was the same shape (HO 10, Kolkata 0), so "84.3% corpus accuracy" was
always ~97% a Delhi number, and so is this one. The blocker is the matcher
refusing to choose between several truth rows carrying the same name in
different months — the right behaviour, since a scorer that guesses flatters
itself. Ask the client for truth rows keyed by month, or by employee code.
Until then two of the three sites cannot be measured at all, which is a bigger
limit on what can be claimed than any single bug above.

---

# UPDATE 7 Oct 2026 — two of the "dead layouts" were never dead

Item 6 above listed 42 pages producing zero days across three layouts. That
count is now wrong, and the correction matters more than the original entry.

**Garden Reach (16 pages): NOT a defect.** Read by eye against the paper. The
pages are read perfectly; the scanned sheet covers days 24-31 while the
client's spreadsheet row covers 1-23, so the scorer compared disjoint ranges
and reported 0 of 23. Fixed in the scorer (D-077), not in the pipeline.

**Still real, still open:**
- **SHELL02 Shell Hazira, 22 pages.** Axis found (24 days on a 31-day month), a
  block is produced, day cells read cleanly ('P' x19, 'L' x5, 'S' x2), yet zero
  match truth. Points at a day-offset or a wrong truth row. Diagnose before
  touching anything -- it is the largest single cluster left.
- **Petrofac.** Attendance marked `1`, not `P`; `_cell_status("1")` returns
  None so no band reaches MIN_RUN. Fix must be contextual: a digit `1` counts
  as present only in a day column of a band already carrying a recognised
  status token. Never map `1 -> P` globally.
- **IOCL30 hours column** reads 31 where the sheet states ~200. Own defect.

## New since the run

**8. Form furniture read as the employee name.** 'Status As On Date',
'RAMESH CHANDRA', and on one page the MONTH value ('Jut.26') landed in
employee_code. Same class as the already-fixed SHELL "CONTRACTOR NAME:-" bug;
the existing looks_like_label guard probably just needs to cover the header
path.

**9. Count checksums cannot detect a permutation.** ADN902 and ADN904 read the
right NUMBER of each status onto the WRONG DAYS, and every total reconciled.
Mitigated for now by refusing to call such pages clean (D-078), but nothing
DETECTS it. A real detector would need per-day evidence the sheet does not
carry -- worth thinking about before promising anything about placement
accuracy.

**10. Only Delhi can be measured.** Unchanged and still the biggest limit on
what can be claimed: HO matched 35 of 247 pages, Kolkata 0 of 29. Ask the
client for truth keyed by employee code rather than name.

## Re-run needed
The 77.2% corpus figure predates the scorer fix and understates the system.
A fresh run under v41 is ~4.5 hours and has not been done.


---

# 8 Oct 2026 — the "292 pages with no name", diagnosed

Not one defect. Four families, each examined by eye, none a quick win. All are
already stopped with `identity_missing` and a plain message, so this is a
CAPABILITY gap (manual entry) and not a safety one. Ranked by pages.

**A. Multi-employee grid, scanned sideways — Thyssen Krupp, 37 of 37 pages.**
`find_day_axis` returns None at 0, 90, 180 and 270 degrees. Start by asking why
the day header is not found at the orientation where the text reads correctly.

**B. Multi-employee grid, unknown vocabulary — Brilliant Bio Pharma, 12 of 12.**
Uses PP / W / EL / AB. The day axis also lands wrong (11 days of ~30), so fix
the axis before the vocabulary or the vocabulary fix cannot be measured.

**C. Statutory FORM D attendance register — Trichy Airport, 12 of 12.**
Many employees per page; attendance marked as circled handwriting that OCR
reads as 'B', 'G', '4', '告'. This needs mark detection, not text recognition,
and is the hardest of the four. Consider declaring it out of scope rather than
half-supporting it.

**D. Not a timesheet — Bharat Petroleum, 30 of 39.**
"Aarvi Encon Leave Record Part-B", a multi-employee leave-balance table. The
right behaviour is to RECOGNISE it as not-a-timesheet and say so, rather than
to extract from it. Cheapest of the four and the clearest message to a user.

**Rejected before coding (keep rejected):** rotating the page. Tried all four
orientations through the full pipeline on four of these layouts; none yields a
name at any rotation. The sideways scans are real but are not the blocker.


---

# STATUS 8 Oct 2026 (v45)

    CLOSED  1. Almost nothing passes as clean -> 0.4% to 10.0%, 0 wrong pages
               passing clean (D-083). Counts accepted as verification; a
               calendar-based placement check catches the drift they cannot.
    CLOSED  2. Shell Hazira "22 unexplained pages" -> never broken; the
               disjoint-date-range artefact, fixed by D-077.
    CLOSED  6. "Three layouts produce NOTHING" -> 0 zero-day pages corpus-wide.
    CLOSED  3/8. Form furniture read as a name -> D-082 (label phrases, not a
               lower threshold) and the Solarium column-header revert.
    CLOSED  9. Count checksums cannot detect a permutation -> they still
               cannot, but the calendar can (D-083).
    DROPPED D. "Recognise it is not a timesheet" -> one-in-six recall. Replaced
               by quoting the page heading to the reviewer (D-084).

    PARTLY  A. Thyssen Krupp 37 pages  [axis now 30 days, D-087] — the sideways scan WAS the blocker for
               the grid (not for the name). D-085 makes the orientation rescue
               score on cells actually read; ~1 page in 3 now yields data.
               Remaining: cells hold HOURS (10.0, 12.5) not letters, so
               presence must be inferred from a numeric day cell — the same
               generalisation Petrofac's `1` needs. Do both together.
    PARTLY  B. Brilliant Bio 12 pages  [axis now 31 days, D-087] — rotation recovers 5-7 day cells on two
               of them. Axis still lands short (12-14 of ~30) and PP/EL/AB are
               still unknown to _cell_status. Fix the axis first.
    OPEN    C. Trichy Airport 12 pages — statutory FORM D, circled handwritten
               marks. Needs mark detection, not OCR. Consider out of scope.
    OPEN    4. Rows merge on dense layouts (D-074). Mitigated by flagging, not
               fixed. The calendar check (D-083) now catches the drift it
               causes, which lowers the urgency.
    OPEN    Petrofac `1` means present; IOCL hours column reads 31 of ~200.
    OPEN    7. Only Delhi can be measured. Client-side: truth keyed by employee
               code. NOTE: only Technip genuinely lacks data — Bharat
               Petroleum, Thyssen and Shell have plenty and fail on OUR bugs.


---

# STATUS 8 Oct 2026 (v47-day-axis-cross-month)

The day axis is fixed (D-087): cross-month periods are read whole, and a header
straddling a cluster boundary is no longer cut in half.

    Brilliant Bio axis   12 -> 31 days
    Thyssen Krupp axis   24 -> 30 days
    pages that produced NOTHING: 0 of 12  ->  6 of 16, 74 day cells

**What is left on those pages, in order:**

1. **Status vocabulary.** BBPP01 writes PP / W / EL / AB; `_cell_status` knows
   none of them. This is now the top blocker -- the axis reaches the cells, and
   the cells are not understood. Collect the vocabulary per layout from the day
   columns FIRST (tools exist in the session history), then extend
   `_cell_status`. Do NOT widen it to bare numbers; see D-088.
2. **Thyssen cells hold HOURS (10.0, 12.5), not letters.** Presence has to come
   from a numeric cell, and the contextual version of that rule measured no
   gain twice (D-086, D-088) because its precondition needs a status letter in
   the same band. A different precondition is needed -- most likely "this
   COLUMN is a day column AND the row already matched an employee", which is
   stronger evidence than a sibling letter.
3. **Petrofac** `1` means present -- same shape as 2.
4. **Trichy** circled handwriting: still recommend declaring out of scope.

**Do not re-try:** rotating to recover a NAME (D-081); scoring a rotation by
axis SIZE (D-085); bare-number presence with the current precondition
(D-086, re-measured D-088).
