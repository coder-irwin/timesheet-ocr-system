# Corpus expansion and the measurement bottleneck

*Work log for the three-dataset upgrade (Delhi + HO + Kolkata).*

## Starting point

Measured before any change, on the existing 49-page Delhi evaluation:

```
fast harness   day_status 710/787 = 90.2%   OVERALL 745/837 = 89.0%
full pipeline  day 757/845 = 89.6%  name 27/28 = 96.4%  desig 21/26 = 80.8%
               OVERALL 805/899 = 89.5%   0 page errors
```

Note the full-pipeline run was made with the VLM **off** (Ollama was not
running). The 88.2% recorded at the client demo was measured with it on. The
rule-based pipeline alone is therefore at least as accurate as the demo
configuration, which is why the shipped container needs no AI model.

## Where the errors actually are

`tools/diag_days.py`, on the day comparisons it covers:

```
correct        86.5%
row_missing     3.4%   grid recovery
status_empty    3.4%   status inference
status_wrong    6.7%   misread
```

Confusions are overwhelmingly one pair: **W->P 6, P->W 4**, with A->W and
A->P once each. Weekly-off versus present is the whole game.

Errors are also concentrated, not diffuse: **6 pages carry 59 of the 88 day
errors (67%)**, while 13 of 28 matched pages are already perfect.

## The real bottleneck was measurement, not extraction

Two findings dominated everything else.

**1. Half the corpus was invisible.** 23 of 49 pages did not match any ground
truth row, so they were never scored. Of those, 8 failed because the month had
bled into the employee-name field:

```
"APRTL.2026 YOGESH RAMAM"     should be YOGESH RAMAN
"SANJAV BOSE APRIL-2026"      should be SANJAY BOSE
"APRIL-2026"                  no name recovered at all
```

This is a product defect, not merely an evaluation artefact -- that string is
what a reviewer would see in the delivered output, and it also prevents the
roster from ever identifying the employee. It further means the **96.2%
reported name accuracy was survivorship bias**: the contaminated names failed
to match and so were excluded from the denominator.

**2. Ground truth was being discarded at scale.** The legacy `parse_truth`
recognised one specific Excel shape and silently returned nothing for the
rest, parsing 35 of 702 files. The rejections were cosmetic:

| Cause | Effect |
|---|---|
| `Employee_Name` != `employee name` | 73 Delhi files dropped over one underscore |
| header below row 15 | outside the search window |
| demanded >= 20 day columns | excluded 15-day fortnightly sheets |
| stricter header regex | missed day columns headed `29 Fri` |

## Changes made, with measurements

### A. Strip month/year from the employee name — KEPT

`aarvi_form.strip_period_from_name`, behind `STRIP_PERIOD_FROM_NAME`.
Deliberately conservative: month-like words are removed **only when a year
token is also present**, so a genuine name resembling a month ("MAYA", "MAY")
is untouched. Verified on those cases explicitly.

```
matched pages    26 -> 30
day_status       710/787 = 90.2%  ->  820/903 = 90.8%
employee_name     25/26           ->   29/30
OVERALL          745/837 = 89.0%  ->  ... = 89.4%
```

Both the numerator and denominator grow here, because fixing the name makes
previously-invisible pages measurable. The honest reading is: **+4 pages of
coverage, and day accuracy improved on the enlarged set.**

### B. Recover the period from the file path — KEPT, but measured NEUTRAL

`reconcile.infer_period_from_source`. Every calendar-based weekly-off repair
is gated on knowing (year, month); 9 of 49 pages resolved no period at all,
including the two worst pages in the corpus (58.1% and 60.0%). The path states
it plainly: `.../VIKR01 Vikram Solar Pvt. Ltd APR  2026/VSPL APR 2026.pdf`.

The mechanism works -- **all 9 unresolved pages now resolve**. But it produced
**no measurable accuracy change**, because 7 of those 9 pages are unmatched
and therefore unscored. Kept anyway: it is correct, it is free, it cannot
regress (baseline reproduced exactly), and it is precisely the robustness
needed for unseen data where the printed month is unreadable.

Recorded here so nobody later "discovers" this as a win. It is not, yet.

### C. Robust ground-truth parser — `tools/truth.py`

```
              files parsed      employee rows
Delhi            8 ->  80         51 -> 8057
HO              27 ->  46        433 -> 2328
Kolkata          0 ->   0          0 ->    0
TOTAL           35 -> 126        484 -> 10385   (x21.5)
```

Two claims were checked rather than assumed:

* **Is it inventing rows?** The 7x row-to-name ratio in the largest file is
  legitimate -- the same employees appear on ~7 sheets (different months), and
  identical (name, day-series) pairs are deduplicated.
* **Did it lose anything?** Two AFCON files "lost" rows against the legacy
  parser. Inspection showed the opposite: the new parser reads days 29-30 that
  the old one missed. More complete, not less.

**Kolkata yields nothing, and that is correct.** Its 30 Excel files are
invoice and payment trackers, not attendance grids. Kolkata's 658 PDFs can be
processed but cannot be scored without ground truth being created for them.

## What this unblocks

`tools/build_truth_index.py` parses everything once into
`data/truth_index.json`; `tools/eval_corpus.py` scores all three datasets
against it. Matching refuses to guess: when one name resolves to several
conflicting day-series, the page is recorded `ambiguous` and excluded, because
an honest denominator is worth more than a large one.

### D. Weekday annotation gate: 82 -> 72 — KEPT

Two real rows were annotated `'Swday.'` and `'Sudny'`. Both are single-letter
**deletions**, which score 72.7 against SUNDAY and so fell through the gate of
82 -- a clearly-marked weekly off reported as a worked day.

Swept rather than guessed:

```
thresh   68     70     72  |  74     76  |  78     80     82  |  84     86
day     825    825    825  | 819    819  | 820    820    820  | 816    816
```

68-72 is a **flat plateau**, not a spike, so 72 is not fitted to noise. Five
pages change -- four up, one down by a single day, net **+5** -- spread across
five different files rather than resting on one page.

### E. Snap a weekly off that landed one row off — KEPT

Comparing our weekly offs against the client's typed Excel showed the real
shape of the top two confusions. Truth always puts them on ONE weekday; ours
were usually right except for a single row-offset:

```
truth W: 5(Sun) 12(Sun) 19(Sun) 26(Sun)
ours  W: 5(Sun) 12(Sun) 19(Sun) 27(Mon)     one row late
ours  W: 5(Sun) 11(Sat) 19(Sun) 26(Sun)     one row early
```

The annotation is written across a row boundary and binds to the neighbour.
**Each misplacement costs two comparisons** -- a W->P on the true day and a
P->W on the neighbour -- which is exactly why those were the top two
confusions (21 and 15).

`reconcile()` section 0 moves it back. It fires only when the sheet's own
weekly offs agree on a weekday by a clear majority, so it never imposes an off
day the page does not already demonstrate, and it MOVES a weekly off rather
than creating one.

The first version was too eager -- it also moved weekly offs that were already
correct, and one page lost 4 comparisons:

```
without guard   5 pages changed, net +3   (one page -4)
with guard      2 pages changed, net +4   (no regressions)
```

The guard is the evidence condition: only move a W **off** a row that shows
work and **onto** a row that does not. That is the actual signature of a
misbound annotation.

```
SNAP_WEEKLY_OFF=False   day 825/903 = 91.36%   overall 0.8991
SNAP_WEEKLY_OFF=True    day 829/903 = 91.81%   overall 0.9032
```

### F. Period from path takes precedence — KEPT, measured NEUTRAL

OCR can return a month that is not merely unreadable but confidently wrong:
`VSPL APR 2026.pdf` resolved to **(2025, 3)** -- March 2025 for a sheet that is
plainly April 2026. A wrong period aims every weekday calculation at the wrong
days, and that page is the worst in the corpus at 58.1%.

`PERIOD_SOURCE_FIRST` prefers the path. It measured **no change**, because
that page states no weekly-off total and we find no weekly offs on it, so no
reconciliation fires regardless of the period. Kept because it removes a known
corruption mode; recorded as neutral so it is not mistaken for a win.

## The finding that mattered most: Sunday is NOT the off day

`reconcile.py` stated that Sunday "is the off day on every sheet in this
corpus" and fell back to it whenever a sheet showed no weekly off of its own.
Measured across all 10,385 ground-truth rows:

| weekday | rows | % weekly-off |
|---|---|---|
| Sunday | 7,530 | **27.8%** |
| Saturday | 8,842 | 6.0% |
| Mon-Fri | ~8,000 each | ~2% |

**Sunday is PRESENT 65% of the time.** The assumption held for the original
8-folder Delhi set and is false on the full corpus. Worse, the convention is
per client, not global:

```
ADANI02      Sun off  79-94%      strong convention
Thyssen02    Sun off  65-73%
HMEL19       Sun off     14%
SHELL02      Sun off    6-8%      no convention
SHELL04      Sat/Mon      3%      continuous site, works Sundays
AFCON08      none         0%
```

A "Sunday is weekly off" rule would have been wrong about two-thirds of the
time, and would invent weekly offs on days a SHELL employee actually worked.

The fallback is now behind `SUNDAY_DEFAULT_OFF`, with the `None` case properly
guarded so refusing the fallback means *do not fill* rather than matching every
row whose weekday is also `None`. Measured on the Delhi frozen set it is still
worth keeping (**820 vs 813 day comparisons**) -- that set is IOCL-heavy, where
Sunday genuinely is the off day. **It must be re-measured on the full corpus
before being trusted for SHELL-type clients**, and the switch exists so that
decision can be made from evidence.

Voting from the sheet's own confirmed weekly offs, which `reconcile` already
does, remains correct everywhere. Only the blind fallback is in question.

## Where the fast harness now stands

```
              baseline            now
matched         26                 30
day_status     710/787 = 90.2%   825/903 = 91.4%
employee_name   25/26            29/30  = 96.7%
designation     10/24 = 41.7%    10/28  = 35.7%
OVERALL        745/837 = 89.0%   864/961 = 89.9%
```

Designation is now the weakest field, but it is 28 of 961 comparisons (2.9%):
ten points there moves the total by 0.3. The grid is still where the accuracy
is.

## Standing caution

`tools/eval_fast.py` calls `aarvi_form.extract` directly, which **does** run
`reconcile`. It does not run the roster, the VLM, or vocabulary correction --
so it measures extraction plus reconciliation only. Compare fast-to-fast and
full-to-full, never across.
