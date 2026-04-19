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
| Node: generic | `#e8ecf3` | All other node types (Organization, Meeting, Record, etc.). |

All colored nodes carry a soft `drop-shadow` glow tuned per color (amber: ~5px / 0.7 alpha; blue: ~5px / 0.6; pink: ~5px / 0.6; mint: ~6px / 0.7). The focus node gets a stronger 8px / 0.9 glow.

### 2.3 Typography

Four faces, used with specific intent. Never substitute one for another.

| Face | When | Sample |
|---|---|---|
| **IBM Plex Sans** (400/500/600) | Body copy, entity page prose, card titles, connection card content. | "A county-funded interim shelter approved in November 2025." |
| **IBM Plex Mono** (400/500) | UI chrome, nav, catalog rows, data-explorer tables, section headers, `⌘K` chips, node-level graph labels. | `/project/350-merrydale-interim-shelter` |
| **IBM Plex Serif Italic** (400) | Editorial callouts — a single-paragraph context blurb on Tier 1 entity pages where a human-written note is warranted. Never for primary content. | *"Primary sources: staff reports, agreement packet, LCA amendment."* |
| **VT323** (400) | Status-bar values, hero numerals (amounts, counts), graph captions, big entity-page stat strips, the brand's blinking cursor. Not used for node labels (too small to render legibly). | `$15,337,953` |

**Type scale** (approximate; implementation may fine-tune):

| Role | Face | Size |
|---|---|---|
| Hero page title (entity page) | VT323 | 38–44px |
| Hero meta strip | VT323 | 15–18px |
| Hero big-number stat | VT323 | 28–32px |
| H2 section heading | Plex Sans 500 | 18px |
| Section label ALL CAPS | Plex Mono 500 | 10–11px, `letter-spacing: 0.14em`, uppercase |
| Body | Plex Sans 400 | 13.5–14px, `line-height: 1.55` |
| Data row / table cell | Plex Mono 400 | 12px |
| Graph node label | Plex Mono 400 | 9–10px |
| Graph caption (under signature subgraph) | VT323 | 16px |
| Status-bar value | VT323 | 14px |
| Keyboard chip | Plex Mono 400 | 10px, inside `<kbd>` with border |

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
● CONNECTED · AURADB · NODES 112,431 · EDGES 141,207 · JURISDICTIONS 11 · SYNC 2026-04-14 09:12 PST
```

The right-aligned SYNC timestamp is the most-recent successful ingestion run. If the graph is stale beyond N days (default 14), the dot shifts amber and the status bar grows a "STALE" tag.

### 3.2 Header row

- Left: `OPEN MARIN` brand in VT323 22px + blinking green cursor block.
- Middle: explicit nav — `Home · Graph · Data · Chat · About` — Plex Mono 12px. Active page gets a `#14171d` background and `#262b35` border.
- Right: `open palette ⌘K` chip in Plex Mono 11px.

### 3.3 Prompt-styled search row

Full-width below the header, inside the page grid. Plex Mono placeholder with a VT323 green `>` chevron on the left. Focusing the field or pressing `/` anywhere on the page moves focus here. Typing and pressing `↵` executes a full-text search across all node types.

### 3.4 Left column — Catalog

A single Plex Mono list of node types with counts. Grouped:

- Core: People, Organizations, Decisions, Meetings, Money flows, Filings, Cases, Projects, Committees, Elections, Places, Issues.
- Records subsection: Source records, Evidence links.
- No rank ordering beyond this grouping; counts are authoritative.

Each row is a link to `/browse/{type}`, a filtered list view (part of Data Explorer).

### 3.5 Center column — Signature subgraph

One curated, captioned subgraph rendered with the Obsidian Glow language (see §5). Center position holds `#ffffff` focus node; 1–2 hop neighborhood fans out with type-colored nodes and edges.

Caption block at bottom-left of the graph pane, VT323 16px:

```
$15,337,953 · 6 decisions · 3 counterparties · 20 records
```

Top-right of the graph pane: a quiet Plex Mono kicker `SIGNATURE SUBGRAPH · MERRYDALE`.

The featured subgraph rotates through **5–8 curated threads** on each session load (random selection; no carousel controls). Candidates for the initial rotation:
- 350 Merrydale Interim Shelter (project, $15.3M)
- Sanctioned Camping Program (program, Boyd-constrained)
- Boyd v. City of San Rafael (case, federal)
- Downtown Library Renovation (project, $15M+)
- Kate Colin (person, mayor)
- Resolution 15336 (decision)
- Grants Pass v. Johnson (case)
- Form 803 Kate Colin / PG&E / Canal Alliance (filing + money chain)

Clicking any node **navigates** to the full-screen explorer centered on that node (no on-homepage re-centering). The homepage graph is a museum piece, not a workspace.

### 3.6 Right column — Currently tracking

4–5 thread cards. Each card:

- **Title** — Plex Sans 500, 13px, white (`#e6e8ec`).
- **Meta line** — Plex Mono 10.5px, dim: `project · San Rafael` or `case · federal`.
- **Stat line** — VT323 15px, amber, glowing: `$15.3M · 6 decisions`.

Cards link to the relevant entity page. The thread list is hand-curated (editable via a config file) until we build a thread-definition layer.

## 4. Navigation & IA

### 4.1 Top-level routes

| Path | Destination |
|---|---|
| `/` | Homepage. |
| `/graph` | Full-screen network explorer. |
| `/data` | Data explorer (predefined queries, filtered tables, CSV export). |
| `/chat` | AI chat (deferred per v1 design spec). |
| `/about` | Static page: what is this, how it was built, methodology, source list. |
| `/browse/{type}` | Paginated filtered list of a single node type. |
| `/{type}/{id}` | Entity page (Tier 1 or Tier 2 based on type). |

### 4.2 URL-as-breadcrumb

Routes are path-readable and human-typable. There is **no on-page breadcrumb component** — the browser URL bar is the breadcrumb. Type slugs are kebab-case (`350-merrydale-interim-shelter`, `kate-colin`, `boyd-v-san-rafael`).

### 4.3 Command palette (⌘K)

Power shortcut, not primary navigation. Opens a centered modal with:
- Full-text search across Person / Organization / Decision / Project / Program / Case / Meeting / Filing / Committee / Agreement / Amendment / Record.
- Recent entities (last 10 viewed, session-scoped).
- Quick jumps: `go home`, `go graph`, `go data`, `go chat`.

Escape closes. Return navigates to the selected item.

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

## 5. Graph visual language

Applies consistently to all three graph surfaces.

### 5.1 Nodes

- Rendered as circles with soft drop-shadow glow.
- **Size** encodes node importance within the current view: focus node largest (radius 9–11), primary neighbors medium (6–7), secondary neighbors small (4–5), tertiary dots (3).
- **Color** encodes node type (see palette). Ungrouped node types use generic light gray.
- **Labels** shown for focus node and all 1-hop primary neighbors; hidden by default for 2-hop+ nodes (appear on hover). Labels use Plex Mono 9–10px in `#b0b7c3`.

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

## 6. The three graph surfaces

### 6.1 Homepage signature subgraph

- **Purpose**: tease connectedness, invite exploration.
- **Interaction**: click any node → navigate to `/graph?focus={id}`. No re-center, no hover-expansion.
- **Motion**: subtle drift.
- **Data shape**: pre-curated list of (focus_node_id, 2-hop neighborhood) rendered from a materialized view. Not a live Cypher query; we bake these for performance and quality.

### 6.2 Entity-page radial hero

- **Purpose**: show "this entity is the center of its own story."
- **Interaction**: hover to reveal label, click to re-center (navigates to the clicked entity's page).
- **Layout**: radial / orbital with concentric rings by hop distance (1-hop inner ring, 2-hop outer ring). Cytoscape `concentric` or `cose-bilkent` layout.
- **Data shape**: live Cypher query returning 1–2 hop neighborhood, capped at ~40 nodes to prevent visual overwhelm.

### 6.3 Full-screen explorer (`/graph`)

- **Purpose**: investigation workbench.
- **Layout**: force-directed (Cytoscape `fcose`).
- **Features**: path finding between two entities, subgraph extraction (select nodes → isolate), temporal filter (date slider), edge-type filter, hop limit slider, save view (session-scoped).
- **Interaction**: drag, pan, zoom, lasso-select, right-click for context actions.
- **Data shape**: starts from `?focus={id}` query param or empty state ("type a name or click Signature Subgraphs"); loads incrementally as user expands.

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
10. **Evidence drawer** (expandable, collapsed by default): list of source Record nodes with record type, captured-at, artifact path (display-only — raw files live on the Mac mini and are not accessible from Vercel), and source URL. Clicking a row opens the `source_url` (the original government-hosted document) in a new tab. The Record ID is selectable for citation.

### 7.2 Tier 2 — Organization / Seat / SeatService / Election / Candidacy / AgendaItem / MoneyFlow / Proceeding / Agreement / Amendment / Record / Place / Issue

Simpler composition: status bar + header + kicker + VT323 title + Plex Mono meta + facts panel + connections list + evidence links. No hero graph, no timeline, no editorial callout.

Every entity page shares the same status bar, header, footer, and type-color treatment so navigating between tiers never feels like landing in a different product.

## 8. Data explorer (`/data`)

Dense, terminal-flavored tables. All text Plex Mono 12px. Rows on `#0b0d11` with `#1a1d24` hairline dividers. Hovered row elevates to `#14171d`.

- **Left rail (240px)**: query templates as a list (the 10 predefined queries from v1 design spec §5c). Active template highlighted.
- **Filters row**: horizontal chips below the header. Type-specific filters (date range, amount threshold, jurisdiction, issue).
- **Table**: sortable columns; column header row in Plex Mono 500 uppercase with `letter-spacing: 0.14em`. Amount cells use VT323. Date cells Plex Mono. Click any row → entity page.
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

- Exact Cytoscape layout tuning (fcose iterations, node-repulsion constants, edge length) — tune visually on real data.
- Whether command palette uses a client-only fuzzy index or round-trips to Neo4j for each keystroke — pick after measuring a warm-loaded palette latency.
- Precise timeline-ribbon interaction model (pan, zoom, click-to-filter) — prototype first.
- Whether `⌘K` includes Records in fuzzy matches or only the 11 primary entity types — decide after seeing palette performance.
- Specific keyboard-shortcut overlay design — low-stakes, build it last.

---

*Primary references: machineryofgovernment.uk (graph restraint), sfgov.civlab.org (product pattern), poetengineer (Obsidian dark aesthetic).*
