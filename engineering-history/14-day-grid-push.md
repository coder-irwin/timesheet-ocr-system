# Stage 14 — The Day Grid Push: 78.8% → 87.3%

> Asked to take the day grid to 100%. This documents what actually moved it,
> what refused to move, and where the ceiling sits. The two big wins came, once
> again, from the printed form — this time from a boundary we had drawn in the
> wrong place ourselves.

---

## 1. Starting breakdown (787 comparisons, fast harness)

```
correct        633   80.4%
row_missing     83   10.5%   <- largest bucket
status_wrong    53    6.7%   (W->P 25, P->W 8, W->H 8)
status_empty    18    2.3%
```

## 2. The missing days were almost all the SAME days

Before proposing anything, one count settled the direction: *which* days were
missing?

```
leading (day 1, 2...)      6
trailing (day 29, 30, 31) 57   <-- 69% of all row_missing
middle                    20
```

Nearly every lost row was days 29–31. The grid was being cut off at the bottom
— systematically, on almost every page.

### The culprit was our own safety pad

`summary_band_start()` bounds the grid above the summary block — at the summary
label's top **minus two label-heights**. That pad is correct for its original
consumer (`extract_summary`, which uses it as a search floor and must not miss
a slightly-high label). As a *grid* bound it is two grid rows too high: on a
verified page, day 29's boxes sit at y 1136–1152 and the bound was 1147.

Sweeping the pad as the band bound:

| pad (label-heights) | day status |
|---|---:|
| 2.0 (existing) | 80.4% |
| 1.0 | 81.8% |
| 0.5 | 82.7% |
| **0.0** | **87.0%** |
| −0.3 | 87.2% |

`grid_bottom()` now returns the label's own top edge — the physically
meaningful boundary — and only the band path uses it. `extract_summary` keeps
its pad; that path is invoice-critical and was tuned as it is.

The +0.2 from cutting *into* the label was declined: rows containing summary
text is exactly the failure the bound exists to prevent.

**row_missing: 83 → 9.** The worst page in the corpus (19%) left the worst-five
list entirely.

## 3. The month became parseable on the pages that needed it most

`'Jaly 2026'` — the 19% page — parsed to nothing, so nothing downstream could
use the calendar. Fuzzy month rescue at ratio ≥ 75, measured against the
corpus's real labels:

```
recovers:  Apsil (80)  Jaly (75)  May2026 (100, after the year fix)
rejects:   Max (67)  Mgy (67)  yue (57)  NORMAL OVER TIME (67 vs NOVEMBER)
```

Two guards: the parsed (year, month) is used **internally only** — rewriting
`period_label` itself was measured and rejected in an earlier stage (it
destroyed two-month labels). And `'May2026'` needed a separate fix: the year
regex required a word boundary that a glued label doesn't have.

## 4. 'Sunday', as it is actually written

The W→P failures put the evidence on screen. Two spellings of "Sunday" recur
that no matcher covered:

| OCR read | What it is |
|---|---|
| `Suudoy`, `Sundoy` | the u/n confusion pair (67 vs SUNDAY, below threshold) |
| `bopuns`, `hopins` | **"Sunday" written upside-down across the row** — the 180° flip of S,U,N,D,A,Y reads as ~`HOPUNS`, and both real reads score 83 against it |

Both added to the annotation words. +0.4 points; the false-positive probes
(`08 HOURS`, `Ropurs`, `HOURS`) all still refuse.

## 5. When the sheet says two weekly offs and we found one

The remaining W→P rows carried *real times* — `8:00–13:00` on a Sunday — and
the client's own typed Excel still calls them WO. Their convention: the off-day
is an off-day regardless of ink in the time cells (often a neighbouring row's
bleed).

`reconcile.py` already filled *empty* rows from the stated W/O total. It now
also reconsiders **non-empty** rows on the off weekday when the total still
says we found too few — weakest-evidence-first, capped at the stated count,
every conversion marked `_inferred`.

This is the one place a read value is overwritten by an inference, so the trade
was measured in both directions: 9 W→P fixed, 3 P→W introduced, net +7. The cap
and the weekday test are what keep it from being a guess: both come from the
page itself.

## 6. Measured and rejected today

| Idea | Result | Why it failed |
|---|---|---|
| Lock ladder row-count to the month length | **76.6%** (−3.8) | The detected span often covers only part of the grid; forcing 31 rungs into a 28-row span misaligns every row. The span was the defect, not the count. |
| Extend ladder to the grid bounds blindly | **68.4%** (−11.8) | Pulled summary and header text into the grid as phantom rows. |
| Global day-shift from the W pattern | 89.2% (0.0) | The offsets on the broken pages are *partial* (+2 early, +1 later — spurious inserted rows), so no global shift fits, and the guard correctly never fired. |

The first two are the same lesson from opposite directions: the calendar is a
strong signal only when anchored to the right span. Right span + free count
beats wrong span + right count.

## 7. Where it stands

```
correct        702   89.2%
status_wrong    59    7.5%   (W->P 21, P->W 17, W->H 7)
status_empty    17    2.2%
row_missing      9    1.1%
```

| | Session start | Now |
|---|---:|---:|
| Day status (fast harness) | 80.4% | **89.2%** |
| Designation (with vocab) | — | 20/24, regression 18/18 |
| Employee name | 25/26 | 25/26 |

## 8. Confirmed on the full pipeline

The quotable numbers, from the 14-minute harness (49 pages, 1,090 comparisons
vs the client's typed Excel):

| | Before this stage | After |
|---|---:|---:|
| Day status | 78.8% | **87.3%** (895/1,025) |
| OVERALL | 79.2% | **87.2%** (950/1,090) |
| Pages read 100% perfectly | 0 | **11 of 34** |
| Median page | 86% | **93%** |

Seven of the ten staged demo pages now agree with the client's Excel on every
single day. The page that opened this stage at 19% ('Jaly 2026') finished at
97%.

One operational lesson from verifying this: the running server still had the
previous day's code in memory while the new code sat on disk — an upload made
at that moment would have silently used the old pipeline. The health endpoint
reports `pipeline`, and the launchers restart fresh; check the version, not
the feeling that it was restarted recently.

The remaining errors concentrate in three structurally-broken pages (58–65%),
each with *drifting* row offsets from spurious band insertions — per-region
alignment work, not a threshold. A workflow is running adversarial diagnosis on
exactly those pages plus an A/B/C recoverability audit of the residual against
the actual scans; its findings gate the next round.

On "100%": the honest framing hasn't changed. The residual includes rows whose
information never made it out of the OCR layer and handwriting a careful human
would squint at. The checksums — not the extraction — remain the guarantee the
demo stands on. Every page that still disagrees with its own stated totals gets
flagged, which is why the wrong rows above are *visible* rather than silent.
