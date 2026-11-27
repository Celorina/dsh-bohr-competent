---
name: pdfstruct
description: >
  Parse a scientific PDF into structure-preserving, evidence-anchored JSON. Use this when
  you must read a research paper PDF and report its sections, paragraph text, tables,
  equations, figure/table captions, references and page layout, with every element carrying
  a page number and a block id (p07-b012) that points back to the source. It is built for
  two-column and multi-column layouts, where a naive text dump interleaves columns and
  silently corrupts sentences. Trigger on: "parse this PDF", "extract sections/tables from
  this paper", "read this two-column paper", "PDF 解析", "文献解析", "提取章节/表格/公式",
  "保留页码定位", or any task needing page-anchored text from a scientific PDF.
---

# pdfstruct — structure-preserving scientific PDF parsing

## What problem this solves

A plain `pdftotext`-style dump of a two-column paper returns lines in *stream* order, not
*reading* order. Both columns start at the same height, so their lines interleave and
sentences fuse:

```
1. Introduction        2. Methods          <- two different columns, same baseline
Two-column layouts ... one paragraph that  <- left and right fused into one line
```

`pdfstruct` recovers the layout first and reads it second:

1. words are extracted with coordinates, then clustered into lines **without** letting two
   columns fuse (wide gaps are cut, not treated as spaces);
2. a recursive **XY-cut** segments the page into regions — horizontal cuts where the whole
   page is empty, vertical cuts through a corridor no line crosses — so a full-width title,
   abstract or conclusion is never assigned to a column;
3. a paragraph broken by a column or page break is rejoined, and the join is recorded;
4. every emitted element reports `page` and `block_id` such as `p07-b012`.

## When to use it

Use it whenever the deliverable has to be *checkable against the source*: section trees,
paragraph text with locators, table dimensions, equation numbers, caption lists, or a
"point every claim back to a page" requirement.

Do **not** use it when you only need a rough word count, or when the PDF has no text layer
and no OCR step is available — in that case it will report `missing` pages rather than
invent content.

## Inputs

| Input | Required | Notes |
|---|---|---|
| a PDF file | yes | located via `--pdf`, or `case.json`, or the usual `/input`, `./input`, `/data` directories |
| `case.json` | no | only used to read `case_id` and to look for a PDF path; its schema is not assumed |
| `task.md` | no | echoed into the result so the output can be read next to the request |

## Outputs

`result.json` in the output directory (default `/app/output`), plus a human-readable
`result.md`. Top level:

```json
{
  "case_id": "...",
  "status": "success | partial | cannot_determine",
  "document": {"pages": 2, "backend": "pdfminer.six", "two_column_pages": [1, 2]},
  "result": {
    "sections":   [{"level": 1, "number": "1", "title": "1. Introduction", "page": 1, "block_id": "p01-b006"}],
    "paragraphs": [{"page": 1, "block_id": "p01-b009", "text": "...", "first_sentence": "...",
                    "column": "r003", "continued_into": [{"page": 1, "block_id": "p01-b010"}]}],
    "tables":     [{"id": "t01", "page": 1, "block_id": "p01-b016", "rows": 4, "cols": 4,
                    "header": ["System", "E_bind", "Error", "Runs"], "cells": [[...]],
                    "markdown": "| System | ... |"}],
    "formulas":   [{"number": "1", "text": "E_bind = E_complex - (E_host + E_guest)",
                    "page": 1, "block_id": "p01-b015"}],
    "figures":    [{"label": "Figure1", "kind": "figure", "caption": "Figure 1. ...", "page": 2, "block_id": "p02-b008"}],
    "references": [{"text": "[1] A. Author, ...", "page": 2, "block_id": "p02-b013"}],
    "headers_footers": [{"page": 1, "band": "top", "text": "Journal ... 12 (2026) 001-002"}],
    "missing":    [{"page": 5, "what": "text layer", "reason": "scanned image page",
                    "handling": "reported and left unresolved; OCR pass required, not guessed"}],
    "counts": {"sections": 9, "paragraphs": 10, "tables": 1, "formulas": 2}
  },
  "evidence":    [{"kind": "paragraph", "block_id": "p01-b009", "page": 1, "quote": "..."}],
  "uncertainty": [{"item": "continuations", "note": "1 paragraph rejoined by heuristic"}],
  "changes":     [{"what": "continuation rejoin", "from": "p01-b009", "to": "p01-b010"}],
  "sources":     [{"type": "input_file", "path": "...", "sha256": "..."}]
}
```

`status` is `partial` whenever any page had no text layer: the parse succeeded for the rest
and the unreadable pages are listed under `result.missing`.

## How to run it

```bash
# minimal: auto-detect the PDF and the output directory
python3 scripts/cli.py --case-id demo

# explicit
python3 scripts/cli.py --pdf paper.pdf --out /app/output --case-id case-03 --log run.log
```

Exit code is 0 for both `success` and `partial`; 2 means no PDF was located, and the reason
is written into `result.json` so the caller can see it rather than only getting a code.

## Dependencies

`pdfminer.six` is required. `pypdf` is an optional last-resort backend for PDFs that
pdfminer refuses. Nothing else is needed: table detection is implemented here rather than
delegated to `pdfplumber`, specifically so the Skill installs in a bare Python image.

```bash
pip install pdfminer.six pypdf
```

The parser also tries `pdfplumber` and `pdftotext -bbox-layout` if they happen to be
present, and records which backend produced the result in `document.backend`.

## Method, and why each step exists

| Step | Method | Failure it prevents |
|---|---|---|
| word extraction | backend chain with per-backend attempts recorded | a missing library silently producing an empty result |
| line grouping | y-overlap clustering, then cut at gaps ≥ 4× the median word gap | two columns on the same baseline fusing into one line |
| region segmentation | recursive XY-cut (horizontal empty bands, then vertical corridors) | a short full-width heading being read as part of one column |
| paragraph merge | same region + gap < ~1 line height + font size within 0.6 pt | paragraphs melting into one block |
| continuation rejoin | no terminal punctuation + next fragment starts lower-case | a sentence split by the column break staying broken |
| tables | repeated column alignment of word gaps, prose cells rejected | two-column running text being reported as a table |
| formulas | equation-number suffix or math-density rule | citations and prose containing `=` being reported as equations |
| headers/footers | position band + repetition | running heads polluting the body text |

## Limits you should state when you report results

- **Scanned PDFs**: pages with no text layer are listed in `result.missing`; this Skill does
  not OCR. Do not claim their content.
- **Tables without a consistent column grid** (merged cells, multi-row headers, tables that
  continue across a page break) are reported with the geometry that was actually recovered.
  A cell that could not be attributed is left empty rather than guessed.
- **Formulas** are recovered as text with their equation number. Superscript and subscript
  positions are not reconstructed into LaTeX; a formula rendered as an image is not read.
- **CJK text** has no inter-word spaces, so word-level statistics (median gap) are less
  informative; section detection is correspondingly looser.
- **Reading order** is solved per page. A paragraph continuing across a *page* break is
  rejoined only when the punctuation/case heuristic fires; the join is always listed in
  `changes`.

## Minimal example

`examples/make_sample.py` generates a two-page, two-column fixture with no third-party
dependency. It deliberately contains a full-width title, a paragraph that starts in the left
column and ends in the right one, a ruled 4×4 table, two numbered equations, a running
header and page-number footers.

The fixture PDF is **generated at run time, not shipped**: Skill resources must be text
files, so a binary would be rejected before evaluation. `src/reproduce.py` builds it into a
temporary directory, parses it, and scores the parse:

```bash
python3 src/reproduce.py
# -> execution/results/result.json, metrics.json, summary.md
```

On that synthetic fixture the recorded run reports (these are *example* numbers for this
document, not a benchmark result on the official cases):

```json
{"section_recall": 1.0, "section_order_correct": true, "table_geometry_correct": true,
 "table_header_correct": true, "formula_recall": 1.0, "figure_label_recall": 1.0,
 "references_count_correct": true, "cross_column_continuation_joined": true,
 "block_locator_coverage": 1.0, "footer_leaked_into_body": 0, "composite_score": 1.0}
```

To run on your own document instead:

```bash
python3 scripts/cli.py --pdf your-paper.pdf --out /app/output --case-id case-01
```

## Self-check before delivering

1. `result.json` exists, parses, and has a `case_id`.
2. `status` is honest: if `missing` is non-empty, say so in the answer you give the user.
3. Spot-check two `block_id`s against the PDF page — an element whose locator does not
   resolve is worse than no locator.
4. Never fill a `missing` region by inference from the surrounding text.
