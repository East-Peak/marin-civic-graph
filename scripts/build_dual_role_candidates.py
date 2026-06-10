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

import argparse
import json
from pathlib import Path
from typing import Any

USASPENDING_COVERAGE_SCOPE = "usaspending_prime_award_total_obligation"

# The v2 envelope. Campaign bundles emit a SUPERSET (extra promotion_state /
# qa_lane / source_* keys) — tolerated by projecting every row down to these
# keys at load, so dedupe and every downstream read see one shape.
_NODE_KEYS = ("id", "node_type", "labels", "display_label", "properties")
_EDGE_KEYS = ("source_id", "target_id", "relationship_type", "properties")


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


def _project(row: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {key: row[key] for key in keys if key in row}


def load_envelope_dirs(
    dirs: list[Path],
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Load + merge envelope dirs into deduped node/edge sets.

    Every row is normalized to the v2 envelope (campaign-superset keys
    dropped). Nodes dedupe by id — identical re-emissions collapse silently
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
        for raw in _read_jsonl(directory / "nodes.jsonl"):
            row = _project(raw, _NODE_KEYS)
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
        for raw in _read_jsonl(directory / "edges.jsonl"):
            row = _project(raw, _EDGE_KEYS)
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
# Influence-out legs — Decision 3: FROM_SOURCE-direction-exact, orgs only
# ---------------------------------------------------------------------------


def extract_influence_out(
    nodes_by_id: dict[str, dict[str, Any]],
    edges: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Influence-out flows per org over the influence-out inputs.

    A campaign MoneyFlow is influence-out evidence for org G only when a
    FROM_SOURCE edge names G as the SOURCE and G is an Organization node
    (a TO_TARGET flow is money TO the org — never influence-out; Person
    contributors and committee sources are out of scope). Amounts are
    carried verbatim (negatives kept); EVIDENCED_BY targets are record ids
    whose Record nodes may live in other bundles — carried as-is, never
    resolved. Entries held per-flow in flow-id order (downstream totals
    sum in this order for float determinism).
    """
    evidence = _evidence_by_source(edges)
    flows: dict[str, list[dict[str, Any]]] = {}
    for edge in edges:
        if edge["relationship_type"] != "FROM_SOURCE":
            continue
        source = nodes_by_id.get(edge["source_id"])
        flow = nodes_by_id.get(edge["target_id"])
        if source is None or source["node_type"] != "Organization":
            continue
        if flow is None or flow["node_type"] != "MoneyFlow":
            continue
        props = flow["properties"]
        flows.setdefault(edge["source_id"], []).append(
            {
                "flow_id": flow["id"],
                "amount": props["amount"],
                "flow_date": props["flow_date"],
                "flow_type": props["flow_type"],
                "evidence_record_ids": sorted(evidence.get(flow["id"], [])),
            }
        )
    for entries in flows.values():
        entries.sort(key=lambda e: e["flow_id"])
    return flows


# ---------------------------------------------------------------------------
# SAME_AS collection — the ingestors' deterministic key merges, carried
# ---------------------------------------------------------------------------


def collect_same_as_edges(edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """SAME_AS edges from any loaded edges output, basis carried verbatim
    (the deterministic-allowlist gate is the join lane's responsibility)."""
    return [e for e in edges if e["relationship_type"] == "SAME_AS"]


# ---------------------------------------------------------------------------
# Join core — lanes A/B/C, Decision 2
# ---------------------------------------------------------------------------

# Lane B allowlist: the ingestors' deterministic key merges. A SAME_AS edge
# with any other (or no) basis must never silently enter this lane.
DETERMINISTIC_SAME_AS_BASES = ("ein_exact", "uei_exact")


def load_approved_resolutions(
    path: Path, known_org_ids: set[str]
) -> list[dict[str, Any]]:
    """Load the operator's approved-only extract of the reviewed queue.

    Every row must carry `status: "approved"` exactly — passing the
    annotated mixed-status review file is an error by design. A row whose
    `subject_ref`/`candidate_ref` is absent from the loaded inputs is a
    stale approval — operator error, never silently skipped. Byte-identical
    duplicate rows dedupe silently (idempotent re-exports).
    """
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in _read_jsonl(Path(path)):
        canon = _canonical(row)
        if canon in seen:
            continue
        seen.add(canon)
        status = row.get("status")
        if status != "approved":
            raise ValueError(
                "approved-resolutions file must be an approved-only extract; "
                f"found status {status!r} for pair "
                f"({row.get('subject_ref')!r}, {row.get('candidate_ref')!r})"
            )
        for field in ("subject_ref", "candidate_ref"):
            ref = row.get(field)
            if ref not in known_org_ids:
                raise ValueError(
                    f"approved resolution {field} {ref!r} is not present in "
                    "the loaded inputs (stale approval)"
                )
        rows.append(row)
    return rows


def build_join_links(
    same_as_edges: list[dict[str, Any]],
    approved_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Join links for lanes B and C, one per connection, both endpoints
    named (lane A — identical id — needs no link). SAME_AS bases must be in
    the deterministic allowlist; approved rows carry their signals and
    confidence through for the audit trail."""
    links: list[dict[str, Any]] = []
    for edge in same_as_edges:
        basis = edge["properties"].get("basis")
        if basis not in DETERMINISTIC_SAME_AS_BASES:
            raise ValueError(
                f"SAME_AS edge {edge['source_id']!r} -> {edge['target_id']!r} "
                f"has basis {basis!r} — not in the deterministic allowlist "
                f"{sorted(DETERMINISTIC_SAME_AS_BASES)}"
            )
        links.append(
            {
                "funding_org_ref": edge["source_id"],
                "influence_org_ref": edge["target_id"],
                "basis": f"same_as:{basis}",
            }
        )
    for row in approved_rows:
        link: dict[str, Any] = {
            "funding_org_ref": row["subject_ref"],
            "influence_org_ref": row["candidate_ref"],
            "basis": "approved_resolution",
        }
        if "signals" in row:
            link["signals"] = row["signals"]
        if "confidence" in row:
            link["confidence"] = row["confidence"]
        links.append(link)
    return links


def build_components(
    funding_org_ids: set[str],
    influence_org_ids: set[str],
    links: list[dict[str, Any]],
) -> list[list[str]]:
    """Connected components over {funding orgs ∪ influence orgs} plus link
    endpoints (a link endpoint joins its component even when it carries no
    leg itself). Deterministic: members sorted, components ordered by first
    member — link order never matters."""
    parent: dict[str, str] = {}

    def find(org: str) -> str:
        parent.setdefault(org, org)
        while parent[org] != org:
            parent[org] = parent[parent[org]]
            org = parent[org]
        return org

    def union(a: str, b: str) -> None:
        root_a, root_b = find(a), find(b)
        if root_a != root_b:
            parent[root_b] = root_a

    for org in funding_org_ids | influence_org_ids:
        find(org)
    for link in links:
        union(link["funding_org_ref"], link["influence_org_ref"])

    members: dict[str, list[str]] = {}
    for org in parent:
        members.setdefault(find(org), []).append(org)
    return sorted(sorted(group) for group in members.values())


# ---------------------------------------------------------------------------
# Table assembly — Decisions 4/5/6
# ---------------------------------------------------------------------------

INFLUENCE_COVERAGE_SCOPE = "netfile_campaign_finance_export"
RANK_BASIS = "influence_out_amount_total"
COVERAGE_NOTE = (
    "Dual-role candidate from broad-coverage sources (USASpending "
    "prime-award obligations; Form 990 aggregate government grants; "
    "NetFile campaign-finance exports). Identity joins are deterministic "
    "or operator-reviewed. Not a confirmed local-dollar claim; "
    "local-spend coverage is milestone M3. Rank orders rows by "
    "campaign-finance dollars only and does not assess severity."
)


def _subject_label(nodes_by_id: dict[str, dict[str, Any]], ref: str) -> str:
    """The org node's display_label; the ref ONLY when the label is missing."""
    node = nodes_by_id.get(ref)
    return (node or {}).get("display_label") or ref


def _candidate_row(
    nodes_by_id: dict[str, dict[str, Any]],
    funding: dict[str, dict[str, list[dict[str, Any]]]],
    influence: dict[str, list[dict[str, Any]]],
    links: list[dict[str, Any]],
    component: list[str],
    dependency_refs: list[dict[str, str]],
) -> dict[str, Any]:
    """One candidate row per Decision 4 — rank assigned by the caller after
    the global sort. Per-lane dollars stay per-lane: 990 grants are annual
    aggregates and USASpending obligations are award-lifetime totals, so
    they are never summed across scopes."""
    members = set(component)
    subject_ref = min(m for m in component if m in influence)

    joined_via = [
        link
        for link in links
        if link["funding_org_ref"] in members or link["influence_org_ref"] in members
    ]
    # Lane A: a member carrying both legs itself joins with no link needed —
    # listed so every join stays auditable.
    joined_via += [
        {"funding_org_ref": m, "influence_org_ref": m, "basis": "id_exact"}
        for m in component
        if m in funding and m in influence
    ]
    joined_via.sort(
        key=lambda l: (l["funding_org_ref"], l["influence_org_ref"], l["basis"])
    )

    form_990: list[dict[str, Any]] = []
    award_flows: list[dict[str, Any]] = []
    for member in component:
        legs = funding.get(member, {})
        form_990.extend(legs.get("form_990", []))
        award_flows.extend(legs.get("usaspending", []))
    form_990.sort(key=lambda e: e["tax_year"])
    award_flows.sort(key=lambda f: f["flow_id"])

    funding_in: dict[str, Any] = {}
    if form_990:
        funding_in["form_990"] = form_990
    if award_flows:
        scopes = {f["coverage_scope"] for f in award_flows}
        if len(scopes) != 1:
            raise ValueError(
                "mixed usaspending coverage scopes in one component: "
                f"{sorted(scopes)}"
            )
        obligation_total = 0.0
        for flow in award_flows:
            obligation_total += flow["amount"]
        funding_in["usaspending"] = {
            "award_count": len(award_flows),
            "obligation_total": round(obligation_total, 2),
            "coverage_scope": scopes.pop(),
            "evidence_record_ids": sorted(
                {rid for f in award_flows for rid in f["evidence_record_ids"]}
            ),
        }

    flows: list[dict[str, Any]] = []
    for member in component:
        flows.extend(influence.get(member, []))
    flows.sort(key=lambda f: f["flow_id"])
    amount_total = 0.0
    for flow in flows:
        amount_total += flow["amount"]
    influence_out = {
        "flow_count": len(flows),
        "amount_total": round(amount_total, 2),
        "first_flow_date": min(f["flow_date"] for f in flows),
        "last_flow_date": max(f["flow_date"] for f in flows),
        "flow_types": sorted({f["flow_type"] for f in flows}),
        "coverage_scope": INFLUENCE_COVERAGE_SCOPE,
        "evidence_record_ids": sorted(
            {rid for f in flows for rid in f["evidence_record_ids"]}
        ),
    }

    evidence_record_ids = sorted(
        {rid for e in form_990 for rid in e["evidence_record_ids"]}
        | {rid for f in award_flows for rid in f["evidence_record_ids"]}
        | set(influence_out["evidence_record_ids"])
    )

    return {
        "subject_ref": subject_ref,
        "subject_label": _subject_label(nodes_by_id, subject_ref),
        "status": "candidate",
        "joined_via": joined_via,
        "funding_in": funding_in,
        "influence_out": influence_out,
        "evidence_record_ids": evidence_record_ids,
        "dependency_refs": dependency_refs,
        "coverage_note": COVERAGE_NOTE,
    }


def assemble_table(
    nodes_by_id: dict[str, dict[str, Any]],
    funding: dict[str, dict[str, list[dict[str, Any]]]],
    influence: dict[str, list[dict[str, Any]]],
    links: list[dict[str, Any]],
    queued_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Assemble the table per Decisions 4/5/6.

    Returns (rows, table_counts): ranked candidate rows (Decision 6 —
    influence_out.amount_total DESC, tie subject_ref ASC, 1-based rank) then
    withheld rows (subject_ref ASC), plus the four pinned coverage buckets,
    each counting components (Decision 5's partition — every org in exactly
    one component, leg-less components count nowhere).

    Withhold grouping (Decision 5): (i) A+B+C components carrying both legs
    → candidate rows; (ii) a queued pair touching a candidate component
    attaches to that row's dependency_refs (to both rows' when it bridges
    two) and creates no withheld row — the outside endpoint stays in its own
    component for the coverage partition; (iii) the orgs outside every
    candidate component regroup over the unconsumed queued pairs plus the
    A/B/C links among them; each regrouped component carrying both legs →
    exactly ONE withheld row.
    """
    funding_orgs = set(funding)
    influence_orgs = set(influence)

    components = build_components(funding_orgs, influence_orgs, links)
    candidate_components = [
        comp
        for comp in components
        if any(m in funding_orgs for m in comp)
        and any(m in influence_orgs for m in comp)
    ]
    component_of = {
        member: idx
        for idx, comp in enumerate(candidate_components)
        for member in comp
    }

    # Queued pairs, projected + deduped (Decision 1 dedupes full rows across
    # sidecar files; the (subject_ref, candidate_ref) pair is what
    # withholding and dependency_refs consume).
    queued_pairs: list[tuple[str, str]] = []
    seen_pairs: set[tuple[str, str]] = set()
    for row in queued_rows:
        pair = (row["subject_ref"], row["candidate_ref"])
        if pair not in seen_pairs:
            seen_pairs.add(pair)
            queued_pairs.append(pair)

    dependencies: dict[int, list[dict[str, str]]] = {}
    unconsumed_pairs: list[tuple[str, str]] = []
    for funding_ref, influence_ref in queued_pairs:
        touched = {
            component_of[ref]
            for ref in (funding_ref, influence_ref)
            if ref in component_of
        }
        if touched:
            for idx in touched:
                dependencies.setdefault(idx, []).append(
                    {"subject_ref": funding_ref, "candidate_ref": influence_ref}
                )
        else:
            unconsumed_pairs.append((funding_ref, influence_ref))

    outside_links = [
        link
        for link in links
        if link["funding_org_ref"] not in component_of
        and link["influence_org_ref"] not in component_of
    ]
    pair_links = [
        {"funding_org_ref": funding_ref, "influence_org_ref": influence_ref}
        for funding_ref, influence_ref in unconsumed_pairs
    ]
    outside_components = build_components(
        funding_orgs - set(component_of),
        influence_orgs - set(component_of),
        outside_links + pair_links,
    )

    counts = {
        "candidate_rows": len(candidate_components),
        "funding_in_only": 0,
        "influence_out_only": 0,
        "withheld_pending_resolution": 0,
    }
    withheld_components: list[list[str]] = []
    for comp in outside_components:
        has_funding = any(m in funding_orgs for m in comp)
        has_influence = any(m in influence_orgs for m in comp)
        if has_funding and has_influence:
            withheld_components.append(comp)
        elif has_funding:
            counts["funding_in_only"] += 1
        elif has_influence:
            counts["influence_out_only"] += 1
        # A leg-less component counts nowhere (Decision 5).
    counts["withheld_pending_resolution"] = len(withheld_components)

    candidate_rows = [
        _candidate_row(
            nodes_by_id,
            funding,
            influence,
            links,
            comp,
            sorted(
                dependencies.get(idx, []),
                key=lambda d: (d["subject_ref"], d["candidate_ref"]),
            ),
        )
        for idx, comp in enumerate(candidate_components)
    ]
    candidate_rows.sort(
        key=lambda r: (-r["influence_out"]["amount_total"], r["subject_ref"])
    )
    for rank, row in enumerate(candidate_rows, start=1):
        row["rank"] = rank
        row["rank_basis"] = RANK_BASIS

    withheld_rows: list[dict[str, Any]] = []
    for comp in withheld_components:
        members = set(comp)
        pairs = sorted(
            (
                {"subject_ref": funding_ref, "candidate_ref": influence_ref}
                for funding_ref, influence_ref in unconsumed_pairs
                if funding_ref in members or influence_ref in members
            ),
            key=lambda d: (d["subject_ref"], d["candidate_ref"]),
        )
        subject_ref = min(m for m in comp if m in influence_orgs)
        withheld_rows.append(
            {
                "subject_ref": subject_ref,
                "subject_label": _subject_label(nodes_by_id, subject_ref),
                "status": "withheld_pending_resolution",
                "dependency_refs": pairs,
                "coverage_note": COVERAGE_NOTE,
            }
        )
    withheld_rows.sort(key=lambda r: r["subject_ref"])

    return candidate_rows + withheld_rows, counts


# ---------------------------------------------------------------------------
# Pipeline + CLI — the operator sequence
# ---------------------------------------------------------------------------

DEFAULT_REVIEW_DIR = Path("data/review")
TABLE_FILENAME = "dual-role-candidates.jsonl"
COVERAGE_FILENAME = "dual-role-coverage.json"


def _merge_nodes_across_classes(
    funding_nodes: dict[str, dict[str, Any]],
    influence_nodes: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """One node map for label lookups. Decision 1's divergence rule holds
    across input classes too: the same id re-emitted with a differing
    payload fails loud, never pick-one."""
    merged = dict(funding_nodes)
    for node_id, node in influence_nodes.items():
        prior = merged.get(node_id)
        if prior is None:
            merged[node_id] = node
        elif _canonical(prior) != _canonical(node):
            raise ValueError(
                f"node id {node_id!r} loaded twice with differing payloads"
            )
    return merged


def load_queued_resolutions(
    paths: list[Path] | tuple[Path, ...],
) -> list[dict[str, Any]]:
    """Queued rows from the resolver review sidecars — withholding and
    coverage input ONLY, never joining. Rows dedupe by full-row equality
    across files (idempotent re-exports); approved rows are consumed via
    the approved-only extract and rejected rows are decided non-identities —
    neither withholds, so both are dropped here."""
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in paths:
        for row in _read_jsonl(Path(path)):
            canon = _canonical(row)
            if canon in seen:
                continue
            seen.add(canon)
            if row.get("status") == "queued":
                rows.append(row)
    return rows


def build_read_model(
    funding_dirs: list[Path],
    influence_dirs: list[Path],
    approved_path: Path | None = None,
    sidecar_paths: list[Path] | tuple[Path, ...] = (),
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The full pipeline over envelope dirs: load and extract legs PER INPUT
    CLASS (a campaign flow TO_TARGETing an org must never register as
    funding-in), join on lanes A/B/C, withhold on queued pairs, and return
    (rows, coverage). Coverage inputs count the deduped loaded evidence;
    the table partition counts components (Decision 7)."""
    funding_nodes, funding_edges = load_envelope_dirs(funding_dirs)
    influence_nodes, influence_edges = load_envelope_dirs(influence_dirs)
    nodes_by_id = _merge_nodes_across_classes(funding_nodes, influence_nodes)
    funding = extract_funding_in(funding_nodes, funding_edges)
    influence = extract_influence_out(influence_nodes, influence_edges)

    same_as_edges: list[dict[str, Any]] = []
    seen: set[str] = set()
    for edge in collect_same_as_edges(funding_edges + influence_edges):
        canon = _canonical(edge)
        if canon not in seen:
            seen.add(canon)
            same_as_edges.append(edge)

    approved_rows = (
        load_approved_resolutions(approved_path, set(nodes_by_id))
        if approved_path is not None
        else []
    )
    queued_rows = load_queued_resolutions(sidecar_paths)
    links = build_join_links(same_as_edges, approved_rows)
    rows, table_counts = assemble_table(
        nodes_by_id, funding, influence, links, queued_rows
    )
    coverage = {
        "inputs": {
            "approved_resolutions": len(approved_rows),
            "funding_in_orgs": len(funding),
            "gov_grant_positive_filings": sum(
                len(legs.get("form_990", [])) for legs in funding.values()
            ),
            "influence_out_flows": sum(
                len(entries) for entries in influence.values()
            ),
            "influence_out_orgs": len(influence),
            "queued_resolutions": len(queued_rows),
            "usaspending_award_flows": sum(
                len(legs.get("usaspending", [])) for legs in funding.values()
            ),
        },
        "table": table_counts,
    }
    return rows, coverage


def write_read_model(
    review_dir: Path,
    rows: list[dict[str, Any]],
    coverage: dict[str, Any],
) -> None:
    """Write the table + coverage summary under the review dir (Decision 7
    serialization: one `sort_keys=True` line per row; coverage pretty-printed
    with a trailing newline — two runs over the same inputs byte-identical)."""
    review_dir = Path(review_dir)
    review_dir.mkdir(parents=True, exist_ok=True)
    (review_dir / TABLE_FILENAME).write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    (review_dir / COVERAGE_FILENAME).write_text(
        json.dumps(coverage, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build the dual-role candidate read model from ingestor envelope "
            "dirs — a JSONL sidecar under the review dir, never the graph "
            "(see the module docstring for the operator sequence)."
        )
    )
    parser.add_argument(
        "--funding-in",
        nargs="+",
        required=True,
        help="Envelope dirs carrying funding-in evidence (990, USASpending).",
    )
    parser.add_argument(
        "--influence-out",
        nargs="+",
        required=True,
        help="Envelope dirs carrying campaign-finance flows.",
    )
    parser.add_argument(
        "--approved-resolutions",
        default=None,
        help=(
            "Approved-only extract of the reviewed resolution queue "
            "(omit to join on the deterministic lanes alone)."
        ),
    )
    parser.add_argument(
        "--resolution-sidecars",
        nargs="*",
        default=[],
        help=(
            "Resolver review sidecars; queued rows withhold would-be rows "
            "(they never join)."
        ),
    )
    parser.add_argument(
        "--review-dir",
        default=str(DEFAULT_REVIEW_DIR),
        help=(
            "Directory for the table + coverage summary "
            f"(default: {DEFAULT_REVIEW_DIR})"
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    rows, coverage = build_read_model(
        funding_dirs=[Path(d) for d in args.funding_in],
        influence_dirs=[Path(d) for d in args.influence_out],
        approved_path=(
            Path(args.approved_resolutions) if args.approved_resolutions else None
        ),
        sidecar_paths=[Path(p) for p in args.resolution_sidecars],
    )
    table = coverage["table"]
    print(
        f"Assembled {table['candidate_rows']} candidate rows, "
        f"{table['withheld_pending_resolution']} withheld pending resolution "
        f"({table['funding_in_only']} funding-in-only, "
        f"{table['influence_out_only']} influence-out-only components)"
    )
    review_dir = Path(args.review_dir)
    print(f"Writing table to: {review_dir / TABLE_FILENAME}")
    print(f"Writing coverage to: {review_dir / COVERAGE_FILENAME}")
    write_read_model(review_dir, rows, coverage)


if __name__ == "__main__":
    main()
