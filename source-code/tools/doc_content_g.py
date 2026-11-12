"""Documentation content, part G: appendices and closing (must run LAST)."""
from __future__ import annotations

from docx.shared import RGBColor

OK = RGBColor(0x2F, 0x85, 0x5A)
WARN = RGBColor(0xC0, 0x56, 0x21)


def write(D):
    # ========================================================== PART VII
    D.h1("Part XV — Appendices")
    D.h2("54. Glossary")
    D.table(["Term", "Meaning"],
            [["anchor", "a printed label on the form used to locate a value"],
             ["day grid", "the ruled table of up to 31 day rows"],
             ["row band", "the vertical extent of one day row"],
             ["p25", "the 25th percentile of OCR confidence — the weakest quarter"],
             ["route", "the decision between the confident and handwriting-tolerant paths"],
             ["reconciliation", "repairing the record from the sheet's own totals and the calendar"],
             ["escaped error", "a wrong value on a page that was NOT flagged — the metric that must be zero"],
             ["block / warn", "issue severities; a block forces needs_review"],
             ["ground truth", "the client's typed Excel, used as the answer key"],
             ["frozen inputs", "stored OCR output replayed by the fast harness"]])

    D.h2("55. Configuration Reference")
    D.table(["Variable", "Default", "Effect"],
            [["TS_PORT", "8077", "port the service listens on"],
             ["TS_DATA_DIR", "/data", "where all state is written"],
             ["TS_PAGE_LONG_EDGE", "1600", "portrait render size; measured optimum"],
             ["TS_LANDSCAPE_LONG_EDGE", "2600", "landscape render size for dense grids"],
             ["TS_HIRES_LONG_EDGE", "2600", "the rescue re-read resolution"],
             ["TS_MAX_DESKEW_DEG", "15", "maximum auto-straightening"],
             ["TS_ROSTER_MIN_SCORE", "82", "minimum name-match similarity"],
             ["TS_ROSTER_MIN_MARGIN", "6", "required gap over the second-best candidate"],
             ["TS_SUM_TOLERANCE_PCT", "0.02", "allowed drift between rows and stated totals"],
             ["TS_OT_MAX_DAY", "12", "maximum overtime hours per day"],
             ["TS_RESCUE_BUDGET_S", "45", "per-page ceiling on rescue work"],
             ["TS_VLM_HEADER", "0", "optional AI fallback; off by default"]],
            caption="Every tunable. Defaults are the measured values.")

    D.h2("56. File Map")
    D.table(["Path", "Role"],
            [["app/pipeline.py", "stage orchestration, caching, the rescue ladder"],
             ["app/aarvi_form.py", "anchors, columns, row bands, day-grid recovery (~1,700 lines)"],
             ["app/generic_grid.py", "layout-agnostic day-grid detection"],
             ["app/reconcile.py", "calendar and stated-total repair"],
             ["app/validate.py", "checks and severities"],
             ["app/ocr_engine.py", "RapidOCR wrapper, confidence profile, rule detection"],
             ["app/preprocess.py", "raster, deskew, flatten, resize"],
             ["app/roster.py", "identity matching"],
             ["app/export_designs.py", "the six workbook designs"],
             ["app/main.py", "HTTP API"],
             ["tools/eval_fast.py", "fast extraction harness"],
             ["tools/eval_corpus.py", "full three-dataset harness"],
             ["tools/truth.py", "ground-truth parser"],
             ["tools/verify_end_to_end.py", "system verification"],
             ["docs/", "research log, one document per investigation"]],
            caption="Where to look for what.")

    D.h1("Closing Note")
    D.p("The most useful thing in this document is not any single algorithm. "
        "It is the discipline the numbers came from: measure before believing, "
        "keep the rejections, and prefer a system that admits doubt over one "
        "that hides it.", bold=True)
    D.p("This product reads roughly nine in ten handwritten day entries "
        "correctly on familiar formats and fewer on formats it has not seen. "
        "It flags every page it gets wrong. Both halves of that sentence are "
        "measured, and both belong in any conversation with a client.")
