# Architecture Review Checklist

Use this when pressure-testing the graph-materialization proposal.

## Import Layer

- Does the importer only materialize normalized bundles, or is it quietly reinterpreting source data?
- Are node IDs always coming from normalized files rather than being reinvented during import?
- Can the import be rerun without changing semantic identity?
- Is there a clear manifest that says what is in scope for v1?

## Promotion Boundary

- Can the graph distinguish `canonical`, `promoted`, `candidate`, and `review` objects cleanly?
- Will normal user views hide `candidate` and `review` material by default?
- Are `Mention`, `Claim`, and `ValidationCheck` clearly separated from settled facts?

## Product Tabs

- Is `Legal & Precedent` explicit enough, or is legal / precedent still buried?
- Are `Decisions` and `Records` both necessary as top-level tabs?
- Is the graph itself correctly treated as an internal engine rather than a primary nav surface?
- Does each tab answer a real user question instead of reflecting backend implementation convenience?

## Legal / Precedent

- Is the proposed `Legal & Precedent` tab backed by a real normalized bundle plan?
- Are precedent, local legal framing, and local case constraint separated clearly?
- Is the first legal import scope narrow enough to be real but broad enough to prove the model?

## Scope Control

- Are we resisting the temptation to import every bundle at once?
- Is the San Rafael governance spine enough to prove the architecture before permits, procurement, and criminal expansion?
- Does the importer stop short of doing identity resolution, extraction, or fuzzy matching itself?

## Query Value

- Can v1 answer at least three real questions end to end?
- Does one query cross campaigns, media, and official records?
- Does one query expose the legal / precedent layer?
- Does one query expose a `ValidationCheck` or reconciliation result?
