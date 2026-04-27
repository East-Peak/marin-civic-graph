# Open Marin v2 — Architecture Design Spec

**Date:** 2026-04-26
**Status:** Draft (awaiting Codex adversarial review + Stuart approval)
**Author:** Claude (Opus 4.7 1M), with Stuart Watson
**Supersedes:** Frontend portions of `docs/specs/2026-04-19-open-marin-frontend-design.md` (Sections 4-8). Data layer, edge vocabulary, ingestion, and entity-loader contracts from the v1 spec remain authoritative.

---

## 1. Why a v2

The v1 frontend shipped (Plans 1-4a) but Stuart, the only authorized user, has not been using it. That's the data: a polished v1 graph-first interface is not the right shape. v1 also has no working surface for the analyst job-to-be-done — investigation flows like *"who funded the BoS members who voted yes on the 2024-Q3 housing item"* are not addressable in v1; the only path is click-and-expand on a force-directed canvas.

v2 demotes the graph from "primary working surface" to **"hero + browse-by-territory."** The graph is the brand and the wow moment — what makes Marin civic data feel real to outsiders. It is not where day-to-day investigation happens.

The architecture pivot:

1. **Constellation is the home page.** A full-bleed Cosmograph (WebGL, GPU-accelerated) view with cards-as-nodes, embedding-clustered regions, auto-named by Claude, gentle ambient motion. This is the demo, the showcase, the thing people see first.
2. **Workspace composition serves the analyst job.** Click any node → opens a URL-addressable composed workspace mixing dossier + egocentric graph + relevant primitives (Sankey for money, timeline for activity, map for jurisdictional anchoring, table when right). The graph is one primitive among several; investigation happens here.
3. **Question bar** is the entry point for analysts. Natural-language input routes to either a search query, a saved-query template, or a workspace composition.

Roughly 70% of the v1 codebase survives — Neo4j data layer, edge vocabulary, search backend, entity loaders, ingestion scripts, /api routes, status bar, /about. The Cytoscape canvas and everything shaped specifically for it (expand-quotas, save-view, edge-class filter UI, time slider as currently wired, pathfinding UI) is replaced.

---

## 2. What we keep / what we throw out

### Keep (v1 → v2 unchanged or near-unchanged)

- **Neo4j data layer** — schema, edges, ingestion. v2 adds new properties on existing nodes; no schema break.
- **Edge vocabulary** (`app/src/lib/edge-vocabulary.ts` + `scripts/edge_vocabulary.py`) — single source of truth for spec ↔ live mapping. Stays.
- **Ingestion scripts** under `scripts/` — refresh_openmarin.py orchestration, build_search_properties, build_record_preferred_urls, build_catalog. v2 adds three new scripts (embeddings, clusters, naming) into this pipeline.
- **Search backend** (`app/src/lib/server/search-backend.ts`) — Lucene-escaped fulltext + rank. v2 adds a vector-similarity branch but the bucketed-results contract is preserved.
- **Entity loaders** (`app/src/lib/server/entity-loader.ts`, `entity-queries.ts`, `path-finder.ts`) — Tier-1 must-show, Phase-2 fill, edges-among-selected. The dossier primitive uses these mostly as-is.
- **/api routes**: `/api/search`, `/api/entity/[id]`, `/api/expand`, `/api/path`, `/api/status`, `/api/catalog` — kept. Adds `/api/cluster`, `/api/embed`, `/api/workspace/[id]`.
- **Layout chrome**: status bar, /about page, keyboard shortcuts provider, command palette (⌘K). All keep — v2 changes what they sit on top of, not the chrome.
- **Tests**: ~300 of the ~405 v1 tests stay green (data layer, search, entity loaders, edge vocabulary, status, /about). The ~100 Cytoscape-canvas-shaped tests are replaced.

### Throw out (v1 surfaces deleted in v2)

- **`app/src/app/graph/`** — full-screen Cytoscape explorer route. Deleted.
- **`app/src/components/explorer/*`** — path dialog, edge-class filters, time slider, save-view, expand quota UI. All Cytoscape-coupled. Deleted (queries underneath are reused).
- **`app/src/lib/explorer/*`** — explorer state, expand quotas, time-range widening. Deleted (some logic moves into workspace primitives).
- **`app/src/app/data/`** — predefined-query data page. Replaced by Sankey/timeline/table workspaces.
- **`app/src/app/search/`** — search results page. Replaced by question-bar + workspace composition.
- **Cytoscape + cytoscape-fcose dependencies** — removed from package.json.

The cutover happens in a single commit at the start of Plan v2.1 (rip the dead routes), with v2 routes replacing them. There is no v1/v2 dual-stack period.

---

## 3. Architecture overview

```
┌─────────────────────────────────────────────────────────────┐
│  / (Constellation — full-bleed Cosmograph)                  │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  > [question bar]                                      │ │  question bar overlay
│  └────────────────────────────────────────────────────────┘ │
│     [cards-as-nodes, region labels, ambient motion]         │
│         │ click any node                                    │
│         ▼                                                   │
│  /w/{workspace-id}                                          │
│  ┌──────────┬───────────────┬──────────────────────────┐    │
│  │ Dossier  │ Egocentric    │ Sankey / Timeline / Map  │    │  workspace shell
│  │ (text)   │ (mini graph)  │ (one or more primitives) │    │
│  └──────────┴───────────────┴──────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘

Backend (Neo4j + scripts/ pipeline + Next.js API routes)
├── existing: ingest, edges, search index, catalog
└── new:      embeddings (OpenAI text-embedding-3-small)
              clusters (HDBSCAN)
              cluster names (Claude Haiku 4.5)
```

The frontend is a single Next.js app; routes are Constellation (`/`), workspace (`/w/{id}`), entity dossier (`/{type}/{slug}`), about (`/about`). Workspaces are URL-addressable composed views of primitives.

---

## 4. The Constellation

### 4.1 Job-to-be-done

When someone (Stuart, friend, civic researcher, demo audience) loads `openmarin.app/`, they should see a beautiful representation of Marin civic data that:

1. **Conveys the territory** — what regions of activity exist, what's adjacent to what.
2. **Reads at a glance** — region labels are human-readable ("Marin BoS housing decisions Q1 2026"), not type taxonomies.
3. **Invites click-through** — every node is something you can click into and learn about.
4. **Feels alive** — gentle ambient motion, not a static screenshot.

The Constellation is *not* for surgical relationship investigation. That happens in workspaces.

### 4.2 Renderer: Cosmograph (`@cosmograph/cosmos`)

- **Library**: `@cosmograph/cosmos` from npm (MIT licensed, free for commercial use). v2.6.x stable as of 2025-11.
- **Why**: GPU-accelerated WebGL force simulation; bloom/glow baked in; designed by ex-Linkurious team specifically for knowledge graphs; 1M+ node headroom; no licensing risk (MIT means even if Cosmograph the company sunsets, the renderer is forever-free).
- **Rejected**: Sigma.js v3 (would need ~1-2 weeks of custom WebGL programs to match Cosmograph's default visual fidelity); Cytoscape (canvas2d ceiling on bloom/glow); commercial Ogma/yFiles (licensing tail not worth it when Cosmograph is free MIT).
- **Not used**: `@cosmograph/react` (CC-BY-NC-4.0 — non-commercial, would block Open Marin's invite-only path). We write our own thin React integration, ~200 lines.

### 4.3 Cards-as-nodes

Each node renders as a small card (~120×60px at default zoom) showing type-specific content:

| Type | Top line | Body | Accent |
|---|---|---|---|
| Person | name | role · jurisdiction | colored dot for party / "official" status |
| Meeting | YYYY-MM-DD | jurisdiction · body | sparkline of agenda count |
| AgendaItem | item title (truncated to 40 chars) | meeting date · result | outcome chip (passed/failed/tabled) |
| Vote | motion (truncated) | result + tally | outcome chip |
| Filing (Form 700) | filer name | year · count of disclosures | $ heat color (sum of disclosed value) |
| Donation | $ amount | donor → recipient | $ heat color |
| Permit | type · address | status · date | status chip |
| CourtCase | case # · party | filed date · type | status chip |
| Place | name | type (city/town/county) | jurisdiction color |
| Issue | tag name | count of related items | category color |
| LLC/Org | name | type · jurisdiction | category color |

Card rendering is **off-screen canvas to a sprite atlas**, not DOM-per-node. Cosmograph consumes the sprite atlas as a texture; each node references its sprite by index. This is how we get 100K+ cards-as-nodes at 60fps. The sprite atlas is rebuilt when underlying entity data changes (nightly).

**Semantic zoom.** Three zoom tiers:

- **Far zoom (>20K nodes visible)**: nodes collapse to type-colored dots with cluster region labels dominating. The territory is the visual.
- **Mid zoom (200-20K)**: nodes are tiny cards, top line only. Cluster labels still visible but smaller.
- **Close zoom (<200)**: full cards, hover-expand showing top-3 connections. Cluster labels fade out (you're inside a cluster now).

Cosmograph supports zoom-level callbacks; we use them to swap node-program shaders and toggle label rendering layers.

### 4.4 Region labels (cluster overlays)

Cluster regions render as **semi-transparent floating labels** above their convex hull. Each label is the LLM-generated name (3-5 words, e.g. "San Rafael housing votes"). At far zoom, region labels are large and dominant; at close zoom they fade.

Implementation: HTML overlay layer (DOM), positioned via Cosmograph's coordinate-space-to-screen-space transform. Labels track node positions as the simulation settles. Performance: ~50-150 cluster labels max, well within DOM rendering capacity.

### 4.5 Ambient motion

Cosmograph's force simulation runs at low alpha continuously (`alpha: 0.01`) so the graph breathes — never fully stops. Selecting a node temporarily raises alpha for a quick re-settle, then decays back to ambient.

Hover: 1-hop neighbors brighten (alpha node-program parameter), everything else dims to ~25% opacity, edges to highlighted set become fully opaque.

Click: opens the workspace for that node (see §5). Constellation remains visible behind the workspace shell as a dimmed backdrop, restoring the "you came from here" thread.

### 4.6 Lenses (deferred to Plan v2.7)

Plan v2.1 ships one lens — HDBSCAN-by-embedding clusters with auto-named regions. Plan v2.7 adds toggle-able lenses:

- **Money lens**: edge weight tied to $ flow magnitude; recipient nodes sized by total received.
- **Recency lens**: node luminance tied to most-recent-activity date; older nodes fade to grey.
- **Influence lens**: node size tied to graph centrality (PageRank or betweenness, computed offline).
- **Issue lens**: cluster-by-Issue-tag instead of by embedding; useful when issue tags are clean.

Lenses are a top-bar toggle. Each is a different node-program / edge-program shader configuration. State is in URL: `/?lens=money`.

---

## 5. Workspaces

### 5.1 What a workspace is

A workspace is a **URL-addressable composed view** that answers a specific question. URL: `/w/{workspace-id}`. Workspace state is encoded in the URL path + query string so it can be shared, bookmarked, embedded.

Two kinds of workspaces:

1. **Entity workspaces** — opened by clicking a node in Constellation. Composes: dossier (left, ~40%) + egocentric graph (top right, ~30%) + one or two contextual primitives (bottom right, ~30%) selected by entity type. URL: `/w/entity/{type}/{slug}`.
2. **Question workspaces** — opened by submitting a query in the question bar. Composes whatever primitives best answer the question. URL: `/w/q/{question-hash}` plus query parameters.

### 5.2 Entity workspace composition (per type)

| Type | Right-pane primary | Right-pane secondary |
|---|---|---|
| Person | Egocentric graph (1-hop) | Sankey: donations received → flowed to votes |
| Meeting | Egocentric graph | Timeline: agenda items in order |
| AgendaItem | Egocentric graph | Vote tally widget |
| Vote | Egocentric graph | Sankey: yea/nay/abstain breakdown by faction |
| Filing | Egocentric graph | Table: disclosed line items |
| Donation | Egocentric graph | Sankey: flow context |
| Permit | Map (centered on parcel) | Timeline: status changes |
| CourtCase | Egocentric graph | Timeline: docket events |
| Place | Map (centered on jurisdiction) | Egocentric graph |
| Issue | Egocentric graph | Timeline of related events |

Composition is **declarative** — a config object per entity type maps to primitives. Adding a new primitive is a config change, not a workspace rewrite.

### 5.3 Workspace shell

The shell is a CSS grid with three slots (left dossier, top-right primary, bottom-right secondary). Shell handles:

- URL ↔ state sync
- Loading skeleton per slot
- Empty / error states per primitive
- A "back to Constellation" affordance (top-left, dimmed Constellation visible behind a translucent panel)
- A breadcrumb showing how you got here (Constellation → entity name)
- Save-workspace button (writes a saved workspace doc to Neo4j; reload-able)

Shell is ~300 lines. Each primitive is a self-contained React component receiving entity context via props.

### 5.4 Workspace primitives — interface contract

Every primitive implements:

```typescript
type PrimitiveProps = {
  entity: { id: string; type: string; label: string };  // null for question workspaces
  context?: { question?: string; params?: Record<string, string> };
  onNavigate: (target: { type: string; id: string }) => void;
};

type Primitive = React.FC<PrimitiveProps>;
```

Self-contained: each primitive owns its own data fetching, loading state, errors, and click-through to other entities (which navigates the workspace, not the URL).

---

## 6. Working primitives

### 6.1 Dossier

Text-heavy entity page. Largely the v1 entity-page component, refactored as a workspace primitive (drops the global header/footer; expects to be embedded). Sections: identity card, key facts, recent activity, citations, evidence drawer. Server component using `entity-loader.ts`.

### 6.2 Egocentric graph

A small focused Cosmograph view (~600×400 default), centered on the entity, showing 1-2 hop neighborhood. Reuses Constellation's Cosmograph integration but with different defaults (smaller, no region labels, focused force simulation). When user clicks a node in the egocentric graph, the workspace navigates to that entity.

### 6.3 Sankey (money flow)

D3-based Sankey rendering (visx or @nivo/sankey — pick one in implementation; visx is closer to bare D3 and gives more control, @nivo is faster to build).

For a Person: shows donations-in (left) → that person (middle) → votes-they-cast-on-funded-issues (right). Width-encodes $ magnitude.

For a Vote: shows donor → recipient (BoS member) → outcome (yea/nay/abstain), grouped by faction.

For a Donation: shows donor → recipient → subsequent vote correlations.

Click any band/node in the Sankey navigates the workspace.

### 6.4 Timeline ribbon

D3-based horizontal time scrubber. Activity events render as ticks along a date axis; hover shows event details; click navigates. Scrubbing the time range filters the rest of the workspace primitives (egocentric graph, Sankey) to that window.

### 6.5 Map

MapLibre GL JS (open source; replaces commercial Mapbox). Renders permits as parcel markers, meetings as jurisdiction-centered clusters, places as boundary polygons. Overlays civic data on the geographic substrate.

Marin County boundary GeoJSON shipped with the app (~50KB). Jurisdiction boundaries from CalGIS open data.

### 6.6 Table

Plain HTML table for tabular drilldowns. Sortable, sticky headers. Lowest-effort primitive; copies columns from the entity's properties + relevant relations. Used when neither graph nor Sankey nor timeline fits.

---

## 7. Question bar

Renders as an input element overlaid on the Constellation (and on every workspace's top chrome).

### 7.1 Initial routing (keyword only — Plan v2.3)

```
input → /api/search (existing) → results dropdown
                              ↓ Enter
                   /w/entity/{type}/{slug}  (top result)
                                  or
                   /w/q/{hash}  (multi-result composition)
```

### 7.2 LLM-mediated routing (deferred to Plan v2.7)

Claude Haiku 4.5 reads the input, classifies (entity-lookup / relationship-question / aggregate-question / unknown), and routes:

- entity-lookup → `/w/entity/...`
- relationship-question (e.g. "who funded the BoS members on housing votes") → `/w/q/...` with a Sankey + timeline composition
- aggregate-question (e.g. "total donations to Novato candidates 2024") → table + Sankey
- unknown → fall back to keyword search

The routing prompt is small (~200 tokens), Haiku response is small (~50 tokens), latency target <500ms.

LLM routing ships in Plan v2.7. Keyword routing (Plan v2.3) is the first version of the question bar.

---

## 8. Data model additions

Existing v1 schema is preserved. v2 adds these properties to all entity nodes:

| Property | Type | Source | Indexed |
|---|---|---|---|
| `embedding` | `vector(1536)` | OpenAI text-embedding-3-small | Yes (Neo4j HNSW vector index, default cosine) |
| `embedding_text` | `string` | Synthesized doc rendered for embedding | No |
| `embedding_version` | `int` | Bumped when synthesis logic changes | No |
| `embedded_at` | `datetime` | When this embedding was last computed | No |
| `cluster_id` | `int` | HDBSCAN cluster assignment | Yes (range index) |
| `cluster_label` | `string` | Claude-named region | No |
| `cluster_centroid_distance` | `float` | Distance to cluster centroid (for centroid-vs-edge lens) | No |
| `centrality_pagerank` | `float` | Computed offline, for Influence lens | No |

Vector index: `CREATE VECTOR INDEX entity_embedding IF NOT EXISTS FOR (n) ON (n.embedding) OPTIONS {indexConfig: {'vector.dimensions': 1536, 'vector.similarity_function': 'cosine'}}`.

**No schema break.** All properties are optional; v1 queries continue to work; v2 adds them as it embeds.

---

## 9. Backend services

### 9.1 Embedding pipeline

**Script**: `scripts/build_embeddings.py`. Run on-ingest (incremental) and nightly (refresh stale).

For each node, render `embedding_text` from properties + top-N relationships:

```
{type} · {label}
{role or description if available}
Jurisdiction: {jurisdiction_name}
Recent activity: {top 5 relations summarized}
```

Batch through OpenAI `text-embedding-3-small` (1536 dim, $0.02/1M tokens). Batch size 100. Write `embedding`, `embedding_version`, `embedded_at` back to the node.

**Incremental logic**: on-ingest runs immediately after node create/update if `embedded_at IS NULL OR <synth_time_of_source_data`. Nightly job re-checks all nodes against current `embedding_version`.

**Cost ceiling**: ~$1.14 for first full embed of 114K entities @ 500 tokens; ~$5/month for refresh + new entities.

### 9.2 Clustering pipeline

**Script**: `scripts/build_clusters.py`. Nightly batch.

1. Pull all `embedding` vectors from Neo4j (114K × 1536 = ~700MB; fits in Mac mini RAM).
2. Run HDBSCAN (min_cluster_size=15, min_samples=5) → cluster_id per node.
3. Compute centroid per cluster, distance per node.
4. Diff against previous run: clusters with Jaccard <0.8 vs previous are flagged for re-naming.
5. Write `cluster_id`, `cluster_centroid_distance` to Neo4j.

Library: `hdbscan` Python package. Nightly job duration: ~2-3 minutes for 114K nodes.

### 9.3 Cluster-naming pipeline

**Script**: `scripts/name_clusters.py`. Runs after clustering, only re-names flagged clusters.

For each flagged cluster, sample 5-10 nodes closest to the centroid, send to Claude Haiku 4.5:

```
Prompt: "These N entities cluster together based on civic-data embeddings:
- {label1} ({type1}) · {key_fact1}
- {label2} ({type2}) · {key_fact2}
...
Name this region in 3-5 words. Examples: 'San Rafael housing votes', 'north county Form 700 conflicts', 'Novato campaign finance flows'.
Output only the name."
```

Write `cluster_label` to all nodes in the cluster. Cache names in Neo4j; only re-name when membership shifts.

**Cost**: ~$0.04 per full naming pass; ~$1/month with daily-refresh-of-shifted-clusters.

### 9.4 Centrality pipeline (deferred to Plan v2.7)

`scripts/build_centrality.py`. Weekly batch. Uses NetworkX or Neo4j Graph Data Science library (free Community edition). Computes PageRank and betweenness centrality per node. Writes `centrality_pagerank` to nodes. Used by the Influence lens.

### 9.5 Pipeline integration

`scripts/refresh_openmarin.py` (existing) gets two new steps:

```
... existing steps ...
build_embeddings.py            # incremental, ~30s
build_clusters.py              # full, ~2 min
name_clusters.py               # delta only, ~30s
update_sync_state.py           # bumps :_SyncState
copy-subgraphs.mjs             # existing
```

---

## 10. Frontend tech stack

### 10.1 Stack

- Next.js 16 (App Router) — kept from v1
- React 19, TypeScript 5, Tailwind 4 — kept
- IBM Plex (Sans/Mono/Serif) + VT323 — kept
- **New**: `@cosmograph/cosmos` (graph renderer)
- **New**: `@visx/sankey` (Sankey)
- **New**: `maplibre-gl` (map)
- **Removed**: `cytoscape`, `cytoscape-fcose`, all explorer-coupled plugins

### 10.2 Routes

| Route | Purpose | Server/Client |
|---|---|---|
| `/` | Constellation (full-bleed) | Client (Cosmograph mount) with server-rendered status bar |
| `/w/entity/{type}/{slug}` | Entity workspace | Server-rendered shell, client-rendered primitives |
| `/w/q/{hash}` | Question workspace | Server-rendered shell, client-rendered primitives |
| `/{type}/{slug}` | Standalone entity dossier (kept for sharing) | Server |
| `/about` | Methodology page | Server (kept from v1) |
| `/api/*` | Existing + new endpoints | Server |

### 10.3 New API endpoints

- `GET /api/cluster/{id}` — returns cluster membership + label + centroid for the Constellation hover-detail.
- `POST /api/embed` — embeds a single ad-hoc text query (for question-bar similarity search).
- `POST /api/workspace` — saves a workspace state (returns workspace-id).
- `GET /api/workspace/{id}` — loads saved workspace state.

---

## 11. Phasing — implementation plans

Each plan is independent and Stuart-review-gated. We can stop after any plan and what's shipped is coherent.

### Plan v2.1 — Constellation MVP (1.5-2 weeks)

Cosmograph integration, cards-as-nodes for top 6 entity types (Person, Meeting, AgendaItem, Vote, Filing, Donation), embedding pipeline, clustering pipeline, naming pipeline, region labels, ambient motion. Replaces v1 homepage. Ships as `/`.

Includes deletion of `/graph`, `/data`, `/search` routes and removal of Cytoscape dependencies in a single commit at plan start.

### Plan v2.2 — Workspace shell + dossier + egocentric graph (1 week)

Workspace shell (CSS grid + URL state), dossier primitive (refactor of v1 entity page), egocentric graph primitive. Click-from-Constellation flow lights up. Ships as `/w/entity/{type}/{slug}`.

### Plan v2.3 — Question bar v1 (3-5 days)

Input element + keyword routing via existing `/api/search`. Top-result-jumps-to-entity-workspace; multi-result lands on a question workspace stub. LLM routing deferred to v2.7.

### Plan v2.4 — Sankey primitive (1 week)

`@visx/sankey` integration, three Sankey shapes (Person/Vote/Donation), wired into Person/Vote/Donation entity workspaces.

### Plan v2.5 — Timeline primitive (3-5 days)

D3-based timeline ribbon, scrub-to-filter, wired into Meeting/Filing/CourtCase/Issue workspaces.

### Plan v2.6 — Map primitive (1 week)

MapLibre integration, jurisdiction GeoJSON bundle, parcel markers for permits, jurisdiction boundary rendering for Place. Wired into Permit/Place workspaces.

### Plan v2.7 — Table primitive + LLM question routing + Constellation Phase 2 lenses (1.5-2 weeks, optional)

- Table primitive (lowest priority).
- LLM-mediated question routing via Claude Haiku.
- Constellation lenses: money / recency / influence / issue.

Stop or continue based on use after v2.6.

---

## 12. Migration / cutover

### 12.1 What lands in v2.1's first commit

- Delete `/graph`, `/data`, `/search` routes.
- Delete `app/src/components/explorer/`, `app/src/lib/explorer/`.
- Remove Cytoscape from `package.json`.
- Add Cosmograph mount as new `/` page (initially with placeholder data).
- Add new pipeline scripts (no-op until embeddings populate).
- Plan 4b (auth + Vercel deploy) is unchanged — still deferred until Constellation MVP ships, then revisited.

### 12.2 Tests

The ~100 v1 tests coupled to Cytoscape canvas / explorer state are deleted as part of the cutover. The ~300 tests for data layer / search / entity loaders / edge vocabulary stay green.

New v2 tests:

- Embedding text synthesizer (unit, ~10 cases per entity type)
- HDBSCAN cluster assignment (integration, against fixed embedding fixtures)
- Cluster-name prompt → response shape (integration, mocked Claude)
- Cosmograph mount (smoke; full WebGL not testable in jsdom)
- Cards-as-nodes sprite atlas builder (unit, asserts atlas size + per-type rendering)
- Workspace shell URL ↔ state sync (unit)
- Each primitive's render contract (component test with mocked entity data)

Total expected v2 test count: ~300 v1 survivors + ~150 new = ~450.

### 12.3 Data backfill

Plan v2.1's deploy unblocks the embedding/clustering/naming pipelines, but the Constellation can't render until those have run for the full graph. First full pipeline run: ~5 minutes (embeddings) + ~3 minutes (clustering) + ~30 seconds (naming) = 9-10 minutes. We backfill once at v2.1 cutover, then nightly thereafter.

Until backfill completes, Constellation renders a "Building constellation..." progress page. Acceptable since this happens once.

---

## 13. Out of scope

- **Multi-tenant or non-Marin data.** v2 stays Marin-only. Generalization is a future product question.
- **Mobile responsiveness for Constellation.** Cosmograph + WebGL on mobile is unreliable; mobile users hit a "view on desktop" page for `/`. Workspaces (`/w/...`) responsively work on mobile.
- **Real-time collaboration on workspaces.** Save-workspace is single-user. Shared cursors / presence is a future feature, deferred.
- **Export to PDF / report builder.** Eventually valuable, not in v2.
- **AI-summary panels in dossiers.** Tempting but distinct from workspace composition; deferred.
- **Public unlocked surface.** v2 stays invite-only behind Plan 4b auth (when 4b lands).

---

## 14. Open questions

1. **Cosmograph React integration code**: write our own or fork `@cosmograph/react` and re-license? The CC-BY-NC license likely cannot be re-licensed by us; we write our own glue. **Resolution: write our own (~200 lines).**
2. **Embedding refresh on graph-structural changes** (e.g., a person joins a new committee — should that re-embed both endpoints?): yes, but with a Bloom-filter dirty-check to avoid pointless re-embeds. **Resolution: implement in Plan v2.1.**
3. **Do we need separate embedding spaces per entity-type cluster** (so Filings cluster with Filings, not with Meetings)? **Resolution: no. Whole-graph single embedding space is the Kat-Zhang move; mixed-type clusters are a feature.**
4. **What's the minimum cluster size before HDBSCAN gives noise?** Tuning parameter; default 15 is reasonable for ~114K nodes. Tune in Plan v2.1 against actual data.
5. **Auth + deploy timing**: does Plan 4b ship before or after Plan v2.1? **Resolution: after. Deploying a rudimentary v1 to Vercel is wasted demo capital. Constellation MVP first, then auth+deploy when there's something to authenticate to.**

---

## 15. Success criteria

After Plan v2.1 ships:

- Stuart loads `openmarin.app/` and the Constellation makes him want to show someone.
- A test user can click any node, land in a workspace, read the dossier + see the egocentric graph, and click through to a related entity without rereading documentation.
- The full pipeline (embedding + clustering + naming) runs nightly without manual intervention.
- Cost: < $10/month total OpenAI + Anthropic.

After Plan v2.4 (Sankey ships):

- Stuart can demo "donor → BoS member → housing vote" in one click from a Person workspace.

After Plan v2.6 (full primitive set):

- Most civic-investigation questions Stuart asks have a workspace shape that answers them without code.

If any of these don't land, we re-spec rather than push more polish at the wrong shape.

---

*End of spec.*
