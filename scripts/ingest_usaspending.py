"""USASpending prime-award ingestion — funding-IN ledger, leg 2 (M2c).

Parses operator-downloaded USASpending API JSON pages (the
`POST /api/v2/search/spending_by_award/` endpoint) into namespaced
`Organization` recipient/agency nodes, award-level `MoneyFlow` facts,
`Record` provenance, and FROM_SOURCE/TO_TARGET/EVIDENCED_BY edges.
Recipient→existing-org joins reuse the shared resolver
(`org_resolution.propose_org_resolutions`, identity_keys=("ein", "uei")):
deterministic identity-key merges only, everything judged lands in the
`ResolutionCandidate` JSONL sidecar (spec §4.4 — enrichment-only until
recipient resolution is reviewed).

THIS MODULE NEVER FETCHES AND NEVER TOUCHES A DATABASE. The download and
`--load` are operator steps (procedure at the bottom of this docstring).

Scope: PRIME awards only. Sub-awards (`/api/v2/subawards/`) are explicitly
deferred (M2d-prep or M3) — pass-through visibility requires the sub-award
endpoint and is a separate coverage claim.

Ethics floor: recipients are organizations receiving public money (scrutiny
up the power gradient). Aggregate award records (`generated_internal_id`
prefix `ASST_AGG_`) are published in aggregate precisely because the
underlying recipients are individuals/PII-redacted — they are SKIPPED, never
ingested; no Person nodes from this source; skip logs carry the award id +
marker only, never the recipient string.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

# Shared helpers — imported, never forked (M2b/M2a precedent). The I/O trio
# is ingest_990's parse/build/resolve/write plumbing reused verbatim;
# _load_into_neo4j keeps the driver import lazy inside itself.
from ingest_990 import (
    _load_existing_orgs,
    _load_into_neo4j,
    _write_jsonl,
    title_if_allcaps,
)
from membership_builders import slugify
from org_resolution import propose_org_resolutions

logger = logging.getLogger("ingest_usaspending")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_DIR = ROOT / "data" / "raw" / "usaspending"
OUTPUT_DIR = ROOT / "data" / "normalized" / "usaspending"
REVIEW_DIR = ROOT / "data" / "review"

# Aggregate award records: county-level rollups whose underlying recipients
# are individuals (PII-redacted) — the structural skip marker (Decision 2).
AGGREGATE_PREFIX = "ASST_AGG_"

# Rows with no recipient identity at all cannot anchor an Organization node.
# On real data this coincides with the ASST_AGG_ rows.
NO_IDENTITY_MARKER = "no_recipient_identity"


# ---------------------------------------------------------------------------
# Parser — API response pages → award dicts (Decisions 1–2)
# ---------------------------------------------------------------------------


def parse_award_row(row: dict[str, Any]) -> dict[str, Any] | None:
    """One API result row → a parsed award dict, or None for a logged skip.

    Identity is `generated_internal_id` — fails loud when absent. Skips
    (never errors): aggregate rows (`ASST_AGG_` prefix) and rows with
    neither UEI nor `recipient_id`. The skip log carries the award id and
    the marker(s) ONLY — never the recipient string (ethics floor: logs
    and evidence files are artifacts too).
    """
    award_id = row.get("generated_internal_id")
    if not award_id:
        raise ValueError(
            "award row missing generated_internal_id — cannot anchor "
            "identity; refusing to guess"
        )

    markers = []
    if award_id.startswith(AGGREGATE_PREFIX):
        markers.append(AGGREGATE_PREFIX)
    if not row.get("Recipient UEI") and not row.get("recipient_id"):
        markers.append(NO_IDENTITY_MARKER)
    if markers:
        logger.info("skipping award %s: %s", award_id, "+".join(markers))
        return None

    return {
        "award_id": award_id,
        "recipient_name": row.get("Recipient Name"),
        "recipient_id": row.get("recipient_id"),
        "uei": row.get("Recipient UEI"),
        "amount": row.get("Award Amount"),
        "start_date": row.get("Start Date"),
        "end_date": row.get("End Date"),
        "awarding_agency": row.get("Awarding Agency"),
        "awarding_sub_agency": row.get("Awarding Sub Agency"),
        "funding_agency": row.get("Funding Agency"),
        "funding_sub_agency": row.get("Funding Sub Agency"),
        "award_type": row.get("Award Type"),
        "cfda_number": row.get("CFDA Number"),
        "agency_slug": row.get("agency_slug"),
    }


def parse_awards_page(data: dict[str, Any]) -> list[dict[str, Any]]:
    """One loaded API response body → parsed award dicts (skips dropped)."""
    awards = []
    for row in data.get("results", []):
        award = parse_award_row(row)
        if award is not None:
            awards.append(award)
    return awards


def parse_awards_file(path: Path) -> list[dict[str, Any]]:
    """One downloaded response page on disk → parsed award dicts."""
    return parse_awards_page(json.loads(Path(path).read_text()))


# ---------------------------------------------------------------------------
# In-batch award dedupe (Decision 3)
# ---------------------------------------------------------------------------


def dedupe_awards(awards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse repeated award ids to one row (first occurrence kept) —
    fails loud when duplicates DISAGREE on amount. Real pagination never
    repeats an award id; this guards operator re-downloads of the same page.
    """
    seen: dict[str, dict[str, Any]] = {}
    deduped: list[dict[str, Any]] = []
    for award in awards:
        award_id = award["award_id"]
        prior = seen.get(award_id)
        if prior is None:
            seen[award_id] = award
            deduped.append(award)
        elif prior["amount"] != award["amount"]:
            raise ValueError(
                f"duplicate award {award_id} disagrees on amount: "
                f"{prior['amount']} != {award['amount']}"
            )
    return deduped


# ---------------------------------------------------------------------------
# Builders — recipient/agency orgs, MoneyFlow, Record (Decisions 3–4)
# ---------------------------------------------------------------------------


def build_recipient_org_nodes(
    awards: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Recipient Organization nodes + an award_id → org id map.

    TWO-PASS identity (Decision 3): pass 1 groups rows by `recipient_id`
    (a UEI-only row anchors its own group); pass 2 assigns the whole group
    `org-usasp-uei-<UEI>` when ANY row carries a UEI, else
    `org-usasp-rid-<recipient_id lowercased>` — a row-local choice would
    split one recipient across two ids when UEI coverage is patchy.

    NO `Nonprofit` label from this source, ever: business categories are
    null on every real row; nonprofit-ness arrives only via reviewed
    cross-source 990 resolution.
    """
    # Pass 1 — group by recipient_id (UEI anchors the no-recipient_id case;
    # the parser already skipped rows with neither).
    groups: dict[str, list[dict[str, Any]]] = {}
    for award in awards:
        group_key = award["recipient_id"] or f"uei:{award['uei']}"
        groups.setdefault(group_key, []).append(award)

    nodes: list[dict[str, Any]] = []
    org_id_by_award: dict[str, str] = {}
    for group_rows in groups.values():
        ueis = {row["uei"] for row in group_rows if row["uei"]}
        if len(ueis) > 1:
            # Defensive — contradicts the recipient_id grouping contract;
            # not constructible from real rows under the fixture rules.
            raise ValueError(
                f"recipient group {group_rows[0]['recipient_id']!r} carries "
                f"multiple distinct UEIs: {sorted(ueis)}"
            )
        first = group_rows[0]
        if ueis:
            org_id = f"org-usasp-uei-{next(iter(ueis))}"
        else:
            org_id = f"org-usasp-rid-{first['recipient_id'].lower()}"

        name_raw = first["recipient_name"]
        props: dict[str, Any] = {
            "name": title_if_allcaps(name_raw),
            "name_raw": name_raw,
        }
        if ueis:
            props["uei"] = next(iter(ueis))
        if first["recipient_id"]:
            props["recipient_id"] = first["recipient_id"]
        props["source"] = "usaspending"

        nodes.append(
            {
                "id": org_id,
                "node_type": "Organization",
                "labels": ["Organization"],
                "display_label": title_if_allcaps(name_raw),
                "properties": props,
            }
        )
        for row in group_rows:
            org_id_by_award[row["award_id"]] = org_id

    return nodes, org_id_by_award


def build_agency_org_nodes(
    awards: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Awarding-agency Organization nodes (deduped on slug) + award map.

    Id base is the API's `agency_slug` (stable, already id-safe); a missing
    slug falls back to the slugified awarding-agency name; neither → loud.
    """
    nodes: list[dict[str, Any]] = []
    by_slug: dict[str, str] = {}
    org_id_by_award: dict[str, str] = {}
    for award in awards:
        slug = award["agency_slug"]
        if not slug and award["awarding_agency"]:
            slug = slugify(award["awarding_agency"])
        if not slug:
            raise ValueError(
                f"award {award['award_id']} has neither agency_slug nor an "
                "awarding agency name"
            )
        org_id = f"org-usasp-agency-{slug}"
        if slug not in by_slug:
            by_slug[slug] = org_id
            nodes.append(
                {
                    "id": org_id,
                    "node_type": "Organization",
                    "labels": ["Organization"],
                    "display_label": award["awarding_agency"],
                    "properties": {
                        "name": award["awarding_agency"],
                        "agency_slug": slug,
                        "source": "usaspending",
                    },
                }
            )
        org_id_by_award[award["award_id"]] = org_id
    return nodes, org_id_by_award


def _moneyflow_id(award_id: str) -> str:
    return f"moneyflow-usasp-{award_id.lower()}"


def _record_id(award_id: str) -> str:
    return f"record-usasp-{award_id.lower()}"


def build_moneyflow_node(award: dict[str, Any]) -> dict[str, Any]:
    """Award-level MoneyFlow fact (funding-IN ledger entry).

    `coverage_scope` is the coverage-honesty marker: the amount is the
    award-LIFETIME total obligation from the prime-award search endpoint —
    never a confirmed annual or local-dollar claim. Funding agency fields
    are stored whenever present (the appropriation source); the FROM_SOURCE
    edge endpoint is always the awarding agency (Decision 5).
    """
    props: dict[str, Any] = {
        "amount": award["amount"],
        "flow_type": "federal_award",
        "award_category": award["award_type"],
        "award_id": award["award_id"],
    }
    for key in (
        "start_date",
        "end_date",
    ):
        if award[key]:
            props[key] = award[key]
    if award["cfda_number"]:
        props["assistance_listing"] = award["cfda_number"]
    props["awarding_agency"] = award["awarding_agency"]
    for key in ("awarding_sub_agency", "funding_agency", "funding_sub_agency"):
        if award[key]:
            props[key] = award[key]
    props["coverage_scope"] = "usaspending_prime_award_total_obligation"
    props["source"] = "usaspending"
    return {
        "id": _moneyflow_id(award["award_id"]),
        "node_type": "MoneyFlow",
        "labels": ["MoneyFlow"],
        "display_label": f"federal_award ${award['amount']:.2f}",
        "properties": props,
    }


def build_award_record_node(award: dict[str, Any]) -> dict[str, Any]:
    """Record node for the award's USASpending profile page (provenance
    target of the EVIDENCED_BY edge). The URL embeds the verbatim-case
    generated_internal_id — it is case-sensitive.
    """
    award_id = award["award_id"]
    return {
        "id": _record_id(award_id),
        "node_type": "Record",
        "labels": ["Record"],
        "display_label": f"USASpending award {award_id}",
        "properties": {
            "award_id": award_id,
            "source_url": f"https://www.usaspending.gov/award/{award_id}",
        },
    }


def build_award_edges(
    award: dict[str, Any], recipient_org_id: str, agency_org_id: str
) -> list[dict[str, Any]]:
    """The three award edges (CF MoneyFlow direction precedent): awarding
    agency —FROM_SOURCE→ MoneyFlow —TO_TARGET→ recipient; MoneyFlow
    —EVIDENCED_BY→ Record.
    """
    moneyflow_id = _moneyflow_id(award["award_id"])
    return [
        {
            "source_id": agency_org_id,
            "target_id": moneyflow_id,
            "relationship_type": "FROM_SOURCE",
            "properties": {},
        },
        {
            "source_id": moneyflow_id,
            "target_id": recipient_org_id,
            "relationship_type": "TO_TARGET",
            "properties": {},
        },
        {
            "source_id": moneyflow_id,
            "target_id": _record_id(award["award_id"]),
            "relationship_type": "EVIDENCED_BY",
            "properties": {},
        },
    ]


# ---------------------------------------------------------------------------
# Resolver wiring — recipient refs → shared resolver (Decision 6)
# ---------------------------------------------------------------------------


def build_recipient_refs(
    recipient_nodes: list[dict[str, Any]],
    org_id_by_award: dict[str, str],
) -> list[dict[str, Any]]:
    """Resolver refs for the recipient orgs, sorted by org id:
    `{id, display_label, uei?, evidence_record_ids[]}` — the uei key is
    OMITTED (never None-filled) when the recipient group carried none, and
    evidence_record_ids are the sorted Record ids of every award the org
    received in this batch.
    """
    records_by_org: dict[str, set[str]] = {}
    for award_id, org_id in org_id_by_award.items():
        records_by_org.setdefault(org_id, set()).add(_record_id(award_id))

    refs: list[dict[str, Any]] = []
    for node in sorted(recipient_nodes, key=lambda n: n["id"]):
        ref: dict[str, Any] = {
            "id": node["id"],
            "display_label": node["display_label"],
        }
        uei = node["properties"].get("uei")
        if uei:
            ref["uei"] = uei
        ref["evidence_record_ids"] = sorted(records_by_org[node["id"]])
        refs.append(ref)
    return refs


def resolve_recipient_orgs(
    recipient_nodes: list[dict[str, Any]],
    org_id_by_award: dict[str, str],
    existing_orgs: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Recipient refs → the SHARED resolver with identity_keys=("ein","uei"):
    (SAME_AS edges, ResolutionCandidate dicts).

    A USASpending ref carries no EIN, so uei-exact is the only deterministic
    lane into the existing graph; today's real export carries neither key,
    so in practice this emits ZERO SAME_AS (spec §4.4 — enrichment-only
    until recipient resolution is reviewed). Candidates are sidecar JSONL
    material only — never nodes, never edges.
    """
    refs = build_recipient_refs(recipient_nodes, org_id_by_award)
    return propose_org_resolutions(
        refs, existing_orgs, identity_keys=("ein", "uei")
    )


# ---------------------------------------------------------------------------
# Pipeline assembly — parse / build / resolve (Decision 7)
# ---------------------------------------------------------------------------


def build_nodes_and_edges(
    awards: list[dict[str, Any]],
    existing_orgs: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Assemble the full batch: (nodes, edges, resolution_candidates).

    Dedupe first (repeated award ids collapse; disagreement fails loud),
    then sort by award id so repeat runs over the same inputs are
    byte-identical downstream — no timestamps anywhere. Deterministic
    SAME_AS edges from the resolver join the edges output; everything
    judged returns as candidates for the JSONL review sidecar — never
    nodes, never edges.
    """
    awards = sorted(dedupe_awards(awards), key=lambda a: a["award_id"])

    recipient_nodes, recipient_by_award = build_recipient_org_nodes(awards)
    agency_nodes, agency_by_award = build_agency_org_nodes(awards)

    nodes = sorted(recipient_nodes, key=lambda n: n["id"]) + sorted(
        agency_nodes, key=lambda n: n["id"]
    )
    edges: list[dict[str, Any]] = []
    for award in awards:
        nodes.append(build_moneyflow_node(award))
        nodes.append(build_award_record_node(award))
        edges.extend(
            build_award_edges(
                award,
                recipient_by_award[award["award_id"]],
                agency_by_award[award["award_id"]],
            )
        )

    same_as_edges, candidates = resolve_recipient_orgs(
        recipient_nodes, recipient_by_award, existing_orgs or []
    )
    edges.extend(same_as_edges)
    return nodes, edges, candidates


# ---------------------------------------------------------------------------
# CLI — mirrors ingest_990 (no fetching; --load is the operator step)
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Ingest already-downloaded USASpending prime-award JSON pages "
            "into the Marin Civic Graph (no fetching — see the module "
            "docstring for the operator download procedure)."
        )
    )
    parser.add_argument(
        "--input-dir",
        default=str(DEFAULT_INPUT_DIR),
        help=(
            "Directory of downloaded spending_by_award response pages "
            f"(default: {DEFAULT_INPUT_DIR})"
        ),
    )
    parser.add_argument(
        "--output-dir",
        default=str(OUTPUT_DIR),
        help=f"Directory to write nodes.jsonl / edges.jsonl (default: {OUTPUT_DIR})",
    )
    parser.add_argument(
        "--review-dir",
        default=str(REVIEW_DIR),
        help=f"Directory for the resolution-candidates sidecar (default: {REVIEW_DIR})",
    )
    parser.add_argument(
        "--existing-orgs",
        default=None,
        help=(
            "JSON array of existing graph orgs ({id, display_label, ein?, "
            "uei?}) to resolve against. Omit to skip resolution entirely."
        ),
    )
    parser.add_argument(
        "--load",
        action="store_true",
        help="Load nodes and edges into Neo4j after writing (operator step).",
    )
    parser.add_argument("--uri", default=os.getenv("NEO4J_URI", "bolt://localhost:7687"))
    parser.add_argument("--user", default=os.getenv("NEO4J_USER", "neo4j"))
    parser.add_argument("--password", default=os.getenv("NEO4J_PASSWORD"))
    parser.add_argument("--database", default=os.getenv("NEO4J_DATABASE", "neo4j"))
    parser.add_argument("--batch-size", type=int, default=500)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)

    input_dir = Path(args.input_dir)
    json_paths = sorted(input_dir.glob("*.json"))
    if not json_paths:
        print(f"ERROR: no JSON files found in {input_dir}", file=sys.stderr)
        sys.exit(1)

    awards: list[dict[str, Any]] = []
    for path in json_paths:
        awards.extend(parse_awards_file(path))
    print(f"Parsed {len(awards)} awards from {len(json_paths)} pages in {input_dir}")

    existing_orgs = (
        _load_existing_orgs(Path(args.existing_orgs))
        if args.existing_orgs
        else None
    )

    nodes, edges, candidates = build_nodes_and_edges(awards, existing_orgs)
    counts = {
        ntype: sum(1 for n in nodes if n["node_type"] == ntype)
        for ntype in ("Organization", "MoneyFlow", "Record")
    }
    print(
        "  "
        + ", ".join(f"{count} {ntype}" for ntype, count in counts.items())
        + f", {len(edges)} edges, {len(candidates)} resolution candidates"
    )

    output_dir = Path(args.output_dir)
    nodes_path = output_dir / "nodes.jsonl"
    edges_path = output_dir / "edges.jsonl"
    review_path = Path(args.review_dir) / "resolution-candidates-usaspending.jsonl"
    print(f"Writing nodes to: {nodes_path}")
    _write_jsonl(nodes_path, nodes)
    print(f"Writing edges to: {edges_path}")
    _write_jsonl(edges_path, edges)
    print(f"Writing resolution candidates to: {review_path}")
    _write_jsonl(review_path, candidates)

    if args.load:
        if not args.password:
            print(
                "ERROR: NEO4J_PASSWORD is required (--password or NEO4J_PASSWORD env var).",
                file=sys.stderr,
            )
            sys.exit(1)
        _load_into_neo4j(
            nodes=nodes,
            edges=edges,
            uri=args.uri,
            user=args.user,
            password=args.password,
            database=args.database,
            batch_size=args.batch_size,
        )


if __name__ == "__main__":
    main()
