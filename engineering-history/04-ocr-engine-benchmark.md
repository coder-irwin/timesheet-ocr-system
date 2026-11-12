# Stage 4 — OCR Engine Benchmark

> Comparative measurement of every OCR engine that can realistically run on a
> 16 GB CPU-only Windows laptop, scored on the same pages with the same metric.

---

## 1. What is being compared, and why these candidates

| Engine | What it is | Why it's a candidate |
|---|---|---|
| **RapidOCR** | PaddleOCR's PP-OCRv6 models repackaged to run on ONNX Runtime | Strongest open general OCR family; no PaddlePaddle install (the usual Windows headache); pure CPU |
| **Tesseract 5** | The long-standing open-source OCR engine (Google) | The industry baseline everyone benchmarks against; tiny install |
| **EasyOCR** | PyTorch-based detector + recogniser | Very widely used; commonly cited as better than Tesseract on noisy input |
| **glm-ocr (1.1B)** | A small vision-language model specialised for OCR, run through Ollama | Tests whether a *purpose-built OCR VLM* beats classical OCR |
| **Qwen3-VL 4B** | General vision-language model | Tests whether a *general* VLM is worth its cost |

### Terms

| Term | Plain meaning |
|---|---|
| **Field recall** | Of the invoice-critical values that are genuinely on the page, what fraction did the engine manage to read? |
| **CER** | Character Error Rate — the usual OCR metric. Explicitly *not* used here; see §2. |
| **p25 confidence** | The 25th percentile of the engine's confidence scores — describes the weakest quarter of readings, where errors live. |
| **Box** | One detected region of text on the page. |
| **ONNX Runtime** | An engine that executes AI models on a plain CPU — no graphics card required. |

---

## 2. Why field recall, not Character Error Rate

CER is the standard metric and it is the wrong one for this product.

A page can score **99% CER and still be a total failure** if the 1% it got
wrong was `Total OT Hours`. Conversely an engine can mangle the employee's
designation with zero consequence — nobody invoices on a job title.

The client's financial exposure is concentrated in roughly a dozen numbers per
page. So the metric scores exactly those: *did the engine read the values that
end up on an invoice?*

### How the metric was made honest

The first version scored a hit if the ground-truth string appeared **anywhere**
in the output. That is far too generous for short numbers: on a page containing
200 numbers, `"25"` will appear by chance whether or not the engine read the
Present Days cell.

The shipped version requires **positional proximity** — a value of 3 characters
or fewer only counts as found if it appears **within 60 characters of its own
label** in the reading-order output. That is the difference between "the digits
25 exist on this page" and "the engine read 25 as the value of Present Days".

The effect of tightening it was large and worth recording:

| Engine | Recall (loose match) | Recall (proximity match) |
|---|---|---|
| RapidOCR, printed | 100% | 79% |
| RapidOCR, handwritten | 60% | 50% |

**The loose metric overstated performance by ~20 points.** Any benchmark you
read that does substring matching on short values is inflated the same way.

---

## 3. Results

Hardware note: measured on an **Apple M4 / 24 GB**. The production target is a
**16 GB CPU-only Windows laptop**, which is materially slower — treat all
timings as *optimistic*, roughly 1.5–3× faster than target hardware.

### Headline — all five engines

| Engine | Printed pages | Handwritten page | Mean s/page |
|---|---:|---:|---:|
| **RapidOCR (PP-OCRv6 / ONNX)** | **79%** | **50%** | **5.7** |
| glm-ocr 1.1B (VLM, via Ollama) | 74% | **0% — returned nothing** | 66.3 |
| Tesseract 5 | 70% | **0%** | **1.6** |
| EasyOCR | 63% | **0%** | 11.0 |
| Qwen3-VL 4B (VLM) | *see §3.1 — harness bug* | | 293.4 |

**RapidOCR is the only engine that reads any handwriting at all.** Every other
engine scored a flat 0% on the hand-filled page. That single column decides the
choice: 16% of this corpus is handwritten, and an engine that returns nothing on
those pages pushes all of them to manual entry.

Tesseract deserves a note: at **1.6 s/page** it is 3.5× faster than RapidOCR and
only 9 points behind on printed pages. If a future workload were *known* to be
all-printed, Tesseract would be the rational pick. It is not chosen here purely
because of the handwriting column.

### 3.1 A false result we nearly published — Qwen3-VL

The first run scored Qwen3-VL **0% on every page**, including `KBR02`, which
every other engine read at 100%. A uniform zero on the easiest page in the set
is not a plausible model failure, so it was investigated rather than reported.

**It was a bug in our harness, not the model.** Qwen3-VL is a *reasoning* model:
it emits an internal `thinking` stream before its answer. Inspecting the raw
Ollama response showed:

```
response:  len=0     ''
thinking:  len=5027  "Got it, let's look at the image... EMPLOYEE ID: 20000001,
                      EMPLOYEE NAME: SAWRABH RAJ SAWRABH RAJ..."
done_reason: 'length'
```

The model **read the page correctly** and then exhausted the entire token budget
inside its thinking channel, returning an empty answer. We were reading
`response` and scoring the emptiness.

Fixed by (a) requesting `think: False` and (b) raising `num_predict` from 4,096
to 16,384, with a fallback that scores the `thinking` text rather than record a
false zero.

> **Lesson worth keeping.** A benchmark result that is *implausibly* bad deserves
> the same scrutiny as one that is implausibly good. Publishing "Qwen3-VL cannot
> read timesheets" would have been flatly untrue, and the only thing that caught
> it was noticing that the easiest page in the set had failed.

**Independent of accuracy, Qwen3-VL 4B is disqualified on speed:** 185–458 s per
page (mean 293 s) on an M4. That is ~50× slower than RapidOCR before the target
laptop's slowdown factor is applied. At 2,527 pages/month it would need over 200
machine-hours for the OCR pass alone.

### Per page

**RapidOCR**

| Page | Kind | Sec | Boxes | Recall | Missed |
|---|---|---:|---:|---:|---|
| ADANI02 | printed | 5.5 | 188 | 91% | leaves |
| KBR02 | printed | 2.7 | 78 | 100% | — |
| SAFEARTH01 | printed, warped | 6.5 | 226 | 75% | present_days, leaves |
| SAMS01 | printed | 8.1 | 292 | 50% | the four totals |
| IOCL30 | **handwritten** | 6.3 | 221 | **50%** | name, code, designation, month, public_holiday |

**glm-ocr 1.1B**

| Page | Kind | Sec | Recall | Note |
|---|---|---:|---:|---|
| ADANI02 | printed | 76.1 | 82% | |
| KBR02 | printed | 53.1 | 100% | |
| SAFEARTH01 | printed, warped | 74.7 | 62% | |
| SAMS01 | printed | 79.0 | 50% | |
| IOCL30 | **handwritten** | 85.5 | **0%** | **returned nothing** |

---

## 4. What the numbers actually say

### 4.1 The VLM is not a general-purpose extractor here

glm-ocr is **12× slower** than RapidOCR (70.7 s vs 5.8 s per page) and **no more
accurate on printed pages** (74% vs 79%). On the one page where a VLM was
supposed to earn its cost — the handwritten sheet — it **returned nothing at
all**.

> **Decision: the VLM is an escalation path for specific low-confidence
> regions, never the default extractor.** Running a VLM over every page would
> cost ~12× the compute to produce slightly worse results.

This is the single most cost-relevant finding in the project. A naive
"just use a vision model" design would have been an order of magnitude more
expensive *and* less accurate.

### 4.2 Warping costs surprisingly little

`SAFEARTH01` is a phone-scanner capture with visible page curl. RapidOCR still
reached 75%. Geometric distortion is **not** the dominant error source —
handwriting is. This lowers the priority of a dewarping stage considerably;
that effort is better spent on the handwritten path.

### 4.3 What "handwritten 50%" actually means

On the handwritten IOCL30 page, RapidOCR missed:
`employee_name`, `employee_code`, `designation`, `month_year`, `public_holiday`.

Four of those five are **handwritten free text**, not numbers. The engine read
the numeric grid substantially better than it read the names.

That is a very convenient failure mode, because:

- **Handwritten names are recoverable without OCR.** They are drawn from a
  closed set of ~3,000 known employees, so fuzzy-matching a partial read against
  the master roster resolves them. This is why the roster is the single biggest
  accuracy lever in the system.
- **Numbers are what the checksums protect.** Present days, man-hours and OT all
  participate in arithmetic that must balance, so a misread there is *detectable*
  even when it isn't preventable.

### 4.4 A caveat on our own metric

`SAMS01`'s four totals were missed by **both** engines. Two engines failing
identically on one page usually indicts the measurement, not the engines: the
proximity label list almost certainly doesn't match how SAMS01 spells its
headers in reading order.

The engine-vs-engine comparison remains valid — the same metric was applied to
both — but **the absolute recall numbers understate real performance** on that
layout. To be re-checked with per-layout label lists.

---

## 5. Consequences for the architecture

1. **RapidOCR is the default extractor for every non-digital page.** ~6 s/page,
   CPU-only, no GPU, clean install.
2. **VLM escalation is per-region, not per-page**, and only for regions the OCR
   flagged as low-confidence.
3. **Dewarping is deprioritised** — measured impact is small relative to its cost.
4. **The employee roster is a first-class requirement**, not a nice-to-have. It
   is what recovers the field class that OCR most reliably fails on.

---

## 6. Still to measure

- Tesseract 5 and EasyOCR (installs in progress) — needed to complete the
  comparison table for publication.
- Qwen3-VL 4B — the general VLM, as an escalation candidate against glm-ocr.
- Per-layout label lists, to remove the SAMS01 measurement artefact.
- A larger labelled set: **5 pages is enough to make a decision, not enough to
  publish a benchmark.**

---

## 7. Addendum (demo day) — the handwriting claim re-verified at scale

The original head-to-head rested on ONE handwritten page. Before the client
demo the losing engines were re-run across **all 10 handwritten demo pages**
(302 day-status comparisons), and this time through the FULL production
extraction pipeline — same printed-rule bands, same column recovery, same
reconciliation, same truth (the client's own typed Excel). Only the OCR
engine differs, so this isolates exactly the engine's contribution:

| Engine | Day status (10 handwritten pages) | Names | s/page |
|---|---:|---:|---:|
| **RapidOCR (production)** | **302/302 = 100%** | 9/10 | ~3–6 |
| EasyOCR | 194/302 = 64.2% | 1/10 | ~6.5 |
| Tesseract 5 | 8/302 = 2.6% | 0/10 | ~0.6 |

Two honest findings the single-page benchmark could not show:

1. **Tesseract is effectively blind to this handwriting** (2.6%) — the
   original 0% was not a one-page fluke.
2. **EasyOCR is far better than its original 0% suggested** — the raw
   field-recall metric buried it, but the surrounding pipeline (printed
   rules, calendar, reconciliation) lifts even a weak engine to 64%. That is
   independent evidence that the architecture, not the engine, carries the
   product — and RapidOCR still leads it by 36 points at twice the speed.

The claim to make in front of a client is therefore: *"On 302 handwritten
day-cells from your own paperwork, the chosen engine read 100% through our
pipeline; the industry-default engine read 2.6%."*
