#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from graph_projection_lib import DEFAULT_MANIFEST_PATH, ROOT, read_manifest, write_json
from run_graph_query_pack import (
    build_indexes,
    edge_sources,
    edge_targets,
    meeting_for_decision,
    node_title,
    node_year,
)


VIEW_DIR_NAME = "views"
DEFAULT_VIEW_TARGETS_PATH = ROOT / "registry" / "view-targets.yaml"
FLOW_RELATIONSHIP_TYPES = {"FROM_SOURCE", "TO_TARGET", "REQUESTED_BY_ACTOR"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build product-facing dossier and summary views over the projected graph-v1 payload."
    )
    parser.add_argument(
        "--manifest",
        default=str(DEFAULT_MANIFEST_PATH),
        help="Path to the JSON-compatible YAML import manifest.",
    )
    parser.add_argument(
        "--targets",
        default=str(DEFAULT_VIEW_TARGETS_PATH),
        help="Path to the JSON-compatible YAML view target manifest.",
    )
    parser.add_argument(
        "--projection-dir",
        default=None,
        help="Override projection directory. Defaults to manifest output_dir.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Override view output directory. Defaults to <projection-dir>/views.",
    )
    return parser.parse_args()


def iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def compact_properties(node: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in node.get("properties", {}).items()
        if key != "payload_json" and value not in (None, "", [])
    }


def node_summary(node: dict[str, Any] | None) -> dict[str, Any] | None:
    if node is None:
        return None
    return {
        "id": node["id"],
        "node_type": node["node_type"],
        "display_label": node_title(node),
        "year": node_year(node),
        "source_bundle_ids": node.get("source_bundle_ids", []),
        "properties": compact_properties(node),
    }


def unique_node_summaries(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    results: list[dict[str, Any]] = []
    for node in nodes:
        if node["id"] in seen:
            continue
        seen.add(node["id"])
        summary = node_summary(node)
        if summary is not None:
            results.append(summary)
    return results


def unique_summary_items(items: list[dict[str, Any] | None]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    results: list[dict[str, Any]] = []
    for item in items:
        if item is None:
            continue
        item_id = item.get("id")
        if not item_id or item_id in seen:
            continue
        seen.add(item_id)
        results.append(item)
    results.sort(key=lambda item: (item.get("year") or 0, item.get("display_label") or "", item.get("id") or ""))
    return results


def unique_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    results: list[dict[str, Any]] = []
    for node in nodes:
        if node["id"] in seen:
            continue
        seen.add(node["id"])
        results.append(node)
    return results


def sort_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(nodes, key=lambda node: (node_year(node) or 0, node_title(node), node["id"]))


def slugify_subject(subject_id: str) -> str:
    for prefix in ("actor-", "decision-", "case-", "program-", "project-", "place-"):
        if subject_id.startswith(prefix):
            return subject_id[len(prefix) :]
    return subject_id


def relative_or_absolute(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def related_records_for_actor(
    actor_id: str,
    *,
    node_by_id: dict[str, dict[str, Any]],
    outgoing: dict[str, list[dict[str, Any]]],
    incoming: dict[str, list[dict[str, Any]]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    evidence_records = edge_targets(
        outgoing,
        node_by_id,
        actor_id,
        relationship_type="EVIDENCED_BY",
        target_node_type="Record",
    )
    related_records = edge_sources(
        incoming,
        node_by_id,
        actor_id,
        relationship_type="RELATES_TO_ACTOR",
        source_node_type="Record",
    )
    return sort_nodes(evidence_records), sort_nodes(related_records)


def connected_money_flows(
    subject_id: str,
    *,
    node_by_id: dict[str, dict[str, Any]],
    outgoing: dict[str, list[dict[str, Any]]],
    incoming: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}
    for edge in outgoing.get(subject_id, []) + incoming.get(subject_id, []):
        if edge["relationship_type"] not in FLOW_RELATIONSHIP_TYPES:
            continue
        other_id = edge["target_id"] if edge["source_id"] == subject_id else edge["source_id"]
        flow = node_by_id.get(other_id)
        if flow is None or flow["node_type"] != "MoneyFlow":
            continue
        bucket = buckets.setdefault(
            flow["id"],
            {
                "money_flow": node_summary(flow),
                "relationship_types": set(),
            },
        )
        bucket["relationship_types"].add(edge["relationship_type"])

    results = []
    for bucket in buckets.values():
        results.append(
            {
                "money_flow": bucket["money_flow"],
                "relationship_types": sorted(bucket["relationship_types"]),
            }
        )
    results.sort(
        key=lambda item: (
            -(item["money_flow"]["properties"].get("amount") or 0),
            item["money_flow"]["display_label"],
            item["money_flow"]["id"],
        )
    )
    return results


def sum_money_amounts(flows: list[dict[str, Any]]) -> float:
    total = 0.0
    for flow in flows:
        amount = flow.get("properties", {}).get("amount")
        if isinstance(amount, (int, float)):
            total += float(amount)
    return total


def linked_decisions_from_money_flows(
    money_flow_entries: list[dict[str, Any]],
    *,
    node_by_id: dict[str, dict[str, Any]],
    outgoing: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    decisions = []
    for item in money_flow_entries:
        flow_id = item["money_flow"]["id"]
        decisions.extend(
            edge_targets(
                outgoing,
                node_by_id,
                flow_id,
                relationship_type="RELATES_TO_DECISION",
                target_node_type="Decision",
            )
        )
    return sort_nodes(decisions)


def linked_money_flows_for_decisions(
    decisions: list[dict[str, Any]],
    *,
    node_by_id: dict[str, dict[str, Any]],
    incoming: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    flows = []
    for decision in decisions:
        flows.extend(
            edge_sources(
                incoming,
                node_by_id,
                decision["id"],
                relationship_type="RELATES_TO_DECISION",
                source_node_type="MoneyFlow",
            )
        )
    return sort_nodes(flows)


def linked_cases_from_records(
    records: list[dict[str, Any]],
    *,
    node_by_id: dict[str, dict[str, Any]],
    outgoing: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    cases = []
    for record in records:
        cases.extend(
            edge_targets(
                outgoing,
                node_by_id,
                record["id"],
                relationship_type="RELATES_TO_CASE",
                target_node_type="Case",
            )
        )
    return sort_nodes(cases)


def linked_programs_from_records(
    records: list[dict[str, Any]],
    *,
    node_by_id: dict[str, dict[str, Any]],
    outgoing: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    programs = []
    for record in records:
        programs.extend(
            edge_targets(
                outgoing,
                node_by_id,
                record["id"],
                relationship_type="RELATES_TO_PROGRAM",
                target_node_type="Program",
            )
        )
    return sort_nodes(programs)


def actor_dossier(
    *,
    actor_id: str,
    node_by_id: dict[str, dict[str, Any]],
    outgoing: dict[str, list[dict[str, Any]]],
    incoming: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    actor = node_by_id[actor_id]
    actor_label = node_title(actor)

    seat_services = sorted(
        edge_sources(
            incoming,
            node_by_id,
            actor_id,
            relationship_type="HELD_BY_ACTOR",
            source_node_type="SeatService",
        ),
        key=lambda node: (node.get("properties", {}).get("started_at", ""), node["id"]),
    )
    committees = sort_nodes(
        edge_sources(
            incoming,
            node_by_id,
            actor_id,
            relationship_type="CONTROLLED_BY_ACTOR",
            source_node_type="Committee",
        )
    )
    candidacies = sort_nodes(
        edge_sources(
            incoming,
            node_by_id,
            actor_id,
            relationship_type="CANDIDATE_ACTOR",
            source_node_type="Candidacy",
        )
    )
    filings = sort_nodes(
        list(
            {
                filing["id"]: filing
                for filing in (
                    edge_sources(incoming, node_by_id, actor_id, relationship_type="OFFICIAL_FILER", source_node_type="Filing")
                    + edge_sources(incoming, node_by_id, actor_id, relationship_type="FILED_BY_ACTOR", source_node_type="Filing")
                    + [
                        filing
                        for committee in committees
                        for filing in edge_sources(
                            incoming,
                            node_by_id,
                            committee["id"],
                            relationship_type="FILED_BY_COMMITTEE",
                            source_node_type="Filing",
                        )
                    ]
                )
            }.values()
        )
    )
    council_decisions = sorted(
        [
            node_by_id[edge["target_id"]]
            for edge in outgoing.get(actor_id, [])
            if edge["relationship_type"] == "CAST_VOTE_ON" and edge["target_id"] in node_by_id
        ],
        key=lambda node: (
            (meeting_for_decision(node["id"], outgoing, node_by_id) or {}).get("properties", {}).get("meeting_date", ""),
            node["id"],
        ),
    )
    vote_records = []
    for edge in outgoing.get(actor_id, []):
        if edge["relationship_type"] != "CAST_VOTE_ON":
            continue
        decision = node_by_id.get(edge["target_id"])
        if decision is None:
            continue
        meeting = meeting_for_decision(decision["id"], outgoing, node_by_id)
        vote_records.append(
            {
                "decision_id": decision["id"],
                "decision_label": node_title(decision),
                "meeting_id": meeting["id"] if meeting else None,
                "meeting_date": meeting.get("properties", {}).get("meeting_date") if meeting else None,
                "vote": edge.get("properties", {}).get("vote"),
                "seat_id": edge.get("properties", {}).get("seat_id"),
                "seat_service_id": edge.get("properties", {}).get("seat_service_id"),
            }
        )

    money_flows = connected_money_flows(
        actor_id,
        node_by_id=node_by_id,
        outgoing=outgoing,
        incoming=incoming,
    )
    evidence_records, related_records = related_records_for_actor(
        actor_id,
        node_by_id=node_by_id,
        outgoing=outgoing,
        incoming=incoming,
    )

    return {
        "id": f"actor-{slugify_subject(actor_id)}-dossier",
        "title": f"Actor dossier: {actor_label}",
        "view_type": "actor_dossier",
        "subject_id": actor_id,
        "subject_node_type": "Actor",
        "contract_version": 1,
        "generated_at": iso_now(),
        "actor": node_summary(actor),
        "metrics": {
            "seat_service_count": len(seat_services),
            "committee_count": len(committees),
            "candidacy_count": len(candidacies),
            "filing_count": len(filings),
            "council_decision_count": len(council_decisions),
            "money_flow_count": len(money_flows),
            "evidence_record_count": len(evidence_records),
            "related_record_count": len(related_records),
            "filing_years": sorted({year for filing in filings if (year := node_year(filing)) is not None}),
            "vote_years": sorted(
                {
                    meeting_date[:4]
                    for vote in vote_records
                    if isinstance((meeting_date := vote.get("meeting_date")), str) and len(meeting_date) >= 4
                }
            ),
        },
        "seat_services": unique_node_summaries(seat_services),
        "committees": unique_node_summaries(committees),
        "candidacies": unique_node_summaries(candidacies),
        "filings": unique_node_summaries(filings),
        "council_votes": vote_records[:80],
        "money_flows": money_flows[:40],
        "evidence_records": unique_node_summaries(evidence_records),
        "related_records": unique_node_summaries(related_records),
    }


def organization_dossier(
    *,
    actor_id: str,
    node_by_id: dict[str, dict[str, Any]],
    outgoing: dict[str, list[dict[str, Any]]],
    incoming: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    organization = node_by_id[actor_id]
    org_label = node_title(organization)
    money_flows = connected_money_flows(
        actor_id,
        node_by_id=node_by_id,
        outgoing=outgoing,
        incoming=incoming,
    )
    linked_decisions = linked_decisions_from_money_flows(
        money_flows,
        node_by_id=node_by_id,
        outgoing=outgoing,
    )
    evidence_records, related_records = related_records_for_actor(
        actor_id,
        node_by_id=node_by_id,
        outgoing=outgoing,
        incoming=incoming,
    )
    all_records = unique_node_summaries(evidence_records + related_records)
    linked_cases = unique_node_summaries(
        linked_cases_from_records(evidence_records + related_records, node_by_id=node_by_id, outgoing=outgoing)
    )
    linked_programs = unique_node_summaries(
        linked_programs_from_records(evidence_records + related_records, node_by_id=node_by_id, outgoing=outgoing)
    )

    return {
        "id": f"organization-{slugify_subject(actor_id)}-dossier",
        "title": f"Organization dossier: {org_label}",
        "view_type": "organization_dossier",
        "subject_id": actor_id,
        "subject_node_type": "Actor",
        "contract_version": 1,
        "generated_at": iso_now(),
        "organization": node_summary(organization),
        "metrics": {
            "money_flow_count": len(money_flows),
            "linked_decision_count": len(linked_decisions),
            "record_count": len(all_records),
            "linked_case_count": len(linked_cases),
            "linked_program_count": len(linked_programs),
        },
        "money_flows": money_flows[:40],
        "linked_decisions": unique_node_summaries(linked_decisions),
        "evidence_records": unique_node_summaries(evidence_records),
        "related_records": unique_node_summaries(related_records),
        "linked_cases": linked_cases,
        "linked_programs": linked_programs,
    }


def decision_dossier(
    *,
    decision_id: str,
    node_by_id: dict[str, dict[str, Any]],
    outgoing: dict[str, list[dict[str, Any]]],
    incoming: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    decision = node_by_id[decision_id]
    meeting = meeting_for_decision(decision_id, outgoing, node_by_id)
    agenda_items = edge_targets(
        outgoing,
        node_by_id,
        decision_id,
        relationship_type="ABOUT_AGENDA_ITEM",
        target_node_type="AgendaItem",
    )
    evidence_records = edge_targets(
        outgoing,
        node_by_id,
        decision_id,
        relationship_type="EVIDENCED_BY",
        target_node_type="Record",
    )
    linked_money_flows = edge_sources(
        incoming,
        node_by_id,
        decision_id,
        relationship_type="RELATES_TO_DECISION",
        source_node_type="MoneyFlow",
    )
    linked_cases = edge_sources(
        incoming,
        node_by_id,
        decision_id,
        relationship_type="RELATES_TO_DECISION",
        source_node_type="Case",
    )
    linked_programs = edge_sources(
        incoming,
        node_by_id,
        decision_id,
        relationship_type="RELATES_TO_DECISION",
        source_node_type="Program",
    )
    votes = []
    for edge in incoming.get(decision_id, []):
        if edge["relationship_type"] != "CAST_VOTE_ON":
            continue
        actor = node_by_id.get(edge["source_id"])
        if actor is None:
            continue
        votes.append(
            {
                "actor_id": actor["id"],
                "actor_label": node_title(actor),
                "vote": edge.get("properties", {}).get("vote"),
                "seat_id": edge.get("properties", {}).get("seat_id"),
                "seat_service_id": edge.get("properties", {}).get("seat_service_id"),
            }
        )

    return {
        "id": f"decision-{slugify_subject(decision_id)}-dossier",
        "title": f"Decision dossier: {node_title(decision)}",
        "view_type": "decision_dossier",
        "subject_id": decision_id,
        "subject_node_type": "Decision",
        "contract_version": 1,
        "generated_at": iso_now(),
        "decision": node_summary(decision),
        "meeting": node_summary(meeting),
        "agenda_items": unique_node_summaries(agenda_items),
        "metrics": {
            "evidence_record_count": len(evidence_records),
            "linked_money_flow_count": len(linked_money_flows),
            "vote_count": len(votes),
            "linked_case_count": len(linked_cases),
            "linked_program_count": len(linked_programs),
        },
        "votes": votes,
        "evidence_records": unique_node_summaries(evidence_records),
        "linked_money_flows": unique_node_summaries(linked_money_flows),
        "linked_cases": unique_node_summaries(linked_cases),
        "linked_programs": unique_node_summaries(linked_programs),
    }


def case_dossier(
    *,
    case_id: str,
    node_by_id: dict[str, dict[str, Any]],
    outgoing: dict[str, list[dict[str, Any]]],
    incoming: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    case = node_by_id[case_id]
    court = next(
        iter(
            edge_targets(
                outgoing,
                node_by_id,
                case_id,
                relationship_type="HEARD_IN_COURT",
                target_node_type="Institution",
            )
        ),
        None,
    )
    proceedings = sort_nodes(
        edge_sources(
            incoming,
            node_by_id,
            case_id,
            relationship_type="PART_OF_CASE",
            source_node_type="Proceeding",
        )
    )
    participations = sort_nodes(
        edge_sources(
            incoming,
            node_by_id,
            case_id,
            relationship_type="PART_OF_CASE",
            source_node_type="CaseParticipation",
        )
    )
    evidence_records = sort_nodes(
        edge_targets(
            outgoing,
            node_by_id,
            case_id,
            relationship_type="EVIDENCED_BY",
            target_node_type="Record",
        )
    )
    related_records = sort_nodes(
        edge_sources(
            incoming,
            node_by_id,
            case_id,
            relationship_type="RELATES_TO_CASE",
            source_node_type="Record",
        )
    )
    issues = sort_nodes(
        edge_targets(
            outgoing,
            node_by_id,
            case_id,
            relationship_type="RELATES_TO_ISSUE",
            target_node_type="Issue",
        )
    )
    programs = sort_nodes(
        edge_targets(
            outgoing,
            node_by_id,
            case_id,
            relationship_type="RELATES_TO_PROGRAM",
            target_node_type="Program",
        )
    )
    places = sort_nodes(
        edge_targets(
            outgoing,
            node_by_id,
            case_id,
            relationship_type="RELATES_TO_PLACE",
            target_node_type="Place",
        )
    )
    linked_local_decisions = sort_nodes(
        edge_targets(
            outgoing,
            node_by_id,
            case_id,
            relationship_type="RELATES_TO_DECISION",
            target_node_type="Decision",
        )
    )

    return {
        "id": f"case-{slugify_subject(case_id)}-dossier",
        "title": f"Case dossier: {node_title(case)}",
        "view_type": "case_dossier",
        "subject_id": case_id,
        "subject_node_type": "Case",
        "contract_version": 1,
        "generated_at": iso_now(),
        "case": node_summary(case),
        "court": node_summary(court),
        "metrics": {
            "proceeding_count": len(proceedings),
            "participation_count": len(participations),
            "evidence_record_count": len(evidence_records),
            "related_record_count": len(related_records),
            "issue_count": len(issues),
            "program_count": len(programs),
            "linked_local_decision_count": len(linked_local_decisions),
        },
        "proceedings": unique_node_summaries(proceedings),
        "participations": unique_node_summaries(participations),
        "evidence_records": unique_node_summaries(evidence_records),
        "related_records": unique_node_summaries(related_records),
        "issues": unique_node_summaries(issues),
        "programs": unique_node_summaries(programs),
        "places": unique_node_summaries(places),
        "linked_local_decisions": unique_node_summaries(linked_local_decisions),
    }


def program_dossier(
    *,
    program_id: str,
    node_by_id: dict[str, dict[str, Any]],
    outgoing: dict[str, list[dict[str, Any]]],
    incoming: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    program = node_by_id[program_id]
    institution = next(
        iter(
            edge_targets(
                outgoing,
                node_by_id,
                program_id,
                relationship_type="OPERATED_BY_INSTITUTION",
                target_node_type="Institution",
            )
        ),
        None,
    )
    jurisdiction_place = next(
        iter(
            edge_targets(
                outgoing,
                node_by_id,
                program_id,
                relationship_type="IN_JURISDICTION",
                target_node_type="Place",
            )
        ),
        None,
    )
    places = unique_nodes(
        sort_nodes(
        edge_targets(
            outgoing,
            node_by_id,
            program_id,
            relationship_type="RELATES_TO_PLACE",
            target_node_type="Place",
        )
    )
    )
    evidence_records = sort_nodes(
        edge_targets(
            outgoing,
            node_by_id,
            program_id,
            relationship_type="EVIDENCED_BY",
            target_node_type="Record",
        )
    )
    evidence_record_ids = {record["id"] for record in evidence_records}
    related_records = unique_nodes(
        sort_nodes(
        edge_sources(
            incoming,
            node_by_id,
            program_id,
            relationship_type="RELATES_TO_PROGRAM",
            source_node_type="Record",
        )
        )
    )
    related_records = [record for record in related_records if record["id"] not in evidence_record_ids]
    linked_cases = unique_nodes(
        sort_nodes(
        edge_targets(
            outgoing,
            node_by_id,
            program_id,
            relationship_type="RELATES_TO_CASE",
            target_node_type="Case",
        )
        + edge_sources(
            incoming,
            node_by_id,
            program_id,
            relationship_type="RELATES_TO_PROGRAM",
            source_node_type="Case",
        )
    )
    )
    linked_decisions = unique_nodes(
        sort_nodes(
        edge_targets(
            outgoing,
            node_by_id,
            program_id,
            relationship_type="RELATES_TO_DECISION",
            target_node_type="Decision",
        )
    )
    )
    direct_money_flows = edge_sources(
        incoming,
        node_by_id,
        program_id,
        relationship_type="RELATES_TO_PROGRAM",
        source_node_type="MoneyFlow",
    )
    linked_money_flows = unique_nodes(
        sort_nodes(
            direct_money_flows
            + linked_money_flows_for_decisions(
                linked_decisions,
                node_by_id=node_by_id,
                incoming=incoming,
            )
        )
    )

    return {
        "id": f"program-{slugify_subject(program_id)}-dossier",
        "title": f"Program dossier: {node_title(program)}",
        "view_type": "program_dossier",
        "subject_id": program_id,
        "subject_node_type": "Program",
        "contract_version": 1,
        "generated_at": iso_now(),
        "program": node_summary(program),
        "institution": node_summary(institution),
        "jurisdiction_place": node_summary(jurisdiction_place),
        "metrics": {
            "place_count": len(places),
            "evidence_record_count": len(evidence_records),
            "related_record_count": len(related_records),
            "linked_case_count": len(linked_cases),
            "linked_decision_count": len(linked_decisions),
            "linked_money_flow_count": len(linked_money_flows),
        },
        "places": unique_node_summaries(places),
        "evidence_records": unique_node_summaries(evidence_records),
        "related_records": unique_node_summaries(related_records),
        "linked_cases": unique_node_summaries(linked_cases),
        "linked_decisions": unique_node_summaries(linked_decisions),
        "linked_money_flows": unique_node_summaries(linked_money_flows),
    }


def project_dossier(
    *,
    project_id: str,
    node_by_id: dict[str, dict[str, Any]],
    outgoing: dict[str, list[dict[str, Any]]],
    incoming: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    project = node_by_id[project_id]
    primary_place = next(
        iter(
            edge_targets(
                outgoing,
                node_by_id,
                project_id,
                relationship_type="PRIMARY_PLACE",
                target_node_type="Place",
            )
        ),
        None,
    )
    jurisdiction_place = next(
        iter(
            edge_targets(
                outgoing,
                node_by_id,
                project_id,
                relationship_type="IN_JURISDICTION",
                target_node_type="Place",
            )
        ),
        None,
    )
    evidence_records = unique_nodes(
        sort_nodes(
            edge_targets(
                outgoing,
                node_by_id,
                project_id,
                relationship_type="EVIDENCED_BY",
                target_node_type="Record",
            )
        )
    )
    evidence_record_ids = {record["id"] for record in evidence_records}
    related_records = unique_nodes(
        sort_nodes(
            edge_sources(
                incoming,
                node_by_id,
                project_id,
                relationship_type="RELATES_TO_PROJECT",
                source_node_type="Record",
            )
        )
    )
    related_records = [record for record in related_records if record["id"] not in evidence_record_ids]
    linked_programs = unique_nodes(
        sort_nodes(
            edge_targets(
                outgoing,
                node_by_id,
                project_id,
                relationship_type="RELATES_TO_PROGRAM",
                target_node_type="Program",
            )
        )
    )
    linked_decisions = unique_nodes(
        sort_nodes(
            edge_targets(
                outgoing,
                node_by_id,
                project_id,
                relationship_type="RELATES_TO_DECISION",
                target_node_type="Decision",
            )
            + edge_sources(
                incoming,
                node_by_id,
                project_id,
                relationship_type="RELATES_TO_PROJECT",
                source_node_type="Decision",
            )
        )
    )
    agreements = unique_nodes(
        sort_nodes(
            edge_sources(
                incoming,
                node_by_id,
                project_id,
                relationship_type="RELATES_TO_PROJECT",
                source_node_type="Agreement",
            )
        )
    )
    amendments = []
    for agreement in agreements:
        amendments.extend(
            edge_sources(
                incoming,
                node_by_id,
                agreement["id"],
                relationship_type="AMENDS_AGREEMENT",
                source_node_type="Amendment",
            )
        )
    amendments.extend(
        edge_sources(
            incoming,
            node_by_id,
            project_id,
            relationship_type="RELATES_TO_PROJECT",
            source_node_type="Amendment",
        )
    )
    amendments = unique_nodes(sort_nodes(amendments))
    linked_money_flows = unique_nodes(
        sort_nodes(
            edge_sources(
                incoming,
                node_by_id,
                project_id,
                relationship_type="RELATES_TO_PROJECT",
                source_node_type="MoneyFlow",
            )
            + linked_money_flows_for_decisions(
                linked_decisions,
                node_by_id=node_by_id,
                incoming=incoming,
            )
        )
    )

    return {
        "id": f"project-{slugify_subject(project_id)}-dossier",
        "title": f"Project dossier: {node_title(project)}",
        "view_type": "project_dossier",
        "subject_id": project_id,
        "subject_node_type": "Project",
        "contract_version": 1,
        "generated_at": iso_now(),
        "project": node_summary(project),
        "primary_place": node_summary(primary_place),
        "jurisdiction_place": node_summary(jurisdiction_place),
        "metrics": {
            "evidence_record_count": len(evidence_records),
            "related_record_count": len(related_records),
            "linked_program_count": len(linked_programs),
            "linked_decision_count": len(linked_decisions),
            "agreement_count": len(agreements),
            "amendment_count": len(amendments),
            "linked_money_flow_count": len(linked_money_flows),
        },
        "evidence_records": unique_node_summaries(evidence_records),
        "related_records": unique_node_summaries(related_records),
        "linked_programs": unique_node_summaries(linked_programs),
        "linked_decisions": unique_node_summaries(linked_decisions),
        "agreements": unique_node_summaries(agreements),
        "amendments": unique_node_summaries(amendments),
        "linked_money_flows": unique_node_summaries(linked_money_flows),
    }


def jurisdiction_delivery_summary(
    *,
    place_id: str,
    node_by_id: dict[str, dict[str, Any]],
    outgoing: dict[str, list[dict[str, Any]]],
    incoming: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    jurisdiction_place = node_by_id[place_id]
    programs = unique_nodes(
        sort_nodes(
            edge_sources(
                incoming,
                node_by_id,
                place_id,
                relationship_type="IN_JURISDICTION",
                source_node_type="Program",
            )
        )
    )
    projects = unique_nodes(
        sort_nodes(
            edge_sources(
                incoming,
                node_by_id,
                place_id,
                relationship_type="IN_JURISDICTION",
                source_node_type="Project",
            )
        )
    )

    program_rollups = []
    project_rollups = []
    linked_decisions: list[dict[str, Any]] = []
    linked_money_flows: list[dict[str, Any]] = []
    linked_cases: list[dict[str, Any]] = []
    evidence_records: list[dict[str, Any]] = []
    related_records: list[dict[str, Any]] = []

    for program in programs:
        payload = program_dossier(
            program_id=program["id"],
            node_by_id=node_by_id,
            outgoing=outgoing,
            incoming=incoming,
        )
        program_rollups.append(
            {
                "program": payload["program"],
                "institution": payload["institution"],
                "metrics": payload["metrics"],
            }
        )
        linked_decisions.extend(payload["linked_decisions"])
        linked_money_flows.extend(payload["linked_money_flows"])
        linked_cases.extend(payload["linked_cases"])
        evidence_records.extend(payload["evidence_records"])
        related_records.extend(payload["related_records"])

    for project in projects:
        payload = project_dossier(
            project_id=project["id"],
            node_by_id=node_by_id,
            outgoing=outgoing,
            incoming=incoming,
        )
        project_rollups.append(
            {
                "project": payload["project"],
                "primary_place": payload["primary_place"],
                "metrics": payload["metrics"],
            }
        )
        linked_decisions.extend(payload["linked_decisions"])
        linked_money_flows.extend(payload["linked_money_flows"])
        evidence_records.extend(payload["evidence_records"])
        related_records.extend(payload["related_records"])

    linked_decisions = unique_summary_items(linked_decisions)
    linked_money_flows = unique_summary_items(linked_money_flows)
    linked_cases = unique_summary_items(linked_cases)
    evidence_records = unique_summary_items(evidence_records)
    related_records = unique_summary_items(
        [record for record in related_records if record.get("id") not in {item["id"] for item in evidence_records}]
    )

    return {
        "id": f"jurisdiction-{slugify_subject(place_id)}-delivery-summary",
        "title": f"Jurisdiction delivery summary: {node_title(jurisdiction_place)}",
        "view_type": "jurisdiction_delivery_summary",
        "subject_id": place_id,
        "subject_node_type": "Place",
        "contract_version": 1,
        "generated_at": iso_now(),
        "jurisdiction_place": node_summary(jurisdiction_place),
        "metrics": {
            "program_count": len(program_rollups),
            "project_count": len(project_rollups),
            "linked_decision_count": len(linked_decisions),
            "linked_money_flow_count": len(linked_money_flows),
            "linked_case_count": len(linked_cases),
            "evidence_record_count": len(evidence_records),
            "related_record_count": len(related_records),
        },
        "program_rollups": program_rollups,
        "project_rollups": project_rollups,
        "linked_decisions": linked_decisions,
        "linked_money_flows": linked_money_flows,
        "linked_cases": linked_cases,
        "evidence_records": evidence_records,
        "related_records": related_records,
    }


def decision_money_rollup(
    *,
    place_id: str,
    nodes: list[dict[str, Any]],
    node_by_id: dict[str, dict[str, Any]],
    outgoing: dict[str, list[dict[str, Any]]],
    incoming: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    jurisdiction_place = node_by_id[place_id]
    rollups = []
    all_flow_type_counts = Counter()
    all_program_ids: set[str] = set()
    all_project_ids: set[str] = set()
    all_case_ids: set[str] = set()

    for node in nodes:
        if node["node_type"] != "Decision":
            continue

        linked_money_flows = unique_nodes(
            sort_nodes(
                edge_sources(
                    incoming,
                    node_by_id,
                    node["id"],
                    relationship_type="RELATES_TO_DECISION",
                    source_node_type="MoneyFlow",
                )
            )
        )
        if not linked_money_flows:
            continue

        linked_programs = unique_nodes(
            sort_nodes(
                edge_sources(
                    incoming,
                    node_by_id,
                    node["id"],
                    relationship_type="RELATES_TO_DECISION",
                    source_node_type="Program",
                )
            )
        )
        linked_projects = unique_nodes(
            sort_nodes(
                edge_targets(
                    outgoing,
                    node_by_id,
                    node["id"],
                    relationship_type="RELATES_TO_PROJECT",
                    target_node_type="Project",
                )
            )
        )
        linked_cases = unique_nodes(
            sort_nodes(
                edge_sources(
                    incoming,
                    node_by_id,
                    node["id"],
                    relationship_type="RELATES_TO_DECISION",
                    source_node_type="Case",
                )
            )
        )

        program_in_scope = any(
            any(
                related["id"] == place_id
                for related in edge_targets(
                    outgoing,
                    node_by_id,
                    program["id"],
                    relationship_type="IN_JURISDICTION",
                    target_node_type="Place",
                )
            )
            for program in linked_programs
        )
        project_in_scope = any(
            any(
                related["id"] == place_id
                for related in edge_targets(
                    outgoing,
                    node_by_id,
                    project["id"],
                    relationship_type="IN_JURISDICTION",
                    target_node_type="Place",
                )
            )
            for project in linked_projects
        )

        if not (program_in_scope or project_in_scope):
            continue

        meeting = meeting_for_decision(node["id"], outgoing, node_by_id)
        agenda_items = unique_nodes(
            sort_nodes(
                edge_targets(
                    outgoing,
                    node_by_id,
                    node["id"],
                    relationship_type="ABOUT_AGENDA_ITEM",
                    target_node_type="AgendaItem",
                )
            )
        )
        evidence_records = unique_nodes(
            sort_nodes(
                edge_targets(
                    outgoing,
                    node_by_id,
                    node["id"],
                    relationship_type="EVIDENCED_BY",
                    target_node_type="Record",
                )
            )
        )

        flow_type_counts = Counter(
            (
                flow.get("properties", {}).get("flow_type")
                or flow.get("properties", {}).get("money_type")
                or "unknown"
            )
            for flow in linked_money_flows
        )
        all_flow_type_counts.update(flow_type_counts)
        all_program_ids.update(program["id"] for program in linked_programs)
        all_project_ids.update(project["id"] for project in linked_projects)
        all_case_ids.update(case["id"] for case in linked_cases)

        rollups.append(
            {
                "decision": node_summary(node),
                "meeting": node_summary(meeting),
                "agenda_items": unique_node_summaries(agenda_items),
                "metrics": {
                    "linked_money_flow_count": len(linked_money_flows),
                    "linked_money_total_amount": sum_money_amounts(linked_money_flows),
                    "linked_program_count": len(linked_programs),
                    "linked_project_count": len(linked_projects),
                    "linked_case_count": len(linked_cases),
                    "evidence_record_count": len(evidence_records),
                    "flow_type_counts": dict(sorted(flow_type_counts.items())),
                },
                "linked_programs": unique_node_summaries(linked_programs),
                "linked_projects": unique_node_summaries(linked_projects),
                "linked_cases": unique_node_summaries(linked_cases),
                "linked_money_flows": unique_node_summaries(linked_money_flows),
                "evidence_records": unique_node_summaries(evidence_records),
            }
        )

    rollups.sort(
        key=lambda item: (
            -(item["metrics"]["linked_money_total_amount"] or 0),
            -item["metrics"]["linked_money_flow_count"],
            item["decision"]["id"],
        )
    )

    return {
        "id": f"decision-money-{slugify_subject(place_id)}-rollup",
        "title": f"Decision money rollup: {node_title(jurisdiction_place)}",
        "view_type": "decision_money_rollup",
        "subject_id": place_id,
        "subject_node_type": "Place",
        "contract_version": 1,
        "generated_at": iso_now(),
        "jurisdiction_place": node_summary(jurisdiction_place),
        "metrics": {
            "decision_count": len(rollups),
            "linked_money_flow_count": sum(item["metrics"]["linked_money_flow_count"] for item in rollups),
            "linked_money_total_amount": sum(item["metrics"]["linked_money_total_amount"] for item in rollups),
            "linked_program_count": len(all_program_ids),
            "linked_project_count": len(all_project_ids),
            "linked_case_count": len(all_case_ids),
            "flow_type_counts": dict(sorted(all_flow_type_counts.items())),
        },
        "decision_rollups": rollups,
    }


def money_overlap_view(
    *,
    nodes: list[dict[str, Any]],
    node_by_id: dict[str, dict[str, Any]],
    outgoing: dict[str, list[dict[str, Any]]],
    incoming: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    flow_type_counts = Counter()
    subject_rollup: dict[tuple[str, str], dict[str, Any]] = {}

    for node in nodes:
        if node["node_type"] != "MoneyFlow":
            continue
        flow_type = node.get("properties", {}).get("flow_type") or node.get("properties", {}).get("money_type") or "unknown"
        flow_type_counts[flow_type] += 1

        connected_edges = outgoing.get(node["id"], []) + incoming.get(node["id"], [])
        for edge in connected_edges:
            other_id = edge["target_id"] if edge["source_id"] == node["id"] else edge["source_id"]
            other = node_by_id.get(other_id)
            if other is None or other["node_type"] in {"Record", "Filing", "ValidationCheck"}:
                continue
            key = (other["node_type"], other["id"])
            bucket = subject_rollup.setdefault(
                key,
                {
                    "node": other,
                    "flow_ids": set(),
                    "flow_types": set(),
                    "bundles": set(),
                    "relationship_types": set(),
                },
            )
            bucket["flow_ids"].add(node["id"])
            bucket["flow_types"].add(flow_type)
            bucket["relationship_types"].add(edge["relationship_type"])
            bucket["bundles"].update(node.get("source_bundle_ids", []))

    overlap_subjects = []
    for bucket in subject_rollup.values():
        flow_count = len(bucket["flow_ids"])
        if flow_count < 2:
            continue
        overlap_subjects.append(
            {
                "node": node_summary(bucket["node"]),
                "flow_count": flow_count,
                "flow_types": sorted(bucket["flow_types"]),
                "relationship_types": sorted(bucket["relationship_types"]),
                "source_bundle_ids": sorted(bucket["bundles"]),
            }
        )

    overlap_subjects.sort(
        key=lambda item: (
            -item["flow_count"],
            -len(item["flow_types"]),
            item["node"]["node_type"],
            item["node"]["id"],
        )
    )

    return {
        "id": "money-overlap-summary",
        "title": "Money overlap summary",
        "view_type": "money_overlap_summary",
        "contract_version": 1,
        "generated_at": iso_now(),
        "metrics": {
            "money_flow_count": sum(flow_type_counts.values()),
            "flow_type_counts": dict(sorted(flow_type_counts.items())),
            "overlap_subject_count": len(overlap_subjects),
        },
        "top_overlap_subjects": overlap_subjects[:25],
    }


def legal_constraint_view(
    *,
    nodes: list[dict[str, Any]],
    node_by_id: dict[str, dict[str, Any]],
    outgoing: dict[str, list[dict[str, Any]]],
    incoming: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    cases = sort_nodes([node for node in nodes if node["node_type"] == "Case"])
    case_views = []
    all_issue_ids: set[str] = set()
    all_program_ids: set[str] = set()
    all_local_decision_ids: set[str] = set()

    for case in cases:
        proceedings = edge_sources(
            incoming,
            node_by_id,
            case["id"],
            relationship_type="PART_OF_CASE",
            source_node_type="Proceeding",
        )
        participations = edge_sources(
            incoming,
            node_by_id,
            case["id"],
            relationship_type="PART_OF_CASE",
            source_node_type="CaseParticipation",
        )
        records = edge_targets(
            outgoing,
            node_by_id,
            case["id"],
            relationship_type="EVIDENCED_BY",
            target_node_type="Record",
        )
        issues = edge_targets(
            outgoing,
            node_by_id,
            case["id"],
            relationship_type="RELATES_TO_ISSUE",
            target_node_type="Issue",
        )
        programs = edge_targets(
            outgoing,
            node_by_id,
            case["id"],
            relationship_type="RELATES_TO_PROGRAM",
            target_node_type="Program",
        )
        decisions = edge_targets(
            outgoing,
            node_by_id,
            case["id"],
            relationship_type="RELATES_TO_DECISION",
            target_node_type="Decision",
        )
        all_issue_ids.update(node["id"] for node in issues)
        all_program_ids.update(node["id"] for node in programs)
        all_local_decision_ids.update(node["id"] for node in decisions)

        case_views.append(
            {
                "case": node_summary(case),
                "proceedings": unique_node_summaries(proceedings),
                "participations": unique_node_summaries(participations),
                "records": unique_node_summaries(records),
                "issues": unique_node_summaries(issues),
                "programs": unique_node_summaries(programs),
                "linked_local_decisions": unique_node_summaries(decisions),
            }
        )

    return {
        "id": "legal-constraint-view",
        "title": "Legal constraint view",
        "view_type": "legal_constraint_view",
        "contract_version": 1,
        "generated_at": iso_now(),
        "metrics": {
            "case_count": len(cases),
            "shared_issue_count": len(all_issue_ids),
            "shared_program_count": len(all_program_ids),
            "linked_local_decision_count": len(all_local_decision_ids),
        },
        "case_views": case_views,
    }


def validation_queue(
    *,
    nodes: list[dict[str, Any]],
    node_by_id: dict[str, dict[str, Any]],
    outgoing: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    severity_rank = {"critical": 4, "high": 3, "medium": 2, "low": 1}
    checks = [node for node in nodes if node["node_type"] == "ValidationCheck"]

    items = []
    for check in checks:
        properties = check.get("properties", {})
        subject = next(iter(edge_targets(outgoing, node_by_id, check["id"], relationship_type="VALIDATES")), None)
        derived_record = next(
            iter(edge_targets(outgoing, node_by_id, check["id"], relationship_type="DERIVED_FROM_RECORD", target_node_type="Record")),
            None,
        )
        items.append(
            {
                "check": node_summary(check),
                "subject": node_summary(subject),
                "derived_record": node_summary(derived_record),
                "status": properties.get("status"),
                "severity": properties.get("severity"),
                "metric_name": properties.get("metric_name"),
                "measured_value_number": properties.get("measured_value_number"),
                "reference_value_number": properties.get("reference_value_number"),
                "absolute_delta_value_number": properties.get("absolute_delta_value_number"),
            }
        )

    items.sort(
        key=lambda item: (
            -severity_rank.get(item["severity"] or "", 0),
            -(item["absolute_delta_value_number"] or 0),
            item["check"]["id"],
        )
    )

    return {
        "id": "validation-queue",
        "title": "Validation queue",
        "view_type": "validation_queue",
        "contract_version": 1,
        "generated_at": iso_now(),
        "metrics": {
            "validation_check_count": len(items),
            "by_status": dict(Counter(item["status"] for item in items)),
            "by_severity": dict(Counter(item["severity"] for item in items)),
        },
        "items": items,
    }


def build_view_from_target(
    target: dict[str, Any],
    *,
    nodes: list[dict[str, Any]],
    node_by_id: dict[str, dict[str, Any]],
    outgoing: dict[str, list[dict[str, Any]]],
    incoming: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    view_type = target["view_type"]
    subject_id = target.get("subject_id")

    if view_type == "actor_dossier":
        return actor_dossier(
            actor_id=subject_id,
            node_by_id=node_by_id,
            outgoing=outgoing,
            incoming=incoming,
        )
    if view_type == "organization_dossier":
        return organization_dossier(
            actor_id=subject_id,
            node_by_id=node_by_id,
            outgoing=outgoing,
            incoming=incoming,
        )
    if view_type == "decision_dossier":
        return decision_dossier(
            decision_id=subject_id,
            node_by_id=node_by_id,
            outgoing=outgoing,
            incoming=incoming,
        )
    if view_type == "case_dossier":
        return case_dossier(
            case_id=subject_id,
            node_by_id=node_by_id,
            outgoing=outgoing,
            incoming=incoming,
        )
    if view_type == "program_dossier":
        return program_dossier(
            program_id=subject_id,
            node_by_id=node_by_id,
            outgoing=outgoing,
            incoming=incoming,
        )
    if view_type == "project_dossier":
        return project_dossier(
            project_id=subject_id,
            node_by_id=node_by_id,
            outgoing=outgoing,
            incoming=incoming,
        )
    if view_type == "jurisdiction_delivery_summary":
        return jurisdiction_delivery_summary(
            place_id=subject_id,
            node_by_id=node_by_id,
            outgoing=outgoing,
            incoming=incoming,
        )
    if view_type == "decision_money_rollup":
        return decision_money_rollup(
            place_id=subject_id,
            nodes=nodes,
            node_by_id=node_by_id,
            outgoing=outgoing,
            incoming=incoming,
        )
    if view_type == "money_overlap_summary":
        return money_overlap_view(
            nodes=nodes,
            node_by_id=node_by_id,
            outgoing=outgoing,
            incoming=incoming,
        )
    if view_type == "legal_constraint_view":
        return legal_constraint_view(
            nodes=nodes,
            node_by_id=node_by_id,
            outgoing=outgoing,
            incoming=incoming,
        )
    if view_type == "validation_queue":
        return validation_queue(
            nodes=nodes,
            node_by_id=node_by_id,
            outgoing=outgoing,
        )

    raise ValueError(f"Unsupported view target type: {view_type}")


def write_markdown_summary(output_dir: Path, views: list[dict[str, Any]]) -> None:
    lines = [
        "# Graph View Summary",
        "",
        f"Generated: {iso_now()}",
        "",
        "## Included Views",
        "",
    ]

    for payload in views:
        lines.append(f"- {payload['title']} (`{payload['view_type']}`)")

    lines.extend(["", "## Highlights", ""])

    actor_views = [payload for payload in views if payload["view_type"] == "actor_dossier"]
    organization_views = [payload for payload in views if payload["view_type"] == "organization_dossier"]
    case_views = [payload for payload in views if payload["view_type"] == "case_dossier"]
    program_views = [payload for payload in views if payload["view_type"] == "program_dossier"]
    project_views = [payload for payload in views if payload["view_type"] == "project_dossier"]
    jurisdiction_views = [payload for payload in views if payload["view_type"] == "jurisdiction_delivery_summary"]
    decision_money_views = [payload for payload in views if payload["view_type"] == "decision_money_rollup"]
    decision_views = [payload for payload in views if payload["view_type"] == "decision_dossier"]
    money_views = [payload for payload in views if payload["view_type"] == "money_overlap_summary"]
    legal_views = [payload for payload in views if payload["view_type"] == "legal_constraint_view"]
    validation_views = [payload for payload in views if payload["view_type"] == "validation_queue"]

    if actor_views:
        lines.append(
            f"- Actor dossiers now cover `{len(actor_views)}` targets, including `{actor_views[0]['actor']['display_label']}` with `{actor_views[0]['metrics']['filing_count']}` filings and `{actor_views[0]['metrics']['council_decision_count']}` council decisions."
        )
    if organization_views:
        lines.append(
            f"- Organization dossiers now cover `{len(organization_views)}` targets, including `{organization_views[0]['organization']['display_label']}` with `{organization_views[0]['metrics']['money_flow_count']}` linked money flows."
        )
    if decision_views:
        lines.append(
            f"- Decision dossiers now cover `{len(decision_views)}` targets, including `{decision_views[0]['decision']['display_label']}` with `{decision_views[0]['metrics']['vote_count']}` vote records."
        )
    if case_views:
        lines.append(
            f"- Case dossiers now cover `{len(case_views)}` targets, including `{case_views[0]['case']['display_label']}` with `{case_views[0]['metrics']['proceeding_count']}` proceedings."
        )
    if program_views:
        lines.append(
            f"- Program dossiers now cover `{len(program_views)}` targets, including `{program_views[0]['program']['display_label']}` with `{program_views[0]['metrics']['linked_decision_count']}` linked decisions and `{program_views[0]['metrics']['linked_money_flow_count']}` linked money flows."
        )
    if project_views:
        lines.append(
            f"- Project dossiers now cover `{len(project_views)}` targets, including `{project_views[0]['project']['display_label']}` with `{project_views[0]['metrics']['agreement_count']}` agreements and `{project_views[0]['metrics']['linked_money_flow_count']}` linked money flows."
        )
    if jurisdiction_views:
        lines.append(
            f"- Jurisdiction delivery summaries now cover `{len(jurisdiction_views)}` targets, including `{jurisdiction_views[0]['jurisdiction_place']['display_label']}` with `{jurisdiction_views[0]['metrics']['program_count']}` programs, `{jurisdiction_views[0]['metrics']['project_count']}` projects, and `{jurisdiction_views[0]['metrics']['linked_money_flow_count']}` linked money flows."
        )
    if decision_money_views:
        lines.append(
            f"- Decision money rollups now cover `{len(decision_money_views)}` targets, including `{decision_money_views[0]['jurisdiction_place']['display_label']}` with `{decision_money_views[0]['metrics']['decision_count']}` money-linked decisions and `${decision_money_views[0]['metrics']['linked_money_total_amount']:,.2f}` in linked flow volume."
        )
    if money_views:
        money = money_views[0]
        lines.append(
            f"- The graph currently materializes `{money['metrics']['money_flow_count']}` money flows across `{len(money['metrics']['flow_type_counts'])}` flow types."
        )
    if legal_views:
        legal = legal_views[0]
        lines.append(
            f"- The legal lane currently includes `{legal['metrics']['case_count']}` cases and links back to `{legal['metrics']['linked_local_decision_count']}` San Rafael local decisions."
        )
    if validation_views:
        validation = validation_views[0]
        lines.append(f"- The validation queue currently contains `{validation['metrics']['validation_check_count']}` checks.")

    lines.extend(["", "## Output Files", ""])
    for payload in views:
        lines.append(f"- `{payload['id']}.json`")
    lines.append("- `index.json`")

    (output_dir / "summary.md").write_text("\n".join(lines) + "\n")


def main() -> None:
    args = parse_args()
    manifest = read_manifest(Path(args.manifest))
    targets_manifest = read_manifest(Path(args.targets))
    projection_dir = Path(args.projection_dir) if args.projection_dir else ROOT / manifest["output_dir"]
    output_dir = Path(args.output_dir) if args.output_dir else projection_dir / VIEW_DIR_NAME
    output_dir.mkdir(parents=True, exist_ok=True)

    for stale_path in output_dir.glob("*.json"):
        stale_path.unlink()
    summary_path = output_dir / "summary.md"
    if summary_path.exists():
        summary_path.unlink()

    nodes, edges, node_by_id, outgoing, incoming = build_indexes(projection_dir)
    _ = edges  # kept for future contract expansion

    views: list[dict[str, Any]] = []
    for target in targets_manifest["targets"]:
        payload = build_view_from_target(
            target,
            nodes=nodes,
            node_by_id=node_by_id,
            outgoing=outgoing,
            incoming=incoming,
        )
        views.append(payload)
        write_json(output_dir / f"{payload['id']}.json", payload)

    index_payload = {
        "generated_at": iso_now(),
        "projection_dir": str(projection_dir.relative_to(ROOT)),
        "contract_version": targets_manifest.get("contract_version", 1),
        "views": [
            {
                "id": payload["id"],
                "title": payload["title"],
                "view_type": payload["view_type"],
                "subject_id": payload.get("subject_id"),
                "subject_node_type": payload.get("subject_node_type"),
                "path": relative_or_absolute(output_dir / f"{payload['id']}.json"),
            }
            for payload in views
        ],
    }
    write_json(output_dir / "index.json", index_payload)
    write_markdown_summary(output_dir, views)


if __name__ == "__main__":
    main()
