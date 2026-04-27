# Open Marin v2 — Architecture Design Spec

**Date:** 2026-04-26
**Status:** Draft (Codex round 1 applied; awaiting round 2 review)
**Author:** Claude (Opus 4.7 1M), with Stuart Watson
**Supersedes:** Frontend portions of `docs/specs/2026-04-19-open-marin-frontend-design.md` (Sections 4-8). Data layer, edge vocabulary, ingestion, and entity-loader contracts from the v1 spec remain authoritative.

---

## 1. Why a v2

The v1 frontend shipped (Plans 1-4a) but Stuart, the only authorized user, has not been using it. That's the data: a polished v1 graph-first interface is not the right shape. v1 also has no working surface for the analyst job-to-be-done — investigation flows like *"who funded the BoS members who voted yes on the 2024-Q3 housing item"* are not addressable in v1; the only path is click-and-expand on a force-directed canvas.

v2 demotes the graph from "primary working surface" to **"hero + browse-by-territory."** The graph is the brand and the wow moment — what makes Marin civic data feel real to outsiders. It is not where day-to-day investigation happens.

The architecture pivot:

1. **Constellation is the home page.** A full-bleed Cosmograph (WebGL) rendering of all entities laid out by **UMAP projection of their semantic embeddings**, with cards-as-nodes (tiered by zoom), cluster regions floating over the projection, region labels auto-named. This is the demo, the showcase. Layout is semantic, not topological — clusters in embedding space land as contiguous spatial regions because the layout itself is the embedding projection.
2. **Workspace composition serves the analyst job.** Click any node → opens a URL-addressable composed workspace mixing dossier + egocentric graph + relevant primitives (adjacency-flow for money, timeline for activity, map for jurisdictional anchoring, table when right). The graph is one primitive among several; investigation happens here.
3. **Question bar** is the entry point for analysts. Natural-language input routes to either a search query, a saved-query template, or a workspace composition.

Roughly 60% of the v1 codebase survives — Neo4j data layer, edge vocabulary, search backend, entity loaders, ingestion scripts, /api routes, status bar, /about. The Cytoscape canvas and everything shaped specifically for it (expand-quotas, save-view, edge-class filter UI, time slider as currently wired, pathfinding UI) is replaced.

The "60% survives" claim is honest: meaningful new infrastructure (UMAP pipeline, cluster pipeline, naming pipeline, payload publish, sprite atlas, workspace shell, primitive interface, Cosmograph integration) is being built, and v2.1 itself is a 3-4 week effort, not a UI refresh.

---

## 2. What we keep / what we throw out

### Keep (v1 → v2 unchanged or near-unchanged)

- **Neo4j data layer** — schema, edges, ingestion. v2 adds new properties on existing nodes; no schema break.
- **Canonical type ontology** (`app/src/lib/type-display.ts`): `Person, Organization, Committee, Seat, SeatService, Election, Candidacy, Meeting, AgendaItem, Decision, Filing, MoneyFlow, Case, Proceeding, Project, Program, Agreement, Amendment, Record, Place, Issue`. v2 honors these names exactly — no renaming.
- **Edge vocabulary** (`app/src/lib/edge-vocabulary.ts` + `scripts/edge_vocabulary.py`) — single source of truth for spec ↔ live mapping. Stays.
- **Ingestion scripts** under `scripts/` — `refresh_openmarin.py` orchestration, `build_search_properties.py`, `build_record_preferred_urls.py`, `build_catalog.py`. v2 adds five new scripts (embeddings, UMAP, clusters, names, constellation payload) into this pipeline.
- **Search backend** (`app/src/lib/server/search-backend.ts`) — Lucene-escaped fulltext + rank. v2 adds a vector-similarity branch but the bucketed-results contract is preserved.
- **Entity loaders** (`app/src/lib/server/entity-loader.ts`, `entity-queries.ts`, `path-finder.ts`) — Tier-1 must-show, Phase-2 fill, edges-among-selected. The dossier primitive uses these mostly as-is.
- **/api routes**: `/api/search`, `/api/entity/[id]`, `/api/expand`, `/api/path`, `/api/status`, `/api/catalog` — kept. Adds `/api/cluster/[id]`, `/api/embed`, `/api/constellation-manifest`.
- **Layout chrome**: status bar, /about page, keyboard shortcuts provider, command palette (⌘K). All keep.
- **Tests**: ~280 of the ~405 v1 tests stay green (data layer, search, entity loaders, edge vocabulary, status, /about). The ~125 Cytoscape-canvas-shaped tests are replaced.

### Throw out — staged, NOT in v2.1's first commit

Rather than a single-commit rip-out (which Codex flagged correctly: it leaves users without `/search` until v2.3 ships), v2 stages deletions to match replacement availability:

- **Plan v2.1 (Constellation MVP)** deletes `/graph` and `app/src/components/explorer/*` only. Cytoscape and cytoscape-fcose dependencies are removed at this point. `/search` and `/data` remain functional throughout v2.1.
- **Plan v2.3 (Question bar)** deletes `/search` only after the question bar is shipped and proven.
- **Plan v2.4-v2.6 (Sankey/timeline/map)** retire `/data` incrementally as predefined queries get replaced with workspace primitives. The final `/data` deletion lands in Plan v2.6.

There is no v1/v2 dual-stack period for the same surface — but during the v2 build, surviving v1 surfaces (`/search`, `/data`) stay as fallbacks until their v2 replacements ship.

---

## 3. Architecture overview

```
┌─────────────────────────────────────────────────────────────┐
│  / (Constellation — full-bleed Cosmograph, UMAP layout)     │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  > [question bar]                                      │ │
│  └────────────────────────────────────────────────────────┘ │
│     [cards-as-nodes (tiered), region labels, gentle drift]  │
│         │ click any node                                    │
│         ▼                                                   │
│  /w/{workspace-id}                                          │
│  ┌──────────┬───────────────┬──────────────────────────┐    │
│  │ Dossier  │ Egocentric    │ Adjacency-flow / Timeline│    │
│  │ (text)   │ (mini graph)  │ Map / Table              │    │
│  └──────────┴───────────────┴──────────────────────────┘    │
│  Workspace state: shared store, URL-serialized              │
└─────────────────────────────────────────────────────────────┘

Backend (Neo4j + scripts/ pipeline + Next.js API routes)
├── existing: ingest, edges, search index, catalog
├── new pipelines (scripts/):
│   build_embeddings.py       # OpenAI text-embedding-3-small
│   build_umap.py             # UMAP 1536 → 2 (cached, stable)
│   build_clusters.py         # HDBSCAN on UMAP-reduced coords
│   match_clusters.py         # Hungarian matching across runs
│   name_clusters.py          # Deterministic + Claude Haiku improve
│   publish_constellation.py  # Bake JSON payload to public/constellation.json
└── new API: /api/cluster, /api/embed, /api/workspace, /api/constellation
```

The frontend is a single Next.js app; routes are Constellation (`/`), workspace (`/w/{id}`), entity dossier (`/{type}/{slug}`), about (`/about`). Workspaces are URL-addressable composed views of primitives.

---

## 4. The Constellation

### 4.1 Job-to-be-done

When someone (Stuart, friend, civic researcher, demo audience) loads `openmarin.app/`, they should see a beautiful representation of Marin civic data that:

1. **Conveys the territory** — what regions of activity exist, what's adjacent to what.
2. **Reads at a glance** — region labels are human-readable ("Marin BoS housing decisions Q1 2026"), not type taxonomies.
3. **Invites click-through** — every node is something you can click into and learn about.
4. **Feels alive** — gentle ambient drift, not a static screenshot.

The Constellation is *not* for surgical relationship investigation. That happens in workspaces.

### 4.2 Renderer: Cosmograph (`@cosmograph/cosmos`)

- **Library**: `@cosmograph/cosmos` from npm (MIT licensed, free for commercial use). v2.6.x stable.
- **Why**: GPU-accelerated WebGL rendering; bloom/glow baked in; designed for knowledge graphs; 1M+ node headroom; no licensing risk (MIT).
- **Not used**: `@cosmograph/react` (CC-BY-NC-4.0 — non-commercial). We write our own thin React integration (~200 lines).
- **Force simulation: disabled.** Node positions come from the UMAP projection (§4.3). Cosmograph supports passing fixed `(x,y)` coordinates per node; we use this. No force calculation runs at render time.

### 4.3 Layout: UMAP projection of embeddings

This is the central architectural decision and the answer to the "do clusters land as spatial regions?" problem.

Each entity has a 1536-dim semantic embedding (§9.1). The layout projects all embeddings to 2D via UMAP (`umap-learn`, Python, run as nightly batch). The projection's (x, y) coordinates are persisted as node properties (`umap_x`, `umap_y`) and shipped in the Constellation payload.

Why UMAP, not force-directed:

- **Cluster geometry matches visual geometry.** HDBSCAN clusters are computed on the 2D UMAP output (§9.4), and UMAP preserves embedding-space locality. So clusters in 2D approximate the dense regions of the 1536-d embedding distribution. Region labels can sit over their convex hulls without lying about visible structure.
- **Stable across days.** UMAP with fixed `random_state` and `init='spectral'` produces near-identical projections across nightly runs (with some drift on new entities). Force simulation, by contrast, finds a fresh local minimum every reload — positions drift visibly between sessions.
- **Semantic, not topological.** Force layout shows graph connectivity (who's edge-adjacent to whom). UMAP shows semantic similarity (who's *about* similar things). For "show me the territory of Marin civic data," the latter is the right map.
- **Edges remain as decoration.** Edges (graph relationships) still render between UMAP-positioned nodes — they're informative as a layer but they're not load-bearing for the layout. Two nodes can be far apart in UMAP space but graph-adjacent (e.g., a Person and an unusual Filing they signed); the edge tells that story.

UMAP parameters (initial; tune in Plan v2.0 benchmark):

```python
umap_model = UMAP(
    n_components=2,
    n_neighbors=30,         # smaller = local structure; larger = global
    min_dist=0.1,
    metric="cosine",        # matches our embedding similarity metric
    random_state=42,
    init="spectral",
    n_jobs=-1,
)
```

For 114K × 1536 embeddings: UMAP fit takes ~3-5 minutes on the Mac mini (M-series, single-threaded `n_jobs=1` is ~10 min; multithreaded much faster). Output is 114K × 2 array of (x, y).

**Stability on incremental updates.** Adding a small batch of new entities nightly: we re-run UMAP `transform` (not `fit`) using the cached `fit` model from the prior full run. Full `fit` runs weekly to absorb drift. This keeps positions stable for existing nodes day-to-day.

**Procrustes alignment on every full fit.** Raw UMAP `fit` can rotate, mirror, or rescale the entire projection across runs even when local structure is preserved. To prevent the territory from "spinning" weekly, every full fit emits raw `(x', y')` coordinates that are then **Procrustes-aligned to the prior week's persisted `(x, y)`** before write-back. The aligned coordinates are what land in Neo4j and the payload — never raw `fit` output. Library: `scipy.spatial.procrustes` or equivalent.

**Hard drift budget**, enforced as gate on the publish step:
- Per-node displacement >25% of map width = block publish, alert Stuart.
- Per-cluster-centroid displacement >15% of map width = block publish, alert Stuart.
- If breach, `publish_constellation.py` republishes the prior week's payload unchanged and the alert names the offenders for human review.

This makes "stable territory" a measurable contract, not a hope.

### 4.4 Cards-as-nodes — tiered rendering

Three rendering tiers driven by zoom level. Sprite atlases are not pre-built for all 100K nodes — that's 2.8GB of texture and unfeasible. Instead:

| Tier | Zoom level | What's rendered | Sprite source |
|---|---|---|---|
| Tier A — dot | far (>10K nodes visible) | Type-colored dot, 4-8px | One static atlas (21 type colors × 3 sizes = 63 sprites). Generated once at build time. |
| Tier B — glyph | mid (1K–10K visible) | Dot + 1-line type abbrev (3 chars) | Generated at build time per type. ~150 sprites total. |
| Tier C — card | close (<1K visible) | Full ~120×60 card with type-specific content (§4.5) | **Generated on-demand** for nodes in the current viewport, via offscreen canvas. Cached in a sprite atlas per zoom session, capped at 2,000 sprites. Older sprites are evicted LRU. |

The on-demand Tier C generator is a Web Worker that takes a node's payload + type → renders to OffscreenCanvas → returns ImageBitmap → uploaded to Cosmograph as a sprite. Generation budget: 200 sprites/second on a modern machine, ample for the 1K-visible threshold.

Tier transitions are smoothed: on zoom-in past the threshold, Tier B nodes fade to Tier C as their sprites populate; on zoom-out, Tier C nodes downgrade to Tier B/A immediately (no fade).

**Memory ceiling.** Tier A+B = ~5MB texture. Tier C = max 2K cards × 120 × 60 × 4 bytes = 56MB. Total ~60MB texture budget. Comfortably within mobile-class GPUs (we're desktop-only for `/`, but headroom is good).

### 4.5 Card content (per canonical type)

Cards (Tier C) render type-specific content. Schema below uses the actual canonical types from `type-display.ts`:

| Type | Top line | Body | Accent |
|---|---|---|---|
| Person | name | role · jurisdiction | colored dot for party / official status |
| Organization | name | subtype · jurisdiction | category color |
| Committee | name | candidate · FPPC ID | jurisdiction color |
| Seat | title | institution · jurisdiction | jurisdiction color |
| SeatService | seat title · person | start–end | jurisdiction color |
| Election | date · jurisdiction | type | — |
| Candidacy | person · seat | filed date | outcome chip |
| Meeting | date | jurisdiction · institution | sparkline of agenda count |
| AgendaItem | item title (≤40 chars) | meeting date · result | outcome chip |
| Decision | motion (≤40 chars) | vote tally · institution | outcome chip |
| Filing | filer name | type · period | $ heat (sum disclosed) |
| MoneyFlow | $ amount | donor → recipient | $ heat color |
| Case | caption (≤40 chars) | docket · status | status chip |
| Proceeding | case # · type | occurred date | status chip |
| Project | name | status · address | status chip |
| Program | name | type · jurisdiction | category color |
| Agreement | parties summary | effective date | status chip |
| Amendment | parent · summary | date | status chip |
| Record | title (≤40 chars) | source · date | source-type chip |
| Place | name | type (city/town/county) | jurisdiction color |
| Issue | tag name | count of related items | category color |

### 4.6 Region labels

Cluster regions render as semi-transparent floating labels above their UMAP-space convex hull (or alpha-shape for clusters with concavity). Each label is the cluster name (§9.4 — deterministic-with-LLM-improvement, not pure LLM hallucination).

Implementation: HTML overlay layer (DOM), positioned via Cosmograph's coordinate-space-to-screen-space transform. Labels track UMAP positions; since UMAP positions are stable, label placement is stable too.

At far zoom: region labels are large and dominant; cards collapse to dots. At close zoom: labels fade out (you're inside a cluster, the type is visible from cards directly).

Max ~80-150 cluster labels (HDBSCAN tuning targets this range). DOM overlay scales fine to that count.

**Fallback rendering.** If a cluster has no label (LLM call failed, deterministic fallback empty), the region renders without a label rather than with a placeholder. Better empty than wrong.

### 4.7 Ambient motion

No force simulation runs at render time (positions are fixed from UMAP). The "alive" feeling comes from:

- **Gentle camera drift** — slow auto-pan + zoom oscillation (~30-second cycle, 5% pan amplitude, 10% zoom amplitude). Pauses on user interaction; resumes after 5s of idle.
- **Per-node sparkle** — random nodes get a brief 200ms luminance pulse, ~3 nodes/second. Cosmetic.
- **Hover halo** — hovered node gets bloom intensifies; 1-hop neighbors brighten slightly; everything else dims to ~25%.

Click: opens the workspace. **Constellation is NOT kept alive as a backdrop** behind the workspace (permanent WebGL would tax every page). The back-link affordance combines two pieces:

1. **Camera state in URL** — when navigating from `/` to `/w/...`, the URL captures `?from_x=&from_y=&from_zoom=&from_umap_version=` so reloads / shared links / cold-start workspaces can restore the Constellation to the same view on return. This is the load-bearing path home and works even without a snapshot.
2. **Optional PNG snapshot** — a low-res capture taken at click-through is rendered as a 120×80px thumbnail in the back-link button. Polish, not load-bearing. Reloads of a workspace from a fresh tab show the back-link without a snapshot (just text + a Constellation glyph).

Clicking either restores the Constellation at the captured camera state (if `from_umap_version` matches current; otherwise restores at default zoom and shows a small "territory updated" badge).

### 4.8 Lenses (deferred to Plan v2.7)

Plan v2.1 ships one lens: the HDBSCAN-on-embedding clusters with auto-named regions. Plan v2.7 adds toggle-able lenses:

- **Money lens**: edge weight tied to $ flow magnitude; recipient nodes sized by total received.
- **Recency lens**: node luminance tied to most-recent-activity date; older nodes fade to grey.
- **Influence lens**: node size tied to graph centrality (PageRank or betweenness, computed offline).
- **Issue lens**: cluster-by-Issue-tag instead of by embedding; useful when issue tags are clean.

Lenses are a top-bar toggle. Each is a different node-program / edge-program shader configuration. State is in URL: `/?lens=money`.

---

## 5. Workspaces

### 5.1 What a workspace is

A workspace is a **URL-addressable composed view** that answers a specific question. Two kinds:

1. **Entity workspaces** — `/w/entity/{type}/{slug}`, opened by clicking a Constellation node.
2. **Question workspaces** — `/w/q/{hash}`, opened by submitting a query in the question bar.

Workspace state is encoded in URL path + query string so it's shareable, bookmarkable, embeddable.

### 5.2 Entity workspace composition (per canonical type)

| Type | Right-pane primary | Right-pane secondary |
|---|---|---|
| Person | Egocentric graph (1-hop) | Adjacency-flow: documented MoneyFlows received → Decisions cast |
| Organization | Egocentric graph | Adjacency-flow: MoneyFlows touching this org |
| Committee | Egocentric graph | Adjacency-flow: in/out flows by year |
| Seat / SeatService | Egocentric graph | Timeline: tenure with overlaid Decisions |
| Election / Candidacy | Egocentric graph | Adjacency-flow: candidate funding + outcomes |
| Meeting | Egocentric graph | Timeline: AgendaItems in order |
| AgendaItem | Egocentric graph | Decision tally widget |
| Decision | Egocentric graph | Adjacency-flow: vote split + funding context (factual, not causal) |
| Filing | Egocentric graph | Table: disclosed line items |
| MoneyFlow | Egocentric graph | Adjacency-flow: source → destination chain |
| Case / Proceeding | Egocentric graph | Timeline: docket events |
| Project | Map (centered on parcel) | Timeline: status changes + related Decisions |
| Program | Egocentric graph | Timeline + Adjacency-flow |
| Agreement / Amendment | Egocentric graph | Timeline: amendment chain |
| Record | Dossier extract | (no right pane — Records are evidence, not subjects) |
| Place | Map (centered on jurisdiction) | Egocentric graph |
| Issue | Egocentric graph | Timeline of related events |

Composition is **declarative** — a config object `app/src/lib/workspace-config.ts` maps type → primitives. Adding a new primitive is a config change.

### 5.3 Workspace shell

CSS grid with three slots (left dossier ~40%, top-right primary ~30%, bottom-right secondary ~30%). Shell handles:

- URL ↔ state sync via the workspace state schema (§5.4)
- Loading skeleton per slot
- Empty / error states per primitive
- A "back to Constellation" affordance: button in the top-left that routes to `/` with `?focus_x=&focus_y=&zoom=&umap_version=` so the Constellation restores to the workspace's anchor view. PNG snapshot is optional polish (rendered as a thumbnail in the button when available; absent on cold reloads).
- A breadcrumb showing how you got here (Constellation → entity name)
- ~~Save-workspace button~~ — deferred to a later plan. v2.2 ships URL-only state; URL is the share/save mechanism.

Shell is ~400 lines. Each primitive is a self-contained React component receiving entity context via props + reading shared state from the workspace store (§5.4).

### 5.4 Workspace state schema

A canonical state object lives in a Zustand store (or Jotai — pick in implementation). The shape:

```typescript
type WorkspaceState = {
  // Identity
  kind: "entity" | "question";
  entity?: { type: NodeType; id: string; label: string };
  question?: { text: string; hash: string };

  // Cross-primitive filters
  timeRange: { start: string | null; end: string | null };  // ISO; null = unbounded
  jurisdictionFilter: string[];                              // empty = all
  edgeClassFilter: ("governance" | "money" | "legal-constrains")[];  // empty = all

  // Per-primitive params (each primitive owns a key)
  primitiveParams: Record<string, Record<string, unknown>>;
  // e.g., primitiveParams.timeline = { hoveredEvent: "..." }
  //       primitiveParams.adjacency = { focusFlow: "..." }

  // Selection (cross-primitive)
  selectedEntityId: string | null;

  // Camera state for back-to-Constellation restoration
  fromConstellation?: {
    x: number; y: number; zoom: number; umap_version: number;
  };
};

// DB-backed saved workspaces (workspaceId, savedAt) are deferred to a
// later plan. v2.2 relies on URL serialization only — the URL itself
// is the shareable, reloadable, persistent form.
```

URL-serialization:

- `kind`, `entity` or `question`, `timeRange`, `jurisdictionFilter`, `edgeClassFilter`, `selectedEntityId`, `fromConstellation` are encoded in the URL query string.
- `primitiveParams` is local-only (ephemeral state like hover that shouldn't survive navigation).
- A workspace URL is fully reconstructable from URL alone — no DB lookup required.

Cross-primitive coordination: timeline scrub updates `timeRange`; egocentric graph and adjacency-flow filter against it. Selection in any primitive sets `selectedEntityId`; other primitives optionally highlight it.

The store exposes typed selectors (`useTimeRange`, `useSelectedEntityId`, etc.) so primitives read only the slices they need.

### 5.5 Primitive interface

```typescript
type PrimitiveProps = {
  // Read-only entity/question context
  entity?: { id: string; type: NodeType; label: string };
  question?: { text: string; hash: string };

  // Navigation callback (workspace handles URL update)
  onNavigate: (target: { type: NodeType; id: string }) => void;
};

type Primitive = React.FC<PrimitiveProps>;
```

Primitives:
- Read shared state via Zustand selectors (timeRange, filters, selection).
- Write to shared state via Zustand actions (setSelection, scrubTimeRange).
- Own their own data fetching against `/api/*`.
- Render their own loading/empty/error states.

Primitives do NOT own the URL; the workspace shell does. Primitives can request URL updates via store actions, which the shell observes and reflects.

---

## 6. Working primitives

### 6.1 Dossier

Text-heavy entity page. Largely the v1 entity-page component, refactored as a workspace primitive (drops the global header/footer; expects to be embedded). Sections: identity card, key facts, recent activity, citations, evidence drawer. Server component using `entity-loader.ts`.

### 6.2 Egocentric graph

A small focused Cosmograph view (~600×400 default), centered on the entity, showing 1-2 hop neighborhood. Reuses Constellation's Cosmograph integration but with different defaults (smaller, no region labels, force simulation enabled here since it's <100 nodes). Click a node → workspace navigates.

### 6.3 Adjacency-flow primitive (replaces "Sankey")

**Reframed from the v1 spec to honor the project's evidence-first non-goals.**

Shows directional adjacency between entities — *what's documented to flow from where to where* — without implying causality. Built on `@visx/sankey` for layout but labeled and copy-edited as "documented adjacency," not "influence."

#### 6.3.1 Band-construction rules per workspace type

Each workspace shape has a deterministic band-construction rule. Below, "anchor" is the workspace's entity. "Time window" defines what counts as "in the same period." Bands violating the eligibility rule (§6.3.2) are silently dropped, not collapsed into "other."

**Person workspace** (anchor: Person)
- Time window: rolling 24 months ending at `max(MoneyFlow.flow_date for flows touching anchor)`, OR if anchor has no flows, the most recent SeatService term boundary.
- Left bands: MoneyFlows where `flow.recipient = anchor` AND `flow.flow_date IN window`. One band per source.
- Center: anchor.
- Right bands: Decisions where `anchor IS_VOTING_MEMBER_OF Decision.institution` AND `Decision.decided_at IN window`. One band per Decision.
- Band width: $ magnitude on left side; uniform on right side (Decisions don't have $ weight).
- Citation requirements: every left band needs a Filing-citation on the MoneyFlow; every right band needs a Decision record from primary minutes.

**Decision workspace** (anchor: Decision)
- Time window: rolling 24 months ending at `Decision.decided_at`.
- Left bands: MoneyFlows where `flow.recipient IN { voting members of Decision } AND flow.flow_date IN window`. Bands grouped by member, then by source.
- Center: Decision (split into yea / nay / abstain sub-nodes).
- Right bands: members → their vote (yea/nay/abstain) on this Decision. Width: uniform.
- Citation requirements: every MoneyFlow needs a Filing citation; the Decision itself needs a primary-minutes citation.

**MoneyFlow workspace** (anchor: MoneyFlow)
- Time window: rolling 24 months ending at `flow.flow_date`.
- Left bands: source filing → flow.
- Center: flow.recipient.
- Right bands: recipient's recorded activities in window — Decisions cast (if recipient is Person), grants disbursed (if recipient is Org), Filings filed (any). Each as a separate band.
- Citation requirements: source filing must be a primary-source FPPC / Form 700 record; right-side activities must have their own primary-source citations.

**Committee workspace** (anchor: Committee)
- Time window: calendar year of `committee.year` or current year if `committee.year IS NULL`.
- Left bands: in-flows (`MoneyFlow.recipient = committee`).
- Center: committee.
- Right bands: out-flows (`MoneyFlow.source = committee`).
- Citation requirements: every flow needs an FPPC schedule citation.

**Organization workspace** (anchor: Organization)
- Same shape as Committee, with time window = rolling 36 months.

For all other entity types, adjacency-flow is not the primary primitive (timeline or table is); workspace config opts out.

#### 6.3.2 Eligibility rule

An adjacency-flow band is only rendered if **every** endpoint and the middle join have a primary-source citation. No flow without provenance — this enforces the project's evidence-first stance.

A "primary-source citation" means: an FPPC report ID, a Form 700 line number, a meeting-minutes URL, a court docket number, a permit ID, or another canonical primary-source field present on the source data. Inferred or derived data does not qualify.

#### 6.3.3 Disclaimer copy

Every adjacency-flow widget renders a disclaimer line below the diagram:

> *Adjacency only. Each band reflects two independently-documented records connected by a shared entity. No causal relationship between funding receipt and subsequent Decisions is asserted by this view.*

#### 6.3.4 Interaction

Each band/node is clickable to navigate. Hover surfaces the underlying citations (Filing IDs, FPPC report IDs, Form 700 line numbers, minutes URLs) in a tooltip.

### 6.4 Timeline ribbon

D3-based horizontal time scrubber. Activity events render as ticks along a date axis; hover shows event details; click navigates. Scrubbing updates `timeRange` in shared workspace state, which filters egocentric graph and adjacency-flow.

### 6.5 Map

MapLibre GL JS (open source). Renders Projects as parcel markers (where lat/long is available), Meetings as jurisdiction-centered clusters, Places as boundary polygons. Marin County boundary GeoJSON shipped with the app (~50KB) plus jurisdiction boundaries from CalGIS open data.

### 6.6 Table

Plain HTML table for tabular drilldowns. Sortable, sticky headers. Lowest-effort primitive; copies columns from the entity's properties + relevant relations. Used when neither graph nor adjacency-flow nor timeline fits.

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
- relationship-question (e.g., "who funded the BoS members on housing votes") → `/w/q/...` with adjacency-flow + timeline composition
- aggregate-question (e.g., "total funding to Novato candidates 2024") → table + adjacency-flow
- unknown → fall back to keyword search

Routing prompt ~200 tokens, response ~50 tokens, latency target <500ms.

LLM routing ships in Plan v2.7. Keyword routing (Plan v2.3) is the first version of the question bar.

---

## 8. Data model additions

Existing v1 schema is preserved. v2 adds these properties to all entity nodes:

| Property | Type | Source | Indexed |
|---|---|---|---|
| `embedding` | `vector(1536)` | OpenAI text-embedding-3-small | Yes (Neo4j HNSW vector index, cosine) |
| `embedding_hash` | `string` | SHA-256 of synthesized text + included relation IDs | No |
| `embedding_version` | `int` | Bumped when synthesis logic changes | No |
| `embedded_at` | `datetime` | When this embedding was last computed | No |
| `umap_x`, `umap_y` | `float` | UMAP-projected position | Yes (range index for spatial queries) |
| `umap_version` | `int` | Bumped when UMAP fit refreshes (weekly) | No |
| `cluster_id` | `int` | HDBSCAN cluster assignment (post-matching, stable across runs) | Yes |
| `cluster_label` | `string` | Region name (deterministic + Claude-improved) | No |
| `cluster_centroid_distance` | `float` | Distance to cluster centroid | No |
| `centrality_pagerank` | `float` | Computed weekly; for Influence lens | No |

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
Recent activity:
- {top 5 relations by edge weight, summarized}
```

**Synthesis hash for dirty-detection.** Compute `embedding_hash = sha256(embedding_text + sorted([rel_id_1, rel_id_2, ...]))` over the exact node properties + relation IDs included in the synthesis. A node is stale iff `current_hash ≠ stored_embedding_hash`.

**Edge-change propagation.** When ingestion modifies an edge (new edge, updated edge property), both endpoints are marked dirty (set `embedding_hash = NULL`) so the next embedding pass re-renders their texts. Dirty marking lives in `scripts/edge_vocabulary.py` (or a hook layer next to it).

**Relation-aware outbound filtering.** Synthesis text MUST exclude any neighbor whose type is in `INELIGIBLE_TYPES` (§9.2) — even if the anchor entity itself is eligible. The synthesis builder iterates neighbors, calls `is_eligible(neighbor.type)`, and skips ineligibles. This is the graph-level enforcement of the outbound policy: an eligible Person's embedding text never includes a CriminalRecord neighbor's label, even though both are connected in the graph.

Batch through OpenAI `text-embedding-3-small` (1536 dim, $0.02/1M tokens). Batch size 100. Write `embedding`, `embedding_hash`, `embedding_version`, `embedded_at` back to the node.

**Cost ceiling**: ~$1.14 for first full embed of 114K entities @ 500 tokens; ~$5/month for refresh + new entities, dirty-cascades included.

### 9.2 Outbound data eligibility & redaction

**Critical for forward compatibility with future sensitive-data lanes** (Codex round 1 #14).

A per-type and per-source policy controls what crosses the OpenAI / Anthropic boundary:

```python
# scripts/outbound_policy.py
ELIGIBLE_TYPES = {  # types whose synthesized text MAY be sent to vendors
    "Person", "Organization", "Committee", "Seat", "SeatService",
    "Election", "Candidacy", "Meeting", "AgendaItem", "Decision",
    "Filing", "MoneyFlow", "Case", "Proceeding", "Project", "Program",
    "Agreement", "Amendment", "Record", "Place", "Issue",
}

INELIGIBLE_TYPES = set()  # placeholder for future sensitive lanes (e.g., "CriminalRecord")

REDACT_FIELDS = {  # fields stripped from synthesis text before outbound
    "Person": ["home_address", "phone", "email", "dob"],
    # ...
}

def is_eligible(node_type: str) -> bool:
    return node_type in ELIGIBLE_TYPES and node_type not in INELIGIBLE_TYPES

def synthesize_outbound_text(node, neighbors) -> str:
    # 1. If is_eligible(node.type) is False, refuse — caller should not even ask.
    # 2. Apply REDACT_FIELDS to anchor node properties.
    # 3. For each neighbor: if not is_eligible(neighbor.type), DROP the neighbor
    #    entirely from the synthesis (don't include label, don't include type).
    # 4. Render the remaining synthesis text.
    ...
```

Default-deny: a new node type is ineligible until explicitly added to `ELIGIBLE_TYPES`. When a future criminal-record lane lands (per the project roadmap's private-data section), it defaults to `INELIGIBLE_TYPES` and never reaches embedding/clustering. Workspaces containing ineligible entities render the entity cards locally; no embeddings → no spatial position → ineligible entities are excluded from the Constellation visual.

**Relation-level enforcement** (graph-aware, not just node-aware): `synthesize_outbound_text` filters neighbors by eligibility. An eligible Person connected to an ineligible CriminalRecord neighbor will not have that neighbor mentioned in the synthesis sent outbound. This is what makes the policy actually safe at the graph level, not just the node level.

**Audit logging.** Every outbound call writes a record to a local `outbound_audit.jsonl` log: `{ timestamp, vendor, node_id, node_type, neighbor_ids_included, neighbor_ids_dropped, prompt_hash }`. Reviewable when expanding eligibility or investigating a leak.

All outbound calls go through `outbound_policy.py`. Direct OpenAI / Anthropic calls from elsewhere in the codebase are forbidden by lint rule.

### 9.3 UMAP projection pipeline

**Script**: `scripts/build_umap.py`.

- **Weekly full fit** (Sunday): `UMAP.fit_transform(all_embeddings)` → 114K × 2 array. Persist the fitted model (`umap.pkl`) for incremental transforms.
- **Nightly incremental transform**: `umap.transform(new_or_dirty_embeddings)` using the cached fit. Cheap (~10s for typical nightly delta).
- Write `umap_x`, `umap_y`, `umap_version` to each node.

Weekly fit benchmark (Plan v2.0): on Mac mini M-series, 114K × 1536 cosine UMAP fit ~3-8 minutes. Acceptable. If runtime exceeds 15 minutes, we add a PCA-to-50d step before UMAP.

**Stability guarantee**: with `random_state=42` + `init="spectral"`, weekly fits produce projections that differ <5% per node from prior week (measured by mean Euclidean distance after Procrustes alignment). Acceptable drift.

### 9.4 Clustering pipeline

**Script**: `scripts/build_clusters.py`. Nightly batch.

1. Pull all `(umap_x, umap_y)` from Neo4j.
2. Run HDBSCAN on the 2D coords (much faster than on 1536-d): `min_cluster_size=15, min_samples=5, metric="euclidean"`.
3. Compute centroid per cluster, distance per node.
4. Output: temporary cluster_id per node (these IDs are not yet stable across runs — see §9.5).

Library: `hdbscan` Python package. Nightly job duration: <1 minute on 2D data (far cheaper than running HDBSCAN on 1536-d).

### 9.5 Cluster matching across runs

**Script**: `scripts/match_clusters.py`. Runs after clustering.

HDBSCAN cluster IDs are not stable across runs (cluster 7 today might be cluster 12 tomorrow). To keep `cluster_id` stable so labels persist:

1. Load yesterday's `(node_id → cluster_id)` mapping.
2. Build a confusion matrix: `M[i][j] = |yesterday_cluster_i ∩ today_cluster_j|`.
3. Run Hungarian algorithm on `-M` to find optimal cluster matching.
4. For matched pairs (Jaccard ≥ 0.5): keep yesterday's cluster_id.
5. For new clusters (no good match): assign new ID.
6. For dropped clusters: ID retired (no rename needed).
7. For split clusters (one yesterday → multiple today): largest descendant inherits ID; siblings get new IDs (and need new names).
8. For merged clusters (multiple yesterday → one today): largest ancestor's ID wins; merged label is regenerated.

Persist the new mapping with stable cluster_ids. This makes `cluster_label` stable too — labels stick to the cluster, not to the ephemeral run ID.

### 9.6 Cluster-naming pipeline

**Script**: `scripts/name_clusters.py`. Runs after matching, only re-names clusters flagged by §9.5 as new, split, or merged.

**Two-stage name generation:**

1. **Deterministic candidate name**: from cluster contents, generate a baseline name without LLM:
   - Most-common jurisdiction + most-common type + top-3 issue tags or label tokens (TF-IDF over cluster member labels).
   - Examples: "Marin County · Decision · housing" or "San Rafael · MoneyFlow · downtown"
   - This is the fallback if LLM is unavailable or rejected.

2. **LLM improvement** (Claude Haiku 4.5): given the deterministic candidate + 5-10 sample members, return a 3-5 word polished name. Constraints in prompt:
   - Must be factual (no "controversial", "scandalous", "influence", "alleged")
   - Must reference what's *documented* in cluster members
   - Must be 3-5 words
   - If unable to improve, return candidate unchanged.

   Prompt:
   ```
   You're naming a cluster of civic-data entities.
   Deterministic candidate: "{candidate}"
   Sample members:
   - {label_1} ({type_1}) · {key_fact_1}
   - {label_2} ({type_2}) · {key_fact_2}
   ...
   Return a 3-5 word name that describes what's documented in these entities.
   Be factual. Avoid "influence", "controversial", "alleged".
   If you can't improve on the candidate, return it unchanged.
   ```

3. **Validation**: reject LLM output if:
   - Contains banned terms ("influence", "controversial", "scandal", "alleged", "corrupt")
   - >7 words or <2 words
   - Doesn't reference any token from the cluster members' labels

   On rejection, fall back to deterministic candidate.

4. **Override registry**: `scripts/cluster_name_overrides.json` is a manual override file. If a cluster_id has a human-set name, that wins over deterministic+LLM. Stuart can pin specific cluster names that the LLM keeps getting wrong.

**Cost**: ~$0.04 per full naming pass; ~$1/month with daily-refresh-of-shifted-clusters.

### 9.7 Constellation payload publish

**Script**: `scripts/publish_constellation.py`. Runs at end of nightly pipeline.

Bakes a single JSON payload to `app/public/constellation.json`:

```json
{
  "version": "2026-04-26-nightly-001",
  "built_at": "2026-04-26T08:00:00Z",
  "node_count": 114493,
  "edge_count": 147862,
  "cluster_count": 87,
  "nodes": [
    {
      "id": "person-kate-colin",
      "type": "Person",
      "label": "Kate Colin",
      "key_fact": "San Rafael City Council",
      "x": 0.234,
      "y": -0.512,
      "cluster_id": 7,
      "embedding_hash": "a4f2..."
    },
    ...
  ],
  "edges": [
    { "s": "person-kate-colin", "t": "decision-12345", "type": "VOTED_ON", "weight": 1 },
    ...
  ],
  "clusters": [
    { "id": 7, "label": "San Rafael Decisions", "centroid": [0.21, -0.49], "member_count": 1247 },
    ...
  ]
}
```

Estimated payload size: 114K nodes × ~150 bytes + 148K edges × ~80 bytes ≈ **30MB raw, ~6MB gzipped**. Acceptable for a one-time-per-session download.

**Publish boundary — versioned object storage.** Vercel's `app/public/` is a build-time artifact, so we cannot rewrite it from a nightly cron. The pipeline publishes to **versioned object storage** instead:

- **Primary**: Vercel Blob (zero-config on our hosting platform). Each pipeline run uploads `constellation-{version}.json.gz` (immutable, versioned URL). Cost: ~$0.15/month for our payload size.
- **Alternative if cost or vendor lock-in concerns arise later**: Cloudflare R2 (~$0.015/GB/month, S3-compatible API).

Manifest endpoint:

- `GET /api/constellation-manifest` returns `{ "current_version": "2026-04-26-nightly-001", "url": "https://blob.vercel-storage.com/constellation-2026-04-26-nightly-001.json.gz", "built_at": "...", "size_gz": 6234567 }`.
- The manifest itself is served by a Next.js API route reading from Neo4j's `:_SyncState{kind:"constellation"}` node (single row, updated by `publish_constellation.py` at end of pipeline). Cache: `Cache-Control: public, max-age=60, stale-while-revalidate=3600`.

Client flow on `/`:

1. Fetch `/api/constellation-manifest` (~1KB, ~50ms).
2. Fetch the versioned blob URL (~6MB gzipped, ~1-2s cold cached at Vercel edge).
3. Parse, feed to Cosmograph.

Versioned URLs mean we get cache-busting for free (no `?v=` hacks) and can roll back instantly by updating the manifest's `current_version` to point at the prior blob. The pipeline retains the previous N versions (default: 7 days of nightly + 4 weekly fits) for rollback; older versions garbage-collected.

**Rollback flow.** If a published payload is bad (drift budget breached, schema regression, naming hallucination caught post-hoc), Stuart runs `scripts/rollback_constellation.py {version}` which updates the manifest to point at a known-good prior version. Site recovers in <60s as the manifest cache TTL expires.

**Failure modes:**
- Manifest missing / unreachable → `/` renders "Constellation is rebuilding..." with status poll every 30s.
- Blob URL 404 or hash mismatch → manifest is stale; same recovery flow.
- Pipeline drift budget breach → `publish_constellation.py` does not advance the manifest version; clients keep loading the prior payload until manual review clears the breach.

### 9.8 Centrality pipeline (deferred to Plan v2.7)

`scripts/build_centrality.py`. Weekly batch. Uses NetworkX or Neo4j Graph Data Science (free Community edition). Computes PageRank and betweenness centrality. Writes `centrality_pagerank` to nodes. Used by Influence lens.

### 9.9 Pipeline integration

`scripts/refresh_openmarin.py` gets new steps in this order:

```
... existing steps (search index, catalog, signature subgraphs) ...
build_embeddings.py        # incremental, ~30s typical, ~5min full
build_umap.py              # incremental nightly ~10s, weekly full ~5min
build_clusters.py          # ~1 min on 2D coords
match_clusters.py          # <30s
name_clusters.py           # delta only, ~30s
publish_constellation.py   # ~30s, writes 30MB JSON
update_sync_state.py       # bumps :_SyncState
copy-subgraphs.mjs         # existing
```

Total nightly added time: ~3-5 min. Weekly (UMAP full fit): ~10 min added.

---

## 10. Frontend tech stack

### 10.1 Stack

- Next.js 16 (App Router) — kept
- React 19, TypeScript 5, Tailwind 4 — kept
- IBM Plex (Sans/Mono/Serif) + VT323 — kept
- **New**: `@cosmograph/cosmos` (graph renderer, MIT)
- **New**: `@visx/sankey` (adjacency-flow primitive)
- **New**: `maplibre-gl` (map primitive)
- **New**: `zustand` (workspace state store)
- **Removed**: `cytoscape`, `cytoscape-fcose`, all explorer-coupled plugins

### 10.2 Routes

| Route | Purpose | Server/Client |
|---|---|---|
| `/` | Constellation (full-bleed) | Client (Cosmograph mount); fetches `/constellation.json` |
| `/w/entity/{type}/{slug}` | Entity workspace | Server-rendered shell, client-rendered primitives |
| `/w/q/{hash}` | Question workspace | Server-rendered shell, client-rendered primitives |
| `/{type}/{slug}` | Standalone entity dossier (kept for sharing) | Server |
| `/about` | Methodology page | Server (kept) |
| `/api/*` | Existing + new endpoints | Server |

### 10.3 New API endpoints

- `GET /api/cluster/{id}` — returns cluster membership + label + centroid for hover detail.
- `POST /api/embed` — embeds a single ad-hoc text query (for question-bar similarity search). Subject to outbound policy (§9.2).
- `GET /api/constellation-manifest` — returns the current payload version + blob URL + size + built_at (§9.7).

DB-backed workspace save/load endpoints are deferred to a later plan. v2.2 workspaces live in URLs only.

---

## 11. Phasing — implementation plans

Each plan is independently coherent and Stuart-review-gated.

### Plan v2.0 — Full-scale rehearsal + payload contract (1-2 weeks)

**Goal**: prove the foundational assumptions at production scale before locking v2.1.

Mandatory: **one full end-to-end production-size rehearsal** of the entire pipeline:

1. Embed all 114K production entities with the synthesizer + outbound policy enforcement.
2. UMAP full fit on 114K × 1536, with Procrustes alignment to a fixture "prior frame" so the alignment code is exercised.
3. HDBSCAN on the 2D UMAP output.
4. Hungarian cluster matching against a fixture prior run.
5. Cluster naming with the deterministic candidate + Haiku improvement + validation pass.
6. Publish payload to Vercel Blob (or local fixture blob if blob isn't yet set up).
7. Manifest endpoint serves the version.
8. Static-data prototype of `/` loads the manifest, fetches the blob, parses, and renders all 114K nodes via Cosmograph.
9. Measure: parse time, first-paint, FPS at full zoom-out (Tier A), zoom-in to Tier C, sprite generation throughput, memory.

Pass criteria (any failure → amend spec, do not start v2.1):
- UMAP full fit completes in <12 min on the Mac mini.
- HDBSCAN on 2D coords completes in <2 min.
- Procrustes alignment + drift budget logic produces sensible per-node + per-cluster movement numbers (calibrate budget thresholds against the rehearsal numbers).
- Payload size ≤8MB gzipped (1.3× our 6MB estimate gives headroom).
- Client first-paint of full Constellation ≤4s on Wi-Fi.
- 60fps sustained at Tier A on baseline (M1 MBP / equivalent).
- Tier C sprite throughput ≥150/sec (target was 200; allow 25% miss).
- Outbound audit log shows zero ineligible-neighbor leaks across the rehearsal.

Other v2.0 deliverables:
- `outbound_policy.py` complete with unit tests, default-deny, neighbor filtering, redaction, audit logging, lint rule.
- Payload schema versioned (`schema_version` field) — v2.1 must reject incompatible payloads gracefully.
- Documented benchmark numbers in `docs/benchmarks/2026-04-XX-v2-rehearsal.md` for v2.1 to plan against.

If any benchmark blows up, the spec is amended before v2.1 starts. v2.0 is the gate; passing it is the precondition for v2.1.

### Plan v2.1 — Constellation MVP (4-6 weeks)

**Honest scope**: renderer + payload publish via versioned object storage + 5 pipelines + UMAP alignment + region rendering + ambient motion + cutover of homepage and `/graph`.

- Cosmograph integration with custom React glue (~200 lines).
- Tier-A and Tier-B sprite atlases (build-time).
- Tier-C on-demand sprite generation in Web Worker.
- Region label DOM overlay.
- All 6 new pipeline scripts (embeddings, UMAP w/ Procrustes alignment, clusters, matching, naming, payload publish-to-blob).
- Manifest API endpoint + rollback script.
- Outbound policy + audit logging + lint rule against direct vendor calls.
- Override registry for cluster names.
- `/graph` route deleted along with `app/src/components/explorer/*`.
- The current homepage's `signature-subgraph.tsx` (Cytoscape consumer) is replaced by the Constellation; the file deleted.

**Cytoscape stays installed.** `RadialHero` on standalone entity pages (`/{type}/{slug}`) is still a Cytoscape consumer. Removing the dep would break those routes. Plan v2.2 replaces RadialHero with the egocentric-graph primitive (Cosmograph) when entity-page becomes the dossier primitive. Cytoscape removal from `package.json` happens in v2.2, NOT v2.1.

`/search` and `/data` remain operational.

Backfill: first full pipeline run on production data takes ~13-15 min; happens once at v2.1 cutover.

**Why 4-6 weeks, not 3-4**: Codex flagged correctly. v2.1 bundles renderer + payload pipeline + worker sprite generation + DOM overlay + 6 pipeline scripts + UMAP-alignment + drift-budget enforcement + ~180 new tests. Realistic.

### Plan v2.2 — Workspace shell + dossier + egocentric graph + state schema (2-3 weeks)

- Workspace shell (CSS grid + URL state sync via Zustand).
- Workspace state schema implemented (§5.4) — URL-only, no DB-backed saves yet.
- Dossier primitive (refactor of v1 entity page).
- Egocentric graph primitive (small Cosmograph mount with force enabled) — replaces RadialHero.
- Click-from-Constellation routes to entity workspace; **camera state (target node, zoom level) persisted in URL** so workspaces are reloadable / shareable without snapshot dependency.
- Static Constellation snapshot is optional polish for the back-link affordance — fallback is a "Back to Constellation" button that uses URL camera state to restore view.
- **Cytoscape dependency removed from `package.json`** (RadialHero now superseded by egocentric graph; `signature-subgraph.tsx` deleted in v2.1; no other consumers remain).

**DB-backed saved workspaces are deferred to a later plan.** v2.2 ships URL-only workspace state. A future Plan (v2.8 or later) adds save-workspace persistence + a `/w/saved/{id}` route + precedence rules. The save button is hidden in v2.2.

### Plan v2.3 — Question bar v1 + delete /search (3-5 days)

- Question bar overlay on Constellation + workspaces.
- Keyword routing via existing `/api/search`.
- Delete `/search` route once new bar is proven on production data.
- LLM routing deferred to v2.7.

### Plan v2.4 — Adjacency-flow primitive (1-1.5 weeks)

- `@visx/sankey` integration.
- Three adjacency-flow shapes (Person / Decision / MoneyFlow centric).
- Eligibility rule: bands only render with primary-source citations on every endpoint.
- Wired into Person, Organization, Committee, Decision, MoneyFlow workspaces.

### Plan v2.5 — Timeline primitive (3-5 days)

- D3-based timeline ribbon, scrub-to-filter via shared workspace state.
- Wired into Meeting, Filing, Case, Proceeding, Project, Issue workspaces.

### Plan v2.6 — Map primitive + retire /data (1-1.5 weeks)

- MapLibre integration, jurisdiction GeoJSON bundle.
- Project markers, Place boundaries, Meeting cluster markers.
- Wired into Project, Place, Meeting workspaces.
- `/data` route retired now that all predefined queries have workspace replacements.

### Plan v2.7 — Table primitive + LLM question routing + Constellation lenses (2-3 weeks, optional)

- Table primitive.
- LLM-mediated question routing via Claude Haiku.
- Constellation Phase 2 lenses: money / recency / influence / issue (requires centrality pipeline).

Stop or continue based on use after v2.6.

---

## 12. Migration / cutover

### 12.1 What lands in v2.1's first commit

- Delete `/graph` and `app/src/components/explorer/*`.
- Remove Cytoscape dependencies from `package.json`.
- Add Cosmograph mount as new `/` page (initially with placeholder data until pipeline backfills).
- Add new pipeline scripts (no-op until embeddings populate).
- `/search` and `/data` remain.

Plan 4b (auth + Vercel deploy) is unchanged — still deferred until Constellation MVP ships.

### 12.2 What lands in v2.3 and v2.6

- v2.3: delete `/search` after question bar proves stable for ~1 week.
- v2.6: delete `/data` after all predefined queries have workspace replacements.

### 12.3 Tests

The ~125 v1 tests coupled to Cytoscape canvas / explorer state are deleted across v2.1 (Cytoscape) and v2.3 / v2.6 (search / data). The ~280 tests for data layer / search backend / entity loaders / edge vocabulary stay green throughout.

New v2 tests:

- `outbound_policy.py` unit tests (default-deny, redaction).
- Embedding text synthesizer (unit, ~10 cases per entity type).
- Synthesis hash determinism (unit).
- Edge-change dirty propagation (integration).
- UMAP transform stability against fixture data.
- HDBSCAN cluster assignment (integration with fixed embedding fixtures).
- Cluster matching across runs (Hungarian algorithm correctness).
- Deterministic cluster name generator (unit).
- LLM-name validation (unit, banned-term filter, length constraints).
- Override registry precedence (unit).
- Constellation payload schema (integration).
- Cards-as-nodes Tier-A/B atlas builder (unit).
- Tier-C on-demand sprite generator (unit, perf budget assertion).
- Workspace store URL ↔ state sync (unit).
- Each primitive's render contract (component test with mocked entity data).

Total expected v2 test count: ~280 v1 survivors + ~180 new = ~460.

### 12.4 Data backfill

Plan v2.1's deploy unblocks the embedding/UMAP/clustering/naming/payload pipelines. First full pipeline run: ~5min embeddings + ~5min UMAP fit + ~1min clusters + ~1min matching + ~1min naming + ~30s publish = ~13 min. Backfill once at v2.1 cutover, then nightly.

Until backfill completes, `/` renders a "Building constellation..." progress page that polls `/api/status`.

---

## 13. Out of scope

- **Multi-tenant or non-Marin data.** v2 stays Marin-only.
- **Mobile responsiveness for Constellation.** Cosmograph + WebGL on mobile is unreliable; mobile users hit a "view on desktop" page for `/`. Workspaces (`/w/...`) responsively work on mobile.
- **Real-time collaboration on workspaces.** Save-workspace is single-user.
- **Export to PDF / report builder.** Eventually valuable, deferred.
- **AI-summary panels in dossiers.** Tempting but distinct from workspace composition; deferred.
- **Public unlocked surface.** v2 stays invite-only behind Plan 4b auth.

---

## 14. Open questions

1. **UMAP fit duration on production hardware**: spec assumes <8 min; benchmark in Plan v2.0 confirms.
2. **HDBSCAN min_cluster_size tuning**: 15 is a starting point; tune in Plan v2.1 against actual data to land in the 80-150 cluster sweet spot.
3. **Constellation payload size on production data**: 30MB raw / 6MB gzipped is an estimate; confirm in Plan v2.0.
4. **Tier-C sprite generation throughput on baseline hardware**: 200 sprites/second is a target; benchmark in Plan v2.0.
5. **Auth + deploy timing**: Plan 4b ships *after* Plan v2.1. Constellation MVP must be live before authenticated demos start.
6. **Outbound policy review**: who else (besides Stuart) should approve the eligibility list before Plan v2.0 closes? Right now: Stuart-only.

---

## 15. Success criteria

### After Plan v2.0 (benchmarks)

- All assumed runtimes / sizes confirmed within budget.
- Static-data prototype of `/` renders 50K nodes at 60fps.
- Outbound policy tests pass; default-deny enforced.

### After Plan v2.1 (Constellation MVP)

- Stuart loads `openmarin.app/` and the Constellation conveys the territory.
- Region labels are coherent (no banned-term hallucinations slip past the validator).
- Pipeline runs nightly without manual intervention; cluster IDs are stable across runs.
- Cost: < $10/month total OpenAI + Anthropic.

(The v2.1 success bar does NOT include click-into-workspace — that's Plan v2.2.)

### After Plan v2.2 (workspaces + dossier + egocentric graph)

- A test user can click any Constellation node, land in a workspace, read the dossier and see the egocentric graph, and click through to a related entity.
- Workspace URL is shareable and reloadable.

### After Plan v2.4 (adjacency-flow ships)

- Stuart can demo "MoneyFlow → BoS member → Decision" adjacency from a Person workspace, with citations on every band.

### After Plan v2.6 (full primitive set)

- Most civic-investigation questions Stuart asks have a workspace shape that answers them without code.

If any of these don't land, we re-spec rather than push more polish at the wrong shape.

---

*End of spec.*
