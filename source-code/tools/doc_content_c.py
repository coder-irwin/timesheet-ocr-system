"""Documentation content, part C: data, accuracy engineering, operations."""
from __future__ import annotations

from docx.shared import RGBColor

OK = RGBColor(0x2F, 0x85, 0x5A)
WARN = RGBColor(0xC0, 0x56, 0x21)


def write(D):
    # =========================================================== PART IV
    D.h1("Part IV — Data and Interfaces")
    D.h2("18. Data Model")
    D.h3("18.1 Persistent tables")
    D.table(["Table", "Key columns", "Purpose"],
            [["batch", "id, name, created_at", "one upload"],
             ["page", "id, batch_id, source_name, image_path, page_hash, record, issues, status",
              "one page, its extracted record and current status"],
             ["audit", "id, page_id, actor, action, field, old_value, new_value, ts",
              "every extraction, correction and export"]],
            caption="SQLite schema. The record and issues columns hold JSON.")
    D.h3("18.2 The record")
    D.p("A record is the structured result for one page. It is the unit that "
        "flows from extraction through validation to export.")
    D.code(
        "{\n"
        "  'employee_name': 'DINESH BHATTACHARYA',\n"
        "  'employee_code': '53340',\n"
        "  'designation':   'Safety Supervisor',\n"
        "  'client':        'IOCL MR',\n"
        "  'project':       'Dept. Fire Safety',\n"
        "  'period_label':  'April -2026',\n"
        "  'summary':       {'total_present_days': '25', 'total_ot_hours': '30', ...},\n"
        "  'days': [\n"
        "     {'day': 1, 'in_time': '8', 'out_time': '18:00',\n"
        "      'normal_hours': '08', 'ot_hours': '01', 'total_hours': '09',\n"
        "      'remarks': None, 'status': 'P',\n"
        "      '_conf': {'date': 0.96, 'in_time': 0.64, ...}},\n"
        "     ... up to 31 entries ...\n"
        "  ],\n"
        "  '_confidence': {...},   '_roster': {...},   '_anchors_found': [...]\n"
        "}")
    D.p("Underscore-prefixed keys are provenance rather than data: which "
        "anchors were found, per-field confidence, how the roster resolved, "
        "whether the page was rotated or read at high resolution. They are "
        "what make a disagreement explainable months later.")

    D.figure("08_upload_sequence.png",
             "Figure 8 — Upload and processing. Ingest is synchronous; extraction is "
             "queued to background workers.")

    D.h2("19. HTTP API")
    D.table(["Method", "Path", "Purpose"],
            [["GET", "/", "the review UI"],
             ["GET", "/api/health", "readiness, engine, roster size, pipeline version, queue depth"],
             ["POST", "/api/batches", "multipart upload; returns batch id and page ids"],
             ["GET", "/api/batches", "list batches"],
             ["GET", "/api/batches/{id}/pages", "page list with status and counts"],
             ["GET", "/api/batches/{id}/export", "download the workbook (design=all or one)"],
             ["GET", "/api/pages/{id}", "full record and issues for one page"],
             ["GET", "/api/pages/{id}/image", "the normalised page image"],
             ["PUT", "/api/pages/{id}", "save reviewer corrections; re-validates"],
             ["POST", "/api/pages/{id}/reextract", "re-run extraction for one page"],
             ["POST", "/api/roster", "replace the employee roster"],
             ["GET", "/api/audit", "audit trail"],
             ["GET", "/api/log", "live event log for the UI strip"]],
            caption="The complete surface. There is no authentication — see Chapter 28.")
    D.callout("Re-validation on save is the point.",
              "PUT does not simply store what the reviewer typed. It re-runs the full "
              "validation suite, so a correction that fixes one number and breaks the "
              "row-sum is caught immediately rather than at invoice time. A defect was "
              "found and fixed during this work where the save path validated a "
              "different data shape from the extraction path, causing a clean page to "
              "acquire a blocking issue merely by being confirmed.")

    D.figure("09_review_sequence.png",
             "Figure 9 — Review and correction. The save path re-validates rather than "
             "simply storing.")

    D.h2("20. Caching")
    D.p("Extraction results are keyed by the SHA-256 of the normalised page "
        "image combined with the pipeline version. The same page re-uploaded "
        "after a correction, or arriving again in next month's batch, is "
        "served from disk instead of re-running OCR. The client's original "
        "cost complaint came from a correction loop that re-billed them for "
        "work already done; this is the structural fix.")
    D.callout("The version bump discipline.",
              "PIPELINE_VERSION must be incremented on any extraction change, or the "
              "cache serves results from the old code and the change appears to do "
              "nothing. This has caught people out before and is the first thing to "
              "check when a change 'has no effect'.")

    # ============================================================ PART V
    D.h1("Part V — Accuracy Engineering")
    D.h2("21. How Accuracy Is Measured")
    D.p("Accuracy is scored against the client's own typed Excel files, which "
        "are simultaneously the ground truth and the output format the client "
        "expects. A page is matched to a truth row by employee code where "
        "available, otherwise by fuzzy name with a margin requirement. Day "
        "statuses are then compared position by position.")
    D.h3("21.1 Ground-truth recovery")
    D.p("The original parser recognised one Excel shape and silently returned "
        "nothing for anything else — 35 of 702 files. The rejections were "
        "cosmetic rather than substantive.")
    D.table(["Cause", "Effect"],
            [["'Employee_Name' ≠ 'employee name'", "73 Delhi files dropped over one underscore"],
             ["header below row 15", "outside the search window"],
             ["demanded ≥20 day columns", "excluded 15-day fortnightly sheets"],
             ["stricter header regex", "missed columns headed '29 Fri'"],
             ["integers only", "missed Excel datetimes and '21May Thu' headers"]],
            caption="Why ground truth was being discarded. Recovering it was worth more "
                    "than any single extraction change, because it is what makes every "
                    "later change measurable.")
    D.p("The rewritten parser reads 285 files and 12,125 employee rows — a "
        "25-fold increase — by finding the day grid structurally and locating "
        "the name column relative to it.")

    D.h2("22. The Harnesses")
    D.table(["Harness", "Runtime", "Covers", "Use for"],
            [["tools/eval_fast.py", "~3 s", "extraction + reconciliation, replaying frozen OCR",
              "choosing between hypotheses"],
             ["tools/eval_corpus.py", "hours", "all three datasets, full pipeline",
              "the quotable number"],
             ["tools/eval_desig.py", "~4 s", "18-probe designation regression panel",
              "guarding vocabulary behaviour"],
             ["tools/verify_end_to_end.py", "~2 min", "10 system checks including export and API",
              "before any release"]],
            caption="The four harnesses. The fast and full harnesses give different "
                    "absolute numbers by design; compare fast-to-fast and full-to-full, "
                    "never across.")
    D.callout("Re-freeze after any OCR or preprocessing change.",
              "eval_fast replays stored OCR output. A preprocessing change scored against "
              "a stale freeze measures nothing at all. A parameter sweep that rewrites "
              "the frozen file also leaves it holding the LAST swept value rather than "
              "the chosen one — rebuild it deliberately at the winner.")

    D.h2("23. Where the Accuracy Lives")
    D.figure("07_accuracy_share.png",
             "Figure 7 — Day status is 94% of all comparisons. Effort spent anywhere "
             "else barely moves the total.")
    D.p("Day status accounts for 1,025 of 1,090 comparisons. A change adding "
        "ten points to employee names moves the overall figure by 0.3; the "
        "same ten points on day status moves it by 9.4. This single fact "
        "should direct almost all optimisation effort at the grid.")

    D.h2("24. Measured Results")
    D.table(["Change", "Effect", "Verdict"],
            [["Strip month from employee name", "matched pages 26→30; day 710/787→820/903", "kept"],
             ["Strip job title from name", "+1 page, +24 correct days, 0 regressions", "kept"],
             ["Snap misplaced weekly off", "+4 day comparisons, no regressions", "kept"],
             ["Annotation gate 82→72", "+5, on a flat plateau", "kept"],
             ["Landscape render at 2600 px", "day header 4/30 → 30/30", "kept"],
             ["Orientation rescue", "sideways pages: 0 anchors → 2", "kept"],
             ["High-resolution rescue", "SHELL04: 0 days → 28, name recovered", "kept"],
             ["Generic grid reader", "a SHELL page: 0 → 30 days, 26/26 vs client Excel", "kept"],
             ["Period from file path", "resolves 9/9 unresolved pages, no accuracy change", "kept, neutral"],
             ["Higher resolution for handwriting", "91.3% → 87.5% → 85.9%", "rejected"]],
            caption="Every change measured. The last row matters as much as the others.")

    D.h2("25. Traps and Rejected Approaches")
    D.p("A design document that lists only successes teaches nothing about "
        "why the system is shaped as it is. These were implemented, measured "
        "and reverted.")
    D.table(["Attempted", "Measured", "Why it failed"],
            [["Month normalisation of the period label", "82.1% → 79.5%",
              "destroyed legitimate two-month labels like 'June - July 26'"],
             ["Ordinal row matching", "handwritten 70% → 60%",
              "right idea for a uniformly shifted grid, wrong for a drifting one"],
             ["Whole-row text for status inference", "55.1% → 53.3%",
              "caught intended 'SUNDAY' notes but pulled text from adjacent rows"],
             ["Splitting merged rows on two time tokens", "60.2% → 57.3%",
              "recovered 27→29 rows but did not fix the alignment it targeted"],
             ["Qwen3-VL for the day grid", "scored 0%",
              "a reasoning model: the output was in 'thinking', not 'response'"],
             ["VLM for the full grid", "flawless but fabricated",
              "returned a perfect 31-day series including four Sundays marked worked"]],
            caption="Rejected approaches with their measurements.")
    D.callout("Two failure signatures worth memorising.",
              "A result too BAD to be true usually indicts the harness, not the model — "
              "the 0% VLM score was an output-field bug. A result too GOOD to be true "
              "usually indicts the data — well-formed fake data passes validation "
              "silently, which is why a VLM is used only where the answer is short and "
              "checkable.")
    D.h3("25.1 Attributing a win to the wrong change")
    D.p("A page went from 10 distinct days to 30. The gain was credited to "
        "rule bands; the bands had in fact been rejected on that page. The "
        "real cause was a footer bound applied as a side effect — one that had "
        "previously measured worse and had silently re-entered the code. One "
        "page cannot attribute a cause.")
    D.h3("25.2 Tuning on five pages")
    D.p("An early version reported 82.1% from five hand-picked pages. The real "
        "number on the full set was 50.7%.")

    D.h2("25.3 The ceiling nobody can engineer past")
    D.p("The client's own spreadsheets contradict themselves.")
    D.table(["Measure", "Value"],
            [["employee records examined", "1,659"],
             ["names appearing more than once", "254"],
             ["names whose records CONTRADICT", "153 (9.2%)"]],
            caption="Self-contradiction in the ground truth, by tools/truth_conflicts.py.")
    D.p("One employee has twelve mutually inconsistent May records. Another "
        "has three April records disagreeing on four to five days each. One "
        "extraction was verified correct on 26 of 26 comparable days against "
        "one of those three versions — and still scored zero, because the "
        "harness refuses to pick whichever answer happens to agree with it.")
    D.callout("Why 100% is not available.",
              "Where the source data gives three different answers for the same "
              "employee-month, there is no single correct answer to be right about. This "
              "caps any accuracy figure, for this pipeline or any other, and it is "
              "resolved by data cleanup on the client side rather than by software.")

    # =========================================================== PART VI
    D.h1("Part VI — Operations")
    D.h2("26. Deployment")
    D.figure("06_deployment.png",
             "Figure 6 — Container topology. The image is effectively read-only; all "
             "state lives in the mounted volume.")
    D.p("The delivered artefact is a single ZIP containing pre-built container "
        "images for both Intel and ARM, the roster, ten sample sheets, the "
        "full source, and an installer that detects the processor and loads "
        "the right image. It installs with no internet connection because the "
        "OCR models are already inside the image.")
    D.h3("26.1 Build-time gates")
    D.p("The Dockerfile fails rather than producing an image if any of three "
        "checks do not hold: the imaging library must be the headless build, "
        "the OCR models must be present, and the application must import "
        "cleanly.")
    D.callout("A real defect these caught.",
              "The first build produced an image that failed with "
              "'libxcb.so.1: cannot open shared object file'. RapidOCR declares a "
              "dependency on the GUI build of OpenCV, which overrode the headless one "
              "this project pins. Without the gate that image would have installed "
              "successfully on a customer server and then failed on the very first "
              "upload.", color=OK)
    D.h3("26.2 Data and backup")
    D.p("Everything the application stores lives in the mounted /data folder: "
        "the roster, original uploads, normalised pages, the extraction cache, "
        "generated workbooks and the SQLite database. Copying that folder is "
        "the entire backup. Nothing of value is inside the container.")

    D.h2("27. Performance and Scale")
    D.table(["Measure", "Value", "Conditions"],
            [["per page", "~5.4 s", "warm engine, no rescue path"],
             ["page preparation", "~3.4 s/page", "render + deskew + flatten + resize"],
             ["500 documents", "~12–15 min", "four workers"],
             ["rescue path", "capped at 45 s", "only on pages that produced nothing"],
             ["peak RAM under load", "~774 MB", "against 16 GB available"],
             ["load test", "243 PDFs / 250 pages, 0 errors", "single upload request"]],
            caption="Measured throughput. Healthy pages never enter a rescue path.")
    D.h3("27.1 The concurrency decision")
    D.p("Extraction runs on a background worker queue. On a CPU-only machine "
        "the model is the bottleneck, and running two pages concurrently makes "
        "both slower while doubling peak memory — the thing most likely to "
        "kill a 16 GB machine mid-demo. The default is four workers, tuned to "
        "the target hardware.")
    D.h3("27.2 A known limitation")
    D.p("Uploads are ingested synchronously inside the HTTP request. With 243 "
        "files in one POST the browser can time out while the server "
        "correctly continues in the background — in the load test all pages "
        "arrived and none were lost. Until that is moved into the worker, "
        "upload in chunks of 50–100 files.")

    D.h2("28. Security and Privacy")
    D.bullets([
        ("No egress.", "The application makes no outbound network calls at runtime. The OCR models are local; the optional VLM is off by default and, if enabled, points at a local Ollama."),
        ("No authentication.", "The service is unauthenticated by design for a private company network. It must not be exposed to the public internet without a reverse proxy providing login — it contains employee names and attendance records."),
        ("Personal data.", "The roster holds 2,575 real employee names and the corpus holds real client documents. The release packaging script refuses to build if any client PDF, spreadsheet or database is present in the bundle."),
        ("Audit trail.", "Every extraction, correction and export is recorded with actor, field, old value, new value and timestamp."),
    ])

    D.h2("29. Troubleshooting")
    D.table(["Symptom", "Likely cause", "Action"],
            [["A change appears to do nothing", "cache serving old results", "bump PIPELINE_VERSION"],
             ["Every page flagged", "roster not loaded", "check /api/health roster_size"],
             ["Names match the wrong person", "threshold too permissive", "raise TS_ROSTER_MIN_SCORE"],
             ["Too many sum mismatches", "tolerance too tight", "raise TS_SUM_TOLERANCE_PCT"],
             ["Sideways page reads nothing", "rotation beyond deskew range", "orientation rescue handles it; check _rotated"],
             ["Dense landscape sheet unreadable", "resolution", "confirm the landscape render path fired"],
             ["Container will not start", "wrong CPU architecture", "installer selects it; check uname -m"],
             ["Upload times out on a huge batch", "synchronous ingest", "upload in chunks of 50–100"]],
            caption="Common symptoms and their causes.")

