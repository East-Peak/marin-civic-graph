"""graph_v2_transforms.py — pure, projection-time transforms for the v2-native
graph projector (build_graph_v2.py), golden-pinned against migration_mapping.

This module is the settled-schema transform surface.  It REUSES the legacy
migration's constants and low-level id/property machinery (importing them, never
re-deriving) and lifts the node-classification rules into clean projection-time
helpers:

    classify_actor(old_id, actor_type)       -> (node_type, labels, new_id)
    classify_institution(old_id, inst_type)  -> (node_type, labels, new_id)
    eid_to_filing(old_id)                    -> (node_type, labels, new_id)
    rename_rel(old_rel)                      -> new_rel
    remap_props(props, id_map=None)          -> dict   (SHALLOW; payload_json kept)

For B-core (behavior-preserving golden parity), the whole-node / whole-edge
transforms used by build_graph_v2 — ``node_to_v2`` / ``edge_to_v2`` /
``cp_to_party_to`` — delegate to migration_mapping's ``migrate_node`` /
``migrate_edge`` / ``case_participation_to_edges`` so the output is byte-identical
to today's pipeline.  The decomposed classifiers above are independently pinned
against ``migrate_node`` (see tests/test_graph_v2_transforms.py) and are the
ready-to-use building blocks for Milestone C, when the legacy delegation is
removed and these helpers drive a from-scratch settled projection.
"""

from __future__ import annotations

from typing import Optional

# Reuse the legacy constants + low-level machinery — do NOT re-derive.
from migration_mapping import (
    _ACTOR_ORG_LABELS,
    _GOVERNMENT_INSTITUTION_TYPES,
    _ORG_ACTOR_TYPES,
    REL_TYPE_MAP,
    _remap_props,
    case_participation_to_edges,
    migrate_edge,
    migrate_id,
    migrate_node,
)

__all__ = [
    "classify_actor",
    "classify_institution",
    "eid_to_filing",
    "rename_rel",
    "remap_props",
    "node_to_v2",
    "edge_to_v2",
    "cp_to_party_to",
    "_ORG_ACTOR_TYPES",
    "_ACTOR_ORG_LABELS",
    "_GOVERNMENT_INSTITUTION_TYPES",
    "REL_TYPE_MAP",
]


# ---------------------------------------------------------------------------
# Decomposed projection-time classifiers (lifted from migration_mapping)
# ---------------------------------------------------------------------------

def classify_actor(old_id: str, actor_type: str) -> tuple[str, list[str], str]:
    """Classify a legacy Actor by actor_type.

    Org-like actor_types map to Organization (with multi-labels from
    _ACTOR_ORG_LABELS); everything else — person, unknown, missing — defaults
    to Person.  Mirrors migration_mapping.migrate_node's Actor branch.
    """
    new_id = migrate_id(old_id, "Actor", {"actor_type": actor_type})
    if actor_type in _ORG_ACTOR_TYPES:
        return "Organization", _ACTOR_ORG_LABELS.get(actor_type, ["Organization"]), new_id
    return "Person", ["Person"], new_id


def classify_institution(old_id: str, institution_type: str) -> tuple[str, list[str], str]:
    """Classify a legacy Institution by institution_type → Organization.

    court → +Court; government types → +Government; otherwise bare Organization.
    """
    new_id = migrate_id(old_id, "Institution", {})
    if institution_type == "court":
        labels = ["Organization", "Court"]
    elif institution_type in _GOVERNMENT_INSTITUTION_TYPES:
        labels = ["Organization", "Government"]
    else:
        labels = ["Organization"]
    return "Organization", labels, new_id


def eid_to_filing(old_id: str) -> tuple[str, list[str], str]:
    """Classify a legacy EconomicInterestDisclosure → Filing."""
    new_id = migrate_id(old_id, "EconomicInterestDisclosure", {})
    return "Filing", ["Filing"], new_id


def rename_rel(old_rel: str) -> str:
    """Rename a relationship type via REL_TYPE_MAP (identity if unmapped)."""
    return REL_TYPE_MAP.get(old_rel, old_rel)


def remap_props(props: dict, id_map: Optional[dict[str, str]] = None) -> dict:
    """Shallow property remap (prefix rules + id_map). payload_json is never
    recursively remapped — legacy ids inside it are preserved verbatim."""
    return _remap_props(props, id_map=id_map)


# ---------------------------------------------------------------------------
# Whole-node / whole-edge transforms (delegated for byte-exact golden parity)
# ---------------------------------------------------------------------------

def node_to_v2(node: dict) -> Optional[dict]:
    """Transform a legacy node envelope to a settled node (None for
    CaseParticipation).  Delegates to migration_mapping.migrate_node."""
    return migrate_node(node)


def edge_to_v2(edge: dict, id_map: dict[str, str]) -> Optional[dict]:
    """Transform a legacy edge to a settled edge (None for casepart- endpoints).
    Delegates to migration_mapping.migrate_edge."""
    return migrate_edge(edge, id_map)


def cp_to_party_to(
    cp_nodes: list[dict],
    cp_evidence: dict[str, list[str]],
    id_map: dict[str, str],
) -> list[dict]:
    """Convert CaseParticipation nodes into PARTY_TO edges, harvesting evidence
    from both the node and the dropped EVIDENCED_BY edges.  Delegates to
    migration_mapping.case_participation_to_edges."""
    return case_participation_to_edges(cp_nodes, cp_evidence, id_map)
