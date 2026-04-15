# Migration + Neo4j Foundation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate the existing graph-v1 projection (6,267 nodes / 21,262 edges) from legacy labels to the settled 21-type ontology and load it into Neo4j AuraDB with proper indexes.

**Architecture:** Read the existing projected JSONL files, apply deterministic label/ID/relationship remapping, output settled-schema JSONL, then load into Neo4j via the Python driver with batched UNWIND writes. The migration is a pure transformation of already-merged/deduped data — not a re-projection from normalized bundles.

**Tech Stack:** Python 3.14, pytest, neo4j Python driver, existing graph_projection_lib.py utilities

**Spec:** `docs/specs/2026-04-14-marin-civic-graph-v1-design.md` Section 4 (Migration mapping table)

---

## File Structure

```
scripts/
  migration_mapping.py       # Pure mapping rules — no I/O, fully testable
  migrate_graph_v2.py         # Reads graph-v1 JSONL, applies mapping, writes graph-v2 JSONL
  load_neo4j_v2.py            # Batched loader using neo4j Python driver
  verify_neo4j_v2.py          # Verification queries against loaded graph
tests/
  test_migration_mapping.py   # Unit tests for every mapping rule
  test_migrate_graph_v2.py    # Integration tests with sample JSONL fixtures
data/projected/graph-v2/
  nodes.jsonl                 # Output: migrated nodes
  edges.jsonl                 # Output: migrated edges
  migration-report.json       # Output: stats, conflicts, dropped nodes
  id-map.json                 # Output: old_id -> new_id for every remapped node
registry/
  neo4j-schema.cypher         # Constraints + indexes as executable Cypher
requirements-migration.txt    # neo4j, pytest
```

---

### Task 1: Project setup

**Files:**
- Create: `requirements-migration.txt`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Create requirements file**

```
neo4j>=5.0,<6.0
pytest>=8.0
```

Write to `requirements-migration.txt`.

- [ ] **Step 2: Install dependencies**

Run: `pip install -r requirements-migration.txt`
Expected: successful install, no errors

- [ ] **Step 3: Create test infrastructure**

Create `tests/__init__.py` (empty file).

Create `tests/conftest.py`:

```python
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_actor_person():
    return {
        "id": "actor-kate-colin",
        "node_type": "Actor",
        "display_label": "Kate Colin",
        "promotion_state": "canonical",
        "source_bundle_ids": ["canonical-seeds-san-rafael-01"],
        "source_sections": ["actor_candidates"],
        "source_status": "canonical_seed",
        "properties": {
            "actor_type": "person",
            "name": "Kate Colin",
            "observed_labels": ["Kate Colin", "Councilmember Colin"],
            "payload_json": "{}",
        },
    }


@pytest.fixture
def sample_actor_business():
    return {
        "id": "actor-anedot",
        "node_type": "Actor",
        "display_label": "Anedot",
        "promotion_state": "promoted",
        "source_bundle_ids": ["san-rafael-actor-completeness-01__bundle-01"],
        "source_sections": ["actor_candidates"],
        "source_status": "promoted_for_graph_completeness",
        "properties": {
            "actor_type": "business",
            "name": "Anedot",
            "observed_labels": ["Anedot"],
            "payload_json": "{}",
        },
    }


@pytest.fixture
def sample_institution():
    return {
        "id": "inst-california-state-library",
        "node_type": "Institution",
        "display_label": "California State Library",
        "promotion_state": "promoted",
        "source_bundle_ids": ["grant-program-dossiers-01__bundle-01"],
        "source_sections": ["institution_candidates"],
        "source_status": None,
        "properties": {
            "institution_type": "state_agency",
            "name": "California State Library",
            "payload_json": "{}",
        },
    }


@pytest.fixture
def sample_eid():
    return {
        "id": "eid-san-rafael-form700-2020-12-23-kertz-rachel-assuming-office-city-council-member-city-council",
        "node_type": "EconomicInterestDisclosure",
        "display_label": "eid-san-rafael-form700-2020-12-23-kertz-rachel-assuming-office-city-council-member-city-council",
        "promotion_state": "promoted",
        "source_bundle_ids": ["san-rafael-officeholder-disclosures-01__bundle-01"],
        "source_sections": ["economic_interest_disclosure_candidates"],
        "source_status": "historical_officeholder_continuity",
        "properties": {
            "disclosure_type": "assuming_office",
            "filed_at": "2020-12-23",
            "filer_actor_id": "actor-rachel-kertz",
            "filing_institution_id": "inst-city-of-san-rafael",
            "seat_id": "seat-san-rafael-city-council-district-4",
            "seat_service_id": "seatservice-rachel-kertz-d4-2020-term",
            "payload_json": "{}",
        },
    }


@pytest.fixture
def sample_case_participation():
    return {
        "id": "casepart-boyd-city-defendant",
        "node_type": "CaseParticipation",
        "display_label": "casepart-boyd-city-defendant",
        "promotion_state": "promoted",
        "source_bundle_ids": ["legal-precedent-01__bundle-01"],
        "source_sections": ["case_participation_candidates"],
        "source_status": None,
        "properties": {
            "case_id": "case-boyd-v-city-of-san-rafael",
            "institution_id": "inst-city-of-san-rafael",
            "role": "defendant",
            "start_date": "2023-08-11",
            "evidence_record_ids": ["record-san-rafael-boyd-dismissal-order-2024-08-07"],
            "payload_json": "{}",
        },
    }


@pytest.fixture
def sample_decision():
    return {
        "id": "decision-2024-08-19-resolution-15336",
        "node_type": "Decision",
        "display_label": "Resolution 15336",
        "promotion_state": "promoted",
        "source_bundle_ids": ["san-rafael-city-council-decisions-01__bundle-01"],
        "source_sections": ["decision_candidates"],
        "source_status": None,
        "properties": {
            "decided_at": "2024-08-19",
            "decision_type": "resolution_adoption",
            "institution_id": "inst-san-rafael-city-council",
            "meeting_id": "meeting-2024-08-19-san-rafael-city-council",
            "payload_json": "{}",
        },
    }


@pytest.fixture
def sample_validation_check():
    return {
        "id": "validationcheck-actor-coverage-01",
        "node_type": "ValidationCheck",
        "display_label": "Actor coverage check",
        "promotion_state": "promoted",
        "source_bundle_ids": ["san-rafael-actor-completeness-01__bundle-01"],
        "source_sections": ["validation_check_candidates"],
        "source_status": None,
        "properties": {"check_type": "actor_coverage", "payload_json": "{}"},
    }
```

- [ ] **Step 4: Verify pytest runs**

Run: `cd /Users/tammypais/projects/marin-civic-graph && python -m pytest tests/ -v --co`
Expected: "no tests ran" (collected 0 items), no import errors

- [ ] **Step 5: Commit**

```bash
git add requirements-migration.txt tests/__init__.py tests/conftest.py
git commit -m "chore: add migration test infrastructure and fixtures"
```

---

### Task 2: Migration mapping module

**Files:**
- Create: `scripts/migration_mapping.py`
- Create: `tests/test_migration_mapping.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_migration_mapping.py`:

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from migration_mapping import (
    migrate_node,
    migrate_edge,
    migrate_id,
    case_participation_to_edges,
)


class TestMigrateId:
    def test_actor_person_prefix(self, sample_actor_person):
        old_id = "actor-kate-colin"
        props = {"actor_type": "person"}
        assert migrate_id(old_id, "Actor", props) == "person-kate-colin"

    def test_actor_business_prefix(self):
        assert migrate_id("actor-anedot", "Actor", {"actor_type": "business"}) == "org-anedot"

    def test_actor_nonprofit_prefix(self):
        assert migrate_id("actor-ritter-center", "Actor", {"actor_type": "nonprofit"}) == "org-ritter-center"

    def test_actor_political_committee_prefix(self):
        assert migrate_id("actor-some-pac", "Actor", {"actor_type": "political_committee"}) == "org-some-pac"

    def test_actor_unknown_defaults_to_org(self):
        assert migrate_id("actor-unknown-entity", "Actor", {"actor_type": "unknown"}) == "org-unknown-entity"

    def test_institution_prefix(self):
        assert migrate_id("inst-california-state-library", "Institution", {}) == "org-california-state-library"

    def test_eid_prefix(self):
        assert migrate_id("eid-san-rafael-form700-filing", "EconomicInterestDisclosure", {}) == "filing-san-rafael-form700-filing"

    def test_passthrough_prefix(self):
        assert migrate_id("decision-2024-08-19-foo", "Decision", {}) == "decision-2024-08-19-foo"
        assert migrate_id("meeting-2024-08-19-bar", "Meeting", {}) == "meeting-2024-08-19-bar"
        assert migrate_id("record-some-doc", "Record", {}) == "record-some-doc"


class TestMigrateNode:
    def test_actor_person(self, sample_actor_person):
        result = migrate_node(sample_actor_person)
        assert result is not None
        assert result["id"] == "person-kate-colin"
        assert result["node_type"] == "Person"
        assert result["labels"] == ["Person"]
        assert result["properties"]["name"] == "Kate Colin"
        assert result["properties"]["aliases"] == ["Kate Colin", "Councilmember Colin"]
        assert "observed_labels" not in result["properties"]
        assert "actor_type" not in result["properties"]

    def test_actor_business(self, sample_actor_business):
        result = migrate_node(sample_actor_business)
        assert result["id"] == "org-anedot"
        assert result["node_type"] == "Organization"
        assert "Business" in result["labels"]
        assert "Organization" in result["labels"]

    def test_institution_to_organization(self, sample_institution):
        result = migrate_node(sample_institution)
        assert result["id"] == "org-california-state-library"
        assert result["node_type"] == "Organization"
        assert "Government" in result["labels"]
        assert "Organization" in result["labels"]
        assert result["properties"]["subtype"] == "state_agency"
        assert "institution_type" not in result["properties"]

    def test_eid_to_filing(self, sample_eid):
        result = migrate_node(sample_eid)
        assert result["id"].startswith("filing-")
        assert result["node_type"] == "Filing"
        assert result["properties"]["filing_type"] == "form_700"
        assert result["properties"]["filed_by"].startswith("person-")
        assert result["properties"]["filing_institution_id"].startswith("org-")

    def test_case_participation_returns_none(self, sample_case_participation):
        result = migrate_node(sample_case_participation)
        assert result is None

    def test_validation_check_gets_qa_flag(self, sample_validation_check):
        result = migrate_node(sample_validation_check)
        assert result is not None
        assert result["node_type"] == "ValidationCheck"
        assert result["qa_lane"] is True

    def test_decision_remaps_institution_ref(self, sample_decision):
        result = migrate_node(sample_decision)
        assert result["properties"]["institution_id"] == "org-san-rafael-city-council"

    def test_passthrough_types_unchanged(self):
        meeting = {
            "id": "meeting-2024-08-19-san-rafael-city-council",
            "node_type": "Meeting",
            "display_label": "Aug 19 2024 Meeting",
            "promotion_state": "promoted",
            "source_bundle_ids": ["test"],
            "source_sections": ["meeting_candidates"],
            "source_status": None,
            "properties": {
                "meeting_date": "2024-08-19",
                "meeting_type": "regular",
                "institution_id": "inst-san-rafael-city-council",
                "payload_json": "{}",
            },
        }
        result = migrate_node(meeting)
        assert result["id"] == "meeting-2024-08-19-san-rafael-city-council"
        assert result["node_type"] == "Meeting"
        assert result["properties"]["institution_id"] == "org-san-rafael-city-council"


class TestMigrateEdge:
    def test_cast_vote_on_renamed(self):
        edge = {
            "source_id": "actor-kate-colin",
            "source_node_type": "Actor",
            "target_id": "decision-2024-08-19-resolution-15336",
            "target_node_type": "Decision",
            "relationship_type": "CAST_VOTE_ON",
            "source_bundle_ids": ["test"],
            "source_fields": ["votes"],
            "properties": {"vote": "yes"},
        }
        id_map = {"actor-kate-colin": "person-kate-colin"}
        result = migrate_edge(edge, id_map)
        assert result["source_id"] == "person-kate-colin"
        assert result["relationship_type"] == "CAST_VOTE"

    def test_decided_by_institution_renamed(self):
        edge = {
            "source_id": "decision-2024-08-19-resolution-15336",
            "source_node_type": "Decision",
            "target_id": "inst-san-rafael-city-council",
            "target_node_type": "Institution",
            "relationship_type": "DECIDED_BY_INSTITUTION",
            "source_bundle_ids": ["test"],
            "source_fields": ["institution_id"],
            "properties": {},
        }
        id_map = {"inst-san-rafael-city-council": "org-san-rafael-city-council"}
        result = migrate_edge(edge, id_map)
        assert result["target_id"] == "org-san-rafael-city-council"
        assert result["target_node_type"] == "Organization"
        assert result["relationship_type"] == "DECIDED_BY"

    def test_edge_touching_case_participation_dropped(self):
        edge = {
            "source_id": "casepart-boyd-city-defendant",
            "source_node_type": "CaseParticipation",
            "target_id": "case-boyd-v-city-of-san-rafael",
            "target_node_type": "Case",
            "relationship_type": "PART_OF_CASE",
            "source_bundle_ids": ["test"],
            "source_fields": ["case_id"],
            "properties": {},
        }
        result = migrate_edge(edge, {})
        assert result is None

    def test_passthrough_edge(self):
        edge = {
            "source_id": "decision-foo",
            "source_node_type": "Decision",
            "target_id": "meeting-bar",
            "target_node_type": "Meeting",
            "relationship_type": "DECIDED_AT_MEETING",
            "source_bundle_ids": ["test"],
            "source_fields": ["meeting_id"],
            "properties": {},
        }
        result = migrate_edge(edge, {})
        assert result["relationship_type"] == "AT_MEETING"

    def test_id_ref_properties_remapped(self):
        edge = {
            "source_id": "actor-kate-colin",
            "source_node_type": "Actor",
            "target_id": "decision-foo",
            "target_node_type": "Decision",
            "relationship_type": "CAST_VOTE_ON",
            "source_bundle_ids": ["test"],
            "source_fields": ["votes"],
            "properties": {
                "vote": "yes",
                "seat_id": "seat-san-rafael-mayor",
                "seat_service_id": "seatservice-kate-colin-2024-2028",
            },
        }
        id_map = {"actor-kate-colin": "person-kate-colin"}
        result = migrate_edge(edge, id_map)
        assert result["properties"]["seat_id"] == "seat-san-rafael-mayor"
        assert result["properties"]["seat_service_id"] == "seatservice-kate-colin-2024-2028"


class TestCaseParticipationToEdges:
    def test_institution_defendant(self, sample_case_participation):
        cp_nodes = [sample_case_participation]
        cp_evidence = {
            "casepart-boyd-city-defendant": [
                "record-san-rafael-boyd-dismissal-order-2024-08-07"
            ]
        }
        id_map = {"inst-city-of-san-rafael": "org-city-of-san-rafael"}
        edges = case_participation_to_edges(cp_nodes, cp_evidence, id_map)
        assert len(edges) == 1
        edge = edges[0]
        assert edge["source_id"] == "org-city-of-san-rafael"
        assert edge["target_id"] == "case-boyd-v-city-of-san-rafael"
        assert edge["relationship_type"] == "PARTY_TO"
        assert edge["properties"]["role"] == "defendant"
        assert edge["properties"]["start_date"] == "2023-08-11"
        assert "record-san-rafael-boyd-dismissal-order-2024-08-07" in edge["properties"]["evidence_record_ids"]

    def test_actor_plaintiff(self):
        cp_node = {
            "id": "casepart-boyd-plaintiff-group",
            "node_type": "CaseParticipation",
            "display_label": "casepart-boyd-plaintiff-group",
            "promotion_state": "promoted",
            "source_bundle_ids": ["legal-precedent-01__bundle-01"],
            "source_sections": ["case_participation_candidates"],
            "source_status": None,
            "properties": {
                "case_id": "case-boyd-v-city-of-san-rafael",
                "actor_id": "actor-shaleeta-boyd-et-al",
                "role": "plaintiff",
                "start_date": "2023-08-11",
                "payload_json": "{}",
            },
        }
        id_map = {"actor-shaleeta-boyd-et-al": "person-shaleeta-boyd-et-al"}
        edges = case_participation_to_edges([cp_node], {}, id_map)
        assert len(edges) == 1
        assert edges[0]["source_id"] == "person-shaleeta-boyd-et-al"
        assert edges[0]["properties"]["role"] == "plaintiff"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/tammypais/projects/marin-civic-graph && python -m pytest tests/test_migration_mapping.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'migration_mapping'`

- [ ] **Step 3: Implement migration_mapping.py**

Create `scripts/migration_mapping.py`:

```python
"""Pure mapping rules for migrating graph-v1 to the settled ontology.

No I/O — all functions take dicts and return dicts. Fully testable.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# ID prefix remapping
# ---------------------------------------------------------------------------

def migrate_id(old_id: str, node_type: str, properties: dict) -> str:
    if node_type == "Actor":
        actor_type = properties.get("actor_type", "unknown")
        prefix = "person-" if actor_type == "person" else "org-"
        return prefix + old_id.removeprefix("actor-")
    if node_type == "Institution":
        return "org-" + old_id.removeprefix("inst-")
    if node_type == "EconomicInterestDisclosure":
        return "filing-" + old_id.removeprefix("eid-")
    return old_id


def _remap_id_ref(value: str, id_map: dict[str, str]) -> str:
    return id_map.get(value, value)


def _remap_property_refs(properties: dict, id_map: dict[str, str]) -> dict:
    out = {}
    for key, value in properties.items():
        if key == "payload_json":
            out[key] = value
            continue
        if isinstance(value, str) and (
            key.endswith("_id") or key.endswith("_actor_id") or key.endswith("_institution_id")
        ):
            out[key] = _remap_id_ref(value, id_map)
        elif isinstance(value, list) and key.endswith("_ids"):
            out[key] = [_remap_id_ref(v, id_map) if isinstance(v, str) else v for v in value]
        else:
            out[key] = value
    return out


# ---------------------------------------------------------------------------
# Actor type -> Organization sublabel mapping
# ---------------------------------------------------------------------------

_ACTOR_TYPE_TO_LABELS = {
    "person": ["Person"],
    "business": ["Organization", "Business"],
    "nonprofit": ["Organization", "Nonprofit"],
    "organization": ["Organization", "Nonprofit"],
    "political_committee": ["Organization", "Political"],
    "government_agency": ["Organization", "Government"],
    "institutional_actor": ["Organization"],
    "unknown": ["Organization"],
}

_INSTITUTION_TYPE_TO_LABELS = {
    "city_government": ["Organization", "Government"],
    "council": ["Organization", "Government"],
    "county_government": ["Organization", "Government"],
    "court": ["Organization", "Court"],
    "filing_officer": ["Organization", "Government"],
    "municipality": ["Organization", "Government"],
    "state_agency": ["Organization", "Government"],
    "state_ethics_agency": ["Organization", "Government"],
}


# ---------------------------------------------------------------------------
# Node migration
# ---------------------------------------------------------------------------

def migrate_node(node: dict) -> dict | None:
    node_type = node["node_type"]
    old_id = node["id"]
    props = dict(node["properties"])

    # CaseParticipation is collapsed into edges — handled separately
    if node_type == "CaseParticipation":
        return None

    new_id = migrate_id(old_id, node_type, props)

    # Build a preliminary id_map for self-referential property remapping
    self_map = {}
    if old_id != new_id:
        self_map[old_id] = new_id
    # Also remap any inst-/actor- refs in properties
    for key, value in props.items():
        if isinstance(value, str) and value.startswith("inst-"):
            self_map[value] = "org-" + value.removeprefix("inst-")
        elif isinstance(value, str) and value.startswith("actor-"):
            # We don't know actor_type of referenced actors here, so we can't
            # determine person- vs org-. This will be resolved in the full
            # migration pass. For now, mark for later resolution.
            pass
        elif isinstance(value, str) and value.startswith("eid-"):
            self_map[value] = "filing-" + value.removeprefix("eid-")

    props = _remap_property_refs(props, self_map)

    # Type-specific transforms
    if node_type == "Actor":
        actor_type = props.pop("actor_type", "unknown")
        labels = list(_ACTOR_TYPE_TO_LABELS.get(actor_type, ["Organization"]))
        new_node_type = labels[0]  # "Person" or "Organization"
        # Rename observed_labels -> aliases
        if "observed_labels" in props:
            props["aliases"] = props.pop("observed_labels")
        return _build_migrated_node(new_id, new_node_type, labels, node, props)

    if node_type == "Institution":
        inst_type = props.get("institution_type", "")
        labels = list(_INSTITUTION_TYPE_TO_LABELS.get(inst_type, ["Organization", "Government"]))
        props["subtype"] = props.pop("institution_type", "government")
        return _build_migrated_node(new_id, "Organization", labels, node, props)

    if node_type == "EconomicInterestDisclosure":
        props["filing_type"] = "form_700"
        if "filer_actor_id" in props:
            # Remap filer_actor_id -> filed_by, assume person
            old_filer = props.pop("filer_actor_id")
            props["filed_by"] = "person-" + old_filer.removeprefix("actor-")
        if "disclosure_type" in props:
            props["disclosure_subtype"] = props.pop("disclosure_type")
        return _build_migrated_node(new_id, "Filing", ["Filing"], node, props)

    if node_type == "ValidationCheck":
        result = _build_migrated_node(new_id, "ValidationCheck", ["ValidationCheck"], node, props)
        result["qa_lane"] = True
        return result

    # All other types pass through with property ref remapping only
    labels = [node_type]
    return _build_migrated_node(new_id, node_type, labels, node, props)


def _build_migrated_node(
    new_id: str,
    node_type: str,
    labels: list[str],
    original: dict,
    properties: dict,
) -> dict:
    return {
        "id": new_id,
        "node_type": node_type,
        "labels": labels,
        "display_label": original["display_label"],
        "promotion_state": original["promotion_state"],
        "source_bundle_ids": original["source_bundle_ids"],
        "source_sections": original["source_sections"],
        "source_status": original.get("source_status"),
        "properties": properties,
        "qa_lane": False,
    }


# ---------------------------------------------------------------------------
# Relationship type remapping
# ---------------------------------------------------------------------------

_RELATIONSHIP_MAP = {
    "CAST_VOTE_ON": "CAST_VOTE",
    "HELD_BY_ACTOR": "HELD_BY",
    "CONTROLLED_BY_ACTOR": "CONTROLLED_BY",
    "FILED_BY_ACTOR": "FILED_BY",
    "DECIDED_BY_INSTITUTION": "DECIDED_BY",
    "DECIDED_AT_MEETING": "AT_MEETING",
    "HELD_BY_INSTITUTION": "AT_INSTITUTION",
    "BELONGS_TO_INSTITUTION": "AT_INSTITUTION",
    "SERVES_IN_INSTITUTION": "AT_INSTITUTION",
    "FILED_WITH_INSTITUTION": "FILED_WITH",
    "FILED_WITH_OFFICER": "FILED_WITH",
    "OPERATED_BY_INSTITUTION": "OPERATED_BY",
    "HEARD_IN_COURT": "HEARD_IN",
    "HEARD_BY_JUDGE": "HEARD_BY",
    "INVOLVES_ACTOR": "PARTY_TO",
    "INVOLVES_INSTITUTION": "PARTY_TO",
    "RELATES_TO_VALIDATIONCHECK": "VALIDATES",
    "COMMITTEE_ACTOR": "CONTROLLED_BY",
}

_NODE_TYPE_REMAP = {
    "Actor": None,  # Determined by actor_type at migration time
    "Institution": "Organization",
    "EconomicInterestDisclosure": "Filing",
    "CaseParticipation": None,
}

# Edge source/target types that need to be touched by CaseParticipation
_CASE_PARTICIPATION_EDGE_TYPES = {"PART_OF_CASE", "INVOLVES_ACTOR", "INVOLVES_INSTITUTION"}


# ---------------------------------------------------------------------------
# Edge migration
# ---------------------------------------------------------------------------

def migrate_edge(edge: dict, id_map: dict[str, str]) -> dict | None:
    source_id = edge["source_id"]
    target_id = edge["target_id"]

    # Drop edges that touch CaseParticipation nodes
    if source_id.startswith("casepart-") or target_id.startswith("casepart-"):
        return None

    new_source = id_map.get(source_id, source_id)
    new_target = id_map.get(target_id, target_id)

    rel_type = _RELATIONSHIP_MAP.get(edge["relationship_type"], edge["relationship_type"])

    source_node_type = edge["source_node_type"]
    target_node_type = edge["target_node_type"]
    new_source_type = _NODE_TYPE_REMAP.get(source_node_type, source_node_type)
    new_target_type = _NODE_TYPE_REMAP.get(target_node_type, target_node_type)
    # Resolve None (Actor) based on the new ID prefix
    if new_source_type is None:
        new_source_type = "Person" if new_source.startswith("person-") else "Organization"
    if new_target_type is None:
        new_target_type = "Person" if new_target.startswith("person-") else "Organization"

    # Remap ID references in edge properties
    new_props = _remap_property_refs(dict(edge["properties"]), id_map)

    return {
        "source_id": new_source,
        "source_node_type": new_source_type,
        "target_id": new_target,
        "target_node_type": new_target_type,
        "relationship_type": rel_type,
        "source_bundle_ids": edge["source_bundle_ids"],
        "source_fields": edge["source_fields"],
        "properties": new_props,
    }


# ---------------------------------------------------------------------------
# CaseParticipation -> PARTY_TO edges
# ---------------------------------------------------------------------------

def case_participation_to_edges(
    cp_nodes: list[dict],
    cp_evidence: dict[str, list[str]],
    id_map: dict[str, str],
) -> list[dict]:
    edges = []
    for cp in cp_nodes:
        props = cp["properties"]
        case_id = props["case_id"]
        role = props.get("role", "unknown")
        start_date = props.get("start_date")

        # Determine the party (actor or institution)
        party_id = props.get("actor_id") or props.get("institution_id")
        if not party_id:
            continue
        new_party_id = id_map.get(party_id, party_id)
        party_type = "Person" if new_party_id.startswith("person-") else "Organization"

        edge_props = {"role": role}
        if start_date:
            edge_props["start_date"] = start_date
        evidence = cp_evidence.get(cp["id"], [])
        if evidence:
            edge_props["evidence_record_ids"] = evidence

        edges.append({
            "source_id": new_party_id,
            "source_node_type": party_type,
            "target_id": case_id,
            "target_node_type": "Case",
            "relationship_type": "PARTY_TO",
            "source_bundle_ids": cp["source_bundle_ids"],
            "source_fields": ["case_participation_migration"],
            "properties": edge_props,
        })
    return edges
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/tammypais/projects/marin-civic-graph && python -m pytest tests/test_migration_mapping.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/migration_mapping.py tests/test_migration_mapping.py
git commit -m "feat: add migration mapping module with node/edge/id remapping rules"
```

---

### Task 3: Migration orchestrator

**Files:**
- Create: `scripts/migrate_graph_v2.py`
- Create: `tests/test_migrate_graph_v2.py`

- [ ] **Step 1: Write integration test**

Create `tests/test_migrate_graph_v2.py`:

```python
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from migrate_graph_v2 import run_migration


@pytest.fixture
def mini_graph(tmp_path):
    nodes = [
        {
            "id": "actor-kate-colin",
            "node_type": "Actor",
            "display_label": "Kate Colin",
            "promotion_state": "canonical",
            "source_bundle_ids": ["test"],
            "source_sections": ["actor_candidates"],
            "source_status": None,
            "properties": {"actor_type": "person", "name": "Kate Colin", "observed_labels": ["Kate Colin"], "payload_json": "{}"},
        },
        {
            "id": "inst-san-rafael-city-council",
            "node_type": "Institution",
            "display_label": "San Rafael City Council",
            "promotion_state": "canonical",
            "source_bundle_ids": ["test"],
            "source_sections": ["institution_candidates"],
            "source_status": None,
            "properties": {"institution_type": "council", "name": "San Rafael City Council", "payload_json": "{}"},
        },
        {
            "id": "decision-2024-08-19-resolution-15336",
            "node_type": "Decision",
            "display_label": "Resolution 15336",
            "promotion_state": "promoted",
            "source_bundle_ids": ["test"],
            "source_sections": ["decision_candidates"],
            "source_status": None,
            "properties": {"decided_at": "2024-08-19", "institution_id": "inst-san-rafael-city-council", "payload_json": "{}"},
        },
        {
            "id": "casepart-boyd-city-defendant",
            "node_type": "CaseParticipation",
            "display_label": "casepart-boyd-city-defendant",
            "promotion_state": "promoted",
            "source_bundle_ids": ["test"],
            "source_sections": ["case_participation_candidates"],
            "source_status": None,
            "properties": {"case_id": "case-boyd", "institution_id": "inst-san-rafael-city-council", "role": "defendant", "payload_json": "{}"},
        },
        {
            "id": "case-boyd",
            "node_type": "Case",
            "display_label": "Boyd v. City of San Rafael",
            "promotion_state": "promoted",
            "source_bundle_ids": ["test"],
            "source_sections": ["case_candidates"],
            "source_status": None,
            "properties": {"case_type": "civil", "payload_json": "{}"},
        },
    ]
    edges = [
        {
            "source_id": "actor-kate-colin",
            "source_node_type": "Actor",
            "target_id": "decision-2024-08-19-resolution-15336",
            "target_node_type": "Decision",
            "relationship_type": "CAST_VOTE_ON",
            "source_bundle_ids": ["test"],
            "source_fields": ["votes"],
            "properties": {"vote": "yes"},
        },
        {
            "source_id": "decision-2024-08-19-resolution-15336",
            "source_node_type": "Decision",
            "target_id": "inst-san-rafael-city-council",
            "target_node_type": "Institution",
            "relationship_type": "DECIDED_BY_INSTITUTION",
            "source_bundle_ids": ["test"],
            "source_fields": ["institution_id"],
            "properties": {},
        },
        {
            "source_id": "casepart-boyd-city-defendant",
            "source_node_type": "CaseParticipation",
            "target_id": "case-boyd",
            "target_node_type": "Case",
            "relationship_type": "PART_OF_CASE",
            "source_bundle_ids": ["test"],
            "source_fields": ["case_id"],
            "properties": {},
        },
        {
            "source_id": "casepart-boyd-city-defendant",
            "source_node_type": "CaseParticipation",
            "target_id": "record-dismissal",
            "target_node_type": "Record",
            "relationship_type": "EVIDENCED_BY",
            "source_bundle_ids": ["test"],
            "source_fields": ["evidence_record_ids"],
            "properties": {},
        },
    ]
    nodes_path = tmp_path / "nodes.jsonl"
    edges_path = tmp_path / "edges.jsonl"
    nodes_path.write_text("\n".join(json.dumps(n) for n in nodes) + "\n")
    edges_path.write_text("\n".join(json.dumps(e) for e in edges) + "\n")
    return tmp_path


def test_migration_output_files(mini_graph):
    out_dir = mini_graph / "output"
    run_migration(
        nodes_path=mini_graph / "nodes.jsonl",
        edges_path=mini_graph / "edges.jsonl",
        output_dir=out_dir,
    )
    assert (out_dir / "nodes.jsonl").exists()
    assert (out_dir / "edges.jsonl").exists()
    assert (out_dir / "id-map.json").exists()
    assert (out_dir / "migration-report.json").exists()


def test_migration_node_counts(mini_graph):
    out_dir = mini_graph / "output"
    run_migration(
        nodes_path=mini_graph / "nodes.jsonl",
        edges_path=mini_graph / "edges.jsonl",
        output_dir=out_dir,
    )
    nodes = [json.loads(line) for line in (out_dir / "nodes.jsonl").read_text().strip().split("\n")]
    # 5 input nodes - 1 CaseParticipation = 4 output nodes
    assert len(nodes) == 4
    types = {n["node_type"] for n in nodes}
    assert "Person" in types
    assert "Organization" in types
    assert "Decision" in types
    assert "Case" in types
    assert "CaseParticipation" not in types


def test_migration_edge_counts(mini_graph):
    out_dir = mini_graph / "output"
    run_migration(
        nodes_path=mini_graph / "nodes.jsonl",
        edges_path=mini_graph / "edges.jsonl",
        output_dir=out_dir,
    )
    edges = [json.loads(line) for line in (out_dir / "edges.jsonl").read_text().strip().split("\n")]
    # 4 input edges:
    #   CAST_VOTE_ON -> CAST_VOTE (kept)
    #   DECIDED_BY_INSTITUTION -> DECIDED_BY (kept)
    #   PART_OF_CASE from CaseParticipation (dropped)
    #   EVIDENCED_BY from CaseParticipation (dropped)
    # + 1 new PARTY_TO edge from CaseParticipation conversion
    # = 3 edges
    assert len(edges) == 3
    rel_types = {e["relationship_type"] for e in edges}
    assert "CAST_VOTE" in rel_types
    assert "DECIDED_BY" in rel_types
    assert "PARTY_TO" in rel_types


def test_migration_id_map(mini_graph):
    out_dir = mini_graph / "output"
    run_migration(
        nodes_path=mini_graph / "nodes.jsonl",
        edges_path=mini_graph / "edges.jsonl",
        output_dir=out_dir,
    )
    id_map = json.loads((out_dir / "id-map.json").read_text())
    assert id_map["actor-kate-colin"] == "person-kate-colin"
    assert id_map["inst-san-rafael-city-council"] == "org-san-rafael-city-council"
    assert "decision-2024-08-19-resolution-15336" not in id_map  # unchanged IDs not in map
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/tammypais/projects/marin-civic-graph && python -m pytest tests/test_migrate_graph_v2.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'migrate_graph_v2'`

- [ ] **Step 3: Implement migrate_graph_v2.py**

Create `scripts/migrate_graph_v2.py`:

```python
#!/usr/bin/env python3
"""Migrate graph-v1 JSONL to settled ontology (graph-v2).

Reads nodes.jsonl and edges.jsonl from graph-v1, applies the migration
mapping, and writes settled-schema JSONL plus an ID map and report.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from migration_mapping import (
    case_participation_to_edges,
    migrate_edge,
    migrate_id,
    migrate_node,
)


def _read_jsonl(path: Path) -> list[dict]:
    nodes = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                nodes.append(json.loads(line))
    return nodes


def _write_jsonl(path: Path, items: list[dict]) -> None:
    with open(path, "w") as f:
        for item in items:
            f.write(json.dumps(item, sort_keys=True) + "\n")


def run_migration(
    nodes_path: Path,
    edges_path: Path,
    output_dir: Path,
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)

    raw_nodes = _read_jsonl(nodes_path)
    raw_edges = _read_jsonl(edges_path)

    # --- Pass 1: Build ID map from all nodes ---
    id_map: dict[str, str] = {}
    for node in raw_nodes:
        old_id = node["id"]
        new_id = migrate_id(old_id, node["node_type"], node["properties"])
        if old_id != new_id:
            id_map[old_id] = new_id

    # --- Pass 2: Migrate nodes ---
    migrated_nodes: list[dict] = []
    cp_nodes: list[dict] = []
    stats: dict[str, Counter] = {
        "nodes_by_type": Counter(),
        "dropped_nodes": Counter(),
        "edges_by_type": Counter(),
        "dropped_edges": Counter(),
    }

    for node in raw_nodes:
        if node["node_type"] == "CaseParticipation":
            cp_nodes.append(node)
            stats["dropped_nodes"]["CaseParticipation"] += 1
            continue
        result = migrate_node(node)
        if result is None:
            stats["dropped_nodes"][node["node_type"]] += 1
            continue
        # Second pass: remap any actor-/inst- refs in properties using full id_map
        props = result["properties"]
        for key, value in list(props.items()):
            if key == "payload_json":
                continue
            if isinstance(value, str) and value in id_map:
                props[key] = id_map[value]
            elif isinstance(value, list):
                props[key] = [id_map.get(v, v) if isinstance(v, str) else v for v in value]
        migrated_nodes.append(result)
        stats["nodes_by_type"][result["node_type"]] += 1

    # --- Pass 3: Collect CaseParticipation evidence for edge conversion ---
    cp_evidence: dict[str, list[str]] = {}
    for edge in raw_edges:
        if (
            edge["source_id"].startswith("casepart-")
            and edge["relationship_type"] == "EVIDENCED_BY"
        ):
            cp_evidence.setdefault(edge["source_id"], []).append(edge["target_id"])

    # --- Pass 4: Migrate edges ---
    migrated_edges: list[dict] = []
    for edge in raw_edges:
        result = migrate_edge(edge, id_map)
        if result is None:
            stats["dropped_edges"][edge["relationship_type"]] += 1
            continue
        migrated_edges.append(result)
        stats["edges_by_type"][result["relationship_type"]] += 1

    # --- Pass 5: Convert CaseParticipation to PARTY_TO edges ---
    party_edges = case_participation_to_edges(cp_nodes, cp_evidence, id_map)
    migrated_edges.extend(party_edges)
    stats["edges_by_type"]["PARTY_TO"] += len(party_edges)

    # --- Write outputs ---
    _write_jsonl(output_dir / "nodes.jsonl", migrated_nodes)
    _write_jsonl(output_dir / "edges.jsonl", migrated_edges)

    # Only include remapped IDs in the map (not unchanged ones)
    (output_dir / "id-map.json").write_text(json.dumps(id_map, indent=2, sort_keys=True) + "\n")

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_nodes": len(raw_nodes),
        "source_edges": len(raw_edges),
        "migrated_nodes": len(migrated_nodes),
        "migrated_edges": len(migrated_edges),
        "nodes_by_type": dict(stats["nodes_by_type"].most_common()),
        "edges_by_type": dict(stats["edges_by_type"].most_common()),
        "dropped_nodes": dict(stats["dropped_nodes"].most_common()),
        "dropped_edges": dict(stats["dropped_edges"].most_common()),
        "id_remaps": len(id_map),
        "case_participation_conversions": len(party_edges),
    }
    (output_dir / "migration-report.json").write_text(json.dumps(report, indent=2) + "\n")

    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate graph-v1 to settled ontology")
    parser.add_argument("--input-dir", default="data/projected/graph-v1", help="Directory with source nodes.jsonl and edges.jsonl")
    parser.add_argument("--output-dir", default="data/projected/graph-v2", help="Output directory for migrated JSONL")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    input_dir = root / args.input_dir
    output_dir = root / args.output_dir

    report = run_migration(
        nodes_path=input_dir / "nodes.jsonl",
        edges_path=input_dir / "edges.jsonl",
        output_dir=output_dir,
    )

    print(f"Migration complete:")
    print(f"  Nodes: {report['source_nodes']} -> {report['migrated_nodes']}")
    print(f"  Edges: {report['source_edges']} -> {report['migrated_edges']}")
    print(f"  ID remaps: {report['id_remaps']}")
    print(f"  CaseParticipation -> PARTY_TO: {report['case_participation_conversions']}")
    print(f"  Report: {output_dir / 'migration-report.json'}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/tammypais/projects/marin-civic-graph && python -m pytest tests/test_migrate_graph_v2.py -v`
Expected: All tests PASS

- [ ] **Step 5: Run migration against real data**

Run: `cd /Users/tammypais/projects/marin-civic-graph && python scripts/migrate_graph_v2.py`
Expected output (approximate):
```
Migration complete:
  Nodes: 6267 -> 6258  (9 CaseParticipation dropped)
  Edges: 21262 -> ~21230  (CP edges dropped, PARTY_TO edges added)
  ID remaps: ~66  (53 actors + 12 institutions + 21 EIDs - overlaps)
  CaseParticipation -> PARTY_TO: 9
```

- [ ] **Step 6: Verify migration report**

Run: `cat data/projected/graph-v2/migration-report.json | python -m json.tool`
Verify: node counts match expectations, no unexpected dropped nodes, all expected types present

- [ ] **Step 7: Commit**

```bash
git add scripts/migrate_graph_v2.py tests/test_migrate_graph_v2.py
git commit -m "feat: add graph migration orchestrator (graph-v1 -> settled ontology)"
```

---

### Task 4: Neo4j schema definition

**Files:**
- Create: `registry/neo4j-schema.cypher`

- [ ] **Step 1: Write the schema file**

Create `registry/neo4j-schema.cypher`:

```cypher
// Auto-generated schema for Marin Civic Graph settled ontology
// Run this BEFORE loading data

// ---------------------------------------------------------------------------
// Unique constraints (one per core node type)
// ---------------------------------------------------------------------------
CREATE CONSTRAINT person_id_unique IF NOT EXISTS FOR (n:Person) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT organization_id_unique IF NOT EXISTS FOR (n:Organization) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT committee_id_unique IF NOT EXISTS FOR (n:Committee) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT seat_id_unique IF NOT EXISTS FOR (n:Seat) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT seatservice_id_unique IF NOT EXISTS FOR (n:SeatService) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT election_id_unique IF NOT EXISTS FOR (n:Election) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT candidacy_id_unique IF NOT EXISTS FOR (n:Candidacy) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT meeting_id_unique IF NOT EXISTS FOR (n:Meeting) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT agendaitem_id_unique IF NOT EXISTS FOR (n:AgendaItem) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT decision_id_unique IF NOT EXISTS FOR (n:Decision) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT filing_id_unique IF NOT EXISTS FOR (n:Filing) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT moneyflow_id_unique IF NOT EXISTS FOR (n:MoneyFlow) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT case_id_unique IF NOT EXISTS FOR (n:Case) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT proceeding_id_unique IF NOT EXISTS FOR (n:Proceeding) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT project_id_unique IF NOT EXISTS FOR (n:Project) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT program_id_unique IF NOT EXISTS FOR (n:Program) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT agreement_id_unique IF NOT EXISTS FOR (n:Agreement) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT amendment_id_unique IF NOT EXISTS FOR (n:Amendment) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT record_id_unique IF NOT EXISTS FOR (n:Record) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT place_id_unique IF NOT EXISTS FOR (n:Place) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT issue_id_unique IF NOT EXISTS FOR (n:Issue) REQUIRE n.id IS UNIQUE;

// QA lane
CREATE CONSTRAINT validationcheck_id_unique IF NOT EXISTS FOR (n:ValidationCheck) REQUIRE n.id IS UNIQUE;

// ---------------------------------------------------------------------------
// Full-text indexes (names and display labels)
// ---------------------------------------------------------------------------
CREATE FULLTEXT INDEX entity_names IF NOT EXISTS
FOR (n:Person|Organization|Committee|Project|Program|Case|Agreement)
ON EACH [n.name, n.display_label];

// ---------------------------------------------------------------------------
// Property indexes (dates, types, amounts)
// ---------------------------------------------------------------------------
CREATE INDEX meeting_date IF NOT EXISTS FOR (n:Meeting) ON (n.meeting_date);
CREATE INDEX decision_decided_at IF NOT EXISTS FOR (n:Decision) ON (n.decided_at);
CREATE INDEX moneyflow_flow_date IF NOT EXISTS FOR (n:MoneyFlow) ON (n.flow_date);
CREATE INDEX moneyflow_amount IF NOT EXISTS FOR (n:MoneyFlow) ON (n.amount);
CREATE INDEX filing_signed_at IF NOT EXISTS FOR (n:Filing) ON (n.signed_at);
CREATE INDEX filing_filed_at IF NOT EXISTS FOR (n:Filing) ON (n.filed_at);
CREATE INDEX election_date IF NOT EXISTS FOR (n:Election) ON (n.election_date);
CREATE INDEX proceeding_date IF NOT EXISTS FOR (n:Proceeding) ON (n.date);
CREATE INDEX agreement_effective_date IF NOT EXISTS FOR (n:Agreement) ON (n.effective_date);

CREATE INDEX moneyflow_flow_type IF NOT EXISTS FOR (n:MoneyFlow) ON (n.flow_type);
CREATE INDEX filing_filing_type IF NOT EXISTS FOR (n:Filing) ON (n.filing_type);
CREATE INDEX decision_decision_type IF NOT EXISTS FOR (n:Decision) ON (n.decision_type);
```

- [ ] **Step 2: Commit**

```bash
git add registry/neo4j-schema.cypher
git commit -m "feat: add Neo4j schema with constraints, full-text, and property indexes"
```

---

### Task 5: Batched Neo4j loader

**Files:**
- Create: `scripts/load_neo4j_v2.py`
- Create: `tests/test_load_neo4j_v2.py`

- [ ] **Step 1: Write the test**

Create `tests/test_load_neo4j_v2.py`:

```python
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, call

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from load_neo4j_v2 import build_node_batch_query, build_edge_batch_query, chunk_list


class TestChunkList:
    def test_even_split(self):
        result = list(chunk_list([1, 2, 3, 4], 2))
        assert result == [[1, 2], [3, 4]]

    def test_remainder(self):
        result = list(chunk_list([1, 2, 3], 2))
        assert result == [[1, 2], [3]]

    def test_empty(self):
        result = list(chunk_list([], 2))
        assert result == []


class TestBuildNodeBatchQuery:
    def test_single_label(self):
        query, params = build_node_batch_query("Decision", ["Decision"])
        assert "UNWIND $batch AS row" in query
        assert "MERGE (n:Decision {id: row.id})" in query
        assert "SET n += row.props" in query

    def test_multi_label(self):
        query, params = build_node_batch_query("Organization", ["Organization", "Government"])
        assert "SET n:Organization:Government" in query


class TestBuildEdgeBatchQuery:
    def test_basic(self):
        query = build_edge_batch_query("CAST_VOTE")
        assert "UNWIND $batch AS row" in query
        assert "MERGE (s)-[r:CAST_VOTE]->(t)" in query
        assert "SET r += row.props" in query
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/tammypais/projects/marin-civic-graph && python -m pytest tests/test_load_neo4j_v2.py -v`
Expected: FAIL

- [ ] **Step 3: Implement the loader**

Create `scripts/load_neo4j_v2.py`:

```python
#!/usr/bin/env python3
"""Load migrated graph-v2 JSONL into Neo4j AuraDB via the Python driver.

Uses batched UNWIND writes for performance. Applies schema (constraints +
indexes) before loading data.
"""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter, defaultdict
from pathlib import Path

from neo4j import GraphDatabase


def chunk_list(lst: list, size: int) -> list[list]:
    for i in range(0, len(lst), size):
        yield lst[i : i + size]


def _read_jsonl(path: Path) -> list[dict]:
    items = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return items


def build_node_batch_query(node_type: str, labels: list[str]) -> tuple[str, dict]:
    label_str = ":".join(labels)
    query = f"""
    UNWIND $batch AS row
    MERGE (n:{node_type} {{id: row.id}})
    SET n:{label_str}
    SET n += row.props
    SET n.display_label = row.display_label
    SET n.promotion_state = row.promotion_state
    """
    return query, {}


def build_edge_batch_query(relationship_type: str) -> str:
    return f"""
    UNWIND $batch AS row
    MATCH (s {{id: row.source_id}})
    MATCH (t {{id: row.target_id}})
    MERGE (s)-[r:{relationship_type}]->(t)
    SET r += row.props
    """


def apply_schema(driver, schema_path: Path) -> None:
    schema_text = schema_path.read_text()
    statements = [
        s.strip()
        for s in schema_text.split(";")
        if s.strip() and not s.strip().startswith("//")
    ]
    with driver.session() as session:
        for stmt in statements:
            session.run(stmt + ";")
    print(f"Applied {len(statements)} schema statements")


def load_nodes(driver, nodes: list[dict], batch_size: int = 500) -> Counter:
    # Group nodes by their label set for batched creation
    by_labels: dict[tuple[str, ...], list[dict]] = defaultdict(list)
    for node in nodes:
        labels = tuple(node["labels"])
        node_type = node["node_type"]
        by_labels[(node_type, *labels)].append(node)

    counts = Counter()
    with driver.session() as session:
        for key, group in by_labels.items():
            node_type = key[0]
            labels = list(key[1:])
            query, _ = build_node_batch_query(node_type, labels)

            for batch in chunk_list(group, batch_size):
                rows = [
                    {
                        "id": n["id"],
                        "display_label": n["display_label"],
                        "promotion_state": n["promotion_state"],
                        "props": {
                            k: v
                            for k, v in n["properties"].items()
                            if k != "payload_json"
                        },
                    }
                    for n in batch
                ]
                session.run(query, batch=rows)
                counts[node_type] += len(rows)

    return counts


def load_edges(driver, edges: list[dict], batch_size: int = 500) -> Counter:
    by_type: dict[str, list[dict]] = defaultdict(list)
    for edge in edges:
        by_type[edge["relationship_type"]].append(edge)

    counts = Counter()
    with driver.session() as session:
        for rel_type, group in by_type.items():
            query = build_edge_batch_query(rel_type)

            for batch in chunk_list(group, batch_size):
                rows = [
                    {
                        "source_id": e["source_id"],
                        "target_id": e["target_id"],
                        "props": e["properties"],
                    }
                    for e in batch
                ]
                session.run(query, batch=rows)
                counts[rel_type] += len(rows)

    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="Load graph-v2 into Neo4j AuraDB")
    parser.add_argument("--input-dir", default="data/projected/graph-v2")
    parser.add_argument("--schema", default="registry/neo4j-schema.cypher")
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--uri", default=os.getenv("NEO4J_URI", "bolt://localhost:7687"))
    parser.add_argument("--user", default=os.getenv("NEO4J_USER", "neo4j"))
    parser.add_argument("--password", default=os.getenv("NEO4J_PASSWORD"))
    parser.add_argument("--database", default=os.getenv("NEO4J_DATABASE", "neo4j"))
    parser.add_argument("--skip-schema", action="store_true", help="Skip schema creation")
    args = parser.parse_args()

    if not args.password:
        raise SystemExit("NEO4J_PASSWORD is required. Set via env var or --password.")

    root = Path(__file__).resolve().parent.parent
    input_dir = root / args.input_dir
    schema_path = root / args.schema

    driver = GraphDatabase.driver(args.uri, auth=(args.user, args.password))

    try:
        driver.verify_connectivity()
        print(f"Connected to {args.uri}")

        if not args.skip_schema:
            apply_schema(driver, schema_path)

        print("Loading nodes...")
        nodes = _read_jsonl(input_dir / "nodes.jsonl")
        node_counts = load_nodes(driver, nodes, args.batch_size)
        for ntype, count in node_counts.most_common():
            print(f"  {ntype}: {count}")

        print("Loading edges...")
        edges = _read_jsonl(input_dir / "edges.jsonl")
        edge_counts = load_edges(driver, edges, args.batch_size)
        for rtype, count in edge_counts.most_common():
            print(f"  {rtype}: {count}")

        print(f"\nDone: {sum(node_counts.values())} nodes, {sum(edge_counts.values())} edges")
    finally:
        driver.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/tammypais/projects/marin-civic-graph && python -m pytest tests/test_load_neo4j_v2.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/load_neo4j_v2.py tests/test_load_neo4j_v2.py
git commit -m "feat: add batched Neo4j loader with UNWIND writes and schema application"
```

---

### Task 6: Verification queries

**Files:**
- Create: `scripts/verify_neo4j_v2.py`

- [ ] **Step 1: Write the verification script**

Create `scripts/verify_neo4j_v2.py`:

```python
#!/usr/bin/env python3
"""Verify the loaded Neo4j graph matches migration expectations.

Runs count checks, sample queries, and the 6 investigation use case
smoke tests.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from neo4j import GraphDatabase


def run_verification(driver, expected_report_path: Path | None = None) -> dict:
    results = {"checks": [], "passed": 0, "failed": 0}

    def check(name: str, query: str, assertion_fn):
        with driver.session() as session:
            result = session.run(query)
            records = [dict(r) for r in result]
        try:
            assertion_fn(records)
            results["checks"].append({"name": name, "status": "PASS"})
            results["passed"] += 1
            print(f"  PASS: {name}")
        except AssertionError as e:
            results["checks"].append({"name": name, "status": "FAIL", "error": str(e)})
            results["failed"] += 1
            print(f"  FAIL: {name} — {e}")

    # --- Node count checks ---
    check(
        "Person nodes exist",
        "MATCH (n:Person) RETURN count(n) AS cnt",
        lambda r: assert_gt(r[0]["cnt"], 0, "Expected Person nodes"),
    )
    check(
        "Organization nodes exist",
        "MATCH (n:Organization) RETURN count(n) AS cnt",
        lambda r: assert_gt(r[0]["cnt"], 0, "Expected Organization nodes"),
    )
    check(
        "Decision nodes exist",
        "MATCH (n:Decision) RETURN count(n) AS cnt",
        lambda r: assert_gt(r[0]["cnt"], 1000, "Expected >1000 Decision nodes"),
    )
    check(
        "No CaseParticipation nodes",
        "MATCH (n:CaseParticipation) RETURN count(n) AS cnt",
        lambda r: assert_eq(r[0]["cnt"], 0, "CaseParticipation should not exist"),
    )
    check(
        "No Actor nodes (migrated away)",
        "MATCH (n:Actor) RETURN count(n) AS cnt",
        lambda r: assert_eq(r[0]["cnt"], 0, "Actor should not exist"),
    )
    check(
        "No Institution nodes (migrated away)",
        "MATCH (n:Institution) RETURN count(n) AS cnt",
        lambda r: assert_eq(r[0]["cnt"], 0, "Institution should not exist"),
    )

    # --- Relationship checks ---
    check(
        "CAST_VOTE edges exist",
        "MATCH ()-[r:CAST_VOTE]->() RETURN count(r) AS cnt",
        lambda r: assert_gt(r[0]["cnt"], 0, "Expected CAST_VOTE edges"),
    )
    check(
        "PARTY_TO edges exist",
        "MATCH ()-[r:PARTY_TO]->() RETURN count(r) AS cnt",
        lambda r: assert_gt(r[0]["cnt"], 0, "Expected PARTY_TO edges"),
    )
    check(
        "No CAST_VOTE_ON edges (renamed)",
        "MATCH ()-[r:CAST_VOTE_ON]->() RETURN count(r) AS cnt",
        lambda r: assert_eq(r[0]["cnt"], 0, "CAST_VOTE_ON should be migrated"),
    )

    # --- Investigation smoke tests ---
    check(
        "Kate Colin is a Person with CAST_VOTE edges",
        """
        MATCH (p:Person {id: 'person-kate-colin'})-[v:CAST_VOTE]->(d:Decision)
        RETURN p.name AS name, count(v) AS vote_count
        """,
        lambda r: (
            assert_eq(r[0]["name"], "Kate Colin", "Expected Kate Colin"),
            assert_gt(r[0]["vote_count"], 50, "Expected many votes"),
        ),
    )
    check(
        "Boyd case has PARTY_TO edges",
        """
        MATCH (party)-[r:PARTY_TO]->(c:Case {id: 'case-boyd-v-city-of-san-rafael'})
        RETURN party.name AS name, r.role AS role
        ORDER BY role
        """,
        lambda r: assert_gt(len(r), 0, "Expected parties in Boyd case"),
    )
    check(
        "Merrydale project has linked decisions",
        """
        MATCH (d:Decision)-[:ABOUT_PROJECT]->(p:Project)
        WHERE p.id CONTAINS 'merrydale'
        RETURN count(d) AS cnt
        """,
        lambda r: assert_gt(r[0]["cnt"], 0, "Expected decisions linked to Merrydale"),
    )
    check(
        "MoneyFlow nodes have amounts",
        """
        MATCH (m:MoneyFlow)
        WHERE m.amount IS NOT NULL AND m.amount > 0
        RETURN count(m) AS cnt
        """,
        lambda r: assert_gt(r[0]["cnt"], 0, "Expected MoneyFlow nodes with amounts"),
    )
    check(
        "Multi-label Organization:Government exists",
        """
        MATCH (o:Organization:Government)
        RETURN count(o) AS cnt
        """,
        lambda r: assert_gt(r[0]["cnt"], 0, "Expected Government-labeled organizations"),
    )

    return results


def assert_gt(actual, expected, msg):
    assert actual > expected, f"{msg}: got {actual}, expected > {expected}"


def assert_eq(actual, expected, msg):
    assert actual == expected, f"{msg}: got {actual}, expected {expected}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify Neo4j graph-v2 load")
    parser.add_argument("--uri", default=os.getenv("NEO4J_URI", "bolt://localhost:7687"))
    parser.add_argument("--user", default=os.getenv("NEO4J_USER", "neo4j"))
    parser.add_argument("--password", default=os.getenv("NEO4J_PASSWORD"))
    parser.add_argument("--database", default=os.getenv("NEO4J_DATABASE", "neo4j"))
    args = parser.parse_args()

    if not args.password:
        raise SystemExit("NEO4J_PASSWORD is required.")

    driver = GraphDatabase.driver(args.uri, auth=(args.user, args.password))
    try:
        driver.verify_connectivity()
        print(f"Connected to {args.uri}\n")
        print("Running verification checks:")
        results = run_verification(driver)
        print(f"\nResults: {results['passed']} passed, {results['failed']} failed")
        if results["failed"] > 0:
            raise SystemExit(1)
    finally:
        driver.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Commit**

```bash
git add scripts/verify_neo4j_v2.py
git commit -m "feat: add Neo4j verification script with count checks and investigation smoke tests"
```

---

### Task 7: End-to-end run

**Files:**
- No new files — this task executes the pipeline

- [ ] **Step 1: Run all unit tests**

Run: `cd /Users/tammypais/projects/marin-civic-graph && python -m pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 2: Run migration on real data**

Run: `cd /Users/tammypais/projects/marin-civic-graph && python scripts/migrate_graph_v2.py`
Expected: Migration report printed, files written to `data/projected/graph-v2/`

- [ ] **Step 3: Review migration report**

Run: `python -m json.tool data/projected/graph-v2/migration-report.json`

Verify:
- `migrated_nodes` ~ 6258 (6267 - 9 CaseParticipation)
- `migrated_edges` ~ 21230 (21262 - dropped CP edges + new PARTY_TO)
- `nodes_by_type` includes Person, Organization, Decision, Meeting, Filing, etc.
- `dropped_nodes` shows CaseParticipation: 9
- No unexpected types in dropped_nodes

- [ ] **Step 4: Spot-check ID map**

Run: `python -c "import json; m = json.load(open('data/projected/graph-v2/id-map.json')); print(f'{len(m)} remapped IDs'); [print(f'  {k} -> {v}') for k, v in list(m.items())[:10]]"`

Verify: actor- prefixes map to person- or org-, inst- prefixes map to org-, eid- prefixes map to filing-

- [ ] **Step 5: Set up Neo4j AuraDB**

Manual steps (Stuart):
1. Create an AuraDB instance at https://console.neo4j.io/
2. Note the connection URI, username, and password
3. Set environment variables:
```bash
export NEO4J_URI="neo4j+s://xxxxxxxx.databases.neo4j.io"
export NEO4J_USER="neo4j"
export NEO4J_PASSWORD="your-password"
```

- [ ] **Step 6: Load into Neo4j**

Run: `cd /Users/tammypais/projects/marin-civic-graph && python scripts/load_neo4j_v2.py`

Expected: Schema applied, nodes loaded, edges loaded, final counts printed

- [ ] **Step 7: Run verification**

Run: `cd /Users/tammypais/projects/marin-civic-graph && python scripts/verify_neo4j_v2.py`

Expected: All checks PASS. If any fail, investigate and fix before proceeding.

- [ ] **Step 8: Commit migrated data and final state**

```bash
git add data/projected/graph-v2/ registry/neo4j-schema.cypher
git commit -m "feat: complete graph-v1 to settled ontology migration — 21 types, loaded to Neo4j"
```

---

## Appendix: Expected Migration Stats

Based on actual graph-v1 data:

| Current Type | Count | Target Type | Notes |
|---|---|---|---|
| Actor (person) | 23 | Person | ID: actor- -> person- |
| Actor (business) | 15 | Organization:Business | ID: actor- -> org- |
| Actor (nonprofit) | 4 | Organization:Nonprofit | ID: actor- -> org- |
| Actor (political_committee) | 2 | Organization:Political | ID: actor- -> org- |
| Actor (government_agency) | 1 | Organization:Government | ID: actor- -> org- |
| Actor (institutional_actor) | 1 | Organization | ID: actor- -> org- |
| Actor (unknown) | 7 | Organization | ID: actor- -> org- |
| Institution (council) | 1 | Organization:Government | ID: inst- -> org- |
| Institution (city_government) | 1 | Organization:Government | ID: inst- -> org- |
| Institution (county_government) | 1 | Organization:Government | ID: inst- -> org- |
| Institution (court) | 4 | Organization:Court | ID: inst- -> org- |
| Institution (municipality) | 2 | Organization:Government | ID: inst- -> org- |
| Institution (state_agency) | 1 | Organization:Government | ID: inst- -> org- |
| Institution (state_ethics_agency) | 1 | Organization:Government | ID: inst- -> org- |
| Institution (filing_officer) | 1 | Organization:Government | ID: inst- -> org- |
| EconomicInterestDisclosure | 21 | Filing | ID: eid- -> filing-, filing_type=form_700 |
| CaseParticipation | 9 | _(dropped, -> PARTY_TO edges)_ | 9 new PARTY_TO edges created |
| ValidationCheck | 16 | ValidationCheck (QA lane) | qa_lane=true flag |
| All other types | 6,156 | _(unchanged)_ | Property refs remapped |
