#!/usr/bin/env python3
"""End-to-end reproduction entry point for the pdfstruct Skill.

Runs the full pipeline the Skill claims to provide, on the bundled example fixture, and
writes machine-readable outputs under execution/results/:

    result.json    the structured parse of examples/sample_two_column.pdf
    metrics.json   the ground-truth score for that parse
    summary.md     a short human-readable digest

Usage:
    python3 src/reproduce.py [--pdf PATH] [--out DIR]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from pdfstruct import document as docmod  # noqa: E402


def ensure_fixture(target_dir):
    """Build the example PDF at run time instead of shipping it.

    The platform refuses binary Skill resources, and the fixture is fully described by
    examples/make_sample.py (standard library only), so the PDF is generated into a
    temporary directory for the duration of the run and never enters the bundle.
    """
    os.makedirs(target_dir, exist_ok=True)
    pdf_path = os.path.join(target_dir, "sample_two_column.pdf")
    sys.path.insert(0, os.path.join(ROOT, "examples"))
    import make_sample  # noqa: E402

    make_sample.write_pdf(pdf_path, make_sample.build())
    return pdf_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", default=None,
                    help="PDF to parse; the bundled fixture is generated when omitted")
    ap.add_argument("--out", default=os.path.join(ROOT, "execution", "results"))
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    t0 = time.time()

    def log(msg):
        print("[reproduce] %s" % msg, flush=True)

    if args.pdf:
        pdf_path = args.pdf
    else:
        import tempfile

        tmpdir = tempfile.mkdtemp(prefix="pdfstruct-fixture-")
        pdf_path = ensure_fixture(tmpdir)
        log("generated fixture at %s (not part of the bundle)" % pdf_path)

    log("pdf=%s" % pdf_path)
    if not os.path.isfile(pdf_path):
        log("FATAL: PDF not found: %s" % pdf_path)
        return 2

    result = docmod.parse_pdf(pdf_path, case_id="sample01")
    result["changes"] = [{"what": "initial parse", "detail": "single pass, no OCR",
                          "version": docmod.VERSION}]

    result_path = os.path.join(args.out, "result.json")
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    counts = result["result"]["counts"]
    log("parsed: %s" % json.dumps(counts))
    log("wrote %s" % result_path)

    # ground-truth score of that parse
    metrics = {}
    try:
        sys.path.insert(0, os.path.join(ROOT, "tests"))
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "evaluate", os.path.join(ROOT, "tests", "evaluate.py"))
        ev = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ev)

        truth = os.path.join(ROOT, "examples", "ground_truth.json")
        sys.argv = ["evaluate", result_path, truth]
        # reuse the CLI body by capturing its metrics through a direct re-implementation
        metrics = _score(result, json.load(open(truth, encoding="utf-8")))
        mpath = os.path.join(args.out, "metrics.json")
        with open(mpath, "w", encoding="utf-8") as f:
            json.dump(metrics, f, indent=1, ensure_ascii=False)
        log("metrics: %s" % json.dumps(metrics))
        log("wrote %s" % mpath)
    except Exception as exc:  # noqa: BLE001
        log("evaluation skipped: %s: %s" % (type(exc).__name__, exc))

    summary = [
        "# pdfstruct reproduction summary",
        "",
        "- fixture: `examples/sample_two_column.pdf`",
        "- status: `%s`" % result["status"],
        "- backend: `%s`" % result["document"]["backend"],
        "- pages: %d (two-column pages: %s)" % (
            result["document"]["pages"], result["document"]["two_column_pages"]),
        "- counts: `%s`" % json.dumps(counts),
        "",
        "## Ground-truth score",
        "",
        "```json",
        json.dumps(metrics, indent=1),
        "```",
        "",
        "These numbers describe the bundled synthetic fixture only. They are not a",
        "benchmark result on the platform's fixed scientific cases.",
        "",
    ]
    spath = os.path.join(args.out, "summary.md")
    with open(spath, "w", encoding="utf-8") as f:
        f.write("\n".join(summary))
    log("wrote %s" % spath)
    log("done in %.2fs" % (time.time() - t0))
    return 0


def _score(res, truth):
    """Same checks as tests/evaluate.py, callable in-process."""
    import re

    def norm(s):
        return re.sub(r"\s+", " ", (s or "")).strip().lower()

    r = res["result"]
    found_titles = [norm(s["title"]) for s in r["sections"]]
    expected = [norm(s) for s in truth["sections"]]
    hits = [t for t in expected if t in found_titles]
    recall = len(hits) / len(expected) if expected else 0.0
    positions = [found_titles.index(t) for t in expected if t in found_titles]
    order_ok = all(a < b for a, b in zip(positions, positions[1:])) if positions else False

    t_truth = truth["tables"][0]
    table_hit = any(t["rows"] == t_truth["rows"] and t["cols"] == t_truth["cols"]
                    for t in r["tables"])
    formula_nums = {str(f.get("number")) for f in r["formulas"] if f.get("number")}
    formula_recall = len(formula_nums & set(truth["formulas"])) / len(truth["formulas"])
    fig_labels = {norm(f.get("label") or "").replace(" ", "") for f in r["figures"]}
    fig_recall = sum(1 for lab in truth["figures"]
                     if norm(lab).replace(" ", "") in fig_labels) / len(truth["figures"])
    ref_ok = len(r["references"]) == truth["references_count"]
    joined = any(norm(truth["cross_column_continuation"]) in norm(p["text"])
                 for p in r["paragraphs"])
    paras = r["paragraphs"]
    locator_cov = (sum(1 for p in paras if p.get("page") and p.get("block_id")) / len(paras)
                   if paras else 0.0)
    footer_leak = sum(1 for p in paras
                      if norm(p["text"]) in {norm(fp) for fp in truth["footer_pages"]})
    checks = [recall, 1.0 if order_ok else 0.0, 1.0 if table_hit else 0.0,
              formula_recall, fig_recall, 1.0 if ref_ok else 0.0,
              1.0 if joined else 0.0, locator_cov, 1.0 if footer_leak == 0 else 0.0]
    return {
        "section_recall": round(recall, 4),
        "section_order_correct": order_ok,
        "table_geometry_correct": table_hit,
        "formula_recall": round(formula_recall, 4),
        "figure_label_recall": round(fig_recall, 4),
        "references_count_correct": ref_ok,
        "cross_column_continuation_joined": joined,
        "block_locator_coverage": round(locator_cov, 4),
        "footer_leaked_into_body": footer_leak,
        "composite_score": round(sum(checks) / len(checks), 4),
    }


if __name__ == "__main__":
    sys.exit(main())
