"""migration_mapping.py — pure mapping rules for the Marin Civic Graph schema migration.

Transforms graph nodes and edges from the legacy 28-type schema to the settled 21-type
ontology.  No I/O — all functions are pure transforms operating on plain dicts.

Node type remapping summary:
  Actor (person)       → Person,       actor- → person-
  Actor (org-like)     → Organization, actor- → org-
  Institution          → Organization, inst-  → org-
  EconomicInterest…    → Filing,       eid-   → filing-
  CaseParticipation    → dropped (None); converted to PARTY_TO edges separately
  ValidationCheck      → ValidationCheck, qa_lane=True
  All others           → pass-through, property refs remapped

Relationship type remapping:  see REL_TYPE_MAP below.
"""

from __future__ import annotations

import copy
from typing import Optional


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Actor actor_type values that map to Organization (explicitly organizational)
_ORG_ACTOR_TYPES = {
    "business",
    "nonprofit",
    "organization",
    "political_committee",
    "government_agency",
    "institutional_actor",
}

# Multi-label rules for Actor → Organization
_ACTOR_ORG_LABELS: dict[str, list[str]] = {
    "business": ["Organization", "Business"],
    "nonprofit": ["Organization", "Nonprofit"],
    "organization": ["Organization", "Nonprofit"],
    "political_committee": ["Organization", "Political"],
    "government_agency": ["Organization", "Government"],
    "institutional_actor": ["Organization"],
}

# Actor types that default to Person (including missing/unknown —
# safer to reclassify a person as org than to corrupt person-as-org edges)
_PERSON_ACTOR_TYPES = {"person", "unknown", ""}

# Institution institution_type → label suffix
_GOVERNMENT_INSTITUTION_TYPES = {
    "city_government",
    "council",
    "county_government",
    "municipality",
    "filing_officer",
    "state_agency",
    "state_ethics_agency",
}

# Relationship type renames (old → new)
REL_TYPE_MAP: dict[str, str] = {
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


# ---------------------------------------------------------------------------
# ID remapping helpers
# ---------------------------------------------------------------------------

def migrate_id(old_id: str, node_type: str, properties: dict) -> str:
    """Return the migrated ID for a node, applying prefix remapping rules.

    Actor (person)      → person-<rest>
    Actor (org-like)    → org-<rest>
    Institution         → org-<rest>
    EID                 → filing-<rest>
    All others          → unchanged
    """
    if node_type == "Actor":
        actor_type = properties.get("actor_type", "")
        rest = old_id[len("actor-"):]
        # Explicitly organizational types get org- prefix
        if actor_type in ("business", "nonprofit", "organization",
                          "political_committee", "government_agency",
                          "institutional_actor"):
            return f"org-{rest}"
        # Everything else (person, unknown, missing, judges, plaintiffs)
        # defaults to person- — safer to reclassify a person as an org
        # than to recover from corrupted person-as-org edges
        return f"person-{rest}"

    if node_type == "Institution":
        rest = old_id[len("inst-"):]
        return f"org-{rest}"

    if node_type == "EconomicInterestDisclosure":
        rest = old_id[len("eid-"):]
        return f"filing-{rest}"

    return old_id


def _remap_prop_value(value: str, id_map: Optional[dict[str, str]] = None) -> str:
    """Remap a single string property value using prefix rules and optional id_map.

    Handles:
      inst-* → org-*
      eid-*  → filing-*
      id_map lookups (for full actor- and other arbitrary IDs)
    """
    if id_map and value in id_map:
        return id_map[value]
    if value.startswith("inst-"):
        return "org-" + value[len("inst-"):]
    if value.startswith("eid-"):
        return "filing-" + value[len("eid-"):]
    return value


def _remap_props(props: dict, id_map: Optional[dict[str, str]] = None) -> dict:
    """Return a copy of props with all string values remapped via prefix/id_map rules."""
    result = {}
    for k, v in props.items():
        if isinstance(v, str):
            result[k] = _remap_prop_value(v, id_map)
        elif isinstance(v, list):
            result[k] = [
                _remap_prop_value(item, id_map) if isinstance(item, str) else item
                for item in v
            ]
        else:
            result[k] = v
    return result


def _node_type_from_new_id(new_id: str, old_node_type: str) -> str:
    """Infer the migrated node_type from the new ID prefix."""
    if new_id.startswith("person-"):
        return "Person"
    if new_id.startswith("org-"):
        return "Organization"
    if new_id.startswith("filing-"):
        return "Filing"
    # Fallback: use old type (already correct for pass-through types)
    return old_node_type


# ---------------------------------------------------------------------------
# migrate_node
# ---------------------------------------------------------------------------

def migrate_node(node: dict) -> Optional[dict]:
    """Transform a legacy node dict to the new schema.

    Returns None for CaseParticipation nodes (they become edges instead).
    """
    node_type = node["node_type"]

    # CaseParticipation is dropped as a node
    if node_type == "CaseParticipation":
        return None

    props = copy.deepcopy(node.get("properties", {}))
    old_id = node["id"]

    # --- Determine new ID, node_type, and labels ---

    if node_type == "Actor":
        actor_type = props.get("actor_type", "")
        new_id = migrate_id(old_id, node_type, props)

        if actor_type in _ORG_ACTOR_TYPES:
            new_node_type = "Organization"
            labels = _ACTOR_ORG_LABELS.get(actor_type, ["Organization"])
        else:
            # person, unknown, missing, or any unrecognized type → Person
            new_node_type = "Person"
            labels = ["Person"]

        # Rename observed_labels → aliases; remove actor_type
        if "observed_labels" in props:
            props["aliases"] = props.pop("observed_labels")
        props.pop("actor_type", None)

    elif node_type == "Institution":
        new_id = migrate_id(old_id, node_type, props)
        new_node_type = "Organization"
        institution_type = props.get("institution_type", "")
        if institution_type == "court":
            labels = ["Organization", "Court"]
        elif institution_type in _GOVERNMENT_INSTITUTION_TYPES:
            labels = ["Organization", "Government"]
        else:
            labels = ["Organization"]

        # Rename institution_type → subtype
        if "institution_type" in props:
            props["subtype"] = props.pop("institution_type")

    elif node_type == "EconomicInterestDisclosure":
        new_id = migrate_id(old_id, node_type, props)
        new_node_type = "Filing"
        labels = ["Filing"]

        # Add filing_type
        props["filing_type"] = "form_700"

        # Rename filer_actor_id → filed_by (actor- prefix left for second-pass resolution)
        if "filer_actor_id" in props:
            props["filed_by"] = props.pop("filer_actor_id")

        # Rename disclosure_type → disclosure_subtype
        if "disclosure_type" in props:
            props["disclosure_subtype"] = props.pop("disclosure_type")

    elif node_type == "ValidationCheck":
        new_id = old_id
        new_node_type = node_type
        labels = [node_type]

    else:
        # Pass-through types
        new_id = old_id
        new_node_type = node_type
        labels = [node_type]

    # Remap inst- and eid- refs in properties (actor- refs deferred to second pass)
    props = _remap_props(props, id_map=None)

    result = {
        "id": new_id,
        "node_type": new_node_type,
        "labels": labels,
        "display_label": node.get("display_label", ""),
        "promotion_state": node.get("promotion_state"),
        "source_bundle_ids": node.get("source_bundle_ids", []),
        "source_sections": node.get("source_sections", []),
        "source_status": node.get("source_status"),
        "properties": props,
        "qa_lane": node_type == "ValidationCheck",
    }

    return result


# ---------------------------------------------------------------------------
# migrate_edge
# ---------------------------------------------------------------------------

def migrate_edge(edge: dict, id_map: dict[str, str]) -> Optional[dict]:
    """Transform a legacy edge dict to the new schema.

    Returns None if either endpoint touches a CaseParticipation node (casepart- prefix).
    """
    src_id = edge["source_id"]
    tgt_id = edge["target_id"]

    # Drop edges involving CaseParticipation nodes
    if src_id.startswith("casepart-") or tgt_id.startswith("casepart-"):
        return None

    # Remap source and target IDs
    new_src_id = id_map.get(src_id, _remap_prop_value(src_id))
    new_tgt_id = id_map.get(tgt_id, _remap_prop_value(tgt_id))

    # Remap node types from new IDs
    new_src_node_type = _infer_node_type_from_id(new_src_id, edge.get("source_node_type", ""))
    new_tgt_node_type = _infer_node_type_from_id(new_tgt_id, edge.get("target_node_type", ""))

    # Remap relationship type
    old_rel = edge["relationship_type"]
    new_rel = REL_TYPE_MAP.get(old_rel, old_rel)

    # Remap property values (both prefix rules and id_map)
    new_props = _remap_props(edge.get("properties", {}), id_map=id_map)

    result = dict(edge)
    result["source_id"] = new_src_id
    result["target_id"] = new_tgt_id
    result["source_node_type"] = new_src_node_type
    result["target_node_type"] = new_tgt_node_type
    result["relationship_type"] = new_rel
    result["properties"] = new_props

    return result


def _infer_node_type_from_id(new_id: str, fallback: str) -> str:
    """Infer node_type from the ID prefix after migration."""
    if new_id.startswith("person-"):
        return "Person"
    if new_id.startswith("org-"):
        return "Organization"
    if new_id.startswith("filing-"):
        return "Filing"
    if new_id.startswith("inst-"):
        # Should have been remapped, but guard
        return "Organization"
    if new_id.startswith("eid-"):
        return "Filing"
    # Pass-through: keep the old type (normalise Institution → Organization just in case)
    if fallback == "Institution":
        return "Organization"
    if fallback in ("EconomicInterestDisclosure",):
        return "Filing"
    return fallback


# ---------------------------------------------------------------------------
# case_participation_to_edges
# ---------------------------------------------------------------------------

def case_participation_to_edges(
    cp_nodes: list[dict],
    cp_evidence: dict[str, list[str]],
    id_map: dict[str, str],
) -> list[dict]:
    """Convert CaseParticipation nodes into PARTY_TO edges.

    For each CaseParticipation:
      - source: actor_id or institution_id (remapped via id_map)
      - target: case_id
      - properties: role, start_date, evidence_record_ids (merged from node + cp_evidence)

    Nodes with neither actor_id nor institution_id are skipped.
    """
    edges = []

    for cp in cp_nodes:
        props = cp.get("properties", {})
        cp_id = cp["id"]
        case_id = props.get("case_id", "")

        # Determine party source
        raw_party_id: Optional[str] = props.get("actor_id") or props.get("institution_id")
        if not raw_party_id:
            continue

        new_party_id = id_map.get(raw_party_id, _remap_prop_value(raw_party_id))
        party_node_type = _infer_node_type_from_id(new_party_id, "")

        # Merge evidence: from node + from cp_evidence map
        node_evidence: list[str] = props.get("evidence_record_ids", [])
        extra_evidence: list[str] = cp_evidence.get(cp_id, [])
        merged_evidence = list(dict.fromkeys(node_evidence + extra_evidence))  # preserve order, dedupe

        edge_props: dict = {
            "role": props.get("role"),
            "start_date": props.get("start_date"),
            "evidence_record_ids": merged_evidence,
        }
        # Remove None values for cleanliness
        edge_props = {k: v for k, v in edge_props.items() if v is not None}
        edge_props["evidence_record_ids"] = merged_evidence  # always include list

        edge = {
            "id": f"edge-{new_party_id}-party_to-{case_id}",
            "relationship_type": "PARTY_TO",
            "source_id": new_party_id,
            "target_id": case_id,
            "source_node_type": party_node_type,
            "target_node_type": "Case",
            "properties": edge_props,
        }
        edges.append(edge)

    return edges
