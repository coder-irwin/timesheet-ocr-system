# Stage 12 — The Column That Was Never Read, and the Page That Fixes Itself

> Found by looking at the screen. The review pane showed a completely empty
> TIME OUT column while the scan beside it had "6:00 PM" written thirty times.
> Three separate defects sat behind that, and the last of them turned into the
> largest single gain of the day.

---

## 1. Why a whole column was blank

`learn_columns()` learns each column's x-range from its printed header. On this
page OCR read the "TIME OUT" header as **`'TME UT'`**, which scores **42**
against the pattern — the threshold is 80. The column was therefore never
learned, and every `6:00 pm` in the grid fell into dead space between
`in_time` (ends x=355) and `normal_hours` (starts x=455). Thirty values,
present and correctly read by OCR, discarded on their way to a column.

Measured across the corpus: **`out_time` missing on 10% of pages, `in_time` on
6%.**

### The fix: the form's column order is not in doubt

The same argument as the row ladder. A header can be unreadable; the *order* of
the columns cannot change, because it is printed. If the neighbours either side
were found, the missing column is the gap between them.

```python
COLUMN_ORDER = ("date", "in_time", "out_time", "normal_hours",
                "ot_hours", "total_hours", "remarks")
```

Guarded so a genuinely absent column is not invented: the gap must be wide
enough to hold a value, and must be a plausible column width next to the ones
that *were* read (0.35× to 2.5× the median).

---

## 2. The cell that belonged to two columns

With the column restored, the values still landed wrong — every clock-in
appeared under TIME OUT. The cause was the assignment rule: *"the column
containing the box's centre."*

OCR routinely merges neighbouring cells when handwriting touches the rule
between them:

```
'9:00Am6:00pm'    x = 257..471
in_time  259..355        out_time  355..455
```

Its centre (364) sits inside `out_time`, so both values went there and TIME IN
emptied. Requiring a box's centre to land in one cell is the same class of
mistake as requiring a readable date.

Two changes:

- **Check for straddling first.** If a box overlaps two columns by more than a
  quarter of their width, split it before the centre rule is consulted.
- **Split on clock readings, not whitespace.** `'9:00Am6:00pm'` is one
  whitespace token. A time-aware pattern finds two, and each is placed by its
  own character offset interpolated across the box.

---

## 3. W/OFF and C/OFF were never recognised at all

Four rows on the page were marked `W/OFF` or `C/OFF` and all four were reported
as **worked days**. Not a fuzzy-matching near miss — a total gap:

| Written | Reaches status inference as | Recognised |
|---|---|---|
| `w110ff` | `'WFF'` after folding | ✗ |
| `C/OFF` | `'COFF'` | ✗ |
| `W/OFF` | `'WOFF'` | ✗ |

`_fuzzy_annotation` folds to letters and then rejects anything under five
characters. `_WEEKOFF_RE` looks for `\bWO\b`, which cannot match inside
`w110ff`. So the abbreviations the supervisors actually write were invisible,
while the spelled-out "SUNDAY" worked fine.

`_SHORT_OFF_RE` now absorbs the usual substitutions for the slash (OCR reads
the stroke as `1`, `l`, `|`, `-`, or drops it) and the `O`→`0` confusion. It is
checked *before* the hours inference, because these markers are usually written
into the hours column, so the row looks like it carries a value.

---

## 4. The row ladder, fitted against the calendar

Even with columns and statuses fixed, the day numbers came out
`1,2,6,4,5,8,7,8,26,10,…` — duplicated and out of order.

The bands were accepted at CV 0.249 with **34 rungs for a 30-row grid**. Dense
handwriting had produced spurious rules, carving real rows into slivers. 33
rows is outside the 27–32 window where positional numbering is trusted, so the
page fell back to reading the handwritten dates — the least reliable signal on
the sheet.

The earlier `regularise_rules()` could not help: it estimates pitch from the
*smallest* gaps, which is right when rules are **missing** and wrong when they
are **spurious**. Here the gaps ran `23,23,22,23,23,14,11,12,10,13,10,20,24…`
and it would have chosen a pitch of 13 against a true pitch of 23 — a 55-row
ladder for a 30-row grid.

**`fit_ladder()` uses the calendar instead of the noise.** A month grid holds
26–31 rows, so try every plausible row count, lay a uniform ladder across the
span, and keep the one the detections agree with best. Spurious rules fail to
align and are outvoted; missing rules cost nothing. And since a month cannot
have more than 31 day rows, a detection set implying more than that is never
used raw — either a ladder explains it or the page returns to ink clustering.

| | Day status |
|---|---:|
| bands, ladder only as a rescue | 73.4% |
| **ladder fitted first, month-capped** | **79.5%** |

Result on the page: **30 rows, days 1–30, all distinct.**

---

## 5. The page repairs itself

The last step reads no pixels at all (`app/reconcile.py`). It uses two things
the page already states:

**The summary block.** The supervisor writes the totals by hand: *"P (Total
Present Days) 26"*, *"W/O (Total Weekly Off) 02"*. Those are short and
anchored to printed labels, so they read far more reliably than thirty rows of
handwriting. If the grid yields one weekly off and the sheet says two, the grid
is wrong — and by exactly one.

**The calendar.** Weekly offs fall on the same weekday. Parsing `"April - 2026"`
gives every day number a weekday, and the Sundays are 5, 12, 19, 26 — which is
precisely where the weekly offs sit on the IOCL sheets.

Together: *"row 12 is a Sunday, the sheet states two weekly offs, we found one,
and row 12 is blank."* That is an answer, not a guess.

Three rules stop it inventing data:
- it only fills rows that are **completely empty** — never overwrites a read value
- it never exceeds the **stated count**
- everything it fills is marked `_inferred` with its reason, so the reviewer
  sees an inference as an inference

| | Day status |
|---|---:|
| without | 79.5% |
| **with self-reconciliation** | **80.4%** |

---

## 6. The day, measured

Fast harness (extraction only, 787 day comparisons):

| Step | Day status |
|---|---:|
| start of day | 52.9% |
| rule bands | 63.7% |
| + footer bound (bands only) | 64.8% |
| + ladder repair | 66.1% |
| + dedicated row-rule detector | 68.5% |
| + rule ceiling at 52 | 73.3% |
| + column inference & cell splitting | 73.4% |
| + month-capped ladder fitted first | 79.5% |
| **+ self-reconciliation** | **80.4%** |

Rejected on measurement: `full_header_bound` (−6.4), `_row_text` in
annotations (0.0), `split_merged_rows` (−2.9, from an earlier stage).

---

## 7. The pattern behind every gain today

Six changes, one idea: **read the printed form, not the handwriting.**

| Signal used | What it replaced |
|---|---|
| Printed row rules | clustering the ink |
| Fixed column order | requiring a readable header |
| Days in a month | trusting parsed dates |
| Weekday periodicity | guessing which blank rows are Sundays |
| The stated totals | accepting whatever the grid summed to |

The handwriting is the unreliable part of these pages. The pre-printed
structure, the calendar, and the totals the supervisor signed are not. Every
plateau this project hit was broken by asking what the *form* already knows.
