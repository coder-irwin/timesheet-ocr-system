"""2-D assignment of value boxes to label anchors.

THE PROBLEM
-----------
On handwritten forms, values are written large and sit low in their cell, while
the form's rows are only ~35 px apart. Measured on IOCL30:

    MONTH & YEAR:   label cy=197   value 'Apsinl -2026'  cy=218
    EMPLOYEE NAME:  label cy=232   value 'Shiv Shankan'  cy=252

Every value therefore falls within tolerance of TWO labels, and a
distance-threshold rule assigns it to both -- producing
`employee_name = 'Shiv Shankan Apsinl -2026'`.

TWO CHEAP FIXES WERE TRIED AND BOTH FAILED (see docs/06):
  * nearest label            -> values shifted DOWN a row (handwriting sits
                                closer to the next label than to its own)
  * nearest label at-or-above -> broke side-by-side label pairs, because these
                                forms carry two label/value pairs per row
                                ("MONTH & YEAR: v | CLIENT: v")

WHAT ACTUALLY WORKS
-------------------
Both failures come from using ONE dimension. A value's owner is determined by
vertical AND horizontal position together:

  * vertically   it belongs to the nearest label at or above it
  * horizontally it belongs to the label immediately to its left, not one
                 further away in another column

So this module scores every (label, value) pair with a 2-D cost and solves the
assignment globally, greedily taking the cheapest pairs first. That is a good
approximation to the Hungarian algorithm and needs no extra dependency.

TERMS
-----
cost        a number saying how unlikely it is that this label owns this value;
            lower is better
greedy      repeatedly take the cheapest remaining pair
assignment  the resulting label -> values mapping
"""
from __future__ import annotations

from typing import Iterable

from .ocr_engine import TextBox

# Vertical misalignment says "which row"; horizontal gap says "which column".
# Both matter, and W_DX was raised from 1.0 to 2.2 after measurement: at 1.0 a
# left-column label could out-bid the right-column label for a right-column
# value, which lost `project` and `location` on printed pages.
W_DY = 3.0
W_DX = 2.2

# A value written ABOVE its label is essentially impossible on these forms
# (handwriting drops into the cell). Penalise it heavily rather than forbidding
# it outright, so a slightly high-sitting typed value can still be matched.
ABOVE_PENALTY = 6.0

# How far above its label a value may sit before the penalty applies.
#
# Measured: on IOCLMS MAY 2026 p3 the box 'SAFETY SUPERVISOR' sits 0.30 label-
# heights above the EMPLOYEE CODE label, just inside the old -0.35 cutoff, so
# employee_code won it at cost 3.21 and took BOTH the title and the code while
# designation was starved and came back empty.
# Measured sweep (49 pages): -0.35 and -0.30 give designation 19/24; -0.28
# through -0.10 all give 20/24 with day-status and employee-name unchanged.
# The conservative end of that plateau is taken.
ABOVE_TOLERANCE = -0.25


def pair_cost(anchor: TextBox, value: TextBox) -> float | None:
    """Cost of claiming that `anchor` owns `value`. None = impossible."""
    # A label never owns something to its left.
    if value.x0 < anchor.x1 - (anchor.y1 - anchor.y0) * 0.2:
        return None

    a_h = max(1.0, float(anchor.y1 - anchor.y0))
    a_cy = (anchor.y0 + anchor.y1) / 2.0

    dy = (value.cy - a_cy) / a_h          # in label-heights, signed
    dx = (value.x0 - anchor.x1) / a_h     # in label-heights, always >= ~0

    # Too far vertically to be the same row at all.
    if abs(dy) > 1.6:
        return None

    cost = W_DY * abs(dy) + W_DX * dx
    if dy < ABOVE_TOLERANCE:              # value sits above its label
        cost += ABOVE_PENALTY
    return cost


def assign(anchors: dict[str, TextBox], values: Iterable[TextBox]
           ) -> dict[str, list[TextBox]]:
    """Globally assign each value box to at most one label.

    Greedy over the cost matrix: repeatedly take the cheapest surviving
    (label, value) pair and remove that value from consideration. Labels may
    take several values (a name can be split across boxes); a value is claimed
    once and once only, which is what stops the bleed.
    """
    values = list(values)
    pairs: list[tuple[float, str, int]] = []
    for fieldname, anc in anchors.items():
        for i, v in enumerate(values):
            c = pair_cost(anc, v)
            if c is not None:
                pairs.append((c, fieldname, i))
    pairs.sort(key=lambda p: p[0])

    taken: set[int] = set()
    out: dict[str, list[TextBox]] = {k: [] for k in anchors}
    for _cost, fieldname, i in pairs:
        if i in taken:
            continue
        taken.add(i)
        out[fieldname].append(values[i])

    for k in out:
        out[k].sort(key=lambda b: b.x0)
    return out
