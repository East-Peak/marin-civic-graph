# Normalized Outputs

Store case-study or graph-ready candidate objects here.

Examples:

- `Meeting` candidates
- `AgendaItem` candidates
- `Decision` candidates
- `Actor` candidates
- `MoneyFlow` candidates
- `ArticleMention` candidates

Suggested shape:

```text
normalized/
  canonical-seeds-*.json
  <case_study_id>/
    <bundle_id>.json
```

Top-level files are acceptable when the bundle is a reusable seed or cross-slice identity layer rather than one case-study output.

This layer should only contain structured records that can be traced back to extracted outputs and raw evidence.
