"""Documentation content, part I: Part XVII -- the 50-page sample, v33, and the
full corpus run of 20 Sep 2026. Every number is from docs/revamp/00-DECISION-LOG.md
(D-045..D-057) and docs/revamp/02-V33-CORPUS-RESULTS.md."""
from __future__ import annotations
import json
from pathlib import Path


def _kolkata_row():
    try:
        d = json.load(open(Path(__file__).resolve().parent.parent / "data" / "v33_final_summary.json"))
        k = d["full_pass"]["by"].get("Kolkata")
        if k and k.get("pages"):
            return ["Kolkata", str(k["pages"]), str(k.get("ok", 0)), str(k.get("review", 0)), str(k.get("must_fix", 0)), str(k.get("needs_review", 0))]
    except Exception:
        pass
    return ["Kolkata", "run separately (see 02-V33-CORPUS-RESULTS.md)", "", "", "", ""]


def write(D):
    D.h1("Part XVII — The 50-page sample, v33, and the full corpus run")
    D.p("Part XVI §64 graded seven pages by hand. Seven pages find defects; "
        "they do not give a number. This part records the number: a seeded, "
        "stratified 50-page sample graded row by row against the paper under "
        "a protocol written before grading began, the fixes it produced, and "
        "the corpus run made with the resulting pipeline (v33). Decisions "
        "D-045 to D-057.")

    D.h2("66. The protocol")
    D.p("Fifty pages were drawn by seed from the corpus index, stratified over "
        "Delhi, HO and Kolkata and over handwritten and typed, excluding every "
        "page ever used for tuning. The unit is one day row; truth is what is "
        "written on the paper, read by eye. A wrong row whose flag says 'ok' "
        "is counted as silent. Unsupported page types score as refused. No "
        "code was changed until all fifty were graded, and every later fix "
        "was re-scored on the same fifty pages by the same script "
        "(tools/eval_sample50.py) as well as on both frozen harnesses.")

    D.h2("67. What the sample measured")
    D.table(["Measure", "v32", "v33"],
            [["Readable day-grid pages (38) — rows right of 1,157", "1,075 = 92.9%", "1,106 = 95.6%"],
             ["Same, by the sheet's own convention for worked Sundays", "93.9%", "96.6%"],
             ["Silent wrong rows", "10", "8"],
             ["Missing rows", "10", "0"],
             ["Spurious 'day 31' rows", "7", "2"],
             ["Unsupported types refused and flagged", "10 of 10", "10 of 10"],
             ["Corrupt source PDFs (listed as skipped by the product)", "2", "2"]],
            caption="Per dataset at v32: Delhi handwritten 83.8%, Delhi typed 95.5%, HO 94.3/94.6, "
                    "Kolkata handwritten 94.5%, Kolkata typed 98.7%. The seven-page 98.4% of §64 was not representative.")

    D.h2("68. What the sample exposed, and the fix for each")
    D.table(["Pattern", "Where", "Fix (flag)", "Log"],
            [["Header VLM invented a person on pages with no name", "3 refused pages", "answers accepted only with support in the page's OCR text (VLM_CORROBORATE)", "D-046"],
             ["Last rows cut when a form has no summary block", "s26, 4 rows", "grid bottom from the date column (GRID_BOTTOM_FROM_DATES)", "D-046"],
             ["Empty 'day 31' in 30-day months", "7 pages", "dropped when empty, kept and flagged when inked (DROP_EMPTY_IMPOSSIBLE_DAYS)", "D-046"],
             ["'ok' rows on a page with no date column", "s23", "capped at review (NO_DATE_COLUMN_CAPS_OK)", "D-046"],
             ["Fitted ladder slid rows over clean printed rules", "s06, s17 — 4 silent", "clean rules win, gated by the calendar row count (CLEAN_RULES_BEAT_LADDER)", "D-047"],
             ["Shaded off-days with '0' hours read as empty (Samsung)", "s08, s09 — 14 rows", "zero hours on a form-labelled Sat/Sun ⇒ W (ZERO_HOURS_WEEKEND_IS_OFF)", "D-048"],
             ["Grid's own top/bottom rule outside the bound", "s49, s17", "one rule within a third of a pitch admitted (HEADER_RULE_TOLERANT)", "D-049"],
             ["No 'Date' header ⇒ 25% fallback cut rows", "s09", "raise-only header from the date column (HEADER_FROM_DATES)", "D-050"],
             ["Anchor consensus demanded unanimity", "typed sheets", "0.7 with an anchored-rows-on-calendar guard (ANCHOR_AGREE)", "D-051"],
             ["'Name: X' printed in one box fell to the VLM", "every GSPL page", "bare label read exactly, inline (BARE_INLINE_LABELS)", "D-054"],
             ["VLM spent on cover pages and attachments", "~40% of HO pages", "VLM only on pages with ≥8 day rows or a name label (VLM_NEEDS_SHEET)", "D-055"],
             ["Rotated page's header sent to the VLM unrotated", "PIL03 block", "the rotated copy is sent; crop capped at the measured width", "D-056, D-057"]],
            caption="Measured worse and withdrawn, all logged: replacing the header bound with the date column "
                    "(guard −25), capping the grid at the date column (−12), a rival-offset cap and an "
                    "all-rows-on-calendar guard (corpus set −7 / −47), a date-first row-count gate (−7).")
    D.p("Harnesses after v33: corpus-faithful set 1,293/1,456 = 88.8% strict, "
        "92.7% convention (v32: 87.2 / 91.1); handwritten guard 876/934 = "
        "93.8% (872); names 30/31. Two crash bugs the corpus run itself "
        "exposed were fixed before the full pass (D-052): the new VLM check "
        "read OCR boxes that do not exist on the cached path, and a circled "
        "digit in an hours cell passed str.isdigit() and broke int().")

    D.h2("69. The corpus run under v33")
    D.p("The eval checkpoint was discarded and every truth-matched page "
        "re-scored from scratch under v33. This number is bounded by the "
        "client's own conventions and self-contradicting truth rows (§62); it "
        "is not the per-row number against the paper.")
    D.table(["Dataset", "Matched pages", "Day rows right", "Day %", "v29"],
            [["Delhi", "282", "6,968 / 8,201", "85.0", "79.7"],
             ["HO", "10", "162 / 261", "62.1", "50.0"],
             ["Kolkata", "0", "no truth overlap", "—", "—"],
             ["Combined", "292", "7,130 / 8,462", "84.3", "78.8"]],
            caption="Name right on 98.3% of matched pages (96.7). Safety: 164 imperfect pages, 164 flagged, "
                    "0 escaped. On the 291 pages matched by both versions: v29 82.1% → v33 84.5%.")

    D.h2("70. Every page through the product")
    D.p("Each openable page of every PDF was run through the shipping "
        "pipeline with eight workers, checkpointed per page, zero worker "
        "errors. There is no truth for most of these pages; the table records "
        "what the reviewer will see.")
    D.table(["Dataset", "Pages", "ok rows", "review", "must-fix", "pages needs_review"],
            [["Delhi", "2,527", "46,170", "16,424", "8,717", "2,436"],
             ["HO", "5,261", "51,617", "24,921", "27,111", "5,089"],
             _kolkata_row()],
            caption="9,003 of 9,271 listed pages, 0 worker errors: 209,335 day rows = 56.3% ok / 24.7% review / "
                    "18.9% must-fix. The 268 listed pages not run sit in PDFs the renderer cannot open; the product "
                    "lists such files as skipped with the reason.")
    D.p("Why 92.7% of pages carry needs_review: the spec's first principle is "
        "that a timesheet must self-validate. On 18 of the 38 sample pages the "
        "'Total Man Hours' cell is blank on the paper or handwritten and "
        "unread, so the row-sum checksum cannot be applied and the page is "
        "held (summary_normal_missing); seven more have a genuine checksum "
        "mismatch. The row flags are what the reviewer works from.")

    D.h2("71. Throughput on the reference laptop")
    D.p("Delhi pages ran at 12 pages per minute with three workers. HO ran at "
        "3–5 until three causes were removed: forms printing 'Name: X' in one "
        "box (D-054), cover pages and attachments calling the VLM (D-055), "
        "and rotated pages sending the wrong crop (D-056/57). With eight "
        "workers, two OCR threads each and three parallel VLM slots, the "
        "HO/Kolkata mix ran at 8–12 pages per minute with the CPU saturated "
        "and the GPU saturated on VLM-heavy blocks. TS_WORKERS and "
        "TS_OCR_THREADS control this; OLLAMA_NUM_PARALLEL=3 on the VLM host.")

    D.h2("72. Recall")
    D.p("versions/v33-sample-fixes holds the complete app, tools, web, the "
        "sample protocol, grades and truth, and the v33 corpus eval, with a "
        "RECALL.md that restores it in one command. Deployment: "
        "dist/timesheet-app-v2.4.0-deployment.zip (arm64 + amd64, OCR models "
        "baked), built 20 Sep 2026 18:48 from this code.")
