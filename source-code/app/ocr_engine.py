"""OCR + spatial layout reconstruction.

WHY THIS IS NOT JUST "RUN OCR"
------------------------------
An OCR engine returns a flat list of text boxes with coordinates. It has no
idea that this page is a table, which column a number sits in, or that the "08"
at (412, 730) is the Normal Hours for day 14. Reconstructing that structure is
where the accuracy of the whole system is won or lost -- a value read perfectly
but assigned to the wrong row is exactly as damaging as a misread digit.

These timesheets are *ruled forms*: the grid is printed. That is a large gift,
because we can recover the exact cell geometry from the printed lines with
classical computer vision -- deterministically, in milliseconds, with no model
and no possibility of hallucination. We then drop the OCR boxes into that
geometry.

TERMS
-----
morphological opening   An image operation that erases everything that doesn't
                        match a given shape. Sliding a long thin horizontal bar
                        over the page keeps only long horizontal lines and
                        deletes text, which is how we isolate the grid.
kernel                  The shape used for that operation.
connected component     A blob of touching pixels, treated as one object.
IoU / overlap           How much two rectangles share area; used to decide
                        which cell a text box belongs to.
confidence              The OCR engine's own 0..1 estimate that it read a box
                        correctly. We propagate this per-cell so downstream
                        validation knows which values are shaky.
"""
from __future__ import annotations

import os
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from . import config


@dataclass
class TextBox:
    text: str
    conf: float
    x0: int
    y0: int
    x1: int
    y1: int

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2


@dataclass
class Cell:
    row: int
    col: int
    x0: int
    y0: int
    x1: int
    y1: int
    boxes: list[TextBox] = field(default_factory=list)

    @property
    def text(self) -> str:
        # Left-to-right within the cell; a cell can legitimately hold two boxes
        # (e.g. "9" and ":30" split by the detector).
        return " ".join(b.text for b in sorted(self.boxes, key=lambda b: b.x0)).strip()

    @property
    def conf(self) -> float:
        """Weakest box wins. A cell is only as trustworthy as its worst part --
        averaging would let one confident token mask an unreadable one."""
        return min((b.conf for b in self.boxes), default=0.0)


# ---------------------------------------------------------------------------
# OCR
# ---------------------------------------------------------------------------

_ENGINE = None


# D-073. RapidOCR runs a text-direction classifier that decides, per detected
# line, whether it is upright or upside down. On a timesheet most cells hold
# three to five characters -- "09:00", "18:00", "8" -- and a short numeric
# string is very nearly symmetric under a 180 degree turn, so the classifier
# flips a large share of them. The recogniser then reads the flipped crop and
# returns a string that is the original reversed with each glyph rotated:
#
#       09:00  ->  00:60        (0->0, 9->6, read right to left)
#       18:00  ->  100:80
#
# Measured on one page (t005, WABTEC, 31 rows of 09:00 and 18:00):
#       classifier on    '00:60' x61, '09:00' x23, '100:80' x2
#       classifier off   '00:60' x0,  '09:00' x84, '100:80' x0
#
# Turning it off is safe here because page orientation is already handled
# twice over, and better: app/preprocess deskews every page, and the pipeline
# retries all four 90-degree rotations when a page yields no anchors at all.
# The per-line classifier adds nothing those two do not, and it is the single
# largest source of unreadable clock times in the corpus.
OCR_USE_CLS = os.getenv("TS_OCR_USE_CLS", "0") == "1"

_ENGINE = None


def _engine():
    global _ENGINE
    if _ENGINE is None:
        from rapidocr import RapidOCR
        params: dict[str, Any] = {"Global.use_cls": OCR_USE_CLS}
        # TS_OCR_THREADS caps onnxruntime's intra-op threads. Default (-1) is
        # every core; with 3 batch workers that is 3x oversubscription and a
        # very warm laptop. Unset = library default, so the product and the
        # single-process harnesses are untouched.
        _n = os.getenv("TS_OCR_THREADS")
        if _n and _n.isdigit():
            params["EngineConfig.onnxruntime.intra_op_num_threads"] = int(_n)
            params["EngineConfig.onnxruntime.inter_op_num_threads"] = 1
        _ENGINE = RapidOCR(params=params)
    return _ENGINE


def run_ocr(image_path: str | Path) -> list[TextBox]:
    res = _engine()(str(image_path))
    out: list[TextBox] = []
    if res is None or getattr(res, "boxes", None) is None:
        return out
    boxes = res.boxes
    txts = res.txts if res.txts is not None else []
    scores = res.scores if res.scores is not None else []
    for i, quad in enumerate(boxes):
        pts = np.asarray(quad, dtype=float).reshape(-1, 2)
        x0, y0 = pts[:, 0].min(), pts[:, 1].min()
        x1, y1 = pts[:, 0].max(), pts[:, 1].max()
        text = str(txts[i]) if i < len(txts) else ""
        conf = float(scores[i]) if i < len(scores) else 0.0
        if not text.strip():
            continue
        out.append(TextBox(text.strip(), conf, int(x0), int(y0), int(x1), int(y1)))
    return out


def confidence_profile(boxes: list[TextBox]) -> dict[str, float]:
    """Statistics used to route the page. p25 is the load-bearing one: it
    describes the weakest quarter of readings, where errors concentrate."""
    if not boxes:
        return {"n": 0, "mean": 0.0, "p25": 0.0, "frac_low": 1.0}
    s = [b.conf for b in boxes]
    return {
        "n": len(s),
        "mean": float(np.mean(s)),
        "p25": float(np.percentile(s, 25)),
        "frac_low": float(sum(1 for v in s if v < 0.8) / len(s)),
    }


# Thresholds sit in the empty gap measured between typed (p25 >= 0.993) and
# handwritten (p25 = 0.777) pages -- not on the edge of either cluster, so
# ordinary variation cannot flip a page across the boundary.
# See docs/03-page-routing.md.
P25_CONFIDENT = 0.90
FRAC_LOW_MAX = 0.15


def route_from_profile(prof: dict[str, float]) -> str:
    if prof["n"] == 0:
        return "unreadable"
    if prof["p25"] >= P25_CONFIDENT and prof["frac_low"] <= FRAC_LOW_MAX:
        return "confident"
    return "needs_escalation"


# ---------------------------------------------------------------------------
# Grid detection
# ---------------------------------------------------------------------------

def _binary(gray: np.ndarray) -> np.ndarray:
    # Adaptive threshold rather than global Otsu: these are phone photos with
    # uneven lighting, where a single global cut-off eats whole regions.
    return cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C,
                                 cv2.THRESH_BINARY_INV, 25, 15)


def _lines(bw: np.ndarray, horizontal: bool, min_frac: float = 0.30) -> list[int]:
    """Find the printed rules by morphological opening with a long thin kernel.

    A kernel 30% of the page wide keeps only structures that long -- i.e. table
    rules -- and deletes text entirely. Deterministic, no model, milliseconds.
    """
    h, w = bw.shape
    length = max(12, int((w if horizontal else h) * min_frac))
    ksize = (length, 1) if horizontal else (1, length)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, ksize)
    opened = cv2.morphologyEx(bw, cv2.MORPH_OPEN, kernel, iterations=1)

    # Project to 1-D and take peaks: a row/column of the image that is mostly
    # ink after opening is a rule.
    axis = 1 if horizontal else 0
    proj = (opened > 0).sum(axis=axis)
    limit = (w if horizontal else h)
    thresh = max(10, int(limit * min_frac * 0.6))
    idx = np.where(proj > thresh)[0]
    if idx.size == 0:
        return []

    # Collapse runs of adjacent indices into one line each.
    groups, start, prev = [], int(idx[0]), int(idx[0])
    for i in idx[1:]:
        i = int(i)
        if i - prev > 3:
            groups.append((start + prev) // 2)
            start = i
        prev = i
    groups.append((start + prev) // 2)
    return groups


# Rule length varies enormously by layout, so a single fixed threshold cannot
# work. Measured on real pages:
#   IOCL30      vertical rules span ~58% of page height
#   KBR02       the table is only a few rows tall -> rules span ~22%
#   SAFEARTH01  page is curved, so a straight kernel matches almost nothing
# We therefore search from strict to permissive and stop at the first scale
# that yields a plausible grid. Strict-first matters: a permissive kernel also
# picks up long runs of text as "lines", so we only loosen when we must.
_LINE_SCALES = (0.30, 0.18, 0.12, 0.08)


def detect_grid(image_path: str | Path) -> tuple[list[int], list[int]]:
    """Return (row_boundaries_y, col_boundaries_x)."""
    raw = cv2.imdecode(np.fromfile(str(image_path), dtype=np.uint8),
                       cv2.IMREAD_GRAYSCALE)
    if raw is None:
        return [], []
    bw = _binary(raw)

    best: tuple[list[int], list[int]] = ([], [])
    for frac in _LINE_SCALES:
        rows = _lines(bw, horizontal=True, min_frac=frac)
        cols = _lines(bw, horizontal=False, min_frac=frac)
        if len(rows) > len(best[0]) or len(cols) > len(best[1]):
            best = (rows if len(rows) >= len(best[0]) else best[0],
                    cols if len(cols) >= len(best[1]) else best[1])
        # A usable timesheet grid needs many rows and at least a few columns.
        if len(rows) >= 8 and len(cols) >= 3:
            return rows, cols
    return best


# Upper bound on how many horizontal rules a real timesheet can have.
#
# A permissive kernel matches long runs of handwriting as well as printed
# rules, so "more lines" stops meaning "more detail" past a point. The bound
# comes from the form, not from tuning: a 31-day grid has 32 row boundaries,
# the header block ~5 and the summary block ~10, so ~50 is the physical
# ceiling and anything beyond it is ink.
#
# Measured sensitivity (49 pages, day-status accuracy):
#     44 -> 59.0%   48 -> 61.1%   50 -> 66.6%   52 -> 72.5%
#     55 -> 70.3%   58 -> 70.1%   62 -> 70.0%   66 -> 67.9%
# The 50 -> 52 step is a cliff rather than a slope, so this value is load-
# bearing. It is not a one-page artifact: 12 of 49 pages select a different
# rule set at 52 than at 55.
ROW_RULE_CEILING = 52


def detect_row_rules(image_path: str | Path) -> list[int]:
    """Horizontal rules only, chosen for ROW banding rather than cell building.

    detect_grid() stops at the first kernel scale where `rows >= 8 and
    cols >= 3`. That is the right stopping rule for building cells, and the
    wrong one for finding row boundaries: it returns whatever the strictest
    passing scale happened to see, which on a faintly-printed page was 13 rules
    for a 30-row grid.

    Here every scale is tried and the richest plausible set is kept. "Plausible"
    is bounded above as well as below -- a permissive kernel also matches long
    runs of handwriting, so a set of 80 "rules" on a 30-row form is noise, not
    detail.
    """
    raw = cv2.imdecode(np.fromfile(str(image_path), dtype=np.uint8),
                       cv2.IMREAD_GRAYSCALE)
    if raw is None:
        return []
    bw = _binary(raw)
    best: list[int] = []
    for frac in _LINE_SCALES:
        rows = _lines(bw, horizontal=True, min_frac=frac)
        if len(rows) > ROW_RULE_CEILING:
            continue
        if len(rows) > len(best):
            best = rows
    return best


def detect_row_rules_in(image_path: str | Path, x0: int, x1: int) -> list[int]:
    """Horizontal rules inside ONE column band [x0, x1) of the page.

    detect_row_rules() scans the full width, so a rule must span most of
    the page to count. On a form whose date column and value grid are
    vertically offset (GRSE01: the middle header block is three lines tall,
    so the value rows start ~0.75 row below the date rows), the page-wide
    rules describe neither column, and every value lands one band late.
    Detecting rules per column, then pairing the two sets by ordinal, is
    the structural fix (decision log D-021). Same scale search, same
    ceiling; min_frac is relative to the crop width.
    """
    raw = cv2.imdecode(np.fromfile(str(image_path), dtype=np.uint8),
                       cv2.IMREAD_GRAYSCALE)
    if raw is None:
        return []
    x0 = max(0, int(x0)); x1 = min(raw.shape[1], int(x1))
    if x1 - x0 < 8:
        return []
    bw = _binary(raw[:, x0:x1])
    best: list[int] = []
    for frac in _LINE_SCALES:
        rows = _lines(bw, horizontal=True, min_frac=frac)
        if len(rows) > ROW_RULE_CEILING:
            continue
        if len(rows) > len(best):
            best = rows
    return best


def build_cells(rows: list[int], cols: list[int]) -> list[Cell]:
    cells: list[Cell] = []
    for r in range(len(rows) - 1):
        for c in range(len(cols) - 1):
            cells.append(Cell(r, c, cols[c], rows[r], cols[c + 1], rows[r + 1]))
    return cells


def assign_boxes(cells: list[Cell], boxes: list[TextBox]) -> list[TextBox]:
    """Drop each text box into the cell containing its centre.

    Using the centre rather than any overlap is deliberate: a box that slightly
    crosses a rule (very common with handwriting) still lands in exactly one
    cell, so a value can never be double-counted into two columns.
    """
    unassigned: list[TextBox] = []
    for b in boxes:
        placed = False
        for cell in cells:
            if cell.x0 <= b.cx < cell.x1 and cell.y0 <= b.cy < cell.y1:
                cell.boxes.append(b)
                placed = True
                break
        if not placed:
            unassigned.append(b)
    return unassigned


# ---------------------------------------------------------------------------
# Fallback: no usable grid
# ---------------------------------------------------------------------------

def cluster_rows(boxes: list[TextBox], tol_frac: float = 0.6) -> list[list[TextBox]]:
    """Group boxes into visual rows by vertical position.

    Used when grid detection fails (unruled form, heavy warping, torn scan).
    Tolerance is derived from the median box height so it adapts to page scale
    instead of assuming a DPI.
    """
    if not boxes:
        return []
    heights = [b.y1 - b.y0 for b in boxes if b.y1 > b.y0]
    tol = max(6.0, statistics.median(heights) * tol_frac) if heights else 10.0

    ordered = sorted(boxes, key=lambda b: b.cy)
    rows: list[list[TextBox]] = [[ordered[0]]]
    for b in ordered[1:]:
        if abs(b.cy - statistics.mean(x.cy for x in rows[-1])) <= tol:
            rows[-1].append(b)
        else:
            rows.append([b])
    for r in rows:
        r.sort(key=lambda b: b.x0)
    return rows


def analyse(image_path: str | Path) -> dict[str, Any]:
    """Full spatial analysis of one page: OCR, routing profile, grid, cells."""
    boxes = run_ocr(image_path)
    prof = confidence_profile(boxes)
    rows, cols = detect_grid(image_path)

    grid_ok = len(rows) >= 5 and len(cols) >= 3
    cells: list[Cell] = []
    unassigned: list[TextBox] = []
    if grid_ok:
        cells = build_cells(rows, cols)
        unassigned = assign_boxes(cells, boxes)
        # If most text failed to land in a cell the grid is wrong, not the text.
        if len(unassigned) > 0.5 * max(len(boxes), 1):
            grid_ok = False
            cells = []

    return {
        "boxes": boxes,
        "profile": prof,
        "route": route_from_profile(prof),
        "grid": {"rows": rows, "cols": cols, "ok": grid_ok},
        "cells": [c for c in cells if c.boxes],
        "unassigned": unassigned,
        "row_clusters": cluster_rows(boxes) if not grid_ok else [],
    }
