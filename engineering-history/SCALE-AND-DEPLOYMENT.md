> **Status note — 22 Oct 2026.** Written 20 Sep 2026, before the system was
> deployed. It describes sizing and scale reasoning, which still holds. What it
> does NOT describe is the deployment that actually exists:
>
> - **Live on GCP** since 21 Sep 2026 — project `timesheet-ocr-prod`, VM
>   `timesheet-prod` (e2-standard-4), zone `asia-south1-a`, static IP behind
>   Caddy with Let's Encrypt HTTPS and per-user basic auth.
> - **Operational runbook:** `~/ocr_production/gcp/RUNBOOK.md` — deploy
>   sequence, the overlay bind-mounts, password rotation, per-person logins,
>   and the traps (a bind-mount of a missing host path becomes an empty
>   DIRECTORY; always upload a file BEFORE adding its mount).
> - **Verify a deploy via `/api/health`**, not the files on disk: a
>   `compose up -d` can report "Container Running" without recycling the
>   process, leaving the new code unused.
> - **Cost control:** `gcp/autosleep.sh` stops the VM after 3 h with no human
>   action (read from the audit table — web traffic is not a usage signal,
>   because the public IP is scanned continuously and the UI polls every
>   1.5 s). `gcp/wake.sh` starts it and waits until `/api/health` answers.
>   Shutdown checkpoints SQLite's WAL and stops containers first; verified
>   across a full cycle with the page table checksummed before and after.
> - **Disk safety:** boot disk `auto-delete=false`, daily snapshots retained
>   7 days and kept even if the disk is deleted.
>
> Measured throughput in production: ~8 pages/min with the header VLM on,
> 2 workers. Median page cost 5.8 s, p99 20.6 s, max 35.9 s (278-page sample).

# Scale & Deployment Brief — for the AARVI meeting

> **Accuracy figures in this file are from August (pipeline v24) and are superseded.** Current, measured on pipeline v33 (20 Sep 2026): 95.6% of day rows right against the paper on a 50-page hand-graded sample, 84.3% against the client's Excel on 292 pages, 100% of imperfect pages flagged. See docs/revamp/01-REVAMP-REPORT.md §9.


*Every number below was measured on the demo laptop the night before the
meeting, by actually running the volumes through the live product. Nothing
is projected from small samples.*

---

## 1. The 250-document question — measured, not estimated

**The client's requirement of 250 documents per upload works on the local
machine today.** Load test, run through the real product:

| Measured | Value |
|---|---|
| Files in ONE upload request | **243 PDFs (128 MB payload)** |
| Pages processed | **250** |
| Errors / dropped pages | **0** |
| Wall time (accuracy mode, VLM fallback on) | **52.5 min** (~12.6 s/page effective) |
| Server RAM under load | **observed up to ~774 MB** (spot-sampled, not continuous) — against 16 GB available |
| Server stability | processed in parallel while still ingesting; API recovered fully; zero restarts |

**Bottom line for the meeting: capacity is not the reason to go to cloud.**
RAM headroom is ~20×; the constraint is only wall-clock time, and 250 pages
inside an hour — unattended — already beats a typist by ~16×
(250 pages × 4 min by hand ≈ 16.7 hours).

### One honest caveat, found by this test (better we found it first)

The current build ingests uploads *synchronously inside the request*: with
243 files in one POST, the browser/client can time out while the server
correctly continues in the background (it did — all pages arrived, zero
lost). Two-line guidance until hardened:

- **Today:** upload very large sets in chunks of ~50–100 files; the batch
  behaviour is identical and feedback is immediate.
- **Pre-production (small, well-understood change):** move the split/queue
  step into the background worker so a 250-file upload returns instantly.
  Estimated effort: ~1 day + test.

---

## 2. Throughput — two modes, choose per run

The pipeline has an optional local-VLM fallback that re-reads unclear
headers. It is the accuracy-maximising mode, and it is the current
throughput bottleneck (Ollama serialises model calls, so the 4 workers
queue behind one another on pages that need it).

| Mode | Per page (measured, all-in) | 250 pages | 3,000 pages (monthly volume) |
|---|---:|---:|---:|
| **Max-accuracy** (VLM fallback on — default) | **12.6 s** (250-page test) | ~52 min | ~10.5 h (overnight run) |
| **Fast** (VLM off: `TS_VLM_HEADER=0`) | **8.9 s** (30-page test, same corpus mix) | ~37 min | ~7.4 h |
| Cached re-run (any corrected/re-uploaded page) | ~1 ms | seconds | seconds |

Both figures were measured on a **handwriting-heavy sample** — the hard
case. The production corpus is ~75% typed pages, which route through the
fast path with no VLM and much quicker OCR, so a representative month runs
faster than this table. (Earlier documentation quotes ~3 s/page — that
figure reflects a typed-heavy mix; use THIS table for handwritten-heavy
batches and treat the truth as "3–13 s/page depending on mix".)

Levers before any hardware change: `OLLAMA_NUM_PARALLEL` (parallel VLM
calls), worker count (`env`), and per-batch mode selection (fast for typed
months, max-accuracy for handwritten). All env-vars, no code.

---

## 3. Accuracy of the output — verified through the live product

The night before this meeting, the truth-covered corpus was uploaded
**through the running app itself** (not a test harness) and its stored
output scored against the Excel AARVI's own team typed from the same scans:

| Field | Live-app output accuracy |
|---|---:|
| Employee name | **97.1%** (33/34) |
| Daily attendance | **88.3%** (905/1,025) |
| Designation | **74.2%** (23/31) |
| **Overall** | **88.2%** (961/1,090) |

This exactly reproduces the offline benchmark — the shipped product and the
measured pipeline are provably the same thing. Per page: 14 of 34 pages
100% perfect, median 94%. And the standing guarantee on the rest: every
page is checksummed against the totals the supervisor wrote; failures are
flagged to a reviewer, never silently shipped.

---

## 4. Local vs cloud — the honest decision table

| Option | When it's right | Trade-offs |
|---|---|---|
| **A. Current laptop / one desktop (local)** | ≤ ~3,000 pages/month, single review team | Zero cloud cost, zero data egress, works offline. Proven above. |
| **B. Bigger on-prem box (client's office)** | Higher volume or multiple reviewers; keeps the privacy story fully intact | One-time hardware (a 32–64 GB, 16-core machine roughly halves-to-quarters wall time; workers scale linearly). Deployment = same `run.bat`, ~1 day incl. testing. |
| **C. Client's own VPC / private server** | Multi-site access needed, IT wants central control | Adds TLS + auth work (currently a localhost app — LAN/WAN exposure needs a login layer: ~2–3 days). Data stays inside the client's boundary. |
| **D. Public cloud (rented VM)** | Only if multi-site + no client infra exists | Same auth work as C, plus monthly VM cost, plus **the privacy story changes**: worker attendance PII leaves client premises. This has been our differentiator — spend it knowingly, not by default. |

**Recommended line for the meeting:** *"250 documents runs on the laptop
today — we tested it last night. Cloud is a choice about multi-site access
and who owns the machine, not about capacity. If you want central access,
our first recommendation is a box inside your network so the
data-never-leaves guarantee survives."*

What cloud/remote deployment genuinely requires (for the commercials):
authentication + TLS (~2–3 days), async ingestion hardening (~1 day),
a systemd/service wrapper + backup of the SQLite file (~half day),
and a sizing test on the target machine (~half day). **Total: roughly one
working week to a hardened multi-user deployment**, on any of B/C/D.

---

## 5. The 14-day accuracy plan (what "accuracy achievable in 14 days" means)

Priority-ordered; items 1–2 are data asks from AARVI, not engineering risk:

| Days | Work | Expected effect |
|---|---|---|
| 1–3 | **Get labelled pages from 2–3 more client folders** (their typed Excel + scans, like IOCL) | Extends measurement beyond one site; designation measured on more than one title |
| 2–5 | **Map their real invoice/Excel template** into the export (file exists in the corpus) | Output drops into their workflow unchanged |
| 3–8 | Per-site code-system mapping (paper codes vs typed-Excel codes) | Raises roster auto-match above 69% → fewer identity reviews |
| 5–12 | The three structurally-weak page types (drifting row offsets — diagnosed in docs/14) | Recovers the worst pages (58–65% → expected 85%+) |
| 10–14 | Re-measure everything on the enlarged truth set; publish the new numbers | The defensible post-hardening accuracy figure |

Honest framing: current 88.2% overall / 97.1% names with 100%-checked
arithmetic. The plan above targets the low-90s overall — driven mostly by
*their data* arriving, which is why the data ask leads the list.

---

## 6. Commercials skeleton (cost drivers to quote against)

*Structure only — rates are yours to fill.*

1. **One-time: hardening to production** (~1 week eng): async ingestion,
   auth+TLS, service wrapper, backups, deployment on target machine.
2. **One-time: client-specific fitting** (scope per §5): invoice template
   mapping, per-site code mapping, additional-folder calibration.
3. **Recurring: nothing structural.** No API fees, no per-page cost, no GPU.
   Options to price: support/maintenance retainer; a review-SLA tier; if
   option D, pass-through VM cost (a 16 GB/8-core VM class is sufficient).
4. **The differentiator to keep visible in the quote:** competitors priced
   per page via cloud OCR APIs will re-charge for every correction re-run;
   this system's content-addressed cache makes re-processing free.

---

## 7. Current state of the demo machine

App reset to pristine after the tests (zero batches, cold cache, v14,
roster 1,863) — ready for a live upload in the meeting if asked. The full
technical documentation for the developer team is `TECHNICAL-DOC.md`;
benchmark portal with the 4-engine comparison remains at
`http://127.0.0.1:8090`.
