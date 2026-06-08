# Graph Query Pack

Verified: April 12, 2026

This is the fixed five-query checkpoint for the narrowed breadth sprint.

It exists to answer one question: does each new breadth slice make the graph more useful, or just larger?

## Why This Exists

The repo now has enough normalized bundles and v2 projection coverage that the main risk is fragmentation, not missing ontology.

The query pack is the gate that keeps the sprint honest:

- do not widen county tracks because they feel important
- do not add new schema because a weird source suggests it
- do not declare success because node counts went up

Run the same five queries after each major breadth checkpoint and compare the results.

Supplemental queries can be added for adjacent lanes, but they do not change the breadth gate unless we deliberately change the sprint rules.

## Current Engine

The canonical runner is the importable `run_query_pack(projection_dir, schema="v2")`
in [run_graph_query_pack.py](../scripts/run_graph_query_pack.py). It runs over the
settled v2 (Person/Organization) projection emitted by
[build_graph_v2.py](../scripts/build_graph_v2.py) — NOT the retired graph-v1
Actor/Institution projection. C-land is v2-only, so an explicit `projection_dir`
is required; the CLI defaults to build_graph_v2's output at
`data/projected/phase0-bcore/candidate-v2/`:

- `candidate-v2/nodes.jsonl`, `candidate-v2/edges.jsonl`
- projection identity: `candidate-v2/migration-report.json` (read in place of the
  retired v1 `report.json`)

Outputs (written next to the projection):

- `query-pack-report.json`
- `query-pack-report.md`

This keeps the checkpoint runnable from repo state even when a live Neo4j session is not configured in the shell.

## Fixed Queries

### Q1: `actor-kate-colin` dossier

Return:

- actor
- seat service
- council records
- city-side committees / filings
- local Form `803`
- imported Form `700` filings

Pass condition:

- spans multiple filing families and more than one year

### Q2: current elected disclosure coverage

Start from all current San Rafael `SeatService` nodes and return every imported Form `700` / `803` filing since `2019`.

Pass condition:

- every imported disclosure resolves to an existing canonical actor and `SeatService`

### Q3: San Rafael council decision timeline

Return all San Rafael City Council `Decision` nodes since `2019` with meeting date, vote links, and evidence records.

Pass condition:

- the result is a real timeline, not just the August 19, 2024 worked example

### Q4: San Rafael election money spine

For San Rafael mayor / council elections in `2020`, `2022`, and `2024`, return:

- committees
- filings
- IE filings
- only QA-backed money flows

Pass condition:

- recurrence appears across more than one cycle without importing noisy OCR actors as durable canonical people or orgs

### Q5: validation queue

Return every `ValidationCheck` and its subject filing, especially `filing-san-rafael-campaign-entry-37677`.

Pass condition:

- the queue stays bounded and legible instead of exploding with low-quality imports

## Use

Run (defaults to build_graph_v2's candidate-v2 projection):

```bash
python3 scripts/build_graph_v2.py          # (re)build the v2 projection
python3 scripts/run_graph_query_pack.py    # run the pack over candidate-v2
```

Or import it directly:

```python
from run_graph_query_pack import run_query_pack
result = run_query_pack("data/projected/phase0-bcore/candidate-v2", schema="v2")
# -> {"ok": ..., "failures": [...], "metrics": {...}, ...}
```

The sprint rule is simple:

- if the query pack improves materially, keep going on the same San Rafael-first backbone
- if it stalls, do not widen by instinct; change the next slice deliberately

As of the first formal run, the expected interpretation is:

- Q1, Q2, Q3, and Q5 should pass if the San Rafael governance spine is healthy
- Q4 is the likely gating failure until multi-cycle QA-backed campaign money coverage improves

## Supplemental Queries

### L1: legal constraint chain

Return:

- the Boyd local case
- the full Grants Pass district -> Ninth Circuit -> Supreme Court lineage
- shared issue overlap
- shared program and local-decision links back into San Rafael
- legal record coverage across the pair

Pass condition:

- Boyd exists
- the full Grants Pass lineage exists
- the pair links back into the San Rafael sanctioned-camping / August 19, 2024 constraint posture through a shared program or at least two linked local decisions

This query is informational and product-facing, but it is not part of the fixed breadth gate.
