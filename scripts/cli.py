#!/usr/bin/env python3
"""pdfstruct command-line entry point.

Designed for the evaluation harness, which supplies:
    /input/case.json     the case definition (schema not fixed across topics)
    /input/task.md       the task statement
    a real PDF           path declared inside case.json, or simply the only PDF in /input
and expects, under /app/output:
    result.json          structured parse + evidence + status + uncertainty

So the entry point does not trust a fixed key name for the PDF: it looks at
case.json, then under the well-known input directories, then at any PDF it can find.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pdfstruct import document as docmod  # noqa: E402


PDF_KEYS = ("pdf", "pdf_path", "file", "file_path", "input", "input_path",
            "document", "document_path", "material", "material_path", "path", "source")
INPUT_DIRS = ("/input", "./input", "/app/input", "/data", "./data", "/materials")
OUT_DIRS = ("/app/output", "./output", "/output", "./out")


def log_factory(logfile):
    fh = None
    if logfile:
        os.makedirs(os.path.dirname(os.path.abspath(logfile)) or ".", exist_ok=True)
        fh = open(logfile, "a", encoding="utf-8")

    def log(msg):
        line = "[pdfstruct] %s" % msg
        print(line, flush=True)
        if fh:
            fh.write(line + "\n")
            fh.flush()

    return log


def find_json_candidates(dirs):
    found = []
    for d in dirs:
        if os.path.isdir(d):
            for name in ("case.json", "input.json", "task.json"):
                p = os.path.join(d, name)
                if os.path.isfile(p):
                    found.append(p)
    return found


def walk_strings(obj, path=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from walk_strings(v, "%s.%s" % (path, k) if path else str(k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from walk_strings(v, "%s[%d]" % (path, i))
    elif isinstance(obj, str):
        yield path, obj


def locate_pdf(case_data, log):
    """Find the PDF this case is about. Returns (path, how)."""
    if case_data:
        # 1. explicit, well-known keys
        for key in PDF_KEYS:
            v = case_data.get(key) if isinstance(case_data, dict) else None
            if isinstance(v, str) and v.lower().endswith(".pdf"):
                if os.path.isfile(v):
                    return v, "case.json key %r" % key
                log("case.json key %r points at missing file: %s" % (key, v))
        # 2. any string anywhere that names an existing .pdf
        for where, s in walk_strings(case_data):
            if s.lower().endswith(".pdf"):
                for cand in (s, os.path.join("/input", os.path.basename(s)),
                             os.path.join("./input", os.path.basename(s)), os.path.basename(s)):
                    if os.path.isfile(cand):
                        return cand, "case.json field %s" % where
        log("case.json carried no resolvable .pdf path")

    # 3. conventional directories
    for d in INPUT_DIRS:
        if not os.path.isdir(d):
            continue
        pdfs = sorted(glob.glob(os.path.join(d, "*.pdf")) + glob.glob(os.path.join(d, "*.PDF")))
        if pdfs:
            return pdfs[0], "first PDF under %s" % d
        for sub in glob.glob(os.path.join(d, "**", "*.pdf"), recursive=True)[:5]:
            return sub, "recursive search under %s" % d

    # 4. current working directory
    pdfs = sorted(glob.glob("*.pdf"))
    if pdfs:
        return pdfs[0], "first PDF in working directory"
    return None, "not found"


def resolve_out_dir(explicit):
    if explicit:
        os.makedirs(explicit, exist_ok=True)
        return explicit
    for d in OUT_DIRS:
        parent = os.path.dirname(d.rstrip("/")) or "."
        if os.path.isdir(parent) or d.startswith("./"):
            try:
                os.makedirs(d, exist_ok=True)
                if os.access(d, os.W_OK):
                    return d
            except OSError:
                continue
    os.makedirs("./output", exist_ok=True)
    return "./output"


def read_task(dirs):
    for d in dirs:
        for name in ("task.md", "task.txt", "TASK.md"):
            p = os.path.join(d, name)
            if os.path.isfile(p):
                return open(p, encoding="utf-8", errors="replace").read(), p
    return None, None


def main(argv=None):
    ap = argparse.ArgumentParser(description="Structure-preserving scientific PDF parser")
    ap.add_argument("--pdf", help="path to the PDF (auto-detected when omitted)")
    ap.add_argument("--case", help="path to case.json (auto-detected when omitted)")
    ap.add_argument("--case-id", help="case identifier to echo into result.json")
    ap.add_argument("--out", help="output directory (default /app/output)")
    ap.add_argument("--log", help="append a run log to this file")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    log = log_factory(args.log)
    out_dir = resolve_out_dir(args.out)
    log("out_dir=%s" % out_dir)

    case_path = args.case
    if not case_path:
        cands = find_json_candidates(INPUT_DIRS + ("/app", "."))
        case_path = cands[0] if cands else None
    case_data = None
    if case_path and os.path.isfile(case_path):
        try:
            case_data = json.load(open(case_path, encoding="utf-8"))
            log("case file: %s" % case_path)
        except Exception as exc:  # noqa: BLE001
            log("case file unreadable (%s): %s" % (case_path, exc))

    case_id = args.case_id or (case_data or {}).get("case_id") or (case_data or {}).get("id")
    if not case_id and case_path:
        case_id = os.path.splitext(os.path.basename(case_path))[0]
    log("case_id=%s" % case_id)

    pdf_path = args.pdf
    how = "explicit --pdf"
    if not pdf_path:
        pdf_path, how = locate_pdf(case_data, log)
    log("pdf=%s (%s)" % (pdf_path, how))

    task_text, task_path = read_task(INPUT_DIRS + (".", ))
    if task_path:
        log("task statement: %s" % task_path)

    if not pdf_path or not os.path.isfile(pdf_path):
        result = {
            "case_id": case_id,
            "status": "cannot_determine",
            "reason": "no PDF input located",
            "searched": list(INPUT_DIRS),
            "result": {"sections": [], "paragraphs": [], "tables": [], "formulas": [],
                       "figures": [], "references": [], "headers_footers": [], "missing": []},
            "evidence": [],
            "uncertainty": [{"item": "input", "note": "no PDF found; nothing parsed"}],
            "changes": [],
            "sources": [],
        }
        _write(out_dir, result, log)
        return 2

    result = docmod.parse_pdf(pdf_path, case_id=case_id, task_text=task_text, logger=log)
    result["changes"] = [
        {"what": "initial parse", "detail": "single pass, no OCR", "version": docmod.VERSION}
    ]
    _write(out_dir, result, log)

    counts = result.get("result", {}).get("counts", {})
    log("status=%s counts=%s" % (result.get("status"), json.dumps(counts)))
    return 0 if result.get("status") == "success" else 0


def _write(out_dir, result, log):
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "result.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    log("wrote %s (%d bytes)" % (path, os.path.getsize(path)))

    # a human-readable companion, useful for review and for the artifact trail
    md = _summary_markdown(result)
    mpath = os.path.join(out_dir, "result.md")
    with open(mpath, "w", encoding="utf-8") as f:
        f.write(md)
    log("wrote %s" % mpath)


def _summary_markdown(result):
    r = result.get("result", {})
    out = ["# Parse summary", "", "- case_id: `%s`" % result.get("case_id"),
           "- status: `%s`" % result.get("status"), ""]
    out.append("## Sections (%d)" % len(r.get("sections", [])))
    for s in r.get("sections", [])[:60]:
        out.append("- L%s %s  `%s`" % (s.get("level"), s.get("title"), s.get("block_id")))
    out.append("")
    out.append("## Tables (%d)" % len(r.get("tables", [])))
    for t in r.get("tables", [])[:20]:
        out.append("- %s  %dx%d  page %s  `%s`" % (t.get("id"), t.get("rows"), t.get("cols"),
                                                    t.get("page"), t.get("block_id")))
    out.append("")
    out.append("## Formulas (%d)" % len(r.get("formulas", [])))
    for f in r.get("formulas", [])[:20]:
        out.append("- (%s) page %s `%s`" % (f.get("number"), f.get("page"), f.get("block_id")))
    out.append("")
    out.append("## Missing (%d)" % len(r.get("missing", [])))
    for m in r.get("missing", [])[:20]:
        out.append("- page %s: %s (%s)" % (m.get("page"), m.get("what"), m.get("reason")))
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    sys.exit(main())
