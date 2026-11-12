"""Build the full technical documentation as a .docx.

Everything in here is drawn from the code and the measurements in this
repository. Where a number appears it was measured, and the document says how.
Where something was tried and rejected, that is recorded too -- a design
document that only lists what worked teaches the reader nothing about why the
design is shaped the way it is.

    python tools/doc_diagrams.py      # first, to (re)generate the figures
    python tools/build_tech_doc.py    # then this
"""
from __future__ import annotations

import sys
from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

BASE = Path(__file__).parent.parent
DIAG = BASE / "docs" / "diagrams"
OUT = BASE / "TIMESHEET-TECHNICAL-DOCUMENTATION.docx"

INK = RGBColor(0x1F, 0x29, 0x33)
ACCENT = RGBColor(0x2B, 0x6C, 0xB0)
MUTED = RGBColor(0x6B, 0x7A, 0x8A)
WARN = RGBColor(0xC0, 0x56, 0x21)
OK = RGBColor(0x2F, 0x85, 0x5A)


class Doc:
    def __init__(self):
        self.d = Document()
        self._styles()
        self._fig = 0
        self._tbl = 0

    # ---------------------------------------------------------------- setup
    def _styles(self):
        st = self.d.styles["Normal"]
        st.font.name = "Calibri"
        st.font.size = Pt(10.5)
        st.paragraph_format.space_after = Pt(6)
        st.paragraph_format.line_spacing = 1.15
        for name, size, color, bold in (
                ("Heading 1", 20, ACCENT, True),
                ("Heading 2", 15, INK, True),
                ("Heading 3", 12, INK, True),
                ("Heading 4", 11, MUTED, True)):
            s = self.d.styles[name]
            s.font.name = "Calibri"
            s.font.size = Pt(size)
            s.font.color.rgb = color
            s.font.bold = bold
            s.paragraph_format.space_before = Pt(14 if size > 14 else 10)
            s.paragraph_format.space_after = Pt(6)

    # ------------------------------------------------------------- elements
    def title_page(self):
        d = self.d
        for _ in range(6):
            d.add_paragraph()
        p = d.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run("TIMESHEET EXTRACTION\n& VALIDATION")
        r.font.size = Pt(30); r.font.bold = True; r.font.color.rgb = ACCENT
        p = d.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run("Complete Technical Documentation")
        r.font.size = Pt(15); r.font.color.rgb = INK
        p = d.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run("High-Level and Low-Level Design · System Architecture · "
                      "Algorithms · Operations")
        r.font.size = Pt(11); r.font.color.rgb = MUTED
        for _ in range(3):
            d.add_paragraph()
        t = d.add_table(rows=5, cols=2); t.alignment = WD_TABLE_ALIGNMENT.CENTER
        rows = [("Product", "Handwritten timesheet digitisation for AARVI Encon"),
                ("Pipeline version", "v24-hires-first"),
                ("Deployment", "timesheet-app:2.0.0 (Docker, offline)"),
                ("Runtime", "Python 3.12 · RapidOCR PP-OCRv6 · CPU-only"),
                ("Audience", "Engineers, reviewers, and the client's technical team")]
        for i, (k, v) in enumerate(rows):
            c0, c1 = t.rows[i].cells
            rr = c0.paragraphs[0].add_run(k); rr.bold = True; rr.font.size = Pt(9.5)
            rr2 = c1.paragraphs[0].add_run(v); rr2.font.size = Pt(9.5)
        d.add_page_break()

    def h1(self, text, page_break=True):
        if page_break:
            self.d.add_page_break()
        self.d.add_heading(text, level=1)

    def h2(self, text): self.d.add_heading(text, level=2)
    def h3(self, text): self.d.add_heading(text, level=3)

    def p(self, text, size=10.5, color=None, bold=False, italic=False):
        par = self.d.add_paragraph()
        r = par.add_run(text)
        r.font.size = Pt(size); r.bold = bold; r.italic = italic
        if color: r.font.color.rgb = color
        return par

    def bullets(self, items, numbered=False):
        for it in items:
            par = self.d.add_paragraph(
                style="List Number" if numbered else "List Bullet")
            if isinstance(it, tuple):
                r = par.add_run(it[0] + " "); r.bold = True; r.font.size = Pt(10.5)
                r2 = par.add_run(it[1]); r2.font.size = Pt(10.5)
            else:
                par.add_run(it).font.size = Pt(10.5)

    def code(self, text):
        par = self.d.add_paragraph()
        par.paragraph_format.left_indent = Inches(0.25)
        par.paragraph_format.space_before = Pt(4)
        par.paragraph_format.space_after = Pt(8)
        r = par.add_run(text)
        r.font.name = "Consolas"; r.font.size = Pt(8.5)
        r.font.color.rgb = RGBColor(0x2D, 0x37, 0x48)
        pPr = par._p.get_or_add_pPr()
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"), "clear"); shd.set(qn("w:fill"), "F4F6F8")
        pPr.append(shd)

    def callout(self, title, text, color=WARN):
        par = self.d.add_paragraph()
        par.paragraph_format.left_indent = Inches(0.2)
        par.paragraph_format.space_before = Pt(8)
        r = par.add_run(f"{title}  "); r.bold = True; r.font.color.rgb = color
        r.font.size = Pt(10.5)
        r2 = par.add_run(text); r2.font.size = Pt(10.5)
        pPr = par._p.get_or_add_pPr()
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"), "clear")
        shd.set(qn("w:fill"), "FFF8F0" if color == WARN else "F0F7F2")
        pPr.append(shd)

    def table(self, headers, rows, caption=None, widths=None):
        self._tbl += 1
        t = self.d.add_table(rows=1, cols=len(headers))
        t.style = "Light Grid Accent 1"
        for i, h in enumerate(headers):
            c = t.rows[0].cells[i]
            c.text = ""
            r = c.paragraphs[0].add_run(h); r.bold = True; r.font.size = Pt(9)
        for row in rows:
            cells = t.add_row().cells
            for i, v in enumerate(row):
                cells[i].text = ""
                r = cells[i].paragraphs[0].add_run(str(v)); r.font.size = Pt(9)
        if caption:
            p = self.d.add_paragraph()
            r = p.add_run(f"Table {self._tbl}. {caption}")
            r.italic = True; r.font.size = Pt(8.5); r.font.color.rgb = MUTED
        self.d.add_paragraph()
        return t

    def figure(self, filename, caption, width=6.6):
        path = DIAG / filename
        if not path.exists():
            self.p(f"[missing figure: {filename}]", color=WARN)
            return
        self.d.add_picture(str(path), width=Inches(width))
        self.d.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
        p = self.d.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run(caption)
        r.italic = True; r.font.size = Pt(8.5); r.font.color.rgb = MUTED

    def save(self):
        self.d.save(OUT)
        return OUT


def main() -> None:
    sys.path.insert(0, str(BASE / "tools"))
    import doc_content_a, doc_content_b, doc_content_c, doc_content_perf, doc_content_d, doc_content_e, doc_content_f, doc_content_g, doc_content_h, doc_content_i, doc_content_j, doc_content_k, doc_content_l

    D = Doc()
    D.title_page()
    doc_content_a.write(D)
    doc_content_b.write(D)
    doc_content_c.write(D)
    doc_content_perf.write(D)
    doc_content_d.write(D)
    doc_content_e.write(D)
    doc_content_f.write(D)
    doc_content_g.write(D)
    doc_content_h.write(D)
    doc_content_i.write(D)
    doc_content_j.write(D)
    doc_content_k.write(D)
    doc_content_l.write(D)
    path = D.save()
    size = path.stat().st_size / 1024
    print(f"  wrote {path.name}  ({size:.0f} KB)")
    print(f"  paragraphs: {len(D.d.paragraphs)}   tables: {len(D.d.tables)}   "
          f"figures: {len(D.d.inline_shapes)}")


if __name__ == "__main__":
    main()
