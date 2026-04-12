# Controlled Breadth Sprint Adversarial Review Checklist

Use this to attack the widening plan before execution.

The point is to challenge scope, sequencing, and evidence discipline, not to reopen abstract ontology debates.

## Scope

- Is the sprint still too broad for one phase?
- Is it too narrow to actually increase recurrence density?
- Should one of the five proposed tracks be deferred?
- Is there a missing high-value source family already in scope that should be included?

## Sequence

- Is the proposed execution order correct?
- Should San Rafael city-side campaign filings move earlier because they are the biggest overlap surface?
- Should Form `700` / `803` move earlier because officeholder continuity is cleaner than campaign OCR work?
- Should Marin County campaign finance move later if yearly exports are already sufficiently covered for now?

## Graph Value

- Which track most improves the fixed query set?
- Which track adds volume without improving joins?
- Which track is most likely to reveal actor-resolution weaknesses?
- Which track is most likely to improve decision and money recurrence quickly?

## Product Relevance

- After this sprint, what user-facing questions become answerable that are not answerable now?
- Does the plan improve `Actors`, `Decisions`, `Money`, and `Investigate`, or mostly just ingest more files?
- Are we widening around actual civic questions or just around adapter convenience?

## Data Quality

- Which proposed track has the highest extraction-error risk?
- Which proposed track is most likely to pollute canonical actors if imported too early?
- Should some tracks stay normalized-only longer instead of entering graph-v1 quickly?
- Are the current `ValidationCheck` and review boundaries strong enough for broader campaign ingestion?

## Operational Risk

- Which track is most likely to burn time on anti-bot / session / export quirks?
- Which track has the cleanest repeatable access pattern?
- Should the sprint explicitly cap time spent on brittle adapter problems before moving to the next track?
- Are we distinguishing “public but gated here” from “actually unavailable” clearly enough?

## Import Scope

- Which new bundles should definitely stay out of graph-v1 during the sprint?
- Should the legal pair remain normalized-only until after the breadth sprint?
- Should procurement and permits remain normalized-only until the core civic spine gets denser?
- Is there any discovery-stage material still at risk of slipping into the core import?

## Kill Criteria

- What would tell us the sprint is drifting into another architecture exercise?
- What would tell us the sprint is just creating file volume without graph value?
- What should force a pause and re-plan?

## End-State Decision

At the end of review, force concrete answers to:

1. What exact tracks are in?
2. What exact tracks are out?
3. What is the execution order?
4. What is the fixed query pack used to judge success?
5. What import-scope decision should be reconsidered only after the sprint completes?
