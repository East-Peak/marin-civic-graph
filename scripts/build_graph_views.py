#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from graph_projection_lib import DEFAULT_MANIFEST_PATH, ROOT, read_manifest, write_json
from run_graph_query_pack import (
    build_indexes,
    edge_sources,
    edge_targets,
    evidence_record_ids,
    format_ids,
    meeting_for_decision,
    node_title,
    node_year,
)


VIEW_DIR_NAME = "views"


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


def actor_dossier(
    *,
    actor_id: str,
    node_by_id: dict[str, dict[str, Any]],
    outgoing: dict[str, list[dict[str, Any]]],
    incoming: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    actor = node_by_id[actor_id]

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
    committees = sorted(
        edge_sources(
            incoming,
            node_by_id,
            actor_id,
            relationship_type="CONTROLLED_BY_ACTOR",
            source_node_type="Committee",
        ),
        key=lambda node: (node_year(node) or 0, node["id"]),
    )
    filings = sorted(
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
        }.values(),
        key=lambda node: (node_year(node) or 0, node["id"]),
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

    money_flows = []
    for edge in outgoing.get(actor_id, []):
        if edge["relationship_type"] not in {"FROM_SOURCE", "TO_TARGET", "REQUESTED_BY_ACTOR"}:
            continue
        flow = node_by_id.get(edge["target_id"])
        if flow is None or flow["node_type"] != "MoneyFlow":
            continue
        money_flows.append(
            {
                "relationship_type": edge["relationship_type"],
                "money_flow": node_summary(flow),
            }
        )
    for edge in incoming.get(actor_id, []):
        if edge["relationship_type"] not in {"FROM_SOURCE", "TO_TARGET", "REQUESTED_BY_ACTOR"}:
            continue
        flow = node_by_id.get(edge["source_id"])
        if flow is None or flow["node_type"] != "MoneyFlow":
            continue
        money_flows.append(
            {
                "relationship_type": edge["relationship_type"],
                "money_flow": node_summary(flow),
            }
        )

    record_ids = sorted(
        {
            record_id
            for filing in filings
            for record_id in evidence_record_ids(outgoing, filing["id"])
        }
        | {
            record_id
            for decision in council_decisions
            for record_id in evidence_record_ids(outgoing, decision["id"])
        }
    )

    return {
        "id": "actor-kate-colin-dossier",
        "title": "Actor dossier: Kate Colin",
        "generated_at": iso_now(),
        "actor": node_summary(actor),
        "metrics": {
            "seat_service_count": len(seat_services),
            "committee_count": len(committees),
            "filing_count": len(filings),
            "council_decision_count": len(council_decisions),
            "money_flow_count": len(money_flows),
            "record_count": len(record_ids),
            "filing_years": sorted({year for filing in filings if (year := node_year(filing)) is not None}),
        },
        "seat_services": unique_node_summaries(seat_services),
        "committees": unique_node_summaries(committees),
        "filings": unique_node_summaries(filings),
        "council_votes": vote_records[:40],
        "money_flows": money_flows[:40],
        "record_ids": format_ids(record_ids, limit=30),
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
        "id": "decision-resolution-15336-dossier",
        "title": "Decision dossier: Resolution 15336",
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
    cases = sorted(
        [node for node in nodes if node["node_type"] == "Case"],
        key=lambda node: (node_year(node) or 0, node["id"]),
    )
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
        "generated_at": iso_now(),
        "metrics": {
            "validation_check_count": len(items),
            "by_status": dict(Counter(item["status"] for item in items)),
            "by_severity": dict(Counter(item["severity"] for item in items)),
        },
        "items": items,
    }


def write_markdown_summary(output_dir: Path, views: dict[str, dict[str, Any]]) -> None:
    actor = views["actor-kate-colin-dossier"]
    decision = views["decision-resolution-15336-dossier"]
    money = views["money-overlap-summary"]
    legal = views["legal-constraint-view"]
    validation = views["validation-queue"]

    lines = [
        "# Graph View Summary",
        "",
        f"Generated: {iso_now()}",
        "",
        "## Included Views",
        "",
        "- Actor dossier: Kate Colin",
        "- Decision dossier: Resolution 15336",
        "- Money overlap summary",
        "- Legal constraint view",
        "- Validation queue",
        "",
        "## Highlights",
        "",
        f"- Kate Colin currently spans `{actor['metrics']['seat_service_count']}` seat-service windows, `{actor['metrics']['committee_count']}` committees, `{actor['metrics']['filing_count']}` filings, and `{actor['metrics']['council_decision_count']}` council decisions.",
        f"- Resolution 15336 currently has `{decision['metrics']['vote_count']}` vote records, `{decision['metrics']['linked_money_flow_count']}` linked money flows, and `{decision['metrics']['linked_case_count']}` linked cases.",
        f"- The graph currently materializes `{money['metrics']['money_flow_count']}` money flows across `{len(money['metrics']['flow_type_counts'])}` flow types.",
        f"- The legal lane currently includes `{legal['metrics']['case_count']}` cases and links back to `{legal['metrics']['linked_local_decision_count']}` San Rafael local decisions.",
        f"- The validation queue currently contains `{validation['metrics']['validation_check_count']}` checks.",
        "",
        "## Output Files",
        "",
        "- `actor-kate-colin-dossier.json`",
        "- `decision-resolution-15336-dossier.json`",
        "- `money-overlap-summary.json`",
        "- `legal-constraint-view.json`",
        "- `validation-queue.json`",
        "- `index.json`",
    ]
    (output_dir / "summary.md").write_text("\n".join(lines) + "\n")


def main() -> None:
    args = parse_args()
    manifest = read_manifest(Path(args.manifest))
    projection_dir = Path(args.projection_dir) if args.projection_dir else ROOT / manifest["output_dir"]
    output_dir = Path(args.output_dir) if args.output_dir else projection_dir / VIEW_DIR_NAME
    output_dir.mkdir(parents=True, exist_ok=True)

    nodes, edges, node_by_id, outgoing, incoming = build_indexes(projection_dir)

    views = {
        "actor-kate-colin-dossier": actor_dossier(
            actor_id="actor-kate-colin",
            node_by_id=node_by_id,
            outgoing=outgoing,
            incoming=incoming,
        ),
        "decision-resolution-15336-dossier": decision_dossier(
            decision_id="decision-2024-08-19-resolution-15336",
            node_by_id=node_by_id,
            outgoing=outgoing,
            incoming=incoming,
        ),
        "money-overlap-summary": money_overlap_view(
            nodes=nodes,
            node_by_id=node_by_id,
            outgoing=outgoing,
            incoming=incoming,
        ),
        "legal-constraint-view": legal_constraint_view(
            nodes=nodes,
            node_by_id=node_by_id,
            outgoing=outgoing,
            incoming=incoming,
        ),
        "validation-queue": validation_queue(
            nodes=nodes,
            node_by_id=node_by_id,
            outgoing=outgoing,
        ),
    }

    for view_id, payload in views.items():
        write_json(output_dir / f"{view_id}.json", payload)

    index_payload = {
        "generated_at": iso_now(),
        "projection_dir": str(projection_dir.relative_to(ROOT)),
        "views": [
            {
                "id": view_id,
                "title": payload["title"],
                "path": f"{output_dir.relative_to(ROOT)}/{view_id}.json",
            }
            for view_id, payload in views.items()
        ],
    }
    write_json(output_dir / "index.json", index_payload)
    write_markdown_summary(output_dir, views)


if __name__ == "__main__":
    main()
