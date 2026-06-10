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
  # Parse + build + resolve from a local directory (no network, no DB)
  python scripts/ingest_990.py --input-dir data/raw/990

  # Also load the emitted nodes/edges into Neo4j (operator step; requires
  # NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD env vars)
  python scripts/ingest_990.py --input-dir data/raw/990 --load

Outputs:
  data/normalized/990/nodes.jsonl + edges.jsonl   (gitignored data layer)
  data/review/resolution-candidates-990.jsonl     (sidecar review queue)
"""

from __future__ import annotations

import logging
import re
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
