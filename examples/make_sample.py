#!/usr/bin/env python3
"""Generate a synthetic two-column scientific PDF using only the standard library.

Why hand-roll the PDF: the example must be reproducible on a machine with no reportlab,
and every glyph position has to be known exactly so `ground_truth.json` is a real
reference rather than a copy of the parser's own output.

The fixture deliberately contains the hazards the task names:
  * a full-width title/abstract above a two-column body (spanning element);
  * a paragraph that starts at the bottom of the left column and continues at the top
    of the right column (cross-column continuation);
  * a ruled table with a header row;
  * two numbered equations;
  * a running header and a page-number footer;
  * a references section.
"""
import json
import os
import zlib

PAGE_W, PAGE_H = 612.0, 792.0
COL_GUTTER = PAGE_W / 2
COL_L_X = 54.0
COL_R_X = 318.0
COL_W = 240.0


def esc(s):
    return s.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


class Page:
    def __init__(self):
        self.ops = []

    def text(self, x, y_top, s, size=10.0, bold=False, color=None):
        y = PAGE_H - y_top
        font = "/F2" if bold else "/F1"
        if color:
            self.ops.append("%.3f %.3f %.3f rg" % color)
        self.ops.append(
            "BT %s %.2f Tf %.2f %.2f Td (%s) Tj ET" % (font, size, x, y, esc(s))
        )
        if color:
            self.ops.append("0 0 0 rg")

    def line(self, x0, y0_top, x1, y1_top, w=0.6):
        self.ops.append(
            "%.2f w %.2f %.2f m %.2f %.2f l S" % (w, x0, PAGE_H - y0_top, x1, PAGE_H - y1_top)
        )

    def content(self):
        return "\n".join(self.ops)


def build():
    pages = []

    # ------------------------------------------------------------------ page 1
    p = Page()
    p.text(54, 40, "Journal of Synthetic Fixtures 12 (2026) 001-002", size=8)
    p.line(54, 46, 558, 46, 0.5)

    p.text(54, 78, "Column-Aware Extraction of Structured Content", size=18, bold=True)
    p.text(54, 100, "A. Author, B. Author and C. Author", size=10)
    p.text(54, 114, "Institute of Reproducible Reading, Example University", size=8)

    p.text(54, 140, "ABSTRACT", size=9, bold=True)
    p.text(54, 152, "We describe a parser that recovers sections, paragraphs, tables and", size=8.5)
    p.text(54, 163, "equations from two-column articles while keeping every element", size=8.5)
    p.text(54, 174, "traceable to a page and a block identifier.", size=8.5)
    p.line(54, 186, 558, 186, 0.5)

    # left column
    y = 206
    p.text(COL_L_X, y, "1. Introduction", size=12, bold=True)
    y += 18
    intro = [
        "Two-column layouts interleave reading order with geometry.",
        "A parser that ignores columns concatenates lines from",
        "different paragraphs and silently corrupts the meaning of",
        "the text.",
    ]
    for ln in intro:
        p.text(COL_L_X, y, ln, size=9)
        y += 12

    y += 8
    p.text(COL_L_X, y, "1.1 Problem setting", size=10, bold=True)
    y += 14
    setting = [
        "The central difficulty is that a column break is invisible",
        "in the raw content stream: the next text run simply jumps",
        "back to the left margin, several hundred points higher on",
        "the page. Any consumer of the extracted text inherits that",
        "jump as a broken sentence.",
    ]
    for ln in setting:
        p.text(COL_L_X, y, ln, size=9)
        y += 12

    y += 8
    # this paragraph deliberately runs off the bottom of the left column
    p.text(COL_L_X, y, "The continuation rule we adopt is simple but effective: a", size=9)
    y += 12
    p.text(COL_L_X, y, "paragraph that does not terminate with sentence punctuation", size=9)
    y += 12
    p.text(COL_L_X, y, "and is immediately followed, at the head of the next", size=9)
    y += 12
    p.text(COL_L_X, y, "column, by text that begins in lower case is treated as", size=9)
    # right column
    yr = 206
    p.text(COL_R_X, yr, "2. Methods", size=12, bold=True)
    yr += 18
    # continuation of the left-column paragraph, at the top of the right column
    cont = [
        "one paragraph that was split by the column break, and the two",
        "fragments are rejoined in reading order before any downstream",
        "analysis runs on the text.",
    ]
    for ln in cont:
        p.text(COL_R_X, yr, ln, size=9)
        yr += 12

    yr += 12
    p.text(COL_R_X, yr, "2.1 Reading order", size=10, bold=True)
    yr += 16
    methods = [
        "We group words into lines by vertical overlap, then sweep a",
        "vertical corridor across the page to locate the gutter. Lines",
        "that cross the corridor are treated as full-width elements and",
        "interrupt the column stream rather than joining either column.",
    ]
    for ln in methods:
        p.text(COL_R_X, yr, ln, size=9)
        yr += 12

    yr += 10
    p.text(COL_R_X, yr, "The affinity of the binding site is given by", size=9)
    yr += 16
    p.text(COL_R_X + 40, yr, "E_bind = E_complex - (E_host + E_guest)", size=10)
    p.text(COL_R_X + COL_W - 14, yr, "(1)", size=9)
    yr += 20
    p.text(COL_R_X, yr, "where each term is the total energy in kcal per mole.", size=9)

    # full-width table at the foot of page 1
    ty = 640
    p.text(54, ty - 16, "Table 1. Measured binding energies for the reference set.", size=8.5)
    rows = [
        ["System", "E_bind", "Error", "Runs"],
        ["Host-A / Guest-1", "-12.4", "0.3", "5"],
        ["Host-A / Guest-2", "-9.8", "0.2", "5"],
        ["Host-B / Guest-1", "-15.1", "0.4", "3"],
    ]
    colx = [54, 170, 300, 420, 520]
    rh = 18
    table_top = ty
    for i, row in enumerate(rows):
        yy = table_top + i * rh
        for j, cell in enumerate(row):
            p.text(colx[j] + 4, yy + 13, cell, size=8.5, bold=(i == 0))
    for i in range(len(rows) + 1):
        p.line(54, table_top + i * rh, 558, table_top + i * rh, 0.5)
    for xxx in colx[:4] + [558]:
        p.line(xxx, table_top, xxx, table_top + len(rows) * rh, 0.5)

    p.text(54, 760, "1", size=8)
    pages.append(p)

    # ------------------------------------------------------------------ page 2
    q = Page()
    q.text(54, 40, "Journal of Synthetic Fixtures 12 (2026) 001-002", size=8)
    q.line(54, 46, 558, 46, 0.5)

    y2 = 78
    q.text(54, y2, "3. Results", size=12, bold=True)
    y2 += 20
    res_l = [
        "The parsed order matched the visual order on all pages of the",
        "reference set. Table 1 was recovered with four rows and four",
        "columns, including its header row.",
    ]
    for ln in res_l:
        q.text(COL_L_X, y2, ln, size=9)
        y2 += 12

    y2 += 10
    q.text(COL_L_X, y2, "Figure 1. Parsed block map for page one.", size=8.5)
    y2 += 14
    q.text(COL_L_X, y2, "Boxes show block identifiers; the gutter is shaded.", size=8.5)

    yr2 = 78
    q.text(COL_R_X, yr2, "3.1 Residual error", size=10, bold=True)
    yr2 += 16
    res_r = [
        "Residuals stay below the reporting precision of the source",
        "tables. The relative deviation is written as",
    ]
    for ln in res_r:
        q.text(COL_R_X, yr2, ln, size=9)
        yr2 += 12
    yr2 += 10
    q.text(COL_R_X + 40, yr2, "delta = |E_calc - E_ref| / |E_ref|", size=10)
    q.text(COL_R_X + COL_W - 14, yr2, "(2)", size=9)
    yr2 += 22
    q.text(COL_R_X, yr2, "and never exceeds four percent in the reference set.", size=9)

    y3 = 300
    q.text(54, y3, "4. Conclusion", size=12, bold=True)
    y3 += 20
    concl = [
        "Column-aware ordering plus explicit continuation merging recovers",
        "paragraphs that a naive reader splits across the column break.",
        "Every emitted element carries a page and block identifier, so any",
        "downstream claim can be traced back to the exact source region.",
    ]
    for ln in concl:
        q.text(54, y3, ln, size=9)
        y3 += 12

    y3 += 16
    q.text(54, y3, "References", size=11, bold=True)
    y3 += 18
    refs = [
        "[1] A. Author, B. Author, Column-aware extraction, J. Synth. Fix. 11 (2025) 1-9.",
        "[2] C. Author, Reading order recovery for multi-column PDF, in: Proc. Example, 2024.",
    ]
    for r in refs:
        q.text(54, y3, r, size=8.5)
        y3 += 12

    q.text(54, 760, "2", size=8)
    pages.append(q)
    return pages


def write_pdf(path, pages):
    objects = []

    def add(obj):
        objects.append(obj)
        return len(objects)

    catalog_id = add(None)  # placeholder, filled later
    pages_id = add(None)

    font_regular = add("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    font_bold = add("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")

    page_ids = []
    for p in pages:
        data = p.content().encode("latin-1", "replace")
        comp = zlib.compress(data)
        # /Length must count exactly the bytes between "stream\n" and "endstream"
        header = "<< /Length %d /Filter /FlateDecode >>" % len(comp)
        content_id = add(header)
        page_ids.append((content_id, comp))

    page_obj_ids = []
    for content_id, _ in page_ids:
        pid = add(
            "<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %.0f %.0f] "
            "/Resources << /Font << /F1 %d 0 R /F2 %d 0 R >> >> /Contents %d 0 R >>"
            % (pages_id, PAGE_W, PAGE_H, font_regular, font_bold, content_id)
        )
        page_obj_ids.append(pid)

    objects[catalog_id - 1] = "<< /Type /Catalog /Pages %d 0 R >>" % pages_id
    objects[pages_id - 1] = "<< /Type /Pages /Kids [%s] /Count %d >>" % (
        " ".join("%d 0 R" % i for i in page_obj_ids),
        len(page_obj_ids),
    )

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0] * (len(objects) + 1)
    bodies = {cid: comp for cid, comp in page_ids}
    for idx, obj in enumerate(objects, 1):
        offsets[idx] = len(out)
        out += ("%d 0 obj\n" % idx).encode("latin-1")
        if idx in bodies:
            out += (obj + "\nstream\n").encode("latin-1")
            out += bodies[idx]
            out += b"\nendstream"
        else:
            out += obj.encode("latin-1")
        out += b"\nendobj\n"

    xref_at = len(out)
    out += ("xref\n0 %d\n" % (len(objects) + 1)).encode("latin-1")
    out += b"0000000000 65535 f \n"
    for idx in range(1, len(objects) + 1):
        out += ("%010d 00000 n \n" % offsets[idx]).encode("latin-1")
    out += ("trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n"
            % (len(objects) + 1, catalog_id, xref_at)).encode("latin-1")

    with open(path, "wb") as f:
        f.write(bytes(out))


GROUND_TRUTH = {
    "pages": 2,
    "two_column": True,
    "title": "Column-Aware Extraction of Structured Content",
    "sections": [
        "1. Introduction",
        "1.1 Problem setting",
        "2. Methods",
        "2.1 Reading order",
        "3. Results",
        "3.1 Residual error",
        "4. Conclusion",
        "References",
    ],
    "tables": [{"label": "Table 1", "rows": 4, "cols": 4,
                "header": ["System", "E_bind", "Error", "Runs"]}],
    "formulas": ["1", "2"],
    "figures": ["Figure 1"],
    "references_count": 2,
    "cross_column_continuation": (
        "is treated as one paragraph that was split by the column break"
    ),
    "footer_pages": ["1", "2"],
}


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    pdf_path = os.path.join(here, "sample_two_column.pdf")
    write_pdf(pdf_path, build())
    with open(os.path.join(here, "ground_truth.json"), "w", encoding="utf-8") as f:
        json.dump(GROUND_TRUTH, f, ensure_ascii=False, indent=1)
    print("wrote", pdf_path, os.path.getsize(pdf_path), "bytes")


if __name__ == "__main__":
    main()
