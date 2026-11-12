"""Ordinal (sequence) matching of header labels to their values.

WHY DISTANCE FAILS
------------------
Verified against the actual scan of `IOCLMS APR 2026 p003`:

    label column          value column        system assigned
    MONTH & YEAR:         APRIL 2026          period  = 'APRIL 2026'      OK
    EMPLOYEE NAME:        Pradeep Chauhan       name    = None              WRONG
    DESIGNATION:          Safety Supervisor   desig   = None              WRONG
    EMPLOYEE CODE:        50782               code    = 'Safity sulenvisor
                                                         NeeraJ Sharomd'  WRONG

The values are all present and OCR read them fine. They are simply written
LOWER relative to their labels than on other scans -- the whole handwritten
block is shifted down by roughly one row. Every distance-based rule (nearest,
nearest-above, 2-D cost) inherits that offset and mis-assigns the entire block.

THE INSIGHT
-----------
The labels appear in a FIXED vertical order on this form, and the values appear
in the SAME order beside them. So the reliable signal is not "how far apart are
they" but "what position in the sequence is each one".

    1st value  ->  1st label
    2nd value  ->  2nd label
    ...

A uniform vertical shift changes every distance but changes no ordering, so
ordinal matching is immune to exactly the failure that defeats distance.

WHEN IT APPLIES
---------------
Only when the counts line up sensibly and the labels form a clean vertical
column. If a value is missing (a blank field on the form) the sequence slips by
one and every later field is wrong -- which is worse than the distance method.
So we require a confident alignment and fall back otherwise.

TERMS
-----
ordinal      by position in a sequence (1st, 2nd, 3rd) rather than by distance
column       here, a set of boxes sharing a similar left edge
slippage     the failure mode where one missing value shifts all the rest
"""
from __future__ import annotations

from .ocr_engine import TextBox


def _column_of(anchors: list[TextBox]) -> tuple[float, float]:
    """The x-range occupied by the label column."""
    return (min(a.x0 for a in anchors), max(a.x1 for a in anchors))


def order_labels(anchors: dict[str, TextBox]) -> list[tuple[str, TextBox]]:
    """Labels top-to-bottom."""
    return sorted(anchors.items(), key=lambda kv: kv[1].cy)


def value_window(boxes: list[TextBox], anchors: list[TextBox],
                 page_w: int) -> tuple[float, float]:
    """Derive the x-range the values occupy, from the page's own geometry.

    Measured on `IOCLMS APR 2026 p005`:
        label column   x ~107-220
        value column   x ~279-500
        NEXT column's labels (CLIENT / PROJECT / LOCATION) start at x ~519

    So the value window is bounded on the left by where the labels end and on
    the right by where the next label column begins. Both edges are read off
    the page rather than assumed, so it adapts to any capture scale.

    Getting this window wrong is what broke v1: a loose right edge pulled in
    the right-hand column's values and the grid's column headers, and the
    sequence then aligned against the wrong rows.
    """
    lx1 = max(a.x1 for a in anchors)
    top = min(a.y0 for a in anchors)
    bot = max(a.y1 for a in anchors)

    # The next column starts at the leftmost OTHER label-ish box that sits
    # well to the right of ours, within the same vertical span.
    right_edge = lx1 + page_w * 0.42
    for b in boxes:
        if b in anchors:
            continue
        if not (top - 20 <= b.cy <= bot + 20):
            continue
        # A short, upper-case, colon-ish box to our right is another label.
        txt = b.text.strip()
        if b.x0 > lx1 + page_w * 0.18 and len(txt) <= 24 and \
                sum(c.isupper() or not c.isalpha() for c in txt) >= len(txt) * 0.7:
            right_edge = min(right_edge, b.x0 - 6)
    return lx1 + 4, max(right_edge, lx1 + 40)


def candidate_values(boxes: list[TextBox], anchors: list[TextBox],
                     page_w: int) -> list[TextBox]:
    """Boxes that sit in the value column beside a vertical label column."""
    if not anchors:
        return []
    x_lo, x_hi = value_window(boxes, anchors, page_w)
    row_h = sum(a.y1 - a.y0 for a in anchors) / len(anchors)
    top = min(a.y0 for a in anchors) - row_h * 0.5
    # Values sit BELOW their label, so allow more room downward than upward --
    # but only ONE row of slack. Measured: at 1.8 rows the window reached into
    # the day-grid header, so `employee_code` was assigned 'TIME IN NORMAL
    # ATTENDANCE' and `designation` swallowed the code value as well.
    bot = max(a.y1 for a in anchors) + row_h * 1.05

    out = []
    for b in boxes:
        if b in anchors:
            continue
        if not (top <= b.cy <= bot):
            continue
        if not (x_lo <= b.x0 <= x_hi):
            continue
        out.append(b)
    return sorted(out, key=lambda b: (b.cy, b.x0))


def group_rows(values: list[TextBox], row_h: float) -> list[list[TextBox]]:
    """Cluster value boxes into visual rows."""
    rows: list[list[TextBox]] = []
    for b in values:
        if rows and abs(b.cy - rows[-1][0].cy) <= row_h * 0.7:
            rows[-1].append(b)
        else:
            rows.append([b])
    for r in rows:
        r.sort(key=lambda b: b.x0)
    return rows


def match(anchors: dict[str, TextBox], boxes: list[TextBox],
          page_w: int) -> dict[str, list[TextBox]] | None:
    """Assign values to labels by sequence position.

    Returns None when the alignment is not confident, so the caller can fall
    back to distance-based assignment rather than trusting a slipped sequence.
    """
    if len(anchors) < 3:
        return None
    ordered = order_labels(anchors)
    anchor_boxes = [a for _, a in ordered]

    # The labels must actually form a vertical column -- if they are scattered
    # horizontally this is a different layout and ordinal logic does not hold.
    xs = [a.x0 for a in anchor_boxes]
    if max(xs) - min(xs) > page_w * 0.12:
        return None

    row_h = sum(a.y1 - a.y0 for a in anchor_boxes) / len(anchor_boxes)
    values = candidate_values(boxes, anchor_boxes, page_w)
    rows = group_rows(values, row_h)

    # Require a plausible 1:1 alignment. Fewer value-rows than labels means a
    # blank field somewhere, and we cannot tell WHICH -- so we decline rather
    # than risk shifting every subsequent field.
    if len(rows) != len(ordered):
        return None

    return {fieldname: rows[i] for i, (fieldname, _) in enumerate(ordered)}
