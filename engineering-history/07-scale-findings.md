# Stage 7 — What Happens at Scale

> The five hand-labelled pages said 78.8%. Running hundreds of real pages says
> something quite different, and more useful. This is the most important
> document in the set.

---

## 1. The headline

**The extractor handles one template family. The corpus contains many.**

Measured over 25 pages sampled round-robin across clients:

| Summary label | Not found at all | Found but blank on form | Successfully read |
|---|---:|---:|---:|
| `Total Man Hours` | **56%** | 16% | 28% |
| `P (Total Present Days)` | **56%** | 4% | 40% |

The dominant failure is **56% "label not found"** — and that is not an OCR
failure and not a blank form. Those pages simply are not the AARVI ENCON layout
the anchors were written for. They are Samsung sheets, KBR weekly sheets, and
other client-specific formats.

**On the pages that ARE the AARVI form, extraction is good:**

| Field | Read successfully | Genuinely blank on the form |
|---|---:|---:|
| `Present Days` | **91%** | 9% |
| `Man Hours` | **64%** | 36% |

That reframes everything. The system is not 78.8%-accurate-everywhere; it is
**good on the template it knows and blind on the ones it doesn't.**

---

## 2. Why the row-sum checksum almost never closes

The checksum is the foundation of the product's core claim. At scale it
completes on **2% of pages**. The breakdown (40 pages):

| Outcome | Share |
|---|---:|
| Summary total not available → checksum cannot run | **75%** |
| Total available, but row sum ≠ stated total | **22%** |
| **Balanced** | **2%** |

Two independent problems, and they need different fixes:

**(a) 75% — the total isn't available.** Mostly template coverage (§1), plus a
real minority (16% of AARVI pages) where the client **left `Total Man Hours`
blank on the paper**. `ADANI02 / ADN901 APR 2026` is a confirmed example: the
field is empty on the form.

> **Business consequence worth telling the client:** you cannot validate against
> a total that was never written down. On those pages the arithmetic guarantee
> is unavailable regardless of how good the OCR is. Either the form-filling
> discipline changes, or those pages get a weaker guarantee.

**(b) 22% — the total is there but the sums disagree.** Some of these are
genuine defects in the paperwork (we found one where a human had scrawled
`25+3+2 = 30` trying to reconcile it). The rest are our day-grid hour extraction
being too noisy. These two cannot currently be separated, which is itself a
problem: a validator that cannot distinguish "their error" from "our error"
sends reviewers on wild-goose chases.

---

## 3. Self-consistency at scale (40 pages, all clients)

| Check | Result |
|---|---:|
| Employee name found | 52% |
| Employee code found | 40% |
| Summary block found | 45% |
| Day grid recovered (≥10 rows) | 60% |
| Row-sum checksum applicable | 25% |
| **Row-sum balanced** | **2%** |
| Day-count balanced | 78% |
| **Pages flagged for review** | **100%** |

**Every page is currently flagged.** That is safe — nothing wrong escapes — but
it is not yet useful: a review queue containing 100% of pages is the same
workload the client already has, which is precisely the failure Utsav named.

The day-count check (78% balanced) is the one that already works well, because
it depends on counting rows rather than reading hour values accurately.

---

## 4. Ground truth vs the client's own Excel

25 pages evaluated against the human-typed spreadsheets:

| | |
|---|---:|
| Pages processed | 25 |
| **Matched to an Excel row** | **6 (24%)** |
| Unmatched | 19 (76%) |
| Numeric fields compared | 6 |
| Correct | 1 (**16.7%**) |

**This measurement is currently inconclusive, and it would be wrong to quote
16.7% as an accuracy figure.** Only six field comparisons were possible, for two
compounding reasons:

1. **76% of pages could not be matched to a row**, mostly because name/code
   extraction fails on non-AARVI templates (§1).
2. **The client's Excel files mostly do not carry the totals columns** we map.
   Their spreadsheets are largely per-day status grids (`P`/`A`/`WO`), not
   totals — so there was almost nothing to compare even on matched pages.

Fixing (2) means comparing **per-day status** rather than totals — a better
comparison anyway, since it checks 30 values per page instead of 5.

---

## 5. What this changes about priorities

The previous priority list was wrong. Revised, in order:

| # | Work | Why |
|---|---|---|
| 1 | **Add extractors for the other template families** (Samsung, KBR, and the rest) | 56% of pages currently get nothing. This single item dominates every accuracy metric. |
| 2 | **Compare per-day status against the client's Excel** | Turns an inconclusive 6-field benchmark into a 30-values-per-page one |
| 3 | **Separate "their error" from "our error"** in checksum failures | A validator that can't tell these apart wastes reviewer time |
| 4 | 2-D anchor assignment | Fixes the handwritten header bleed; worth ~10 points on handwritten pages |
| 5 | Reduce the 100% flag rate | Only meaningful once 1–3 are done |

---

## 5a. Multi-template support — built, partially effective

`app/form_profiles.py` was added in response to §1: a registry of form layouts,
each declaring its own signature, header anchors, summary anchors and column
anchors. The extractor now detects the layout per page and swaps anchor sets.

**Detection works well.** Over 30 real pages:

| Profile | Share |
|---|---:|
| AARVI ENCON | 83% |
| Samsung E&A | 10% |
| KBR weekly | 7% |

**Extraction improved modestly, not dramatically:**

| Metric | Before profiles | With profiles |
|---|---:|---:|
| Employee name extracted | 52% | **57%** |
| Employee code extracted | 40% | **47%** |
| Any summary field found | 45% | **50%** |
| Day grid ≥10 rows | 60% | **63%** |
| Pages with ≥4 anchors found | — | 57% |
| Pages with **0** anchors found | — | 23% |

**Why the gain is smaller than the detection rate suggests.** Recognising a
Samsung page is not the same as reading it. The Samsung layout packs several
numbers into single cells (`30|21`, `0|0|4`), which needs the `split_fields`
logic declared in the profile but **not yet implemented**. So Samsung and KBR
pages are now correctly identified and their identity fields extract, but their
totals still do not.

That is the next piece of work, and it is small and well-defined.

---

## 6. Honest reassessment

**The 78.8% figure is real but narrow.** It was measured on five pages, three of
which are the AARVI form. On a representative sample the system reads the
template it knows well (91% on Present Days) and produces nothing on the 56% it
doesn't.

**The architecture is sound and the evidence for it is strong** — OCR beats VLMs
here by 100× on cost and wins on handwriting; the roster resolves names OCR
cannot read; the validation engine catches real defects in the client's
paperwork. None of that changes.

**What changed is the estimate of remaining work.** This is not "polish a
78.8% system to 90%". It is "the extractor covers one of several layouts, and
the others need building". That is well-understood, unblocked work — each new
template is a dict of anchors, not a research problem — but it is more than a
day.

> **Do not quote a single accuracy number to the client yet.** Quote the split:
> strong on the dominant AARVI form, not yet implemented for the others, with a
> measured plan for closing the gap.
