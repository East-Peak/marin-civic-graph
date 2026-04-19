# Open Marin Frontend — Plan 2: Entity Pages + Slug Routing + Radial Hero

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn every node in the graph into a navigable entity page. Tier 1 pages (Person, Decision, Project, Program, Case, Meeting, Filing, Committee) get hero stats, a radial graph hero (Query 1 + Query 2 per spec §5.1.1), connections, timeline, and an evidence drawer. Tier 2 pages (13 remaining types) share the same shell minus the hero graph. Along the way, address the three Plan 1 deferrals — edge vocabulary reconciliation, richer search properties, and the Record URL registry fallback — that each block something in Plan 2.

**Architecture:**
- Dynamic route `/{type}/{slug}` backed by a single `loadEntity(type, id)` function that runs a per-focus-type Cypher bundle (Query 1 + Query 2 for Tier 1 focus types; a simpler 1-hop neighborhood for Tier 2).
- Shared entity-page layout component composes Tier 1 vs Tier 2 based on focus type.
- A new `edge-vocabulary` module (TypeScript + Python) maps the spec's §3 relationship names (`PART_OF`, `ABOUT_ITEM`, `DISCLOSED_IN`, `AMENDS`, `RESULT_OF`, `UNDER_AGREEMENT`, `ABOUT_PROJECT`, `ABOUT_PROGRAM`, `FOR_PROJECT`, `BY_PERSON`, `IN_ELECTION`, `BETWEEN`, `CONSTRAINS`) to the live AuraDB names. This is the single source of truth consulted by the radial-hero queries, the signature-subgraph builder, and any pathfinding later.
- Radial hero renders with Cytoscape `concentric` layout (three rings: 1-hop primary, 2-hop secondary, Person-only 3-hop institution).
- Timeline ribbon uses §5.4's per-type event-date projection.
- Evidence drawer uses the `preferred_public_url`/`has_public_source`/`preferred_display_artifact` contract from §7.1, upgraded with registry fallback.

**Tech stack:** same as Plan 1 — Next.js 16 + React 19 + TypeScript 5 + Tailwind 4 + Cytoscape + fcose + Vitest. New for Plan 2: `cytoscape-concentric` (built into core cytoscape, no install needed).

**Spec:** `docs/specs/2026-04-19-open-marin-frontend-design.md` (23-round Codex-reviewed). This plan implements §§5.1, 5.1.1, 5.2, 5.4, 6.2, 7.1, 7.2, plus the three deferred ingestion additions.

**Prerequisites:** Plan 1 (foundation + homepage) landed. Repo at `main` branch. `app/.env.local` has real AuraDB creds.

---

## File structure (new or modified)

```
scripts/
  edge_vocabulary.py                        NEW — single-source spec→live edge mapping (Python)
  build_search_properties.py                MODIFY — emit search_key_fact + search_last_activity; recency-weight rank
  build_record_preferred_urls.py            MODIFY — registry fallback for records without source_url
  build_signature_subgraphs.py              MODIFY — consume edge_vocabulary.py instead of hard-coded whitelist
  refresh_openmarin.py                      no change (already sequences everything)

app/src/
  lib/
    edge-vocabulary.ts                      NEW — TypeScript mirror of edge_vocabulary.py
    server/
      entity-loader.ts                      NEW — loadEntity(type, id): builds neighborhood + facts
      entity-queries.ts                     NEW — Query 1 (must-show) + Query 2 (phase-2 fill) Cypher
      entity-temporal.ts                    NEW — §5.4 per-type event-date projection
      entity-facts.ts                       NEW — per-type hero stats + facts-panel key/value rows
  components/
    entity/
      entity-page.tsx                       NEW — shared Tier 1/Tier 2 layout
      hero-title.tsx                        NEW — kicker + VT323 title + meta strip
      hero-stats.tsx                        NEW — Tier 1 only; VT323 big numerals
      radial-hero.tsx                       NEW — Cytoscape concentric layout
      facts-panel.tsx                       NEW — Plex Mono key/value table
      connections.tsx                       NEW — grouped connection cards
      timeline-ribbon.tsx                   NEW — §5.4 temporal strip
      evidence-drawer.tsx                   NEW — expandable records list
      editorial-callout.tsx                 NEW — optional Plex Serif italic blurb
  app/
    [type]/[slug]/page.tsx                  MODIFY — replace ComingSoon with real entity page
  tests/
    lib/edge-vocabulary.test.ts             NEW
    lib/server/entity-loader.test.ts        NEW
    lib/server/entity-queries.test.ts       NEW
    lib/server/entity-temporal.test.ts      NEW
    components/entity/                      NEW — component tests per component

tests/scripts/
  test_edge_vocabulary.py                   NEW
  test_build_search_properties.py           MODIFY — assert new properties
  test_build_record_preferred_urls.py       MODIFY — assert registry fallback
```

---

## Conventions (same as Plan 1)

- Push directly to `main` (workspace policy for this project).
- Commit per task.
- TDD for logic; pragmatic for UI scaffolding.
- Subagent-driven execution, batched by phase.
- `npm run verify` (typecheck + lint + test) before each commit.
- Never `git add -A`; stage explicit paths only.
- Ambient dirty state in `data/extracted/`, `data/raw/`, `data/normalized/`, `data/projected/graph-v2/`, and `docs/specs/2026-04-14-marin-civic-graph-v1-design.md` belongs to another agent — do not touch.

---

## Phase A — Edge-vocabulary reconciliation

The spec's §3 relationship ontology uses clean names (`PART_OF`, `ABOUT_ITEM`, `DISCLOSED_IN`, `AMENDS`, `RESULT_OF`, `UNDER_AGREEMENT`, `ABOUT_PROJECT`, `ABOUT_PROGRAM`, `FOR_PROJECT`, `BY_PERSON`, `IN_ELECTION`, `BETWEEN`, `CONSTRAINS`). The live projection uses denormalized variants (`PART_OF_MEETING`, `PART_OF_CASE`, `ABOUT_AGENDA_ITEM`, `DISCLOSED_IN_FILING`, `AMENDS_AGREEMENT`, `RESULT_OF_ELECTION`, and a `RELATES_TO_*` family not in the spec at all). Without reconciliation, Plan 2's radial-hero Cypher will hit the same empty-bundle failures the signature-subgraph builder hit in Plan 1.

### Task 1: Discover + document the live edge catalog

**Files:**
- Create: `docs/reference/2026-04-19-live-edge-catalog.md`

- [ ] **Step 1: Query AuraDB for the full relationship type list.**

```bash
export NEO4J_URI=neo4j+s://<INSTANCE-ID>.databases.neo4j.io NEO4J_USER=neo4j NEO4J_PASSWORD=<pwd> NEO4J_DATABASE=neo4j
python3.14 -c "
from neo4j import GraphDatabase
import os
with GraphDatabase.driver(os.environ['NEO4J_URI'], auth=(os.environ['NEO4J_USER'], os.environ['NEO4J_PASSWORD'])) as d:
    with d.session() as s:
        for r in s.run('CALL db.relationshipTypes()'): print(r['relationshipType'])
"
```

- [ ] **Step 2: For each live relationship type, query a sample to identify source/target labels.**

```python
# For each rel type, run:
# MATCH (a)-[r:REL_TYPE]->(b) RETURN labels(a) AS src_labels, labels(b) AS tgt_labels LIMIT 5
```

- [ ] **Step 3: Write `docs/reference/2026-04-19-live-edge-catalog.md`** with a table: live rel type | source labels (common) | target labels (common) | spec §3 equivalent | notes.

For each spec §3 name, identify:
- Exact match (e.g., `CAST_VOTE` → `CAST_VOTE`)
- Split by target type (e.g., `PART_OF` → `PART_OF_MEETING` | `PART_OF_CASE`)
- Collapsed weak family (e.g., `ABOUT_PROJECT` / `ABOUT_PROGRAM` probably → `RELATES_TO_PROJECT` / `RELATES_TO_PROGRAM`)
- Missing (e.g., `UNDER_AGREEMENT` may not exist at all)

- [ ] **Step 4: Commit.**

```
docs: live-edge catalog for Plan 2 vocabulary reconciliation

Queries the live AuraDB for all 65 relationship types and maps them against the spec §3 ontology. Foundation for scripts/edge_vocabulary.py and app/src/lib/edge-vocabulary.ts.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

### Task 2: Write `scripts/edge_vocabulary.py` (single source of truth, Python side)

**Files:**
- Create: `scripts/edge_vocabulary.py`
- Create: `tests/scripts/test_edge_vocabulary.py`

TDD.

- [ ] **Step 1: Failing test.**

```python
# tests/scripts/test_edge_vocabulary.py
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from edge_vocabulary import (
    spec_to_live,
    PHASE2_WHITELIST_LIVE,
    MONEY_EDGES_LIVE,
    LEGAL_EDGES_LIVE,
    UNIVERSAL_EDGES_LIVE,
)


def test_spec_to_live_simple():
    # CAST_VOTE is unchanged
    assert "CAST_VOTE" in spec_to_live("CAST_VOTE")


def test_spec_to_live_split():
    # PART_OF → PART_OF_MEETING + PART_OF_CASE
    live = spec_to_live("PART_OF")
    assert "PART_OF_MEETING" in live
    assert "PART_OF_CASE" in live


def test_spec_to_live_renamed():
    # ABOUT_ITEM → ABOUT_AGENDA_ITEM
    assert "ABOUT_AGENDA_ITEM" in spec_to_live("ABOUT_ITEM")


def test_phase2_whitelist_is_live_names():
    # All entries should be real AuraDB names
    for edge in PHASE2_WHITELIST_LIVE:
        assert "_" in edge or edge.isupper()
    # No spec §3 aliases
    assert "ABOUT_ITEM" not in PHASE2_WHITELIST_LIVE
    assert "DISCLOSED_IN" not in PHASE2_WHITELIST_LIVE


def test_universal_edges_excluded():
    # EVIDENCED_BY, IN_JURISDICTION, RELATES_TO_ISSUE stay excluded from Phase 2
    for edge in UNIVERSAL_EDGES_LIVE:
        assert edge not in PHASE2_WHITELIST_LIVE
```

- [ ] **Step 2: Run → expect failure.**

- [ ] **Step 3: Implement `scripts/edge_vocabulary.py`.**

Build the mapping from the live-edge catalog produced in Task 1. Structure:

```python
# scripts/edge_vocabulary.py
"""
Spec §3 edge name → live AuraDB edge name(s) mapping.
Used by signature-subgraph builder, entity-loader Cypher queries, and pathfinding.

Live names come from the current graph projection; spec names come from
docs/specs/2026-04-19-open-marin-frontend-design.md §3 (referencing v1 §3 ontology).

Discrepancies (spec → live):
- PART_OF        → PART_OF_MEETING, PART_OF_CASE   (split by target type)
- ABOUT_ITEM     → ABOUT_AGENDA_ITEM                 (renamed)
- DISCLOSED_IN   → DISCLOSED_IN_FILING               (renamed)
- AMENDS         → AMENDS_AGREEMENT                  (renamed)
- RESULT_OF      → RESULT_OF_ELECTION                (renamed)
- ABOUT_PROJECT  → RELATES_TO_PROJECT                (weak variant)
- ABOUT_PROGRAM  → RELATES_TO_PROGRAM                (weak variant)
- IN_ELECTION    → FILED_FOR_ELECTION                (renamed)
- FOR_PROJECT    → RELATES_TO_PROJECT                (no direct; collapses)
- UNDER_AGREEMENT → RELATES_TO_AGREEMENT             (no direct; collapses)
- BETWEEN        → COUNTERPARTY_ACTOR                (split between committee/agreement contexts; see catalog)
- BY_PERSON      → CANDIDATE_ACTOR                   (for Candidacy→Person; different from CAST_VOTE)
- CONSTRAINS     → (not present in current graph; leave as CONSTRAINS placeholder)

Fill in exact mappings from the live-edge catalog (Task 1 output). If a spec
edge has no live equivalent, its entry is an empty list — queries referencing
it will match nothing in the current graph, which is the correct behavior.
"""
from __future__ import annotations

SPEC_TO_LIVE: dict[str, list[str]] = {
    # Governance
    "CAST_VOTE": ["CAST_VOTE"],
    "AT_MEETING": ["AT_MEETING"],
    "ABOUT_ITEM": ["ABOUT_AGENDA_ITEM"],
    "DECIDED_BY": ["DECIDED_BY"],
    "PART_OF": ["PART_OF_MEETING", "PART_OF_CASE"],
    "HELD_BY": ["HELD_BY"],
    "FOR_SEAT": ["FOR_SEAT"],
    "RESULT_OF": ["RESULT_OF_ELECTION"],
    "AT_INSTITUTION": ["AT_INSTITUTION"],
    # Money
    "FROM_SOURCE": ["FROM_SOURCE"],
    "TO_TARGET": ["TO_TARGET"],
    "DISCLOSED_IN": ["DISCLOSED_IN_FILING"],
    "UNDER_AGREEMENT": ["RELATES_TO_AGREEMENT"],  # TODO verify in catalog
    "AMENDS": ["AMENDS_AGREEMENT"],
    # Committee / filing
    "CONTROLLED_BY": ["CONTROLLED_BY", "CONTROLLED_BY_COMMITTEE"],
    "FILED_BY": ["FILED_BY", "FILED_BY_COMMITTEE"],
    "BY_PERSON": ["CANDIDATE_ACTOR"],  # TODO verify
    "IN_ELECTION": ["FILED_FOR_ELECTION", "RELATED_TO_ELECTION"],
    "FOR_ELECTION": ["FOR_ELECTION"],
    # Projects / programs / agreements
    "FOR_PROJECT": ["RELATES_TO_PROJECT"],
    "ABOUT_PROJECT": ["RELATES_TO_PROJECT"],
    "ABOUT_PROGRAM": ["RELATES_TO_PROGRAM"],
    "BETWEEN": ["COUNTERPARTY_ACTOR"],
    # Legal
    "PARTY_TO": ["PARTY_TO"],
    "CONSTRAINS": [],  # not yet materialized in live graph
    "HEARD_IN": ["HEARD_IN", "HEARD_BY"],
}

UNIVERSAL_EDGES_SPEC = ["EVIDENCED_BY", "IN_JURISDICTION", "RELATES_TO_ISSUE"]
UNIVERSAL_EDGES_LIVE = [
    "EVIDENCED_BY",
    "IN_JURISDICTION",
    "RELATES_TO_ISSUE",
    # The RELATES_TO_* family is universal-like in the live graph — too weak
    # for default traversal. Added here so they're excluded from PHASE2_WHITELIST_LIVE.
    "RELATES_TO_ACTOR",
    "RELATES_TO_AGENDA_ITEM",
    "RELATES_TO_AMENDMENT",
    "RELATES_TO_CASE",
    "RELATES_TO_COMMITTEE",
    "RELATES_TO_DECISION",
    "RELATES_TO_ELECTION",
    "RELATES_TO_FILING",
    "RELATES_TO_INSTITUTION",
    "RELATES_TO_MEETING",
    "RELATES_TO_MONEY_FLOW",
    "RELATES_TO_PLACE",
    "RELATES_TO_RECORD",
    "RELATES_TO_SEAT",
    # Note: RELATES_TO_PROJECT, RELATES_TO_PROGRAM, and RELATES_TO_AGREEMENT
    # are kept in PHASE2_WHITELIST_LIVE because they're the *only* live variant
    # of the spec's FOR_PROJECT / ABOUT_PROJECT / ABOUT_PROGRAM / UNDER_AGREEMENT.
]

MONEY_EDGES_LIVE = sorted({
    e for spec in ("FROM_SOURCE", "TO_TARGET", "DISCLOSED_IN", "UNDER_AGREEMENT")
    for e in SPEC_TO_LIVE[spec]
})

LEGAL_EDGES_LIVE = sorted({e for spec in ("CONSTRAINS",) for e in SPEC_TO_LIVE[spec]})


def spec_to_live(spec_edge: str) -> list[str]:
    """Return live AuraDB edge names for a spec §3 edge name."""
    return SPEC_TO_LIVE.get(spec_edge, [])


# Phase-2 whitelist in live names — what the radial hero + signature-subgraph
# builder should traverse. Derived from the spec whitelist minus universals.
_PHASE2_SPEC = [
    "CAST_VOTE", "AT_MEETING", "ABOUT_ITEM", "DECIDED_BY", "PART_OF", "HELD_BY",
    "FOR_SEAT", "RESULT_OF", "AT_INSTITUTION", "FROM_SOURCE", "TO_TARGET",
    "DISCLOSED_IN", "UNDER_AGREEMENT", "AMENDS", "CONTROLLED_BY", "FILED_BY",
    "BY_PERSON", "IN_ELECTION", "FOR_ELECTION", "FOR_PROJECT", "ABOUT_PROJECT",
    "ABOUT_PROGRAM", "PARTY_TO", "CONSTRAINS", "BETWEEN", "HEARD_IN",
]

PHASE2_WHITELIST_LIVE = sorted({
    live
    for spec in _PHASE2_SPEC
    for live in SPEC_TO_LIVE[spec]
    if live not in UNIVERSAL_EDGES_LIVE
})

# Also include the two "ABOUT_PROJECT/PROGRAM" variants that are legitimate
# content edges even though they share the RELATES_TO_* naming:
for _extra in ("RELATES_TO_PROJECT", "RELATES_TO_PROGRAM", "RELATES_TO_AGREEMENT"):
    if _extra not in PHASE2_WHITELIST_LIVE:
        PHASE2_WHITELIST_LIVE.append(_extra)
PHASE2_WHITELIST_LIVE.sort()
```

*(The mapping above is a best-effort starting point — Task 1's catalog will confirm the exact live names; correct them here before committing.)*

- [ ] **Step 4: Run tests → expect pass.**

```bash
python3.14 -m pytest tests/scripts/test_edge_vocabulary.py -v
```

- [ ] **Step 5: Commit.**

```
add scripts/edge_vocabulary.py — single source for spec→live edge mapping

Reconciles spec §3 edge names (PART_OF, ABOUT_ITEM, DISCLOSED_IN, AMENDS, RESULT_OF, etc.) with live AuraDB relationship names (PART_OF_MEETING, PART_OF_CASE, ABOUT_AGENDA_ITEM, DISCLOSED_IN_FILING, AMENDS_AGREEMENT, RESULT_OF_ELECTION, etc.). Addresses Codex round 1 deferred item — radial-hero Cypher needs real edge names to traverse the graph.

PHASE2_WHITELIST_LIVE is derived from the spec whitelist minus universal/structural edges. Signature-subgraph builder and (soon) entity-loader consume this.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

### Task 3: Apply edge vocabulary to `build_signature_subgraphs.py` + regenerate

**Files:**
- Modify: `scripts/build_signature_subgraphs.py`

- [ ] **Step 1:** Replace the hard-coded `PHASE2_WHITELIST` in `build_signature_subgraphs.py` with `from edge_vocabulary import PHASE2_WHITELIST_LIVE as PHASE2_WHITELIST`.

- [ ] **Step 2:** Also replace `MONEY_EDGES`, `LEGAL_EDGES` with the live equivalents.

- [ ] **Step 3:** Run `python3.14 scripts/refresh_openmarin.py` to regenerate all bundles.

Expected: the four previously-empty bundles (Merrydale, Sanctioned Camping, Downtown Library, Form 803) now have real content. Kate Colin / Boyd / Resolution 15336 / Grants Pass continue to build cleanly.

- [ ] **Step 4:** Inspect each bundle's node count. If any still < 2 nodes, add its specific edge names to `edge_vocabulary.py` based on what the focus entity actually has in the graph.

```bash
for f in data/projected/graph-v1/signature-subgraphs/*.json; do
  echo "$f: $(python3.14 -c "import json; print(len(json.load(open('$f'))['nodes']))")"
done
```

- [ ] **Step 5: Commit once all 8 bundles have ≥ 2 nodes.**

```
apply edge_vocabulary to signature-subgraph builder + regenerate

The 4 previously-empty bundles (Merrydale, Sanctioned Camping, Downtown Library, Form 803) now build with real content because the Phase-2 whitelist uses live AuraDB edge names instead of spec §3 aliases. Manifest grows from 4 to 8 active slugs.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

---

## Phase B — Richer search properties

### Task 4: Add `search_key_fact` + `search_last_activity` to `build_search_properties.py`

**Files:**
- Modify: `scripts/build_search_properties.py`
- Modify: `tests/scripts/test_build_search_properties.py`

- [ ] **Step 1: Update tests to assert new properties exist for each type.**

```python
def test_key_fact_person_is_current_role():
    props = {
        "id": "person-kate-colin",
        "name": "Kate Colin",
        "current_seat_display": "Mayor, San Rafael",
        "current_seat_start": "2024",
    }
    assert build_search_key_fact("Person", props) == "Mayor, San Rafael · 2024–"


def test_key_fact_decision_is_subject_date():
    props = {"id": "decision-2024-08-19-resolution-15336", "title": "Resolution 15336", "decided_at": "2024-08-19"}
    assert build_search_key_fact("Decision", props) == "Resolution 15336 · 2024-08-19"


def test_last_activity_person_is_latest_linked_event():
    # Person with filings [2024-03-01, 2024-11-15] and decisions [2024-09-12]
    # → latest is 2024-11-15
    props = {
        "id": "person-kate-colin",
        "_linked_event_dates": ["2024-03-01", "2024-11-15", "2024-09-12"],
    }
    assert build_search_last_activity("Person", props) == "2024-11-15"


def test_search_rank_recency_weighted():
    # Same degree, different recency — the more recent one ranks higher
    recent = {"id": "person-a", "degree": 50, "_last_activity": "2026-01-01"}
    old = {"id": "person-b", "degree": 50, "_last_activity": "2020-01-01"}
    assert compute_search_rank("Person", recent) > compute_search_rank("Person", old)
```

- [ ] **Step 2: Implement the new builders.**

Add `build_search_key_fact(type, props)` and `build_search_last_activity(type, props)` helpers. Extend `compute_search_rank` to include a recency component.

The tricky part is that `props` needs to carry linked-event dates per node — a second pass of Cypher. Options:
- (a) Load linked dates in the main Cypher (one pass with `collect()` and `max()`).
- (b) Separate pass per type.

Go with (a). The main per-type query becomes:

```python
def fetch_nodes_with_activity(session, type_name: str):
    # Collect each node's out-neighborhood dates.
    date_fields = {
        "Person": ["filing_signed_at", "decision_decided_at", "moneyflow_flow_date"],
        ...
    }
    query = f"""
    MATCH (n:{type_name})
    OPTIONAL MATCH (n)-[]-(e)
    WHERE e:Filing OR e:Decision OR e:MoneyFlow OR e:Meeting OR e:Proceeding
    WITH n, collect(DISTINCT coalesce(e.signed_at, e.decided_at, e.flow_date, e.meeting_date, e.date)) AS dates
    RETURN n, [d IN dates WHERE d IS NOT NULL] AS linked_dates
    """
    ...
```

Compute `search_last_activity = max(linked_dates)` at Python level. Recency weighting:

```python
def compute_search_rank(type_name, props):
    degree = int(props.get("degree", 0) or 0)
    degree_component = min(25, int(20 * math.log1p(degree) / math.log(1000))) if degree > 0 else 0
    last_activity = props.get("_last_activity") or props.get("search_last_activity")
    recency_component = 0
    if last_activity:
        try:
            days_ago = (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(last_activity).replace(tzinfo=dt.timezone.utc)).days
            # 0 to 25 points, decaying linearly over 3 years (1095 days)
            recency_component = max(0, 25 - int(25 * days_ago / 1095))
        except (ValueError, TypeError):
            pass
    base = 50 + degree_component + recency_component + TYPE_WEIGHT.get(type_name, 0)
    if type_name == "Record":
        return max(0, min(30, degree_component + 10))
    return max(0, min(100, base))
```

- [ ] **Step 3: Run unit tests → pass.**

- [ ] **Step 4: Run against AuraDB.**

```bash
python3.14 scripts/refresh_openmarin.py
```

- [ ] **Step 5: Verify in AuraDB console.**

```cypher
MATCH (n:Person {id: "person-kate-colin"})
RETURN n.search_label, n.search_key_fact, n.search_last_activity, n.search_rank;
```

Expect non-null `search_key_fact` and `search_last_activity`; `search_rank` should reflect recency.

- [ ] **Step 6: Commit.**

```
add search_key_fact + search_last_activity; recency-weight search_rank

Spec §3.3 authoritative response shape calls for these fields. Previously only search_label/search_terms/search_rank were computed. Now every indexed entity also carries:
- search_key_fact: short type-specific description (current role, decision subject+date, etc.)
- search_last_activity: latest ISO date from linked events
- search_rank: now includes up to 25 points of recency weighting (decays linearly over 3 years)

Addresses Codex round 1 deferred item #5.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

### Task 5: Update `/api/search` response to surface new fields

**Files:**
- Modify: `app/src/app/api/search/route.ts`
- Modify: `app/src/tests/api/search.test.ts`

- [ ] **Step 1:** Update the `nodeToResult` mapper to read `search_key_fact` and `search_last_activity` from node properties (they're now real, not `null`).

```typescript
function nodeToResult(node: Neo4jNode): SearchResult {
  const props = node.properties;
  ...
  return {
    ...
    key_fact: (props.search_key_fact as string) ?? null,
    last_activity: (props.search_last_activity as string) ?? null,
    ...
  };
}
```

*(The code already reads these — this task just verifies they actually show up in live responses.)*

- [ ] **Step 2:** Hit `/api/search?q=kate+colin` locally and confirm the response includes non-null `key_fact` and `last_activity`.

- [ ] **Step 3:** If anything is still null, trace back to Task 4 and fix the ingestion.

- [ ] **Step 4:** If the search test mock needs updating (to reflect the new expected shape), update it. Otherwise no commit needed — this is verification.

---

## Phase C — Record URL registry fallback

### Task 6: Extend `build_record_preferred_urls.py` with jurisdiction-source-registry fallback

**Files:**
- Modify: `scripts/build_record_preferred_urls.py`
- Modify: `tests/scripts/test_build_record_preferred_urls.py`

Per spec §7.1: if `source_url` is missing or non-http(s), derive a canonical upstream URL from `registry/*-sources.yaml` based on the Record's parent context (jurisdiction, record_type).

- [ ] **Step 1: Write failing tests.**

```python
def test_registry_fallback_for_meeting_minutes(tmp_path):
    # Record is a Meeting-child with no source_url but a parent Meeting
    # in a jurisdiction whose registry has a known base URL.
    registry_load = {...}  # mocked source registry
    props = {
        "id": "record-foo-minutes",
        "source_url": None,
        "record_type": "minutes",
        "parent_jurisdiction": "san-rafael",
        "parent_meeting_date": "2024-08-19",
    }
    url = normalize_public_url_with_registry(props, registry_load)
    assert url is not None
    assert url.startswith("https://")
```

- [ ] **Step 2: Implement.**

Load the YAML registries (`registry/granicus-sources.yaml`, `civicplus-sources.yaml`, etc.) once. For Records without a usable `source_url`, look up the parent jurisdiction + record_type and synthesize a URL from the registry's base pattern.

- [ ] **Step 3: Run against AuraDB.**

- [ ] **Step 4: Commit.**

```
add registry-based Record URL fallback

Spec §7.1 requires preferred_public_url to fall back on the jurisdiction source registry when a Record has no explicit source_url or a non-http scheme. Loads registry/*-sources.yaml once and synthesizes canonical upstream URLs from jurisdiction + record_type. Addresses Codex round 1 deferred item #7.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

---

## Phase D — Routing foundations

### Task 7: Write `app/src/lib/edge-vocabulary.ts` (TypeScript mirror)

**Files:**
- Create: `app/src/lib/edge-vocabulary.ts`
- Create: `app/src/tests/lib/edge-vocabulary.test.ts`

TDD, mirroring the Python module from Task 2. Same constants, same `specToLive()` function. Tests assert parity with Python (hardcode the expected mapping).

- [ ] **Step 1: Failing test.**

```typescript
import { specToLive, PHASE2_WHITELIST_LIVE, UNIVERSAL_EDGES_LIVE } from "@/lib/edge-vocabulary";

describe("edge-vocabulary", () => {
  it("PART_OF resolves to both PART_OF_MEETING and PART_OF_CASE", () => {
    expect(specToLive("PART_OF")).toEqual(expect.arrayContaining(["PART_OF_MEETING", "PART_OF_CASE"]));
  });

  it("ABOUT_ITEM resolves to ABOUT_AGENDA_ITEM", () => {
    expect(specToLive("ABOUT_ITEM")).toContain("ABOUT_AGENDA_ITEM");
  });

  it("PHASE2_WHITELIST_LIVE excludes universal edges", () => {
    for (const universal of UNIVERSAL_EDGES_LIVE) {
      expect(PHASE2_WHITELIST_LIVE).not.toContain(universal);
    }
  });

  it("PHASE2_WHITELIST_LIVE has no spec-only names", () => {
    for (const specName of ["ABOUT_ITEM", "DISCLOSED_IN", "PART_OF"]) {
      expect(PHASE2_WHITELIST_LIVE).not.toContain(specName);
    }
  });
});
```

- [ ] **Step 2: Implement** by transcribing the Python module to TypeScript. The data must match exactly — update both in lockstep.

- [ ] **Step 3: Run tests → pass. Commit.**

```
add app/src/lib/edge-vocabulary.ts — TS mirror of scripts/edge_vocabulary.py

Identical mapping. Any change must be made to both.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

### Task 8: Write Cypher query helpers — `entity-queries.ts`

**Files:**
- Create: `app/src/lib/server/entity-queries.ts`
- Create: `app/src/tests/lib/server/entity-queries.test.ts`

These helpers build the Query 1 (must-show) and Query 2 (Phase-2 fill) parameterized Cypher strings per spec §5.1.1. Pure string builders — no Neo4j calls.

- [ ] **Step 1: Failing tests.**

```typescript
describe("entity-queries", () => {
  it("buildMustShowQuery(Person) returns Cypher including SeatService/Seat/Committee/Case traversals", () => {
    const q = buildMustShowQuery("Person");
    expect(q).toContain("HELD_BY");
    expect(q).toContain("FOR_SEAT");
    expect(q).toContain("PARTY_TO");
    expect(q).toContain("CONTROLLED_BY");
    expect(q).toContain("AT_INSTITUTION"); // 3-hop institution path
  });

  it("buildPhase2FillQuery includes per-type sub-queries with LIMIT", () => {
    const q = buildPhase2FillQuery("Person");
    expect(q).toContain("UNION ALL");
    expect(q).toContain("LIMIT 8"); // MoneyFlow quota
    expect(q).toContain("LIMIT 6"); // Person quota
    expect(q).toContain("c.id <> $focus_id");
  });

  it("phase-2 whitelist comes from edge-vocabulary module", () => {
    const q = buildPhase2FillQuery("Project");
    // Spec §3 names not present; live names present
    expect(q).not.toContain(":ABOUT_ITEM|");
    expect(q).toContain("ABOUT_AGENDA_ITEM");
  });
});
```

- [ ] **Step 2: Implement** `buildMustShowQuery(focusType)` and `buildPhase2FillQuery(focusType)` per §5.1.1. Each returns a Cypher string template plus a `params` spec (what parameters to pass at execution time).

For `buildMustShowQuery`, implement the per-focus-type table from spec §5.1.1:

| focus | must-show traversals |
|---|---|
| Person | current SeatService via `HELD_BY`; SeatService's Seat via `FOR_SEAT`; Committee via `CONTROLLED_BY`; Candidacy via `BY_PERSON`; Case via `PARTY_TO`; Seat's Organization via 3-hop HELD_BY → FOR_SEAT → AT_INSTITUTION |
| Decision | Meeting via `AT_MEETING`; AgendaItem via `ABOUT_ITEM`; Organization via `DECIDED_BY`; Persons via `CAST_VOTE`; Project via `ABOUT_PROJECT`; Program via `ABOUT_PROGRAM`; Case via inverse `CONSTRAINS` |
| Project | Agreement via inverse `FOR_PROJECT`; Amendment via inverse `AMENDS`; Decision via inverse `ABOUT_PROJECT`; Program via 2-hop through Decision |
| Program | Decision via inverse `ABOUT_PROGRAM`; Project via 2-hop; Case via 2-hop through CONSTRAINS |
| Case | Proceeding via inverse `PART_OF`; Organization:Court via `HEARD_IN`; Persons/Orgs via inverse `PARTY_TO`; Decision via `CONSTRAINS` |
| Meeting | Organization:Government via `AT_INSTITUTION`; AgendaItem via inverse `PART_OF`; Decision via inverse `AT_MEETING` |
| Filing | Person or Committee via `FILED_BY`; Election via `FOR_ELECTION`; MoneyFlow via inverse `DISCLOSED_IN` |
| Committee | Person via `CONTROLLED_BY`; Filing via inverse `FILED_BY` |

For `buildPhase2FillQuery`, implement the quota table from §5.1.1:
- MoneyFlow 8, Decision 8, Filing 6, Meeting 6, Person 6, Organization 4, AgendaItem 4, Amendment 2, Proceeding 4, Election 2, Candidacy 2 — no Record (excluded).

Use the edge-vocabulary module's `PHASE2_WHITELIST_LIVE` when building the relationship-type list.

- [ ] **Step 3: Run tests → pass. Commit.**

```
add entity-queries: build Cypher for must-show + Phase-2 fill per §5.1.1

Per-focus-type must-show traversals (Person / Decision / Project / Program / Case / Meeting / Filing / Committee) and the 11-type Phase-2 quota-fill query. Uses edge-vocabulary for live edge names. Pure string builders — no Neo4j calls.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

### Task 9: Write `entity-loader.ts` and replace stub `[type]/[slug]/page.tsx`

**Files:**
- Create: `app/src/lib/server/entity-loader.ts`
- Create: `app/src/lib/server/entity-temporal.ts` (extracted helper)
- Create: `app/src/lib/server/entity-facts.ts` (extracted helper)
- Create: `app/src/tests/lib/server/entity-loader.test.ts`
- Modify: `app/src/app/[type]/[slug]/page.tsx` — replace ComingSoon stub

- [ ] **Step 1: Design the loader.**

```typescript
// app/src/lib/server/entity-loader.ts
import "server-only";
import { runQuery } from "@/lib/neo4j";
import { buildMustShowQuery, buildPhase2FillQuery } from "./entity-queries";
import { canonicalType, type NodeType } from "@/lib/canonical-type";
import { resolveIdAlias } from "@/lib/id-aliases";

export type EntityNeighbor = {
  id: string;
  type: NodeType;
  label: string;
  route: string;
  ring: 1 | 2 | 3;
  role: "must-show" | "phase-2";
  rank_value: number | null;
};

export type EntityEdge = {
  source: string;
  target: string;
  type: string;
  style: "governance" | "money" | "legal-constrains";
};

export type EntityPayload = {
  id: string;
  type: NodeType;
  properties: Record<string, unknown>;
  label: string;
  neighbors: EntityNeighbor[];
  edges: EntityEdge[];
  /** Total non-Place, non-Issue neighbors reachable at ≤ 2 hops, for the overflow footer. */
  neighbor_total: number;
};

const TIER_1_FOCUS_TYPES: NodeType[] = [
  "Person", "Decision", "Project", "Program", "Case", "Meeting", "Filing", "Committee",
];

export async function loadEntity(typeSegment: string, slug: string): Promise<EntityPayload | null> {
  // Resolve to canonical id
  const resolved = resolveIdAlias(`${typeSegment}-${slug}`.replace("seat-service-", "seatservice-"));
  if (!resolved) return null;
  const { id, type } = resolved;

  // 1. Load focus node
  const focusRecords = await runQuery(
    "MATCH (n {id: $id}) RETURN n LIMIT 1",
    { id },
  );
  if (focusRecords.length === 0) return null;
  const focusNode = focusRecords[0].get("n");

  const isTier1 = TIER_1_FOCUS_TYPES.includes(type);

  let mustShow: EntityNeighbor[] = [];
  let phase2: EntityNeighbor[] = [];
  let neighborhoodEdges: EntityEdge[] = [];
  let neighborTotal = 0;

  if (isTier1) {
    mustShow = await runMustShowQuery(type, id);
    const mustShowIds = mustShow.map((n) => n.id);
    phase2 = await runPhase2FillQuery(type, id, mustShowIds, 40 - mustShow.length);
    const selectedIds = new Set([id, ...mustShow.map((n) => n.id), ...phase2.map((n) => n.id)]);
    neighborhoodEdges = await runEdgesAmongSelectedQuery(Array.from(selectedIds));
    neighborTotal = await runNeighborhoodCountQuery(id);
  } else {
    // Tier 2 — simpler 1-hop neighborhood along Phase-2 whitelist
    const neighbors = await runTier2NeighborhoodQuery(id);
    phase2 = neighbors;
    const selectedIds = new Set([id, ...neighbors.map((n) => n.id)]);
    neighborhoodEdges = await runEdgesAmongSelectedQuery(Array.from(selectedIds));
    neighborTotal = await runNeighborhoodCountQuery(id);
  }

  return {
    id,
    type,
    properties: Object.fromEntries(Object.entries(focusNode.properties).map(([k, v]) => [k, v])),
    label: String(focusNode.properties.search_label ?? id),
    neighbors: [...mustShow, ...phase2],
    edges: neighborhoodEdges,
    neighbor_total: neighborTotal,
  };
}

// … runMustShowQuery / runPhase2FillQuery / runEdgesAmongSelectedQuery /
// runNeighborhoodCountQuery / runTier2NeighborhoodQuery implementations …
```

- [ ] **Step 2: Write tests for `loadEntity`.**

Mock `runQuery` and assert:
- `loadEntity("person", "kate-colin")` returns `{ id: "person-kate-colin", type: "Person", ...}`.
- `loadEntity("nonexistent", "xyz")` returns `null`.
- Tier 1 types trigger both must-show and phase-2 queries; Tier 2 types only trigger 1-hop.
- Edge classification uses `classifyEdgeStyle` from Plan 1's signature-subgraph logic (extract to shared module if needed).

- [ ] **Step 3: Implement supporting queries.**

For each helper (`runMustShowQuery`, `runPhase2FillQuery`, etc.), build the Cypher using `buildMustShowQuery(type)` / `buildPhase2FillQuery(type)` and parse the result into the typed shape. Handle the 500ms timeout circuit-breaker from §5.1.1 (if Phase 2 exceeds timeout, return must-show only with overflow footer).

- [ ] **Step 4: Replace `[type]/[slug]/page.tsx`.**

```tsx
// app/src/app/[type]/[slug]/page.tsx
import { notFound } from "next/navigation";
import { loadEntity } from "@/lib/server/entity-loader";
import { EntityPage } from "@/components/entity/entity-page";

export const dynamic = "force-dynamic";

export default async function EntityPageRoute({
  params,
}: {
  params: Promise<{ type: string; slug: string }>;
}) {
  const { type, slug } = await params;
  const entity = await loadEntity(type, slug);
  if (!entity) notFound();
  return <EntityPage entity={entity} />;
}
```

- [ ] **Step 5: Temporary EntityPage stub.**

Until Phase E implements the real `EntityPage`, have it render:

```tsx
// app/src/components/entity/entity-page.tsx
import type { EntityPayload } from "@/lib/server/entity-loader";

export function EntityPage({ entity }: { entity: EntityPayload }) {
  return (
    <div className="min-h-screen bg-bg p-8 font-mono text-body">
      <pre>{JSON.stringify(entity, null, 2)}</pre>
    </div>
  );
}
```

This proves the route + loader work before we wire the real UI.

- [ ] **Step 6: Smoke test** — visit http://localhost:3100/person/kate-colin, http://localhost:3100/decision/2024-08-19-resolution-15336, http://localhost:3100/case/boyd-v-city-of-san-rafael.

Expect a JSON dump of the focus node + neighbors + edges. If the loader errors, diagnose before committing.

- [ ] **Step 7: Commit.**

```
add entity-loader + [type]/[slug] route (JSON-dump placeholder UI)

Wires the Phase-D foundation: /{type}/{slug} → loadEntity(type, slug) runs Query 1 (must-show) + Query 2 (Phase-2 fill) for Tier 1 focus types, or a 1-hop neighborhood for Tier 2. EntityPage component is a placeholder JSON dump until Phase E/F implement the real UI.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

---

## Phase E — Tier 2 entity page shell (7 tasks)

Phase E builds the shared shell used by all 21 entity types. Tier 1 pages add the radial hero + hero stats + timeline in Phase F; Tier 2 pages render the shell alone.

### Task 10: `entity-page.tsx` — shared layout composer

**Files:**
- Modify: `app/src/components/entity/entity-page.tsx`

Composes: StatusBar → NavHeader → HeroTitle → (HeroStats if Tier 1) → grid of (RadialHero if Tier 1, else nothing) + FactsPanel → Connections → (TimelineRibbon if Tier 1) → EditorialCallout (optional) → EvidenceDrawer. Pass the focus `entity` through.

No tests for the layout itself; tests live on each child component.

### Task 11: `hero-title.tsx` — Plex Mono kicker + VT323 title + meta strip

**Files:**
- Create: `app/src/components/entity/hero-title.tsx`
- Create: `app/src/tests/components/entity/hero-title.test.tsx`

Per spec §7.1 item 3 + §2.3 authoritative type scale.

### Task 12: `facts-panel.tsx` — Plex Mono key/value

**Files:**
- Create: `app/src/components/entity/facts-panel.tsx`
- Create: `app/src/lib/server/entity-facts.ts` — per-type fact field definitions
- Create: tests

Each type has its own fact-field list (spec §7.1 item 6 + spec §7.2). Extract into a pure module so tests can exercise it without rendering.

Example:

```typescript
// app/src/lib/server/entity-facts.ts
import type { NodeType } from "@/lib/type-display";

export type FactRow = { key: string; value: string | null };

export function factsForEntity(type: NodeType, props: Record<string, unknown>): FactRow[] {
  switch (type) {
    case "Person":
      return [
        { key: "Name", value: s(props.name) },
        { key: "Current seat", value: s(props.current_seat_display) },
        { key: "Jurisdiction", value: s(props.jurisdiction_name) },
        { key: "Aliases", value: asList(props.aliases) },
      ];
    case "Decision":
      return [
        { key: "Decided", value: s(props.decided_at) },
        { key: "Institution", value: s(props.institution_name) },
        { key: "Vote", value: s(props.vote_summary) },
        { key: "Status", value: s(props.status) },
      ];
    case "Project":
      return [
        { key: "Name", value: s(props.name) },
        { key: "Status", value: s(props.status) },
        { key: "Address", value: s(props.address) },
        { key: "Jurisdiction", value: s(props.jurisdiction_name) },
      ];
    case "Program":
      return [
        { key: "Name", value: s(props.name) },
        { key: "Status", value: s(props.status) },
        { key: "Type", value: s(props.program_type) },
      ];
    case "Case":
      return [
        { key: "Caption", value: s(props.caption ?? props.name) },
        { key: "Docket", value: s(props.docket_number) },
        { key: "Filed", value: s(props.filed_at) },
        { key: "Closed", value: s(props.closed_at) },
        { key: "Status", value: s(props.status) },
      ];
    case "Meeting":
      return [
        { key: "Title", value: s(props.title) },
        { key: "Date", value: s(props.meeting_date) },
        { key: "Institution", value: s(props.institution_name) },
        { key: "Type", value: s(props.meeting_type) },
      ];
    case "Filing":
      return [
        { key: "Type", value: s(props.filing_type) },
        { key: "Signed", value: s(props.signed_at) },
        { key: "Period", value: s(props.period_start) && s(props.period_end)
            ? `${props.period_start} – ${props.period_end}` : s(props.period_start) },
        { key: "Filer", value: s(props.filed_by_name) },
      ];
    case "Committee":
      return [
        { key: "Name", value: s(props.name) },
        { key: "FPPC ID", value: s(props.fppc_id) },
        { key: "Treasurer", value: s(props.treasurer) },
      ];
    case "Organization":
      return [
        { key: "Name", value: s(props.name) },
        { key: "Subtype", value: asList(props.labels) },
        { key: "Jurisdiction", value: s(props.jurisdiction_name) },
      ];
    case "MoneyFlow":
      return [
        { key: "Amount", value: s(props.amount) },
        { key: "Date", value: s(props.flow_date) },
        { key: "Type", value: s(props.flow_type) },
        { key: "Schedule", value: s(props.source_schedule) },
      ];
    // Remaining Tier 2 types (Seat, SeatService, Election, Candidacy, AgendaItem,
    // Proceeding, Agreement, Amendment, Record, Place, Issue) — one case per type.
    // Reference spec §7.1 item 6 and §7.2 for the per-type fact field lists. Each
    // should pull the 3–5 most meaningful scalar properties from the node.
    default:
      return [{ key: "ID", value: s(props.id) }];
  }
}

function s(v: unknown): string | null { return typeof v === "string" && v.length > 0 ? v : null; }
function asList(v: unknown): string | null { return Array.isArray(v) && v.length > 0 ? v.join(", ") : null; }
```

### Task 13: `connections.tsx` — grouped by relationship type

**Files:**
- Create: `app/src/components/entity/connections.tsx`
- Create: tests

Groups `entity.neighbors` by relationship (inferred from `entity.edges`). Each group is a header + list of cards linking to the neighbor's entity page.

### Task 14: `evidence-drawer.tsx` — expandable records list

**Files:**
- Create: `app/src/components/entity/evidence-drawer.tsx`
- Create: `app/src/lib/server/entity-evidence.ts` — loads Record nodes directly linked via EVIDENCED_BY
- Create: tests

Spec §7.1 item 10 contract:
- Row shows `record_type`, `captured_at`, `preferred_display_artifact`, and `preferred_public_url`.
- If `has_public_source`: clickable, opens `preferred_public_url` in new tab.
- If not: dim + non-clickable with tooltip "no public source captured".
- Always: Record ID selectable for citation.

### Task 15: `editorial-callout.tsx` — optional Plex Serif italic

**Files:**
- Create: `app/src/components/entity/editorial-callout.tsx`

Renders `entity.properties.editorial_note` if present. Returns null otherwise.

### Task 16: Smoke test the Tier 2 shell

Wire `entity-page.tsx` to render the components built in Tasks 10–15. Visit http://localhost:3100/organization/org-san-rafael-city-council (or similar Tier 2 entity), verify:
- Status bar + nav render normally
- Title + meta strip show real data
- Facts panel has real key/values
- Connections list shows real neighbors as clickable cards
- Evidence drawer, when expanded, lists records

Commit once all Tier 2 types render cleanly.

---

## Phase F — Tier 1 additions (8 tasks)

### Task 17: `hero-stats.tsx` — Tier 1 hero stat strip

Per spec §7.1 item 4. VT323 30px numerals. Extract per-type stat definitions to `entity-facts.ts`:

```typescript
export function heroStatsForEntity(type: NodeType, props): Array<{label: string, value: string}> {
  switch (type) {
    case "Project": return [
      { label: "money", value: formatMoney(props.total_money) },
      { label: "decisions", value: String(props.decisions_count) },
      ...
    ];
    ...
  }
}
```

### Task 18: `radial-hero.tsx` — Cytoscape concentric layout

**Files:**
- Create: `app/src/components/entity/radial-hero.tsx`
- Create: tests (with CytoscapeBase mocked)

Consumes `entity.neighbors` + `entity.edges`. Renders with Cytoscape `concentric` layout using `ring` (1 / 2 / 3) as the level. Reuse `obsidianStylesheet`, `colorClassForType`, `shapeForType`, `sizeForRole`, `glowForRole` from Plan 1.

Hover reveals label for 2-hop/3-hop. Click navigates to the clicked node's route.

Overflow footer when `entity.neighbors.length + 1 < entity.neighbor_total`:
`+{N} more neighbors · see /graph?focus={id}` — `/graph` is still a Plan 3 stub, but the deep link is preserved.

### Task 19: `timeline-ribbon.tsx` — horizontal temporal strip

Per spec §5.4. Consumes `entity.neighbors` + `entity.edges`. Extract each neighbor's effective event date via `entity-temporal.ts`:

```typescript
// app/src/lib/server/entity-temporal.ts
import type { EntityNeighbor } from "./entity-loader";

export function effectiveEventDate(neighbor: EntityNeighbor, props: Record<string, unknown>): string | null {
  switch (neighbor.type) {
    case "Meeting": return props.meeting_date as string ?? null;
    case "Decision": return props.decided_at as string ?? null;
    case "MoneyFlow": return props.flow_date as string ?? null;
    case "Filing": return props.signed_at as string ?? null;
    case "Election": return props.election_date as string ?? null;
    case "Proceeding": return props.date as string ?? null;
    case "Agreement":
    case "Amendment": return props.effective_date as string ?? null;
    case "Case": return props.filed_at as string ?? null;
    case "AgendaItem": return props.parent_meeting_date as string ?? null;  // normalizer-provided
    case "Record": return (props.published_at ?? props.captured_at) as string ?? null;
    default: return null;
  }
}
```

Render: horizontal strip spanning from earliest-loaded date to `INGEST`. VT323 tick marks at year boundaries. Each event as a small diamond in its node-type color. Hover reveals the neighbor's label + date. Click navigates.

Sliders (date range) — defer to Plan 3's explorer. Timeline ribbon on entity pages is read-only.

### Task 20: Wire timeline into Tier 1 pages

Modify `entity-page.tsx` — after the radial + facts row, insert `<TimelineRibbon entity={entity} />` for Tier 1 types only.

### Task 21: Verify §5.4 durable-vs-event semantics

Unit tests for `effectiveEventDate`:
- Person/Organization/Committee/Project/Program/Place/Issue/Seat return null (always visible, no slider).
- Case returns `filed_at`; if `closed_at` exists too, timeline shows a range (optional for Plan 2; spec says range, but simplest first rendering is just the start).
- SeatService returns `started_at` → `ended_at` range.

### Task 22: Tier 1 smoke test — Person page

Visit http://localhost:3100/person/kate-colin:
- Hero: "KATE COLIN" in VT323 40px
- Stat strip: "Mayor, San Rafael · 2024– · N filings · M votes"
- Radial hero: Kate Colin at center, ring 1 has SeatServices + Committee, ring 2 has Decisions/Money/Filings, ring 3 has Organization:Government
- Facts panel: name, current seat, jurisdiction, aliases
- Connections: grouped by relationship type
- Timeline: events plotted chronologically
- Evidence drawer: collapsed by default; expand to see source records

### Task 23: Tier 1 smoke test — Decision page

Visit http://localhost:3100/decision/2024-08-19-resolution-15336. Same checks, focus on decision-specific stats (date, institution, vote summary).

### Task 24: Tier 1 smoke test — remaining Tier 1 types

Project, Program, Case, Meeting, Filing, Committee — spot-check each by visiting a known entity of that type. Note any that break and fix.

---

## Phase G — Wire + ship

### Task 25: Final `npm run verify` + `npm run build`

Expected: all tests green; production build succeeds; all routes register. No console errors on any entity page.

### Task 26: End-to-end smoke + commit final state

```bash
cd app && rm -rf .next
npm run verify
npm run build
npm run start &
sleep 3
curl -sL http://localhost:3100/person/kate-colin | grep -E "(KATE COLIN|Mayor|search_label)" | head -5
curl -sL http://localhost:3100/decision/2024-08-19-resolution-15336 | grep -E "(Resolution|2024-08-19)" | head -3
curl -sL http://localhost:3100/case/boyd-v-city-of-san-rafael | grep -E "(Boyd|case)" | head -3
kill %1
```

Commit any final cleanups. Plan 2 complete.

---

## Plan 2 completion checklist

- [ ] All 26 tasks committed.
- [ ] `npm run verify` green (estimated 35-40 tests total by end of Plan 2).
- [ ] All 8 signature-subgraph bundles build with ≥ 2 nodes (edge vocabulary reconciled).
- [ ] `/api/search?q=kate+colin` returns `key_fact` and `last_activity` populated.
- [ ] Every Tier 1 entity page renders hero + radial + stats + timeline.
- [ ] Every Tier 2 entity page renders shell cleanly.
- [ ] `/{type}/{slug}` returns 404 on unknown entities, real page on known ones.
- [ ] Production build succeeds.

Follow-ons deferred to Plan 3:
- `/graph` full-screen explorer (+ pathfinding, time slider, expand contract)
- `/data` data explorer with predefined queries + CSV export
- `/search?q=` full results page
- `/browse/{type}` paginated list pages

Plan 4:
- Command palette (⌘K)
- Keyboard shortcuts
- Invite-only auth
- Vercel deploy polish
- `/about` page
