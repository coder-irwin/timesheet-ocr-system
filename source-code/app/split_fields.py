"""Multi-value cell parsing.

WHY
---
Some layouts pack several numbers into one labelled cell:

    Samsung:  "Calendar Days | Total Working"   ->  "30 | 21"
              "Worked | Off Days"                ->  "17 | 4"
              "ABS | LWP | LEA"                  ->  "0 | 0 | 4"

Anchor extraction finds the label and the value fine, but the value is a
compound. Without splitting it, the Samsung layout has NO extractable totals at
all -- which is why Samsung pages were detected correctly but still produced no
summary. Measured: 10% of the corpus is this layout.

The separator is unreliable after OCR. A vertical bar is read as `|`, `l`, `I`,
`1`, `/` or simply dropped, so we cannot split on a fixed character. Instead we
pull out the NUMBERS in order and assign them positionally to the field names
the profile declared. That is robust to whatever the separator degraded into.

TERMS
-----
compound cell   one cell holding several values ("30 | 21")
positional      the Nth number found maps to the Nth declared field name
"""
from __future__ import annotations

import re
from typing import Any

# Numbers, including decimals. Deliberately does NOT match a lone separator.
_NUM = re.compile(r"\d+(?:\.\d+)?")


def split_numbers(text: str, field_names: tuple[str, ...]) -> dict[str, str]:
    """Assign the numbers found in `text` to `field_names`, in order.

    Returns only the fields actually found, so a partially-read cell degrades
    to partial data rather than to wrong data.

        "30 | 21"  + ("period_days", "total_present_days")
            -> {"period_days": "30", "total_present_days": "21"}

        "0|0|4"    + ("total_absent_days", "total_lwp", "total_leave_days")
            -> {"total_absent_days": "0", "total_lwp": "0",
                "total_leave_days": "4"}
    """
    if not text:
        return {}
    nums = _NUM.findall(str(text))
    out: dict[str, str] = {}
    for name, val in zip(field_names, nums):
        out[name] = val
    return out


def apply_splits(summary: dict[str, Any],
                 split_spec: dict[str, tuple[str, ...]]) -> dict[str, Any]:
    """Expand every compound field in `summary` according to `split_spec`.

    The compound key is removed once expanded, so downstream code only ever
    sees the atomic fields it knows about.
    """
    if not split_spec:
        return summary
    out = dict(summary)
    for compound_key, targets in split_spec.items():
        raw = out.get(compound_key)
        if not raw:
            continue
        parts = split_numbers(str(raw), targets)
        for k, v in parts.items():
            # Never clobber a value that was read directly from its own label.
            if not out.get(k):
                out[k] = v
        out.pop(compound_key, None)
    return out


# ---------------------------------------------------------------------------
# Totals-row extraction (KBR / Samsung)
# ---------------------------------------------------------------------------

def totals_row_values(boxes, row_label_patterns: tuple[str, ...],
                      column_ranges: dict[str, tuple[float, float]]
                      ) -> dict[str, str]:
    """Read a horizontal TOTAL row by intersecting it with the learned columns.

    Samsung and KBR both put their totals in a final row labelled "Total"
    rather than in a labelled summary block. There is no per-value label, so
    the only way to know which number is which is by the column it sits under
    -- which is exactly the geometry `learn_columns` already recovered.
    """
    from .aarvi_form import _matches

    label_box = None
    for b in boxes:
        if _matches(b.text, row_label_patterns) >= 88 and len(b.text.strip()) <= 12:
            # Prefer the lowest such row: "Total" also appears in column headers.
            if label_box is None or b.cy > label_box.cy:
                label_box = b
    if label_box is None:
        return {}

    band = max(12, (label_box.y1 - label_box.y0)) * 0.9
    out: dict[str, str] = {}
    for b in boxes:
        if b is label_box or abs(b.cy - label_box.cy) > band:
            continue
        if not _NUM.search(b.text):
            continue
        for fieldname, (x0, x1) in column_ranges.items():
            if x0 <= b.cx <= x1:
                m = _NUM.search(b.text)
                if m and not out.get(fieldname):
                    out[fieldname] = m.group(0)
                break
    return out
