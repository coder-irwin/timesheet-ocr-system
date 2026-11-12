"""Per-row confidence and review flags: the post-OCR evaluation layer.

Every day row gets a score in [0, 1] and a flag:

    ok        the row's own evidence is consistent and was read, not inferred
    review    something about the row is weak or was inferred; a human should
              glance at it
    must_fix  the row is empty, contradicts itself, or a validation issue
              names it; it should not reach an invoice as-is

The score is not a probability. It is a ranking signal built from what the
pipeline already knows about the row, so a reviewer can sort the doubtful
rows to the top instead of reading thirty. Every deduction is named in
`reasons`, so the flag is explainable, never a bare number.

Signals, in order of weight:
  - status missing / empty                       -> must_fix
  - a validation issue that names this day       -> must_fix
  - status contradicts the row's own evidence    -> must_fix
        P with no clock and no hours; W/A/L/H with recorded hours
  - status was inferred, not read (_inferred)    -> review
  - low OCR confidence on the cells that matter  -> review (graded)
  - the row was moved/snapped by reconcile       -> review
"""
from __future__ import annotations

import re
from typing import Any

# Cells whose OCR confidence bears on the status.
_STATUS_CELLS = ("in_time", "out_time", "normal_hours", "total_hours",
                 "remarks")

_CLOCK = re.compile(r"\d{1,2}\s*[:.]\s*\d{2}")


def _has_work(d: dict[str, Any]) -> bool:
    for k in ("in_time", "out_time", "normal_hours", "total_hours"):
        v = str(d.get(k) or "").strip()
        if not v or not any(c.isdigit() for c in v):
            continue
        m = re.search(r"\d+(?:[.:]\d+)?", v.replace(",", ""))
        if m:
            try:
                if float(m.group(0).replace(":", ".")) > 0:
                    return True
            except ValueError:
                pass
    return False


NO_DATE_COLUMN_CAPS_OK = True   # D-046
CROWDED_CELL_REVIEW = True      # D-074
DRIFT_WINDOW = 2                # D-074: rows past a merged cell that stay suspect


def _crowded_cells(d: dict[str, Any]) -> list[str]:
    """Cells holding more than one row's value -- the row boundary did not hold.

    D-074. On dense layouts (the Samsung sheets, which print two project codes
    per day) the row segmentation sometimes merges neighbours, and a single
    cell comes back as '4 4 4' or '17:00 2.SW7370 1. SW7318'. The damage is not
    in that cell: once rows merge, every day BELOW is read off the wrong row,
    so the statuses silently slide by one against the calendar. That is the
    worst failure this product has, because a plausible P on the wrong day is
    not arithmetically detectable -- the month still adds up.

    We cannot reliably un-merge the rows here. We can refuse to call such a row
    confident, which turns a silent error into a flagged one.
    """
    out: list[str] = []
    for k in ("in_time", "out_time"):
        v = str(d.get(k) or "").strip()
        if v and len(_CLOCK.findall(v)) > 1:
            out.append(k)
    for k in ("normal_hours", "ot_hours", "total_hours"):
        v = str(d.get(k) or "").strip()
        if v and len(re.findall(r"\d+(?:\.\d+)?", v)) > 1:
            out.append(k)
    return out


def score_row(d: dict[str, Any],
              day_issues: list[dict[str, Any]] | None = None,
              status_only: bool = False
              ) -> tuple[float, str, list[str]]:
    """(score, flag, reasons) for one day row."""
    reasons: list[str] = []
    score = 1.0
    st = (d.get("status") or "").strip().upper()
    issues = day_issues or []

    # 1. hard failures
    if not st:
        reasons.append("could not tell if this day was worked, off or leave")
        return 0.0, "must_fix", reasons
    blocking = [i for i in issues if (i.get("severity") or "") == "block"]
    if blocking:
        reasons.append("check: " + "; ".join(
            str(i.get("message") or i.get("code") or "issue")[:60]
            for i in blocking[:2]))
        score = min(score, 0.2)
    work = _has_work(d)
    # On a sheet that records only a letter per day there are no clock
    # columns, so "present with no hours" is the format, not a fault (D-066).
    if st == "P" and not work and not status_only:
        reasons.append("marked present but no times or hours written")
        score = min(score, 0.25)
    if st in ("W", "A", "L", "H") and work:
        reasons.append(f"marked {st} (a day off) but hours are written")
        score = min(score, 0.3)

    # 2. soft signals
    # D-072: a clock cell the grammar could not resolve is reported, never
    # silently blanked. A time the sheet's other rows had to vouch for is
    # reported too -- it is probably right, but the reviewer is told it was
    # not read cleanly off this row.
    tfix = d.get("_time_fix") or {}
    unread = sorted(k.replace("_time", "-time").replace("_", " ")
                    for k, v in tfix.items() if v.get("to") is None)
    if unread:
        reasons.append(f"the {' and '.join(unread)} on this row could not be read")
        score = min(score, 0.5)
    if any(v.get("why") == "matched_the_rest_of_the_sheet" for v in tfix.values()):
        reasons.append("a time here was unclear and was taken from the rest of the sheet")
        score = min(score, 0.7)

    if CROWDED_CELL_REVIEW and _crowded_cells(d):
        reasons.append("two days' worth of writing landed in one box here, "
                       "so this row and the ones below it may be out of step")
        score = min(score, 0.5)

    inf = d.get("_inferred")
    if inf:
        reasons.append("worked out from the sheet's totals: " + str(inf)[:70])
        score = min(score, 0.6)
    warn = [i for i in issues if (i.get("severity") or "") != "block"]
    if warn:
        reasons.append("check: " + str(warn[0].get("message") or "")[:60])
        score = min(score, 0.7)

    conf = d.get("_conf") or {}
    vals = [float(conf[k]) for k in _STATUS_CELLS
            if k in conf and conf[k] is not None]
    if vals:
        lo = min(vals)
        if lo < 0.60:
            reasons.append("the handwriting here was hard to read")
            score = min(score, 0.45)
        elif lo < 0.80:
            reasons.append("one box on this row was a little unclear")
            score = min(score, 0.75)
        else:
            score = min(score, 0.85 + 0.15 * (lo - 0.80) / 0.20)

    flag = "ok" if score >= 0.8 else ("review" if score >= 0.4 else "must_fix")
    return round(score, 3), flag, reasons


def annotate(record: dict[str, Any],
             issues: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Attach _row_conf / _review / _review_why to every day row, in place.

    Also writes record["_row_summary"] = {"ok": n, "review": n,
    "must_fix": n} so the page list can show it without re-scoring.
    """
    days = record.get("days") or []
    by_day: dict[int, list[dict[str, Any]]] = {}
    for i in issues or []:
        dday = i.get("day")
        if dday is not None:
            try:
                by_day.setdefault(int(dday), []).append(i)
            except (TypeError, ValueError):
                pass
    summary = {"ok": 0, "review": 0, "must_fix": 0}
    # D-046: on a page where the grid reader found NO date column, the day
    # numbers are positional guesses over whatever text was there. s23 (an
    # ERP time-card printout) got 7 "ok" rows that way, next to 21 must_fix.
    # Nothing on such a page has earned "ok": cap every row at review.
    cols = record.get("_columns_found")
    no_date_col = (NO_DATE_COLUMN_CAPS_OK and isinstance(cols, list)
                   and cols and "date" not in cols
                   and not record.get("_generic_grid"))
    # D-074: once two days' writing has landed in one box, the rows around it
    # are not trustworthy either, and they often look perfectly clean while
    # sitting against the wrong date. Measured on s08: days 17, 19, 24 and 26
    # were each read as a confident, plausible status one row out of step, and
    # nothing in the row itself gave it away.
    #
    # The doubt is carried DRIFT_WINDOW rows past each merged cell, not to the
    # bottom of the page. Propagating to the end also caught all four, but it
    # sent 689 of 1,157 rows to review instead of 366 -- it would roughly
    # double the checking work for the whole account to cover a defect that is
    # local to a few rows. A merge displaces its immediate neighbours; rows
    # further down re-anchor on their own date.
    suspect: set[int] = set()
    if CROWDED_CELL_REVIEW:
        for d in days:
            if not _crowded_cells(d):
                continue
            try:
                dn0 = int(d.get("day"))
            except (TypeError, ValueError):
                continue
            suspect.update(range(dn0, dn0 + DRIFT_WINDOW + 1))

    for d in days:
        try:
            dn = int(d.get("day"))
        except (TypeError, ValueError):
            dn = -1
        s, flag, why = score_row(d, by_day.get(dn),
                                 status_only=bool(record.get("_status_only")))
        if dn in suspect and flag == "ok":
            flag = "review"
            why = list(why) + ["the rows on this page may have slipped against "
                               "the dates -- please check this one against the paper"]
        if no_date_col and flag == "ok":
            flag = "review"
            why = list(why) + ["no date column found on this page"]
        d["_row_conf"] = s
        d["_review"] = flag
        d["_review_why"] = why
        summary[flag] += 1
    record["_row_summary"] = summary
    return record
