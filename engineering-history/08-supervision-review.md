# Stage 8 — Supervision Review

> A systematic audit: read the actual scans, compare against what the system
> produced, find the *patterns* rather than reacting to single pages, then fix.
> Includes throughput design for 3,000 pages/day.

---

## 1. Why this review was necessary

Every accuracy change up to this point had been measured against **five
hand-labelled pages**. That is enough to choose between engines, where the gaps
are huge, but far too small to know whether a fix *generalises*.

The symptom of that blind spot: **six** consecutive attempts to improve
handwritten header extraction all regressed when measured. Tuning against five
samples was producing changes that fit those five and broke others.

So: dump what the system produces across a full handwritten batch, read the
originals directly, and look for structure.

---

## 2. What the audit found

Ten handwritten IOCL pages, system output vs the actual scans:

| Page | Failure mode |
|---|---|
| p003 | `code` = `'Safity sulenvisor NeeraJ'` — designation **and** name in the code field |
| p004 | `code` = `'AUTHORIZED'` — a grid column header captured as a value |
| p005 | `name` = `'APRIL-2026'`, `desig` = `'RAJEEV IYENGAR'` — **every field shifted down one label** |
| p006 | `name` = `'APRTL.2026 ViVEK KOMAR'` — month merged into name |
| p008, p009 | same merge pattern |
| p007 | `name` and `code` both `None` |

**The pattern:** failures are concentrated almost entirely in the **header
block**. The summary block extracts well — `P`, `MH`, `OT`, `WO`, `PH` were
present on 9 of 10 pages.

That is a useful split: the invoice-critical numbers are largely working; the
identity fields are not.

---

## 3. Root cause, measured

Dumping OCR box coordinates for `p005` explains all of it:

```
label                 cy      value                cy     gap
MONTH & YEAR          231     APRIL-2026           257    +26
EMPLOYEE NAME         262     RAJEEV IYENGAR        292    +30
DESIGNATION           292     SAFETY SUPERVISOR    324    +32
```

Handwritten values sit **~28 px below their own label**, while the form's label
rows are only **~30 px apart**.

Therefore `APRIL-2026` (cy 257) is **5 px** from the *wrong* label
(`EMPLOYEE NAME`, cy 262) and **26 px** from its *own* (`MONTH & YEAR`, cy 231).

> **Every distance-based rule is guaranteed to fail on these pages.** Not
> mis-tuned — structurally wrong. Nearest, nearest-above, and 2-D cost all
> inherit the same offset. This finally explains why six attempts regressed.

---

## 4. A real bug found by supervision

While testing the ordinal approach, `SAFETY SUPERVISOR` never appeared in the
candidate list. Investigating:

```
'SAFETY SUPERVISOR'  ->  furniture = True   (score 81 vs the "SUPERVISOR" label)
```

The **form-furniture filter was discarding a legitimate designation value**
because it resembled a label. Threshold was 80; the value scored 81.

Impact: the designation was being silently destroyed on **most IOCL pages** —
and it never showed up in the 5-page metric because the one handwritten page in
that set failed for a different reason first.

**Fix, two parts:**

1. Removed the bare `"SUPERVISOR"` pattern. The real label is
   `"SUPERVISOR NAME"`; the bare word matches the *value* just as strongly.
2. Split the thresholds. Finding a label needs ≥ 80. **Discarding a box as
   furniture now needs ≥ 92.** A near-miss should be treated as a value; only a
   near-exact label match is furniture.

```python
MATCH_THRESHOLD     = 80   # to FIND a label
FURNITURE_THRESHOLD = 92   # higher bar to DISCARD a box as a label
```

> **Lesson.** Asymmetric costs deserve asymmetric thresholds. Wrongly *finding*
> a label is recoverable; wrongly *discarding* a value is silent data loss.
> They should never have shared one number.

---

## 5. Ordinal matching — closer, still not shipped

The right idea for a uniformly shifted block: match by **sequence position**
rather than distance, since a uniform shift changes every distance but changes
no ordering.

**v1** failed (82.1% → 79.5%): its value-column detection pulled in grid
headers, so `employee_code` was assigned `'NORMAL'`.

**v2** derives the value column from the page's own geometry — bounded left by
where the labels end, right by where the next label column begins:

```
p005:  labels x~107-220 · values x~279-500 · next column x~519
       -> value window (240, 711)
```

On `p005` it then produced:

```
month_year     APRIL-2026        CORRECT
employee_name  RAJEEV IYENGAR     CORRECT
designation    50700             wrong (should be SAFETY SUPERVISOR)
employee_code  TIME IN NORMAL…   wrong
```

Two of four correct — and the two failures were **caused by the furniture bug
above**, which was removing `SAFETY SUPERVISOR` from the candidate list and
letting grid text slide into its place.

**Status: not shipped.** The furniture fix landed after this test, so v2 should
be re-tested now that its inputs are correct. It remains the most promising
route for the handwritten header block. The module is in
`app/ordinal_match.py`, unused.

---

## 6. Throughput design — 3,000 pages/day

A hard requirement, so it was measured rather than estimated. Same pages, cache
cleared between runs, no other load:

| Workers | s/page | 3,000 pages |
|---|---:|---:|
| 1 | 19.71 | **16.4 h** |
| **4** | **3.18** | **2.7 h** |

**6.2× speedup** — better than linear, because the single-worker run also paid
model-load cost.

### Why four

The ceiling is **RAM, not CPU**. Each worker holds an OCR session plus a decoded
page, peaking around 250–400 MB. On the 16 GB target with Windows taking 3–4 GB,
four workers is the safe maximum, and leaving two cores free keeps the machine
usable while a batch runs.

```python
WORKERS = max(1, min(4, cpu_count() - 2))   # override with TS_WORKERS
```

### Headroom on the target machine

The 16 GB Windows laptop is 1.5–3× slower than the M4 these numbers came from,
giving **4–8 hours for 3,000 pages**. The requirement is met with margin, and
OCR (not the model) is the bottleneck — so it scales with cores if a bigger
machine is ever used.

**Also note:** the content-addressed cache means a re-run costs ~1 ms/page. The
3,000/day figure is worst-case, all-new-pages throughput.

---

## 7. Current accuracy

| | Value |
|---|---:|
| Overall | **82.1%** |
| Printed | **86%** |
| Handwritten | **70%** |

Handwritten is up from 40% at the start, but has been stuck at 70% across six
attempted improvements. §3 explains why: the remaining failures are structural,
not tuning.

---

## 8. What supervision changed about the approach

1. **Stop tuning against five pages.** They cannot tell you whether a fix
   generalises, and they hid a bug that was destroying data on most pages.
2. **Read the originals.** The `p005` coordinate dump explained six failed
   attempts in one measurement. No amount of parameter search would have.
3. **Look for structure, not incidents.** "Values sit 28 px low while rows are
   30 px apart" is actionable; "this page got the name wrong" is not.
4. **Asymmetric risks need asymmetric thresholds** (§4).

### Next, in order

1. **Re-test ordinal v2** now that the furniture bug is fixed — its two failures
   were caused by that bug.
2. **Expand ground truth to ~30 pages** by reading them directly. Everything
   above argues that five is not enough to measure against.
3. Fix the `days` count (currently 8–29 rows recovered where ~30 is expected).
