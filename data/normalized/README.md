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
  <case_study_id>/
    <bundle_id>.json
```

This layer should only contain structured records that can be traced back to extracted outputs and raw evidence.
