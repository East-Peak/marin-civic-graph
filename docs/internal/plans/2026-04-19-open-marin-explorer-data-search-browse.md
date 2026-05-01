# Open Marin Frontend — Plan 3: Explorer + Data + Search + Browse

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Plan 1 stub pages with real surfaces. The full-screen explorer (`/graph`) becomes a real investigation workbench with fcose layout, click-to-expand, right-click N-hop expand-all, weighted shortest-path finding, time slider, and save-view. The data explorer (`/data`) runs the 10 predefined queries from spec §8 against AuraDB with filters + CSV export. The search results page (`/search?q=`) consumes the `/api/search` bucketed backend from Plan 1 with the section-divided layout. The browse pages (`/browse/{type}`) are paginated list views per node type.

**Architecture:**
- Explorer state lives in URL query params (focus, hop, filters, time slider) plus sessionStorage (loaded nodes + saved views), so refreshing the page stays on the same investigation.
- Cytoscape extension `cytoscape-fcose` (installed in Plan 1) drives the force-directed layout. Pathfinding uses Neo4j APOC's `apoc.algo.dijkstra` via a new `/api/path` endpoint.
- Data explorer calls a new `/api/data/{query}` endpoint; each predefined query is a separate server-side Cypher template with typed filters.
- Search results page and browse pages are both live-Cypher (no baking); search uses the existing `/api/search`, browse uses a new `/api/browse/{type}` endpoint.

**Tech stack:** same as Plans 1-2. New for Plan 3: no new npm packages (Cytoscape + fcose already installed); `apoc.algo.dijkstra` already available on AuraDB Pro (confirmed during Plan 1 schema apply).

**Spec:** `docs/specs/2026-04-19-open-marin-frontend-design.md`. This plan implements §5.4 time slider (explorer), §5.6 pathfinding contract, §6.3 explorer initial-load + expand contract, §8 data explorer, §4.5 search results page, §4.1 browse routes.

**Prerequisites:** Plan 2 (entity pages) landed on `main` at `d8a6518`. Edge vocabulary module, `/api/search` backend, and entity-loader all exist and are tested.

---

## File structure (new or modified)

```
app/src/
  lib/
    server/
      explorer-queries.ts                    NEW — expand + expand-all Cypher builders
      path-finder.ts                         NEW — weighted shortest path per §5.6
      data-queries.ts                        NEW — the 10 predefined query templates
      browse-queries.ts                      NEW — per-type paginated list query
  app/
    graph/page.tsx                           MODIFY — replace stub; full-screen explorer
    graph/explorer-client.tsx                NEW — client component (Cytoscape + toolbar + state)
    data/page.tsx                            MODIFY — replace stub; data explorer shell
    data/[query]/page.tsx                    NEW — per-query view with filters + results
    search/page.tsx                          MODIFY — replace stub; real results page
    browse/[type]/page.tsx                   MODIFY — replace stub; paginated list
    api/
      path/route.ts                          NEW — GET /api/path?from=&to=&loose=
      data/[query]/route.ts                  NEW — GET /api/data/{query}?filters
      browse/[type]/route.ts                 NEW — GET /api/browse/{type}?cursor=&q=
      expand/route.ts                        NEW — GET /api/expand?focus=&hop=&filters
  components/
    explorer/
      explorer-toolbar.tsx                   NEW — hop slider, edge/node filters, time slider
      path-dialog.tsx                        NEW — pathfinding source + target picker
      save-view-menu.tsx                     NEW — localStorage save/load
      overflow-indicator.tsx                 NEW — "+N more" affordance
    data/
      data-query-nav.tsx                     NEW — left rail with 10 query templates
      data-filters.tsx                       NEW — horizontal chip filters
      data-table.tsx                         NEW — Plex Mono sortable table + CSV
    search/
      search-results.tsx                     NEW — bucketed results renderer
    browse/
      browse-table.tsx                       NEW — per-type paginated table
  lib/
    explorer/
      explorer-state.ts                      NEW — URL + sessionStorage state management
      expand-quotas.ts                       NEW — hop-scaled per-type quotas per §6.3
  tests/
    lib/server/
      explorer-queries.test.ts               NEW
      path-finder.test.ts                    NEW
      data-queries.test.ts                   NEW
      browse-queries.test.ts                 NEW
    components/
      explorer/explorer-toolbar.test.tsx     NEW
      explorer/path-dialog.test.tsx          NEW
      data/data-filters.test.tsx             NEW
      data/data-table.test.tsx               NEW
      search/search-results.test.tsx         NEW
      browse/browse-table.test.tsx           NEW
    api/path.test.ts                         NEW
    api/expand.test.ts                       NEW
```

---

## Conventions (same as Plans 1-2)

- Push directly to `main`. Ambient dirty state in `data/extracted/*`, `data/raw/*`, `data/normalized/*`, `data/projected/graph-v2/*`, and `docs/specs/2026-04-14-marin-civic-graph-v1-design.md` — do not touch.
- Never `git add -A`.
- TDD for logic (queries, state management, filters); pragmatic for UI scaffolding.
- `npm run verify` green before each commit.
- Commit message format matches Plan 2: imperative, concise, reference spec section or Codex item when applicable.
- Subagent-driven; one subagent per phase.

---

## Phase A — Explorer data loaders (5 tasks)

### Task 1: `explorer-queries.ts` — expand + expand-all Cypher

Builds Cypher for click-expand (1 hop, 20-node cap, halved quotas) and right-click-expand-all (N hops, scaled cap, full quotas per §6.3).

**Files:**
- Create: `app/src/lib/server/explorer-queries.ts`
- Create: `app/src/lib/explorer/expand-quotas.ts` — per-type quota tables for hop=1/2/3/4
- Create: `app/src/tests/lib/server/explorer-queries.test.ts`

Quota table from spec §6.3 Expand contract:

| Type | Expand (1-hop) | Expand-all 2-hop | 3-hop (2×) | 4-hop (3×) |
|---|---|---|---|---|
| MoneyFlow | 4 | 8 | 16 | 24 |
| Decision | 4 | 8 | 16 | 24 |
| Case | 2 | 4 | 8 | 12 |
| Project | 2 | 4 | 8 | 12 |
| Program | 2 | 4 | 8 | 12 |
| Agreement | 2 | 4 | 8 | 12 |
| Amendment | 1 | 2 | 4 | 6 |
| Filing | 3 | 6 | 12 | 18 |
| Committee | 2 | 4 | 8 | 12 |
| Election | 1 | 2 | 4 | 6 |
| Candidacy | 1 | 2 | 4 | 6 |
| Meeting | 3 | 6 | 12 | 18 |
| Proceeding | 2 | 4 | 8 | 12 |
| Person | 3 | 6 | 12 | 18 |
| Organization | 2 | 4 | 8 | 12 |
| Seat | 2 | 4 | 8 | 12 |
| SeatService | 2 | 4 | 8 | 12 |
| AgendaItem | 2 | 4 | 8 | 12 |
| Record | 2 | 4 | 8 | 12 |
| Place | 1 | 2 | 4 | 6 |
| Issue | 1 | 2 | 4 | 6 |

Aggregate caps: 20 / 80 / 160 / 240 for N=1/2/3/4.

**Key signature:**
```typescript
export function buildExpandQuery(params: {
  focusId: string;
  hopLimit: 1 | 2 | 3 | 4;
  excludedNodeTypes: NodeType[];  // from filter toggles
  excludedEdgeTypes: string[];    // from filter toggles
  alreadyLoadedIds: string[];     // dedup
}): { cypher: string; params: Record<string, unknown>; cap: number };
```

The query:
1. Traverses 1-to-N hops along the Phase-2 whitelist minus excluded edges, from `$focusId`.
2. Filters candidates: `NOT c.id IN $alreadyLoadedIds` AND `NOT labels(c) IN $excludedNodeTypes`.
3. Sorts by `(hop_distance ASC, type-priority ASC, type-specific ranking key, id ASC)` — per spec §6.3 "closer candidates preferred within each type's quota."
4. Applies per-type LIMITs from the quota table (as UNION ALL sub-queries, like Query 2 in Plan 2).
5. Aggregate LIMIT = cap for N.

Tests assert the quota table values and sort-key structure.

Commit: `add explorer-queries: expand + expand-all Cypher (§6.3)`.

### Task 2: `path-finder.ts` — weighted shortest path

Per spec §5.6 contract.

**Files:**
- Create: `app/src/lib/server/path-finder.ts`
- Create: `app/src/tests/lib/server/path-finder.test.ts`

Edge weight table (from spec §5.6):

| Weight | Relationships (use live names via edge-vocabulary) |
|---|---|
| 1 | CAST_VOTE, DECIDED_BY, PARTY_TO (+ CONSTRAINS when live) |
| 2 | FROM_SOURCE, TO_TARGET, DISCLOSED_IN_FILING, RELATES_TO_AGREEMENT (UNDER_AGREEMENT live), AMENDS_AGREEMENT |
| 3 | HELD_BY, FOR_SEAT, RESULT_OF_ELECTION, CONTROLLED_BY, CANDIDATE_ACTOR (BY_PERSON live), FILED_FOR_ELECTION (IN_ELECTION live), FOR_ELECTION, RELATES_TO_PROJECT (FOR_PROJECT live) |
| 4 | RELATES_TO_PROJECT (ABOUT_PROJECT live), RELATES_TO_PROGRAM (ABOUT_PROGRAM live), ABOUT_AGENDA_ITEM (ABOUT_ITEM live), COUNTERPARTY_ACTOR (BETWEEN live), HEARD_IN, AT_INSTITUTION |
| 5 | AT_MEETING, FILED_BY, PART_OF_MEETING, PART_OF_CASE (PART_OF live) |

Excluded from default: EVIDENCED_BY, IN_JURISDICTION, RELATES_TO_ISSUE (universals). Excluded node types (intermediates): Record, Issue, Place, AgendaItem (per spec §5.6). Loosen toggle re-admits these at weight 10.

Use `apoc.algo.dijkstra` with a relationship-type + weight map. The Cypher:

```cypher
MATCH (from {id: $fromId}), (to {id: $toId})
CALL apoc.algo.dijkstra(from, to, $relTypes, "cost", $maxHops)
YIELD path, weight
RETURN
  [n IN nodes(path) | {id: n.id, type: labels(n)[0], label: coalesce(n.search_label, n.id)}] AS path_nodes,
  [r IN relationships(path) | {source: startNode(r).id, target: endNode(r).id, type: type(r)}] AS path_edges,
  weight
LIMIT 1
```

Signature:
```typescript
export async function findPath(
  fromId: string,
  toId: string,
  options: { loose?: boolean; maxHops?: number },
): Promise<{
  found: boolean;
  loose_match: boolean;
  path?: { nodes: PathNode[]; edges: PathEdge[]; weight: number };
}>;
```

Return `{ found: false }` on no-path. Return `loose_match: true` if the loose toggle was used.

Tests:
- Weight table exposed and verifiable
- No-path returns `found: false`
- Loose toggle admits Record as intermediate (mock-verified)

Commit: `add path-finder: weighted shortest path per §5.6`.

### Task 3: `/api/path/route.ts`

**Files:**
- Create: `app/src/app/api/path/route.ts`
- Create: `app/src/tests/api/path.test.ts`

Thin wrapper. GET `/api/path?from=...&to=...&loose=true|false`. Validates inputs (both ids required, loose is optional boolean). Returns `{ found, loose_match, path? }`.

Commit: `add /api/path endpoint for explorer pathfinding`.

### Task 4: `/api/expand/route.ts`

**Files:**
- Create: `app/src/app/api/expand/route.ts`
- Create: `app/src/tests/api/expand.test.ts`

GET `/api/expand?focus={id}&hop=1|2|3|4&excluded_node_types=A,B&excluded_edge_types=X,Y&already_loaded={id1,id2,...}`.

Response: `{ nodes: Neighbor[], edges: EntityEdge[], new_count: N }`.

Uses `buildExpandQuery()` from Task 1.

Commit: `add /api/expand endpoint — click-expand + expand-all Cypher`.

### Task 5: `explorer-state.ts` — URL + sessionStorage state

**Files:**
- Create: `app/src/lib/explorer/explorer-state.ts`
- Create: `app/src/tests/lib/explorer/explorer-state.test.ts`

Pure TypeScript state module for the explorer. Tracks:
- URL params: `focus`, `hop` (1–4 slider), `filters.nodes` (comma list of enabled node types), `filters.edges` (comma list of enabled edge classes: governance | money | legal-constrains | universal), `time.from`, `time.to`
- sessionStorage: loaded node IDs, loaded edge IDs (for dedup and refresh continuity), saved views (named snapshots)

Key functions:

```typescript
export type ExplorerState = {
  focus: string | null;
  hop: 1 | 2 | 3 | 4;
  nodeFilters: Record<NodeType, boolean>;
  edgeFilters: { governance: boolean; money: boolean; legalConstrains: boolean; universal: boolean };
  timeFrom: string; // ISO date
  timeTo: string;   // ISO date
  loadedNodeIds: Set<string>;
  loadedEdgeKeys: Set<string>;
};

export function parseUrlToState(params: URLSearchParams, ingestAt: string): ExplorerState;
export function stateToUrl(state: ExplorerState): URLSearchParams;
export function mergeExpansion(state: ExplorerState, nodes: Neighbor[], edges: Edge[]): ExplorerState;

export function defaultTimeRange(ingestAt: string): { from: string; to: string };
// spec §5.4: widen to cover both last-5-years AND earliest event in loaded subgraph

export function autoEnableFiltersForFocus(state: ExplorerState, focusType: NodeType): ExplorerState;
// spec §6.3: if focus is Record, auto-enable Record filter + EVIDENCED_BY edge class
```

Tests exercise each function with representative URLs and focus types.

Commit: `add explorer-state: URL + sessionStorage state management`.

---

## Phase B — Explorer UI (8 tasks)

### Task 6: `explorer-client.tsx` — core client component

**Files:**
- Create: `app/src/app/graph/explorer-client.tsx`

Client component (`"use client"`). Full-page Cytoscape canvas with fcose layout. Consumes initial state from URL + props from the server component. Mounts CytoscapeBase; hooks up click, right-click, hover handlers.

State lives in React (mirrors ExplorerState); sessionStorage sync runs on mount + every state change.

Key handlers:
- **Click on node** (not focus): call `/api/expand?focus={clickedId}&hop=1&...` → merge response into state → re-render.
- **Right-click on node**: open context menu → "expand all (N hops)" item → call `/api/expand?focus={id}&hop={sliderValue}&...`.
- **Double-click on focus**: no-op (explicit).
- **Hover node**: reveal label if ring > 1.
- **Shift+click on node**: add to pathfinding selection (max 2).

### Task 7: `graph/page.tsx` — server wrapper

**Files:**
- Modify: `app/src/app/graph/page.tsx`

Server component. If `?focus` is present, run the entity-loader (reuse from Plan 2) for initial load. Pass initial payload to ExplorerClient.

If no `?focus`, render the empty state: centered `>` prompt + signature-subgraph picker.

```tsx
export const dynamic = "force-dynamic";

export default async function GraphPage({
  searchParams,
}: {
  searchParams: Promise<{ focus?: string }>;
}) {
  const { focus } = await searchParams;
  const initial = focus ? await loadEntityForExplorer(focus) : null;
  const status = await loadStatus();

  return (
    <div className="flex min-h-screen flex-col bg-bg">
      <StatusBar {...status} />
      <NavHeader currentPath="/graph" />
      <ExplorerClient initial={initial} ingestAt={status.ingest_at} />
    </div>
  );
}
```

Commit both tasks: `add /graph explorer with fcose + URL state`.

### Task 8: `explorer-toolbar.tsx` — filters + hop slider + time slider

**Files:**
- Create: `app/src/components/explorer/explorer-toolbar.tsx`
- Create: `app/src/tests/components/explorer/explorer-toolbar.test.tsx`

Docked toolbar (top of explorer canvas). Components:
- **Hop slider** (1–4, default 2)
- **Node filters**: 21 toggle chips grouped by type family (People, Governance, Campaigns, Projects, Legal, Context, Records). Defaults per spec §6.3: Record / Place / Issue / AgendaItem off; everything else on; focus-type auto-enables.
- **Edge filters**: 4 toggle chips (governance / money / legal-constrains / universal). Defaults: first three on, universal off; toggling a node filter auto-enables its corresponding universal edge class.
- **Time slider**: two-thumb date range. Defaults per §5.4 rules.
- **Save view** dropdown: save current state to localStorage; list/load saved views.

Emit state changes via a prop callback.

Tests assert filter toggles update state, hop slider clamps to 1–4, time slider defaults to last 5 years widened to earliest loaded event.

### Task 9: `path-dialog.tsx` — pathfinding

**Files:**
- Create: `app/src/components/explorer/path-dialog.tsx`
- Create: `app/src/tests/components/explorer/path-dialog.test.tsx`

Modal dialog. Two search boxes (source + target, using `/api/search` autocomplete — reuse the palette-style UI from Plan 1 where possible, though Plan 4 owns the palette itself). A "loose path" checkbox. A "Find path" button.

On click, calls `/api/path?from=...&to=...&loose=...` and renders the result:
- Path found: render breadcrumb chain `{node} → {node} → {node}`, highlight path nodes and edges on the main canvas (amber outline).
- Loose match: show the "PATH VIA LOOSE MATCH" tag per spec §5.6.
- No path: "no path under default rules · try loosen path".

### Task 10: `save-view-menu.tsx` — localStorage save/load

**Files:**
- Create: `app/src/components/explorer/save-view-menu.tsx`
- Create: `app/src/tests/components/explorer/save-view-menu.test.tsx`

Serialize current ExplorerState to localStorage under a user-provided name. List saved views in a dropdown; click to load (applies state, navigates to new URL). Export to JSON file button.

Storage key: `openmarin_saved_views` (JSON object mapping name → ExplorerState). Limit to last 20 views.

### Task 11: `overflow-indicator.tsx` — "+N more" for expand

**Files:**
- Create: `app/src/components/explorer/overflow-indicator.tsx`

Small badge that appears on a node when its expand would produce more than the cap. "+{N}" label on the node. Clicking re-runs expand with a larger cap? Or just a text indicator? Spec §6.3 says "+{N} more · expand again to load more" — text indicator is simplest.

### Task 12: Integrate toolbar + path dialog + save view + overflow into ExplorerClient

Wire all Phase B components together in `explorer-client.tsx`. Handle all the keyboard + mouse interactions. Commit.

### Task 13: Explorer smoke test

Visit `http://localhost:3100/graph?focus=person-kate-colin` — expect the radial hero from Plan 2 transplanted into fcose layout, with the full toolbar. Try:
- Click a Decision node → 1-hop expansion adds nodes
- Set slider to 3, right-click expand-all → 3-hop expansion adds more
- Toggle "money" edge filter off → money edges hide
- Open path dialog, search "kate colin" and "merrydale", find path
- Save view, reload page, load view

Fix any bugs before committing.

---

## Phase C — Data explorer (5 tasks)

### Task 14: `data-queries.ts` — 10 predefined query templates

**Files:**
- Create: `app/src/lib/server/data-queries.ts`
- Create: `app/src/tests/lib/server/data-queries.test.ts`

Per spec §8 / v1 §5c, the 10 queries:

1. **San Rafael decisions since 2019** — filter by meeting date, institution, issue, linked project/program
2. **Money flows over $X by year, flow type, and related decision/project** — filter by amount threshold, date range
3. **Filings by person or committee 2020–2026** — grouped by filing_type
4. **Current officeholders and Form 700/803 coverage**
5. **Agreements and amendments for a project** — especially Downtown Library + Merrydale
6. **Legal proceedings affecting a local project/program** — Boyd/Grants Pass threads
7. **Evidence records supporting a decision, project, or case**
8. **Local pressure ranking for San Rafael threads** — QX-001 outputs
9. **Campaign money within N days of a local decision** — bounded San Rafael
10. **QA-only: unresolved validation/reconciliation gaps**

Each query has:

```typescript
export type DataQueryDef = {
  slug: string;
  display_name: string;
  description: string;
  filters: Array<{
    key: string;
    label: string;
    type: "date" | "amount" | "select" | "text";
    default?: string;
    options?: string[];
  }>;
  columns: Array<{ key: string; label: string; sortable: boolean; alignment?: "left" | "right" }>;
  cypher: (filters: Record<string, string>) => { query: string; params: Record<string, unknown> };
};
```

Write stub queries first for each of the 10 (simplest Cypher that returns rows with the expected columns). Full accurate queries can be refined; the contract is the filter + column shape.

Tests assert the 10 queries exist and their Cypher is parameterized (no string interpolation of user input).

Commit: `add data-queries: 10 predefined templates for /data explorer (§8)`.

### Task 15: `/api/data/[query]/route.ts`

**Files:**
- Create: `app/src/app/api/data/[query]/route.ts`

GET `/api/data/{slug}?{filters...}`. Look up the query by slug, validate filters (reject unknown ones; type-check values), run Cypher, return `{ query: slug, rows: [...], columns: DataQueryDef.columns }`.

Commit.

### Task 16: `/data/page.tsx` — left rail + first query by default

**Files:**
- Modify: `app/src/app/data/page.tsx`
- Create: `app/src/components/data/data-query-nav.tsx`

Server component. Server-side fetch `/api/data/san-rafael-decisions-since-2019` (or whatever the first query slug is). Render left rail (query list) + query view (filters + table).

### Task 17: `data-filters.tsx` + `data-table.tsx`

**Files:**
- Create: `app/src/components/data/data-filters.tsx`
- Create: `app/src/components/data/data-table.tsx`
- Tests for each

Filters render as horizontal chips above the table. Changing a filter pushes state to URL (so the URL bar is shareable). Table sorts in-browser on column click. CSV export button downloads `{slug}-{timestamp}.csv` from the current filter state.

### Task 18: `/data/[query]/page.tsx` — per-query view

**Files:**
- Create: `app/src/app/data/[query]/page.tsx`

Server component. Parses search params for filter values, calls `/api/data/{query}`, renders the left rail + filters + table.

Smoke test: visit `/data/san-rafael-decisions-since-2019`, apply a date filter, export CSV.

Commit Phase C: `add /data explorer — 10 predefined queries with filters + CSV`.

---

## Phase D — Search results page (3 tasks)

### Task 19: `/search/page.tsx` — real implementation

**Files:**
- Modify: `app/src/app/search/page.tsx`
- Create: `app/src/components/search/search-results.tsx`
- Create: `app/src/tests/components/search/search-results.test.tsx`

Server component. Reads `?q=` and `?include_records=` from search params. Calls `/api/search?q=...&include_records=...` (the existing Plan 1 endpoint). Renders the bucketed layout per spec §3.3:
- If `include_records=false` and `results[0]` is a Record (exact-id match): show "EXACT MATCH" kicker above it.
- Entity bucket: list cards, each showing type badge, `search_label`, `key_fact`, `last_activity`, link to entity page.
- Record bucket divider + list (only if `include_records=true`).
- Include-records checkbox toggles the param.

Empty state: "no matches · try the command palette" (palette is Plan 4, so just a note for now).

### Task 20: `search-results.tsx` component

See above — extract the bucket rendering into a reusable component. Test it with mocked `/api/search` responses.

### Task 21: Search smoke test

Visit `/search?q=kate+colin`, verify the homepage's prompt-search `↵` landing lands here. Toggle `include_records=true`, see divider + Records. Click an entity to navigate to its page.

Commit: `add /search?q= results page — bucketed rendering per §3.3`.

---

## Phase E — Browse pages (4 tasks)

### Task 22: `browse-queries.ts`

**Files:**
- Create: `app/src/lib/server/browse-queries.ts`
- Create: `app/src/tests/lib/server/browse-queries.test.ts`

Per-type paginated list query. Cursor-based pagination (`?cursor={id}&limit=50`). Order by type-specific key (Person: `name ASC`; Decision: `decided_at DESC`; etc.).

Signature: `buildBrowseQuery(type: NodeType, opts: { cursor?: string; limit: number; search?: string })`.

### Task 23: `/api/browse/[type]/route.ts`

GET `/api/browse/{type}?cursor=...&limit=50&q=...`. Returns `{ rows: [...], next_cursor: string | null }`.

### Task 24: `/browse/[type]/page.tsx`

**Files:**
- Modify: `app/src/app/browse/[type]/page.tsx`
- Create: `app/src/components/browse/browse-table.tsx`

Server component. Paginated table. Optional search box filters by `search_label`. "Load more" button appends next page.

Per-type column sets (reuse logic from `factsForEntity` in Plan 2, extracted to `entity-columns.ts` if clean):
- Person: Name, Current seat, Jurisdiction
- Decision: Subject, Decided at, Institution
- etc.

### Task 25: Browse smoke test

Visit `/browse/person`, `/browse/decision`, `/browse/moneyflow`. Verify pagination works, search filters, click-through to entity pages.

Commit Phase E: `add /browse/{type} paginated lists per type`.

---

## Phase F — Verify + ship (2 tasks)

### Task 26: Final `npm run verify` + `npm run build`

Expected: ≥ 170 tests (Plan 2 had 128; Plan 3 adds ~40), all green; build succeeds; 20+ routes registered.

### Task 27: End-to-end smoke

```bash
cd app && rm -rf .next && npm run build && PORT=3100 npm run start &
sleep 3
# Explorer
curl -sL "http://localhost:3100/graph?focus=person-kate-colin" | grep -oE "(KATE COLIN|ENTITY · PERSON)" | sort -u
curl -s "http://localhost:3100/api/path?from=person-kate-colin&to=project-san-rafael-350-merrydale-interim-shelter" | python3 -m json.tool | head
# Data
curl -sL "http://localhost:3100/data/san-rafael-decisions-since-2019" | grep -oE "(DATA · SAN RAFAEL|sortable|CSV)" | head
curl -s "http://localhost:3100/api/data/money-flows-by-year?min_amount=10000" | python3 -m json.tool | head -20
# Search
curl -sL "http://localhost:3100/search?q=merrydale" | grep -oE "(SEARCH · MERRYDALE|Kate Colin|Merrydale)" | head
# Browse
curl -sL "http://localhost:3100/browse/decision" | grep -oE "(BROWSE · DECISIONS|Resolution)" | head
kill %1
```

Fix any broken smoke tests before closing.

Commit: `smoke-test Plan 3 surfaces end-to-end`.

---

## Plan 3 completion checklist

- [ ] All 27 tasks committed.
- [ ] `npm run verify` green (≥ 170 tests).
- [ ] `npm run build` green with ≥ 20 routes.
- [ ] `/graph?focus={id}` renders fcose explorer with real data; expand + expand-all work; pathfinding finds paths for known connected pairs; filters apply; time slider filters loaded nodes; save-view persists.
- [ ] `/data` renders the 10 query list; each query runs with filters; CSV export works.
- [ ] `/search?q=...` renders bucketed results; include-records toggles records below a divider.
- [ ] `/browse/{type}` paginates through each type; search-by-name filters; click-through to entity pages.
- [ ] Homepage links (from Plan 1 stubs) now all resolve to real pages.

Follow-ons for Plan 4:
- Command palette (⌘K)
- Keyboard shortcuts ( `/`, `g g`, `g d`, `g c`, `?`, `esc`)
- Invite-only auth (release gate)
- Vercel deploy polish
- `/about` page

Plan 5 (deferred per spec §9):
- `/chat` AI chat
