# Meeting Normalization Pipeline — Design Spec

**Date:** 2026-04-14
**Status:** Draft
**Author:** Claude (Opus), with Stuart Watson

## 1. Purpose

Wire Granicus and CivicPlus adapter output into Neo4j AuraDB. Transform captured meeting data into settled-ontology nodes (Meeting, Record, Organization, Place) and load them into the live graph alongside the existing San Rafael data.

## 2. Scope

**Build now:**
- A normalizer script that reads adapter extracted JSON and produces settled-format JSONL (nodes + edges)
- Load the JSONL into Neo4j via the existing `load_neo4j_v2.py` batched loader
- Create Organization and Place nodes for each new jurisdiction
- Normalize meetings from all 5 Granicus/CivicPlus sources into the graph

**Build later:**
- Campaign finance normalization (NetFile Excel → MoneyFlow, Filing, Committee, Person)
- AgendaItem and Decision extraction from meeting content (requires document download)

## 3. Architecture Decision: Skip the old projection builder

New data from new cities goes through a shorter pipeline:

```
Adapter extracted JSON
    → normalize_meetings.py (produces settled-format JSONL)
    → load_neo4j_v2.py (batched UNWIND into AuraDB)
```

**Why not use `build_graph_projection.py`?** The existing projection builder expects old-format bundles with `inst-` prefixes and produces JSONL that then needs migration to the settled ontology. New data was never in the old format — running it through two transformations (projection + migration) is wasteful. The normalizer produces settled-format JSONL directly using `org-` prefixes, `Person`/`Organization` labels, and the 21-type ontology.

The normalized bundle JSON on disk still serves as the audit trail. It just uses the settled format from the start.

## 4. Data Flow

```
data/extracted/{source_id}/{date}.json    (adapter output)
        │
        ▼
scripts/normalize_meetings.py             (transform to settled nodes/edges)
        │
        ▼
data/normalized/{source_id}-meetings/     (settled-format bundle on disk)
  ├── nodes.jsonl                          
  ├── edges.jsonl
  └── normalization-report.json
        │
        ▼
scripts/load_neo4j_v2.py --input-dir ...  (batched UNWIND into AuraDB)
```

## 5. Node Types Produced

| Type | Source | Example ID |
|------|--------|-----------|
| Meeting | Each meeting row | `meeting-novato-city-council-2193` |
| Record | Archive page + each artifact URL | `record-novato-city-council-archive-page-2026-04-14` |
| Organization | Institution from config (created once) | `org-novato-city-council` |
| Place | Jurisdiction from config (created once) | `place-novato` |

## 6. Edge Types Produced

| Edge | From → To | Source |
|------|-----------|--------|
| `AT_INSTITUTION` | Meeting → Organization | `institution_id` from meeting |
| `IN_JURISDICTION` | Meeting → Place | `jurisdiction_id` from config |
| `IN_JURISDICTION` | Organization → Place | `jurisdiction_id` from config |
| `EVIDENCED_BY` | Meeting → Record | Artifact URLs → Record nodes |

## 7. Node Format (settled ontology)

Each node in `nodes.jsonl`:
```json
{
  "id": "meeting-novato-city-council-2193",
  "node_type": "Meeting",
  "labels": ["Meeting"],
  "display_label": "Novato City Council — 2024-03-12",
  "promotion_state": "promoted",
  "source_bundle_ids": ["novato-city-council-meetings__2026-04-14"],
  "source_sections": ["meeting_candidates"],
  "source_status": "captured_from_granicus",
  "properties": {
    "meeting_date": "2024-03-12",
    "meeting_type": "regular",
    "title": "Regular City Council Meeting",
    "institution_id": "org-novato-city-council",
    "jurisdiction_id": "place-novato"
  },
  "qa_lane": false
}
```

Organization stub node (MERGE semantics — created if not exists):
```json
{
  "id": "org-novato-city-council",
  "node_type": "Organization",
  "labels": ["Organization", "Government"],
  "display_label": "Novato City Council",
  "promotion_state": "promoted",
  "source_bundle_ids": ["novato-city-council-meetings__2026-04-14"],
  "source_sections": ["institution_stubs"],
  "source_status": "stub_from_adapter_config",
  "properties": {
    "name": "Novato City Council",
    "subtype": "city_council",
    "jurisdiction_id": "place-novato"
  },
  "qa_lane": false
}
```

Place stub node:
```json
{
  "id": "place-novato",
  "node_type": "Place",
  "labels": ["Place"],
  "display_label": "Novato",
  "promotion_state": "promoted",
  "source_bundle_ids": ["novato-city-council-meetings__2026-04-14"],
  "source_sections": ["place_stubs"],
  "source_status": "stub_from_adapter_config",
  "properties": {
    "name": "Novato",
    "place_type": "city"
  },
  "qa_lane": false
}
```

## 8. Edge Format

```json
{
  "source_id": "meeting-novato-city-council-2193",
  "source_node_type": "Meeting",
  "target_id": "org-novato-city-council",
  "target_node_type": "Organization",
  "relationship_type": "AT_INSTITUTION",
  "source_bundle_ids": ["novato-city-council-meetings__2026-04-14"],
  "source_fields": ["institution_id"],
  "properties": {}
}
```

## 9. ID Conventions

- Meeting: `meeting-{source_id}-{clip_id}` (Granicus) or `meeting-{source_id}-{agenda_id}` (CivicPlus) or `meeting-{source_id}-{date}-row-{N}` (fallback)
- Record: `record-{source_id}-{artifact_type}-{date}` for archive pages, `record-{source_id}-{meeting_id}-{artifact_type}` for per-meeting artifacts
- Organization: `org-{slug}` from adapter config `institution_id`
- Place: `place-{slug}` from adapter config `jurisdiction_id`

Meeting IDs are already stamped by the adapter's `capture()` method — the normalizer passes them through unchanged.

## 10. Handling Existing Data

The existing graph has 283 San Rafael meetings with IDs like `meeting-2019-01-22-san-rafael-city-council`. New meetings use `meeting-{source_id}-{clip_id}` format. No collision risk because:
- Different source_id prefixes (novato-city-council vs 2019-01-22-san-rafael)
- Granicus meetings use clip_id (numeric), not dates

The loader uses `MERGE` on `id`, so if a node already exists (e.g., re-running normalization), it updates rather than duplicates.

## 11. CLI Interface

```bash
# Normalize one source
python scripts/normalize_meetings.py --source novato-city-council

# Normalize all sources with meeting data
python scripts/normalize_meetings.py --all

# Then load into Neo4j
python scripts/load_neo4j_v2.py --input-dir data/normalized/novato-city-council-meetings/
```

Or a combined command:
```bash
python scripts/normalize_meetings.py --source novato-city-council --load
```

The `--load` flag runs `load_neo4j_v2.py` automatically after normalization (requires NEO4J_* env vars).

## 12. What This Doesn't Do

- No AgendaItem or Decision extraction (requires parsing agenda PDFs/HTML — future work)
- No campaign finance normalization (separate spec)
- No document download (adapter captures URLs only, not PDF content)
- No identity resolution beyond institution/jurisdiction stubs

## 13. Success Criteria

1. `python scripts/normalize_meetings.py --source novato-city-council` produces settled-format JSONL
2. `python scripts/load_neo4j_v2.py` loads it into AuraDB without errors
3. Neo4j shows: new Meeting nodes for Novato, Sausalito, Corte Madera, Mill Valley, Marin County BOS
4. Neo4j shows: new Organization:Government nodes for each institution
5. Neo4j shows: new Place nodes for each jurisdiction
6. Neo4j shows: AT_INSTITUTION and IN_JURISDICTION edges connecting meetings to institutions and places
7. Existing San Rafael data is untouched (verify with existing verification queries)
8. Running normalization twice produces the same result (idempotent via MERGE)

## 14. Source-to-Jurisdiction Mapping

| Source ID | Institution Node | Place Node | Display Name |
|-----------|-----------------|------------|-------------|
| marin-county-bos | org-marin-county-board-of-supervisors | place-marin-county | Marin County Board of Supervisors |
| novato-city-council | org-novato-city-council | place-novato | Novato City Council |
| sausalito-city-council | org-sausalito-city-council | place-sausalito | Sausalito City Council |
| corte-madera-town-council | org-corte-madera-town-council | place-corte-madera | Corte Madera Town Council |
| mill-valley-committees | org-mill-valley-committees | place-mill-valley | Mill Valley Committees |

These Organization and Place nodes use MERGE semantics — they're created on first normalization and skipped on subsequent runs.
