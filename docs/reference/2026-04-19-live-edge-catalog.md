# Live AuraDB Edge Catalog — 2026-04-19

Snapshot of all relationship types in the live `neo4j+s://<INSTANCE-ID>.databases.neo4j.io` projection, mapped against the spec §3 ontology from `docs/specs/2026-04-19-open-marin-frontend-design.md` (referring to the v1 design's edge names).

Queried via `CALL db.relationshipTypes()` plus per-type label sampling (`MATCH (a)-[r:REL]->(b) RETURN labels(a), labels(b), count(*)`).

**Total live relationship types: 66.**

This catalog is the source of truth consumed by:
- `scripts/edge_vocabulary.py` — Python mapping used by the signature-subgraph builder and future entity-loader
- `app/src/lib/edge-vocabulary.ts` — TypeScript mirror for the radial-hero (Plan 2 Batch D)

## How to use this table

- **Exact match** — spec name == live name (e.g., `CAST_VOTE`). No translation needed.
- **Split by target** — one spec name fans out to multiple live names (e.g., `PART_OF` → `PART_OF_MEETING` + `PART_OF_CASE`).
- **Renamed** — same semantic, different live name (e.g., `ABOUT_ITEM` → `ABOUT_AGENDA_ITEM`).
- **Weak (`RELATES_TO_*`) collapse** — the v2 ingestion emits weak `RELATES_TO_<TargetType>` edges in addition to (or instead of) the strong spec edge. For Project/Program/Agreement, the weak variant is the *only* live edge, so it is load-bearing and stays in the Phase-2 whitelist.
- **Missing** — no live edge yet (e.g., `CONSTRAINS`); spec queries referencing it match nothing — correct behavior until materialized.

## Phase-2 whitelist edges (§3 ontology)

| live relationship type | common source labels | common target labels | spec §3 equivalent | notes |
|---|---|---|---|---|
| `CAST_VOTE` | Person | Decision | `CAST_VOTE` | exact |
| `AT_MEETING` | Decision | Meeting | `AT_MEETING` | exact |
| `ABOUT_AGENDA_ITEM` | Decision | AgendaItem | `ABOUT_ITEM` | renamed |
| `DECIDED_BY` | Decision | Organization:Government | `DECIDED_BY` | exact |
| `DECIDED_AT` | Decision | Meeting | (adjunct to `AT_MEETING`) | redundant-ish — same semantics as AT_MEETING; keep both in whitelist since both exist in projection |
| `PART_OF_MEETING` | AgendaItem | Meeting | `PART_OF` | split — AgendaItem side |
| `PART_OF_CASE` | Proceeding | Case | `PART_OF` | split — Proceeding side |
| `HELD_BY` | SeatService | Person | `HELD_BY` | exact |
| `FOR_SEAT` | SeatService, Candidacy, Election | Seat | `FOR_SEAT` | exact (multi-source) |
| `RESULT_OF_ELECTION` | SeatService | Election | `RESULT_OF` | renamed |
| `AT_INSTITUTION` | Meeting, Seat, SeatService | Organization:Government | `AT_INSTITUTION` | exact |
| `FROM_SOURCE` | Person, Committee, Organization, MoneyFlow | MoneyFlow, Person, … | `FROM_SOURCE` | exact |
| `TO_TARGET` | MoneyFlow | Committee, Organization, Person | `TO_TARGET` | exact |
| `DISCLOSED_IN_FILING` | MoneyFlow, Filing | Filing | `DISCLOSED_IN` | renamed — connects MoneyFlow and child Filings to the parent Filing |
| `RELATES_TO_AGREEMENT` | MoneyFlow, Decision | Agreement | `UNDER_AGREEMENT` | weak collapse — only live variant |
| `AMENDS_AGREEMENT` | Amendment | Agreement | `AMENDS` | renamed |
| `CONTROLLED_BY` | Committee | Person, Organization:Political | `CONTROLLED_BY` | exact |
| `CONTROLLED_BY_COMMITTEE` | Candidacy | Committee | `CONTROLLED_BY` | split — Candidacy side (Candidacy is controlled by a Committee, not a Person) |
| `FILED_BY` | Filing | Person, Organization:Political | `FILED_BY` | exact |
| `FILED_BY_COMMITTEE` | Filing | Committee | `FILED_BY` | split — Committee side |
| `OFFICIAL_FILER` | Filing | Person | `FILED_BY` | adjunct — distinguishes the named official from the filing entity; include in whitelist |
| `CANDIDATE_ACTOR` | Candidacy | Person | `BY_PERSON` | renamed |
| `FILED_FOR_ELECTION` | Filing | Election | `IN_ELECTION` | renamed — Filing side |
| `RELATED_TO_ELECTION` | Election | Election | `IN_ELECTION` (Election→Election only) | mostly runoff/general→primary linkage; keep for election pages |
| `FOR_ELECTION` | Candidacy | Election | `FOR_ELECTION` | exact |
| `FILED_FOR_SEAT` | Filing | Seat | (adjunct to `IN_ELECTION`/`FOR_SEAT`) | keep in whitelist — load-bearing for Form 803 / officeholder filings |
| `FILED_WITH` | Filing | Organization:Government | (new §3 concept) | keep — filings pages need the receiving agency |
| `FILED_DURING_SEAT_SERVICE` | Filing | SeatService | (new §3 concept) | keep — ties Form 700/803 to the holder's tenure |
| `RELATES_TO_PROJECT` | Record, Decision, Agreement, MoneyFlow, Amendment | Project | `FOR_PROJECT`, `ABOUT_PROJECT` | weak collapse — the **only** live variant of both spec edges |
| `RELATES_TO_PROGRAM` | Record, Case, Project, Agreement, MoneyFlow | Program | `ABOUT_PROGRAM` | weak collapse — only live variant |
| `COUNTERPARTY_ACTOR` | Agreement | Organization:Business, Organization:Government | `BETWEEN` | renamed — the "other side" of an Agreement |
| `OPERATED_BY` | Program | Organization:Government | (new §3 concept — program operator) | keep — load-bearing for Program pages |
| `PARTY_TO` | Organization, Person, Case | Case, Organization, Person | `PARTY_TO` | exact — bidirectional (Party→Case *and* Case→Party both exist) |
| `HEARD_IN` | Case | Organization:Court | `HEARD_IN` | exact |
| `HEARD_BY` | Proceeding | Organization, Person | `HEARD_IN` (Proceeding side) | split — Proceeding level |
| `PRIMARY_FOR_ELECTION` | Committee | Election | (adjunct to `IN_ELECTION`) | keep — committee↔election linkage for Committee pages |
| `PRIMARY_PLACE` | Project | Place | (new §3 — primary-location place) | keep for Project pages; note Place nodes are filtered downstream but the edge is fine |

## Universal / structural edges — excluded from Phase-2 whitelist

These are either too weak or structural (evidence, jurisdiction, issues) to drive signature-subgraph traversal. They stay excluded from `PHASE2_WHITELIST_LIVE` per spec §5.5.

| live relationship type | common source labels | common target labels | spec §3 equivalent | notes |
|---|---|---|---|---|
| `EVIDENCED_BY` | Meeting, AgendaItem, Decision, Filing, … | Record | `EVIDENCED_BY` | universal; loaded into evidence drawer, not 2-hop traversal |
| `IN_JURISDICTION` | Project, Filing, Meeting, Case, … | Place | `IN_JURISDICTION` | universal; Place excluded from radial per §5.1.1 |
| `RELATES_TO_ISSUE` | Record, Case, AgendaItem | Issue | `RELATES_TO_ISSUE` | universal; Issue excluded from radial |
| `RELATES_TO_ACTOR` | Record, Person, MoneyFlow | Person, Organization | — | weak universal |
| `RELATES_TO_AGENDA_ITEM` | Record | AgendaItem | — | weak universal |
| `RELATES_TO_AMENDMENT` | Decision | Amendment | — | weak universal |
| `RELATES_TO_CASE` | Record, Case, Program | Case | — | weak universal |
| `RELATES_TO_COMMITTEE` | Record, MoneyFlow, Organization | Committee | — | weak universal |
| `RELATES_TO_DECISION` | Decision, Record, MoneyFlow, Project | Decision | — | weak universal |
| `RELATES_TO_ELECTION` | Record, Decision | Election | — | weak universal (distinct from `RELATED_TO_ELECTION` Election→Election which is whitelisted) |
| `RELATES_TO_FILING` | Record | Filing | — | weak universal |
| `RELATES_TO_INSTITUTION` | MoneyFlow, Agreement, Organization | Organization:Government | — | weak universal |
| `RELATES_TO_MEETING` | Record | Meeting | — | weak universal |
| `RELATES_TO_MONEY_FLOW` | Record | MoneyFlow | — | weak universal |
| `RELATES_TO_PLACE` | Record, Case, Place, AgendaItem | Place | — | weak universal; Place excluded from radial |
| `RELATES_TO_RECORD` | Record, Filing | Record | — | weak universal (record-to-record) |
| `RELATES_TO_SEAT` | Record | Seat | — | weak universal |

**Kept in whitelist (exception to the `RELATES_TO_*` rule):** `RELATES_TO_PROJECT`, `RELATES_TO_PROGRAM`, `RELATES_TO_AGREEMENT`. These are the *only* live variant of spec §3's `FOR_PROJECT` / `ABOUT_PROJECT` / `ABOUT_PROGRAM` / `UNDER_AGREEMENT` edges, so without them Project/Program/Agreement pages would have no neighborhood at all.

## Record-lineage edges — excluded from Phase-2 whitelist

Record-to-Record and Record-to-artifact lineage. Used by the evidence drawer / provenance pipelines, not by the radial hero.

| live relationship type | common source labels | common target labels | notes |
|---|---|---|---|
| `DERIVED_FROM_RECORD` | Record, ValidationCheck | Record | lineage |
| `RECORD_ATTACHED_TO_RECORD` | Record | Record | attachment lineage |
| `RECORD_EXTRACTS_FROM_RECORD` | Record | Record | OCR/extract lineage |
| `RECORD_AUTHORIZES_DECISION` | Record | Decision | authorizing document |
| `RECORD_INTRODUCES_DECISION` | Record | Decision | introducing record |
| `SAME_AS` | Organization | Organization | actor-resolution alias |
| `VALIDATES` | Filing, ValidationCheck | ValidationCheck, Filing | validation pipeline |
| `REQUESTED_BY_ACTOR` | MoneyFlow | Person | low-volume (1 edge) — not whitelisted but kept for reference |
| `REQUESTED_BY_SEAT` | MoneyFlow | Seat | low-volume (1 edge) |
| `REQUESTED_BY_SEAT_SERVICE` | MoneyFlow | SeatService | low-volume (1 edge) |
| `TARGETS_ACTOR` | Filing | Person | Form 803 target subject |
| `TARGETS_SEAT` | Filing | Seat | Form 803 target seat |

## Spec names with no live equivalent

| spec §3 edge | status | notes |
|---|---|---|
| `CONSTRAINS` | not present | v1 design specifies Case→Decision legal-precedent edge; not yet materialized. `SPEC_TO_LIVE["CONSTRAINS"]` resolves to `[]` — queries match nothing, which is correct until ingestion lands. |

## Summary of the spec → live mapping

```text
CAST_VOTE        → CAST_VOTE
AT_MEETING       → AT_MEETING, DECIDED_AT
ABOUT_ITEM       → ABOUT_AGENDA_ITEM
DECIDED_BY       → DECIDED_BY
PART_OF          → PART_OF_MEETING, PART_OF_CASE
HELD_BY          → HELD_BY
FOR_SEAT         → FOR_SEAT
RESULT_OF        → RESULT_OF_ELECTION
AT_INSTITUTION   → AT_INSTITUTION
FROM_SOURCE      → FROM_SOURCE
TO_TARGET        → TO_TARGET
DISCLOSED_IN     → DISCLOSED_IN_FILING
UNDER_AGREEMENT  → RELATES_TO_AGREEMENT         (weak-only)
AMENDS           → AMENDS_AGREEMENT
CONTROLLED_BY    → CONTROLLED_BY, CONTROLLED_BY_COMMITTEE
FILED_BY         → FILED_BY, FILED_BY_COMMITTEE, OFFICIAL_FILER
BY_PERSON        → CANDIDATE_ACTOR
IN_ELECTION      → FILED_FOR_ELECTION, RELATED_TO_ELECTION
FOR_ELECTION     → FOR_ELECTION
FOR_PROJECT      → RELATES_TO_PROJECT           (weak-only)
ABOUT_PROJECT    → RELATES_TO_PROJECT           (weak-only)
ABOUT_PROGRAM    → RELATES_TO_PROGRAM           (weak-only)
BETWEEN          → COUNTERPARTY_ACTOR
PARTY_TO         → PARTY_TO
HEARD_IN         → HEARD_IN, HEARD_BY
CONSTRAINS       → (empty — not materialized)
```

Plus these live edges that are not spec §3 aliases but are load-bearing for entity pages and therefore included in `PHASE2_WHITELIST_LIVE`:

- `OPERATED_BY` — Program → operating institution
- `FILED_WITH` — Filing → receiving agency
- `FILED_DURING_SEAT_SERVICE` — Filing → holder's tenure
- `FILED_FOR_SEAT` — Filing → affected seat
- `PRIMARY_FOR_ELECTION` — Committee ↔ Election (primary)
- `PRIMARY_PLACE` — Project → primary place
