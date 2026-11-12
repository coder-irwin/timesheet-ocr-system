"""Architecture diagrams for the technical documentation.

Drawn with matplotlib rather than hand-waved in ASCII, so the shapes, layers
and data flow in the document match the code they describe. Every diagram is
generated from this file, so when the architecture changes the picture can be
regenerated rather than redrawn.

    python tools/doc_diagrams.py          # writes docs/diagrams/*.png
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.patches as mpatches                          # noqa: E402
import matplotlib.pyplot as plt                                # noqa: E402

BASE = Path(__file__).parent.parent
OUT = BASE / "docs" / "diagrams"

# A restrained palette: one accent, greys for structure, red only for danger.
INK = "#1f2933"
BOX = "#e8eef4"
EDGE = "#5b7c99"
ACCENT = "#2b6cb0"
WARN = "#c05621"
OK = "#2f855a"
MUTED = "#8a99a8"


def _box(ax, x, y, w, h, text, fc=BOX, ec=EDGE, fs=9, bold=False, tc=INK):
    ax.add_patch(mpatches.FancyBboxPatch(
        (x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.06",
        linewidth=1.2, facecolor=fc, edgecolor=ec))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center",
            fontsize=fs, color=tc, wrap=True,
            fontweight="bold" if bold else "normal")


def _arrow(ax, x1, y1, x2, y2, text="", color=EDGE, style="-|>", fs=7.5):
    ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(arrowstyle=style, color=color, lw=1.3,
                                shrinkA=2, shrinkB=2))
    if text:
        # Opaque background: on a diagonal arrow the line runs straight
        # through the label and reads as a strikethrough without it.
        ax.text((x1 + x2) / 2, (y1 + y2) / 2 + 0.06, text, ha="center",
                va="bottom", fontsize=fs, color=MUTED, zorder=5,
                bbox=dict(facecolor="white", edgecolor="none",
                          boxstyle="round,pad=0.22"))


def _canvas(w=12, h=6.5):
    fig, ax = plt.subplots(figsize=(w, h))
    ax.set_xlim(0, 12); ax.set_ylim(0, h)
    ax.axis("off")
    return fig, ax


def d1_context():
    """Who touches the system and what crosses the boundary."""
    fig, ax = _canvas(12, 5.6)
    ax.text(6, 5.25, "Figure 1 — System Context", ha="center",
            fontsize=13, fontweight="bold", color=INK)
    _box(ax, 0.3, 3.4, 2.4, 1.1, "Site supervisor\nwrites the sheet by hand",
         fc="#fff", fs=9)
    _box(ax, 0.3, 1.6, 2.4, 1.1, "Office staff\nphotograph / scan", fc="#fff")
    _box(ax, 4.2, 2.2, 3.6, 2.4,
         "TIMESHEET EXTRACTION\n& VALIDATION\n\nruns entirely on the\nclient's own server",
         fc=BOX, ec=ACCENT, bold=True, fs=10)
    _box(ax, 9.3, 3.4, 2.4, 1.1, "Reviewer\nconfirms flagged pages", fc="#fff")
    _box(ax, 9.3, 1.6, 2.4, 1.1, "Payroll / Finance\nreceive the Excel", fc="#fff")
    _arrow(ax, 2.7, 3.95, 4.2, 3.6, "paper")
    _arrow(ax, 2.7, 2.15, 4.2, 3.0, "PDF / JPG upload")
    _arrow(ax, 7.8, 3.6, 9.3, 3.95, "flagged pages")
    _arrow(ax, 7.8, 3.0, 9.3, 2.15, "6-sheet workbook")
    ax.text(6, 1.35, "No cloud • no API keys • no per-page cost • data never leaves the network",
            ha="center", fontsize=8.5, color=OK, style="italic")
    ax.set_ylim(1.05, 5.5)
    fig.savefig(OUT / "01_context.png", dpi=200, bbox_inches="tight")
    plt.close(fig)


def d2_pipeline():
    """The nine stages a page passes through."""
    fig, ax = _canvas(13, 4.4)
    ax.set_xlim(0, 13)
    ax.text(6.5, 4.05, "Figure 2 — Processing Pipeline (one page)",
            ha="center", fontsize=13, fontweight="bold", color=INK)
    stages = [
        ("Ingest", "PDF split\nimage load"),
        ("Preprocess", "deskew\nflatten\nresize"),
        ("OCR", "PP-OCRv6\nboxes + conf"),
        ("Route", "typed vs\nhandwritten"),
        ("Extract", "anchors\ncolumns\nday grid"),
        ("Reconcile", "calendar\nstated totals"),
        ("Validate", "checksums\nbounds\nroster"),
        ("Status", "clean / review\n/ needs review"),
        ("Export", "6-sheet\nworkbook"),
    ]
    w, gap = 1.24, 0.15
    x = 0.25
    for i, (title, sub) in enumerate(stages):
        fc = BOX if i not in (6, 7) else "#fdf3e7"
        _box(ax, x, 1.9, w, 1.25, f"{title}\n\n{sub}", fc=fc, fs=7.6, bold=False)
        ax.text(x + w / 2, 3.32, str(i + 1), ha="center", fontsize=8,
                color=ACCENT, fontweight="bold")
        if i:
            _arrow(ax, x - gap - 0.02, 2.52, x - 0.02, 2.52)
        x += w + gap
    ax.text(6.5, 1.35,
            "DESIGN RULE: no page may fall through — every branch ends in a record plus a status",
            ha="center", fontsize=9, color=WARN, fontweight="bold")
    ax.text(6.5, 0.95,
            "A stage that fails marks the page for review with the reason attached; it is never dropped, never silently emitted as clean.",
            ha="center", fontsize=8, color=MUTED)
    fig.savefig(OUT / "02_pipeline.png", dpi=200, bbox_inches="tight")
    plt.close(fig)


def d3_modules():
    """Module dependency layers."""
    fig, ax = _canvas(12, 7.0)
    ax.text(6, 6.75, "Figure 3 — Module Architecture (layered)",
            ha="center", fontsize=13, fontweight="bold", color=INK)
    ax.text(6, 6.42, "dependencies point downwards only; no lower layer imports from a higher one",
            ha="center", fontsize=8.5, color=MUTED, style="italic")
    layers = [
        (5.05, "Interface", ["main.py  (FastAPI)", "web/index.html", "db.py"], "#eaf2fb"),
        (3.90, "Orchestration", ["pipeline.py", "eventlog.py"], "#e8eef4"),
        (2.75, "Understanding",
         ["aarvi_form.py", "generic_grid.py", "field_typing.py", "reconcile.py"], "#eef4ea"),
        (1.60, "Perception", ["ocr_engine.py", "preprocess.py", "vlm_header.py"], "#f7f0ea"),
        (0.45, "Knowledge",
         ["roster.py", "vocab.py", "templates_spec.py", "form_profiles.py", "validate.py"],
         "#f4eef4"),
    ]
    for y, name, mods, fc in layers:
        _box(ax, 0.25, y, 1.85, 0.95, name, fc="#fff", ec=MUTED, fs=8.8, bold=True)
        x = 2.45
        for m in mods:
            w = max(1.35, 0.105 * len(m))
            _box(ax, x, y, w, 0.95, m, fc=fc, fs=7.5)
            x += w + 0.10
    # Dependency arrows live in the gutter between the label column and the
    # modules, so they cannot land on top of a box.
    for y in (5.05, 3.90, 2.75, 1.60):
        _arrow(ax, 2.27, y, 2.27, y - 0.20, color=MUTED)
    fig.savefig(OUT / "03_modules.png", dpi=200, bbox_inches="tight")
    plt.close(fig)


def d4_extraction():
    """How a day grid is recovered - the core algorithm."""
    fig, ax = _canvas(12, 6.2)
    ax.text(6, 5.85, "Figure 4 — Day-Grid Recovery (the core algorithm)",
            ha="center", fontsize=13, fontweight="bold", color=INK)
    _box(ax, 0.4, 4.4, 2.6, 0.95, "OCR text boxes\n(text, x, y, confidence)", fc="#fff")
    _box(ax, 0.4, 3.1, 2.6, 0.95, "Printed rules\n(morphology, no model)", fc="#fff")
    _box(ax, 3.6, 3.75, 2.6, 1.6,
         "Row bands\n\nrules if regular,\nelse ink clustering\nby row pitch", fc=BOX)
    _box(ax, 6.8, 4.5, 2.4, 0.85, "Learn columns\nfrom printed headers", fc=BOX)
    _box(ax, 6.8, 3.4, 2.4, 0.85, "Infer missing\ncolumns by order", fc=BOX)
    _box(ax, 9.6, 3.9, 2.1, 1.4, "Day rows\n\nday -> cells", fc="#eef4ea", ec=OK)
    _arrow(ax, 3.0, 4.85, 3.6, 4.7)
    _arrow(ax, 3.0, 3.55, 3.6, 4.1)
    _arrow(ax, 6.2, 4.7, 6.8, 4.9)
    _arrow(ax, 6.2, 4.3, 6.8, 3.8)
    _arrow(ax, 9.2, 4.9, 9.6, 4.7)
    _arrow(ax, 9.2, 3.8, 9.6, 4.2)
    ax.text(6, 2.75, "THE INSIGHT THAT DRIVES EVERY GAIN", ha="center",
            fontsize=10, fontweight="bold", color=ACCENT)
    ax.text(6, 1.95,
            "Read the printed FORM, not the handwriting.\n"
            "Row boundaries come from printed rules, not ink clustering.  Column positions come from the form's\n"
            "fixed left-to-right order when a header is unreadable.  Row count comes from the calendar (a month has <= 31 rows).",
            ha="center", fontsize=8.6, color=INK)
    ax.text(6, 1.15,
            "The handwriting is the unreliable part of these pages. The pre-printed structure is not.",
            ha="center", fontsize=9, color=WARN, style="italic", fontweight="bold")
    ax.set_ylim(0.85, 6.2)
    fig.savefig(OUT / "04_extraction.png", dpi=200, bbox_inches="tight")
    plt.close(fig)


def d5_safety():
    """Status lattice and the escaped-error guarantee."""
    fig, ax = _canvas(12, 5.6)
    ax.set_ylim(0.75, 5.6)
    ax.text(6, 5.25, "Figure 5 — Validation & the Safety Guarantee",
            ha="center", fontsize=13, fontweight="bold", color=INK)
    _box(ax, 0.4, 3.5, 2.5, 1.1, "Extracted record", fc="#fff")
    checks = ["row-sum vs stated total", "day counts vs calendar",
              "OT / hours bounds", "roster identity match",
              "OCR confidence floors"]
    y = 4.5
    for c in checks:
        _box(ax, 3.4, y, 3.1, 0.42, c, fc=BOX, fs=7.6)
        y -= 0.52
    _arrow(ax, 2.9, 4.05, 3.4, 4.05)
    _box(ax, 7.2, 4.15, 2.0, 0.62, "clean", fc="#e6f4ea", ec=OK, fs=9, bold=True)
    _box(ax, 7.2, 3.35, 2.0, 0.62, "review_optional", fc="#fdf6e3", ec=WARN, fs=8.5)
    _box(ax, 7.2, 2.55, 2.0, 0.62, "needs_review", fc="#fdeaea", ec="#c53030",
         fs=9, bold=True)
    for yy in (4.46, 3.66, 2.86):
        _arrow(ax, 6.5, 3.9, 7.2, yy)
    _box(ax, 9.7, 2.9, 2.1, 1.6,
         "MEASURED\n\n256 imperfect pages\n256 flagged\n\n0 escaped",
         fc="#e6f4ea", ec=OK, fs=8.5, bold=True)
    _arrow(ax, 9.2, 3.7, 9.7, 3.7, color=OK)
    ax.text(6, 1.75,
            "A wrong value that is FLAGGED costs a reviewer thirty seconds.\n"
            "A wrong value that is SILENT pays the wrong person.",
            ha="center", fontsize=9.5, color=INK, fontweight="bold")
    ax.text(6, 1.05,
            "This is why the roster refuses to choose between two similar names, and why every inference is marked.",
            ha="center", fontsize=8.4, color=MUTED)
    fig.savefig(OUT / "05_safety.png", dpi=200, bbox_inches="tight")
    plt.close(fig)


def d6_deployment():
    """Container topology and persistence."""
    fig, ax = _canvas(12, 5.4)
    ax.text(6, 5.05, "Figure 6 — Deployment Topology",
            ha="center", fontsize=13, fontweight="bold", color=INK)
    ax.add_patch(mpatches.FancyBboxPatch(
        (0.5, 0.7), 6.6, 3.9, boxstyle="round,pad=0.05", linewidth=1.4,
        facecolor="#f7fafc", edgecolor=ACCENT, linestyle="--"))
    ax.text(3.8, 4.35, "Client server (Linux / Windows / Mac)",
            ha="center", fontsize=9.5, color=ACCENT, fontweight="bold")
    ax.add_patch(mpatches.FancyBboxPatch(
        (0.9, 1.9), 5.8, 2.1, boxstyle="round,pad=0.04", linewidth=1.2,
        facecolor="#eaf2fb", edgecolor=EDGE))
    ax.text(3.8, 3.75, "Docker container  timesheet-app:2.0.0",
            ha="center", fontsize=8.6, fontweight="bold", color=INK)
    _box(ax, 1.2, 2.9, 1.6, 0.65, "uvicorn\nFastAPI", fc="#fff", fs=7.6)
    _box(ax, 3.0, 2.9, 1.6, 0.65, "4 worker\nthreads", fc="#fff", fs=7.6)
    _box(ax, 4.8, 2.9, 1.6, 0.65, "PP-OCRv6\nbaked in", fc="#fff", fs=7.6)
    _box(ax, 1.2, 2.05, 5.2, 0.6, "read-only image — no network needed at runtime",
         fc="#fff", fs=7.6, tc=MUTED)
    _box(ax, 0.9, 0.95, 5.8, 0.75,
         "/data volume  —  roster.csv · uploads · pages · cache · exports · timesheets.db",
         fc="#eef4ea", ec=OK, fs=7.8)
    _box(ax, 7.6, 3.2, 2.0, 0.8, "Browser\n(staff)", fc="#fff")
    _box(ax, 10.0, 3.2, 1.7, 0.8, "Excel\ndownload", fc="#fff")
    _arrow(ax, 7.6, 3.6, 7.15, 3.2, "HTTP :8077")
    _arrow(ax, 9.6, 3.6, 10.0, 3.6)
    ax.text(9.6, 1.9,
            "Back-up = copy the /data folder.\nThat is the entire backup.",
            ha="center", fontsize=8.4, color=OK)
    ax.set_ylim(0.55, 5.35)
    fig.savefig(OUT / "06_deployment.png", dpi=200, bbox_inches="tight")
    plt.close(fig)


def d7_accuracy():
    """Where accuracy is won and lost."""
    fig, ax = plt.subplots(figsize=(11, 4.6))
    labels = ["day status", "employee name", "designation"]
    share = [1025, 34, 31]
    ax2 = ax
    bars = ax2.barh(labels, share, color=[ACCENT, MUTED, MUTED], height=0.55)
    ax2.set_xlabel("comparisons in the 1,090-point evaluation", fontsize=9)
    ax2.set_title("Figure 7 — Where the accuracy actually lives",
                  fontsize=13, fontweight="bold", color=INK, pad=14)
    for b, v in zip(bars, share):
        ax2.text(v + 12, b.get_y() + b.get_height() / 2, f"{v}  ({v/1090:.0%})",
                 va="center", fontsize=9, color=INK)
    ax2.set_xlim(0, 1200)
    ax2.spines[["top", "right"]].set_visible(False)
    plt.tight_layout(rect=[0, 0.16, 1, 1])
    fig.text(0.5, 0.06,
             "A change adding 10 points to NAMES moves the total by 0.3.\n"
             "A change adding 10 points to DAY STATUS moves it by 9.4.   Work the grid.",
             ha="center", fontsize=9.5, color=WARN, fontweight="bold")
    plt.savefig(OUT / "07_accuracy_share.png", dpi=200, bbox_inches="tight")
    plt.close()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for fn in (d1_context, d2_pipeline, d3_modules, d4_extraction,
               d5_safety, d6_deployment, d7_accuracy,
               d8_upload_sequence, d9_review_sequence):
        fn()
        print(f"  {fn.__name__}")
    print(f"\nwrote {len(list(OUT.glob('*.png')))} diagrams to {OUT}")




def d8_upload_sequence():
    """Sequence: what happens when staff press Upload."""
    fig, ax = _canvas(12, 6.6)
    ax.text(6, 6.3, "Figure 8 — Upload and Processing Sequence",
            ha="center", fontsize=13, fontweight="bold", color=INK)
    actors = ["Browser", "FastAPI\n/api/batches", "preprocess", "worker\nqueue",
              "pipeline", "SQLite"]
    xs = [1.0, 3.0, 5.0, 7.0, 9.0, 11.0]
    for x, a in zip(xs, actors):
        _box(ax, x - 0.75, 5.5, 1.5, 0.6, a, fc=BOX, fs=7.6, bold=True)
        ax.plot([x, x], [0.5, 5.5], color=MUTED, lw=0.8, ls="--", zorder=0)
    steps = [
        (0, 1, 5.1, "POST multipart (N files)"),
        (1, 5, 4.75, "create batch"),
        (1, 2, 4.4, "prepare(file)"),
        (2, 2, 4.05, "split -> deskew -> flatten -> resize"),
        (1, 5, 3.7, "add_page(status=pending)"),
        (1, 3, 3.35, "enqueue page_id"),
        (1, 0, 3.0, "202: batch_id, page_ids"),
        (3, 4, 2.55, "process_page()"),
        (4, 4, 2.2, "OCR -> extract -> reconcile -> validate"),
        (4, 5, 1.85, "update_record(record, issues, status)"),
        (0, 1, 1.4, "GET /api/log  (poll)"),
        (1, 0, 1.05, "live progress"),
    ]
    for a, b, y, label in steps:
        if a == b:
            ax.annotate("", xy=(xs[a] + 0.45, y - 0.12), xytext=(xs[a], y + 0.06),
                        arrowprops=dict(arrowstyle="-|>", color=ACCENT, lw=1.1,
                                        connectionstyle="arc3,rad=-1.4"))
            ax.text(xs[a] + 0.6, y - 0.02, label, fontsize=7, color=INK, va="center")
        else:
            _arrow(ax, xs[a], y, xs[b], y, color=ACCENT if b > a else MUTED)
            ax.text((xs[a] + xs[b]) / 2, y + 0.08, label, ha="center",
                    fontsize=7, color=INK)
    ax.text(6, 0.25, "Ingest is synchronous inside the request; extraction is not. "
                     "See 27.2 for the known limitation on very large batches.",
            ha="center", fontsize=8, color=MUTED, style="italic")
    fig.savefig(OUT / "08_upload_sequence.png", dpi=200, bbox_inches="tight")
    plt.close(fig)


def d9_review_sequence():
    """Sequence: reviewer corrects a flagged page."""
    fig, ax = _canvas(12, 5.8)
    ax.text(6, 5.5, "Figure 9 — Review and Correction Sequence",
            ha="center", fontsize=13, fontweight="bold", color=INK)
    actors = ["Reviewer", "Review UI", "PUT /api/pages/{id}", "validate", "audit + DB"]
    xs = [1.2, 3.4, 6.0, 8.6, 10.9]
    for x, a in zip(xs, actors):
        _box(ax, x - 0.85, 4.7, 1.7, 0.6, a, fc=BOX, fs=7.4, bold=True)
        ax.plot([x, x], [0.6, 4.7], color=MUTED, lw=0.8, ls="--", zorder=0)
    steps = [
        (0, 1, 4.3, "open flagged page"),
        (1, 2, 3.95, "GET record + image"),
        (2, 1, 3.6, "image left, grid right"),
        (0, 1, 3.25, "edit a value"),
        (1, 2, 2.9, "PUT {record}"),
        (2, 4, 2.55, "diff old vs new -> audit each field"),
        (2, 3, 2.2, "re-validate the CORRECTED record"),
        (3, 2, 1.85, "issues[]"),
        (2, 4, 1.5, "update status: corrected | needs_review"),
        (2, 1, 1.15, "{status, changed, issues}"),
    ]
    for a, b, y, label in steps:
        _arrow(ax, xs[a], y, xs[b], y, color=ACCENT if b > a else MUTED)
        ax.text((xs[a] + xs[b]) / 2, y + 0.08, label, ha="center", fontsize=7,
                color=INK)
    ax.text(6, 0.3,
            "Re-validation on save is the point: a fix that breaks a checksum is caught here, not at invoice time.",
            ha="center", fontsize=8.2, color=WARN, fontweight="bold")
    fig.savefig(OUT / "09_review_sequence.png", dpi=200, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    main()
