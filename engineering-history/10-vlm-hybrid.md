# Stage 10 — The VLM, Reconsidered

> A model that was measured, rejected, and then re-measured doing a different
> job — where it turned out to be the largest single accuracy gain of the
> project. Also records the version of the same idea that failed.

---

## 1. The reversal

Earlier benchmarking ruled out vision models decisively:

| Engine | Handwritten | s/page |
|---|---:|---:|
| RapidOCR | 50% | 5.7 |
| Qwen3-VL 4B | 30% | **563** |
| glm-ocr | 0% | 66 |

Conclusion at the time: *"the VLM is ~100× slower and less accurate — it is an
escalation path, never the default extractor."*

That measurement was correct. It was also **measuring the wrong job**.

Whole-page transcription is a VLM's worst case — a large image to encode and
thousands of output tokens, where any drift compounds. The header block is the
opposite: a small crop, four fields, ~40 tokens of answer.

Same model, same pages, cropped instead of whole-page:

| Job | Accuracy | Cost |
|---|---:|---:|
| Whole page | 30% | 563 s |
| **Header crop** | **67%** | **24 s** |

**2.2× the accuracy at 4% of the cost.** The model was never the problem; the
task framing was.

---

## 2. Why it pairs so well with the roster

The VLM's residual errors are near-misses, not nonsense:

```
'JACODISH SINGH'   for   RAJEEV IYENGAR
'NURAI SPANOOQ'    for   Pradeep Chauhan
'54388'            for   54788
```

Those are exactly what a 96%-accurate roster match resolves. **VLM for reading,
roster for resolving** — each covers the other's weakness. Neither alone would
have produced the result below.

---

## 3. When it runs

At ~24 s it is far too expensive to run on every page. It fires only when the
cheap path has clearly failed:

```python
def header_needs_help(record):
    name = record.get("employee_name")
    if not name:                    return True   # nothing extracted
    if not _NAME_LIKE.match(name):  return True   # contains digits etc.
    return score_month(name) > 0.7                # "name" is really a month
```

That last case is the classic header-shift failure, where the extractor returns
`'APRIL-2026'` as the employee name.

Because it is gated, measured throughput stayed at **8.2 s/page** overall.

---

## 4. Measured result

Full harness, 49 pages, scored against the client's own typed Excel:

| Metric | Before | With VLM fallback |
|---|---:|---:|
| Pages matched to Excel | 57% | **69%** |
| Employee name | 96.4% | **97.1%** |
| Day status | 53.8% | **56.0%** |
| **OVERALL** | **55.1%** | **57.1%** |
| Comparisons | 899 | **1,090** |

The comparison count rising from 899 to 1,090 is itself the point: more pages
became matchable, so more of the corpus is now measurable at all.

---

## 5. The same idea applied to the day grid — REJECTED

Day status is 94% of all comparisons, so the obvious next step was to crop the
grid and ask the VLM for a day→status map. It was built, run, and rejected.

**What came back** (three pages, ~47 s each):

```
026_p001.png  days_returned=31  range 1..31  [(1,'P'),(2,'P'),(3,'P'),(4,'P'),...]
026_p002.png  days_returned=30  range 1..30  [(1,'P'),(2,'P'),(3,'P'),(4,'P'),...]
026_p003.png  days_returned=31  range 1..31  [(1,'P'),(2,'P'),(3,'P'),(4,'P'),...]
```

Structurally flawless — a complete, correctly-numbered series. **And wrong.**
Every one of those pages has four Sundays clearly marked as weekly-off. The
model returned `P` for all 31 days.

It was not reading the grid. It was generating a plausible attendance pattern.

> **This is the most dangerous failure mode in the whole system.** Missing data
> is visible and gets flagged. Fabricated data that is well-formed, complete and
> plausible sails through validation — the row-sum checksum would even *pass*
> on a uniform-P page whose stated total happened to match.

**Why it fails here but works on the header:** four values versus thirty. Short
structured output stays grounded in the image; long output drifts into the
model's prior about what a timesheet looks like. The boundary is output length,
not image content.

**Rule adopted:** use a VLM only where the expected answer is **short and
verifiable**. Never for bulk tabular data.

---

## 6. What this changes about the architecture

The original plan proposed *"Extraction → VLM with per-template JSON schema"* as
the primary extractor. The evidence now supports a more specific position:

- **Whole-page VLM extraction: no.** 563 s/page and 30% on handwriting.
- **VLM for bulk grid data: actively unsafe.** It fabricates convincingly.
- **VLM for small, failed, verifiable regions: yes, and it is the single
  biggest gain measured** (+12 points of page-match rate, +2 points overall).

OCR remains the workhorse; the VLM is a targeted repair tool.

---

## 7. Honest limits

- The header-crop result rests on **3 hand-verified pages** (67%). The
  end-to-end gain on 49 pages is solid, but the isolated figure is a small
  sample.
- It requires a local Ollama with `qwen3-vl:4b` (~3.3 GB). If absent, the
  pipeline skips it silently and falls back to OCR alone — no page is lost, but
  accuracy returns to 55.1%.
- ~24 s per triggered page means a batch with many failed headers runs slower.
  With 4 workers this still sits inside the 3,000-pages-per-day budget, but it
  is the component most likely to breach it on a bad batch.
