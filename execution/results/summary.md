# pdfstruct reproduction summary

- fixture: `examples/sample_two_column.pdf`
- status: `success`
- backend: `pdfminer.six`
- pages: 2 (two-column pages: [1, 2])
- counts: `{"sections": 9, "paragraphs": 11, "tables": 1, "formulas": 2, "figures": 2, "references": 2, "headers_footers": 4, "missing": 0}`

## Ground-truth score

```json
{
 "section_recall": 1.0,
 "section_order_correct": true,
 "table_geometry_correct": true,
 "formula_recall": 1.0,
 "figure_label_recall": 1.0,
 "references_count_correct": true,
 "cross_column_continuation_joined": true,
 "block_locator_coverage": 1.0,
 "footer_leaked_into_body": 0,
 "composite_score": 1.0
}
```

These numbers describe the bundled synthetic fixture only. They are not a
benchmark result on the platform's fixed scientific cases.
