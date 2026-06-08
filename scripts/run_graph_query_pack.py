#!/usr/bin/env python3
"""run_graph_query_pack.py — the fixed five-query breadth-sprint pack, ported to
the settled v2 (Person/Organization) schema.

`run_query_pack(projection_dir, schema="v2")` is the importable entrypoint. It
runs over build_graph_v2's output (data/projected/phase0-bcore/candidate-v2/),
NOT the retired graph-v1 Actor/Institution projection. C-land is v2-only, so an
explicit `projection_dir` is REQUIRED — there is no graph-v1 default. Projection
identity is read from `migration-report.json` (the v2 report), with a graceful
fallback. IDs and edges are ported to the settled schema; the one place where the
live graph carries two names for the same edge (Decision → Meeting is `AT_MEETING`
in the candidate projection and additionally `DECIDED_AT` in the live AuraDB) is
resolved through `edge_vocabulary` rather than hard-coded.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from edge_vocabulary import spec_to_live
from graph_projection_lib import ROOT, read_jsonl, write_json

# --- Settled-schema (v2) identities the pack pins on ------------------------
# Migrated from graph-v1: actor-kate-colin -> person-kate-colin,
# inst-san-rafael-city-council -> org-san-rafael-city-council.
KATE_COLIN_ID = "person-kate-colin"
SAN_RAFAEL_COUNCIL_ID = "org-san-rafael-city-council"

# Decision -> Meeting: AT_MEETING in the candidate projection; the live AuraDB
# also carries the redundant DECIDED_AT. edge_vocabulary is the source of truth.
DECISION_MEETING_RELS = tuple(spec_to_live("AT_MEETING"))  # ("AT_MEETING", "DECIDED_AT")

# The form460-schedules OCR bundle is the noisy campaign source; Q4 must never
# import its actors as settled Person/Organization identities.
FORM460_BUNDLE = "san-rafael-city-campaign-form460-schedules-01__bundle-01"

# Default v2 projection for the CLI (build_graph_v2's output).
DEFAULT_PROJECTION_DIR = ROOT / "data" / "projected" / "phase0-bcore" / "candidate-v2"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the fixed five-query breadth-sprint pack against a v2 "
        "(Person/Organization) projection produced by build_graph_v2."
    )
    parser.add_argument(
        "--projection-dir",
        default=str(DEFAULT_PROJECTION_DIR),
        help="v2 projection directory (default: build_graph_v2's candidate-v2/).",
    )
    parser.add_argument(
        "--output-json",
        default=None,
        help="Override JSON report path. Defaults to <projection-dir>/query-pack-report.json.",
    )
    parser.add_argument(
        "--output-md",
        default=None,
        help="Override Markdown report path. Defaults to <projection-dir>/query-pack-report.md.",
    )
    return parser.parse_args()


def iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_indexes(
    projection_dir: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, dict[str, Any]], dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]]]:
    nodes = read_jsonl(projection_dir / "nodes.jsonl")
    edges = read_jsonl(projection_dir / "edges.jsonl")
    node_by_id = {node["id"]: node for node in nodes}
    outgoing: dict[str, list[dict[str, Any]]] = defaultdict(list)
    incoming: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in edges:
        outgoing[edge["source_id"]].append(edge)
        incoming[edge["target_id"]].append(edge)
    return nodes, edges, node_by_id, outgoing, incoming


def node_year(node: dict[str, Any]) -> int | None:
    properties = node.get("properties", {})
    for key in ("meeting_date", "election_date", "posted_at", "filed_at", "signed_at", "started_at"):
        value = properties.get(key)
        if isinstance(value, str) and len(value) >= 4 and value[:4].isdigit():
            return int(value[:4])
    return None


def node_title(node: dict[str, Any]) -> str:
    return node.get("display_label") or node.get("properties", {}).get("title") or node["id"]


def edge_targets(
    outgoing: dict[str, list[dict[str, Any]]],
    node_by_id: dict[str, dict[str, Any]],
    source_id: str,
    *,
    relationship_type: str | None = None,
    target_node_type: str | None = None,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for edge in outgoing.get(source_id, []):
        if relationship_type and edge["relationship_type"] != relationship_type:
            continue
        target = node_by_id.get(edge["target_id"])
        if target is None:
            continue
        if target_node_type and target["node_type"] != target_node_type:
            continue
        results.append(target)
    return results


def edge_sources(
    incoming: dict[str, list[dict[str, Any]]],
    node_by_id: dict[str, dict[str, Any]],
    target_id: str,
    *,
    relationship_type: str | None = None,
    source_node_type: str | None = None,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for edge in incoming.get(target_id, []):
        if relationship_type and edge["relationship_type"] != relationship_type:
            continue
        source = node_by_id.get(edge["source_id"])
        if source is None:
            continue
        if source_node_type and source["node_type"] != source_node_type:
            continue
        results.append(source)
    return results


def has_outgoing_edge(
    outgoing: dict[str, list[dict[str, Any]]],
    source_id: str,
    relationship_type: str,
    target_id: str | None = None,
) -> bool:
    for edge in outgoing.get(source_id, []):
        if edge["relationship_type"] != relationship_type:
            continue
        if target_id and edge["target_id"] != target_id:
            continue
        return True
    return False


def count_votes(incoming: dict[str, list[dict[str, Any]]], decision_id: str) -> int:
    return sum(1 for edge in incoming.get(decision_id, []) if edge["relationship_type"] == "CAST_VOTE")


def evidence_record_ids(outgoing: dict[str, list[dict[str, Any]]], source_id: str) -> list[str]:
    return sorted(
        {
            edge["target_id"]
            for edge in outgoing.get(source_id, [])
            if edge["relationship_type"] == "EVIDENCED_BY"
        }
    )


def meeting_for_decision(
    decision_id: str,
    outgoing: dict[str, list[dict[str, Any]]],
    node_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    # Decision -> Meeting edge is named AT_MEETING here (and DECIDED_AT in the
    # live AuraDB); both resolve through edge_vocabulary's AT_MEETING entry.
    for edge in outgoing.get(decision_id, []):
        if edge["relationship_type"] not in DECISION_MEETING_RELS:
            continue
        target = node_by_id.get(edge["target_id"])
        if target is not None and target["node_type"] == "Meeting":
            return target
    return None


def is_san_rafael_council_decision(
    node: dict[str, Any],
    outgoing: dict[str, list[dict[str, Any]]],
    node_by_id: dict[str, dict[str, Any]],
) -> bool:
    if node["node_type"] != "Decision":
        return False
    if not has_outgoing_edge(outgoing, node["id"], "DECIDED_BY", SAN_RAFAEL_COUNCIL_ID):
        return False
    meeting = meeting_for_decision(node["id"], outgoing, node_by_id)
    if not meeting:
        return False
    year = node_year(meeting)
    return year is not None and year >= 2019


def format_ids(items: list[str], limit: int = 8) -> list[str]:
    if len(items) <= limit:
        return items
    return items[:limit] + [f"... (+{len(items) - limit} more)"]


def run_q1(
    node_by_id: dict[str, dict[str, Any]],
    outgoing: dict[str, list[dict[str, Any]]],
    incoming: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    actor_id = KATE_COLIN_ID
    actor = node_by_id[actor_id]

    seat_services = sorted(
        edge_sources(
            incoming,
            node_by_id,
            actor_id,
            relationship_type="HELD_BY",
            source_node_type="SeatService",
        ),
        key=lambda node: node["id"],
    )
    committees = sorted(
        edge_sources(
            incoming,
            node_by_id,
            actor_id,
            relationship_type="CONTROLLED_BY",
            source_node_type="Committee",
        ),
        key=lambda node: node["id"],
    )

    filing_ids = set()
    for filing in edge_sources(incoming, node_by_id, actor_id, relationship_type="OFFICIAL_FILER", source_node_type="Filing"):
        filing_ids.add(filing["id"])
    for filing in edge_sources(incoming, node_by_id, actor_id, relationship_type="FILED_BY", source_node_type="Filing"):
        filing_ids.add(filing["id"])
    for committee in committees:
        for filing in edge_sources(incoming, node_by_id, committee["id"], relationship_type="FILED_BY_COMMITTEE", source_node_type="Filing"):
            filing_ids.add(filing["id"])
    filings = sorted((node_by_id[filing_id] for filing_id in filing_ids), key=lambda node: (node_year(node) or 0, node["id"]))

    filing_family_counts = Counter(
        filing["properties"].get("filing_type", "unknown") for filing in filings
    )
    filing_years = sorted({year for filing in filings if (year := node_year(filing)) is not None})

    council_decisions = sorted(
        (
            node_by_id[edge["target_id"]]
            for edge in outgoing.get(actor_id, [])
            if edge["relationship_type"] == "CAST_VOTE"
            and edge["target_id"] in node_by_id
            and is_san_rafael_council_decision(node_by_id[edge["target_id"]], outgoing, node_by_id)
        ),
        key=lambda node: (
            meeting_for_decision(node["id"], outgoing, node_by_id)["properties"]["meeting_date"],
            node["id"],
        ),
    )
    council_meeting_ids = sorted(
        {
            meeting["id"]
            for decision in council_decisions
            if (meeting := meeting_for_decision(decision["id"], outgoing, node_by_id))
        }
    )
    council_record_ids = sorted(
        {
            record_id
            for decision in council_decisions
            for record_id in evidence_record_ids(outgoing, decision["id"])
        }
    )

    result = {
        "id": "Q1",
        "title": "actor-kate-colin dossier",
        "pass": len(filing_family_counts) >= 2 and len(filing_years) >= 2,
        "metrics": {
            "seat_service_count": len(seat_services),
            "committee_count": len(committees),
            "filing_count": len(filings),
            "filing_family_counts": dict(sorted(filing_family_counts.items())),
            "filing_years": filing_years,
            "council_decision_count": len(council_decisions),
            "council_meeting_count": len(council_meeting_ids),
            "council_record_count": len(council_record_ids),
        },
        "samples": {
            "seat_service_ids": [node["id"] for node in seat_services],
            "committee_ids": [node["id"] for node in committees],
            "form700_filing_ids": [node["id"] for node in filings if node["properties"].get("filing_type") == "form_700"],
            "form803_filing_ids": [node["id"] for node in filings if node["properties"].get("filing_type") == "form_803"],
            "campaign_filing_ids": [node["id"] for node in filings if node["properties"].get("filing_type", "").startswith("form_4") or node["properties"].get("filing_type") in {"form_496", "form_497", "form_501"}],
            "first_council_decision_ids": format_ids([node["id"] for node in council_decisions[:5]]),
            "last_council_decision_ids": format_ids([node["id"] for node in council_decisions[-5:]]),
        },
        "notes": [
            f"{actor['display_label']} now spans council voting, campaign committees, campaign filings, a local Form 803 filing, and imported Form 700 continuity.",
            "The dossier crosses more than one year and more than one filing family, so it satisfies the fixed breadth-sprint threshold.",
        ],
    }
    return result


def run_q2(
    nodes: list[dict[str, Any]],
    node_by_id: dict[str, dict[str, Any]],
    outgoing: dict[str, list[dict[str, Any]]],
    incoming: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    seat_services = sorted(
        (
            node
            for node in nodes
            if node["node_type"] == "SeatService"
            and node["properties"].get("status") == "current"
            and node["properties"].get("institution_id") == SAN_RAFAEL_COUNCIL_ID
        ),
        key=lambda node: node["id"],
    )

    coverage_rows: list[dict[str, Any]] = []
    disclosure_filing_ids: set[str] = set()
    unresolved_filing_ids: list[str] = []

    for seat_service in seat_services:
        filings = sorted(
            (
                node
                for node in edge_sources(
                    incoming,
                    node_by_id,
                    seat_service["id"],
                    relationship_type="FILED_DURING_SEAT_SERVICE",
                    source_node_type="Filing",
                )
                if node["properties"].get("filing_type") in {"form_700", "form_803"}
                and (node_year(node) or 0) >= 2019
            ),
            key=lambda node: (node_year(node) or 0, node["id"]),
        )
        resolved = 0
        for filing in filings:
            disclosure_filing_ids.add(filing["id"])
            has_actor = has_outgoing_edge(outgoing, filing["id"], "OFFICIAL_FILER")
            has_seat_service = has_outgoing_edge(outgoing, filing["id"], "FILED_DURING_SEAT_SERVICE", seat_service["id"])
            if has_actor and has_seat_service:
                resolved += 1
            else:
                unresolved_filing_ids.append(filing["id"])
        coverage_rows.append(
            {
                "seat_service_id": seat_service["id"],
                "actor_id": seat_service["properties"].get("actor_id"),
                "filing_count": len(filings),
                "filing_ids": [filing["id"] for filing in filings],
                "resolved_count": resolved,
            }
        )

    result = {
        "id": "Q2",
        "title": "current elected disclosure coverage",
        "pass": bool(disclosure_filing_ids) and not unresolved_filing_ids,
        "metrics": {
            "current_seat_service_count": len(seat_services),
            "imported_disclosure_filing_count": len(disclosure_filing_ids),
            "resolved_disclosure_filing_count": len(disclosure_filing_ids) - len(unresolved_filing_ids),
            "unresolved_disclosure_filing_count": len(unresolved_filing_ids),
        },
        "samples": {
            "seat_service_coverage": coverage_rows,
            "unresolved_filing_ids": unresolved_filing_ids,
        },
        "notes": [
            "This query only tracks the narrow imported disclosure lane: current San Rafael elected seat services plus imported Form 700/Form 803 filings since 2019.",
            "The pass condition is strict: every imported disclosure filing must resolve to both a canonical actor and a current seat service.",
        ],
    }
    return result


def run_q3(
    nodes: list[dict[str, Any]],
    node_by_id: dict[str, dict[str, Any]],
    outgoing: dict[str, list[dict[str, Any]]],
    incoming: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    decisions: list[dict[str, Any]] = []
    for node in nodes:
        if not is_san_rafael_council_decision(node, outgoing, node_by_id):
            continue
        meeting = meeting_for_decision(node["id"], outgoing, node_by_id)
        if meeting is None:
            continue
        decisions.append(
            {
                "id": node["id"],
                "title": node_title(node),
                "meeting_id": meeting["id"],
                "meeting_date": meeting["properties"]["meeting_date"],
                "vote_count": count_votes(incoming, node["id"]),
                "evidence_record_ids": evidence_record_ids(outgoing, node["id"]),
            }
        )
    decisions.sort(key=lambda row: (row["meeting_date"], row["id"]))

    years = sorted({int(row["meeting_date"][:4]) for row in decisions})
    meeting_ids = sorted({row["meeting_id"] for row in decisions})
    with_votes = sum(1 for row in decisions if row["vote_count"] > 0)
    with_evidence = sum(1 for row in decisions if row["evidence_record_ids"])

    result = {
        "id": "Q3",
        "title": "San Rafael council decision timeline",
        "pass": len(decisions) > 100 and len(meeting_ids) > 20 and len(years) > 1,
        "metrics": {
            "decision_count": len(decisions),
            "meeting_count": len(meeting_ids),
            "year_span": years,
            "decisions_with_votes": with_votes,
            "decisions_with_evidence": with_evidence,
        },
        "samples": {
            "first_five": decisions[:5],
            "last_five": decisions[-5:],
        },
        "notes": [
            "This is the first fixed-query-pack check that directly measures whether the council breadth pass created an actual multi-year decision timeline.",
            "The result is now a real 2019+ council decision spine rather than one worked-example branch.",
        ],
    }
    return result


def noisy_campaign_actor_ids(nodes: list[dict[str, Any]]) -> list[str]:
    """Q4's noisy-actor guard, recast for the settled v2 schema.

    In graph-v1 this keyed on ``node_type == "Actor"`` — a label that no longer
    exists post-v2, so the check was silently always-false. The invariant is
    unchanged: the noisy form460-schedules OCR bundle must NOT introduce settled
    Person/Organization identities into the graph. Returns the offending
    settled-actor ids (sorted), keyed on actor TYPE + bundle origin, not on the
    retired ``Actor`` label.
    """
    return sorted(
        node["id"]
        for node in nodes
        if node["node_type"] in ("Person", "Organization")
        and FORM460_BUNDLE in node.get("source_bundle_ids", [])
    )


def run_q4(
    nodes: list[dict[str, Any]],
    node_by_id: dict[str, dict[str, Any]],
    outgoing: dict[str, list[dict[str, Any]]],
    incoming: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    in_scope_years = {2020, 2022, 2024}

    campaign_filing_nodes = [
        node
        for node in nodes
        if node["node_type"] == "Filing"
        and node_year(node) in in_scope_years
        and (
            "san-rafael-city-campaign-filings-01__bundle-01" in node["source_bundle_ids"]
            or "san-rafael-city-campaign-ie-01__bundle-01" in node["source_bundle_ids"]
            or "san-rafael-city-campaign-form460-schedules-01__bundle-01" in node["source_bundle_ids"]
        )
    ]

    committee_ids: set[str] = set()
    ie_filing_ids: set[str] = set()
    for filing in campaign_filing_nodes:
        for committee in edge_targets(
            outgoing,
            node_by_id,
            filing["id"],
            relationship_type="FILED_BY_COMMITTEE",
            target_node_type="Committee",
        ):
            committee_ids.add(committee["id"])
        if "san-rafael-city-campaign-ie-01__bundle-01" in filing["source_bundle_ids"]:
            ie_filing_ids.add(filing["id"])

    qa_money_flow_nodes = []
    for node in nodes:
        if node["node_type"] != "MoneyFlow":
            continue
        if "san-rafael-city-campaign-form460-schedules-01__bundle-01" not in node["source_bundle_ids"]:
            continue
        filing_targets = edge_targets(
            outgoing,
            node_by_id,
            node["id"],
            relationship_type="DISCLOSED_IN_FILING",
            target_node_type="Filing",
        )
        if not filing_targets:
            continue
        filing = filing_targets[0]
        if filing["id"] not in {candidate["id"] for candidate in campaign_filing_nodes}:
            continue
        qa_money_flow_nodes.append(node)

    cycle_rollup: dict[int, dict[str, int]] = {
        year: {"committee_count": 0, "filing_count": 0, "ie_filing_count": 0, "qa_money_flow_count": 0}
        for year in sorted(in_scope_years)
    }
    for filing in campaign_filing_nodes:
        year = node_year(filing)
        if year is None:
            continue
        cycle_rollup[year]["filing_count"] += 1
        if filing["id"] in ie_filing_ids:
            cycle_rollup[year]["ie_filing_count"] += 1
    for committee_id in committee_ids:
        committee = node_by_id[committee_id]
        year = node_year(committee) or None
        if year in cycle_rollup:
            cycle_rollup[year]["committee_count"] += 1
    # Committees often lack direct dates; infer year from linked filings when needed.
    for year in sorted(in_scope_years):
        if cycle_rollup[year]["committee_count"] == 0:
            linked_committees = set()
            for filing in campaign_filing_nodes:
                if node_year(filing) != year:
                    continue
                for committee in edge_targets(
                    outgoing,
                    node_by_id,
                    filing["id"],
                    relationship_type="FILED_BY_COMMITTEE",
                    target_node_type="Committee",
                ):
                    linked_committees.add(committee["id"])
            cycle_rollup[year]["committee_count"] = len(linked_committees)
    for flow in qa_money_flow_nodes:
        filing_targets = edge_targets(
            outgoing,
            node_by_id,
            flow["id"],
            relationship_type="DISCLOSED_IN_FILING",
            target_node_type="Filing",
        )
        if not filing_targets:
            continue
        year = node_year(filing_targets[0])
        if year in cycle_rollup:
            cycle_rollup[year]["qa_money_flow_count"] += 1

    recurrence_years = sorted(year for year, row in cycle_rollup.items() if row["qa_money_flow_count"] > 0)
    noisy_actor_nodes = noisy_campaign_actor_ids(nodes)

    notes = []
    if len(recurrence_years) >= 2 and not noisy_actor_nodes:
        notes.append(
            "QA-backed campaign money now spans more than one cycle without importing noisy OCR actors into graph-v1."
        )
    else:
        notes.append(
            "Committees and filings now span 2020, 2022, and 2024, but the QA-backed money layer still effectively lives in too few cycles."
        )
        notes.append(
            "That is the core reason this query still fails: the graph has campaign filing breadth, but not enough multi-cycle QA-backed money recurrence yet."
        )

    result = {
        "id": "Q4",
        "title": "San Rafael election money spine",
        "pass": len(recurrence_years) >= 2 and not noisy_actor_nodes,
        "metrics": {
            "cycle_rollup": cycle_rollup,
            "committee_count": len(committee_ids),
            "filing_count": len(campaign_filing_nodes),
            "ie_filing_count": len(ie_filing_ids),
            "qa_money_flow_count": len(qa_money_flow_nodes),
            "qa_money_flow_years": recurrence_years,
            "imported_noisy_actor_count": len(noisy_actor_nodes),
        },
        "samples": {
            "committee_ids": format_ids(sorted(committee_ids), limit=12),
            "ie_filing_ids": format_ids(sorted(ie_filing_ids), limit=12),
            "qa_money_flow_samples": format_ids(sorted(node["id"] for node in qa_money_flow_nodes), limit=12),
            "noisy_actor_ids": noisy_actor_nodes,
        },
        "notes": notes,
    }
    return result


def run_q5(
    nodes: list[dict[str, Any]],
    node_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    validation_nodes = sorted(
        (node for node in nodes if node["node_type"] == "ValidationCheck"),
        key=lambda node: (node["properties"].get("subject_node_id", ""), node["id"]),
    )
    status_counts = Counter(node["properties"].get("status", "unknown") for node in validation_nodes)
    subject_rows: dict[str, dict[str, Any]] = {}
    for node in validation_nodes:
        subject_id = node["properties"].get("subject_node_id")
        row = subject_rows.setdefault(
            subject_id,
            {
                "subject_node_id": subject_id,
                "subject_display_label": node_title(node_by_id[subject_id]) if subject_id in node_by_id else subject_id,
                "check_count": 0,
                "status_counts": Counter(),
                "max_absolute_delta_value_number": 0.0,
            },
        )
        row["check_count"] += 1
        row["status_counts"][node["properties"].get("status", "unknown")] += 1
        row["max_absolute_delta_value_number"] = max(
            row["max_absolute_delta_value_number"],
            float(node["properties"].get("absolute_delta_value_number", 0.0) or 0.0),
        )

    subject_summaries = []
    for subject_id, row in sorted(subject_rows.items()):
        row["status_counts"] = dict(sorted(row["status_counts"].items()))
        subject_summaries.append(row)

    queue_is_small = len(validation_nodes) <= 20 and len(subject_rows) <= 10
    notes = []
    if queue_is_small:
        notes.append("The validation queue remains small enough to review directly.")
    else:
        notes.append(
            "The validation queue is too large for the current checkpoint and needs pruning or better reference-aware suppression."
        )
    focus_row = next(
        (
            row
            for row in subject_summaries
            if row["subject_node_id"] == "filing-san-rafael-campaign-entry-37677"
        ),
        None,
    )
    if focus_row is not None:
        notes.append(
            "The known Kate Colin 2024 Schedule A extraction gap remains visible in the queue and is still the main carried-forward reconciliation issue."
        )

    result = {
        "id": "Q5",
        "title": "validation queue",
        "pass": queue_is_small,
        "metrics": {
            "validation_check_count": len(validation_nodes),
            "subject_filing_count": len(subject_rows),
            "status_counts": dict(sorted(status_counts.items())),
        },
        "samples": {
            "subjects": subject_summaries,
            "focus_subject": focus_row,
        },
        "notes": notes
        + [
            "This query checks whether new breadth work is creating a manageable validation surface instead of a noisy anomaly dump."
        ],
    }
    return result


def run_l1(
    nodes: list[dict[str, Any]],
    node_by_id: dict[str, dict[str, Any]],
    outgoing: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    boyd_id = "case-boyd-v-city-of-san-rafael"
    grants_supreme_id = "case-city-of-grants-pass-v-johnson"
    grants_lineage_ids = [
        "case-blake-v-city-of-grants-pass",
        "case-johnson-v-city-of-grants-pass",
        "case-city-of-grants-pass-v-johnson",
    ]
    legal_nodes = [node for node in nodes if node["node_type"] in {"Case", "Proceeding", "CaseParticipation"}]

    boyd_present = boyd_id in node_by_id
    grants_supreme_present = grants_supreme_id in node_by_id
    grants_lineage_present = [case_id for case_id in grants_lineage_ids if case_id in node_by_id]

    shared_program_ids = sorted(
        set(edge["target_id"] for edge in outgoing.get(boyd_id, []) if edge["relationship_type"] == "RELATES_TO_PROGRAM")
        & set(edge["target_id"] for edge in outgoing.get(grants_supreme_id, []) if edge["relationship_type"] == "RELATES_TO_PROGRAM")
    )
    linked_local_decision_ids = sorted(
        set(edge["target_id"] for edge in outgoing.get(boyd_id, []) if edge["relationship_type"] == "RELATES_TO_DECISION")
        | set(edge["target_id"] for edge in outgoing.get(grants_supreme_id, []) if edge["relationship_type"] == "RELATES_TO_DECISION")
    )
    shared_issue_ids = sorted(
        set(edge["target_id"] for edge in outgoing.get(boyd_id, []) if edge["relationship_type"] == "RELATES_TO_ISSUE")
        & set(edge["target_id"] for edge in outgoing.get(grants_supreme_id, []) if edge["relationship_type"] == "RELATES_TO_ISSUE")
    )
    legal_record_ids = sorted(
        {
            edge["target_id"]
            for case_id in [boyd_id, *grants_lineage_ids]
            for edge in outgoing.get(case_id, [])
            if edge["relationship_type"] == "EVIDENCED_BY"
        }
    )

    passed = (
        boyd_present
        and grants_supreme_present
        and len(grants_lineage_present) == len(grants_lineage_ids)
        and (bool(shared_program_ids) or len(linked_local_decision_ids) >= 2)
    )

    return {
        "id": "L1",
        "title": "legal constraint chain",
        "pass": passed,
        "metrics": {
            "boyd_present": boyd_present,
            "grants_pass_present": grants_supreme_present,
            "grants_pass_lineage_case_count": len(grants_lineage_present),
            "shared_issue_count": len(shared_issue_ids),
            "shared_program_count": len(shared_program_ids),
            "linked_local_decision_count": len(linked_local_decision_ids),
            "legal_record_count": len(legal_record_ids),
            "legal_node_count": len(legal_nodes),
        },
        "samples": {
            "grants_pass_lineage_case_ids": grants_lineage_present,
            "shared_issue_ids": shared_issue_ids,
            "shared_program_ids": shared_program_ids,
            "linked_local_decision_ids": linked_local_decision_ids,
            "legal_record_ids": format_ids(legal_record_ids, limit=12),
        },
        "notes": [
            "This is a supplemental query, not part of the fixed five-query breadth gate.",
            "It checks whether the first local-case plus controlling-precedent pair is materialized well enough to show a real legal constraint chain back into San Rafael decisions and programs.",
        ],
    }


def build_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Graph Query Pack Report",
        "",
        f"- `generated_at`: {report['generated_at']}",
        f"- `engine`: {report['engine']}",
        f"- `projection_id`: {report['projection_id']}",
        f"- `nodes`: {report['projection_counts']['nodes']}",
        f"- `edges`: {report['projection_counts']['edges']}",
        f"- `queries_passed`: {report['summary']['passed']}/{report['summary']['total']}",
        "",
    ]
    for query in report["queries"]:
        lines.extend(
            [
                f"## {query['id']}: {query['title']}",
                "",
                f"- `pass`: {'yes' if query['pass'] else 'no'}",
                f"- `metrics`: {json.dumps(query['metrics'], sort_keys=True)}",
            ]
        )
        if query.get("notes"):
            lines.append("- `notes`:")
            for note in query["notes"]:
                lines.append(f"  - {note}")
        lines.append("")
    if report.get("supplemental_queries"):
        lines.extend(["## Supplemental Queries", ""])
        for query in report["supplemental_queries"]:
            lines.extend(
                [
                    f"### {query['id']}: {query['title']}",
                    "",
                    f"- `pass`: {'yes' if query['pass'] else 'no'}",
                    f"- `metrics`: {json.dumps(query['metrics'], sort_keys=True)}",
                ]
            )
            if query.get("notes"):
                lines.append("- `notes`:")
                for note in query["notes"]:
                    lines.append(f"  - {note}")
            lines.append("")
    lines.extend(
        [
            "## Recommendation",
            "",
            report["next_recommendation"],
            "",
        ]
    )
    return "\n".join(lines)


def read_projection_metadata(projection_dir) -> dict[str, Any]:
    """Read projection identity from migration-report.json (the v2 report), NOT
    the retired graph-v1 report.json. Falls back gracefully if the report
    predates build_graph_v2's projection_id/generated_at fields, so an older
    projection never crashes the pack."""
    path = Path(projection_dir) / "migration-report.json"
    data = json.loads(path.read_text()) if path.exists() else {}
    return {
        "projection_id": data.get("projection_id") or "graph-v2-native",
        "generated_at": data.get("generated_at") or "unknown",
        "node_type_counts": data.get("nodes_by_type", {}),
    }


def run_query_pack(projection_dir=None, schema: str = "v2") -> dict[str, Any]:
    """Run the five-query breadth-sprint pack over a v2 projection.

    C-land is v2-only: there is no graph-v1 default, so `projection_dir` is
    REQUIRED. Returns ``{ok, failures, metrics, ...}`` where ``ok`` is True iff
    every core query (Q1–Q5) passes, ``failures`` lists the ids that didn't, and
    ``metrics`` maps each query id to its metrics block.
    """
    if schema != "v2":
        raise ValueError(
            f"run_query_pack supports only schema='v2' in Phase 0 C-land; got {schema!r}"
        )
    if projection_dir is None:
        raise ValueError(
            "run_query_pack(schema='v2') requires an explicit projection_dir "
            "(there is no graph-v1 default)"
        )
    projection_dir = Path(projection_dir).resolve()
    nodes, edges, node_by_id, outgoing, incoming = build_indexes(projection_dir)
    meta = read_projection_metadata(projection_dir)

    queries = [
        run_q1(node_by_id, outgoing, incoming),
        run_q2(nodes, node_by_id, outgoing, incoming),
        run_q3(nodes, node_by_id, outgoing, incoming),
        run_q4(nodes, node_by_id, outgoing, incoming),
        run_q5(nodes, node_by_id),
    ]
    supplemental_queries = [run_l1(nodes, node_by_id, outgoing)]
    failures = [query["id"] for query in queries if not query["pass"]]
    return {
        "ok": not failures,
        "failures": failures,
        "metrics": {query["id"]: query["metrics"] for query in queries},
        "queries": queries,
        "supplemental_queries": supplemental_queries,
        "schema": schema,
        "projection_id": meta["projection_id"],
        "projection_generated_at": meta["generated_at"],
        "projection_counts": {
            "nodes": len(nodes),
            "edges": len(edges),
            "node_type_counts": meta["node_type_counts"],
        },
    }


def main() -> None:
    """Thin CLI wrapper over run_query_pack: write the JSON + Markdown report."""
    args = parse_args()
    projection_dir = Path(args.projection_dir).resolve()
    output_json = (
        projection_dir / "query-pack-report.json"
        if args.output_json is None
        else Path(args.output_json).resolve()
    )
    output_md = (
        projection_dir / "query-pack-report.md"
        if args.output_md is None
        else Path(args.output_md).resolve()
    )

    result = run_query_pack(projection_dir, schema="v2")
    queries = result["queries"]
    failed = result["failures"]
    passed = len(queries) - len(failed)
    if failed == ["Q4"]:
        next_recommendation = (
            "Continue the San Rafael city-office campaign filing backbone, but focus specifically on multi-cycle QA-backed "
            "money extraction and validation rather than opening county tracks or adding more schema."
        )
    else:
        next_recommendation = (
            "Do not widen scope blindly. Use the failed query set to pick the next density move and keep the sprint San Rafael-first."
        )

    report = {
        "generated_at": iso_now(),
        "engine": "projection_jsonl_v2",
        "schema": result["schema"],
        "projection_id": result["projection_id"],
        "projection_report_generated_at": result["projection_generated_at"],
        "projection_counts": result["projection_counts"],
        "summary": {
            "total": len(queries),
            "passed": passed,
            "failed": len(failed),
            "failed_query_ids": failed,
        },
        "queries": queries,
        "supplemental_queries": result["supplemental_queries"],
        "next_recommendation": next_recommendation,
    }

    write_json(output_json, report)
    output_md.write_text(build_markdown(report))
    print(
        json.dumps(
            {
                "output_json": str(output_json),
                "output_md": str(output_md),
                "ok": result["ok"],
                "passed": passed,
                "failed_query_ids": failed,
                "next_recommendation": next_recommendation,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
