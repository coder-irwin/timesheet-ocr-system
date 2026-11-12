# Stage 9 — Real Accuracy, Measured at Scale

> The number to quote the client, how it was obtained, and the two fixes that
> moved it. Supersedes every earlier accuracy figure in these docs.

---

## 1. The headline

**49 pages · 837 field comparisons · scored against the client's own typed Excel**

| Field | Accuracy | Comparisons |
|---|---:|---:|
| Employee name | **96.2%** | 25 / 26 |
| Day-by-day status | **50.1%** | 394 / 787 |
| Designation | **20.8%** | 5 / 24 |
| **OVERALL** | **50.7%** | 424 / 837 |

Pages matched to an Excel row: **53%** (26 of 49).

### This replaces the earlier "82.1%"

Every prior figure came from **five hand-labelled pages** using a generous
metric that asked "could this value be read anywhere on the page". The honest
number, scored field-by-field against real human-typed output, is **50.7%**.

**Quote 50.7%, not 82.1%.** The gap between them is the entire argument for
measuring at scale.

---

## 2. Why the client's own data is the right answer key

Alongside the scanned PDFs sit the spreadsheets a human typed from them:

```
S.No | Month | E.Code   | Employee Name       | Designation       | 1 | 2 | 3 | 4 | 5 ...
1    | 46082 | IOCLMS900 | Vikram Prasad Sethi | Safety Supervisor | P | P | P | P | WO ...
```

That gives **~33 checkable values per page** (identity, designation, and a
status for all 31 days) instead of the 6–8 a hand-labelled header provides.
It is also exactly the output format the client actually consumes, so scoring
against it measures the thing they will judge us on.

---

## 3. Progression

| Version | Overall | Day status |
|---|---:|---:|
| Baseline | 43.2% | 42.2% |
| + row recovery from position | 49.8% | 49.2% |
| + status-inference fix | **50.7%** | **50.1%** |

---

## 4. Fix 1 — recover day rows from position (+6.6 points)

**Diagnosis.** Instrumenting the failure gave an unambiguous split:

```
correct 50.7% · row_missing 35.1% · status_empty 9.0% · status_wrong 5.2%
```

The dominant problem was not misreading. It was **rows being dropped entirely**.

**Root cause.** Tracing the real code showed `extract_day_rows` correctly
returning **27 rows**, but only 14 day-numbers surviving. The reason:

```
cluster 1: ['021426@65', '01426@68', '8@226', '18:0@318', ...]
                 ^ two adjacent handwritten dates in ONE OCR box
```

Merged dates parse to the same number, so 27 good rows collapsed into 12
distinct days.

**Fix.** When ~a full month of rows is recovered, the grid is complete and
strictly sequential — so **row position is a better estimator of the day than
the handwritten date**.

**A false start worth recording.** The first version of this fix cross-checked
position against the parsed dates and fell back when they disagreed. Measured,
**that check never passed** — the dates are too unreliable to validate anything.
Removing the check is what made the fix work. Row-missing errors fell
35.1% → 19.4%; sample pages went from 12 → 27 and 20 → 28 rows recovered.

---

## 5. Fix 2 — status inference (+0.9 points)

**The bug.** The weekly-off / holiday patterns were unanchored regexes:

```python
_WEEKOFF_RE = re.compile(r"(SUNDAY|WEEK\s*OFF|W/?O|HOLIDAY|H\.?O)", re.I)
```

`H\.?O` matches **"HO" inside "HOURS"**. So any row reading `"08 HOURS"` was
classified as a holiday or weekly-off. `W/?O` matched "WO" inside "WORKING" the
same way. That produced the symmetric P→W / W→P confusion which was the largest
remaining status error.

**Fix.** Word-boundary anchoring, explicit precedence
(absent → holiday → comp-off → leave → weekly-off → present), plus a
`_positive_hours` check so a row reading `"0"` no longer counts as present.
Nine unit cases now pass, including `"08 HOURS"`.

**Honest note on impact.** This was expected to be worth more than +0.9. On the
diagnostic sample it moved correct 56.4% → 59.7%, but the confusions did not
disappear — `W→P` remains the top error at 8 occurrences. The regex was a real
bug, but it was not the whole story.

---

## 6. Where the remaining ~49% sits

Latest diagnostic (211 day comparisons):

| Cause | Share |
|---|---:|
| Correct | **59.7%** |
| Row missing | 19.4% |
| Status empty | 11.4% |
| Status wrong | 9.5% |

**Row missing (19.4%)** is now concentrated on pages where row extraction is
genuinely poor — e.g. one page recovers 16 rows of 29, falls below the
sequential-assignment threshold, and reverts to unreliable dates. Better row
recovery on those pages is the next lever.

**A known limitation of the positional fix:** if a row is missed *in the middle*
of the grid, every subsequent day shifts by one. On the pages measured the
missing rows were at the end (28, 29, 30), so alignment held — but this is a
real failure mode that would show up as a whole-page offset, and it is not yet
detected.

**Designation (20.8%)** is the worst field in the product and unchanged. It has
no vocabulary source in the client's data (no designation column exists in any
of their 289 spreadsheets), so the closed-set trick that took names to 96.2%
cannot be applied without a job-title list from the client.

**47% of pages are unmatched**, traceable to the header-shift problem: names
extracted as `'APRIL-2026'` or `'APRTL.2026 ViVEK KOMAR'`. The content-typing
module (`app/field_typing.py`) targets exactly this and is written but disabled;
it can now be evaluated properly against this harness.

---

## 7. What made the difference methodologically

1. **Score against the client's data, not our labels.** Five hand-labelled pages
   hid a data-destroying bug and sent six "improvements" the wrong way.
2. **Instrument before fixing.** The row-missing/status-empty/status-wrong split
   pointed straight at the real problem; every earlier guess had been wrong.
3. **Trace the actual code path.** "27 rows extracted, 14 days surviving" located
   the defect in one measurement, after several days-long detours.
4. **Record the false starts.** The date cross-check that never passed is more
   useful to the next person than the fix that replaced it.
