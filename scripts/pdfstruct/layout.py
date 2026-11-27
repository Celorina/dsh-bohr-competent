"""Layout analysis: words -> lines -> reading order -> blocks -> typed blocks.

The interesting parts are `detect_gutter` (find the vertical whitespace corridor that
separates columns) and `reading_order` (walk the page so that a full-width element such
as a title or a spanning table interrupts the column stream instead of being sorted into
one column).

All coordinates are top-down PDF points, origin at the top-left of the page.
"""
from __future__ import annotations

import re
import statistics
from collections import Counter

CJK = re.compile(r"[\u3400-\u9fff\uf900-\ufaff\u3040-\u30ff\uac00-\ud7af]")

CAPTION_RE = re.compile(
    r"^\s*(fig(?:ure)?\.?\s*\d+|table\s*\d+|图\s*\d+|表\s*\d+|scheme\s*\d+)",
    re.I,
)
HEADING_NUM_RE = re.compile(r"^(\d+(?:\.\d+)*)[\.\s、]\s*\S")
FORMULA_NUM_RE = re.compile(r"^\((\d+[a-z]?)\)\s*$|^\(\d+[a-z]?\)\s*$")

MATH_CHARS = set("=+−-×·÷∑∏∫√≈≠≤≥∂∇αβγδεζηθικλμνξπρστυφχψωΓΔΘΛΞΠΣΦΨΩ^_")


def _median(values, default=10.0):
    values = [v for v in values if v]
    if not values:
        return default
    return statistics.median(values)


# ---------------------------------------------------------------- lines

def _median_word_gap(words):
    gaps = []
    ws = sorted(words, key=lambda w: (round(w["top"], 1), w["x0"]))
    for a, b in zip(ws, ws[1:]):
        if abs(a["top"] - b["top"]) < 2.0:
            g = b["x0"] - a["x1"]
            if g > 0:
                gaps.append(g)
    return _median(gaps, 3.0)


def group_lines(words, tol_ratio=0.55, split_gap=None):
    """Cluster words into text lines by vertical overlap, then cut wide gaps.

    The cut is essential: in a two-column layout the left and right column can start at
    exactly the same height, and y-overlap alone would fuse them into one line that
    spuriously spans the gutter. A gap much wider than the page's typical inter-word
    space means a column (or table cell) boundary, not a space.
    """
    if not words:
        return []
    heights = [w["bottom"] - w["top"] for w in words if w["bottom"] > w["top"]]
    med_h = _median(heights, 10.0)
    tol = max(1.0, med_h * tol_ratio)
    if split_gap is None:
        split_gap = max(12.0, _median_word_gap(words) * 4.0)

    ordered = sorted(words, key=lambda w: (round(w["top"], 1), w["x0"]))
    raw = []
    for w in ordered:
        placed = False
        for line in reversed(raw[-6:]):
            overlap = min(line["bottom"], w["bottom"]) - max(line["top"], w["top"])
            ref = min(line["bottom"] - line["top"], w["bottom"] - w["top"]) or 1.0
            if overlap / ref >= 0.5 and abs(w["top"] - line["top"]) <= tol * 2:
                line["words"].append(w)
                line["x0"] = min(line["x0"], w["x0"])
                line["x1"] = max(line["x1"], w["x1"])
                line["top"] = min(line["top"], w["top"])
                line["bottom"] = max(line["bottom"], w["bottom"])
                placed = True
                break
        if not placed:
            raw.append({"words": [w], "x0": w["x0"], "x1": w["x1"],
                        "top": w["top"], "bottom": w["bottom"]})

    lines = []
    for line in raw:
        ws = sorted(line["words"], key=lambda w: w["x0"])
        segment = [ws[0]]
        for prev, cur in zip(ws, ws[1:]):
            if cur["x0"] - prev["x1"] >= split_gap:
                lines.append(_finish_line(segment))
                segment = [cur]
            else:
                segment.append(cur)
        lines.append(_finish_line(segment))

    lines.sort(key=lambda l: (l["top"], l["x0"]))
    return lines


def _finish_line(words):
    return {
        "words": words,
        "x0": min(w["x0"] for w in words),
        "x1": max(w["x1"] for w in words),
        "top": min(w["top"] for w in words),
        "bottom": max(w["bottom"] for w in words),
        "text": join_words(words),
        "size": _median([w["size"] for w in words], 0.0),
        "font": Counter(w["font"] for w in words).most_common(1)[0][0] if words else "",
    }


def join_words(words):
    """Join words into text, inserting spaces only where a Latin gap exists."""
    out = []
    prev = None
    for w in words:
        t = w["text"]
        if prev is not None:
            gap = w["x0"] - prev["x1"]
            prev_ch = prev["text"][-1:] if prev["text"] else ""
            cur_ch = t[:1]
            if gap > 1.2 and not (CJK.match(prev_ch) and CJK.match(cur_ch)):
                out.append(" ")
        out.append(t)
        prev = w
    return "".join(out).strip()


# ---------------------------------------------------------------- columns

def detect_gutter(lines, page_width):
    """Find a vertical whitespace corridor separating two text columns.

    Returns (gutter_x or None, diagnostics). A corridor qualifies when very few lines
    cross it and both sides carry a substantial share of the text.
    """
    candidates = [page_width * f for f in (0.5,)]
    best = None
    best_cross = None

    # sweep a band around the page centre; the gutter is centred there in most layouts
    lo, hi = page_width * 0.32, page_width * 0.68
    steps = 60
    for i in range(steps + 1):
        x = lo + (hi - lo) * i / steps
        crossings = sum(1 for l in lines if l["x0"] < x - 2 and l["x1"] > x + 2)
        left = sum(1 for l in lines if l["x1"] <= x + 2)
        right = sum(1 for l in lines if l["x0"] >= x - 2)
        ranked = (crossings, -min(left, right))
        if best is None or ranked < best[0]:
            best = (ranked, x, crossings, left, right)

    _, x, crossings, left, right = best
    total = max(1, len(lines))
    covered = left + right
    # Full-width elements (title, abstract, a spanning table, the conclusion) legitimately
    # cross the gutter, so a strict "almost nothing crosses" rule fails on pages where they
    # dominate. What still separates a two-column page from a one-column one is that most
    # lines sit wholly on one side.
    ok = (
        crossings <= max(2, int(0.40 * total))
        and left >= max(3, int(0.15 * total))
        and right >= max(3, int(0.15 * total))
        and covered >= 0.55 * total
    )
    diag = {
        "gutter_x": round(x, 2) if ok else None,
        "crossings": crossings,
        "lines_left": left,
        "lines_right": right,
        "total_lines": total,
        "two_columns": bool(ok),
    }
    return (round(x, 2) if ok else None), diag


# ---------------------------------------------------------------- XY-cut

def xy_cut(lines, depth=0, max_depth=10):
    """Recursive XY-cut: split the page into reading-order leaves.

    Top-to-bottom horizontal cuts find regions where *every* column is empty (title band,
    abstract, body, spanning table, conclusion); a left-to-right vertical cut then splits a
    region that has a corridor no line crosses. This is what makes a short full-width
    heading such as "4. Conclusion" land after both columns instead of being sucked into
    whichever column its short x-extent happens to resemble.
    """
    if len(lines) <= 1 or depth >= max_depth:
        return [sorted(lines, key=lambda l: (l["top"], l["x0"]))]

    heights = [l["bottom"] - l["top"] for l in lines if l["bottom"] > l["top"]]
    med_h = _median(heights, 10.0)
    # Must exceed the gap a heading leaves above the next body line, or a heading shared by
    # both columns is cut off as its own one-row region and the columns are never split.
    h_gap = max(8.0, med_h * 1.4)

    segments = _horizontal_segments(lines, h_gap)
    if len(segments) > 1:
        out = []
        for seg in segments:
            out.extend(xy_cut(seg, depth + 1, max_depth))
        return out

    split = _vertical_split(lines, min_gap=10.0)
    if split:
        left, right = split
        return xy_cut(left, depth + 1, max_depth) + xy_cut(right, depth + 1, max_depth)

    return [sorted(lines, key=lambda l: (l["top"], l["x0"]))]


def _horizontal_segments(lines, min_gap):
    """Split at y-bands that no line occupies (so the band is empty across the page)."""
    ordered = sorted(lines, key=lambda l: l["top"])
    segs = [[ordered[0]]]
    bottom = ordered[0]["bottom"]
    for line in ordered[1:]:
        if line["top"] - bottom >= min_gap:
            segs.append([line])
            bottom = line["bottom"]
        else:
            segs[-1].append(line)
            bottom = max(bottom, line["bottom"])
    return segs


def _vertical_split(lines, min_gap=10.0):
    """Find a vertical corridor no line crosses; split into left/right sets."""
    intervals = sorted((l["x0"], l["x1"]) for l in lines)
    cur_end = intervals[0][1]
    gaps = []
    for x0, x1 in intervals[1:]:
        if x0 - cur_end >= min_gap:
            gaps.append((cur_end, x0))
        cur_end = max(cur_end, x1)
    if not gaps:
        return None
    # widest corridor first; a line straddling it disqualifies that corridor
    for gap_start, gap_end in sorted(gaps, key=lambda g: g[1] - g[0], reverse=True):
        straddlers = [l for l in lines if l["x0"] < gap_end - 1 and l["x1"] > gap_start + 1]
        if straddlers:
            continue
        left = [l for l in lines if l["x1"] <= gap_start + 1]
        right = [l for l in lines if l["x0"] >= gap_end - 1]
        if len(left) >= 2 and len(right) >= 2 and len(left) + len(right) == len(lines):
            return left, right
    return None

def reading_order(lines, gutter_x, page_width):
    """Return lines in reading order, letting full-width lines interrupt columns."""
    if gutter_x is None:
        return sorted(lines, key=lambda l: (l["top"], l["x0"]))

    for line in lines:
        if line["x0"] < gutter_x - 2 and line["x1"] > gutter_x + 2:
            line["col"] = "F"
        elif line["x1"] <= gutter_x + 2:
            line["col"] = "L"
        elif line["x0"] >= gutter_x - 2:
            line["col"] = "R"
        else:
            line["col"] = "F"

    lines = sorted(lines, key=lambda l: (l["top"], l["x0"]))
    ordered = []
    pending = []

    def flush():
        if pending:
            left = sorted([p for p in pending if p["col"] == "L"], key=lambda l: l["top"])
            right = sorted([p for p in pending if p["col"] == "R"], key=lambda l: l["top"])
            ordered.extend(left)
            ordered.extend(right)
            pending.clear()

    for line in lines:
        if line["col"] == "F":
            flush()
            ordered.append(line)
        else:
            pending.append(line)
    flush()
    return ordered


# ---------------------------------------------------------------- blocks

def build_blocks(ordered_lines):
    """Merge consecutive reading-order lines into blocks."""
    if not ordered_lines:
        return []
    med_h = _median([l["bottom"] - l["top"] for l in ordered_lines], 10.0)
    blocks = []
    cur = None

    for line in ordered_lines:
        if cur is None:
            cur = _start_block(line)
            continue
        same_col = cur["col"] == line.get("col", "F")
        gap = line["top"] - cur["bottom"]
        # a heading is one line and must not absorb the paragraph beneath it
        cur_is_heading = cur["n_lines"] == 1 and (
            HEADING_NUM_RE.match(cur["text"].strip()) or (cur["size"] or 0) > (line["size"] or 0) + 0.6
        )
        size_ok = abs((line["size"] or 0) - (cur["size"] or 0)) <= 0.6
        indent_ok = abs(line["x0"] - cur["x0"]) <= max(6.0, med_h * 1.5)
        # paragraph spacing is usually wider than leading inside a paragraph, so the merge
        # threshold sits just under one line height and lets the gap break the block
        if (same_col and gap <= med_h * 0.95 and size_ok and indent_ok
                and gap > -med_h and not cur_is_heading):
            cur["lines"].append(line)
            cur["x0"] = min(cur["x0"], line["x0"])
            cur["x1"] = max(cur["x1"], line["x1"])
            cur["bottom"] = max(cur["bottom"], line["bottom"])
            cur["n_lines"] += 1
            cur["text"] = (cur["text"] + " " + line["text"]).strip() if line["text"] else cur["text"]
        else:
            blocks.append(cur)
            cur = _start_block(line)
    if cur is not None:
        blocks.append(cur)
    return blocks


def _start_block(line):
    return {
        "lines": [line],
        "text": line["text"],
        "x0": line["x0"],
        "x1": line["x1"],
        "top": line["top"],
        "bottom": line["bottom"],
        "size": line["size"],
        "font": line["font"],
        "col": line.get("col", "F"),
        "n_lines": 1,
    }


# ---------------------------------------------------------------- classification

def classify(blocks, page, body_size):
    """Assign a type to every block and detect header/footer by page position."""
    height = page["height"]
    width = page["width"]
    top_band = height * 0.075
    bottom_band = height * 0.925

    for b in blocks:
        text = b["text"].strip()
        size = b["size"] or body_size
        b["type"] = "body"

        if b["top"] < top_band or b["bottom"] > bottom_band:
            b["type"] = "header_footer"
            continue
        if not text:
            b["type"] = "empty"
            continue
        if CAPTION_RE.match(text):
            b["type"] = "caption"
            continue
        if FORMULA_NUM_RE.search(text) and len(text) < 120:
            b["type"] = "formula"
            continue
        if _looks_like_formula(text):
            b["type"] = "formula"
            continue
        if _looks_like_heading(text, size, body_size, b):
            b["type"] = "heading"
            continue
    return blocks


def _looks_like_formula(text):
    """Conservative: prose that merely contains '=' or a Greek letter is not a formula."""
    if len(text) > 180:
        return False
    if re.search(r"\b(19|20)\d\d\b", text):      # a year means a citation, not an equation
        return False
    if re.search(r"\b(doi|pp\.|vol\.|arXiv)\b", text, re.I):
        return False
    body = "".join(text.split())
    if not body:
        return False
    mathish = sum(ch in MATH_CHARS or ch.isdigit() for ch in body)
    letters = sum(ch.isalpha() for ch in body)
    return (
        mathish >= 3
        and mathish / len(body) >= 0.15
        and letters <= len(body) * 0.72
        and ("=" in text or any(ch in text for ch in "∑∏∫√≈≤≥"))
    )


def _looks_like_heading(text, size, body_size, block):
    compact = text.strip()
    if not compact or len(compact) > 120:
        return False
    if compact.endswith((".", "。", ";", "；", ",")) and block["n_lines"] > 1:
        return False
    if size >= body_size * 1.12 and len(compact.split()) <= 20:
        return True
    if HEADING_NUM_RE.match(compact) and len(compact.split()) <= 18 and block["n_lines"] <= 2:
        return True
    return False


def heading_level(text, size, body_size):
    """Depth from a numbered heading, else from font size relative to body text."""
    m = HEADING_NUM_RE.match(text.strip())
    if m:
        return m.group(1).count(".") + 1
    if size and body_size:
        ratio = size / body_size
        if ratio >= 1.5:
            return 1
        if ratio >= 1.25:
            return 2
    return 3


def split_sentences(text):
    parts = re.split(r"(?<=[\.\!\?。！？])\s+", text.strip())
    return [p for p in parts if p]


def first_sentence(text, limit=300):
    s = split_sentences(text)
    return (s[0] if s else text)[:limit]
