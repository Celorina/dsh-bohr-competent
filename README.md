# pdfstruct — structure-preserving scientific PDF parsing (Skill)

`pdfstruct` turns a scientific PDF into JSON that keeps its structure *and* its provenance:
sections with hierarchy, paragraph text in the right reading order, tables with dimensions
and cells, equations with their numbers, captions, references, and running headers/footers
separated from body text. Every element carries a `page` and a `block_id` (`p07-b012`) so a
reader can point any claim back to the exact source region.

The deliverable here is the **Skill** — `SKILL.md` plus the scripts and documentation it
needs. It is not a set of answers for any particular paper: the platform runs it on its own
fixed cases.

## Why it exists

A two-column paper read in content-stream order comes out interleaved. Both columns start at
the same height, so their lines fuse:

```
1. Introduction            2. Methods
Two-column layouts ...     one paragraph that was split ...
```

Read naively that becomes `Two-column layouts ... one paragraph that was split ...`, which is
two unrelated sentences welded together. Downstream translation, summarisation or table
reading inherits the corruption and cannot tell it happened. This Skill fixes the order
*before* anything else consumes the text.

## Repository layout

```
SKILL.md                    the Skill definition the agent loads
scripts/pdfstruct/
    backends.py             word/char extraction, backend chain, coordinates
    layout.py               line grouping, XY-cut reading order, block typing
    tables.py               table detection from repeated column alignment
    document.py             assembles result.json (sections/paras/tables/eqs/refs/missing)
scripts/cli.py              command-line entry, auto-detects the input PDF and output dir
src/reproduce.py            end-to-end run on the fixture (ARM entry point)
examples/make_sample.py     builds the two-column fixture + ground truth with stdlib only
examples/ground_truth.json
tests/evaluate.py           scores a result.json against the ground truth
execution/run.log           log of the recorded run
execution/results/          result.json, metrics.json, summary.md from that run
characterization.json       what is measured, what is not, and how it can fail
```

The fixture PDF is **not committed**: Skill resources must be text files, so
`src/reproduce.py` generates it into a temporary directory at run time and only the JSON
results are written back.

## Requirements

- Python 3.8+
- `pdfminer.six` (required)

```bash
pip install -r requirements.txt
```

`pypdf`, `pdfplumber` and `pdftotext` are optional: the parser uses them if present and
records which backend served the run in `document.backend`. Table detection is implemented
in this repository so the Skill does not depend on `pdfplumber` being installable.

## Running it

```bash
# on your own PDF
python3 scripts/cli.py --pdf paper.pdf --out /app/output --case-id case-01 --log run.log

# reproduce the bundled example and its score
python3 src/reproduce.py
python3 tests/evaluate.py execution/results/result.json examples/ground_truth.json
```

`cli.py` finds the PDF by itself when `--pdf` is omitted: it reads `case.json` (any key that
holds an existing `.pdf` path), then `/input`, `./input`, `/data`, `/materials`, then the
working directory. It writes `result.json` and `result.md` to `/app/output` by default.

## What the recorded run shows

On the bundled synthetic fixture — a two-page, two-column paper with a spanning title and
abstract, a paragraph continued across the column break, a ruled 4×4 table, two numbered
equations, a running header and page-number footers — the recorded run gives:

```json
{"section_recall": 1.0, "section_order_correct": true,
 "table_geometry_correct": true, "formula_recall": 1.0,
 "figure_label_recall": 1.0, "references_count_correct": true,
 "cross_column_continuation_joined": true,
 "block_locator_coverage": 1.0, "footer_leaked_into_body": 0,
 "composite_score": 1.0}
```

That is a regression check on a fixture whose layout this repository controls. It is **not**
a benchmark result on the platform's fixed scientific cases, and should never be reported as
one.

## Honest limits

- Pages with no text layer (scanned images) are listed under `result.missing` and are not
  OCR'd. Their content is unknown and is reported as unknown.
- Tables with merged cells, multi-level headers, or a continuation across a page break are
  reported with the geometry actually recovered; an unattributable cell stays empty.
- Equations are captured as text plus their number. Superscript/subscript positions are not
  rebuilt into LaTeX, and a formula present only as an image is not read.
- CJK text has no inter-word spaces, so the gap-based heuristics that drive column and
  heading decisions are weaker there.
- Reading order is solved per page; a paragraph continued across a *page* break is rejoined
  only when the punctuation/case heuristic fires, and every such join is listed in `changes`
  so it can be audited rather than trusted.

## Rebuilding the fixture

```bash
python3 examples/make_sample.py       # writes the PDF and ground_truth.json
```

The generator writes the PDF byte-by-byte with the standard library and no font embedding,
so the fixture rebuilds on any machine that has Python — including one with none of the PDF
libraries installed.
