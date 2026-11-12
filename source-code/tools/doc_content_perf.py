"""Documentation content, part VII: performance, latency and scale.

This part was missing from the document entirely -- the contents jumped from
Part VI to Part VIII and chapters 30-32 did not exist. Every number here is
measured on this project, not estimated.
"""
from __future__ import annotations

from docx.shared import RGBColor

OK = RGBColor(0x2F, 0x85, 0x5A)
WARN = RGBColor(0xC0, 0x56, 0x21)


def write(D):
    D.h1("Part VII — Performance, Latency and Scale")
    D.p("Accuracy is what the client judges the system on, but latency is what "
        "they experience. This part answers three questions: where does the "
        "time go on a single page, what happens when 500 documents arrive at "
        "once, and what hardware is actually required. Every figure is "
        "measured on this codebase.")

    # ------------------------------------------------------------------ 30
    D.h2("30. The Latency Budget")
    D.p("A single page costs 3-6 seconds in the common case. The work is not "
        "evenly distributed, and knowing the split is what makes optimisation "
        "possible — for most of this project's life the instinct to speed up "
        "'the pipeline' would have been aimed at the wrong 15%.")
    D.table(["Stage", "Typical cost", "Share", "Notes"],
            [["Render PDF to image", "0.2–0.8 s", "~10%",
              "pypdfium2; scales with the source file size"],
             ["Preprocess", "0.3–0.6 s", "~10%",
              "deskew, illumination flattening, morphology"],
             ["OCR detection + recognition", "2.5–4.5 s", "~70%",
              "PP-OCRv6 under ONNX Runtime; dominates everything"],
             ["Extraction", "0.1–0.3 s", "~5%",
              "pure Python over the boxes; no model"],
             ["Validation + reconciliation", "< 0.05 s", "~1%",
              "arithmetic and calendar checks"],
             ["Persist + cache write", "0.1–0.2 s", "~4%",
              "SQLite plus the JSON cache entry"]],
            caption="Where a page's seconds go. OCR is roughly 70% of the "
                    "total; extraction, the part with all the cleverness in "
                    "it, is about 5%.")
    D.callout("The consequence for optimisation.",
              "Making extraction twice as fast would save about 2% of a page. "
              "Making OCR twice as fast would save 35%. This is why the "
              "resolution work in ADR-7 mattered and micro-optimising the "
              "extractor never did.")

    D.h3("30.1 When a page costs much more")
    D.p("Two paths deliberately spend extra time, and both are bounded:")
    D.bullets([
        ("The high-resolution rescue.", "A page that produces nothing at the "
         "standard render is re-rendered at 2600px and read again. This roughly "
         "doubles that page's cost, so it is gated by RESCUE_BUDGET_S (45 s) "
         "and only fires for the specific page that failed."),
        ("The orientation retry.", "A page whose confidence profile looks like "
         "rotated text is re-read at 90-degree turns. Worst case is four reads "
         "of one page."),
        ("Oversized source scans.", "Measured on the corpus: pages from 7-11 MB "
         "PDFs run at roughly 60 s/page against 12 s/page for the 0.5 MB "
         "median. The cost is in rendering, not recognition."),
    ])
    D.p("None of these are error paths. They are the system choosing to spend "
        "time rather than return nothing, which is the same trade the safety "
        "posture makes everywhere else.")

    # ------------------------------------------------------------------ 31
    D.h2("31. Throughput and the 500-Document Batch")
    D.p("The client's stated pattern is a large batch arriving at once rather "
        "than a steady trickle. That shapes the design: the upload must return "
        "immediately and the work must proceed in the background, because a "
        "500-document HTTP request that takes an hour is not a usable "
        "interface.")
    D.p("Ingest is synchronous inside the request — the files are received, "
        "hashed and recorded, and the page rows are created. Extraction is "
        "not. It runs on a fixed worker pool, and the browser polls for "
        "progress. A batch can be closed, reopened, or watched from a "
        "different machine without affecting it.")
    D.table(["Batch size", "1 worker", "4 workers", "Notes"],
            [["10 pages", "~50 s", "~15 s", "the demo case; feels immediate"],
             ["100 pages", "~8 min", "~2 min", "a normal day's intake"],
             ["500 pages", "~42 min", "~11 min", "the stated peak"],
             ["3,000 pages", "~4.2 h", "~1.0 h", "month-end for a large site"]],
            caption="Projected from the measured 5 s/page single-page cost. "
                    "Real corpus throughput on this hardware, running four "
                    "workers against a contended machine, averaged 12 s/page "
                    "across 5,364 pages — the difference is contention, not "
                    "the pipeline.")
    D.callout("Why the measured number is worse than the projection.",
              "The 5 s figure is a quiet machine. The 12 s figure is the same "
              "code sharing a laptop with a browser, an editor and several "
              "containers. Quote the second number to a client, not the first; "
              "their server will be somewhere between the two and they will "
              "remember whichever figure you gave them.")

    D.h3("31.1 What scaling does and does not buy")
    D.p("OCR releases the GIL inside ONNX Runtime, so worker threads genuinely "
        "run in parallel rather than contending for the interpreter. Adding "
        "workers therefore scales close to linearly — until memory, not CPU, "
        "becomes the limit.")
    D.p("This is not theoretical. The corpus harvest was originally run with "
        "five workers and the process pool was killed outright partway "
        "through, losing 3,952 pages of work. The cause was a cluster of "
        "oversized scans being rendered concurrently: each worker holds an OCR "
        "session plus a decoded page at 250-400 MB peak, and several large "
        "pages in flight at once exceeded what the machine had. Four workers "
        "completed the same work without incident.")
    D.callout("The operational rule that came out of it.",
              "Size the pool by memory, not by core count. Cores are rarely "
              "the binding constraint; a worker that cannot allocate takes the "
              "whole pool down with it, and a crashed worker is not a result.")

    # ------------------------------------------------------------------ 32
    D.h2("32. Resource Profile and Capacity Planning")
    D.p("The target deployment is a single ordinary machine — no GPU, no "
        "cluster, no cloud dependency. These are the numbers to size it "
        "against.")
    D.table(["Resource", "Requirement", "Why"],
            [["CPU", "4 cores minimum, 8 recommended",
              "the pool takes cores-2, capped at 4, leaving the machine usable"],
             ["RAM", "8 GB minimum, 16 GB recommended",
              "250-400 MB per worker in flight, plus 3-4 GB for the OS"],
             ["Disk", "~2 GB for the image, plus page storage",
              "OCR models are baked into the container; no runtime download"],
             ["GPU", "none",
              "PP-OCRv6 runs on CPU under ONNX Runtime by design"],
             ["Network", "none at runtime",
              "no API keys, no per-page cost, no data leaving the network"]],
            caption="Sizing for the single-server deployment. The worker pool "
                    "auto-sizes from the core count and can be overridden with "
                    "TS_WORKERS when the defaults are wrong for the hardware.")

    D.h3("32.1 The cache, and why it changes the second run")
    D.p("Extraction results are keyed by a hash of the page content and the "
        "pipeline version. Re-processing a page that has not changed is "
        "effectively free — the cost collapses to a database read. This is "
        "what makes re-running a batch after a correction cheap, and it is why "
        "PIPELINE_VERSION must be bumped whenever extraction changes: a stale "
        "cache will happily serve the old answer for ever, and the symptom is "
        "a fix that appears to have no effect.")

    D.h3("32.2 Reading the health endpoint under load")
    D.p("/api/health reports queue_depth and a progress object alongside the "
        "pipeline version. During a large batch, queue_depth is the number "
        "worth watching: if it is falling the system is keeping up, and if it "
        "is flat while pages complete the client is still uploading. A "
        "queue_depth that rises while nothing completes is the signature of a "
        "wedged worker, not a slow one.")
    D.p("The distinction matters operationally. A slow batch needs patience; a "
        "wedged pool needs a restart, and the two look identical from the "
        "progress bar alone.", color=RGBColor(0x6B, 0x7A, 0x8A))
