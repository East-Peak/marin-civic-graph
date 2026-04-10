# Extracted Outputs

Store machine-readable outputs derived from raw artifacts here.

Examples:

- extracted text
- heading maps
- table extraction
- quote blocks
- attachment link inventories

Suggested shape:

```text
extracted/
  <source_id>/
    <capture_date>.json
    <artifact_stem>.txt
```

These outputs are derived and reproducible. They should point back to raw capture IDs and artifact paths wherever possible.

Suggested JSON contents:

- source metadata
- artifact inventory
- extracted text paths
- page counts or link inventories where available
- lightweight candidate signals such as money values, place hits, actor hits, and legal references

The sibling `.txt` files are the plain extracted text for individual artifacts. The JSON file should describe them, not duplicate their full contents.
