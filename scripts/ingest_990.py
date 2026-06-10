#!/usr/bin/env python3
"""ingest_990.py — IRS Form 990 e-file XML ingestion for Marin Civic Graph.

Parses already-downloaded IRS Form 990 e-file XML into namespaced
Organization (+Nonprofit) nodes with EIN identity, year-scoped Filing facts
(gov grants / total revenue), Record provenance, and Membership nodes for
Part VII officers/directors via the M2a membership_builders. Non-deterministic
org matches are emitted as ResolutionCandidate sidecar JSONL (review queue),
never as graph nodes or edges.

This module has NO fetch code. The operator download procedure:

  1. Discover Marin filers (filer city/ZIP scoping) via the IRS bulk e-file
     index (https://www.irs.gov/charities-non-profits/form-990-series-downloads)
     or ProPublica Nonprofit Explorer org pages (which expose e-file object_ids).
  2. Download each return as XML from the GivingTuesday 990 data lake mirror:
     https://gt990datalake-rawdata.s3.amazonaws.com/EfileData/XmlFiles/<object_id>_public.xml
  3. Place the XML files in data/raw/990/ (or pass --input-dir).

Usage:
  # Parse + build from a local directory (no network, no DB)
  python scripts/ingest_990.py --input-dir data/raw/990

  # Resolve against an export of existing graph orgs — a JSON array of
  # {id, display_label, ein?} dicts. Exact-EIN matches emit SAME_AS edges;
  # everything else lands in the review sidecar. Omit to skip resolution.
  python scripts/ingest_990.py --input-dir data/raw/990 \
      --existing-orgs data/review/existing-orgs.json

  # Also load the emitted nodes/edges into Neo4j (operator step; requires
  # NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD env vars)
  python scripts/ingest_990.py --input-dir data/raw/990 --load

Outputs (override with --output-dir / --review-dir):
  data/normalized/990/nodes.jsonl + edges.jsonl   (gitignored data layer)
  data/review/resolution-candidates-990.jsonl     (sidecar review queue)
"""

from __future__ import annotations

import argparse
import difflib
import json
import logging
import os
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

# M2a builders — imported, never forked (the goal contract; tests assert the
# function identity). Membership ids, envelopes, and edge shapes all come from
# membership_builders so the 990 lane stays in lock-step with Form 700's.
from membership_builders import (
    build_evidenced_by_edge,
    build_member_edge,
    build_member_of_org_edge,
    build_membership_node,
    slugify,
)

logger = logging.getLogger("ingest_990")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT_DIR = ROOT / "data" / "raw" / "990"
OUTPUT_DIR = ROOT / "data" / "normalized" / "990"
REVIEW_DIR = ROOT / "data" / "review"

# ReturnData child local names that are recognized non-990 returns: skip with
# a logged reason (not an error). Anything else without an IRS990 child fails
# loud — it is not a known shape.
SKIP_RETURN_TYPES = ("IRS990EZ", "IRS990PF", "IRS990N")

# Part VII Section A inclusion flags (local names). A row qualifies only when
# it has a PersonNm AND at least one of these is truthy — and is excluded
# outright when FormerOfcrDirectorTrusteeInd is truthy or when its only flag
# is HighestCompensatedEmployeeInd.
OFFICER_INCLUSION_FLAGS = (
    "OfficerInd",
    "IndividualTrusteeOrDirectorInd",
    "IndividualTrusteeInd",  # older-schema trustee variant
    "KeyEmployeeInd",
)
FORMER_FLAG = "FormerOfcrDirectorTrusteeInd"

_TRUTHY = {"x", "true", "1"}


# ---------------------------------------------------------------------------
# Namespace-agnostic XML helpers
# ---------------------------------------------------------------------------


def _local(tag: str) -> str:
    """Local name of a possibly `{namespace}`-qualified tag."""
    return tag.rpartition("}")[2]


def _children_by_local(parent: ET.Element, name: str) -> list[ET.Element]:
    return [child for child in parent if _local(child.tag) == name]


def _find_descendant(parent: ET.Element, *names: str) -> ET.Element | None:
    """First descendant of `parent` whose local name matches any of `names`,
    tried in the given order (so newer-schema names win over older variants).
    """
    for name in names:
        for el in parent.iter():
            if _local(el.tag) == name:
                return el
    return None


def _descendant_text(parent: ET.Element, *names: str) -> str | None:
    el = _find_descendant(parent, *names)
    if el is None or el.text is None:
        return None
    text = el.text.strip()
    return text or None


def _is_truthy(text: str | None) -> bool:
    return text is not None and text.strip().lower() in _TRUTHY


def title_if_allcaps(value: str) -> str:
    """Title-case an ALL-CAPS source string for display; pass through mixed
    case unchanged. Raw strings are always preserved in `*_raw` properties.
    """
    return value.title() if value.isupper() else value


# ---------------------------------------------------------------------------
# Parser — e-file XML → typed return dict
# ---------------------------------------------------------------------------


def _parse_officers(irs990: ET.Element) -> list[dict[str, str]]:
    """Qualifying Part VII Section A rows.

    Include only rows with a PersonNm (institutional-trustee business-name
    rows are skipped) and at least one truthy inclusion flag; exclude any row
    with a truthy former flag and rows whose only flag is
    HighestCompensatedEmployeeInd. The FLAG governs former-ness — title text
    like "(THRU 6/23)" does not exclude.
    """
    officers: list[dict[str, str]] = []
    for grp in irs990.iter():
        if _local(grp.tag) != "Form990PartVIISectionAGrp":
            continue
        name_raw = _descendant_text(grp, "PersonNm")
        if not name_raw:
            continue
        flags = {
            _local(el.tag): el.text for el in grp.iter() if _local(el.tag).endswith("Ind")
        }
        if _is_truthy(flags.get(FORMER_FLAG)):
            continue
        if not any(_is_truthy(flags.get(f)) for f in OFFICER_INCLUSION_FLAGS):
            continue
        role_raw = _descendant_text(grp, "TitleTxt") or ""
        officers.append(
            {
                "name": title_if_allcaps(name_raw),
                "name_raw": name_raw,
                "role": title_if_allcaps(role_raw),
                "role_raw": role_raw,
            }
        )
    return officers


def parse_return_xml(
    xml_text: str,
    *,
    object_id: str | None = None,
    source_url: str | None = None,
) -> dict[str, Any] | None:
    """Parse one IRS e-file return into a typed dict, or skip it.

    Namespace-agnostic by local name (IRS e-file XML carries a default
    namespace and version-varying schemas). Processes a return only when
    ReturnData has a child whose local name is exactly IRS990; the recognized
    non-990 types (990-EZ / 990-PF / 990-N) skip with a logged reason and
    return None. Identity fields (EIN, legal name) are located within the
    Filer element of ReturnHeader — first-match-in-document-order would
    return the PREPARER firm, not the filer. A missing identity field
    (EIN, legal name, tax year) raises ValueError — never silent.
    """
    root = ET.fromstring(xml_text)
    header = next(iter(_children_by_local(root, "ReturnHeader")), None)
    return_data = next(iter(_children_by_local(root, "ReturnData")), None)
    if header is None or return_data is None:
        raise ValueError(f"not an IRS e-file Return document ({object_id or 'inline'})")

    # Return-type gate — exact local-name match on ReturnData's children.
    child_names = {_local(child.tag) for child in return_data}
    if "IRS990" not in child_names:
        for skip_type in SKIP_RETURN_TYPES:
            if skip_type in child_names:
                logger.info(
                    "skipping return %s: ReturnData child is %s, not IRS990",
                    object_id or "<inline>",
                    skip_type,
                )
                return None
        raise ValueError(
            f"ReturnData has no IRS990 child (found {sorted(child_names)})"
        )
    irs990 = _children_by_local(return_data, "IRS990")[0]

    # Identity — Filer-scoped (the preparer trap).
    filer = _find_descendant(header, "Filer")
    if filer is None:
        raise ValueError("ReturnHeader has no Filer element")
    ein_text = _descendant_text(filer, "EIN")
    if not ein_text:
        raise ValueError("Filer EIN not found")
    ein = re.sub(r"\D", "", ein_text)

    name1 = _descendant_text(filer, "BusinessNameLine1Txt", "BusinessNameLine1")
    if not name1:
        raise ValueError("Filer legal name not found")
    name2 = _descendant_text(filer, "BusinessNameLine2Txt", "BusinessNameLine2")
    legal_name_raw = f"{name1} {name2}" if name2 else name1

    tax_year = _descendant_text(header, "TaxYr")
    if not tax_year:
        period_end = _descendant_text(header, "TaxPeriodEndDt")
        if period_end and re.match(r"\d{4}", period_end):
            tax_year = period_end[:4]
    if not tax_year:
        raise ValueError("tax year not found (no TaxYr, no TaxPeriodEndDt)")

    parsed: dict[str, Any] = {
        "ein": ein,
        "legal_name": title_if_allcaps(legal_name_raw),
        "legal_name_raw": legal_name_raw,
        "tax_year": tax_year,
        "officers": _parse_officers(irs990),
    }

    if _is_truthy(_descendant_text(irs990, "Organization501c3Ind")):
        parsed["nonprofit_status"] = "501c3"

    total_revenue = _descendant_text(irs990, "CYTotalRevenueAmt")
    if total_revenue is not None:
        parsed["total_revenue"] = int(total_revenue)

    gov_grants = _descendant_text(irs990, "GovernmentGrantsAmt")
    if gov_grants is not None:
        parsed["gov_grants_amount"] = int(gov_grants)

    if object_id:
        parsed["object_id"] = object_id
    if source_url:
        parsed["source_url"] = source_url

    return parsed


def parse_return_file(path: Path) -> dict[str, Any] | None:
    """Parse one e-file XML file; the object id derives from the filename
    (`<object_id>.xml` or the data lake's `<object_id>_public.xml`).
    """
    object_id = path.stem.removesuffix("_public")
    return parse_return_xml(
        path.read_text(encoding="utf-8"), object_id=object_id
    )


# ---------------------------------------------------------------------------
# Builders — parsed return dicts → graph ontology envelopes
# ---------------------------------------------------------------------------


def _org_id(ein: str) -> str:
    return f"org-990-ein-{ein}"


def _record_id(ein: str, tax_year: str) -> str:
    return f"record-990-{ein}-{tax_year}"


def build_org_node(parsed: dict[str, Any]) -> dict[str, Any]:
    """Organization(+Nonprofit) node. EIN IS the identity — the same filer
    across tax years collapses to one node.
    """
    props: dict[str, Any] = {
        "ein": parsed["ein"],
        "legal_name": parsed["legal_name"],
        "legal_name_raw": parsed["legal_name_raw"],
    }
    if "nonprofit_status" in parsed:
        props["nonprofit_status"] = parsed["nonprofit_status"]
    props["source"] = "irs-990"
    return {
        "id": _org_id(parsed["ein"]),
        "node_type": "Organization",
        "labels": ["Organization", "Nonprofit"],
        "display_label": parsed["legal_name"],
        "properties": props,
    }


def build_990_filing_node(parsed: dict[str, Any]) -> dict[str, Any]:
    """Year-scoped Filing fact for one return — revenue facts live here,
    never flattened onto the Organization.

    `gov_revenue_share` is computed only when both inputs are present and
    revenue > 0. `revenue_scope` accompanies any `gov_grants_amount` (coverage
    honesty): it is an aggregate annual fact, never a confirmed local claim.
    """
    ein, tax_year = parsed["ein"], parsed["tax_year"]
    props: dict[str, Any] = {
        "filing_type": "form_990",
        "ein": ein,
        "tax_year": tax_year,
    }
    total_revenue = parsed.get("total_revenue")
    if total_revenue is not None:
        props["total_revenue"] = total_revenue
    gov_grants = parsed.get("gov_grants_amount")
    if gov_grants is not None:
        props["gov_grants_amount"] = gov_grants
        if total_revenue is not None and total_revenue > 0:
            props["gov_revenue_share"] = round(gov_grants / total_revenue, 4)
        props["revenue_scope"] = "form_990_aggregate_government_grants"
    return {
        "id": f"filing-990-{ein}-{tax_year}",
        "node_type": "Filing",
        "labels": ["Filing"],
        "display_label": f"Form 990 — {parsed['legal_name']} — TY {tax_year}",
        "properties": props,
    }


def build_990_record_node(parsed: dict[str, Any]) -> dict[str, Any]:
    """Record node for the return document itself (provenance target of every
    EVIDENCED_BY edge this ingestor emits). source_url only when explicitly
    known — never derived.
    """
    ein, tax_year = parsed["ein"], parsed["tax_year"]
    props: dict[str, Any] = {"ein": ein, "tax_year": tax_year}
    if parsed.get("source_url"):
        props["source_url"] = parsed["source_url"]
    if parsed.get("object_id"):
        props["object_id"] = parsed["object_id"]
    return {
        "id": _record_id(ein, tax_year),
        "node_type": "Record",
        "labels": ["Record"],
        "display_label": (
            f"IRS Form 990 e-file return — {parsed['legal_name']} — TY {tax_year}"
        ),
        "properties": props,
    }


def build_990_person_node(officer: dict[str, str], ein: str) -> dict[str, Any]:
    """Person node for a qualifying Part VII officer/director.

    EIN-scoped id ON PURPOSE: the same name at two different orgs must never
    auto-merge. Cross-org person identity is deferred to a later
    person-resolution lane (M2d/M4) — M2b ships no person resolver.
    """
    return {
        "id": f"person-990-{ein}-{slugify(officer['name'])}",
        "node_type": "Person",
        "labels": ["Person"],
        "display_label": officer["name"],
        "properties": {
            "name": officer["name"],
            "name_raw": officer["name_raw"],
            "source": "irs-990",
        },
    }


def build_filed_by_org_edge(filing_id: str, org_id: str) -> dict[str, Any]:
    """FILED_BY_ORG edge from a Filing node to the filing Organization — the
    org-filer variant under spec FILED_BY (the FILED_BY_COMMITTEE precedent).
    """
    return {
        "source_id": filing_id,
        "target_id": org_id,
        "relationship_type": "FILED_BY_ORG",
        "properties": {},
    }


def build_memberships(
    parsed_returns: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Person + Membership nodes (and their edges) across parsed returns.

    Multi-year dedupe: when the same membership id recurs across years, keep
    ONE node whose evidence_record_ids is the sorted union across years and
    whose source_basis (and display fields) come from the EARLIEST observed
    year; emit one EVIDENCED_BY edge per distinct record. The result is
    independent of input order.
    """
    persons: dict[str, dict[str, Any]] = {}
    # membership id → {"year", "node", "records", "person_id", "org_id"}
    accumulated: dict[str, dict[str, Any]] = {}

    for parsed in parsed_returns:
        ein, tax_year = parsed["ein"], parsed["tax_year"]
        org_id = _org_id(ein)
        record_id = _record_id(ein, tax_year)
        for officer in parsed["officers"]:
            person_node = build_990_person_node(officer, ein)
            persons.setdefault(person_node["id"], person_node)
            node = build_membership_node(
                person_id=person_node["id"],
                person_name=officer["name"],
                organization_id=org_id,
                organization_name=parsed["legal_name"],
                role=officer["role"],
                confidence=0.95,
                source_basis=f"irs_990_{tax_year}",
                evidence_record_ids=[record_id],
            )
            entry = accumulated.get(node["id"])
            if entry is None:
                accumulated[node["id"]] = {
                    "year": int(tax_year),
                    "node": node,
                    "records": {record_id},
                    "person_id": person_node["id"],
                    "org_id": org_id,
                }
            else:
                entry["records"].add(record_id)
                if int(tax_year) < entry["year"]:
                    entry["year"] = int(tax_year)
                    entry["node"] = node

    nodes: list[dict[str, Any]] = list(persons.values())
    edges: list[dict[str, Any]] = []
    for membership_id in sorted(accumulated):
        entry = accumulated[membership_id]
        node = entry["node"]
        node["properties"]["evidence_record_ids"] = sorted(entry["records"])
        nodes.append(node)
        edges.append(build_member_edge(membership_id, entry["person_id"]))
        edges.append(build_member_of_org_edge(membership_id, entry["org_id"]))
        for record_id in sorted(entry["records"]):
            edges.append(build_evidenced_by_edge(membership_id, record_id))
    return nodes, edges


# ---------------------------------------------------------------------------
# Resolver — deterministic SAME_AS + ResolutionCandidate sidecar (Decision 6)
# ---------------------------------------------------------------------------

# Trailing corporate suffixes stripped during name normalization. Bounded by
# design — this is a tie-breaker for exact-equality after cleanup, not a
# general company-name canonicalizer.
_NAME_SUFFIXES = {"inc", "incorporated", "llc", "corp"}

# Minimum difflib ratio for a name-similarity ResolutionCandidate. Below this
# the pair produces nothing — no edge, no candidate.
_SIMILARITY_THRESHOLD = 0.85


def _normalize_ein(value: Any) -> str | None:
    """Digits only; None when absent or no digits survive."""
    if not value:
        return None
    digits = re.sub(r"\D", "", str(value))
    return digits or None


def _normalize_name(value: str) -> str:
    """Casefold, collapse non-alphanumeric runs to single spaces, and strip
    trailing corporate suffixes (inc/incorporated/llc/corp) repeatedly.
    """
    tokens = re.sub(r"[^0-9a-z]+", " ", value.casefold()).split()
    while tokens and tokens[-1] in _NAME_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def propose_org_resolutions(
    new_orgs: list[dict[str, Any]],
    existing_orgs: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Pure resolver: (SAME_AS edges, ResolutionCandidate dicts).

    Deterministic auto-merge on exact normalized-EIN equality ONLY (both
    sides must carry an EIN) — that pair is a settled join, so nothing is
    queued for it. Everything else is bounded stdlib-only name evidence that
    lands in the JSONL review sidecar, never in the graph: exact
    normalized-name equality (conf 0.9), else difflib ratio ≥ 0.85
    (conf = the 2dp ratio). Name similarity alone NEVER merges.

    `existing_orgs` is injected (`[{id, display_label, ein?}]`) — no graph
    access here; the operator feeds a real export at run time.
    """
    same_as_edges: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []

    for new in new_orgs:
        new_ein = _normalize_ein(new.get("ein"))
        new_name = new["display_label"]
        for existing in existing_orgs:
            existing_ein = _normalize_ein(existing.get("ein"))
            if new_ein and existing_ein and new_ein == existing_ein:
                same_as_edges.append(
                    {
                        "source_id": new["id"],
                        "target_id": existing["id"],
                        "relationship_type": "SAME_AS",
                        "properties": {"basis": "ein_exact"},
                    }
                )
                continue  # settled deterministically — queue nothing

            existing_name = existing["display_label"]
            if _normalize_name(new_name) == _normalize_name(existing_name):
                signals = ["normalized_name_exact"]
                confidence = 0.9
            else:
                ratio = difflib.SequenceMatcher(
                    None, new_name.casefold(), existing_name.casefold()
                ).ratio()
                if ratio < _SIMILARITY_THRESHOLD:
                    continue
                confidence = round(ratio, 2)
                signals = [f"name_similarity:{confidence}"]

            candidates.append(
                {
                    "subject_ref": new["id"],
                    "candidate_ref": existing["id"],
                    "signals": signals,
                    "confidence": confidence,
                    "status": "queued",
                    "evidence_record_ids": list(
                        new.get("evidence_record_ids", [])
                    ),
                }
            )

    return same_as_edges, candidates


# ---------------------------------------------------------------------------
# Pipeline assembly — parse / build / resolve (Decision 7)
# ---------------------------------------------------------------------------


def build_nodes_and_edges(
    parsed_returns: list[dict[str, Any]],
    existing_orgs: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Assemble the full batch: (nodes, edges, resolution_candidates).

    In-batch dedupe: the same EIN across years collapses to ONE org node
    (earliest tax year's, matching the membership source_basis rule); one
    Filing + Record per return; memberships via `build_memberships` (which
    owns the multi-year membership dedupe). Deterministic SAME_AS edges from
    the resolver join the edges output; everything non-deterministic returns
    as candidates for the JSONL review sidecar — never nodes, never edges.

    Ordering is fully deterministic (sorted by EIN + tax year) so repeat runs
    over the same inputs are byte-identical downstream.
    """
    returns = sorted(parsed_returns, key=lambda p: (p["ein"], p["tax_year"]))

    orgs: dict[str, dict[str, Any]] = {}
    org_records: dict[str, set[str]] = {}
    filings: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    for parsed in returns:
        org_id = _org_id(parsed["ein"])
        orgs.setdefault(org_id, build_org_node(parsed))  # earliest year wins
        org_records.setdefault(org_id, set()).add(
            _record_id(parsed["ein"], parsed["tax_year"])
        )

        filing = build_990_filing_node(parsed)
        record = build_990_record_node(parsed)
        filings.append(filing)
        records.append(record)
        edges.append(build_filed_by_org_edge(filing["id"], org_id))
        edges.append(build_evidenced_by_edge(filing["id"], record["id"]))

    membership_nodes, membership_edges = build_memberships(returns)
    edges.extend(membership_edges)

    new_org_refs = [
        {
            "id": org_id,
            "display_label": orgs[org_id]["display_label"],
            "ein": orgs[org_id]["properties"]["ein"],
            "evidence_record_ids": sorted(org_records[org_id]),
        }
        for org_id in sorted(orgs)
    ]
    same_as_edges, candidates = propose_org_resolutions(
        new_org_refs, existing_orgs or []
    )
    edges.extend(same_as_edges)

    nodes = (
        [orgs[org_id] for org_id in sorted(orgs)]
        + filings
        + records
        + membership_nodes
    )
    return nodes, edges, candidates


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def _load_existing_orgs(path: Path) -> list[dict[str, Any]]:
    """Operator-supplied existing-org export: a JSON array of
    `{id, display_label, ein?}` dicts (see the module docstring).
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"existing-orgs file must be a JSON array: {path}")
    return data


# ---------------------------------------------------------------------------
# Neo4j loader — operator step; driver import stays lazy in here
# ---------------------------------------------------------------------------


def _load_into_neo4j(
    nodes: list[dict],
    edges: list[dict],
    uri: str,
    user: str,
    password: str,
    database: str = "neo4j",
    batch_size: int = 500,
) -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from load_neo4j_v2 import load_edges, load_nodes

    try:
        from neo4j import GraphDatabase
    except ImportError:
        print(
            "ERROR: neo4j Python driver not installed. Run: pip install neo4j",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"Connecting to Neo4j: {uri} (database={database})")
    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        driver.verify_connectivity()
        print("  Connection verified.")

        print(f"Loading {len(nodes):,} nodes (batch_size={batch_size}) ...")
        node_counts = load_nodes(driver, nodes, batch_size=batch_size)
        total_nodes = sum(node_counts.values())
        print(f"  {total_nodes:,} nodes written.")
        for ntype, count in sorted(node_counts.items()):
            print(f"    {ntype:30s} {count:6,d}")

        print(f"Loading {len(edges):,} edges (batch_size={batch_size}) ...")
        edge_counts = load_edges(driver, edges, batch_size=batch_size)
        total_edges = sum(edge_counts.values())
        print(f"  {total_edges:,} edges written.")
        for rel, count in sorted(edge_counts.items(), key=lambda x: -x[1]):
            print(f"    {rel:40s} {count:6,d}")
    finally:
        driver.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Ingest already-downloaded IRS Form 990 e-file XML into the "
            "Marin Civic Graph (no fetching — see the module docstring for "
            "the operator download procedure)."
        )
    )
    parser.add_argument(
        "--input-dir",
        default=str(DEFAULT_INPUT_DIR),
        help=f"Directory of downloaded 990 XML files (default: {DEFAULT_INPUT_DIR})",
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
            "JSON array of existing graph orgs ({id, display_label, ein?}) "
            "to resolve against. Omit to skip resolution entirely."
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
    xml_paths = sorted(input_dir.glob("*.xml"))
    if not xml_paths:
        print(f"ERROR: no XML files found in {input_dir}", file=sys.stderr)
        sys.exit(1)

    parsed_returns = []
    for path in xml_paths:
        parsed = parse_return_file(path)
        if parsed is not None:
            parsed_returns.append(parsed)
    print(f"Parsed {len(parsed_returns)} of {len(xml_paths)} returns from {input_dir}")

    existing_orgs = (
        _load_existing_orgs(Path(args.existing_orgs))
        if args.existing_orgs
        else None
    )

    nodes, edges, candidates = build_nodes_and_edges(parsed_returns, existing_orgs)
    counts = {
        ntype: sum(1 for n in nodes if n["node_type"] == ntype)
        for ntype in ("Organization", "Filing", "Record", "Person", "Membership")
    }
    print(
        "  "
        + ", ".join(f"{count} {ntype}" for ntype, count in counts.items())
        + f", {len(edges)} edges, {len(candidates)} resolution candidates"
    )

    output_dir = Path(args.output_dir)
    nodes_path = output_dir / "nodes.jsonl"
    edges_path = output_dir / "edges.jsonl"
    review_path = Path(args.review_dir) / "resolution-candidates-990.jsonl"
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
