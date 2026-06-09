# Claude Collaboration Handoff

Verified: April 14, 2026

This is the durable handoff for bringing Claude into the project without relying on prior Codex chat history.

It is intentionally expansive.

It should be enough to:

- explain what the project is
- explain how the repo is structured
- explain what has already been built
- explain what is still missing
- let a second model pick up bounded work without re-deriving the architecture

## Short Version

Marin Civic Graph is a primary-source civic-intelligence graph for Marin County, with San Rafael as the most advanced jurisdiction.

The graph is no longer just schema and sample baskets. It now has:

- a live normalized data spine
- a v2-native projection layer (`build_graph_v2.py` → `candidate-v2/`; the legacy `build_graph_projection` CLI and `migrate_graph_v2` are retired)
- an import manifest
- a local Neo4j load path
- a fixed query pack
- a projected JSON read-model layer
- a thin local shell over projected JSON

The current rule is:

- do not add more ontology by default
- do not widen source coverage just because a source exists
- use the bounded question set as the gate for future work

## What This Project Is Trying To Do

The product thesis is simple:

- local government is formally public but practically obscure
- primary-source records should make institutional process legible
- the graph should help answer defensible civic-process questions without overclaiming

The repo is designed to answer questions like:

- who decided this
- which meeting and agenda item covered it
- what records supported it
- what money, counterparties, programs, or projects were adjacent to it
- what legal constraints bear on it
- what still does not reconcile cleanly

It is explicitly not trying to become:

- a partisan scorecard
- an unsupported corruption detector
- a black-box influence engine

## Current Architecture

There are four durable data layers:

1. `data/raw/`
   Exact captured artifacts:
   - HTML
   - PDF
   - XML
   - OCR text
   - browser-visible text proxies
   - capture manifests

2. `data/extracted/`
   Parsed or derived outputs:
   - text extraction
   - OCR output
   - row inventories
   - schedule extraction
   - page-level summaries

3. `data/normalized/`
   Stable graph-ready objects with IDs and explicit joins.

4. `data/projected/graph-v1/`
   Materialized graph payload:
   - `nodes.jsonl`
   - `edges.jsonl`
   - `report.json`
   - `query-pack-report.json`
   - projected dossier / summary views

Important rule:

- Neo4j is a rebuildable materialization target, not the primary source of truth.

The truth of the project lives in:

- raw artifacts
- extracted outputs
- normalized bundles

## Current Graph State

As of April 14, 2026:

- graph-v1 projection: `6267` nodes / `21262` edges
- fixed query pack: `5/5` passing
- supplemental legal constraint query: passing
- projected view pack: `22` views
- remaining completeness gaps:
  - no `missing_target:Actor`
  - no `missing_target:Record`
  - no `missing_target:Issue`

Core graph-v1 coverage now includes:

- meetings
- agenda items
- decisions
- records
- actors
- institutions
- seats
- seat services
- elections
- committees
- filings
- economic-interest disclosures
- money flows
- validation checks
- cases
- proceedings
- case participations
- programs
- projects
- agreements
- amendments
- issues
- places

## What Has Already Been Built

### 1. San Rafael civic-process backbone

This is the strongest lane in the repo.

It includes:

- full `2019+` San Rafael City Council meeting-page corpus
- citywide minutes-backed agenda-item and decision layer
- explicit council decision continuity across years
- officeholder identity / seat / seat-service layer

This is what made the graph stop being a set of worked examples and start being an actual civic spine.

### 2. Campaign / disclosure lane

San Rafael is now materially modeled for:

- city-side campaign filing discovery
- folder-listing capture
- direct filing OCR
- direct filing PDF export
- `Form 460` schedule extraction
- QA-backed validation checks
- Form `700`
- Form `803`

Important boundary:

- broad row-level donor import is still intentionally suppressed
- one-off OCR-tainted row actors stay as labels on `MoneyFlow` nodes unless known or repeated

### 3. Legal lane

The legal lane is real, but still bounded.

Current imported legal pair:

- `Boyd v. City of San Rafael`
- `City of Grants Pass v. Johnson`

Including:

- district / appellate / Supreme Court lineage for Grants Pass
- TRO / PI / dismissal order coverage for Boyd
- crosswalks back into San Rafael local decisions and programs

Important boundary:

- legal is strong enough for graph-v1 import
- legal is not yet a broad court-intelligence lane

### 4. Read-model layer

The graph is no longer only machine-shaped.

It now emits bounded JSON read models:

- actor dossiers
- organization dossier
- decision dossier
- case dossier
- program dossiers
- project dossiers
- jurisdiction delivery summary
- decision-money rollup
- decision-money explanation
- local-pressure summaries
- local-pressure comparison
- local-pressure explanation
- legal-constraint summary
- validation queue

These are data contracts, not frontend work.

### 5. Local thread comparison

The current north-star answer is already materialized.

The San Rafael local-pressure comparison currently spans `7` bounded local threads:

- `2` program threads
- `3` project threads
- `2` election threads

Those threads are:

- `program-san-rafael-sanctioned-camping`
- `program-san-rafael-camping-ordinance-implementation`
- `project-san-rafael-350-merrydale-interim-shelter`
- `project-downtown-library-renovation`
- `project-700-irwin-st`
- `election-2024-11-05-san-rafael-general`
- `election-2020-11-03-san-rafael-general`

This is the current best answer path for the product.

## Current North-Star Question

The active question set lives in:

- [question-set-v1.md](./question-set-v1.md)
- [question-set-v1.yaml](../registry/question-set-v1.yaml)

The current north-star question is:

`QX-001`: Which San Rafael local threads carry the most combined money pressure and legal pressure, and who are the recurring counterparties around them?

This is the key discipline rule for future work:

- do not widen the graph because a domain seems interesting
- widen only when it materially improves one of the bounded product questions

## Most Important Current Outputs

If Claude needs fast orientation, these are the highest-signal files:

### State and control

- [README.md](../README.md)
- [decision-log.md](./decision-log.md)
- [question-set-v1.md](./question-set-v1.md)
- [open-questions.md](./open-questions.md)
- [graph-query-pack.md](./graph-query-pack.md)
- [graph-read-model-contracts.md](./graph-read-model-contracts.md)

### Graph materialization

- [import-manifest.yaml](../registry/import-manifest.yaml)
- [build_graph_v2.py](../scripts/build_graph_v2.py) — **the** v2-native projector (manifest → Person/Organization in one pass). Output: `data/projected/phase0-bcore/candidate-v2/`.
- [projection_helpers.py](../scripts/projection_helpers.py) — shared projection-phase helpers reused by build_graph_v2 (extracted from the now-deleted build_graph_projection.py; `migrate_graph_v2` is deleted).
- [graph_projection_lib.py](../scripts/graph_projection_lib.py)
- [run_graph_query_pack.py](../scripts/run_graph_query_pack.py) — `run_query_pack(projection_dir, schema="v2")` over candidate-v2.
- [migration-report.json](../data/projected/phase0-bcore/candidate-v2/migration-report.json)
- [query-pack-report.json](../data/projected/phase0-bcore/candidate-v2/query-pack-report.json)

### Read-model layer

- [build_graph_views.py](../scripts/build_graph_views.py)
- [view-targets.yaml](../registry/view-targets.yaml)
- [index.json](../data/projected/graph-v1/views/index.json)
- [summary.md](../data/projected/graph-v1/views/summary.md)

### Highest-signal example outputs

- [jurisdiction-san-rafael-local-pressure-comparison.json](../data/projected/graph-v1/views/jurisdiction-san-rafael-local-pressure-comparison.json)
- [jurisdiction-san-rafael-local-pressure-explanation.json](../data/projected/graph-v1/views/jurisdiction-san-rafael-local-pressure-explanation.json)
- [project-san-rafael-350-merrydale-interim-shelter-dossier.json](../data/projected/graph-v1/views/project-san-rafael-350-merrydale-interim-shelter-dossier.json)
- [program-san-rafael-sanctioned-camping-local-pressure-summary.json](../data/projected/graph-v1/views/program-san-rafael-sanctioned-camping-local-pressure-summary.json)
- [case-boyd-v-city-of-san-rafael-dossier.json](../data/projected/graph-v1/views/case-boyd-v-city-of-san-rafael-dossier.json)
- [validation-queue.json](../data/projected/graph-v1/views/validation-queue.json)

## Most Important Modeling Rules

These rules matter more than any individual slice.

### 1. Primary-source evidence first

Prefer:

- official meeting pages
- official minutes
- official packets
- official staff reports
- official filings
- official court records where available

Media can enrich, but should not outrank stronger official evidence.

### 2. Stable IDs in normalized data

The normalized layer carries stable IDs and explicit joins.

Projection and Neo4j materialization are rebuildable derivatives.

### 3. Bounded promotion

Do not promote a node just because a string exists.

Promotion should happen when one of these is true:

- the source materially supports a stable object boundary
- the object is reused across source families
- a real product question needs the object

### 4. Label-only is allowed

For noisy campaign rows especially:

- unresolved one-off counterparties can stay as normalized labels on `MoneyFlow`
- not every name becomes an `Actor`

This is how the graph avoids fake recurrence.

### 5. Read models are not graph truth

The projected dossiers and summaries are convenience outputs.

They should explain the graph, not invent it.

## What Still Needs Work

The repo is far along, but it is not done.

The main unfinished areas are:

### 1. More representative local pressure threads

The current San Rafael comparison is good enough to be useful, but still intentionally bounded.

The next widening trigger should be:

- a genuinely different local pressure pattern
- or a local thread the current question set cannot represent well

Not just more count.

### 2. Historical backfill beyond the current dense slices

We already have inventories and adapters for:

- San Rafael City Council
- Marin County BOS
- Marin County campaign finance exports
- San Rafael Form 700
- San Rafael city-side campaign filings

But most of that historical breadth is not yet imported at the same depth as the dense San Rafael spine.

### 3. Broader legal and permit depth

The current legal pair is enough for the active product questions.

The permit and procurement lanes are real, but not imported broadly into graph-v1.

They are intentionally bounded and should stay that way unless a product question requires more.

### 4. More explicit user-facing question discipline

We now have a bounded question set, but it is still early.

The next layer is not more schema. It is sharper product questions and tighter “what counts as a good answer” criteria.

## What Claude Should Not Redo

Claude should not spend time:

- redesigning the whole schema from scratch
- proposing a new giant ontology tranche
- building a big frontend
- reopening county-wide breadth just because it exists
- broad-importing noisy donor / vendor actor names
- treating projected read models as the source of truth

Those are all low-value relative to the current repo state.

## Good Bounded Work For Claude

These are the most useful lanes for parallel help.

### Good lane A: bounded thread widening

Find one more San Rafael local thread that materially improves `QX-001`, but only if it adds a different pressure pattern and can be built from existing or easily captured primary-source evidence.

### Good lane B: answer-quality review

Stress-test the existing read models:

- what answer is still weak
- what evidence is thin
- what joins feel brittle

### Good lane C: historical depth in an existing lane

Stay inside a lane we already know works:

- San Rafael council
- San Rafael disclosures
- San Rafael campaign money

Do not open a brand-new domain family unless a question forces it.

### Good lane D: legal support provenance

Tighten the legal lane only where it improves an existing answer, not as a standalone docket-collection hobby.

## Practical Work Split Between Codex And Claude

If you want parallel work, the cleanest split is:

### Codex

- keeps doing source-adapter, extraction, normalization, projection, and graph-shape work
- does bounded structural changes
- handles scripts, manifests, rebuilds, and validation

### Claude

- reviews current answer quality
- proposes bounded new local threads
- critiques read-model usefulness
- drafts product-facing explanation layers or additional JSON contracts
- helps with frontend later if needed

That split keeps Claude away from re-litigating core graph architecture while still giving it high-leverage work.

## Pasteable Prompt For Claude

Use this if you want to drop Claude directly into the current project state:

```text
You are joining an active civic-graph project midstream. Do not redesign the whole project from scratch.

Repo:
/Users/tammypais/projects/marin-civic-graph

Read first:
- /Users/tammypais/projects/marin-civic-graph/README.md
- /Users/tammypais/projects/marin-civic-graph/docs/claude-collaboration-handoff.md
- /Users/tammypais/projects/marin-civic-graph/docs/question-set-v1.md
- /Users/tammypais/projects/marin-civic-graph/docs/open-questions.md
- /Users/tammypais/projects/marin-civic-graph/docs/decision-log.md
- /Users/tammypais/projects/marin-civic-graph/data/projected/graph-v1/query-pack-report.json
- /Users/tammypais/projects/marin-civic-graph/data/projected/graph-v1/views/jurisdiction-san-rafael-local-pressure-comparison.json
- /Users/tammypais/projects/marin-civic-graph/data/projected/graph-v1/views/jurisdiction-san-rafael-local-pressure-explanation.json

Current state:
- graph-v1 projection: 6267 nodes / 21262 edges
- fixed query pack: 5/5 passing
- active north-star question: which San Rafael local threads carry the most combined money pressure and legal pressure, and who are the recurring counterparties around them?
- current comparison spans 7 bounded local threads across programs, projects, and elections

Rules:
- do not propose a giant new ontology tranche by default
- do not reopen county-wide breadth by default
- do not treat projected views as source truth
- do not broad-import noisy donor names as actors
- prefer bounded work that materially improves the current question set

Your job:
1. Identify the weakest current answer in the question set.
2. Propose one or two bounded next slices that materially improve answer quality.
3. Say what Claude should own vs what Codex should own.
4. If useful, draft a product-facing explanation or critique of the current read-model layer.

Output:
- findings first
- then recommended next slice
- then recommended work split between Claude and Codex
```

## Final Orientation

The repo is at the stage where discipline matters more than imagination.

There is already enough architecture.

The best contributions now are the ones that:

- improve answer quality
- preserve evidence discipline
- avoid fake precision
- and keep the graph widening only when a bounded question actually needs it
