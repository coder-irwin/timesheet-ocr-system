# Stage 11 — Reading Rows From the Form, Not From the Ink

> The day grid is 94% of everything this product is measured on. Three separate
> attempts to recover its rows from the handwriting all plateaued. This stage
> stops inferring where the rows are and reads the printed lines that say so.

---

## 1. The problem, as a number

From the harness (49 pages, scored against the client's own typed Excel):

| Field | Accuracy | Comparisons | Share |
|---|---:|---:|---:|
| Employee name | 97.1% | 34 | 3% |
| Designation | 48.4% | 31 | 3% |
| **Day status** | **56.4%** | **1,025** | **94%** |
| OVERALL | 57.4% | 1,090 | |

Day status *is* the product's accuracy. Nothing else moves the total.

---

## 2. Three failed row-finders, and what they had in common

| Attempt | Idea | Measured |
|---|---|---|
| `cluster_rows` | group boxes by vertical gap | merges rows when handwriting is tall — 12 clusters from a 29-row grid |
| `cluster_by_pitch` | assume a uniform pitch across the grid | better, but the pitch is estimated from the ink's extent |
| `split_merged_rows` | split a cluster holding two time-tokens | **60.2% → 57.3%. Reverted.** |

All three answer "where are the rows?" by looking at **where the writing is**.
Handwriting is precisely the unreliable part of the page. The printed rules are
not — they are the same on every sheet the client has ever sent.

`ocr_engine._lines()` already found them, by morphological opening with a long
thin kernel. They were used for whole-page grid detection and then dropped.
They were never wired into row extraction.

---

## 3. Measuring the rules before trusting them

The rules are not always usable, so the first step was counting, not coding
(`tools/probe_row_rules.py`, 12 pages):

```
page                     ocr_rows  rules_grid  med_gap  pitch_cv
DN16 APR 2026_p001.png         39          29     23.0     0.021
Bhanu prakash_p001.png         42          37     21.0     0.428
CLMS APR 2026_p001.png         27           9     33.0     1.059
CLMS APR 2026_p003.png         32           0     None      None
CLMS APR 2026_p007.png         37          30     24.0     0.029
```

Two findings, one of which overturned the working diagnosis:

**a. The rules are clean on many pages and absent on others.** `pitch_cv` (the
coefficient of variation of the gaps between rules) separates them sharply:
0.02–0.21 where a real grid was found, 0.4–1.06 where long runs of handwriting
were mistaken for rules. That gives a usable accept/reject test rather than a
hope.

**b. The row finder was producing TOO MANY rows, not too few.** 39 and 42 rows
on 30-day grids. The failure had been filed as `row_missing`, which pointed at
recovery; the actual defect was **over-segmentation**, which points somewhere
else entirely. And it explains a downstream symptom: `infer_days_by_position`
only trusts row order when 27 ≤ n ≤ 32, so an over-segmented page falls back to
reading the handwritten dates — the least reliable signal on the sheet.

---

## 4. What was built

```python
def rule_bands(rules, header_y, footer_y, max_cv=0.30, min_rules=20):
    """Row boundaries from the PRINTED rules. None when untrustworthy."""
```

Guards, in order: only rules inside the grid band; collapse hairline duplicates
(a thick rule detects twice); require ≥20 rules; require pitch CV ≤ 0.30.
Anything that fails a guard is handed back to the ink clusterer unchanged — the
noisy and rule-less pages are not made worse.

The bands buy two things clustering cannot:

1. **Two rows whose ink merged still occupy two bands.**
2. **A blank row still occupies a band.** This is the one that matters most. A
   dropped blank row shifts every later day up by one, silently, and the result
   still validates — the failure mode with no visible symptom.

`rows_from_bands()` therefore emits *every* band including the empty ones, and
`extract_day_rows` keeps them as placeholders instead of filtering them out.

One asymmetry is deliberate. Bounding the grid below by `summary_band_start()`
was measured on the ink path and **hurt** (51.5% → 50.4%), so it was left off.
The rule path *needs* it, because the printed rules continue into the summary
block. The bound is applied only where the bands are used.

---

## 5. A single-page "win" that turned out to be a different change

Page 11 (Vikram Prasad Sethi, IOCL May 2026) looked like a spectacular
confirmation:

```
BEFORE   rows=30  distinct days=10  duplicates=20
   [1, 5, 5, 4, 5, 5, 5, 5, 9, 5, 5, 12, 13, 14, 5, 5, ...]

AFTER    rows=30  distinct days=30  duplicates=0
   [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, ...]
```

Twenty of that page's 24 blocking issues were `day_duplicate`, so this also
looked like a fix for the review queue — when every page carries 24 blockers,
"only flagged pages need review" stops meaning anything.

**It was not the rule bands.** Instrumenting the page afterwards:

```
page_h 1600  header_y 465  footer_y 1147  rules 22
in-band 13   [488, 535, 556, 603, 670, 693, 715, 737, 759, 805, 826, 848, 893]
cv 0.447  ->  rule_bands returned None
```

Thirteen rules for a thirty-row grid, irregularly spaced. The bands were
**rejected** on this page. What actually fixed it was a side effect of the
first implementation: it passed the summary-block lower bound to
`extract_day_rows` whenever *any* rule was detected, so the **ink** path
silently gained a footer bound — the very change previously measured as
harmful (51.5% → 50.4%).

The same slip broke another page in the opposite direction: page 14, whose 8
rules were also rejected, collapsed from 30 day rows to **1**, because the
footer bound alone cut its grid.

Two lessons, both already in the research skill and both nearly skipped here:

- **A single page cannot attribute a cause.** The change and the improvement
  were real; the causal link between them was invented.
- **A previously-rejected change can come back disguised as a side effect.**
  The footer bound re-entered the ink path unnoticed, inside a commit about
  something else.

The bands are now computed in `_extract_inner` and passed down explicitly, so
the footer bound cannot apply unless the bands were actually accepted.

---

## 6. Making the measurement cheap enough to be honest

The reason the attribution error survived as long as it did is that checking it
properly cost 20 minutes. OCR is ~95% of that runtime, and OCR output does not
change when extraction logic changes.

`tools/eval_fast.py` freezes the OCR layer once — boxes, page size, detected
rules, matched ground-truth row — into a pickle, then replays extraction
against it. Same score, seconds instead of minutes:

```
python tools/eval_fast.py --freeze   # once, after an OCR-level change
python tools/eval_fast.py            # every experiment after that
```

It deliberately does not cover preprocessing, the OCR engine, or the VLM
fallback: those change the frozen inputs, so a final quotable number still
comes from `eval_100.py`. The fast harness is for choosing between hypotheses;
the slow one is for reporting.

---

## 7. Cache invalidation

`PIPELINE_VERSION` moved `v3-ocr-typed` → `v4-rule-bands`. The version is part
of the cache filename, so every prior result is invalidated without deleting
anything: a rollback re-uses the v3 entries instantly rather than re-reading
3,000 pages.
