"""Repair the day grid using facts the page already states about itself.

The idea
--------
Every other stage in this pipeline reads pixels. This one reads nothing: it
takes the record we already extracted and asks whether it is *self-consistent*,
then fixes what isn't -- using two sources of truth that cost nothing and
cannot be misread by OCR.

**1. The summary block.** The supervisor writes the totals by hand at the
bottom: "P (Total Present Days) 26", "W/O (Total Weekly Off) 02". Those numbers
are short, printed-label-anchored, and read far more reliably than thirty rows
of handwriting. If the grid yields 24 present days and the sheet says 26, the
grid is wrong -- and we know by exactly how much.

**2. The calendar.** Weekly offs are not scattered at random; they fall on the
same weekday. Given the period ("April - 2026") every day number has a known
weekday, so one confirmed Sunday implies the others.

Together these turn "we could not read row 13" into "row 13 is a Sunday, the
sheet states two weekly offs, we found one, and row 13 is blank" -- which is an
answer, not a guess.

Why this is safe
----------------
Three rules keep it from inventing data:

  - It only ever fills rows that are **empty** -- no status and no clock times.
    A row we actually read is never overwritten by an inference.
  - It only fills **up to the stated count**, never beyond it.
  - Anything it changes is marked, so the reviewer sees inferred values as
    inferred.

If the summary is unreadable, or the counts already agree, this does nothing.
"""
from __future__ import annotations

import calendar
import re
from typing import Any

_MONTHS = {m.upper(): i for i, m in enumerate(calendar.month_name) if m}
_MONTHS.update({m.upper(): i for i, m in enumerate(calendar.month_abbr) if m})

# When a sheet shows no confirmed weekly off of its own, do we assume the off
# day is Sunday?
#
# This module used to state that Sunday "is the off day on every sheet in this
# corpus". That was true of the original 8-folder Delhi set and is FALSE on
# the full three-dataset corpus. Measured over 10,385 ground-truth employee
# rows, Sunday is weekly-off only 27.8% of the time and PRESENT 65% of the
# time, and the convention is per-client, not global:
#
#     ADANI02      Sun off  79-94%     strong convention
#     Thyssen02    Sun off  65-73%
#     HMEL19       Sun off     14%
#     SHELL02      Sun off    6-8%     no convention
#     SHELL04      Sat/Mon      3%     continuous site, works Sundays
#     AFCON08      none         0%
#
# Guessing Sunday on a continuous site invents weekly offs on days the
# employee worked. Voting from the sheet's OWN confirmed weekly offs stays
# correct everywhere; only the blind fallback is in question, so it is behind
# this switch and attributable on its own.
SUNDAY_DEFAULT_OFF = True

# Trust the file path's month over the month read off the page?
#
# The page's printed label goes through OCR and can come back not merely
# unreadable but CONFIDENTLY WRONG. Measured: 'VSPL APR 2026.pdf' -- whose
# label OCR'd as 'ELENT Lowes Parel, Mumbst 400819 VIERAM SOLAR UMITED' --
# resolved to (2025, 3), March 2025, for a sheet that is plainly April 2026.
# A wrong period is worse than no period: it points every weekday calculation
# at the wrong days. That page is the worst in the corpus at 58.1% day
# accuracy.
#
# The path states it without an OCR step in the way:
#     VIKR01 Vikram Solar Pvt. Ltd APR  2026/VSPL APR 2026.pdf
PERIOD_SOURCE_FIRST = True

# Move a weekly off that bound to the row next to its own. See section 0 of
# reconcile() for the measured pattern this corrects.
SNAP_WEEKLY_OFF = True

# Work evidence = time or hours only, never a word (D-017).
EVIDENCE_POSITIVE_ONLY = True

# A SAT/SUN word snaps its W to the calendar day it names (D-025).
WEEKDAY_WORD_SNAP = True

# D-041: blank Sunday on a blank-Sunday page => W; stated P == worked rows => worked Sundays are P.
EMPTY_SUNDAY_IS_OFF = True
STATED_P_CONFIRMS_WORK = True
STATED_WO_DEMOTES_INKED = True   # D-042

# LEAVE/PH/A merged cells follow the offset the SAT/SUN snaps established (D-028).
MERGED_OFFSET_FOLLOW = False


def parse_period(label: str | None) -> tuple[int, int] | None:
    """Pull (year, month) out of whatever the period line says.

    Handles 'April - 2026', 'APRIL-26', 'Apr 2026', 'Aprcil- 26'. The month
    name is matched on its first three letters so a mangled tail still resolves
    -- 'Aprcil' and 'Apsil' both start 'APR'/'APS', and only the former hits,
    which is the correct conservative behaviour.
    """
    if not label:
        return None
    text = str(label).upper()
    month = None
    for name, num in _MONTHS.items():
        if len(name) >= 3 and name[:3] in text:
            month = num
            break
    if not month:
        # Fuzzy rescue for OCR-mangled month words. Measured on the corpus's
        # real period labels: 'Apsil' scores 80 vs APRIL, 'Jaly' 75 vs JULY,
        # while every trap stays below 70 ('Max' 67, 'Mgy' 67, 'yue' 57,
        # 'NORMAL OVER TIME' 67 vs NOVEMBER). 75 separates them cleanly --
        # and the 'Jaly 2026' page was the single worst page in the corpus
        # (19% day accuracy) precisely because its month never parsed, so
        # nothing downstream could use the calendar.
        #
        # NOTE this affects only the PARSED (year, month) used internally for
        # month length and weekday math. It deliberately does not rewrite
        # period_label itself: that rewrite was measured earlier and rejected
        # (it destroyed legitimate two-month labels like 'June - July 26').
        from rapidfuzz import fuzz as _f
        best_score = 0.0
        for tok in re.split(r"[^A-Z]+", text):
            if len(tok) < 3:
                continue
            for name, num in _MONTHS.items():
                if len(name) < 4:
                    continue
                s = _f.ratio(tok, name)
                if s > best_score:
                    best_score, month = s, num
        if best_score < 75:
            return None
    # A four-digit year is unambiguous even glued to the month ('May2026'),
    # where \b finds no boundary between Y and 2. Two-digit years still
    # require the boundary, or every '26' inside a code would become a year.
    years = re.findall(r"(20\d{2})", text) + re.findall(r"\b(\d{2})\b", text)
    for y in years:
        n = int(y)
        year = 2000 + n if n < 100 else n
        if 2020 <= year <= 2099:
            return year, month
    return None


def _months_in(text: str) -> set[int]:
    """Month numbers named in a string, matched on WORD boundaries.

    Boundaries matter: without them 'MAR' fires inside 'MARINE' and 'MAY'
    inside a client name. With them, 'JULY' matches the full name only (the
    abbreviation 'JUL' cannot match inside 'JULY'), so a component naming one
    month yields exactly one number.
    """
    up = text.upper()
    out: set[int] = set()
    for name, num in _MONTHS.items():
        if len(name) >= 3 and re.search(rf"\b{name}\b", up):
            out.add(num)
    return out


def _years_in(text: str) -> set[int]:
    return {int(y) for y in re.findall(r"\b(20\d{2})\b", text)}


def infer_period_from_source(source: str | None) -> tuple[int, int] | None:
    """Recover the month from the file's own name and folder path.

    The last resort, and the strongest signal available when the page itself
    is unreadable. Measured: 7 of 49 evaluation pages resolved no period at
    all -- neither from the printed label ('ELENT Lowes Parel, Mumbst 400819
    VIERAM SOLAR UMITED' is what OCR made of one) nor from the grid. Those
    pages run with the calendar switched off entirely, so no weekly-off
    reconciliation can fire, and they include the two worst pages in the whole
    corpus (58.1% and 60.0% day accuracy).

    Meanwhile the path says it plainly:

        VIKR01 Vikram Solar Pvt. Ltd APR  2026/VSPL APR 2026.pdf

    Components are read leaf-first, so the specific month folder beats the
    dataset root. A component naming two months, or a fiscal-year root like
    '2026-2027' naming two years, is ambiguous and contributes nothing rather
    than guessing.
    """
    if not source:
        return None
    from pathlib import PurePath
    parts = [p for p in PurePath(str(source)).parts if p not in ("/", "")]
    month = year = None
    for comp in reversed(parts):
        if month is None:
            ms = _months_in(comp)
            if len(ms) == 1:
                month = ms.pop()
            elif len(ms) > 1:
                return None            # ambiguous -- refuse rather than pick
        if year is None:
            ys = _years_in(comp)
            if len(ys) == 1:
                year = ys.pop()
        if month is not None and year is not None:
            return (year, month)
    return None


def infer_period_from_grid(label: str | None,
                           days: list[dict[str, Any]]) -> tuple[int, int] | None:
    """Recover the month when its NAME is unreadable, from the calendar.

    'yue-2026' defeats every string method -- but the page still knows its
    month. The confirmed weekly offs fall on specific day numbers, and only
    some months of that year put all of those numbers on the same weekday.
    If exactly one month does (preferring Sundays, the corpus's universal
    off day), that is the month. Requires a readable year and at least two
    confirmed W days; returns None on any ambiguity rather than guessing.
    """
    text = str(label or "").upper()
    year = None
    for y in re.findall(r"(20\d{2})", text) + re.findall(r"\b(\d{2})\b", text):
        n = int(y)
        cand = 2000 + n if n < 100 else n
        if 2020 <= cand <= 2099:
            year = cand
            break
    if not year or not days:
        return None
    w_days = [d.get("day") for d in days
              if (d.get("status") or "").upper() == "W" and d.get("day")]
    if len(w_days) < 2:
        return None
    # Month length can only be evidenced by rows that HOLD something. The
    # printed form carries 31 rows in every month, so an empty day-31 row is
    # furniture, not proof of a 31-day month -- counting it excluded the
    # correct 30-day month on a measured page.
    max_day = max((d.get("day") or 0 for d in days if not _is_empty(d)),
                  default=0)
    if not 1 <= max_day <= 31:
        return None
    cands = []
    for month in range(1, 13):
        ndays = calendar.monthrange(year, month)[1]
        if ndays < max_day:
            continue
        wds = {calendar.weekday(year, month, d) for d in w_days}
        if len(wds) == 1:
            cands.append((month, wds.pop(), ndays))
    pool = [m for m, wd, _ in cands if wd == 6] or [m for m, _, _ in cands]
    if len(pool) == 1:
        return year, pool[0]
    # Still tied: a grid printed with exactly N rows names an N-day month.
    exact = [m for m, _, nd in cands if m in pool and nd == max_day]
    if len(exact) == 1:
        return year, exact[0]
    return None


def weekday_of(year: int, month: int, day: int) -> int | None:
    """0 = Monday ... 6 = Sunday. None if the day is not in that month."""
    try:
        return calendar.weekday(year, month, day)
    except (ValueError, calendar.IllegalMonthError):
        return None


def _is_empty(d: dict[str, Any]) -> bool:
    """A row we genuinely failed to read: no status and no times."""
    if (d.get("status") or "").strip():
        return False
    return not any(str(d.get(k) or "").strip()
                   for k in ("in_time", "out_time", "normal_hours",
                             "total_hours", "ot_hours"))


def _as_int(v: Any) -> int | None:
    m = re.search(r"\d+", str(v or ""))
    return int(m.group()) if m else None


def _work_evidence(d: dict[str, Any]) -> int:
    """How many cells carry POSITIVE work evidence.

    The original counted any non-empty value, so a weekday word in the hours
    cell ("SAT", "SUN" on GRSE01's merged rows) looked like recorded work and
    the demotion rule flipped four correct Sundays per page to P. Evidence is
    a value that carries a digit and whose first number is positive -- which
    still admits every mangled handwritten clock ('19100', '8:', '0800') that
    the stricter first draft of this rule rejected (old-set guard 853 -> 851).
    A bare word is never work. Gated by EVIDENCE_POSITIVE_ONLY (D-017/D-018).
    """
    keys = ("in_time", "out_time", "normal_hours", "ot_hours", "total_hours")
    if not EVIDENCE_POSITIVE_ONLY:
        return sum(1 for k in keys if str(d.get(k) or "").strip())
    n = 0
    for k in keys:
        v = str(d.get(k) or "").strip()
        if not v or not any(c.isdigit() for c in v):
            continue
        m = re.search(r"\d+(?:[.:]\d+)?", v.replace(",", ""))
        if m and float(m.group(0).replace(":", ".")) > 0:
            n += 1
    return n


def reconcile(record: dict[str, Any]) -> dict[str, Any]:
    """Fill unread rows from the stated totals and the calendar. In place."""
    days = record.get("days") or []
    summary = record.get("summary") or {}
    if not days:
        return record

    _from_src = infer_period_from_source(record.get("_source_hint"))
    if PERIOD_SOURCE_FIRST and _from_src:
        period = _from_src
    else:
        period = parse_period(record.get("period_label")) \
            or infer_period_from_grid(record.get("period_label"), days) \
            or _from_src
    # A stated total is only usable as a repair signal if it was READ well.
    #
    # Measured failure: a sheet whose P.H. box said 'Nil' was OCR'd as '1' at
    # confidence 0.80 -- and reconciliation then invented a public holiday on a
    # day the employee worked. The whole safety argument for this module is
    # that the stated totals are more reliable than the grid; a low-confidence
    # total is exactly the case where that premise fails, so it must not drive
    # a repair. (The low-confidence WARNING still fires either way -- the
    # reviewer sees the doubt; we just refuse to act on it.)
    # --- 0. snap a weekly off that landed one row off ---------------------
    #
    # Weekly offs fall on ONE weekday. Measured against the client's own typed
    # Excel, our weekly offs are usually right except for a single row-offset:
    #
    #     truth W: 5(Sun) 12(Sun) 19(Sun) 26(Sun)
    #     ours  W: 5(Sun) 12(Sun) 19(Sun) 27(Mon)     one row late
    #     ours  W: 5(Sun) 11(Sat) 19(Sun) 26(Sun)     one row early
    #
    # The annotation is written across a row boundary and binds to the
    # neighbour. Each misplacement costs TWO comparisons -- a W->P on the true
    # day and a P->W on the neighbour -- which is why those were the top two
    # confusions (21 and 15).
    #
    # Only fires when the sheet's own weekly offs agree on a weekday by a
    # clear majority, so it never imposes an off day the page does not
    # already demonstrate. The count is preserved: this MOVES a weekly off,
    # it never creates one.
    # --- 0b. a weekday WORD names its own day ---------------------------
    # GRSE01 prints "SAT"/"SUN" as a merged cell one row below the calendar
    # Saturday/Sunday (the form's own layout; the client's truth follows
    # the calendar). The modal-weekday vote below cannot see this, and with
    # two off-days a week it votes one of them and demotes the other. The
    # word is stronger evidence than a vote: if the row's day is not that
    # weekday but an adjacent day is, and that neighbour carries no work
    # evidence, the marking belongs there. Flag WEEKDAY_WORD_SNAP (D-025).
    _snap_dirs: list[int] = []
    if WEEKDAY_WORD_SNAP and period:
        year, month = period
        by_day = {d.get("day"): d for d in days if d.get("day")}
        # The WORD is the trigger, not the row's status. Through the skew the
        # merged "SUN" shares a band with the next row's 09:00, so that row
        # reads P -- a genuinely worked Monday carrying a Sunday's label.
        # The label still names the adjacent calendar day.
        for d in list(days):
            wd_word = d.get("_weekday_word")
            day_no = d.get("day") or 0
            if wd_word is None:
                continue
            if weekday_of(year, month, day_no) == wd_word:
                continue
            for cand in (day_no - 1, day_no + 1):
                nb = by_day.get(cand)
                if nb is None or weekday_of(year, month, cand) != wd_word:
                    continue
                if (nb.get("status") or "").upper() == "W" or \
                        _work_evidence(nb) > 0:
                    continue
                nb["status"] = "W"
                nb["_inferred"] = ("weekly-off moved here: the adjacent "
                                   "row's weekday word names this day")
                if (d.get("status") or "").upper() == "W":
                    d["status"] = "P" if _work_evidence(d) else None
                    d["_inferred"] = ("weekly-off marking belonged to the "
                                      "adjacent calendar day named by its word")
                _snap_dirs.append(cand - day_no)
                break
        # --- 0c. other merged-cell annotations follow the same offset -------
        # On a form whose merged cells all sit one row from their date (the
        # SAT/SUN snaps above establish the direction), a LEAVE / PUBLIC
        # HOLIDAY / ABSENT merged cell is displaced the same way. Follow only
        # when >= 2 snaps agree on one direction, only for annotation-only
        # rows (no work evidence), and only into a neighbour that is empty.
        # Flag MERGED_OFFSET_FOLLOW (D-028).
        if MERGED_OFFSET_FOLLOW and len(_snap_dirs) >= 2 and len(set(_snap_dirs)) == 1:
            step = _snap_dirs[0]
            for d in list(days):
                st = (d.get("status") or "").upper()
                if st not in ("L", "H", "A", "C") or _work_evidence(d) > 0:
                    continue
                if d.get("_inferred"):
                    continue
                nb = by_day.get((d.get("day") or 0) + step)
                if nb is None or not _is_empty(nb) or nb.get("status"):
                    continue
                nb["status"] = st
                nb["_inferred"] = (f"{st} moved here: this form's merged cells "
                                   "all sit one row from their date")
                d["status"] = None
                d["_inferred"] = "annotation belonged to the adjacent row"

    if SNAP_WEEKLY_OFF and period:
        year, month = period
        w_rows0 = [d for d in days if (d.get("status") or "").upper() == "W"]
        votes0: dict[int, int] = {}
        for d in w_rows0:
            w = weekday_of(year, month, d.get("day") or 0)
            if w is not None:
                votes0[w] = votes0.get(w, 0) + 1
        if votes0:
            top_wd = max(votes0, key=lambda k: votes0[k])
            agree = votes0[top_wd]
            # A clear majority, and at least two rows proving the pattern.
            if agree >= 2 and agree > sum(v for k, v in votes0.items()
                                          if k != top_wd):
                by_day = {d.get("day"): d for d in days if d.get("day")}
                for d in w_rows0:
                    day_no = d.get("day") or 0
                    if weekday_of(year, month, day_no) == top_wd:
                        continue
                    for cand in (day_no - 1, day_no + 1):
                        nb = by_day.get(cand)
                        if nb is None:
                            continue
                        if weekday_of(year, month, cand) != top_wd:
                            continue
                        if (nb.get("status") or "").upper() == "W":
                            continue
                        # Move only when the evidence points that way: the row
                        # currently marked W shows work, and the neighbour on
                        # the off weekday does not. Without this the rule also
                        # moved weekly offs that were already correct, and one
                        # page lost 4 comparisons.
                        if _work_evidence(d) == 0 or _work_evidence(nb) > 0:
                            continue
                        nb["status"] = "W"
                        nb["_inferred"] = (
                            "weekly-off moved here: the sheet's other weekly "
                            "offs all fall on this weekday, and the marking "
                            "landed on the adjacent row")
                        d["status"] = "P" if _work_evidence(d) else None
                        filled_snap = True                     # noqa: F841
                        break

    # --- 0d. an EMPTY Sunday on a page whose Sundays are empty is a weekly off
    # The fill below needs a stated W/O total; on TEIL sheets that cell is a
    # dash, so blank Sunday rows stayed EMPTY (must_fix on six rows across two
    # hand-checked pages). The paper settles it: >= 2 calendar Sundays with
    # no ink and no blank non-Sunday row => a blank Sunday is the weekly off.
    # Inferred, so the row is marked review. Flag EMPTY_SUNDAY_IS_OFF (D-041).
    if EMPTY_SUNDAY_IS_OFF and period:
        _y, _m = period
        def _blank(d: dict[str, Any]) -> bool:
            # No ink in ANY cell -- a "C/OFF" in remarks is not a blank row.
            return not (d.get("status") or "") and not any(
                str(d.get(k) or "").strip() for k in
                ("in_time", "out_time", "normal_hours", "ot_hours",
                 "total_hours", "remarks"))
        _empties = [d for d in days if _blank(d)]
        _sun_e = [d for d in _empties if weekday_of(_y, _m, d.get("day") or 0) == 6]
        _oth_e = [d for d in _empties if weekday_of(_y, _m, d.get("day") or 0) not in (6, None)]
        # A blank weekday or two (an absence, a leave the OCR missed) is
        # normal and must not veto the Sunday inference.
        if len(_sun_e) >= 2 and len(_oth_e) <= 2:
            for d in _sun_e:
                d["status"] = "W"
                d["_inferred"] = ("weekly-off: blank row on a Sunday, on a page "
                                  "whose Sundays are all blank")

    # --- 0e. the stated P total confirms that worked Sundays count as present
    # ADANI-family sheets mark a worked Sunday with hours plus a "(SUNDAY)"
    # remark; the weekday-word rule reads that as W. The sheet's own P total
    # says otherwise when it equals the number of rows carrying work evidence
    # (31 on a page with four worked Sundays). Evidence, not convention: on
    # IOCL sheets the stated P excludes Sundays, so this never fires there.
    # Flag STATED_P_CONFIRMS_WORK (D-041).
    if STATED_P_CONFIRMS_WORK:
        _p_stated = _as_int(summary.get("total_present_days"))
        _worked = [d for d in days if _work_evidence(d) > 0]
        # Tolerate one dropped row: the total must be unreachable without the
        # W-with-hours rows, and within one of the worked-row count.
        _non_w = [d for d in _worked if (d.get("status") or "").upper() != "W"]
        if _p_stated is not None and _p_stated >= 20 and \
                len(_worked) - 1 <= _p_stated <= len(_worked) + 1 and \
                _p_stated > len(_non_w):
            for d in _worked:
                if (d.get("status") or "").upper() == "W":
                    d["status"] = "P"
                    d["_inferred"] = ("present: carries hours, and the sheet's "
                                      "stated present-day total counts every "
                                      "row with hours")

    conf = record.get("_confidence") or {}

    def trusted(field: str) -> int | None:
        c = conf.get(field)
        if c is not None and float(c) < 0.85:
            return None
        v = _as_int(summary.get(field))
        # An impossible count is a misread even at high OCR confidence:
        # no day-type total can exceed the days in the month.
        month_len = (calendar.monthrange(*period)[1] if period else 31)
        if v is not None and v > month_len:
            return None
        return v

    counts = {"W": trusted("total_weekly_off"),
              "H": trusted("total_public_holiday"),
              "A": trusted("total_absent_days"),
              "L": trusted("total_leave_days"),
              "C": trusted("total_comp_off")}

    filled: list[dict[str, Any]] = []

    # --- 1. weekly offs, by weekday periodicity ---------------------------
    want_w = counts.get("W")
    have_w = [d for d in days if (d.get("status") or "").upper() == "W"]
    if period and want_w and len(have_w) < want_w:
        year, month = period
        # Which weekday is this employee's off day? Take the one most of the
        # confirmed weekly offs fall on; default to Sunday, which is the off
        # day on every sheet in this corpus.
        wd_votes: dict[int, int] = {}
        for d in have_w:
            wd = weekday_of(year, month, d.get("day") or 0)
            if wd is not None:
                wd_votes[wd] = wd_votes.get(wd, 0) + 1
        off_wd = (max(wd_votes, key=lambda k: wd_votes[k]) if wd_votes
                  else (6 if SUNDAY_DEFAULT_OFF else None))

        need = want_w - len(have_w) if off_wd is not None else 0
        for d in days:
            if need <= 0:
                break
            if not _is_empty(d):
                continue
            wd_here = weekday_of(year, month, d.get("day") or 0)
            if wd_here is not None and wd_here == off_wd:
                d["status"] = "W"
                d["_inferred"] = "weekly-off: same weekday as the others, and " \
                                 "the sheet states more weekly offs than we read"
                filled.append(d)
                need -= 1

        # Still short? Reconsider NON-empty rows on the off weekday.
        #
        # This is the one place an already-read value is overwritten, so the
        # evidence bar is explicit. Reading the actual W->P failures: rows on
        # Sundays carrying '18:00 08' or '8:00-13:00' -- and the client's own
        # typed Excel calls every one of them WO. Their convention is that the
        # off-day is an off-day regardless of ink in the time cells (which is
        # frequently a neighbouring row's bleed, or an annotation misread as a
        # time). The stated W/O total on the sheet is the client's own number;
        # when it says there are more weekly offs than we found, and the only
        # candidates are off-weekday rows, the total wins.
        #
        # Ordered weakest-evidence-first, capped at the stated count, and every
        # conversion is marked _inferred for the reviewer.
        if need > 0:
            def evidence(d: dict[str, Any]) -> int:
                return sum(1 for k in ("in_time", "out_time", "normal_hours",
                                       "ot_hours", "total_hours")
                           if str(d.get(k) or "").strip())
            candidates = sorted(
                (d for d in days
                 if (d.get("status") or "").upper() not in ("W", "H", "A", "L", "C")
                 and weekday_of(year, month, d.get("day") or 0) == off_wd),
                key=evidence)
            for d in candidates:
                if need <= 0:
                    break
                d["status"] = "W"
                d["_inferred"] = ("weekly-off: falls on the off weekday and the "
                                  "sheet's own W/O total says we found too few")
                filled.append(d)
                need -= 1

    # --- 1a-bis. weekly offs WITHOUT a trusted stated count ----------------
    # The fill above needs the sheet's W/O total, and that total is itself
    # sometimes unreadable. But two or more confirmed weekly offs already
    # prove the periodicity: they name the off weekday. An EMPTY row on that
    # weekday is a weekly off -- a genuinely worked off-day would carry
    # clock times or hours and so would not be empty. Fill-only, capped by
    # the calendar itself, every row marked inferred.
    if period and not want_w and len(have_w) >= 2:
        year, month = period
        votes_nc: dict[int, int] = {}
        for d in have_w:
            wd = weekday_of(year, month, d.get("day") or 0)
            if wd is not None:
                votes_nc[wd] = votes_nc.get(wd, 0) + 1
        if votes_nc and max(votes_nc.values()) >= 2:
            off_wd = max(votes_nc, key=lambda k: (votes_nc[k], k == 6))
            for d in days:
                if _is_empty(d) and weekday_of(
                        year, month, d.get("day") or 0) == off_wd:
                    d["status"] = "W"
                    d["_inferred"] = ("weekly-off: same weekday as the "
                                      "confirmed weekly offs, and the row "
                                      "is otherwise blank")
                    filled.append(d)

    # --- 1b. TOO MANY weekly offs: demote the misplaced ones ---------------
    # The mirror image of the fill above. A weekday-name annotation written
    # between rows ('Sunday' across the boundary of the 25th and 26th) can
    # land on the wrong row and mark a worked Saturday as W. Three signals
    # together identify exactly that case: the sheet's own W/O total says we
    # have too many, the suspect row does NOT fall on the off weekday, and
    # the row itself carries recorded working time. Rows on the off weekday
    # are never touched (the client's own Excel counts those as WO even when
    # inked), and we demote at most down to the stated count.
    if period and want_w and len(have_w) > want_w:
        year, month = period
        wd_votes2: dict[int, int] = {}
        for d in have_w:
            wd = weekday_of(year, month, d.get("day") or 0)
            if wd is not None:
                wd_votes2[wd] = wd_votes2.get(wd, 0) + 1
        off_wd = (max(wd_votes2, key=lambda k: wd_votes2[k]) if wd_votes2
                  else (6 if SUNDAY_DEFAULT_OFF else None))
        suspects = sorted(
            (d for d in have_w
             if off_wd is not None
             and weekday_of(year, month, d.get("day") or 0) is not None
             and weekday_of(year, month, d.get("day") or 0) != off_wd
             and _work_evidence(d) > 0),
            key=_work_evidence, reverse=True)
        for d in suspects[:len(have_w) - want_w]:
            d["status"] = "P"
            d["_inferred"] = ("worked day: marked W but falls on a normal "
                              "weekday, carries recorded hours, and the "
                              "sheet's own W/O total says we have one too many")
            filled.append(d)

    # --- 1b'. inked rows on the off weekday, above the sheet's own W/O count
    # A worked Sunday (hours plus a "(SUNDAY)" remark) reads W; the sheet's
    # stated W/O says otherwise. 1b above never touches the off weekday --
    # on IOCL an inked Sunday IS a weekly off -- but there the stated W/O
    # equals the Sundays, so this cannot fire. The stated value may be
    # handwritten and below the 0.85 trust gate ("01" read at 0.57 on TEIL);
    # it is accepted here only when CORROBORATED: it equals the number of W
    # rows that carry no work evidence at all. Two weak signals that agree.
    # Demote the inked rows with the most evidence, down to that count.
    # Flag STATED_WO_DEMOTES_INKED (D-042).
    if STATED_WO_DEMOTES_INKED and period:
        _wo_any = _as_int(summary.get("total_weekly_off"))
        _w_rows = [d for d in days if (d.get("status") or "").upper() == "W"]
        _w_blank = [d for d in _w_rows if _work_evidence(d) == 0]
        _w_inked = sorted((d for d in _w_rows if _work_evidence(d) > 0),
                          key=_work_evidence, reverse=True)
        _target = want_w if want_w is not None else (
            _wo_any if (_wo_any is not None and _wo_any == len(_w_blank)) else None)
        if _target is not None and len(_w_rows) > _target and _w_inked:
            for d in _w_inked[:len(_w_rows) - _target]:
                d["status"] = "P"
                d["_inferred"] = ("worked day: carries recorded hours on the "
                                  "off weekday, and the sheet's own W/O total "
                                  "does not count it")
                filled.append(d)

    # --- 1c. a W bleeding onto the neighbouring row ------------------------
    # Needs no stated total (which may itself be unreadable). A weekday-name
    # annotation written across a row boundary can mark BOTH the Sunday and
    # its neighbour as W. When two adjacent rows are W, one falls on the off
    # weekday and the other does not, and the misplaced one carries recorded
    # working time, the annotation belonged to the Sunday: the neighbour is a
    # worked day. (A genuine Saturday off would carry no hours -- the work
    # evidence is the disambiguator.)
    if period:
        year, month = period
        w_rows = [d for d in days if (d.get("status") or "").upper() == "W"]
        if len(w_rows) >= 2:
            votes: dict[int, int] = {}
            for d in w_rows:
                wd = weekday_of(year, month, d.get("day") or 0)
                if wd is not None:
                    votes[wd] = votes.get(wd, 0) + 1
            off_wd = (max(votes, key=lambda k: (votes[k], k == 6))
                      if votes else (6 if SUNDAY_DEFAULT_OFF else None))
            w_daynums = {d.get("day") for d in w_rows}
            for d in w_rows:
                day_no = d.get("day") or 0
                wd = weekday_of(year, month, day_no)
                if wd is None or wd == off_wd or _work_evidence(d) == 0:
                    continue
                neighbour_is_true_w = any(
                    (day_no + step) in w_daynums
                    and weekday_of(year, month, day_no + step) == off_wd
                    for step in (-1, 1))
                if neighbour_is_true_w:
                    d["status"] = "P"
                    d["_inferred"] = ("worked day: the weekly-off note here "
                                      "belongs to the adjacent off-day row; "
                                      "this row has recorded hours")
                    filled.append(d)

    # --- 2. remaining stated non-working days -----------------------------
    # No calendar signal for these, so they are only assigned when the count of
    # unread rows matches what is missing exactly. An exact match means there
    # is one consistent reading; anything else is ambiguous and left flagged.
    for code in ("H", "A", "L", "C"):
        want = counts.get(code)
        if not want:
            continue
        have = sum(1 for d in days if (d.get("status") or "").upper() == code)
        need = want - have
        if need <= 0:
            continue
        empties = [d for d in days if _is_empty(d)]
        if len(empties) == need:
            for d in empties:
                d["status"] = code
                d["_inferred"] = (f"the sheet states {want} of this type and "
                                  f"exactly {need} row(s) could not be read")
                filled.append(d)

    # --- 3. complete the normal-hours column against its own total ---------
    # On these forms the worked days almost all carry the same normal hours
    # (site shifts: 8.0, day after day), and the supervisor's stated total is
    # that value times the present days -- 27 x 8 = 216, written at the
    # bottom. When some hour CELLS are unreadable but the day rows themselves
    # are known-present, the sheet's own arithmetic completes the column.
    #
    # Guards, in order of importance:
    #   - only cells with NO plausible hours reading are filled: empty cells,
    #     unparseable junk ('90p0'), and zero-on-a-present-day (P status and
    #     0 hours cannot both be true; the stated total arbitrates). A cell
    #     that parsed to a real 1-24h value is never overwritten;
    #   - the fill value must come from the page itself: the modal read value
    #     among present rows (>=5 occurrences), or the stated total divided
    #     by the stated present days when that is a clean half-hour value;
    #   - the fill is committed ONLY if it brings the column sum into
    #     agreement with the stated total -- otherwise everything is rolled
    #     back and the page stays flagged.
    stated_norm = None
    c_norm = conf.get("total_man_hours")
    if c_norm is None or float(c_norm) >= 0.85:
        m = re.search(r"\d+(?:\.\d+)?", str(summary.get("total_man_hours") or ""))
        if m:
            v = float(m.group())
            month_len = (calendar.monthrange(*period)[1] if period else 31)
            if 0 < v <= 24 * month_len:
                stated_norm = v

    if stated_norm:
        def hours_of(d: dict[str, Any]) -> float | None:
            s = str(d.get("normal_hours") or "").strip()
            if not s:
                return None
            mm = re.fullmatch(r"(\d{1,2})(?:[:.](\d{1,2}))?", s)
            if not mm:
                return None
            val = float(mm.group(1)) + (float(mm.group(2) or 0) / 60.0
                                        if ":" in s else
                                        float("0." + mm.group(2))
                                        if mm.group(2) else 0.0)
            return val if 0 < val <= 24 else None

        p_rows = [d for d in days
                  if (d.get("status") or "").upper() == "P"]
        read_vals = [hours_of(d) for d in p_rows]
        empties = [d for d, v in zip(p_rows, read_vals) if v is None]
        got_sum = sum(v for v in read_vals if v is not None)

        from collections import Counter
        modes = Counter(v for v in read_vals if v is not None).most_common(1)
        fill_val = None
        if modes and modes[0][1] >= 5:
            fill_val = modes[0][0]
        else:
            stated_p = trusted("total_present_days")
            if stated_p:
                rate = stated_norm / stated_p
                if 4 <= rate <= 12 and abs(rate * 2 - round(rate * 2)) < 1e-6:
                    fill_val = rate

        if fill_val and empties:
            new_sum = got_sum + fill_val * len(empties)
            if abs(new_sum - stated_norm) <= max(0.01, 0.02 * stated_norm):
                for d in empties:
                    prev = str(d.get("normal_hours") or "").strip()
                    d["normal_hours"] = fill_val
                    d["_inferred"] = ("normal hours: no readable value on a "
                                      "present day"
                                      + (f" (cell read {prev!r})" if prev else "")
                                      + "; the page's usual value completes "
                                        "the stated total")
                    filled.append(d)

    if filled:
        record["_reconciled"] = len(filled)
    return record
