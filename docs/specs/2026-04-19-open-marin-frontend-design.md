# Open Marin — Frontend Design Spec

**Date:** 2026-04-19
**Status:** Draft (awaiting review)
**Author:** Claude (Opus), with Stuart Watson
**Scope:** Visual and product design of the Next.js application described in Section 5 of the v1 design spec.
**Supersedes:** visual/product direction portions of `docs/superpowers/plans/2026-04-14-nextjs-app-core-browse.md` (plan will be rewritten after this spec is approved).

## 1. Design thesis

Open Marin is a **dark-mode, terminal-flavored civic-intelligence workstation**. The graph is the product's wow moment and its primary proof; everything else is chrome that lets you reach the graph and the records behind it.

The aesthetic sits between three references:
- **Machinery of Government UK** for the graph's restraint and informational bearing.
- **poetengineer / Obsidian dark graph skins** for atmospheric glow on nodes and edges.
- **A serious computer terminal** (think DEC VT220 on a well-run mainframe, not a CRT costume) for the chrome — status bars, path-readable URLs, monospace labels, prompt-styled search, ⌘K palette.

The product is invite-only, so the design optimizes for **return users doing investigations** over **first-time casual visitors**. But chrome remains legible to a friend-who-got-a-link: the top nav is explicit, the homepage explains itself with a captioned signature subgraph, and the keyboard shortcuts are a reward, not a requirement.

## 2. Foundations

### 2.1 Mode
Dark only. No light-mode toggle in v1. The product's feel depends on the graph's glow against deep black — a light mode would require redesigning the graph's visual language from scratch.

### 2.2 Palette

| Role | Hex | Usage |
|---|---|---|
| Background | `#07090d` | Root page background. |
| Panel | `#0b0d11` | Status bar, header, cards elevated from the page. |
| Surface (raised) | `#14171d` | Hover states, selected nav items, command palette. |
| Border primary | `#1f232b` | Between major regions (panes, columns). |
| Border hairline | `#1a1d24` | Between rows in tables and lists. |
| Body text | `#c2c8d2` | Default reading color. |
| Dim text | `#7b8494` | Metadata, captions, de-emphasized chrome. |
| Hairline text | `#5e6573` | Path segments, status-bar right-side info. |
| Node: focus / selected | `#ffffff` | Current entity, graph center, selected row. |
| Node: decision | `#a4e8bf` | Decision nodes. |
| Node: money | `#f2c77a` | MoneyFlow nodes. |
| Node: person | `#8db8ff` | Person nodes. |
| Node: case / legal | `#e27a7a` | Case / Proceeding nodes and legal-constrains edges. |
| Node: organization | `#b8a8d9` | Organization nodes (all subtypes — Government, Nonprofit, Business, Political, Court, Department, Commission). |
| Node: project / program | `#d9a88d` | Project and Program nodes. |
| Node: generic | `#e8ecf3` | Everything else — Meeting, AgendaItem, Committee, Filing, Seat, SeatService, Election, Candidacy, Agreement, Amendment, Record, Place, Issue, Proceeding. |

All colored nodes carry a soft `drop-shadow` glow tuned per color (amber: ~5px / 0.7 alpha; blue: ~5px / 0.6; pink: ~5px / 0.6; mint: ~6px / 0.7; lavender: ~4px / 0.5; sand: ~4px / 0.5). The focus node gets a stronger 8px / 0.9 glow.

**Shape encoding (second channel, applies to generic bucket):** within the generic bucket, shape distinguishes structural categories so the signature subgraph stays readable before hover:
- **Circle** (default): events and artifacts — Meeting, AgendaItem, Filing, Election, Agreement, Amendment, Record, Proceeding.
- **Square**: places and topics — Place, Issue.
- **Ring (outlined circle)**: role structures — Seat, SeatService, Candidacy, Committee.

Colored nodes (decision / money / person / case / organization / project-program) are always solid circles — shape is reserved for disambiguating the generic bucket.

### 2.3 Typography

Four faces, used with specific intent. Never substitute one for another.

| Face | When | Sample |
|---|---|---|
| **IBM Plex Sans** (400/500/600) | Body copy, entity page prose, card titles, connection card content. | "A county-funded interim shelter approved in November 2025." |
| **IBM Plex Mono** (400/500) | UI chrome, nav, catalog rows, data-explorer tables, section headers, `⌘K` chips, node-level graph labels. | `/project/350-merrydale-interim-shelter` |
| **IBM Plex Serif Italic** (400) | Editorial callouts — a single-paragraph context blurb on Tier 1 entity pages where a human-written note is warranted. Never for primary content. | *"Primary sources: staff reports, agreement packet, LCA amendment."* |
| **VT323** (400) | Status-bar values, hero numerals (amounts, counts), graph captions, big entity-page stat strips, the brand's blinking cursor. Not used for node labels (too small to render legibly). | `$15,337,953` |

**Type scale** (authoritative — any later section that disagrees with this table is wrong and should be reconciled to this):

| Role | Face | Size |
|---|---|---|
| Hero page title (entity page) | VT323 | 40px |
| Hero stat strip (big numerals: amounts, counts) | VT323 | 30px |
| Hero meta line (under title: jurisdiction, kicker identifiers) | Plex Mono 400 | 11px |
| H2 section heading | Plex Sans 500 | 18px |
| Section label ALL CAPS | Plex Mono 500 | 10–11px, `letter-spacing: 0.14em`, uppercase |
| Body | Plex Sans 400 | 13.5–14px, `line-height: 1.55` |
| Data row / table cell | Plex Mono 400 | 12px |
| Data table — amount cells | Plex Mono 400 | 12px, color `#f2c77a` (amber) — NOT VT323 at this size |
| Graph node label | Plex Mono 400 | 9–10px |
| Graph caption (under signature subgraph) | VT323 | 16px |
| Status-bar label | Plex Mono 400 | 11px |
| Status-bar value | VT323 | 14px |
| Thread card stat strip | VT323 | 15px |
| Keyboard chip | Plex Mono 400 | 10px, inside `<kbd>` with border |

**VT323 legibility rule (single source of truth):** VT323 is only used at sizes ≥ 14px. Amber-colored amounts inside the data explorer table (12px rows) use Plex Mono with `#f2c77a` color, not VT323.

### 2.4 Motion

- **Homepage signature subgraph**: subtle drift (~0.3–0.5px node translation at ~0.2Hz), never fully still. The drift is decorative; interaction is a deep-link click, not re-center.
- **Entity-page radial hero**: smooth 250ms ease-out radial expansion on page load; hovered node scales to 1.2x; clicking re-centers with a 350ms tween.
- **Full-screen explorer**: real force-directed physics (Cytoscape fcose or cola layout). No artificial easing.
- **Blinking cursor** (brand, prompts): 1.1s step animation. Avoid continuous smooth fades — it's a terminal cursor.
- **Status bar dot**: constant glow, no pulse.
- **Everywhere else**: 120–180ms ease-out for hover, 200–250ms for nav transitions. No bounces, no springs.

## 3. Homepage (`/`)

Layout: **25 / 50 / 25 three-column hero**, under a status bar and header row.

### 3.1 Status bar (top, full width)

Single-line, Plex Mono labels + VT323 values, separated by middots. Green dot at start indicates live AuraDB connection.

```
● CONNECTED · AURADB · NODES 112,431 · EDGES 141,207 · JURISDICTIONS 11 · INGEST 2026-04-14 · SUBGRAPHS 2026-04-18
```

**Two freshness timestamps**, reflecting the system's two data sources (see §3.7 Freshness contract):
- `INGEST` — most-recent successful run of the ingestion pipeline (source of truth for live Cypher queries).
- `SUBGRAPHS` — most-recent rebuild of the baked signature-subgraph bundle (source of truth for the homepage centerpiece).

If either is stale beyond its threshold (ingest: 14 days default; subgraphs: 7 days default), the green dot shifts amber and a `STALE: INGEST` or `STALE: SUBGRAPHS` tag appears inline.

### 3.2 Header row

- Left: `OPEN MARIN` brand in VT323 22px + blinking green cursor block.
- Middle: explicit nav — `Home · Graph · Data · Chat · About` — Plex Mono 12px. Active page gets a `#14171d` background and `#262b35` border.
- Right: `open palette ⌘K` chip in Plex Mono 11px.

### 3.3 Prompt-styled search row (homepage only)

Full-width below the header, inside the homepage grid. Plex Mono placeholder with a VT323 green `>` chevron on the left. On the homepage, pressing `/` focuses this field. On any other route, pressing `/` opens the command palette (§4.3) with its input pre-focused. The homepage field and the command palette share a single search implementation and corpus — the only difference is where results render.

**Execution contract:**
1. User types a query and presses `↵`.
2. Client navigates to `/search?q={query}` — a results page (see §4.5).
3. The command palette (⌘K) uses the same backend but renders results inline inside the modal; selecting a palette result navigates directly to the entity page, skipping the results page.

**Search corpus (authoritative v1, single source of truth):** matches against `name`, `aliases`, and `id` on the 14 indexed types — `Person`, `Organization`, `Decision`, `Project`, `Program`, `Case`, `Meeting`, `Filing`, `Committee`, `Agreement`, `Amendment`, `Election`, `Place`, `Issue`. **Records are excluded** from general search (too noisy, too many). A checkbox in the results page toggles `include records` for the rare case where Record IDs are needed.

**Ranking:** exact ID match > name prefix match > alias match > name substring match. Ties broken by `node_degree` descending (more-connected nodes rank higher).

### 3.4 Left column — Catalog

A single Plex Mono list of node types with counts. Every row maps to exactly one node label and links to `/browse/{type}`, a filtered list view (see §4.1). Counts come from the `/api/catalog.json` baked bundle (§3.7) and are authoritative for their build window.

Grouped for readability only — grouping does not change what a row links to:

**People & organizations**
- People (`Person`)
- Organizations (`Organization`)

**Governance**
- Meetings (`Meeting`)
- Agenda items (`AgendaItem`)
- Decisions (`Decision`)
- Seats (`Seat`)
- Seat services (`SeatService`)

**Elections & campaigns**
- Elections (`Election`)
- Candidacies (`Candidacy`)
- Committees (`Committee`)
- Filings (`Filing`)
- Money flows (`MoneyFlow`)

**Programs, projects, agreements**
- Programs (`Program`)
- Projects (`Project`)
- Agreements (`Agreement`)
- Amendments (`Amendment`)

**Legal**
- Cases (`Case`)
- Proceedings (`Proceeding`)

**Context**
- Places (`Place`)
- Issues (`Issue`)

**Records (separate section, visually dimmer):**
- Source records (`Record`) — the evidence corpus. Rendered separately because clicking it takes you to a Records browse view with different default filters (by source URL presence, by record_type) rather than the generic entity-list treatment.

No row labeled "Evidence links" — that was an artifact of an earlier draft and isn't a node type.

### 3.5 Center column — Signature subgraph

One curated, captioned subgraph rendered with the Obsidian Glow language (see §5). Center position holds `#ffffff` focus node; 1–2 hop neighborhood fans out with type-colored nodes and edges. Data is served by a baked bundle (see §5.5 for the full contract). Clicking any node navigates to `/graph?focus={id}` — no on-homepage re-centering.

**Caption** (bottom-left, VT323 16px): auto-generated from the bundle's `headline_stats` field. Example: `$15,337,953 · 6 decisions · 3 counterparties · 20 records`.

**Kicker** (top-right, Plex Mono 10px uppercase): `SIGNATURE SUBGRAPH · {bundle.display_name.upper()}`.

**Rotation.** On each session load, one subgraph is selected uniformly at random from the bundle manifest (`/api/subgraphs/manifest.json`). No carousel controls, no "next" button. Initial rotation candidates (editable in `registry/signature-subgraphs.yaml`):
- 350 Merrydale Interim Shelter (project, $15.3M)
- Sanctioned Camping Program (program, Boyd-constrained)
- Boyd v. City of San Rafael (case, federal)
- Downtown Library Renovation (project, $15M+)
- Kate Colin (person, mayor)
- Resolution 15336 (decision)
- Grants Pass v. Johnson (case)
- Form 803 Kate Colin / PG&E / Canal Alliance (filing + money chain)

### 3.6 Right column — Currently tracking

4–5 thread cards. Each card:

- **Title** — Plex Sans 500, 13px, white (`#e6e8ec`).
- **Meta line** — Plex Mono 10.5px, dim: `project · San Rafael` or `case · federal`.
- **Stat line** — VT323 15px, amber, glowing: `$15.3M · 6 decisions`.

Cards link to the relevant entity page. The thread list is hand-curated (editable via a config file) until we build a thread-definition layer.

### 3.7 Freshness contract

Every surface in the app declares its data source, caching policy, and freshness indicator. The status bar is a summary of these.

| Surface | Source | Cache | Freshness indicator |
|---|---|---|---|
| Homepage signature subgraph | Baked bundle (`/api/subgraphs/{slug}.json`) generated from Neo4j by a nightly script | Built at ingestion time; served as static JSON | `SUBGRAPHS` timestamp in status bar; caption kicker also shows build date |
| Homepage catalog counts | Baked bundle (`/api/catalog.json`) | Built at ingestion time | Counts reflect `INGEST` timestamp |
| Homepage "currently tracking" threads | Hand-curated config file committed to repo | Static, rebuilt only on deploy | No per-surface indicator — rotates on deploy |
| Entity pages (facts, connections, timeline, evidence drawer) | Live Cypher against AuraDB | No cache (fresh every request) | `INGEST` timestamp in status bar |
| Entity-page radial hero | Live Cypher against AuraDB with per-type neighborhood rules (§5.1.1) | No cache | `INGEST` timestamp |
| Full-screen explorer | Live Cypher against AuraDB | No cache | `INGEST` timestamp |
| Data explorer | Live Cypher against AuraDB | No cache | `INGEST` timestamp |
| Command-palette fuzzy index | Pre-built index shipped with deploy (name/alias table from all searchable types) | Rebuilt at ingestion time | Palette footer shows build date in Plex Mono dim |

**Invariant:** if a user sees a node on the homepage signature subgraph, navigates to its entity page, and the live data shows materially different facts, the entity page is authoritative and the baked subgraph must be rebuilt. The app does not detect this divergence automatically in v1; it's a staleness signal for the ingestion operator.

## 4. Navigation & IA

### 4.1 Top-level routes

| Path | Destination |
|---|---|
| `/` | Homepage. |
| `/graph` | Full-screen network explorer. |
| `/graph?focus={id}` | Explorer centered on a specific node. |
| `/data` | Data explorer (predefined queries, filtered tables, CSV export). |
| `/search?q={query}` | Search results page (§4.5). |
| `/chat` | AI chat (deferred per v1 design spec). |
| `/about` | Static page: what is this, how it was built, methodology, source list. |
| `/browse/{type}` | Paginated filtered list of a single node type. |
| `/{type}/{slug}` | Entity page. `{type}` is the URL-form type (see §4.2); `{slug}` is the ID with the type prefix stripped. |

### 4.2 Entity route form — ID, slug, and collisions

The graph's canonical node IDs already follow a type-prefixed, kebab-case convention (examples from the current projected layer: `person-kate-colin`, `project-san-rafael-350-merrydale-interim-shelter`, `case-boyd-v-city-of-san-rafael`, `decision-2024-08-19-resolution-15336`).

**Routing rule (no separate slug field in v1):**
- The URL `{type}` segment is the lowercase singular type name: `person`, `organization`, `decision`, `project`, `program`, `case`, `meeting`, `filing`, `committee`, `agreement`, `amendment`, `election`, `candidacy`, `seat`, `seat-service`, `agenda-item`, `money-flow`, `proceeding`, `record`, `place`, `issue`.
- The URL `{slug}` segment is the canonical node ID with the type prefix stripped. Examples:
  - `person-kate-colin` → `/person/kate-colin`
  - `project-san-rafael-350-merrydale-interim-shelter` → `/project/san-rafael-350-merrydale-interim-shelter`
  - `case-boyd-v-city-of-san-rafael` → `/case/boyd-v-city-of-san-rafael`
  - `seat-service-san-rafael-mayor-2024` → `/seat-service/san-rafael-mayor-2024`
- IDs whose prefix differs from the singular type name (legacy `actor-*`, `inst-*`, or the `eid-*` prefix merged into Filing) resolve through a small alias table committed to the repo at `app/src/lib/id-aliases.json`. Example: `actor-kate-colin` → `/person/kate-colin` via alias. An entity page receiving `/person/{slug}` looks up both `person-{slug}` and any aliased-to `person-{slug}` on the node.
- **Collision handling:** node IDs are deterministic and produced by the normalizer, so collisions within a type are treated as ingestion bugs — the loader already refuses to load duplicates. The frontend does not attempt to disambiguate.
- **Unknown slugs** return a 404 page that shows the attempted URL and a search-from-here prompt.

**No on-page breadcrumb component** — the browser URL bar is the breadcrumb.

### 4.3 Command palette (⌘K)

Power shortcut, not primary navigation. Opens a centered modal. Shares the exact search corpus and ranking rules with the homepage search and `/search?q=` results page (§3.3) — this is a deliberate invariant so "search" means one thing everywhere in the product.

Palette sections:
1. **Results** — up to 20 ranked matches from the authoritative v1 corpus (14 types, Records excluded by default — toggleable).
2. **Recent entities** — last 10 viewed, session-scoped (localStorage).
3. **Quick jumps** — `go home`, `go graph`, `go data`, `go chat`, `go about`.

Escape closes. Return navigates to the highlighted item.

### 4.4 Keyboard shortcuts (global)

| Key | Action |
|---|---|
| `⌘K` | Open command palette |
| `/` | Focus search |
| `g h` | Home |
| `g g` | Graph explorer |
| `g d` | Data explorer |
| `g c` | Chat |
| `?` | Shortcut overlay |
| `esc` | Close modal / clear focus |

These are not displayed on the homepage in variant A — they surface in the command palette, in a `?` overlay, and on hover over the `⌘K` chip.

### 4.5 Search results page (`/search?q=...`)

- Layout reuses the data-explorer chrome (status bar, header, filters row, results table).
- Query is echoed as a prompt-style header: `> {query}` in VT323 22px.
- Results table columns: `type`, `name`, `jurisdiction`, `key_fact`, `last_activity`.
- Default: excludes Records. Checkbox toggles `include records`.
- Clicking a row navigates to that entity's page.
- Empty state shows "no matches" + a suggestion to try the command palette.

## 5. Graph visual language

Applies consistently to all three graph surfaces.

### 5.1 Nodes

- Rendered as circles (or squares/rings for generic-bucket disambiguation — see §2.2 shape encoding).
- **Size** encodes importance within the current view: focus node largest (radius 9–11), primary neighbors medium (6–7), secondary neighbors small (4–5), tertiary dots (3).
- **Color** encodes node type (see palette). Organization is lavender, Project/Program is sand, the rest of the generic bucket is light gray and distinguished by shape.
- **Labels** shown for focus node and all 1-hop primary neighbors; hidden by default for 2-hop+ nodes (appear on hover). Labels use Plex Mono 9–10px in `#b0b7c3`.

### 5.1.1 Neighborhood selection rules (for entity-page radial hero)

High-degree entities like `person-kate-colin` touch hundreds of decisions and meetings. A naive "LIMIT 40" is visually unstable and investigatively misleading (you never know what you're seeing). The radial hero instead uses a **deterministic per-type selection contract** that caps total nodes at 40 while preserving the investigatively important neighbors.

**Always-include** (visible regardless of degree):
- All `:Case` nodes connected via `CONSTRAINS` or `PARTY_TO`.
- All `:Seat` and current `:SeatService` nodes for a Person.
- All `:Committee` nodes a Person controls or a Candidacy belongs to.
- Directly-linked `:Agreement` for a Project.
- Directly-linked `:Program` for a Project and vice versa.

**Ranked selection with per-type quotas** (filled in order until the 40-node cap hits):

| Type | Quota | Ranking key |
|---|---|---|
| MoneyFlow | up to 8 | `amount DESC` |
| Decision | up to 8 | `decided_at DESC` |
| Filing | up to 6 | `signed_at DESC` |
| Meeting | up to 6 | `meeting_date DESC` |
| Person | up to 6 | degree centrality inside current 2-hop neighborhood |
| Organization | up to 4 | degree centrality |
| Record | up to 4 | `captured_at DESC` |
| AgendaItem | up to 4 | `item_number ASC` |
| Amendment | up to 2 | `effective_date DESC` |

**Excluded from the hero** (too structural to add signal): `:Place` and `:Issue`. Both appear in the facts panel and connections list, but not the graph — they would dominate as high-degree hubs.

**When the 40-cap is reached**, a Plex Mono dim footer on the graph pane reads `+{N} more neighbors · see /graph?focus={id}` linking to the full-screen explorer where no cap applies.

The selection runs as a single parameterized Cypher query per entity type. The query shape is part of the implementation plan; the contract above is what it must satisfy.

### 5.2 Edges

Edges carry meaning. Three styles:

| Style | Stroke | Usage |
|---|---|---|
| **Governance (default)** | `rgba(150,180,220,0.22)` thin 0.9px solid | AT_MEETING, ABOUT_ITEM, DECIDED_BY, PART_OF, HELD_BY, FOR_SEAT, RESULT_OF, AT_INSTITUTION, AT_PLACE, EVIDENCED_BY, RELATES_TO_ISSUE, BETWEEN, FOR_PROJECT, ABOUT_PROJECT, ABOUT_PROGRAM |
| **Money** | `rgba(220,200,140,0.55)` 1.2px solid with amber glow | FROM_SOURCE, TO_TARGET, DISCLOSED_IN, UNDER_AGREEMENT |
| **Legal constrains** | `rgba(226,122,122,0.45)` 1.1px dashed `3,3` with pink glow | `(:Case)-[:CONSTRAINS]->(:Decision)` and parent PARTY_TO where the case is also linked via CONSTRAINS |

Other typed edges (FILED_BY, CONTROLLED_BY, BY_PERSON, etc.) render as governance gray — not enough semantic weight to warrant distinct encoding, and the node colors already tell the story.

### 5.3 Focus treatment

The focus node is:
- `#ffffff` fill.
- 8px drop-shadow glow at 0.9 alpha.
- Ring with `#f2b441` 2px stroke *only* on the full-screen explorer (too visually heavy on homepage and entity-page heroes).

### 5.4 Temporal semantics (timeline ribbon + explorer time slider)

The graph has many date fields and some important entities have no single event date. Two engineers shown "add a time slider" will produce incompatible semantics. This section is the single source of truth.

**Per-type temporal projection:**

| Type | `event_date` field used for filtering | Treatment |
|---|---|---|
| Meeting | `meeting_date` | Point event. |
| Decision | `decided_at` | Point event. |
| MoneyFlow | `flow_date` | Point event. |
| Filing | `signed_at` | Point event. Period fields (`period_start`, `period_end`) shown as secondary context, not used for slider inclusion. |
| Election | `election_date` | Point event. |
| Proceeding | `date` | Point event. |
| Agreement | `effective_date` | Point event (start). Amendments show as additional events on the ribbon. |
| Amendment | `effective_date` | Point event. |
| Case | `filed_at` | Range: `filed_at` through `closed_at` (or "open" if null). Visible on slider if range overlaps. |
| SeatService | `started_at` through `ended_at` | Range. Visible if range overlaps. |
| Candidacy | linked `Election.election_date` | Point event via election. |
| Person / Organization / Committee / Project / Program / Place / Issue / Seat / Agenda­Item / Record | **none** | Always visible regardless of slider — these are durable entities, not events. |

**Slider semantics:**
- Slider sets an inclusive `[from, to]` range.
- Point events are visible iff `from ≤ event_date ≤ to`.
- Ranges are visible iff `range.start ≤ to AND (range.end IS NULL OR range.end ≥ from)`.
- Durable entities are always visible.
- Nodes with a required date field set to `NULL` render as "date-unknown" with a small hollow tick on the timeline and are visible at any slider range.

**Default slider range:** last 5 years from `INGEST` timestamp, clamped to the earliest event in the current subgraph.

This contract applies identically to the timeline ribbon on Tier 1 entity pages and the explorer's time slider.

### 5.5 Signature-subgraph contract (homepage centerpiece)

Baked JSON served from `/api/subgraphs/{slug}.json`. One file per curated subgraph, built by a script run at ingestion time from Neo4j. The manifest is served from `/api/subgraphs/manifest.json`.

**Manifest shape:**

```json
{
  "built_at": "2026-04-18T03:11:44Z",
  "subgraphs": [
    {
      "slug": "merrydale-interim-shelter",
      "display_name": "350 Merrydale Interim Shelter",
      "focus_node_id": "project-san-rafael-350-merrydale-interim-shelter"
    },
    ...
  ]
}
```

**Individual bundle shape:**

```json
{
  "slug": "merrydale-interim-shelter",
  "display_name": "350 Merrydale Interim Shelter",
  "built_at": "2026-04-18T03:11:44Z",
  "focus_node_id": "project-san-rafael-350-merrydale-interim-shelter",
  "headline_stats": {
    "caption": "$15,337,953 · 6 decisions · 3 counterparties · 20 records",
    "kicker": "SIGNATURE SUBGRAPH · MERRYDALE"
  },
  "nodes": [
    {
      "id": "project-san-rafael-350-merrydale-interim-shelter",
      "type": "Project",
      "label": "350 Merrydale Interim Shelter",
      "role": "focus",
      "route": "/project/san-rafael-350-merrydale-interim-shelter"
    },
    {
      "id": "moneyflow-merrydale-county-grant",
      "type": "MoneyFlow",
      "label": "$15.3M county grant",
      "role": "primary",
      "route": "/money-flow/merrydale-county-grant"
    },
    ...
  ],
  "edges": [
    {
      "source": "project-san-rafael-350-merrydale-interim-shelter",
      "target": "moneyflow-merrydale-county-grant",
      "type": "UNDER_AGREEMENT",
      "style": "money"
    },
    ...
  ]
}
```

**Rules:**
- `node.role` is one of `focus`, `primary` (1-hop), `secondary` (2-hop). The frontend uses this for sizing.
- `node.route` is the pre-computed URL — the frontend does NOT construct routes from raw IDs here.
- `edge.style` is one of `governance`, `money`, `legal-constrains`. Pre-classified so the frontend doesn't need to interpret relationship types.
- Bundles are immutable once built; the builder always writes a new file and updates the manifest atomically.
- Bundle size target: ≤ 60 nodes, ≤ 120 edges. Anything larger means the subgraph wasn't curated enough.

### 5.6 Pathfinding contract (full-screen explorer)

The explorer's "find path between two entities" feature needs explicit rules — shortest paths through `Record`, `Issue`, or `Place` routinely return technically-short but investigatively-useless paths.

**Default pathfinding behavior:**
- **Algorithm:** weighted shortest path (Neo4j `apoc.algo.dijkstra` or equivalent with the JavaScript driver).
- **Excluded node types** (never traversed): `Record`, `Issue`, `Place`, `AgendaItem`.
- **Edge weights** (lower = preferred):
  - `CONSTRAINS`, `CAST_VOTE`, `DECIDED_BY`, `PARTY_TO`: 1 (highest-signal)
  - `FROM_SOURCE`, `TO_TARGET`, `DISCLOSED_IN`, `UNDER_AGREEMENT`: 2
  - `HELD_BY`, `FOR_SEAT`, `RESULT_OF`, `CONTROLLED_BY`: 3
  - `AT_MEETING`, `AT_INSTITUTION`, `ABOUT_ITEM`, `FILED_BY`, `BY_PERSON`: 5
  - `EVIDENCED_BY`: excluded from default pathfinding entirely (too hub-like, only useful when starting or ending at a Record).
- **Max path length:** 6 hops.
- **UI toggle:** a "loosen path" checkbox in the explorer toolbar sets all excluded types/edges to weight 10 and allows traversal through them. Labeled so the user knows what they asked for.

When no path is found under default rules, the UI suggests "try loosen path" rather than silently returning a path through less-meaningful relationships.

## 6. The three graph surfaces

### 6.1 Homepage signature subgraph

- **Purpose**: tease connectedness, invite exploration.
- **Interaction**: click any node → navigate to the node's `route` (pre-computed in the bundle, see §5.5). No re-center, no hover-expansion.
- **Motion**: subtle drift (~0.3–0.5px at ~0.2Hz). Disabled under `prefers-reduced-motion`.
- **Data shape**: baked JSON bundle per §5.5. The frontend does not query Neo4j for this surface.
- **Freshness**: governed by §3.7; the `SUBGRAPHS` timestamp in the status bar is authoritative.

### 6.2 Entity-page radial hero

- **Purpose**: show "this entity is the center of its own story."
- **Interaction**: hover to reveal a node's label; clicking a node navigates to that entity's own page (where it becomes the focus). This is one action: re-centering and navigating are the same thing.
- **Layout**: Cytoscape `concentric` layout — 1-hop inner ring, 2-hop outer ring, focus at center. Not `cose-bilkent` or any force-directed layout. Ring placement is stable across renders so the same entity looks the same every visit.
- **Data shape**: live Cypher query using the neighborhood selection rules in §5.1.1. Total cap 40 nodes.
- **Freshness**: live Cypher, `INGEST` timestamp is authoritative.

### 6.3 Full-screen explorer (`/graph`)

- **Purpose**: investigation workbench.
- **Layout**: force-directed (Cytoscape `fcose`).
- **Features**:
  - Path finding between two entities (per the pathfinding contract in §5.6).
  - Subgraph extraction (select nodes → isolate).
  - Temporal filter / date slider (per the temporal semantics in §5.4).
  - Edge-type filter (toggle governance / money / legal-constrains classes, matching §5.2).
  - Hop limit slider (1–4).
  - Save view (session-scoped localStorage; JSON export for longer-term retention).
- **Interaction**: drag, pan, zoom, lasso-select, right-click for context actions.
- **Data shape**: starts from `?focus={id}` or empty state ("type a name or click Signature Subgraphs"); loads incrementally as user expands. Each expansion is a live Cypher call.
- **Freshness**: live Cypher, `INGEST` timestamp is authoritative.

## 7. Entity pages

### 7.1 Tier 1 — Person / Decision / Project / Program / Case / Meeting / Filing / Committee

Top-down composition:

1. **Status bar** (persists, same as homepage).
2. **Header row** (persists).
3. **Kicker + hero title**:
   - Kicker: Plex Mono 10px ALL CAPS, e.g. `PROJECT` or `DECISION · 2024-08-19`.
   - Title: VT323 38–44px, entity name.
   - Meta strip: Plex Mono 11px — jurisdiction, type-specific identifiers, status badges.
4. **Hero stat strip** (VT323 28–32px numerals): type-specific high-order facts.
   - Project/Program: total money, linked decisions, counterparties, evidence count.
   - Person: current seat, SeatService window, filings count.
   - Decision: decided-at date, vote summary, linked agenda item.
   - Case: filed-at, court, status, constrains count.
   - Meeting: date, institution, agenda-items count, decisions count.
   - Filing: filing type, signed-at, period, actor.
   - Committee: fppc_id, candidate, elections, money totals.
5. **Radial graph hero** (60–70% page width): entity centered, 1–2 hop neighborhood. Hover to reveal labels, click to re-center.
6. **Facts panel** (right rail, 30–40%): Plex Mono key-value table of scalar properties.
7. **Connections**: grouped by relationship type, each group a card cluster. Cards show related-entity title (Plex Sans 500), type badge (Plex Mono kicker), mini-meta. Click = navigate.
8. **Timeline ribbon**: horizontal, VT323 tick marks for dates, events plotted by date. Relevance filtered to events involving this entity or its 1-hop neighborhood.
9. **Editorial callout** (optional, Plex Serif italic): one-paragraph context blurb if a human-written note exists in the repo.
10. **Evidence drawer** (expandable, collapsed by default): list of source Record nodes. Each row shows `record_type`, `captured_at`, a preferred display path, and a preferred public link. Fields are resolved via the rules below so the drawer never leaks internal paths or breaks on missing sources.

**Record display contract.** The normalizer already produces (or must produce) these fields on every Record emitted into AuraDB. The frontend reads them as-is and does not interpret raw capture lists.

| Field | Resolution rule |
|---|---|
| `preferred_public_url` | First non-empty of: `source_url` (if present and `http(s)://`), else the record's canonical upstream URL derived from jurisdiction source registry, else `null`. Never an internal `file://` or on-disk path. |
| `preferred_display_artifact` | Short human label for what the user is clicking through to (e.g., `Staff report PDF`, `Minutes text`, `Committee page`). Derived from `record_type` + file extension. |
| `artifact_paths` | Array of internal paths (raw captures on the Mac mini). **Never rendered in the UI.** Used only when the app runs locally for Stuart's own investigation mode; omitted from any Vercel deployment response. |
| `has_public_source` | Boolean: `true` iff `preferred_public_url` is non-null. |

**UI treatment by resolution state:**
- If `has_public_source`: row is clickable; click opens `preferred_public_url` in a new tab; cursor pointer.
- If not: row is visually dim and labeled `no public source captured` in Plex Mono dim; not clickable; tooltip on hover explains that the record exists in the graph but its upstream copy was never captured or has gone dark.
- The Record ID is always selectable for citation, regardless of source availability.

### 7.2 Tier 2 — Organization / Seat / SeatService / Election / Candidacy / AgendaItem / MoneyFlow / Proceeding / Agreement / Amendment / Record / Place / Issue

Simpler composition: status bar + header + kicker + VT323 title + Plex Mono meta + facts panel + connections list + evidence links. No hero graph, no timeline, no editorial callout.

Every entity page shares the same status bar, header, footer, and type-color treatment so navigating between tiers never feels like landing in a different product.

## 8. Data explorer (`/data`)

Dense, terminal-flavored tables. All text Plex Mono 12px. Rows on `#0b0d11` with `#1a1d24` hairline dividers. Hovered row elevates to `#14171d`.

- **Left rail (240px)**: query templates as a list (the 10 predefined queries from v1 design spec §5c). Active template highlighted.
- **Filters row**: horizontal chips below the header. Type-specific filters (date range, amount threshold, jurisdiction, issue).
- **Table**: sortable columns; column header row in Plex Mono 500 uppercase with `letter-spacing: 0.14em`. Amount cells use Plex Mono 12px in amber (`#f2c77a`) — not VT323, since the 14px legibility rule applies. Date cells Plex Mono. Click any row → entity page.
- **Footer bar**: row count, export-to-CSV button (Plex Mono, on `#14171d` surface).

## 9. AI chat (`/chat`, deferred)

Last thing built. Design direction locked now so later work stays coherent:

- **Layout**: input anchored at bottom, scrolling transcript above. Full-width, no sidebar.
- **Input**: prompt-styled — `>` chevron + cursor + Plex Mono input. Enter sends.
- **Assistant output**: Plex Sans body. Citations rendered as Plex Mono chips `[record-xxxxx]` that expand on click into a popover with the source Record's details.
- **Context chip** (top-left): if chat was opened from an entity page, display the entity as a dismissible chip. The system prompt receives that entity as context.
- **Mode indicator** (top-right): small Plex Mono label — `QUERY`, `CONTEXT`, or `INVESTIGATION` — reflecting which mode the assistant selected.
- **System flashes** (Plex Mono 11px dim): transient lines above the transcript — `LOADING SUBGRAPH…`, `CYPHER OK · 23 ROWS`, `TIMEOUT`. Fade after 2s.

## 10. Accessibility & legibility

- All text colors pass WCAG AA against their background. The dim text (`#7b8494` on `#07090d`) is ~4.6:1 — acceptable for non-essential metadata but **not** used for body copy or any text carrying a required meaning.
- VT323 at small sizes can be hard to read; we constrain it to large display sizes (14px+).
- Glow effects are decorative and do not carry semantic meaning — anyone with reduced-motion or vision issues still gets full information from hex color and shape.
- Respect `prefers-reduced-motion`: disable homepage graph drift, reduce radial-hero expansion to an instant transition, disable cursor blink.

## 11. Out of scope

- Light mode.
- Mobile-optimized layouts (desktop-first, breaks below ~1024px acceptable for v1).
- Scanlines, CRT distortion, green-on-black monochrome, phosphor burn-in, or any literal retro-terminal pastiche.
- Command-palette-first navigation (top nav remains primary).
- Sankey money-flow and org-structure tree visualizations (deferred to v2 per v1 design spec §5b).
- Multi-user sessions, shared investigation views, comments, annotations.

## 12. Relationship to the existing v1 design spec and plan

**v1 design spec (`docs/specs/2026-04-14-marin-civic-graph-v1-design.md`)**: functional scope remains authoritative. Section 5 (Product Surfaces), Section 6 (Auth), Section 8 (Out of Scope), and Section 9 (Success Criteria) are unchanged. This spec fills in visual + interaction detail the v1 spec left open.

**Next.js app + core browse plan (`docs/superpowers/plans/2026-04-14-nextjs-app-core-browse.md`)**: will be rewritten to reflect this spec. Specifically, the plan needs to add:

- Tailwind theme tokens for the palette above.
- Font loading for IBM Plex Mono / Sans / Serif and VT323.
- Status bar, header, homepage layout, entity-page hero, catalog, threads, command palette, and keyboard-shortcut layers.
- Cytoscape styling hooks for the Obsidian Glow graph language.
- Per-entity-type Tier 1 / Tier 2 detail components.

The plan rewrite is the next step after this spec is approved.

## 13. Deferred to implementation

Decisions intentionally left to the build, to avoid over-committing before code is in the browser:

- Exact Cytoscape layout tuning (fcose iterations, node-repulsion constants, edge length, `concentric` ring radii) — tune visually on real data.
- Whether command palette uses a client-only fuzzy index or round-trips to Neo4j for each keystroke — pick after measuring a warm-loaded palette latency. Corpus and ranking (§3.3) are fixed regardless.
- Precise timeline-ribbon interaction model (pan, zoom, click-to-filter) — prototype first, honoring the temporal semantics in §5.4.
- Specific keyboard-shortcut overlay design — low-stakes, build it last.
- Signature-subgraph builder script details (Python/TypeScript, where it runs, scheduling) — build-layer concern; the JSON contract in §5.5 is fixed.

---

*Primary references: machineryofgovernment.uk (graph restraint), sfgov.civlab.org (product pattern), poetengineer (Obsidian dark aesthetic).*
