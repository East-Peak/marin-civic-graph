#!/usr/bin/env python3

from __future__ import annotations

import argparse
from collections import Counter, defaultdict, deque
from pathlib import Path

from graph_projection_lib import DEFAULT_MANIFEST_PATH, ROOT, read_jsonl, read_manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run basic smoke checks on the projected graph-v1 payload.")
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
    return parser.parse_args()


def assert_path(adjacency: dict[str, set[str]], start_id: str, target_id: str) -> None:
    if start_id == target_id:
        return
    visited = {start_id}
    queue = deque([start_id])
    while queue:
        current = queue.popleft()
        for neighbor in adjacency[current]:
            if neighbor == target_id:
                return
            if neighbor in visited:
                continue
            visited.add(neighbor)
            queue.append(neighbor)
    raise AssertionError(f"No graph path between {start_id} and {target_id}")


def main() -> None:
    args = parse_args()
    manifest = read_manifest(Path(args.manifest).resolve())
    projection_dir = (
        (ROOT / manifest["output_dir"]).resolve()
        if args.projection_dir is None
        else Path(args.projection_dir).resolve()
    )

    nodes = read_jsonl(projection_dir / "nodes.jsonl")
    edges = read_jsonl(projection_dir / "edges.jsonl")
    node_ids = {node["id"] for node in nodes}
    node_by_id = {node["id"]: node for node in nodes}

    node_type_counts = Counter(node["node_type"] for node in nodes)
    required_types = [
        "Actor",
        "Case",
        "CaseParticipation",
        "Institution",
        "Seat",
        "SeatService",
        "Election",
        "Committee",
        "EconomicInterestDisclosure",
        "Meeting",
        "AgendaItem",
        "Decision",
        "Filing",
        "MoneyFlow",
        "Proceeding",
        "Program",
        "Record",
        "ValidationCheck",
    ]
    missing_types = [node_type for node_type in required_types if node_type_counts[node_type] == 0]
    if missing_types:
        raise AssertionError(f"Missing expected node types: {missing_types}")
    if node_type_counts["Meeting"] < 200:
        raise AssertionError(
            f"Expected the San Rafael council breadth slice to lift Meeting density above 200, found {node_type_counts['Meeting']}"
        )
    if node_type_counts["Decision"] < 500:
        raise AssertionError(
            f"Expected the San Rafael council decision slice to lift Decision density above 500, found {node_type_counts['Decision']}"
        )
    if node_type_counts["AgendaItem"] < 1000:
        raise AssertionError(
            f"Expected the San Rafael council decision slice to lift AgendaItem density above 1000, found {node_type_counts['AgendaItem']}"
        )

    dangling_edges = [
        edge
        for edge in edges
        if edge["source_id"] not in node_ids or edge["target_id"] not in node_ids
    ]
    if dangling_edges:
        raise AssertionError(f"Found {len(dangling_edges)} dangling edges in projection output")

    adjacency: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        adjacency[edge["source_id"]].add(edge["target_id"])
        adjacency[edge["target_id"]].add(edge["source_id"])

    assert_path(adjacency, "actor-kate-colin", "seatservice-kate-colin-mayor-current")
    assert_path(adjacency, "actor-kate-colin", "filing-2025-09-04-kate-colin-form-803")
    assert_path(
        adjacency,
        "actor-kate-colin",
        "eid-san-rafael-form700-2025-03-30-colin-catherine-annual-mayor-city-council",
    )
    assert_path(
        adjacency,
        "eid-san-rafael-form700-2025-03-30-colin-catherine-annual-mayor-city-council",
        "seatservice-kate-colin-mayor-current",
    )
    assert_path(
        adjacency,
        "filing-2025-09-04-kate-colin-form-803",
        "moneyflow-2025-08-08-pge-to-canal-alliance-form-803",
    )
    assert_path(
        adjacency,
        "actor-downtown-streets-team",
        "decision-2024-08-19-resolution-15336",
    )
    assert_path(
        adjacency,
        "decision-2024-08-19-resolution-15336",
        "record-2024-08-19-resolution-15336-text",
    )
    assert_path(
        adjacency,
        "meeting-2026-03-16-san-rafael-city-council",
        "record-2026-03-16-san-rafael-city-council-page",
    )
    assert_path(
        adjacency,
        "meeting-2026-03-16-san-rafael-city-council",
        "decision-2026-03-16-san-rafael-city-council-2-consent-calendar-approval",
    )
    assert_path(
        adjacency,
        "decision-2026-03-16-san-rafael-city-council-2-consent-calendar-approval",
        "agenda-item-2026-03-16-san-rafael-city-council-2",
    )
    assert_path(
        adjacency,
        "meeting-2026-03-16-san-rafael-city-council",
        "inst-san-rafael-city-council",
    )
    assert_path(
        adjacency,
        "case-boyd-v-city-of-san-rafael",
        "decision-2024-08-19-resolution-15336",
    )
    assert_path(
        adjacency,
        "case-boyd-v-city-of-san-rafael",
        "program-san-rafael-sanctioned-camping",
    )
    assert_path(
        adjacency,
        "case-city-of-grants-pass-v-johnson",
        "decision-2024-08-19-resolution-15336",
    )
    assert_path(
        adjacency,
        "case-blake-v-city-of-grants-pass",
        "case-city-of-grants-pass-v-johnson",
    )

    validation_nodes = [
        node["id"]
        for node in nodes
        if node["node_type"] == "ValidationCheck"
        and node["properties"].get("subject_node_id") == "filing-san-rafael-campaign-entry-37677"
    ]
    if not validation_nodes:
        raise AssertionError("Missing validation check for filing-san-rafael-campaign-entry-37677")
    assert_path(adjacency, validation_nodes[0], "filing-san-rafael-campaign-entry-37677")

    print(
        "graph-smoke-checks-passed",
        {
            "nodes": len(nodes),
            "edges": len(edges),
            "node_type_counts": dict(sorted(node_type_counts.items())),
            "validation_check": validation_nodes[0],
            "decision_sample": node_by_id["decision-2024-08-19-resolution-15336"]["display_label"],
            "legal_case_sample": node_by_id["case-city-of-grants-pass-v-johnson"]["display_label"],
        },
    )


if __name__ == "__main__":
    main()
