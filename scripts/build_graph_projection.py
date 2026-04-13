#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from graph_projection_lib import (
    DEFAULT_MANIFEST_PATH,
    PROMOTION_RANK,
    ROOT,
    derive_display_label,
    infer_node_type_from_id,
    load_json,
    merge_property_maps,
    read_manifest,
    sanitize_graph_properties,
    write_json,
    write_jsonl,
)


EXPLICIT_RELATION_TYPES: dict[tuple[str, str], str] = {
    ("Seat", "institution_id"): "BELONGS_TO_INSTITUTION",
    ("SeatService", "actor_id"): "HELD_BY_ACTOR",
    ("SeatService", "seat_id"): "FOR_SEAT",
    ("SeatService", "election_id"): "RESULT_OF_ELECTION",
    ("SeatService", "institution_id"): "SERVES_IN_INSTITUTION",
    ("Election", "jurisdiction_id"): "IN_JURISDICTION",
    ("Election", "seat_id"): "FOR_SEAT",
    ("Election", "related_canonical_election_ids"): "RELATED_TO_ELECTION",
    ("EconomicInterestDisclosure", "filer_actor_id"): "FILED_BY_ACTOR",
    ("EconomicInterestDisclosure", "filing_institution_id"): "FILED_WITH_INSTITUTION",
    ("EconomicInterestDisclosure", "seat_id"): "FILED_FOR_SEAT",
    ("EconomicInterestDisclosure", "seat_service_id"): "FILED_DURING_SEAT_SERVICE",
    ("EconomicInterestDisclosure", "filing_id"): "DISCLOSED_IN_FILING",
    ("Meeting", "institution_id"): "HELD_BY_INSTITUTION",
    ("AgendaItem", "meeting_id"): "PART_OF_MEETING",
    ("AgendaItem", "place_ids"): "RELATES_TO_PLACE",
    ("Decision", "institution_id"): "DECIDED_BY_INSTITUTION",
    ("Decision", "meeting_id"): "DECIDED_AT_MEETING",
    ("Decision", "agenda_item_id"): "ABOUT_AGENDA_ITEM",
    ("Decision", "election_id"): "RELATES_TO_ELECTION",
    ("Decision", "record_ids"): "EVIDENCED_BY",
    ("Decision", "related_decision_id"): "RELATES_TO_DECISION",
    ("Decision", "related_decision_ids"): "RELATES_TO_DECISION",
    ("Record", "meeting_id"): "RELATES_TO_MEETING",
    ("Record", "agenda_item_id"): "RELATES_TO_AGENDA_ITEM",
    ("Record", "case_id"): "RELATES_TO_CASE",
    ("Record", "case_ids"): "RELATES_TO_CASE",
    ("Record", "related_case_ids"): "RELATES_TO_CASE",
    ("Record", "decision_ids"): "RELATES_TO_DECISION",
    ("Record", "related_decision_ids"): "RELATES_TO_DECISION",
    ("Record", "related_moneyflow_ids"): "RELATES_TO_MONEY_FLOW",
    ("Record", "election_ids"): "RELATES_TO_ELECTION",
    ("Record", "committee_ids"): "RELATES_TO_COMMITTEE",
    ("Record", "candidate_actor_ids"): "RELATES_TO_ACTOR",
    ("Record", "target_actor_ids"): "RELATES_TO_ACTOR",
    ("Record", "seat_ids"): "RELATES_TO_SEAT",
    ("Record", "actor_ids"): "RELATES_TO_ACTOR",
    ("Record", "place_ids"): "RELATES_TO_PLACE",
    ("Record", "source_record_id"): "DERIVED_FROM_RECORD",
    ("Committee", "controlling_actor_id"): "CONTROLLED_BY_ACTOR",
    ("Committee", "actor_candidate_id"): "COMMITTEE_ACTOR",
    ("Committee", "primary_election_id"): "PRIMARY_FOR_ELECTION",
    ("Committee", "jurisdiction_place_id"): "IN_JURISDICTION",
    ("Filing", "committee_id"): "FILED_BY_COMMITTEE",
    ("Filing", "committee_actor_id"): "FILED_BY_ACTOR",
    ("Filing", "filer_actor_id"): "FILED_BY_ACTOR",
    ("Filing", "election_id"): "FILED_FOR_ELECTION",
    ("Filing", "record_id"): "EVIDENCED_BY",
    ("Filing", "official_actor_id"): "OFFICIAL_FILER",
    ("Filing", "official_seat_id"): "FILED_FOR_SEAT",
    ("Filing", "official_seat_service_id"): "FILED_DURING_SEAT_SERVICE",
    ("Filing", "filing_institution_id"): "FILED_WITH_INSTITUTION",
    ("Filing", "filing_officer_institution_id"): "FILED_WITH_OFFICER",
    ("Filing", "target_actor_id"): "TARGETS_ACTOR",
    ("Filing", "target_seat_id"): "TARGETS_SEAT",
    ("Candidacy", "candidate_actor_id"): "CANDIDATE_ACTOR",
    ("Candidacy", "committee_id"): "CONTROLLED_BY_COMMITTEE",
    ("Candidacy", "election_id"): "FOR_ELECTION",
    ("Candidacy", "seat_id"): "FOR_SEAT",
    ("MoneyFlow", "from_actor_id"): "FROM_SOURCE",
    ("MoneyFlow", "to_actor_id"): "TO_TARGET",
    ("MoneyFlow", "to_committee_id"): "TO_TARGET",
    ("MoneyFlow", "filing_id"): "DISCLOSED_IN_FILING",
    ("MoneyFlow", "requested_by_actor_id"): "REQUESTED_BY_ACTOR",
    ("MoneyFlow", "requested_by_seat_id"): "REQUESTED_BY_SEAT",
    ("MoneyFlow", "requested_by_seat_service_id"): "REQUESTED_BY_SEAT_SERVICE",
    ("MoneyFlow", "related_institution_id"): "RELATES_TO_INSTITUTION",
    ("MoneyFlow", "related_decision_id"): "RELATES_TO_DECISION",
    ("Program", "institution_id"): "OPERATED_BY_INSTITUTION",
    ("Program", "jurisdiction_place_id"): "IN_JURISDICTION",
    ("Program", "record_ids"): "EVIDENCED_BY",
    ("Program", "related_case_ids"): "RELATES_TO_CASE",
    ("Program", "related_decision_ids"): "RELATES_TO_DECISION",
    ("Program", "place_ids"): "RELATES_TO_PLACE",
    ("Case", "court_institution_id"): "HEARD_IN_COURT",
    ("Case", "record_ids"): "EVIDENCED_BY",
    ("Case", "issue_ids"): "RELATES_TO_ISSUE",
    ("Case", "place_ids"): "RELATES_TO_PLACE",
    ("Case", "related_decision_ids"): "RELATES_TO_DECISION",
    ("Case", "related_program_ids"): "RELATES_TO_PROGRAM",
    ("Proceeding", "case_id"): "PART_OF_CASE",
    ("Proceeding", "judge_actor_id"): "HEARD_BY_JUDGE",
    ("Proceeding", "evidence_record_ids"): "EVIDENCED_BY",
    ("CaseParticipation", "case_id"): "PART_OF_CASE",
    ("CaseParticipation", "actor_id"): "INVOLVES_ACTOR",
    ("CaseParticipation", "institution_id"): "INVOLVES_INSTITUTION",
    ("CaseParticipation", "evidence_record_ids"): "EVIDENCED_BY",
    ("ValidationCheck", "subject_node_id"): "VALIDATES",
    ("ValidationCheck", "derived_from_record_id"): "DERIVED_FROM_RECORD",
}

COMMON_REFERENCE_FIELDS = {
    "evidence_record_ids",
    "record_id",
    "record_ids",
    "source_record_id",
    "decision_ids",
    "related_decision_ids",
    "related_moneyflow_ids",
    "meeting_id",
    "agenda_item_id",
    "election_id",
    "election_ids",
    "committee_id",
    "committee_ids",
    "candidate_actor_ids",
    "target_actor_ids",
    "seat_ids",
    "target_seat_id",
    "actor_ids",
    "place_ids",
    "institution_id",
    "court_institution_id",
    "controlling_actor_id",
    "actor_candidate_id",
    "primary_election_id",
    "jurisdiction_place_id",
    "committee_actor_id",
    "filer_actor_id",
    "official_actor_id",
    "official_seat_id",
    "official_seat_service_id",
    "filing_institution_id",
    "filing_officer_institution_id",
    "target_actor_id",
    "candidate_actor_id",
    "from_actor_id",
    "to_actor_id",
    "to_committee_id",
    "filing_id",
    "requested_by_actor_id",
    "requested_by_seat_id",
    "requested_by_seat_service_id",
    "related_institution_id",
    "related_decision_id",
    "related_case_ids",
    "related_program_ids",
    "subject_node_id",
    "jurisdiction_id",
    "case_id",
    "case_ids",
    "seat_service_id",
    "seat_id",
    "actor_id",
    "judge_actor_id",
    "related_canonical_election_ids",
    "co_recipient",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a graph-ready projection from normalized civic bundles.")
    parser.add_argument(
        "--manifest",
        default=str(DEFAULT_MANIFEST_PATH),
        help="Path to the import manifest. The manifest is stored as JSON-compatible YAML.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Override output directory. Defaults to the manifest output_dir.",
    )
    return parser.parse_args()


def should_include_object(section: dict[str, Any], obj: dict[str, Any]) -> tuple[bool, str | None]:
    filters = section.get("filters") or {}
    for key, allowed_values in filters.items():
        value = obj.get(key)
        if value not in allowed_values:
            return False, f"filter:{key}"
    return True, None


def infer_relationship_type(source_node_type: str, field_name: str, target_type: str | None) -> str:
    explicit = EXPLICIT_RELATION_TYPES.get((source_node_type, field_name))
    if explicit:
        return explicit
    if field_name in {"record_id", "record_ids", "evidence_record_ids", "evidence"} and target_type == "Record":
        return "EVIDENCED_BY"
    if field_name == "source_record_id" and target_type == "Record":
        return "DERIVED_FROM_RECORD"
    if field_name == "committee_id":
        return "RELATES_TO_COMMITTEE"
    if field_name == "meeting_id":
        return "RELATES_TO_MEETING"
    if field_name == "agenda_item_id":
        return "RELATES_TO_AGENDA_ITEM"
    if field_name in {"decision_id", "decision_ids", "related_decision_id"}:
        return "RELATES_TO_DECISION"
    if field_name in {"place_id", "place_ids"}:
        return "RELATES_TO_PLACE"
    if field_name in {"actor_id", "actor_ids", "candidate_actor_ids", "target_actor_ids"}:
        return "RELATES_TO_ACTOR"
    if field_name in {"seat_id", "seat_ids", "target_seat_id"}:
        return "RELATES_TO_SEAT"
    if field_name in {"election_id", "election_ids", "related_canonical_election_ids"}:
        return "RELATES_TO_ELECTION"
    if target_type:
        return f"RELATES_TO_{target_type.upper()}"
    return "RELATED_TO"


def build_node_envelope(
    node_type: str,
    promotion_state: str,
    bundle_id: str,
    section_name: str,
    obj: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": obj["id"],
        "node_type": node_type,
        "display_label": derive_display_label(obj),
        "promotion_state": promotion_state,
        "source_bundle_ids": [bundle_id],
        "source_sections": [section_name],
        "source_status": obj.get("status"),
        "properties": sanitize_graph_properties(obj),
        "_promotion_rank": PROMOTION_RANK[promotion_state],
    }


def build_edge_envelope(
    *,
    source_id: str,
    source_node_type: str,
    target_id: str,
    target_node_type: str | None,
    relationship_type: str,
    bundle_id: str,
    source_field: str,
    properties: dict[str, Any] | None = None,
) -> dict[str, Any]:
    clean_properties = {
        key: value
        for key, value in (properties or {}).items()
        if value is not None and (isinstance(value, (str, int, float, bool)) or (isinstance(value, list) and all(not isinstance(item, (dict, list)) for item in value)))
    }
    return {
        "source_id": source_id,
        "source_node_type": source_node_type,
        "target_id": target_id,
        "target_node_type": target_node_type,
        "relationship_type": relationship_type,
        "source_bundle_ids": [bundle_id],
        "source_fields": [source_field],
        "properties": clean_properties,
    }


def extract_edges_from_evidence(
    *,
    source_id: str,
    source_node_type: str,
    bundle_id: str,
    evidence_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    for evidence in evidence_items:
        target_id = evidence.get("document_id") or evidence.get("record_id")
        target_type = infer_node_type_from_id(target_id)
        if not target_id or not target_type:
            continue
        properties = {key: value for key, value in evidence.items() if key not in {"document_id", "record_id"}}
        edges.append(
            build_edge_envelope(
                source_id=source_id,
                source_node_type=source_node_type,
                target_id=target_id,
                target_node_type=target_type,
                relationship_type="EVIDENCED_BY",
                bundle_id=bundle_id,
                source_field="evidence",
                properties=properties,
            )
        )
    return edges


def extract_vote_edges(decision: dict[str, Any], bundle_id: str) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    decision_id = decision["id"]
    for vote in decision.get("votes") or []:
        actor_id = vote.get("actor_id")
        actor_type = infer_node_type_from_id(actor_id)
        if actor_type != "Actor":
            continue
        edge_props = {
            "vote": vote.get("vote"),
            "seat_id": vote.get("seat_id"),
            "seat_service_id": vote.get("seat_service_id"),
        }
        edges.append(
            build_edge_envelope(
                source_id=actor_id,
                source_node_type="Actor",
                target_id=decision_id,
                target_node_type="Decision",
                relationship_type="CAST_VOTE_ON",
                bundle_id=bundle_id,
                source_field="votes",
                properties=edge_props,
            )
        )
    return edges


def extract_edges_from_object(
    node_type: str,
    obj: dict[str, Any],
    bundle_id: str,
) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    source_id = obj["id"]

    if isinstance(obj.get("evidence"), list):
        edges.extend(
            extract_edges_from_evidence(
                source_id=source_id,
                source_node_type=node_type,
                bundle_id=bundle_id,
                evidence_items=obj["evidence"],
            )
        )

    if node_type == "Decision":
        edges.extend(extract_vote_edges(obj, bundle_id))

    for field_name, value in obj.items():
        if field_name == "id":
            continue
        if field_name == "evidence":
            continue
        if field_name == "votes":
            continue
        if field_name not in COMMON_REFERENCE_FIELDS and not field_name.endswith("_id") and not field_name.endswith("_ids"):
            continue

        candidate_targets: list[tuple[str, dict[str, Any] | None]] = []
        if isinstance(value, str):
            candidate_targets.append((value, None))
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, str):
                    candidate_targets.append((item, None))
        else:
            continue

        for target_id, edge_props in candidate_targets:
            target_type = infer_node_type_from_id(target_id)
            if target_type is None:
                continue
            edges.append(
                build_edge_envelope(
                    source_id=source_id,
                    source_node_type=node_type,
                    target_id=target_id,
                    target_node_type=target_type,
                    relationship_type=infer_relationship_type(node_type, field_name, target_type),
                    bundle_id=bundle_id,
                    source_field=field_name,
                    properties=edge_props,
                )
            )

    return edges


def passthrough_relationships(
    relationships: list[dict[str, Any]],
    bundle_id: str,
) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    for relationship in relationships:
        source_id = relationship["source_record_id"]
        source_type = infer_node_type_from_id(source_id)
        if not source_type:
            continue
        for key, value in relationship.items():
            if not key.startswith("target_") or not key.endswith("_id"):
                continue
            target_id = value
            target_type = infer_node_type_from_id(target_id)
            if not target_type:
                continue
            edge_properties = {
                prop_key: prop_value
                for prop_key, prop_value in relationship.items()
                if prop_key not in {"source_record_id", key, "relationship_type"}
            }
            edges.append(
                build_edge_envelope(
                    source_id=source_id,
                    source_node_type=source_type,
                    target_id=target_id,
                    target_node_type=target_type,
                    relationship_type=relationship["relationship_type"].upper(),
                    bundle_id=bundle_id,
                    source_field="record_relationships",
                    properties=edge_properties,
                )
            )
    return edges


def merge_node(existing: dict[str, Any], incoming: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    if existing["node_type"] != incoming["node_type"]:
        raise ValueError(
            f"Node type collision for {existing['id']}: {existing['node_type']} vs {incoming['node_type']}"
        )
    prefer_incoming = incoming["_promotion_rank"] > existing["_promotion_rank"]
    merged_properties, conflicts = merge_property_maps(
        existing["properties"],
        incoming["properties"],
        prefer_incoming=prefer_incoming,
    )
    merged = dict(existing)
    merged["source_bundle_ids"] = sorted(
        set(existing["source_bundle_ids"]) | set(incoming["source_bundle_ids"])
    )
    merged["source_sections"] = sorted(
        set(existing["source_sections"]) | set(incoming["source_sections"])
    )
    merged["properties"] = merged_properties
    if prefer_incoming:
        merged["promotion_state"] = incoming["promotion_state"]
        merged["_promotion_rank"] = incoming["_promotion_rank"]
        merged["display_label"] = incoming["display_label"]
        merged["source_status"] = incoming.get("source_status") or existing.get("source_status")
    else:
        merged["source_status"] = existing.get("source_status") or incoming.get("source_status")
        if not merged["display_label"]:
            merged["display_label"] = incoming["display_label"]
    return merged, conflicts


def merge_edge(existing: dict[str, Any], incoming: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    merged_properties, conflicts = merge_property_maps(
        existing["properties"],
        incoming["properties"],
        prefer_incoming=False,
    )
    merged = dict(existing)
    merged["source_bundle_ids"] = sorted(
        set(existing["source_bundle_ids"]) | set(incoming["source_bundle_ids"])
    )
    merged["source_fields"] = sorted(
        set(existing["source_fields"]) | set(incoming["source_fields"])
    )
    merged["properties"] = merged_properties
    return merged, conflicts


def finalize_node_for_output(node: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": node["id"],
        "node_type": node["node_type"],
        "display_label": node["display_label"],
        "promotion_state": node["promotion_state"],
        "source_bundle_ids": node["source_bundle_ids"],
        "source_sections": node["source_sections"],
        "source_status": node.get("source_status"),
        "properties": node["properties"],
    }


def finalize_edge_for_output(edge: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_id": edge["source_id"],
        "source_node_type": edge["source_node_type"],
        "target_id": edge["target_id"],
        "target_node_type": edge["target_node_type"],
        "relationship_type": edge["relationship_type"],
        "source_bundle_ids": edge["source_bundle_ids"],
        "source_fields": edge["source_fields"],
        "properties": edge["properties"],
    }


def build_actor_alias_map(nodes_by_id: dict[str, dict[str, Any]]) -> dict[str, str]:
    alias_map: dict[str, str] = {}
    for node in nodes_by_id.values():
        if node["node_type"] != "Actor":
            continue
        for alias_id in node.get("properties", {}).get("resolves_raw_actor_seed_ids", []) or []:
            if isinstance(alias_id, str) and alias_id.startswith("actor-"):
                alias_map[alias_id] = node["id"]
    return alias_map


def remap_actor_aliases(edge: dict[str, Any], alias_map: dict[str, str]) -> tuple[dict[str, Any], bool]:
    remapped = dict(edge)
    changed = False
    if remapped["source_node_type"] == "Actor" and remapped["source_id"] in alias_map:
        remapped["source_id"] = alias_map[remapped["source_id"]]
        changed = True
    if remapped["target_node_type"] == "Actor" and remapped["target_id"] in alias_map:
        remapped["target_id"] = alias_map[remapped["target_id"]]
        changed = True
    return remapped, changed


def main() -> None:
    args = parse_args()
    manifest_path = Path(args.manifest).resolve()
    manifest = read_manifest(manifest_path)
    output_dir = (
        (ROOT / manifest["output_dir"]).resolve()
        if args.output_dir is None
        else Path(args.output_dir).resolve()
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    nodes_by_id: dict[str, dict[str, Any]] = {}
    raw_edges: list[dict[str, Any]] = []
    bundle_reports: list[dict[str, Any]] = []
    skipped_edge_reasons: Counter[str] = Counter()
    skipped_edge_targets: Counter[str] = Counter()
    node_conflicts: list[dict[str, Any]] = []
    edge_conflicts: list[dict[str, Any]] = []
    duplicate_node_count = 0
    duplicate_edge_count = 0

    for bundle in manifest["bundles"]:
        bundle_path = (ROOT / bundle["path"]).resolve()
        payload = load_json(bundle_path)
        bundle_id = payload.get("bundle_id") or bundle_path.stem
        bundle_report = {
            "bundle_id": bundle_id,
            "path": str(bundle_path.relative_to(ROOT)),
            "sections": [],
        }
        for section in bundle["sections"]:
            section_name = section["name"]
            items = payload.get(section_name) or []
            section_report = {
                "section": section_name,
                "mode": section["mode"],
                "input_count": len(items),
                "imported_count": 0,
                "skipped_count": 0,
                "skip_reasons": Counter(),
            }
            if section["mode"] == "relationship_passthrough":
                passthrough_edges = passthrough_relationships(items, bundle_id)
                raw_edges.extend(passthrough_edges)
                section_report["imported_count"] = len(passthrough_edges)
                bundle_report["sections"].append(
                    {
                        **section_report,
                        "skip_reasons": dict(section_report["skip_reasons"]),
                    }
                )
                continue

            node_type = section["node_type"]
            promotion_state = section["promotion_state"]
            for obj in items:
                include, reason = should_include_object(section, obj)
                if not include:
                    section_report["skipped_count"] += 1
                    section_report["skip_reasons"][reason or "filter"] += 1
                    continue
                node = build_node_envelope(
                    node_type=node_type,
                    promotion_state=promotion_state,
                    bundle_id=bundle_id,
                    section_name=section_name,
                    obj=obj,
                )
                existing = nodes_by_id.get(node["id"])
                if existing is None:
                    nodes_by_id[node["id"]] = node
                else:
                    duplicate_node_count += 1
                    merged, conflicts = merge_node(existing, node)
                    nodes_by_id[node["id"]] = merged
                    if conflicts:
                        node_conflicts.append(
                            {
                                "id": node["id"],
                                "bundle_id": bundle_id,
                                "fields": conflicts,
                            }
                        )
                raw_edges.extend(extract_edges_from_object(node_type, obj, bundle_id))
                section_report["imported_count"] += 1
            bundle_report["sections"].append(
                {
                    **section_report,
                    "skip_reasons": dict(section_report["skip_reasons"]),
                }
            )
        bundle_reports.append(bundle_report)

    known_node_ids = set(nodes_by_id)
    actor_alias_map = build_actor_alias_map(nodes_by_id)
    edges_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    actor_alias_edge_remaps = 0
    for edge in raw_edges:
        edge, remapped = remap_actor_aliases(edge, actor_alias_map)
        if remapped:
            actor_alias_edge_remaps += 1
        if edge["source_id"] not in known_node_ids:
            skipped_edge_reasons["missing_source"] += 1
            skipped_edge_targets[edge["source_id"]] += 1
            continue
        if edge["target_id"] not in known_node_ids:
            skipped_edge_reasons[f"missing_target:{edge['target_node_type'] or 'unknown'}"] += 1
            skipped_edge_targets[edge["target_id"]] += 1
            continue
        edge_key = (edge["source_id"], edge["relationship_type"], edge["target_id"])
        existing = edges_by_key.get(edge_key)
        if existing is None:
            edges_by_key[edge_key] = edge
        else:
            duplicate_edge_count += 1
            merged, conflicts = merge_edge(existing, edge)
            edges_by_key[edge_key] = merged
            if conflicts:
                edge_conflicts.append(
                    {
                        "source_id": edge["source_id"],
                        "relationship_type": edge["relationship_type"],
                        "target_id": edge["target_id"],
                        "fields": conflicts,
                    }
                )

    nodes = sorted(
        (finalize_node_for_output(node) for node in nodes_by_id.values()),
        key=lambda item: (item["node_type"], item["id"]),
    )
    edges = sorted(
        (finalize_edge_for_output(edge) for edge in edges_by_key.values()),
        key=lambda item: (item["relationship_type"], item["source_id"], item["target_id"]),
    )

    report = {
        "projection_id": manifest["projection_id"],
        "generated_at": utc_now_iso(),
        "manifest_path": str(manifest_path),
        "output_dir": str(output_dir.relative_to(ROOT)),
        "bundle_reports": bundle_reports,
        "node_type_counts": dict(sorted(Counter(node["node_type"] for node in nodes).items())),
        "edge_type_counts": dict(sorted(Counter(edge["relationship_type"] for edge in edges).items())),
        "total_nodes": len(nodes),
        "total_edges": len(edges),
        "duplicate_node_merges": duplicate_node_count,
        "duplicate_edge_merges": duplicate_edge_count,
        "actor_alias_edge_remaps": actor_alias_edge_remaps,
        "node_conflicts": node_conflicts,
        "edge_conflicts": edge_conflicts,
        "skipped_edge_reasons": dict(sorted(skipped_edge_reasons.items())),
        "top_skipped_edge_targets": skipped_edge_targets.most_common(25),
    }

    write_jsonl(output_dir / "nodes.jsonl", nodes)
    write_jsonl(output_dir / "edges.jsonl", edges)
    write_json(output_dir / "report.json", report)
    write_json(output_dir / "manifest.snapshot.json", manifest)


if __name__ == "__main__":
    main()
