#!/usr/bin/env python3
"""Score a pdfstruct result.json against examples/ground_truth.json.

Produces machine-readable numbers rather than an opinion: section recall and order,
table geometry, formula numbers, figure labels, reference count, whether a paragraph split
by the column break was rejoined, block-locator coverage, and whether the running
header/footer leaked into body text.
"""
import json
import os
import re
import sys


def norm(s):
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


def main():
    result_path = sys.argv[1]
    truth_path = sys.argv[2] if len(sys.argv) > 2 else os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "examples", "ground_truth.json")
    out_path = sys.argv[3] if len(sys.argv) > 3 else None

    res = json.load(open(result_path, encoding="utf-8"))
    truth = json.load(open(truth_path, encoding="utf-8"))
    r = res["result"]

    found_titles = [norm(s["title"]) for s in r["sections"]]
    expected = [norm(s) for s in truth["sections"]]
    hits = [t for t in expected if t in found_titles]
    recall = len(hits) / len(expected) if expected else 0.0

    # order: expected titles must appear in the same relative order in the output
    positions = [found_titles.index(t) for t in expected if t in found_titles]
    order_ok = all(a < b for a, b in zip(positions, positions[1:])) if positions else False

    tables = r["tables"]
    t_truth = truth["tables"][0]
    table_hit = any(t["rows"] == t_truth["rows"] and t["cols"] == t_truth["cols"] for t in tables)
    table_exact = table_hit and any(
        [norm(c) for c in t["header"]] == [norm(c) for c in t_truth["header"]]
        for t in tables if t["rows"] == t_truth["rows"] and t["cols"] == t_truth["cols"])

    formula_nums = {str(f.get("number")) for f in r["formulas"] if f.get("number")}
    formula_recall = len(formula_nums & set(truth["formulas"])) / len(truth["formulas"])

    fig_labels = {norm(f.get("label") or "").replace(" ", "") for f in r["figures"]}
    fig_recall = sum(1 for lab in truth["figures"]
                     if norm(lab).replace(" ", "") in fig_labels) / len(truth["figures"])

    ref_ok = len(r["references"]) == truth["references_count"]

    joint = truth["cross_column_continuation"]
    joined = any(norm(joint) in norm(p["text"]) for p in r["paragraphs"])

    paras = r["paragraphs"]
    locator_cov = (
        sum(1 for p in paras if p.get("page") and p.get("block_id")) / len(paras)
        if paras else 0.0
    )

    body_text = " ".join(p["text"] for p in paras)
    # a footer leaks when a paragraph IS a bare page number, not when one merely contains
    # a digit somewhere (e.g. "Table 1 was recovered ...")
    footer_leak = sum(1 for p in paras
                      if norm(p["text"]) in {norm(fp) for fp in truth["footer_pages"]})

    metrics = {
        "sections_expected": len(expected),
        "sections_found": len(hits),
        "section_recall": round(recall, 4),
        "section_order_correct": order_ok,
        "table_geometry_correct": table_hit,
        "table_header_correct": table_exact,
        "tables_detected": len(tables),
        "formula_recall": round(formula_recall, 4),
        "figure_label_recall": round(fig_recall, 4),
        "references_count_correct": ref_ok,
        "cross_column_continuation_joined": joined,
        "block_locator_coverage": round(locator_cov, 4),
        "footer_leaked_into_body": footer_leak,
        "status": res.get("status"),
    }
    # a single headline number for tracking improvements across runs
    checks = [
        recall,
        1.0 if order_ok else 0.0,
        1.0 if table_hit else 0.0,
        1.0 if table_exact else 0.0,
        formula_recall,
        fig_recall,
        1.0 if ref_ok else 0.0,
        1.0 if joined else 0.0,
        locator_cov,
        1.0 if footer_leak == 0 else 0.0,
    ]
    metrics["composite_score"] = round(sum(checks) / len(checks), 4)

    print(json.dumps(metrics, indent=1, ensure_ascii=False))
    if out_path:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(metrics, f, indent=1, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
