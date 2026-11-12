"""The processing pipeline: one page in, a validated record out.

    PDF/image
       -> preprocess        deskew, flatten lighting, denoise, resize
       -> route             digital text / OCR-confident / needs escalation
       -> extract           anchors + learned columns -> structured record
       -> validate          checksums, bounds, roster
       -> status            clean | review_optional | needs_review

DESIGN RULE: NO PAGE MAY FALL THROUGH.
Every branch below terminates in a record plus a status. If a stage fails, the
page is marked for review with the reason attached -- it is never dropped and
never silently emitted as clean. That is what makes the system safe to put in
front of an invoice run: the output is not "everything we read correctly", it
is "everything, with the doubtful parts marked".

CACHING
-------
Results are keyed by the SHA-256 of the *normalised page image*, so the same
page re-uploaded after a correction, or arriving again in next month's batch,
is served from disk instead of re-running OCR. The client's whole cost
complaint came from a correction loop that re-billed them for work already
done; this is the structural fix for that.
"""
from __future__ import annotations

import calendar
import json
import re
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from . import aarvi_form, clocks, config, generic_grid, ocr_engine, rowconf
from . import preprocess as preprocess_mod
from .roster import Roster
from .templates_spec import get as get_template
from .validate import BLOCK, WARN, status_for, validate

# Bumped whenever extraction logic changes, which invalidates every cached
# result without deleting anything -- the old entries stay on disk and a
# rollback re-uses them instantly instead of re-reading 3,000 pages.
PIPELINE_VERSION = "v52-no-silent-employee-loss"
DROP_EMPTY_IMPOSSIBLE_DAYS = True   # D-046
VLM_NEEDS_SHEET = True              # D-055
CLEAN_PERIOD_LABEL = True           # D-059
HALF_HOUR_REPAIR = True             # D-060
GRID_MULTI_EMPLOYEE = True          # D-066: keep every employee on a shared page
GRID_FILL_BLANK_DAYS = True         # D-066: a blank cell is a day off, not a missing row
# D-072: MEASURED WORSE, OFF until the cause is found. The clock-grammar
# layer recovers damaged strings but also doubles the GENUINELY WRONG
# readings (19 -> 38 of 1,532), which is the worst trade available here: a
# wrong-but-plausible time does not get flagged, an unreadable one does.
#   long edge 1600:  off 1280/1532 = 83.6%   on 1269/1532 = 82.8%
#   long edge 2400:  off 1334/1532 = 87.1%   on 1318/1532 = 86.0%
CLOCK_REPAIR = False                # D-072
CLOCK_CONSENSUS = True              # only consulted when CLOCK_REPAIR is on
UNIT_SUFFIX_HOURS = True            # D-076: "10Hrs" is ten hours
SPLIT_CELL_IS_UNREADABLE = True     # D-076: "3 6" is two values, not 0.36
# "10Hrs", "8.5 hrs", "10 HR", "9hours" -- the unit as printed on the sheet.
_UNIT_SUFFIX_RE = re.compile(r"\s*(?:hrs?|hours?|h)\.?\s*$", re.I)

_DESIG_VOCAB = None

# Retry the other three orientations when a page yields no anchors at all.
# See the rescue block in process_page for the measurement that motivated it.
ORIENTATION_RETRY = True

# Read the day grid structurally when no known client profile matches. See the
# fallback block in process_page for the measurement behind it.
GRID_BEATS_WEAK_PROFILE = True   # D-090
UNREAD_ROW_BLOCKS_CLEAN = True   # D-091
GENERIC_GRID_FALLBACK = True

# Re-read at high resolution when a page yields no days at the normal size.
HIRES_RESCUE = True


def _grid_yield(boxes, page_w: int, page_h: int) -> int:
    """How many day cells the STRUCTURAL reader actually fills at this
    orientation -- not how many day columns it thinks it can see.

    D-085. Scoring a rotation on the size of the day axis was tried first and
    was wrong: on an Avaada sheet a 180-degree turn produced a LARGER axis out
    of spurious numbers and read nothing from it, beating the orientation that
    read 13 real days. An axis is a hypothesis; filled cells are evidence.
    """
    try:
        axis = generic_grid.find_day_axis(boxes, page_w, page_h)
        if axis is None:
            return 0
        blocks = (generic_grid.read_row_oriented(boxes, axis)
                  if axis.orientation == "row"
                  else generic_grid.read_column_oriented(boxes, axis))
        return sum(1 for b in blocks for d in (b.get("days") or [])
                   if (d.get("status") or "").strip())
    except Exception:                                           # noqa: BLE001
        return 0


def _rotated_copy(image_path: Path, degrees: int) -> Path:
    """A rotated copy of a normalised page, for the orientation rescue."""
    from PIL import Image
    out = image_path.with_name(f"{image_path.stem}__rot{degrees}.png")
    with Image.open(image_path) as im:
        im.rotate(degrees, expand=True).save(out)
    return out


def _cache_path(page_hash: str) -> Path:
    return config.CACHE_DIR / f"{page_hash[:32]}__{PIPELINE_VERSION}.json"


def cache_get(page_hash: str) -> dict | None:
    p = _cache_path(page_hash)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def cache_put(page_hash: str, value: dict) -> None:
    p = _cache_path(page_hash)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, default=str),
                   encoding="utf-8")
    tmp.replace(p)      # atomic: an interrupted run never leaves half a cache


def _page_size(image_path: Path) -> tuple[int, int]:
    img = cv2.imdecode(np.fromfile(str(image_path), dtype=np.uint8),
                       cv2.IMREAD_GRAYSCALE)
    if img is None:
        return 0, 0
    return img.shape[1], img.shape[0]


def process_page(image_path: str | Path, page_hash: str,
                 roster: Roster | None = None,
                 template_key: str | None = None,
                 force: bool = False,
                 source_hint: str | None = None) -> dict[str, Any]:
    """Run one page end to end. Always returns a record and a status."""
    image_path = Path(image_path)
    started = time.time()

    cached = None if force else cache_get(page_hash)
    if cached is not None:
        record = cached["record"]
        analysis = cached.get("analysis", {})
        from_cache = True
    else:
        from_cache = False
        try:
            page_w, page_h = _page_size(image_path)
            boxes = ocr_engine.run_ocr(image_path)
            profile = ocr_engine.confidence_profile(boxes)
            route = ocr_engine.route_from_profile(profile)
            # Printed horizontal rules, used to band the day grid when they
            # form a regular table. Pure morphology -- milliseconds, no model.
            try:
                row_rules = ocr_engine.detect_row_rules(image_path)
            except Exception:                                   # noqa: BLE001
                row_rules = []
            record = aarvi_form.extract(
                boxes, page_w, page_h,
                handwritten=(route == "needs_escalation"),
                row_rules=row_rules,
                source_hint=source_hint)

            # ---- rescue a sideways page ------------------------------
            #
            # preprocess deskews only within +-15 degrees, so a sheet scanned
            # at 90 degrees is never straightened. On such a page the header
            # band holds the wrong content, every learned column x-position is
            # meaningless, and extraction returns nothing at all.
            #
            # Measured on the HO dataset: 207 of 247 pages produced no
            # employee name, and every failing page sampled preferred a
            # NON-zero orientation, OCR mean confidence rising 0.73 -> 0.90 on
            # one and text volume up to +39%.
            #
            # Re-OCR at the other three orientations, keep whichever finds the
            # most anchors. Cost is paid ONLY by pages that already failed --
            # a page that found anchors upright never enters this branch, so
            # throughput on healthy pages is untouched.
            _rescue_t0 = time.time()

            def _budget_left() -> bool:
                return (time.time() - _rescue_t0) < config.RESCUE_BUDGET_S

            # Which rescue first? They fix different faults, and running the
            # wrong one first spends the whole budget for nothing.
            #
            # A page whose OCR found PLENTY of text at decent confidence is not
            # upside down -- it is under-resolved. Measured on SHELL04, the
            # SHELL layout printed portrait:
            #
            #     normal 1131x1600  180 boxes conf 0.72  -> no grid at all
            #     hires  1839x2600  556 boxes conf 0.95  -> 30 days, 6 blocks
            #
            # Whereas a page with very little text at poor confidence is the
            # signature of a sideways scan. Choosing on that signal means the
            # common case succeeds on the first attempt instead of the fourth.
            _looks_underresolved = (len(boxes) >= 80
                                    and float(profile.get("mean") or 0) >= 0.60)

            def _try_hires() -> None:
                nonlocal record, boxes, page_w, page_h
                if not (HIRES_RESCUE and not (record.get("days") or [])
                        and _budget_left()):
                    return
                hi = preprocess_mod.ensure_hires(image_path, source_hint)
                if hi is None or not hi.exists():
                    return
                try:
                    hboxes = ocr_engine.run_ocr(hi)
                    hprof = ocr_engine.confidence_profile(hboxes)
                    hw, hh = _page_size(hi)
                    hrec = aarvi_form.extract(
                        hboxes, hw, hh,
                        handwritten=(ocr_engine.route_from_profile(hprof)
                                     == "needs_escalation"),
                        row_rules=[], source_hint=source_hint)
                    gained = (len(hrec.get("days") or [])
                              > len(record.get("days") or [])
                              or (hrec.get("_anchors_found")
                                  and not record.get("_anchors_found")))
                    if gained:
                        record = hrec
                        record["_hires"] = True
                        boxes, page_w, page_h = hboxes, hw, hh
                    elif len(hboxes) > len(boxes):
                        # Even when the profile extractor gained nothing, the
                        # richer boxes are what the generic grid reader needs.
                        boxes, page_w, page_h = hboxes, hw, hh
                        record["_hires_boxes"] = True
                except Exception:                               # noqa: BLE001
                    pass

            if _looks_underresolved:
                _try_hires()

            # Gate on ZERO DAYS alone. The old gate also required "no anchors
            # found", which let a page through untouched whenever the header
            # read a name -- Avaada01 is a sideways three-employee grid that
            # yielded a name and no days, and never entered this branch. A
            # page with a name and no days is still a failed page.
            if ORIENTATION_RETRY and not (record.get("days") or []):
                _gd0 = _grid_yield(boxes, page_w, page_h)
                best = (len(record.get("_anchors_found") or []),
                        len(record.get("days") or []), _gd0, 0, record)
                for rot in (270, 90, 180):
                    if not _budget_left():
                        record["_rescue_truncated"] = True
                        break
                    try:
                        rp = _rotated_copy(image_path, rot)
                        rboxes = ocr_engine.run_ocr(rp)
                        rprof = ocr_engine.confidence_profile(rboxes)
                        rw, rh = _page_size(rp)
                        try:
                            rrules = ocr_engine.detect_row_rules(rp)
                        except Exception:                       # noqa: BLE001
                            rrules = []
                        rrec = aarvi_form.extract(
                            rboxes, rw, rh,
                            handwritten=(ocr_engine.route_from_profile(rprof)
                                         == "needs_escalation"),
                            row_rules=rrules, source_hint=source_hint)
                        # D-085. Score the orientation on the GENERIC GRID too,
                        # not only on what the profile extractor found.
                        #
                        # A sideways multi-employee grid returns zero anchors
                        # and zero days from aarvi_form at EVERY orientation,
                        # so nothing ever beat the upright original and the
                        # page was handed to the grid reader still sideways.
                        # Measured on a Thyssen Krupp sheet (37 pages fail this
                        # way): as scanned, find_day_axis returns None; rotated,
                        # it finds a 24-day axis. The right orientation was
                        # being produced and then thrown away.
                        #
                        # Third in the tuple, so it only decides when the first
                        # two are tied -- which is exactly the case where the
                        # profile extractor has nothing to say. The measure is
                        # cells actually READ, not columns detected; see
                        # _grid_yield for why that distinction matters.
                        _gd = _grid_yield(rboxes, rw, rh)
                        cand = (len(rrec.get("_anchors_found") or []),
                                len(rrec.get("days") or []), _gd, rot, rrec)
                        if cand[:3] > best[:3]:
                            best = cand
                            page_w, page_h, boxes = rw, rh, rboxes
                            profile, row_rules = rprof, rrules
                            route = ocr_engine.route_from_profile(rprof)
                    except Exception:                           # noqa: BLE001
                        continue
                if best[3]:
                    record = best[4]
                    record["_rotated"] = best[3]

            # If the page did not look under-resolved we skipped the
            # high-detail read above; try it now as the genuine last resort.
            if not _looks_underresolved:
                _try_hires()

            # ---- generic grid fallback -------------------------------
            #
            # The profile-based extractor knows three client layouts. When a
            # page matches none of them it returns nothing at all -- 207 of
            # 247 HO pages, across eleven client folders. Adding a fourth
            # anchor set does not generalise; the next client brings a fifth.
            #
            # So fall back on the one thing every timesheet must do: enumerate
            # its days. app/generic_grid finds that run of numbers and which
            # way it travels, which works on a layout nobody has seen before.
            #
            # Validated on a SHELL sheet that previously produced nothing:
            # name and all 30 days recovered, agreeing with the client's own
            # Excel on 26 of 26 comparable days.
            # D-090. The gate used to be "the profile extractor found NOTHING".
            # That let a weak profile result suppress a far stronger structural
            # one. Measured on a Brilliant Bio page: the profile extractor
            # returned 14 days with 5 cells filled, which closed this branch,
            # while the grid reader on the same boxes found 33 employee blocks
            # and 692 filled cells with real names on them. The better answer
            # was computed and thrown away because a worse one existed.
            #
            # So the branch now also opens when the grid reader does
            # DECISIVELY better -- at least twice as many filled day cells and
            # at least ten more. Both parts matter: the ratio stops a page that
            # is already read well from being re-litigated over one or two
            # cells, and the absolute floor stops a tiny difference on a nearly
            # empty page from qualifying. A page the profile extractor handles
            # properly is never touched, which is what keeps the known client
            # layouts exactly as measured.
            _prof_cells = sum(1 for _d in (record.get("days") or [])
                              if (_d.get("status") or "").strip())
            _grid_cells = (_grid_yield(boxes, page_w, page_h)
                           if GRID_BEATS_WEAK_PROFILE else 0)
            _grid_wins = (_grid_cells >= max(2 * _prof_cells, _prof_cells + 10))
            if GENERIC_GRID_FALLBACK and (not (record.get("days") or [])
                                          or _grid_wins):
                try:
                    axis = generic_grid.find_day_axis(boxes, page_w, page_h)
                    if axis is not None:
                        blocks = (generic_grid.read_row_oriented(boxes, axis)
                                  if axis.orientation == "row"
                                  else generic_grid.read_column_oriented(
                                      boxes, axis))
                        if blocks:
                            # D-066: a shared sheet lists several people. The
                            # page record still carries one of them -- the
                            # block with the most days -- and every other
                            # block becomes a page of its own further down,
                            # so nobody on the sheet is dropped. Measured
                            # before the change: 4 of 12 employees survived
                            # on the four ISGEC sheets, 246 days lost.
                            #
                            # The month is needed to tell a Sunday from an
                            # unexplained blank. These grids print it as
                            # "MONTH: April 2026" rather than under a label
                            # the header reader knows, so take it from any
                            # box on the page that parses as one.
                            if not record.get("period_label"):
                                from .reconcile import parse_period as _pp
                                for _b in boxes:
                                    _q = _pp(_b.text or "")
                                    if _q:
                                        record["period_label"] = (
                                            f"{calendar.month_abbr[_q[1]]} {_q[0]}")
                                        record["_period_raw"] = _b.text.strip()
                                        break
                            _per = None
                            try:
                                from .reconcile import parse_period as _pp2
                                _per = _pp2(record.get("period_label"))
                            except Exception:                   # noqa: BLE001
                                _per = None
                            if GRID_FILL_BLANK_DAYS and axis.days:
                                _all = sorted(axis.days)
                                for _blk in blocks:
                                    _blk["days"] = _fill_blank_days(
                                        _blk.get("days") or [], _all, _per)
                            blk = max(blocks, key=lambda b: len(b["days"]))
                            if blk["days"]:
                                record["days"] = blk["days"]
                                if GRID_MULTI_EMPLOYEE and len(blocks) > 1:
                                    record["_more_employees"] = [
                                        b for b in blocks
                                        if b is not blk and b.get("days")
                                        and b.get("employee_name")]
                                # Take the grid's name when there is none --
                                # and ALSO when the one already there is form
                                # furniture. On the SHELL sheets the anchor
                                # extractor confidently returns 'CONTRACTOR
                                # NAME:- AARVI ENCON LTD.', which is not empty,
                                # so an only-if-missing rule kept the garbage
                                # and threw away the real name.
                                if blk.get("employee_name") and (
                                        not record.get("employee_name")
                                        or generic_grid.looks_like_label(
                                            record.get("employee_name"))):
                                    record["employee_name"] = \
                                        blk["employee_name"]
                                if generic_grid.looks_like_label(
                                        record.get("employee_code")):
                                    record["employee_code"] = None
                                record["_generic_grid"] = axis.orientation
                                if len(blocks) > 1:
                                    record["_grid_blocks"] = len(blocks)
                except Exception:                               # noqa: BLE001
                    pass
            # A name that arrived with a section title welded to its tail is
            # still the right name -- trim rather than discard it.
            if record.get("employee_name"):
                record["employee_name"] = generic_grid.trim_trailing_label(
                    record["employee_name"])
            analysis = {
                "route": route,
                "row_rules": len(row_rules),
                "profile": profile,
                "n_boxes": len(boxes),
                "page_w": page_w,
                "page_h": page_h,
                "columns_found": record.get("_columns_found", []),
                "anchors_found": record.get("_anchors_found", []),
            }
            cache_put(page_hash, {"record": record, "analysis": analysis})
        except Exception as exc:                                # noqa: BLE001
            # Failure is a reviewable outcome, never a dropped page.
            return {
                "record": {"days": [], "summary": {}},
                "analysis": {"route": "error", "error": str(exc)},
                "issues": [{
                    "code": "pipeline_error", "severity": BLOCK,
                    "message": f"Processing failed: {exc}. Page needs manual entry.",
                    "field": None, "day": None, "expected": None, "found": None,
                }],
                "status": "needs_review",
                "from_cache": False,
                "ms": int((time.time() - started) * 1000),
            }

    # NOTE: month normalisation (app/vocab.normalise_month) was implemented and
    # MEASURED here, then reverted. It failed to rescue the case it was built
    # for ("Apsinl -2026" scored below the confidence floor) AND it destroyed a
    # legitimate two-month period, rewriting "June - July 26" as "June-2026".
    # Net effect 82.1% -> 79.5%. The module is kept and unit-tested; re-enable
    # only with range detection ("A - B" spanning two months) handled first.

    # ---- re-type header fields by CONTENT --------------------------------
    # Geometry cannot separate these on handwritten pages: values sit ~5 px
    # from the WRONG label and ~26 px from their own. But the values themselves
    # are unambiguous -- "APRIL-2026" is a month, "RAJEEV IYENGAR" is a name.
    from .field_typing import salvage_code, type_assign

    # Recover the code from a value it got glued to, BEFORE typing.
    #
    # type_assign classifies whole strings, so a contaminated code
    # ('Sayety Suyp. 54789') scores 0 as a code and is dropped -- with the
    # digits sitting right there. Measured on the frozen corpus: 13 of 24
    # extracted codes were contaminated this way, and no harness scored
    # employee_code, so all 13 were being lost silently.
    _code = salvage_code(record.get("employee_code"))
    if _code:
        record["employee_code"] = _code
    elif record.get("employee_code") and not any(
            ch.isdigit() for ch in str(record["employee_code"])):
        # Every real code in the roster contains a digit (measured: 0 of
        # 1,863 are letters-only). A digit-less "code" is form furniture that
        # fell into the box -- 'ATTENDANCE SHECT', 'AT ANNSET' -- and keeping
        # it poisons the identity match downstream. Blank beats junk: a blank
        # code lets the roster resolve identity from the name alone.
        record["employee_code"] = None

    typed = type_assign(
        {"month_year": record.get("period_label"),
         "employee_name": record.get("employee_name"),
         "designation": record.get("designation"),
         "employee_code": record.get("employee_code")},
        roster)
    if typed:
        claimed = {str(v).strip().upper() for v in typed.values() if v}
        for fld, key in (("month_year", "period_label"),
                         ("employee_name", "employee_name"),
                         ("designation", "designation"),
                         ("employee_code", "employee_code")):
            if typed.get(fld):
                record[key] = typed[fld]
            elif str(record.get(key) or "").strip().upper() in claimed:
                record[key] = None

    # ---- VLM fallback for a failed header --------------------------------
    # Only fires when the cheap path has clearly failed (no name, or a "name"
    # that is really a month). Measured: header crop scores 67% vs 30% for
    # whole-page VLM, at 24 s instead of 563 s. Its residual errors are
    # near-misses ('JACODISH SINGH') which the roster then resolves.
    if config.VLM_HEADER_FALLBACK:
        from . import vlm_header
        # D-055: spend the VLM only on a page that IS a timesheet -- a day
        # grid of >= 8 rows, or a printed name label whose value could not
        # be read. Cover pages, On-Duty forms and SAP printouts (1-6 rows, no
        # label) were costing ~45 s each on one GPU queue for a name that is
        # not on the page, and occasionally getting one invented.
        _is_sheet = (len(record.get("days") or []) >= 8
                     or "employee_name" in (record.get("_anchors_found") or []))
        if (not VLM_NEEDS_SHEET or _is_sheet) and \
                vlm_header.header_needs_help(record) and vlm_header.available():
            # D-057: a page the rescue ladder rotated has its header along
            # the side of the ORIGINAL image; the top-22% crop of that image
            # is not the header. Send the rotated copy the rescue wrote (the
            # PIL03 block: 159 s per call for nothing, no name on 40 of 60).
            _vlm_img = image_path
            if record.get("_rotated"):
                _rp = _rotated_copy(image_path, int(record["_rotated"]))
                if _rp.exists():
                    _vlm_img = _rp
            v = vlm_header.read_header(_vlm_img)
            if v:
                record["_vlm_header"] = v
                # D-046: accept each answer only if the page's OCR text
                # corroborates it; the VLM invents identities on pages
                # that carry none.
                # On the cached path there are no OCR boxes in scope: the
                # record itself is the page text we have (24 corpus pages
                # crashed here under v33 before this guard -- D-052).
                _texts = ([b.text for b in boxes] if "boxes" in locals()
                          else _record_texts(record))
                _ok = {k: vlm_header.corroborated(k, v.get(k), _texts)
                       for k in ("name", "code", "designation", "month")}
                v["_corroborated"] = _ok
                if v.get("name") and _ok["name"]:
                    record["employee_name"] = v["name"]
                if v.get("code") and _ok["code"] and not record.get("employee_code"):
                    record["employee_code"] = v["code"]
                if v.get("designation") and _ok["designation"] and not record.get("designation"):
                    record["designation"] = v["designation"]
                if v.get("month") and _ok["month"] and not record.get("period_label"):
                    record["period_label"] = v["month"]

    # ---- normalise designation against a closed vocabulary ---------------
    # Same mechanism that took employee_name to 96.4%: job titles are a small
    # closed set, so OCR only has to get close enough to identify which one.
    # The vocabulary is harvested from the corpus itself (tools/build_
    # designations.py) plus titles verified by reading the scans directly.
    from .vocab import Vocabulary
    global _DESIG_VOCAB
    if _DESIG_VOCAB is None:
        _DESIG_VOCAB = Vocabulary.from_csv(
            config.DATA_DIR / "designations.csv", "designation")
    if record.get("designation") and not _DESIG_VOCAB.empty:
        fixed, score = _DESIG_VOCAB.normalise(record["designation"])
        if fixed:
            record["_original_designation"] = record["designation"]
            record["designation"] = fixed

    # ---- resolve identity against the roster ----------------------------
    record = apply_roster(record, roster)

    # ---- D-059: a garbled period label reads as a month; show the month ----
    # "Pemensdo Corporate Pare ... May·26 KLENT Siemens Ltd" parses to May 2026
    # (that is what drives the calendar) but is what the reviewer saw. Keep the
    # raw text for audit; show the canonical month when the label is long.
    _pl = str(record.get("period_label") or "")
    if CLEAN_PERIOD_LABEL and len(_pl) > 24:
        from .reconcile import parse_period as _pp_
        _q = _pp_(_pl)
        if _q:
            record["_period_raw"] = _pl
            record["period_label"] = f"{calendar.month_abbr[_q[1]]} {_q[0]}"

    # ---- reject IMPOSSIBLE stated day-counts ------------------------------
    # A stated total of day-type units cannot exceed the days in the month:
    # 'P 97' on a 30-day sheet and 'C/O 170' are misreads, full stop
    # (measured: 9<->2 and a stray digit, both on real pages). An impossible
    # value must not drive checksums or reconciliation, and printing it in
    # the export as "what the sheet states" would be false. Treated exactly
    # like an unreadable cell: blanked, with the original kept for audit.
    from .reconcile import parse_period, infer_period_from_grid
    _p = parse_period(record.get("period_label")) \
        or infer_period_from_grid(record.get("period_label"),
                                  record.get("days") or [])
    _month_len = calendar.monthrange(*_p)[1] if _p else 31
    # D-046: a form's empty trailing row below day 30 was emitted as "day 31"
    # on 7 of 38 readable sample pages (always must_fix, always noise for the
    # reviewer). A day the calendar does not have, with nothing written in
    # it, is not a row. Only EMPTY impossible days are dropped: an inked one
    # stays and stays flagged, because then the month may be what is wrong.
    if DROP_EMPTY_IMPOSSIBLE_DAYS and _p:
        _keep, _dropped = [], []
        for _d in (record.get("days") or []):
            try:
                _dn = int(_d.get("day"))
            except (TypeError, ValueError):
                _dn = None
            _blank = not any(_d.get(k) for k in
                             ("status", "in_time", "out_time", "normal_hours",
                              "ot_hours", "total_hours", "remarks"))
            if _dn is not None and _dn > _month_len and _blank:
                _dropped.append(_dn)
            else:
                _keep.append(_d)
        if _dropped:
            record["days"] = _keep
            record["_dropped_impossible_days"] = _dropped
    _summ = record.get("summary") or {}
    for _k in ("total_present_days", "total_absent_days", "total_leave_days",
               "total_weekly_off", "total_public_holiday", "total_comp_off"):
        _m = re.search(r"\d+(?:\.\d+)?", str(_summ.get(_k) or ""))
        if _m and float(_m.group()) > _month_len:
            record.setdefault("_implausible", {})[_k] = _summ[_k]
            _summ[_k] = None
    # A fractional present-days total ('2.5' where the grid holds 25 P rows)
    # is a phantom decimal point, not half a day: nobody bills half-days on
    # these forms, and the digits with the dot removed equal what the grid
    # itself counts. Only that exact agreement licenses the repair.
    _p_stated = str(_summ.get("total_present_days") or "")
    if "." in _p_stated:
        _digits = re.sub(r"\D", "", _p_stated)
        _grid_p = sum(1 for d in (record.get("days") or [])
                      if str(d.get("status") or "").upper() == "P")
        if _digits and _grid_p and int(_digits) == _grid_p:
            record.setdefault("_implausible", {})["total_present_days"] = \
                _p_stated
            _summ["total_present_days"] = _digits

    # Same bound for hour totals: a month holds at most 24h x its days.
    # 'Total OT 1120' on a 31-day sheet (max 744) is a misread, not overtime.
    for _k in ("total_man_hours", "total_ot_hours", "total_normal_hours"):
        _m = re.search(r"\d+(?:\.\d+)?", str(_summ.get(_k) or ""))
        if _m and float(_m.group()) > 24 * _month_len:
            record.setdefault("_implausible", {})[_k] = _summ[_k]
            _summ[_k] = None

    # D-072: in/out times are read back through the clock grammar before
    # anything downstream sees them. Measured at 83.4% correct without this
    # (data/testsets/clock-times, truth from the sheets' own text layer); the
    # failures were overwhelmingly damaged strings rather than wrong readings,
    # which is the class a grammar can recover. A cell that still will not
    # parse is left as None and flagged -- never guessed at.
    if CLOCK_REPAIR:
        _fix = clocks.apply_to_days(record.get("days") or [],
                                    consensus=CLOCK_CONSENSUS)
        if _fix:
            record["_clock_fix"] = _fix

    # D-084: the biggest, highest piece of text on the page. Used only to tell
    # a reviewer what a page IS when we cannot say who it belongs to -- it is
    # never treated as data.
    #
    # D-092: ONLY on the fresh-extraction path. `boxes` does not exist on a
    # cache hit, and calling this there raised UnboundLocalError and failed
    # the whole page. The cached record already carries the heading from the
    # run that wrote it, so there is nothing to recompute. This repeats a
    # defect the log already records once (the VLM corroboration crashed the
    # same way on the same path) -- the cached branch rejoins the common code
    # with a DIFFERENT set of locals defined, and anything added to the common
    # path has to be checked against that.
    if not from_cache:
        record["_page_heading"] = _page_heading(boxes)

    if _is_status_only(record.get("days") or []):
        record["_status_only"] = True

    # D-066: these grids carry no totals box, so the export had nothing to put
    # in the payroll row. Count the day types from the rows and keep them in a
    # SEPARATE field: `summary` means "what the sheet states" and the checksums
    # compare the two, so writing counts there would make every check pass
    # against itself. The export labels these as counted, and the page still
    # goes out as HOLD for a human to confirm.
    if not any((record.get("summary") or {}).values()):
        _cnt = _count_day_types(record.get("days") or [])
        if _cnt:
            record["_counted"] = _cnt

    # ---- normalise the record into the validator's shape ----------------
    spec = get_template(template_key)
    norm = _to_validator_shape(record)
    issues = validate(norm, spec, roster=roster, disagreements=None)
    issues += _confidence_issues(record, analysis)
    # Post-OCR evaluation layer: every day row gets a confidence score and an
    # ok / review / must_fix flag with named reasons (app/rowconf.py). Runs
    # after validation so day-level issues feed the score.
    rowconf.annotate(record, issues)

    more: list[dict] = []
    if GRID_MULTI_EMPLOYEE:
        for blk in record.get("_more_employees") or []:
            try:
                more.append(_finalise_block(record, blk, roster, template_key))
            except Exception as exc:                            # noqa: BLE001
                # D-094. This used to `pass`. On a shared sheet listing 33
                # people, one block failing to finalise removed that PERSON
                # from the output with no issue, no log and no trace -- the
                # exact silent-loss failure the whole design exists to
                # prevent, and the only one that cannot be caught by any
                # checksum because the row simply is not there to check.
                #
                # The page now says so, and says so as a BLOCK, because a
                # sheet that has quietly lost an employee must not be
                # exported as complete.
                issues.append({
                    "code": "employee_block_failed", "severity": BLOCK,
                    "message": (
                        f"This sheet lists more than one person, and one of them "
                        f"({blk.get('employee_name') or 'name unread'}) could not be "
                        f"processed ({type(exc).__name__}). That person is MISSING "
                        f"from this page's output and must be entered by hand."),
                    "field": "employee_name", "day": None,
                    "expected": None, "found": None})
                record.setdefault("_dropped_employees", []).append(
                    {"name": blk.get("employee_name"), "error": f"{type(exc).__name__}: {exc}"[:160]})

    return {
        "record": record,
        "normalised": norm,
        "analysis": analysis,
        "issues": issues,
        "status": _page_status(issues, record),
        "from_cache": from_cache,
        "ms": int((time.time() - started) * 1000),
        "more": more,
    }


def _fill_blank_days(days: list[dict], all_days: list[int],
                     period: tuple[int, int] | None) -> list[dict]:
    """Day columns this person has no cell in.

    On a multi-employee grid an empty cell is not a missing reading: it means
    the person did not work that day. Where the calendar says the column is a
    Sunday, that is the weekly off and is recorded as one. A blank on any
    other day has no explanation on the paper, so the row is emitted with no
    status and the confidence layer flags it for a human -- the same
    treatment any unreadable row gets, rather than a guess.
    """
    have = {d.get("day") for d in days}
    out = list(days)
    for dn in all_days:
        if dn in have:
            continue
        st = None
        if period:
            try:
                if calendar.weekday(period[0], period[1], dn) == 6:
                    st = "W"
            except ValueError:                                  # day outside the month
                continue
        out.append({"day": dn, "status": st, "in_time": None, "out_time": None,
                    "normal_hours": None, "ot_hours": None, "total_hours": None,
                    "remarks": None, "_blank_cell": True})
    return sorted(out, key=lambda d: d.get("day") or 0)


def _count_day_types(days: list[dict]) -> dict[str, int] | None:
    """How many of each day type the rows themselves show.

    Kept apart from `summary`, which means "what the sheet states": the
    checksums compare the two, so counts written into `summary` would make
    every check pass against itself.
    """
    c: dict[str, int] = {}
    for d in days or []:
        st = str(d.get("status") or "").strip().upper()
        if st:
            c[st] = c.get(st, 0) + 1
    if not c:
        return None
    return {"total_present_days": c.get("P", 0), "total_absent_days": c.get("A", 0),
            "total_leave_days": c.get("L", 0), "total_weekly_off": c.get("W", 0),
            "total_public_holiday": c.get("H", 0), "total_comp_off": c.get("C", 0)}


def _page_status(issues: list, record: dict) -> str:
    """Page status, with one rule the issue list cannot express.

    D-091. A row the confidence layer calls `must_fix` -- most often a day
    whose status could not be read AT ALL -- did not stop the page being
    called clean, because page status came only from the validation issues and
    an unread cell breaks no arithmetic.

    Found on a Garden Reach page passed as CLEAN with 29 of 31 days right. The
    paper says `SUN` on the 17th and `09:00 / 17:30` on the 27th; we read
    neither, and the remaining counts still reconciled with the sheet's own
    totals, so nothing objected. It was the only genuine escape among six --
    the other five were pages where our reading matched the paper and the
    client's spreadsheet did not.

    A page with a cell nobody could read has not been fully read, and must not
    be advertised as confirmed. Same principle as D-078: `clean` means checked
    and reconciled, never merely unobjected-to.
    """
    st = status_for(issues)
    if UNREAD_ROW_BLOCKS_CLEAN and st == "clean":
        for d in record.get("days") or []:
            if d.get("_review") == "must_fix":
                return "review_optional"
    return st


def _page_heading(boxes) -> str | None:
    """The page's own title: the largest text in the top eighth of the sheet.

    Area, not font size, because OCR gives us boxes rather than typography, and
    a title is wide as well as tall. Nothing downstream parses this -- it is
    quoted back to a human verbatim, so a misread costs nothing.
    """
    if not boxes:
        return None
    try:
        bottom = max(b.y1 for b in boxes)
        head = [b for b in boxes
                if b.cy < bottom * 0.12 and len(str(b.text).strip()) >= 6]
        if not head:
            return None
        # The biggest text at the top of an AARVI sheet is the letterhead --
        # the Mumbai office address -- on every one of these forms. Quoting
        # that back tells a reviewer nothing and makes the message longer, so
        # furniture is skipped and the next-largest line is taken instead.
        # Measured on eight layouts: three were showing the address.
        from .aarvi_form import _is_form_furniture
        for b in sorted(head, key=lambda b: -((b.x1 - b.x0) * (b.y1 - b.y0))):
            try:
                if _is_form_furniture(b):
                    continue
            except Exception:                                   # noqa: BLE001
                pass
            t = str(b.text).strip()[:90]
            if t:
                return t
        return None
    except Exception:                                           # noqa: BLE001
        return None


def _is_status_only(days: list[dict]) -> bool:
    """True when the sheet records a letter per day and nothing else.

    These grids have no in/out or hours columns at all, so 'present but no
    hours recorded' is not a defect -- it is the format. Without this the
    confidence layer paints a perfectly-read page almost entirely red.
    """
    if not days:
        return False
    return not any(d.get(k) for d in days
                   for k in ("in_time", "out_time", "normal_hours",
                             "ot_hours", "total_hours"))


def _finalise_block(primary: dict, block: dict, roster: Roster | None,
                    template_key: str) -> dict:
    """Make one extra employee from a shared page into a page of its own.

    Same validation and row scoring as any other page; it simply inherits the
    header fields that belong to the sheet rather than to the person.
    """
    rec: dict[str, Any] = {
        "employee_name": block.get("employee_name"),
        "employee_code": None,
        "designation": None,
        "project": primary.get("project"),
        "client": primary.get("client"),
        "location": primary.get("location"),
        "period_label": primary.get("period_label"),
        "days": block.get("days") or [],
        "summary": {},
        "_confidence": {},
        "_columns_found": primary.get("_columns_found"),
        "_anchors_found": primary.get("_anchors_found"),
        "_profile": primary.get("_profile"),
        "_generic_grid": primary.get("_generic_grid"),
        "_grid_blocks": primary.get("_grid_blocks"),
        "_shared_page": True,
    }
    if primary.get("_status_only"):
        rec["_status_only"] = True
    cnt = _count_day_types(rec["days"])
    if cnt:
        rec["_counted"] = cnt
    if rec["employee_name"]:
        rec["employee_name"] = generic_grid.trim_trailing_label(rec["employee_name"])
    rec = apply_roster(rec, roster)
    spec = get_template(template_key)
    norm = _to_validator_shape(rec)
    issues = validate(norm, spec, roster=roster, disagreements=None)
    rowconf.annotate(rec, issues)
    return {"record": rec, "normalised": norm, "analysis": {"route": "shared_page"},
            "issues": issues, "status": status_for(issues), "from_cache": False, "ms": 0}


def _record_texts(record: dict) -> list[str]:
    """Every string the record carries, for corroborating a VLM answer when
    the OCR boxes are not available (cached record)."""
    out: list[str] = []
    for k, v in record.items():
        if k.startswith("_") or k == "days":
            continue
        if isinstance(v, str):
            out.append(v)
        elif isinstance(v, dict):
            out.extend(str(x) for x in v.values() if isinstance(x, str))
    for d in record.get("days") or []:
        out.extend(str(x) for x in d.values() if isinstance(x, str))
    return out


def apply_roster(record: dict, roster: Roster | None) -> dict:
    """Resolve the employee against the master roster and CORRECT the record.

    This is the single largest accuracy gain in the system, and it works
    because names are not free text -- they come from a closed set of ~1,900
    known people. We therefore do not need OCR to *read* the name correctly,
    only to get close enough to identify which person it is.

    Measured on real handwritten misreads:
        "Shiv Shankan"          -> Lokesh Khurana        (91.7)
        "Jitendna Singh"        -> Naveen Trivedi      (92.9)
        "Balder Singh Rajpur"   -> Vikram Prasad Sethi (89.5)
        "DANDE BIANU PRAKASHI"  -> Anil Lal Rathore (via exact code)

    SAFETY RULE: we only overwrite on an unambiguous match. A near-tie between
    two roster entries is left alone and flagged instead, because silently
    attributing a page to the WRONG employee is the invoice-freezing error --
    far worse than asking a reviewer to pick from a shortlist.
    """
    if roster is None or roster.empty:
        return record

    name = (record.get("employee_name") or "").strip()
    code = (record.get("employee_code") or "").strip()
    if not name and not code:
        return record

    m = roster.match(name=name, code=code)
    record["_roster"] = {
        "status": m.status,
        "matched_name": m.roster_name,
        "matched_code": m.roster_code,
        "score": m.name_score,
        "candidates": m.candidates,
    }

    # exact_code  -- the code was found verbatim in the roster.
    # strong_name -- one clear winner, well clear of the runner-up.
    # Anything else (ambiguous / none) is deliberately NOT auto-corrected.
    if m.status in ("exact_code", "strong_name") and m.roster_name:
        if m.roster_name.upper() != name.upper():
            record["_original_name"] = record.get("employee_name")
            record["employee_name"] = m.roster_name

        # NEVER overwrite a code we actually read off the page.
        #
        # Measured failure: ADANI02's code 9100955164 was extracted correctly,
        # then clobbered to "ISL900" because a same-named employee exists at a
        # different client. Personal names are not unique across a 1,900-person
        # roster spanning 34 clients, so a name match is not evidence about the
        # code. We therefore only FILL IN a missing code, never replace one.
        # Only an EXACT CODE match may supply a code. A name match is not
        # evidence about the code: the same person appears under different
        # codes at different clients (measured -- "Lokesh Khurana" resolved to
        # IOCLMS901 while this page's own code was 54788). Filling from a name
        # match manufactures a plausible, wrong identifier, which is worse than
        # leaving it blank for a reviewer.
        if m.roster_code and not code and m.status == "exact_code":
            record["_original_code"] = None
            record["employee_code"] = m.roster_code
    return record


_HHMM_RE = re.compile(r"^(\d{1,2})[:.](\d{2})$")


def normalise_hours(v: Any) -> Any:
    """Repair hour values that OCR mangled, before validation sees them.

    Measured failures on real ADANI pages:
      "10:00" -> "1000"   the colon is thin and OCR frequently drops it
      "0.42"  -> "42"     a leading "0." is lost the same way

    Without this repair the bounds check fires on every single row
    ("normal hours 1000.0 is outside 0-12"), burying the ONE genuine issue on
    the page in twenty false ones -- which is exactly the "reviewing it takes as
    long as doing it" failure the client already complained about. A validation
    engine that cries wolf is worse than none.

    We only reinterpret values that cannot possibly be literal hour counts, so
    a real 8 stays 8 and a real 10.5 stays 10.5.
    """
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None

    # D-076: the unit is printed in the cell on some layouts. Every hours cell
    # on the ADANI sheets reads "10Hrs", which parsed as nothing at all, so the
    # whole column summed to 0 and three separate checksums reported the entire
    # stated total as a discrepancy -- on pages where every day was correct.
    if UNIT_SUFFIX_HOURS:
        s = _UNIT_SUFFIX_RE.sub("", s).strip() or s

    m = _HHMM_RE.match(s)
    if m:                                   # "10:00" / "10.00" -> 10.0
        h, mm = int(m.group(1)), int(m.group(2))
        if 0 <= h <= 23 and 0 <= mm < 60:
            return round(h + mm / 60.0, 4)

    # D-076: two numbers in one cell means the row boundary failed and this
    # cell holds a neighbour's value too. Stripping the space merged them --
    # "3 6" became "36", which the dropped-decimal rule then read as 0.36, a
    # plausible-looking number that is on no sheet anywhere. Refuse to read it
    # instead; rowconf already flags a crowded cell (D-074), so the row goes to
    # a human rather than carrying an invented figure into a total.
    if SPLIT_CELL_IS_UNREADABLE:
        parts = [p for p in re.split(r"\s+", s) if p]
        if len(parts) > 1 and sum(bool(re.fullmatch(r"\d{1,2}(?:\.\d+)?", p))
                                  for p in parts) > 1:
            return None

    digits = s.replace(" ", "")
    # ASCII digits only: str.isdigit() is True for "③" and int() then raises
    # (measured: one v33 corpus page crashed on '③2' in an hours cell).
    if digits.isascii() and digits.isdigit():
        n = int(digits)
        # 4 digits in an hours column is HHMM with a dropped separator.
        if len(digits) == 4 and n > 100:
            h, mm = n // 100, n % 100
            if 0 <= h <= 23 and 0 <= mm < 60:
                return round(h + mm / 60.0, 4)
        # A bare 2-digit number above the day-length ceiling is a dropped
        # decimal point. Which one? "85" is "8.5" (19 rows of it on a
        # Siemens sheet whose total is 161.5 = 19 x 8.5), "42" is "0.42".
        # A first digit that is a plausible whole day (1-12) with a second
        # digit 0/5 is H.M -- the half-hour convention every one of these
        # forms uses; anything else keeps the old "0." reading. D-060.
        if len(digits) == 2 and n > 24:
            if HALF_HOUR_REPAIR and 1 <= n // 10 <= 12 and n % 10 in (0, 5):
                return round(n // 10 + (n % 10) / 10.0, 4)
            return round(n / 100.0, 4)
    try:
        f = float(s)
    except ValueError:
        return v
    # Beyond every repair above, a value of 100+ hours in a DAY cell is not a
    # number a person writes in an hours box -- it is several columns' digits
    # merged into one OCR read ('81125', '121425', measured on a real page,
    # five block-level issues from one column smear). Unreadable beats junk:
    # None here silences the false out-of-band/mismatch cascade while the
    # genuinely-human miswrites the bounds check exists for (a 42-hour day)
    # stay below 100 and keep flagging.
    if f >= 100:
        return None
    return f


def _to_validator_shape(record: dict) -> dict:
    """Map the AARVI record onto the generic schema validate.py expects.

    Kept as an explicit translation rather than making the validator understand
    every template: the validator encodes the *business rules*, which are the
    same for every client, and should not accumulate per-layout branches.
    """
    s = record.get("summary") or {}
    return {
        "employee_name": record.get("employee_name"),
        "page_heading": record.get("_page_heading"),
        "employee_code": record.get("employee_code"),
        "project": record.get("project"),
        "period_start": record.get("period_label"),
        "period_end": None,
        "days": [
            {
                "day": d.get("day"),
                "status": d.get("status"),
                "in_time": d.get("in_time"),
                "out_time": d.get("out_time"),
                "normal_hours": normalise_hours(d.get("normal_hours")),
                "ot_hours": normalise_hours(d.get("ot_hours")),
            }
            for d in record.get("days", [])
        ],
        "summary": {
            "total_normal_hours": s.get("total_man_hours"),
            "total_ot_hours": s.get("total_ot_hours"),
            "total_present_days": s.get("total_present_days"),
            "total_leave_days": s.get("total_leave_days"),
            "mandays": s.get("total_present_days"),
            "man_hours": s.get("total_man_hours"),
        },
    }


LOW_CONF = 0.80


def _confidence_issues(record: dict, analysis: dict) -> list[dict]:
    """Turn OCR uncertainty into reviewable issues.

    This is the honest substitute for a model claiming per-field confidence.
    The number here is the recogniser's own score for the pixels it read, which
    is a measured quantity rather than a generated one.
    """
    out: list[dict] = []
    route = analysis.get("route")
    if route == "needs_escalation":
        prof = analysis.get("profile", {})
        out.append({
            "code": "low_ocr_confidence", "severity": WARN,
            "message": (
                f"This page reads as handwritten (weakest-quarter confidence "
                f"{prof.get('p25', 0):.2f}, {prof.get('frac_low', 0):.0%} of text "
                f"below 0.80). Values should be spot-checked against the image."),
            "field": None, "day": None, "expected": None, "found": None,
        })
    elif route == "unreadable":
        out.append({
            "code": "no_text_found", "severity": BLOCK,
            "message": "No text could be read from this page at all. "
                       "Check the scan quality or re-photograph the sheet.",
            "field": None, "day": None, "expected": None, "found": None,
        })

    for fieldname, conf in (record.get("_confidence") or {}).items():
        try:
            c = float(conf)
        except (TypeError, ValueError):
            continue
        if 0 < c < LOW_CONF:
            out.append({
                "code": "low_field_confidence", "severity": WARN,
                "message": f"'{fieldname}' was read with low confidence ({c:.2f}).",
                "field": fieldname, "day": None, "expected": None, "found": None,
            })

    missing_anchor = [a.field for a in aarvi_form.SUMMARY_ANCHORS
                      if a.field not in (record.get("_anchors_found") or [])]
    if len(missing_anchor) >= 6:
        out.append({
            "code": "summary_block_not_found", "severity": BLOCK,
            "message": ("The totals block could not be located on this page, so "
                        "the arithmetic cross-checks could not run. Verify "
                        "manually."),
            "field": "summary", "day": None, "expected": None, "found": None,
        })
    return out
