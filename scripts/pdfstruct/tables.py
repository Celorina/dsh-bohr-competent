"""Table detection from word geometry (no pdfplumber dependency).

Scientific tables come in ruled and borderless varieties, so this detector works on the
weaker but more general signal: **repeated column alignment**. A table row is a set of
words sharing a baseline and separated by gaps far wider than the page's normal word
space; a table is a run of such rows whose cell boundaries line up.

Rows are clustered here independently of the text-line builder, because that builder
deliberately cuts wide gaps apart (a column jump and a table cell gap look alike at glyph
level, but a table needs the row kept whole).
"""
from __future__ import annotations

import statistics

MIN_BIG_GAP_PT = 9.0
COL_TOL = 16.0


def _median(values, default=0.0):
    values = [v for v in values if v]
    return statistics.median(values) if values else default


def cluster_rows(words):
    """Group words into rows by vertical overlap (no horizontal cutting)."""
    if not words:
        return []
    heights = [w["bottom"] - w["top"] for w in words if w["bottom"] > w["top"]]
    med_h = _median(heights, 10.0)
    rows = []
    for w in sorted(words, key=lambda w: (round(w["top"], 1), w["x0"])):
        placed = False
        for row in reversed(rows[-6:]):
            overlap = min(row["bottom"], w["bottom"]) - max(row["top"], w["top"])
            ref = min(row["bottom"] - row["top"], w["bottom"] - w["top"]) or 1.0
            if overlap / ref >= 0.5 and abs(w["top"] - row["top"]) <= med_h * 1.1:
                row["words"].append(w)
                row["x0"] = min(row["x0"], w["x0"])
                row["x1"] = max(row["x1"], w["x1"])
                row["top"] = min(row["top"], w["top"])
                row["bottom"] = max(row["bottom"], w["bottom"])
                placed = True
                break
        if not placed:
            rows.append({"words": [w], "x0": w["x0"], "x1": w["x1"],
                         "top": w["top"], "bottom": w["bottom"]})
    for r in rows:
        r["words"].sort(key=lambda w: w["x0"])
    rows.sort(key=lambda r: r["top"])
    return rows


def split_cells(row, min_gap=MIN_BIG_GAP_PT):
    ws = row["words"]
    if not ws:
        return []
    cells = [[ws[0]]]
    for prev, cur in zip(ws, ws[1:]):
        if cur["x0"] - prev["x1"] >= min_gap:
            cells.append([cur])
        else:
            cells[-1].append(cur)
    return cells


def _key(cells):
    return [round(c[0]["x0"], 1) for c in cells if c]


def _aligns(a, b, tol=COL_TOL):
    if len(a) != len(b) or len(a) < 2:
        return False
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def detect_tables(words, page):
    """Return tables: {rows, cols, cells, header, top, bottom, x0, x1, method}."""
    rows = cluster_rows(words)
    if not rows:
        return []
    med_h = _median([r["bottom"] - r["top"] for r in rows], 10.0)

    cands = []
    for r in rows:
        cells = split_cells(r)
        if len(cells) >= 2:
            cands.append({"row": r, "cells": cells, "key": _key(cells)})
    if not cands:
        return []

    groups = []
    cur = [cands[0]]
    for prev, cc in zip(cands, cands[1:]):
        gap = cc["row"]["top"] - prev["row"]["bottom"]
        if gap <= med_h * 1.2 and _aligns(prev["key"], cc["key"]):
            cur.append(cc)
        else:
            groups.append(cur)
            cur = [cc]
    groups.append(cur)

    out = []
    for g in groups:
        if len(g) < 2:
            continue
        n_cols = max(len(c["cells"]) for c in g)
        if n_cols < 2:
            continue
        cells = []
        for c in g:
            row = [" ".join(w["text"] for w in grp).strip() for grp in c["cells"]]
            row += [""] * (n_cols - len(row))
            cells.append(row)
        # A table cell holds a value or a short label. Two-column *running text* lines up
        # perfectly at the gutter and would otherwise look like a 2-column table, so a
        # region whose cells are mostly prose is rejected.
        word_counts = [len(c.split()) for r in cells for c in r if c]
        med_words = sorted(word_counts)[len(word_counts) // 2] if word_counts else 0
        if med_words > 6:
            continue
        if n_cols == 2 and med_words > 3:
            continue
        # reject a wrapped paragraph masquerading as a 2-column table
        if n_cols == 2 and all(len(r[1].split()) > 8 for r in cells):
            continue
        # reject if almost all cells are empty (a stray wide gap in running text)
        filled = sum(1 for r in cells for c in r if c)
        if filled < len(cells) * n_cols * 0.45:
            continue
        out.append({
            "rows": len(cells),
            "cols": n_cols,
            "cells": cells,
            "header": cells[0],
            "top": round(min(c["row"]["top"] for c in g), 2),
            "bottom": round(max(c["row"]["bottom"] for c in g), 2),
            "x0": round(min(c["row"]["x0"] for c in g), 2),
            "x1": round(max(c["row"]["x1"] for c in g), 2),
            "method": "repeated column alignment of word gaps",
        })
    return out


def to_markdown(cells):
    if not cells:
        return ""
    n = max(len(r) for r in cells)
    cells = [r + [""] * (n - len(r)) for r in cells]
    out = ["| " + " | ".join(cells[0]) + " |",
           "| " + " | ".join("---" for _ in range(n)) + " |"]
    for r in cells[1:]:
        out.append("| " + " | ".join(r) + " |")
    return "\n".join(out)
