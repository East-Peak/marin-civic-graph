"""Build the dual-role candidate read model (M2d) — a JSONL sidecar, never the graph.

Joins funding-IN evidence (990 gov-grant Filings, USASpending award
MoneyFlows) against influence-OUT evidence (campaign-finance MoneyFlows the
org sources) and surfaces every org carrying BOTH legs as a row in a neutral
ranked table. The table is a read model: JSONL + a coverage summary under the
review dir — never nodes, never edges, never loaded into a database (this
module has no neo4j import and no --load by design).

Inputs are the ingestors' envelope dirs (`nodes.jsonl` + `edges.jsonl`),
consumed as-is. Joins are deterministic-only (identical id / allowlisted
SAME_AS / operator-approved resolutions); anything resting on a queued
ResolutionCandidate is withheld pending review.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

USASPENDING_COVERAGE_SCOPE = "usaspending_prime_award_total_obligation"


# ---------------------------------------------------------------------------
# Loader — envelope dirs, Decision 1 dedupe
# ---------------------------------------------------------------------------


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _canonical(row: dict[str, Any]) -> str:
    return json.dumps(row, sort_keys=True)


def load_envelope_dirs(
    dirs: list[Path],
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Load + merge envelope dirs into deduped node/edge sets.

    Nodes dedupe by id — byte-identical re-emissions collapse silently
    (overlapping bundles and a dir passed twice are operator-normal); the
    same id with a DIFFERING payload fails loud, never pick-one. Edges
    dedupe by full-row equality, first occurrence kept in load order.
    """
    nodes_by_id: dict[str, dict[str, Any]] = {}
    node_canon: dict[str, str] = {}
    edges: list[dict[str, Any]] = []
    seen_edges: set[str] = set()
    for directory in dirs:
        directory = Path(directory)
        for row in _read_jsonl(directory / "nodes.jsonl"):
            node_id = row["id"]
            canon = _canonical(row)
            prior = node_canon.get(node_id)
            if prior is None:
                nodes_by_id[node_id] = row
                node_canon[node_id] = canon
            elif prior != canon:
                raise ValueError(
                    f"node id {node_id!r} loaded twice with differing payloads"
                )
        for row in _read_jsonl(directory / "edges.jsonl"):
            canon = _canonical(row)
            if canon not in seen_edges:
                seen_edges.add(canon)
                edges.append(row)
    return nodes_by_id, edges


# ---------------------------------------------------------------------------
# Funding legs — Decision 3: direction-exact, evidence-positive
# ---------------------------------------------------------------------------


def _evidence_by_source(edges: list[dict[str, Any]]) -> dict[str, list[str]]:
    """EVIDENCED_BY targets per source node id, carried verbatim (no closure
    requirement — record nodes may live in other bundles)."""
    evidence: dict[str, list[str]] = {}
    for edge in edges:
        if edge["relationship_type"] == "EVIDENCED_BY":
            evidence.setdefault(edge["source_id"], []).append(edge["target_id"])
    return evidence


def extract_funding_in(
    nodes_by_id: dict[str, dict[str, Any]],
    edges: list[dict[str, Any]],
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """Funding-in legs per org over the funding-in inputs.

    990 lane: a Filing reached via FILED_BY_ORG with `gov_grants_amount`
    present AND > 0 (a Filing without positive gov grants is NOT funding-in
    evidence); fields carried verbatim, entries sorted by tax_year ASC.
    USASpending lane: a MoneyFlow with TO_TARGET → an Organization; one
    entry per flow, held in flow-id order (downstream totals sum in this
    order for float determinism). Orgs appear only with ≥1 entry.
    """
    evidence = _evidence_by_source(edges)
    funding: dict[str, dict[str, list[dict[str, Any]]]] = {}

    for edge in edges:
        if edge["relationship_type"] != "FILED_BY_ORG":
            continue
        filing = nodes_by_id.get(edge["source_id"])
        if filing is None or filing["node_type"] != "Filing":
            continue
        props = filing["properties"]
        gov_grants = props.get("gov_grants_amount")
        if gov_grants is None or gov_grants <= 0:
            continue
        entry: dict[str, Any] = {
            "tax_year": props["tax_year"],
            "gov_grants_amount": gov_grants,
        }
        if "gov_revenue_share" in props:
            entry["gov_revenue_share"] = props["gov_revenue_share"]
        if "total_revenue" in props:
            entry["total_revenue"] = props["total_revenue"]
        entry["revenue_scope"] = props["revenue_scope"]
        entry["evidence_record_ids"] = sorted(evidence.get(filing["id"], []))
        funding.setdefault(edge["target_id"], {}).setdefault("form_990", []).append(
            entry
        )

    for edge in edges:
        if edge["relationship_type"] != "TO_TARGET":
            continue
        flow = nodes_by_id.get(edge["source_id"])
        target = nodes_by_id.get(edge["target_id"])
        if flow is None or flow["node_type"] != "MoneyFlow":
            continue
        if target is None or target["node_type"] != "Organization":
            continue
        props = flow["properties"]
        entry = {
            "flow_id": flow["id"],
            "amount": props["amount"],
            "coverage_scope": props["coverage_scope"],
            "evidence_record_ids": sorted(evidence.get(flow["id"], [])),
        }
        funding.setdefault(edge["target_id"], {}).setdefault(
            "usaspending", []
        ).append(entry)

    for legs in funding.values():
        if "form_990" in legs:
            legs["form_990"].sort(key=lambda e: e["tax_year"])
        if "usaspending" in legs:
            legs["usaspending"].sort(key=lambda e: e["flow_id"])
    return funding


# ---------------------------------------------------------------------------
# SAME_AS collection — the ingestors' deterministic key merges, carried
# ---------------------------------------------------------------------------


def collect_same_as_edges(edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """SAME_AS edges from any loaded edges output, basis carried verbatim
    (the deterministic-allowlist gate is the join lane's responsibility)."""
    return [e for e in edges if e["relationship_type"] == "SAME_AS"]
