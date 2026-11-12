"""Documentation content, part A: orientation and high-level design."""
from __future__ import annotations

from docx.shared import RGBColor

OK = RGBColor(0x2F, 0x85, 0x5A)
WARN = RGBColor(0xC0, 0x56, 0x21)
ACCENT = RGBColor(0x2B, 0x6C, 0xB0)


def write(D):
    # ================================================================== TOC
    D.h1("Contents", page_break=False)
    D.p("This document is written to be read start to finish by an engineer "
        "new to the project, and to be dipped into afterwards. Part I explains "
        "the problem. Parts II and III are the high-level and low-level "
        "design. Part IV covers data and interfaces, Part V how accuracy is "
        "measured and improved, Part VI operations, and Part VII latency and "
        "scale.", color=RGBColor(0x6B,0x7A,0x8A))
    D.table(
        ["Part", "Chapters", "What it answers"],
        [["I — Orientation", "1–3", "What the product is, and why the problem is hard"],
         ["II — High-Level Design", "4–8", "Architecture, pipeline, module layering, technology choices"],
         ["III — Low-Level Design", "9–17", "Every stage, algorithm by algorithm"],
         ["IV — Data & Interfaces", "18–20", "Data model, HTTP API, caching"],
         ["V — Accuracy Engineering", "21–25", "How accuracy is measured, what worked, what failed"],
         ["VI — Operations", "26–29", "Deployment, scale, security, troubleshooting"],
         ["VII — Performance & Scale", "30–32", "Latency budget, the 500-document batch, capacity planning"],
         ["VIII — A Page, End to End", "33", "One real page traced through all nine stages"],
         ["IX — Testing & Change Discipline", "34–36", "The change loop, verification suite, known traps"],
         ["X — Extending the System", "37–39", "Adding a client format; known gaps"],
         ["XI — Foundations", "40–46", "Every technique from first principles, basic to advanced"],
         ["XII — Domain Reference", "47–50", "Status codes, summary block, identity, billing"],
         ["XIII — Decision Record", "ADR 1–8", "Why the architecture is shaped this way"],
         ["XIV — Operational Runbook", "51–53", "Daily operation, release checklist, debugging"],
         ["XV — Appendices", "54–56", "Glossary, configuration, file map"],
         ["XVI — Revamp Addendum", "57–65", "The v25→v29 rebuild: harness, changes, evaluation layer, ceiling"]])

    # =========================================================== PART I
    D.h1("Part I — Orientation")
    D.h2("1. Executive Summary")
    D.p("This system turns photographs of handwritten attendance timesheets "
        "into validated, structured Excel that a payroll department can use. "
        "It runs entirely on the client's own hardware: no cloud service, no "
        "API keys, no per-page cost, and no data leaving the network.")
    D.p("The essential design claim is not that it reads handwriting "
        "perfectly. Nothing does. The claim is that it reads most of it "
        "correctly and it tells you about the rest. A wrong value that is "
        "flagged costs a reviewer thirty seconds; a wrong value that is silent "
        "pays the wrong person. Every architectural decision in this document "
        "follows from that asymmetry.", bold=True)

    D.h3("1.1 What it does, in one paragraph")
    D.p("A supervisor fills in a printed attendance form by hand at a refinery "
        "or construction site. Someone photographs or scans it. The system "
        "rasterises the page, corrects skew and lighting, reads it with OCR, "
        "locates the day grid using the printed structure of the form rather "
        "than the handwriting, cross-checks the result against the totals the "
        "supervisor wrote at the bottom and against the calendar, matches the "
        "employee to a roster of 2,575 people, and emits a six-sheet workbook. "
        "Pages it is unsure about are surfaced in a review screen with the "
        "original image beside an editable grid.")

    D.h3("1.2 Measured position")
    D.table(
        ["Measure", "Value", "Basis"],
        [["Day-status accuracy (tuned corpus)", "91.3%", "853/934, 49-page Delhi evaluation"],
         ["Employee name accuracy", "96.8%", "30/31, same evaluation"],
         ["Day-status accuracy (whole corpus)", "72.6%", "6,347/8,737 across 1,218 pages, all three datasets"],
         ["Employee name (whole corpus)", "96.7%", "291/301 matched pages"],
         ["Imperfect pages that were flagged", "100%", "256 of 256 — zero escaped errors"],
         ["Page processing errors", "0", "across 1,218 pages"],
         ["Throughput", "~5.4 s/page", "single page, warm engine, 4 workers"]],
        caption="Headline measurements. The two accuracy figures differ because the "
                "49-page set is one form family the extractor was tuned on, while the "
                "corpus figure includes clients it had never seen.")
    D.callout("Read these two numbers together.",
              "Quoting 91% alone would mislead: it describes familiar formats. "
              "72.6% is what unfamiliar client formats produce today. Both are real, "
              "and the gap is the honest measure of how far generalisation has to go.")
    D.callout("Superseded by Part XVI (2026-09-13 revamp).",
              "The table above is the v25 position. On the corpus-faithful harness "
              "the pipeline now measures 86.5% strict / 90.3% convention-respected "
              "day status (from 78.4% / 82.0%), with every change and its "
              "measurement recorded in Part XVI and docs/revamp/. The safety row "
              "is unchanged: every imperfect page flagged, none escaped.",
              color=ACCENT)

    D.h2("2. The Problem Domain")
    D.h3("2.1 What a timesheet actually is")
    D.p("The documents are pre-printed A4 forms. The printed part carries the "
        "company header, labelled header fields (Employee Name, Designation, "
        "Client, Project, Month & Year), a ruled grid of up to 31 day rows "
        "with columns for date, time in, time out, normal hours, overtime and "
        "remarks, and a summary block at the bottom stating totals: present "
        "days, absent days, leave, weekly offs, public holidays, man hours, "
        "overtime hours.")
    D.p("Everything written into that structure is handwritten, in ballpoint, "
        "by a supervisor at a site, often photographed on a phone under "
        "fluorescent light on a desk with other paper visible at the edges.")

    D.h3("2.2 Why this is harder than ordinary OCR")
    D.bullets([
        ("Handwriting, not print.", "OCR trained on printed text reads ballpoint digits with far lower confidence. On these pages the weakest quarter of readings sits near 0.78 confidence versus 0.99 for printed labels."),
        ("The values are numbers with no redundancy.", "In prose, context repairs a misread character. '18:00' misread as '10:00' has no context to repair it — it is simply eight hours of pay."),
        ("The grid is geometric, not linear.", "A cell's meaning comes from its row and column, so a row-boundary error shifts every subsequent day by one and corrupts the whole month."),
        ("Formats vary per client.", "The corpus contains 244 client folders across three datasets. The layouts are not variations on one form; some run days down the page, others across it."),
        ("The ground truth is imperfect.", "The client's own typed Excels contradict each other on 9.2% of employee records — the same person, same month, different attendance in different files."),
    ])

    D.h3("2.3 The economics")
    D.p("A person typing one of these sheets takes about four minutes. At 500 "
        "sheets a month that is roughly a working week of somebody's time, "
        "every month, spent transcribing. The system processes 500 documents "
        "in twelve to fifteen minutes on four workers. The saving is not the "
        "machine being clever; it is the machine being tireless, plus a human "
        "confirming the small fraction that is doubtful.")

    D.h2("3. The User Journey")
    D.bullets([
        ("Upload.", "Staff select PDFs or photographs in a browser and give the batch a name. Multi-page PDFs are split into pages automatically."),
        ("Processing.", "A background worker queue reads each page. A live log strip shows progress; nothing blocks the browser."),
        ("Review.", "Each page appears with a status. Pages with blocking issues surface first, showing the original image on the left and an editable grid on the right."),
        ("Correction.", "The reviewer fixes a value and saves. The record is re-validated immediately, so a correction that fixes one number and breaks a checksum is caught at once, not at invoice time. Every change is written to an audit trail with the actor's name."),
        ("Export.", "One click produces a workbook with six sheets, each aimed at a different consumer — finance, HR, payroll import, compliance audit, and a dashboard."),
    ], numbered=True)
    D.callout("Why the review screen shows the image.",
              "A reviewer cannot judge whether '18' should be '13' from the extracted "
              "value alone. Putting the source pixels beside the editable field is what "
              "makes a thirty-second correction possible.", color=OK)

    # =========================================================== PART II
    D.h1("Part II — High-Level Design")
    D.h2("4. System Context")
    D.figure("01_context.png",
             "Figure 1 — Actors and boundaries. Everything inside the box runs on the "
             "client's own server.")
    D.p("The system has no outbound dependencies at runtime. The OCR models "
        "are baked into the container image at build time, which is what "
        "makes an air-gapped installation possible. The only external "
        "interfaces are a browser on the local network and the Excel files "
        "that leave by download.")

    D.h2("5. Architecture Principles")
    D.p("Five principles explain most of the code. They are stated here "
        "because the design is otherwise hard to justify locally.")
    D.h3("5.1 No page may fall through")
    D.p("Every branch of the pipeline terminates in a record plus a status. If "
        "a stage throws, the page becomes 'needs_review' with the exception "
        "attached — it is never dropped and never silently emitted as clean. "
        "The output is not 'everything we read correctly'; it is 'everything, "
        "with the doubtful parts marked'. This is the property that makes the "
        "system safe to place in front of an invoice run.")
    D.code(
        "except Exception as exc:\n"
        "    # Failure is a reviewable outcome, never a dropped page.\n"
        "    return {\n"
        "        'record': {'days': [], 'summary': {}},\n"
        "        'issues': [{'code': 'pipeline_error', 'severity': BLOCK,\n"
        "                    'message': f'Processing failed: {exc}. Page needs manual entry.'}],\n"
        "        'status': 'needs_review',\n"
        "    }                                          # app/pipeline.py")

    D.h3("5.2 Read the printed form, not the handwriting")
    D.p("The largest accuracy gains in this project all came from the same "
        "move: take structure from the pre-printed parts of the page, which "
        "are crisp and machine-readable, and use the handwriting only for the "
        "values. Row boundaries come from printed rules rather than ink "
        "clustering. Column positions come from the form's fixed left-to-right "
        "order when a header is unreadable. Row count is bounded by the "
        "calendar, because a month has at most 31 days.")

    D.h3("5.3 Refuse rather than guess")
    D.p("Where the system cannot distinguish between two answers it declines "
        "to choose. The roster will not match a name if the two best "
        "candidates score within six points of each other, because a "
        "confident match to the wrong employee is the error that costs money. "
        "The generic grid reader refuses a page whose 'day numbers' are "
        "actually a serial-number column. An honest refusal becomes a review "
        "item; a confident guess becomes a wrong payment.")

    D.h3("5.4 Measure before believing")
    D.p("This codebase has repeatedly produced changes that looked obviously "
        "correct and measured worse. The project therefore keeps two "
        "evaluation harnesses and a regression panel, and no accuracy claim is "
        "accepted without a harness run. Chapter 25 lists the changes that "
        "were implemented, measured, and reverted.")

    D.h3("5.5 Everything env-overridable")
    D.p("All tunable behaviour is read from environment variables with tested "
        "defaults, so the same build runs on a 16 GB demo laptop and on a "
        "larger server without a code change. Configuration is catalogued in "
        "Appendix 31.")

    D.h2("6. The Processing Pipeline")
    D.figure("02_pipeline.png",
             "Figure 2 — The nine stages a page passes through. Stages 7 and 8 are "
             "where safety is enforced.")
    D.table(
        ["#", "Stage", "Module", "Input → Output"],
        [["1", "Ingest", "preprocess.split_pdf", "PDF/image → one PNG per page"],
         ["2", "Preprocess", "preprocess.normalise_page", "raw PNG → deskewed, flattened, resized"],
         ["3", "OCR", "ocr_engine.run_ocr", "PNG → text boxes with confidence"],
         ["4", "Route", "ocr_engine.route_from_profile", "boxes → confident | needs_escalation"],
         ["5", "Extract", "aarvi_form.extract / generic_grid", "boxes → structured record"],
         ["6", "Reconcile", "reconcile.reconcile", "record → record repaired from its own totals"],
         ["7", "Validate", "validate.validate", "record → list of issues"],
         ["8", "Status", "validate.status_for", "issues → clean | review_optional | needs_review"],
         ["9", "Export", "export_designs.export", "records → six-sheet workbook"]],
        caption="Stage-by-stage responsibilities. Each stage is a pure function of its "
                "input except ingest and export, which touch the filesystem.")

    D.h2("7. Module Architecture")
    D.figure("03_modules.png",
             "Figure 3 — Five layers. Dependencies point downwards only; no lower layer "
             "imports from a higher one.")
    D.table(
        ["Layer", "Modules", "Responsibility"],
        [["Interface", "main.py, web/index.html, db.py",
          "HTTP API, the review UI, persistence"],
         ["Orchestration", "pipeline.py, eventlog.py",
          "Sequencing the stages, caching, the live log"],
         ["Understanding", "aarvi_form.py, generic_grid.py, field_typing.py, reconcile.py",
          "Turning boxes into a record and repairing it"],
         ["Perception", "ocr_engine.py, preprocess.py, vlm_header.py",
          "Pixels to text; page geometry"],
         ["Knowledge", "roster.py, vocab.py, templates_spec.py, form_profiles.py, validate.py",
          "What the world contains and what is plausible"]],
        caption="Layering. app/aarvi_form.py is the largest module at roughly 1,700 lines "
                "and holds the day-grid recovery described in Chapter 11.")

    D.h2("8. Technology Choices")
    D.table(
        ["Decision", "Chosen", "Rejected alternative", "Why"],
        [["OCR engine", "RapidOCR (PP-OCRv6, ONNX)", "PaddleOCR framework",
          "Same models, no PaddlePaddle install — the usual source of Windows failures"],
         ["Runtime", "CPU-only ONNX", "GPU inference",
          "Client hardware is a 16 GB CPU box; no CUDA dependency"],
         ["PDF raster", "pypdfium2", "poppler / pdf2image",
          "No external binary to install"],
         ["Imaging", "opencv-python-headless", "opencv-python",
          "No GUI libraries in the container; see the libxcb defect in Chapter 26"],
         ["Web", "FastAPI + uvicorn", "Flask/Django",
          "Async upload handling and automatic schema in one small dependency"],
         ["Store", "SQLite", "PostgreSQL",
          "Single-process deployment; no DB server for the client to run"],
         ["Excel", "openpyxl", "pandas.to_excel",
          "Needs cell-level styling and multiple designs per workbook"],
         ["VLM", "off by default", "Ollama + qwen3-vl:4b",
          "Measured as unnecessary: 89.5% overall without it (Chapter 25)"]],
        caption="Technology decisions and the alternatives considered.")
