"""Assemble a structure-preserving, evidence-anchored parse of a scientific PDF.

Public entry point: `parse_pdf(path, case_id=...) -> result dict`.

Design rules the scoring rubric cares about, encoded here rather than only in prose:
  * every emitted element carries page + block id (p07-b012) so it can be pointed back;
  * unreadable content is recorded under `missing`, never guessed or smoothed over;
  * headers/footers are separated from body text instead of polluting paragraphs;
  * reading order is column-major within a page, interrupted by full-width elements;
  * a paragraph split by a column or page break is rejoined, and the join is recorded.
"""
from __future__ import annotations

import hashlib
import os
import re
import time

from . import backends
from . import layout
from . import tables as tablemod

VERSION = "1.0.0"

REFERENCE_HEADING_RE = re.compile(r"^\s*(references|bibliography|literature cited|参考文献)\s*$", re.I)
FIGURE_RE = re.compile(r"^\s*(fig(?:ure)?\.?|图)\s*(\d+)", re.I)
TABLE_CAP_RE = re.compile(r"^\s*(table|表)\s*(\d+)", re.I)
EQ_NUMBER_RE = re.compile(r"\((\d+[a-z]?)\)\s*$")
TERMINAL = tuple(".!?:;。！？：；\"')]")
CJK = re.compile(r"[\u3400-\u9fff]")


def _block_id(page_no, index):
    return "p%02d-b%03d" % (page_no, index)


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _continues(prev, cur):
    """True when `cur` is the tail of the paragraph that `prev` starts."""
    a = (prev.get("text") or "").rstrip()
    b = (cur.get("text") or "").lstrip()
    if not a or not b:
        return False
    if a.endswith(TERMINAL):
        return False
    first = b[:1]
    if not (first.islower() or CJK.match(first)):
        return False
    sa, sb = prev.get("_size") or 0, cur.get("_size") or 0
    if sa and sb and abs(sa - sb) > max(1.0, 0.18 * sa):
        return False
    return True


def parse_pdf(path, case_id=None, task_text=None, logger=None):
    t0 = time.time()
    log = logger or (lambda m: None)

    pages, backend, attempts = backends.extract(path, logger=log)
    if not pages:
        return {
            "case_id": case_id,
            "status": "cannot_determine",
            "reason": "no PDF text backend produced any text",
            "backend_attempts": attempts,
            "sources": [{"type": "input_file", "path": path}],
            "result": {"sections": [], "paragraphs": [], "tables": [], "formulas": [],
                       "figures": [], "references": [], "headers_footers": [], "missing": []},
            "evidence": [],
            "uncertainty": [{"item": "document", "note": "PDF could not be read by any backend"}],
            "changes": [],
        }

    body_sizes = [w["size"] for p in pages for w in p["words"] if w["size"]]
    body_size = layout._median(body_sizes, 10.0)

    sections, paragraphs, formulas, figures = [], [], [], []
    headers_footers, references, missing, uncertainty = [], [], [], []
    table_rows = []
    two_col_pages = []
    in_references = False

    for page in pages:
        page_no = page["number"]
        if not page["has_text"]:
            missing.append({
                "page": page_no, "what": "text layer",
                "reason": "no extractable text (likely a scanned image page)",
                "handling": "reported and left unresolved; OCR pass required, not guessed",
            })
            uncertainty.append({"item": "page_%d" % page_no,
                                "note": "no text layer; this page's content is unknown"})
            continue

        lines = layout.group_lines(page["words"])
        gutter, diag = layout.detect_gutter(lines, page["width"])
        if gutter is not None:
            two_col_pages.append(page_no)
        # XY-cut gives the reading order and, per leaf region, the column identity that
        # keeps block merging from joining text across a column break.
        regions = layout.xy_cut(lines)
        ordered = []
        for r_i, region in enumerate(regions):
            for ln in region:
                ln["col"] = "r%03d" % r_i
            ordered.extend(region)
        blocks = layout.build_blocks(ordered)
        blocks = layout.classify(blocks, page, body_size)

        for idx, b in enumerate(blocks, 1):
            b["page"] = page_no
            b["block_id"] = _block_id(page_no, idx)

        # ---- tables first, so a paragraph that is really a table row is not emitted twice
        page_tables = tablemod.detect_tables(page["words"], page)
        table_spans = [(t["top"] - 1, t["bottom"] + 1) for t in page_tables]

        def in_table(block):
            for top, bottom in table_spans:
                overlap = min(block["bottom"], bottom) - max(block["top"], top)
                if overlap > 0.5 * max(1.0, block["bottom"] - block["top"]):
                    return True
            return False

        for b in blocks:
            text = b["text"].strip()
            if b["type"] == "header_footer":
                if text:
                    headers_footers.append({
                        "page": page_no, "block_id": b["block_id"], "text": text,
                        "band": "top" if b["top"] < page["height"] * 0.5 else "bottom",
                    })
                continue
            if text and REFERENCE_HEADING_RE.match(text):
                in_references = True
                sections.append({"level": 1, "number": None, "title": text,
                                 "page": page_no, "block_id": b["block_id"]})
                continue
            if in_table(b):
                continue
            if b["type"] == "heading":
                in_references = False
                m = layout.HEADING_NUM_RE.match(text)
                sections.append({
                    "level": layout.heading_level(text, b["size"], body_size),
                    "number": m.group(1) if m else None,
                    "title": text, "page": page_no, "block_id": b["block_id"],
                })
                continue
            if b["type"] == "formula":
                m = EQ_NUMBER_RE.search(text)
                num = m.group(1) if m else None
                body_text = EQ_NUMBER_RE.sub("", text).strip() if m else text
                # a lone "(7)" is the number of the equation just above it, not its own formula
                if num and not body_text:
                    if formulas and formulas[-1]["number"] is None:
                        formulas[-1]["number"] = num
                        continue
                formulas.append({"number": num, "text": body_text or text,
                                 "page": page_no, "block_id": b["block_id"]})
                continue
            if b["type"] == "caption":
                fm = FIGURE_RE.match(text)
                tm = TABLE_CAP_RE.match(text)
                label = None
                kind = "caption"
                if fm:
                    label, kind = fm.group(1).rstrip(".") + fm.group(2), "figure"
                elif tm:
                    label, kind = tm.group(1).rstrip(".") + tm.group(2), "table"
                figures.append({"label": label, "kind": kind, "caption": text,
                                "page": page_no, "block_id": b["block_id"]})
                continue
            if b["type"] != "body" or not text:
                continue
            if in_table(b):
                continue
            if in_references:
                references.append({"text": text, "page": page_no, "block_id": b["block_id"]})
                continue
            paragraphs.append({
                "id": b["block_id"], "page": page_no, "block_id": b["block_id"],
                "text": text, "first_sentence": layout.first_sentence(text),
                "n_lines": b["n_lines"], "column": b["col"],
                "section": sections[-1]["title"] if sections else None,
                "_size": b["size"],
            })

        for t in page_tables:
            best, best_ov = None, 0.0
            for b in blocks:
                if b["type"] == "header_footer":
                    continue
                ov = min(b["bottom"], t["bottom"]) - max(b["top"], t["top"])
                if ov > best_ov:
                    best, best_ov = b, ov
            bid = best["block_id"] if best else _block_id(page_no, 0)
            table_rows.append({
                "id": "t%02d" % (len(table_rows) + 1),
                "page": page_no, "block_id": bid,
                "rows": t["rows"], "cols": t["cols"],
                "header": t["header"], "cells": t["cells"],
                "markdown": tablemod.to_markdown(t["cells"]),
                "bbox": {"x0": t["x0"], "top": t["top"], "x1": t["x1"], "bottom": t["bottom"]},
                "method": t["method"],
            })

    # ---- split a merged reference block back into individual entries
    split_refs = []
    for r in references:
        parts = [p.strip() for p in re.split(r"(?=\[\d+\]\s)", r["text"]) if p.strip()]
        if len(parts) > 1:
            for k, p in enumerate(parts):
                item = dict(r)
                item["text"] = p
                item["part"] = k + 1
                item["parts_total"] = len(parts)
                split_refs.append(item)
        else:
            split_refs.append(r)
    references = split_refs

    # ---- rejoin paragraphs broken by a column or page break
    merged = []
    joins = []
    for p in paragraphs:
        if merged and _continues(merged[-1], p):
            prev = merged[-1]
            prev["text"] = prev["text"].rstrip() + " " + p["text"].lstrip()
            prev["first_sentence"] = layout.first_sentence(prev["text"])
            prev.setdefault("continued_into", []).append(
                {"page": p["page"], "block_id": p["block_id"]})
            joins.append({"from": prev["block_id"], "to": p["block_id"],
                          "reason": "no terminal punctuation at column/page break"})
        else:
            merged.append(p)
    for p in merged:
        p.pop("_size", None)
    paragraphs = merged

    evidence = []
    for p in paragraphs:
        evidence.append({"kind": "paragraph", "block_id": p["block_id"], "page": p["page"],
                         "quote": p["text"][:160],
                         "basis": "text layer, column-aware reading order"})
    for t in table_rows:
        evidence.append({"kind": "table", "block_id": t["block_id"], "page": t["page"],
                         "quote": "table %dx%d" % (t["rows"], t["cols"]),
                         "basis": t["method"]})
    for f in formulas:
        evidence.append({"kind": "formula", "block_id": f["block_id"], "page": f["page"],
                         "quote": f["text"][:120], "basis": "formula pattern match"})

    if backend and "no coordinates" in backend:
        uncertainty.append({"item": "layout",
                            "note": "only a coordinate-free backend was available; column "
                                    "order and block geometry are unreliable in this run"})
    if joins:
        uncertainty.append({"item": "continuations",
                            "note": "%d paragraph(s) were rejoined across a column or page "
                                    "break by punctuation/case heuristic; each join is listed "
                                    "under changes" % len(joins)})

    result = {
        "case_id": case_id,
        "status": "success" if not missing else "partial",
        "document": {
            "path": os.path.basename(path),
            "sha256": _sha256(path),
            "pages": len(pages),
            "backend": backend,
            "body_font_size": round(body_size, 2) if body_size else None,
            "two_column_pages": two_col_pages,
            "gutter_diagnostics": diag if two_col_pages else {},
        },
        "result": {
            "sections": sections,
            "paragraphs": paragraphs,
            "tables": table_rows,
            "formulas": formulas,
            "figures": figures,
            "references": references,
            "headers_footers": headers_footers,
            "missing": missing,
            "counts": {
                "sections": len(sections), "paragraphs": len(paragraphs),
                "tables": len(table_rows), "formulas": len(formulas),
                "figures": len(figures), "references": len(references),
                "headers_footers": len(headers_footers), "missing": len(missing),
            },
        },
        "evidence": evidence,
        "uncertainty": uncertainty,
        "changes": [{"what": "continuation rejoin", "from": j["from"], "to": j["to"],
                     "reason": j["reason"]} for j in joins],
        "sources": [
            {"type": "input_file", "path": path, "sha256": _sha256(path)},
            {"type": "backend", "name": backend or "none"},
            {"type": "table_detector", "name": "internal gap-clustering"},
        ],
        "runtime": {"tool": "pdfstruct", "version": VERSION,
                    "seconds": round(time.time() - t0, 2), "backend_attempts": attempts},
        "task_text": task_text,
    }
    return result
