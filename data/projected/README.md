# Projected Graph Outputs

This layer is the bridge between `data/normalized/` and Neo4j.

Expected shape:

```text
projected/
  graph-v1/
    nodes.jsonl
    edges.jsonl
    report.json
    manifest.snapshot.json
    load-graph-v1.cypher
```

Rules:

- projection narrows bundle-local JSON into one uniform graph envelope
- projection is rebuildable from the import manifest
- Neo4j should load projected outputs, not raw normalized bundles directly
- review-only material stays out of core v1 unless the manifest includes it explicitly
