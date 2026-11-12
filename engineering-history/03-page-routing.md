# Stage 3 — Page Routing

> How the system decides what to do with each page, why two earlier designs
> failed, and the measurements behind the one we shipped.

---

## 1. Why routing exists at all

Not every page is equally hard. In this corpus a page can be any of:

| Kind | What it is | Cost to read | Accuracy |
|---|---|---|---|
| Born-digital PDF | The PDF already contains the text as text | ~0 ms | 100% by construction |
| Printed form, typed values | A scan of a form filled in on a computer | ~5 seconds | Very high |
| Printed form, handwritten values | A scan of a form filled in by pen | 2–5 minutes | The hard case |

Those differ by roughly **1,000×** in cost. If we sent every page down the
slowest path, 2,527 pages a month would need 100–250 hours of compute on the
target laptop. If we route correctly, most of that disappears.

Routing wrong is costly in both directions:

- **Handwritten page → fast path** = silently wrong numbers on an invoice.
- **Typed page → slow path** = minutes of CPU burnt for nothing.

### Terms used here

| Term | Plain meaning |
|---|---|
| **OCR** | Optical Character Recognition — turning a picture of text into an actual string of characters. |
| **Text layer** | Many PDFs store real text alongside the visual page. If present, you can read it perfectly without OCR. A scanned page has no text layer — it's just a photo. |
| **VLM** | Vision-Language Model — an AI model that looks at an image and writes text about it. Powerful, slow, and it can invent things. |
| **Confidence score** | A number from 0 to 1 that an OCR engine attaches to each thing it reads, meaning roughly "how sure am I that I read this correctly". |
| **Percentile (p25)** | If you sort all the confidence scores, p25 is the value 25% of the way up. It describes the *weakest quarter* of readings, which is where errors live. Averages hide that; percentiles don't. |
| **ONNX / ONNX Runtime** | An open file format for AI models, and the engine that runs them. It runs on an ordinary CPU, which is why we need no graphics card. |
| **Connected component** | A blob of touching pixels. Used to find individual letters or lines on a page. |
| **Stroke width** | How thick the pen or print strokes are. |
| **Coefficient of variation (CV)** | Standard deviation ÷ mean. A unit-free measure of "how much does this vary relative to its typical size". |

---

## 2. Attempt 1 — stroke-width statistics (FAILED)

**The idea.** Printed characters come from one font at one weight, so their
stroke width is nearly constant. Handwriting varies with pen pressure and
speed. So: measure stroke width across all ink pixels and look at its
coefficient of variation. High variation ⇒ handwriting.

**How stroke width was measured.** A *distance transform* labels every ink
pixel with its distance to the nearest non-ink pixel. In the middle of a
stroke that distance is about half the stroke's thickness. Collect those
values across the page and you have a stroke-width distribution for free —
no model, milliseconds of CPU.

**The result on 708 PDFs:**

```
printed       389 files (55%)   1,907 pages (75%)
handwritten   229 files (32%)     414 pages (16%)
digital        90 files (13%)     206 pages ( 8%)
```

**Why it failed.** Visual inspection of `SAMS01` — 70 files the classifier
called handwritten — showed a **fully typed, system-generated Samsung
timesheet**. The page also contains:

- a passport photo of the employee,
- solid dark-blue filled table header bands,
- a column of ~30 small scanned signature images.

None of that is text, and all of it has wildly varying "stroke width". A small
contaminating minority of pixels dominated a whole-page statistic. **145 files
were mislabelled**, which would have sent ~145 typed pages down the 2–5 minute
path for no reason.

> **Lesson.** A statistic computed over a whole page is only as good as the
> assumption that the page contains one kind of thing. These pages don't.

---

## 3. Attempt 2 — trimmed statistics + a second feature (STILL FAILED)

**The fixes tried.**

1. **Trim the distribution** to the 10th–90th percentile of stroke widths, so a
   minority of odd strokes (signatures, stamps, logos) can't dominate.
2. **Add an independent second feature** — the variation in *text-line height*.
   Typed rows sit on a strict grid with near-identical heights; handwritten
   rows wander. Require *both* features to agree before calling a page
   handwritten, on the theory that two features which fail differently are
   harder to fool than one.

**Validated against 5 hand-labelled pages** (every one actually looked at):

```
file                    label        pred          sw_cv  lh_cv   result
IOCL30                  handwritten  handwritten   0.943  0.325   OK
ADANI02                 printed      printed       0.000  0.107   OK
SAMS01                  printed      handwritten   0.926  0.981   WRONG
KBR02                   digital      printed       0.000  0.124   WRONG
SAFEARTH01              printed      printed       0.000  0.069   OK
                                                          3/5 correct
```

**Two different lessons from the two failures.**

- **KBR02 was my labelling error, not a model error.** I labelled it "digital"
  because the rendered page looked razor-sharp. But its extracted text length
  is **0** — there is no text layer. Sharp ≠ digital. The classifier's
  "printed" was correct. *Always check the machine-readable fact rather than
  trusting how something looks.*

- **SAMS01 failed for the same root cause as v1.** Trimming removed a few
  outlier pixels but not an entire employee photo and solid colour bands.

### The deeper problem

Both attempts asked: *"is this page printed or handwritten?"*

Looking at the actual pages, that question is **malformed**. Nearly every page
here is a **printed form containing filled-in values**:

- `IOCL30` — printed AARVI form, **handwritten** values
- `ADANI02` — the **same printed AARVI form**, **typed** values

The form's printed rules, labels and logo are identical in both. Only the
*filled cells* differ. Classifying "the page" measures mostly the form, which
is the part that carries no information about difficulty.

---

## 4. Attempt 3 — OCR confidence (SHIPPED)

**The idea.** Stop predicting whether we *will* be able to read the page.
Just try to read it with a fast engine, and look at how confident that engine
was. The engine's own uncertainty is a far better signal than any pixel proxy,
because it measures the thing we actually care about.

**Engine chosen: RapidOCR** (`rapidocr` 3.9.2 + `onnxruntime` 1.28.0).

| Why | Detail |
|---|---|
| Accuracy | Ships PaddleOCR's **PP-OCRv6** models (June 2026) — the strongest open general OCR family available. |
| No heavy framework | Runs the models via ONNX Runtime. **No PaddlePaddle install**, which is the usual source of Windows pain. |
| CPU-native | No GPU needed. Measured 2.6–7.9 s/page on CPU. |
| Small | Models are a few tens of MB, fine for a 512 GB laptop. |
| Installed cleanly | Verified on Python 3.14 with zero build errors. |

### The measurement

Confidence statistics per page, on the hand-labelled samples:

| Sample | Values | Sec | Boxes | Mean | Median | **p25** | **% < 0.8** |
|---|---|---:|---:|---:|---:|---:|---:|
| IOCL30 | **handwritten** | 7.1 | 221 | 0.869 | 0.924 | **0.777** | **29%** |
| ADANI02 | typed | 5.4 | 188 | 0.965 | 1.000 | 0.999 | 9% |
| SAMS01 | typed | 7.9 | 292 | 0.976 | 0.999 | 0.995 | 5% |
| KBR02 | typed | 2.6 | 78 | 0.987 | 1.000 | 0.997 | 3% |
| SAFEARTH01 | typed, warped scan | 6.3 | 226 | 0.969 | 1.000 | 0.993 | 7% |
| GRSE01 | (unlabelled) | 4.8 | 174 | 0.993 | 1.000 | 1.000 | 1% |
| NUBE02 | (unlabelled) | 4.5 | 161 | 0.982 | 1.000 | 0.999 | 3% |
| FPEP01 | (unlabelled) | 6.0 | 223 | 0.979 | 0.999 | 0.993 | 4% |

**The separation is clean and has no overlap:**

- Handwritten p25 = **0.777**; every typed page ≥ **0.993**.
- Handwritten has **29%** of boxes below 0.8; typed pages 1–9%.

That is a gap of more than 0.2 in p25 with nothing in between — far wider and
far more stable than anything the pixel statistics produced.

**Note why the mean is the wrong statistic.** IOCL30's *mean* confidence is
0.869, which doesn't look alarming next to 0.965. The **p25** tells the real
story (0.777 vs 0.999) because errors concentrate in the weakest readings.
Averages hide exactly the tail you care about.

### Why this is the right design, not just a working one

1. **Self-calibrating.** No per-client pixel thresholds to retune when a new
   client sends a differently-shaped form.
2. **Task-aligned.** It measures "can we read this?", which is the actual
   question, instead of a proxy for it.
3. **Degrades per-region, not per-page.** Confidence is attached to each
   detected text box, so we can escalate *only the low-confidence boxes* to the
   slow model instead of the whole page. A printed form with three handwritten
   cells costs three small model calls, not a full-page one.
4. **No page can fall through.** Anything the OCR can't read confidently is
   escalated; anything the model can't read confidently is flagged for review.
   There is no silent-failure path.

---

## 5. The shipped routing rule

```
for each page:
    if the PDF has a usable text layer (avg extracted chars > 400):
        route = DIGITAL      -> parse text directly, no model, 100% accurate
    else:
        run RapidOCR (~5 s)
        if p25(confidence) >= 0.90 and (% boxes < 0.8) <= 15%:
            route = PRINTED  -> accept OCR output
        else:
            route = MIXED    -> keep the confident boxes,
                                escalate only low-confidence regions to the VLM
```

Thresholds (`p25 >= 0.90`, `≤15%` weak boxes) sit in the wide empty gap between
the measured handwritten and typed clusters, not on the edge of either — so
normal variation cannot flip a page across the boundary.

### Expected production cost

| Route | Pages/mo (est.) | Unit cost | Total |
|---|---:|---|---|
| Digital | ~206 | ~0 | negligible |
| Printed | ~1,907 | ~5 s | ~2.6 h |
| Escalated regions | ~414 pages, partial | seconds–minutes | ~5–20 h |

**Roughly 8–23 machine-hours per month**, against 100–250 hours for a
naive "VLM on everything" design. That is what makes a 16 GB CPU-only laptop a
viable production machine rather than a demo toy.

---

## 6. What still needs verifying

- The `p25 ≥ 0.90` threshold rests on **5 hand-labelled pages**. It should be
  re-validated once more pages are labelled; the gap is wide, but the sample is
  small.
- `SAMS01`/`SAMS03` (145 files) are typed and were mislabelled by v1 — the
  corpus route counts in §2 are therefore **wrong** and must be regenerated
  with the confidence-based router before being quoted to the client.
