# Ralph Loop Plan

Verified: April 12, 2026

This note defines the execution pattern for breadth work after the first fixed query-pack run.

The project is no longer at the stage where "ingest a ton of stuff" is a good operating rule.

The right pattern now is a bounded Ralph loop:

1. pick one lane
2. pick one bounded batch
3. capture
4. extract
5. normalize
6. rebuild `graph-v1`
7. rerun smoke checks and the fixed query pack
8. keep the batch only if the graph got better in the way we care about

## Why This Exists

The repo already proved that raw volume is not the main bottleneck.

As of the current checkpoint:

- `Q1` passes
- `Q2` passes
- `Q3` passes
- `Q5` passes
- `Q4` fails

That means the next execution pattern should target the missing graph density directly instead of reopening broad county backfill or adding more schema.

## Ralph Loop Versus Cron

Use a Ralph loop for:

- historical backfill
- densification of a weak query lane
- bounded recovery of high-value evidence
- adapter hardening while the source shape is still moving

Use cron later for:

- stable recurring sync on already-proven adapters
- freshness maintenance after a backfill lane has settled

Current project state calls for Ralph loops, not cron.

## Loop Rules

During an active Ralph loop:

- keep the lane narrow
- freeze schema by default
- do not reopen county tracks because they are important in the abstract
- do not widen scope just because the adapter keeps working
- use the same fixed query pack after each accepted batch

A new node type is still only justified if:

1. a real source cannot be represented cleanly without it
2. a real query cannot be answered without it
3. the same object boundary appears in multiple source families

## Acceptance Gate

The loop is query-pack gated.

For the current phase:

- `Q1`, `Q2`, `Q3`, and `Q5` must remain passing
- `Q4` must improve materially

Material improvement means:

- QA-backed campaign money spans more than one cycle
- `imported_noisy_actor_count` stays at `0`
- the validation queue remains bounded and legible

## Stop Conditions

Stop and review instead of continuing automatically when:

- two consecutive batches fail to improve `Q4`
- imported noisy actors appear in graph-v1
- the validation queue grows faster than the coverage gain justifies
- the batch requires schema changes instead of parser or adapter work
- the batch mostly produces raw artifacts but no usable new joins

## Current Active Loop

The active loop is:

- `san-rafael-city-campaign-money-01`

Goal:

- turn `Q4` from fail to pass by adding multi-cycle QA-backed money coverage for San Rafael city-office races without polluting canonical actor resolution

Lane:

- San Rafael mayor and city-council campaign money

Primary source family:

- San Rafael city-side campaign filings

Working surfaces:

- public Laserfiche folder listings
- selective Form `460` OCR capture
- selective Form `460` PDF export
- schedule extraction and reconciliation

Machine-readable control file:

- [san-rafael-city-campaign-money-01.json](../registry/loop-manifests/san-rafael-city-campaign-money-01.json)

## Current Batch Strategy

Run the campaign-money loop in this order:

1. `2020` city-office Form `460` batch
2. `2022` city-office Form `460` batch
3. `2024` gap-closure batch only if `Q4` still fails

Why this order:

- `2024` already has QA-backed money
- `2020` is the fastest path to multi-cycle recurrence
- `2022` is the second strengthening cycle if `2020` alone is not enough
- more `2024` extraction should only happen if the older cycles still leave `Q4` short

## Operational Pattern

For each batch:

1. confirm the target filing IDs from the active loop manifest
2. use the existing capture workflows first
3. prefer parser or adapter fixes over schema changes
4. rebuild `graph-v1`
5. rerun:
   - `python3 scripts/graph_smoke_checks.py`
   - `python3 scripts/run_graph_query_pack.py`
6. compare the new query-pack report against the previous accepted checkpoint
7. commit only if the batch improves the target lane without breaking the others

## Notes

- The current campaign-money workflows are still target-list driven. The manifest is the control plane for what should be attempted next, even before every script is fully parameterized.
- This is not a giant autonomous ingest loop. It is a bounded execution loop with explicit acceptance gates.
- When this loop stabilizes and `Q4` passes, reevaluate whether the next best move is another San Rafael densification pass or a normalized-only county pilot.
