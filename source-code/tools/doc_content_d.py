"""Documentation content, part D: worked example, testing, extension guide."""
from __future__ import annotations

from docx.shared import RGBColor

OK = RGBColor(0x2F, 0x85, 0x5A)
WARN = RGBColor(0xC0, 0x56, 0x21)


def write(D):
    # ============================================ WORKED EXAMPLE
    D.h1("Part VIII — A Page, End to End")
    D.p("This chapter traces one real page through every stage, with the "
        "actual values produced at each step. It is the fastest way to build "
        "a mental model of the system, and the best reference when debugging: "
        "if your page behaves differently at a given stage, that is where to "
        "look.")

    D.h2("33. The Input")
    D.p("The file is 01_Sharad_Saxena.pdf: one page, a printed AARVI "
        "attendance form for IOCL, filled in by hand for April 2026 and "
        "photographed.")

    D.h3("33.1 Stage 1 — Ingest")
    D.code(
        "preprocess.split_pdf('01_Sharad_Saxena.pdf', out_dir, stem)\n"
        "  page size 595 x 842 pt (A4 portrait)\n"
        "  portrait -> render scale 2\n"
        "  -> 01_Sharad_Saxena_p001.png   1190 x 1684")

    D.h3("33.2 Stage 2 — Preprocess")
    D.code(
        "deskew   : Hough finds the ruled lines, median angle -0.4 deg -> rotated\n"
        "flatten  : divide by Gaussian blur (sigma = long_edge/20)\n"
        "resize   : portrait, so long edge -> 1600\n"
        "  -> 1130 x 1600 normalised page")

    D.h3("33.3 Stage 3 — OCR")
    D.code(
        "ocr_engine.run_ocr(page)  ->  224 text boxes\n"
        "confidence_profile:\n"
        "  n        224\n"
        "  mean     0.931\n"
        "  p25      0.9236        <- weakest quarter\n"
        "  frac_low 0.1059        <- 10.6% below 0.80")

    D.h3("33.4 Stage 4 — Route")
    D.p("p25 of 0.9236 is above the 0.90 threshold and frac_low of 0.1059 is "
        "below 0.15, so the page routes as 'confident'. This is the case "
        "discussed in 10.3: a printed form filled in by hand looks typed in "
        "aggregate. The extraction path still handles the handwriting "
        "correctly; the routing only selects tolerances.")

    D.h3("33.5 Stage 5 — Extract")
    D.code(
        "anchors found (14):\n"
        "  client, designation, employee_code, employee_name, location,\n"
        "  month_year, project, total_absent_days, total_comp_off,\n"
        "  total_leave_days, total_man_hours, total_ot_hours,\n"
        "  total_present_days, total_public_holiday, total_weekly_off\n"
        "\n"
        "columns learned (7):\n"
        "  date, in_time, out_time, normal_hours, ot_hours, total_hours, remarks\n"
        "\n"
        "row bands   : printed rules formed a regular ladder -> 31 bands\n"
        "day rows    : 31 emitted")
    D.p("Two header values arrive contaminated and are repaired by the content "
        "cleaners described in 11.2:")
    D.code(
        "employee_name raw : 'DINESH BHATTACHARYA'        (clean on this page)\n"
        "designation   raw : 'Sefcty Supesniser'\n"
        "designation   snapped by vocabulary -> 'Safety Supervisor'  (score 76.7)")

    D.h3("33.6 Stage 6 — Reconcile")
    D.code(
        "period_label 'April -2026' -> parse_period -> (2026, 4)\n"
        "stated total_weekly_off = 4, confidence 0.988  -> trusted\n"
        "grid already holds 4 W rows                    -> counts agree\n"
        "weekly-off snap: all four W rows fall on Sunday -> nothing to move\n"
        "result: no repair needed on this page")

    D.h3("33.7 Stage 7 — Validate")
    D.code(
        "[block] ot_sum_mismatch\n"
        "        Day rows sum to 32.0 OT hours but the sheet states 30.0\n"
        "        (difference 2.0)\n"
        "[warn]  in_out_vs_hours_mismatch  (day 29: span 3.0h vs 8.0+1.0 recorded)\n"
        "[warn]  low_field_confidence      total_leave_days     0.75\n"
        "[warn]  low_field_confidence      total_public_holiday 0.77")
    D.callout("This is the system working, not failing.",
              "The sheet's own arithmetic does not add up: the thirty-one day rows sum "
              "to 32 overtime hours while the supervisor wrote 30 at the bottom. Today "
              "that discrepancy goes into payroll unnoticed. The system caught it and "
              "will not release the page until a human looks.", color=OK)

    D.h3("33.8 Stage 8 — Status")
    D.p("One blocking issue is present, so the page is 'needs_review' and "
        "surfaces at the top of the review queue.")

    D.h3("33.9 The reviewer corrects it")
    D.code(
        "PUT /api/pages/1\n"
        "  summary.total_ot_hours: '30' -> '32'\n"
        "\n"
        "response: {'ok': True, 'status': 'corrected', 'changed': 1,\n"
        "           'issues': [...], blocks: 0}\n"
        "\n"
        "audit: demo-reviewer  field_corrected  summary.total_ot_hours  30 -> 32")
    D.p("The save re-runs the full validation suite against the corrected "
        "record. The blocking issue clears, the page becomes 'corrected', and "
        "the change is in the audit trail with the reviewer's name.")

    D.h3("33.10 Stage 9 — Export")
    D.code(
        "GET /api/batches/1/export?design=all   -> HTTP 200, 39 KB\n"
        "\n"
        "Timesheet Detail   556 rows\n"
        "Invoice             16 rows\n"
        "Attendance          14 rows\n"
        "Audit              154 rows\n"
        "Payroll_Import      11 rows\n"
        "Dashboard           37 rows")
    D.p("Total elapsed for this page from upload to reviewable state: about "
        "four seconds on a warm engine.")

    # ============================================ TESTING
    D.h1("Part IX — Testing and Change Discipline")
    D.h2("34. The Change Loop")
    D.p("Every accuracy-affecting change in this project follows the same "
        "loop. It exists because the codebase has repeatedly produced "
        "plausible improvements that measured worse, and one that measured "
        "better for the wrong reason.")
    D.bullets([
        ("State the number.", "Current value, on how many comparisons, and the target. If you cannot state it, your first task is measurement, not code."),
        ("Categorise the failures before hypothesising.", "Count row_missing versus status_wrong versus status_empty. This has overturned the obvious explanation more than once — a defect filed as 'rows missing' turned out to be over-segmentation producing 42 rows on a 30-row grid."),
        ("Change one thing, behind a keyword argument", "so both states remain runnable and the effect is attributable."),
        ("Run the fast harness.", "Improved, keep; worse, revert."),
        ("Sweep the parameter if the change has one.", "A flat surface means the value is safe; a sharp spike means you are fitting noise — check how many pages actually differ before believing it."),
        ("Run the full harness once, at the end,", "for the number you quote."),
        ("Write the rejection down.", "A measured failure is a result."),
    ], numbered=True)

    D.h2("35. The Verification Suite")
    D.p("tools/verify_end_to_end.py runs ten checks against the shipped code "
        "with nothing mocked. It is the gate before any release.")
    D.table(["#", "Check", "Proves"],
            [["1", "all app modules import", "no syntax or dependency breakage"],
             ["2", "roster loads", "identity matching will work"],
             ["3", "handwritten page, full chain", "the core path produces a record"],
             ["4", "typed transposed page", "the generic grid reader works"],
             ["5", "corrupt input", "no page falls through; it becomes reviewable"],
             ["6", "Excel export", "a real workbook with real rows"],
             ["7", "fast accuracy harness", "no accuracy regression"],
             ["8", "designation regression panel", "vocabulary behaviour intact"],
             ["9", "generic grid refuses an employee list", "the anti-fabrication guard holds"],
             ["10", "ground-truth index", "measurement infrastructure is present"]],
            caption="The ten end-to-end checks. All ten pass on the shipped build.")

    D.h2("36. Traps Specific to This Codebase")
    D.table(["Trap", "Symptom", "Guard"],
            [["Stale cache", "a change appears to do nothing", "bump PIPELINE_VERSION"],
             ["Stale frozen inputs", "an OCR change measures as neutral", "re-freeze before scoring"],
             ["Sweep leaves the wrong freeze", "later runs measure the last swept value", "rebuild at the chosen value"],
             ["Comparing across harnesses", "apparent 10-point swings", "fast-to-fast, full-to-full only"],
             ["Denominator growth", "accuracy % falls while the system improves", "report hits AND totals"],
             ["A rejected change returning", "an old regression reappears", "re-check defaults of new keywords"],
             ["Server running old code", "the UI disagrees with the harness", "check /api/health pipeline"]],
            caption="Failure modes this project has actually hit, and what catches them.")
    D.callout("The denominator trap is the subtlest.",
              "Fixing the name contamination took matched pages from 26 to 30 and correct "
              "days from 710 to 820 — a clear improvement — while one headline percentage "
              "FELL, because four previously-invisible hard pages entered the scoring. "
              "Always report the counts alongside the percentage.")

    # ============================================ EXTENSION
    D.h1("Part X — Extending the System")
    D.h2("37. Adding Support for a New Client Format")
    D.p("This is the most common extension task. There are three levels of "
        "effort, and the right one depends on how the new form differs.")
    D.h3("37.1 Level 1 — nothing to do")
    D.p("If the form enumerates its days in a run of integers, the generic "
        "grid reader (Chapter 12) will find it without any code change. Test "
        "first before assuming work is needed:")
    D.code(
        "from app import generic_grid, ocr_engine, preprocess\n"
        "page  = preprocess.prepare(pdf)[0][0]\n"
        "boxes = ocr_engine.run_ocr(page)\n"
        "axis  = generic_grid.find_day_axis(boxes, w, h)\n"
        "print(generic_grid.describe(axis))\n"
        "  ->  'row-oriented grid, 30 days (1..30)'")

    D.h3("37.2 Level 2 — a new anchor set")
    D.p("If the form is a labelled header plus a day-per-row grid but the "
        "label wording differs, add a FormProfile in app/form_profiles.py with "
        "that client's header and summary anchors. The existing extraction "
        "machinery then applies unchanged.")

    D.h3("37.3 Level 3 — a new reader")
    D.p("If the grid is structurally different — days across the page, several "
        "employees per sheet, sub-rows per employee — extend generic_grid "
        "rather than adding another profile. The row-oriented reader in that "
        "module was written for exactly this case and is the template.")
    D.callout("Prefer structure over identity.",
              "Adding a per-client anchor set does not generalise: the next client brings "
              "another layout. Every hour spent making the structural reader handle one "
              "more shape pays off on clients you have not met.", color=OK)

    D.h2("38. Known Gaps and Next Work")
    D.table(["Gap", "Detail", "Suggested approach"],
            [["Thyssen02 (37 pages)", "produces nothing; only ~55 OCR boxes at 0.70 confidence",
              "inspect the scans; likely a capture-quality problem, not a layout one"],
             ["Column-layout families (~21 pages)", "grid detected, statuses not read through it",
              "extend read_column_oriented to infer status from hours as aarvi_form does"],
             ["Designation accuracy 35.7%", "weakest field, though only 2.9% of comparisons",
              "widen the vocabulary; low priority against the grid"],
             ["Synchronous upload ingest", "browser can time out on very large batches",
              "move the split/queue step into the background worker (~1 day)"],
             ["Kolkata unmeasurable", "its Excels are invoice and summary sheets",
              "ground truth must be created before accuracy can be claimed"],
             ["No authentication", "unauthenticated by design for a private network",
              "reverse proxy with SSO before any internet exposure"]],
            caption="What is not finished, stated plainly.")

    D.h2("39. Reading the Research Log")
    D.p("The docs/ folder holds one document per investigation, numbered in "
        "the order the work happened. They are working notes rather than "
        "polished prose, and they record the measurements behind decisions "
        "summarised in this document.")
    D.table(["Document", "Subject"],
            [["03-page-routing", "the confidence thresholds and the gap they sit in"],
             ["04-ocr-engine-benchmark", "why RapidOCR over the alternatives"],
             ["06-accuracy-improvements", "the first systematic accuracy campaign"],
             ["09-real-accuracy", "correcting an earlier over-claim"],
             ["10-vlm-hybrid", "the VLM experiments and why it is off"],
             ["11-row-bands", "printed rules versus ink clustering"],
             ["12-columns-and-calendar", "column learning and calendar reconciliation"],
             ["13-designation", "the vocabulary and the regression panel"],
             ["16-corpus-expansion", "the three-dataset work and the Sunday refutation"]],
            caption="The research log. Read 16-corpus-expansion first for the most "
                    "recent state.")
