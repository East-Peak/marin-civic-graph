"""Tests for scripts/ingest_marin_county_contracts.py (M3 leg-1).

The County of Marin "delegated contracts" open-data CSV → funding-IN MoneyFlow
facts (County/department FROM_SOURCE; recipient is raw-name-on-the-fact until an
operator-reviewed resolution draws TO_TARGET — NO recipient node is auto-created,
NEVER a Person node). Money is Decimal, never float. The full staged CSV lives in
data/raw (gitignored, local); committable tests run against a curated fixture
slice, and the exact $141,238,172 tie-out test skipifs when the full CSV is absent.

Codex round-1+2 reviewed this design (8 + 1 findings folded).
"""
from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from ingest_marin_county_contracts import (  # noqa: E402
    parse_contract_rows,
    source_profile,
)

FIXTURE = REPO_ROOT / "tests" / "fixtures" / "marin_county_contracts" / "sample-delegated-contracts.csv"
FULL_CSV = (REPO_ROOT / "data" / "raw" / "marin-county-delegated-contracts"
            / "2026-06-10" / "delegated-contracts.csv")
full_csv = pytest.mark.skipif(not FULL_CSV.is_file(), reason="full staged CSV absent (local-only)")


class TestParseRows:
    def test_parses_fixture_rows_with_decimal_amounts(self):
        rows = parse_contract_rows(FIXTURE)
        assert len(rows) == 9
        by_dpid = {r["data_portal_id"]: r for r in rows}
        assert len(by_dpid) == 9  # raw Data Portal IDs unique
        # amounts are Decimal (or None), never float
        for r in rows:
            assert r["amount"] is None or isinstance(r["amount"], Decimal)
        # the empty-amount row parses to None, not 0
        empty = [r for r in rows if r["vendor_name_raw"] == "Breakfast Club Rally"]
        assert empty and empty[0]["amount"] is None
        # the zero-amount row parses to Decimal(0), distinct from missing
        zero = [r for r in rows if r["amount"] == Decimal("0")]
        assert len(zero) == 1
        # required normalized fields present
        r0 = rows[0]
        assert set(r0) >= {"month_and_year", "contract_number", "review_contract",
                           "department", "vendor_name_raw", "amount", "data_portal_id"}
        # PDF link captured when present, None when blank
        cam_pdf = [r for r in rows if r["vendor_name_raw"] == "COMMUNITY ACTION MARIN"
                   and r["review_contract"]]
        assert cam_pdf and cam_pdf[0]["review_contract"].startswith("http")

    def test_fixture_source_profile(self):
        prof = source_profile(parse_contract_rows(FIXTURE))
        assert prof["row_count"] == 9
        assert prof["distinct_vendor_count"] == 8       # CAM appears twice
        assert prof["distinct_data_portal_ids"] == 9
        assert prof["amount_total"] == Decimal("112059")
        assert prof["amount_present_count"] == 8
        assert prof["amount_missing_count"] == 1
        assert prof["spaced_slash_count"] == 2          # "Person / Org" rows only


class TestFullCsvProfile:
    @full_csv
    def test_full_csv_ties_out_to_source_total(self):
        prof = source_profile(parse_contract_rows(FULL_CSV))
        assert prof["row_count"] == 6898
        assert prof["distinct_data_portal_ids"] == 6898  # raw DPIDs unique
        assert prof["amount_total"] == Decimal("141238172")
        assert prof["amount_missing_count"] == 19


# ---------------------------------------------------------------------------
# Unit 2 — source / MoneyFlow / Record builders + guarded vendor classifier
# ---------------------------------------------------------------------------
from ingest_marin_county_contracts import (  # noqa: E402
    build_flow_edges,
    build_moneyflow_node,
    build_record_node,
    build_source_nodes,
    classify_recipient,
    department_id,
    moneyflow_id,
)

_SEARCHABLE_FIELDS = ("display_label", "search_label", "name", "description")


class TestClassifyRecipient:
    def test_clean_person_slash_org_strips_person_to_provenance(self):
        c = classify_recipient("Lisa Ravina / Good Shepherd Lutheran School")
        assert c["recipient_name_resolved"] == "Good Shepherd Lutheran School"
        assert c["person_side"] == "Lisa Ravina"          # provenance only, never a node
        assert c["recipient_kind_hint"] == "explicit_org_from_split"

    def test_org_slash_org_is_NOT_split(self):
        # "CSW/STUBER-STROEH" has no spaced ' / ' and the right side is org-like;
        # keep the raw name whole (guarded split, Codex major).
        c = classify_recipient("CSW/STUBER-STROEH ENGINEERING GROUP")
        assert c["recipient_name_resolved"] == "CSW/STUBER-STROEH ENGINEERING GROUP"
        assert c["person_side"] is None
        assert c["recipient_kind_hint"] == "org_token_present"  # GROUP token

    def test_org_token_name(self):
        c = classify_recipient("DIMENSION REPORT LLC")
        assert c["recipient_kind_hint"] == "org_token_present"
        assert c["person_side"] is None

    def test_bare_personal_name_is_a_hint_only_never_proof(self):
        c = classify_recipient("ALONSO MATA")
        assert c["recipient_kind_hint"] in {"person_name_pattern", "ambiguous"}
        assert "classification_basis" in c and "heuristic_version" in c
        # The hint is advisory; the raw name is still preserved for resolution.
        assert c["recipient_name_resolved"] == "ALONSO MATA"

    def test_classification_is_graded_not_binary(self):
        hints = {classify_recipient(v)["recipient_kind_hint"] for v in (
            "Lisa Ravina / Good Shepherd Lutheran School",
            "DIMENSION REPORT LLC", "ALONSO MATA", "COMMUNITY ACTION MARIN")}
        assert hints <= {"explicit_org_from_split", "org_token_present",
                         "person_name_pattern", "ambiguous"}


class TestSourceNodes:
    def test_county_and_department_government_nodes(self):
        rows = parse_contract_rows(FIXTURE)
        nodes = build_source_nodes(rows)
        # County root + one node per distinct department, all Organization/Government.
        assert all(n["node_type"] == "Organization" for n in nodes)
        assert all("Government" in n["labels"] for n in nodes)
        county = [n for n in nodes if n["id"] == "org-marincounty"]
        assert len(county) == 1
        depts = [n for n in nodes if n["id"].startswith("org-marincounty-dept-")]
        # fixture has HHS, Cultural Services, Marin County Parks, Free Library
        assert len(depts) >= 4
        # department ids are case-insensitive-stable (CULTURAL vs Cultural collapse)
        assert department_id("HEALTH AND HUMAN SERVICES") == department_id("Health and Human Services")


class TestMoneyFlowAndRecord:
    def test_one_moneyflow_per_row_rowstable_unique_ids(self):
        rows = parse_contract_rows(FIXTURE)
        flows = [build_moneyflow_node(r, classify_recipient(r["vendor_name_raw"])) for r in rows]
        assert len(flows) == 9
        assert len({f["id"] for f in flows}) == 9              # unique
        # row-stable: rebuilding yields the same id
        assert moneyflow_id(rows[0]["data_portal_id"]) == flows[0]["id"]

    def test_moneyflow_carries_decimal_amount_and_coverage_honesty(self):
        rows = parse_contract_rows(FIXTURE)
        cam = next(r for r in rows if r["vendor_name_raw"] == "COMMUNITY ACTION MARIN")
        f = build_moneyflow_node(cam, classify_recipient(cam["vendor_name_raw"]))
        p = f["properties"]
        assert p["amount"] == "10000"                          # Decimal serialized as string
        assert p["coverage_scope"] == "marin_county_delegated_contracts"
        assert p["amount_semantics"] == "delegated_contract_amount"
        assert p["not_full_checkbook"] is True
        assert p["not_invoice_payment"] is True
        assert p["recipient_name_raw"] == "COMMUNITY ACTION MARIN"
        assert p["recipient_kind_hint"] in {"org_token_present", "ambiguous", "person_name_pattern"}
        assert p["department_raw"] == "HEALTH AND HUMAN SERVICES"

    def test_missing_amount_flagged_not_zero(self):
        rows = parse_contract_rows(FIXTURE)
        empty = next(r for r in rows if r["vendor_name_raw"] == "Breakfast Club Rally")
        f = build_moneyflow_node(empty, classify_recipient(empty["vendor_name_raw"]))
        assert f["properties"].get("amount") is None
        assert f["properties"]["amount_missing"] is True

    def test_recipient_name_never_leaks_into_searchable_fields(self):
        # Ethics machine-check (Codex nit): the raw recipient name lives ONLY in
        # recipient_name_raw, never in any indexed/displayed field.
        rows = parse_contract_rows(FIXTURE)
        for r in rows:
            f = build_moneyflow_node(r, classify_recipient(r["vendor_name_raw"]))
            for field in _SEARCHABLE_FIELDS:
                val = f.get(field) or f["properties"].get(field, "")
                assert r["vendor_name_raw"] not in (val or ""), \
                    f"recipient name leaked into {field}"

    def test_record_per_row_with_optional_pdf(self):
        rows = parse_contract_rows(FIXTURE)
        recs = [build_record_node(r) for r in rows]
        assert len({r["id"] for r in recs}) == 9
        cam_pdf = next(build_record_node(r) for r in rows
                       if r["vendor_name_raw"] == "COMMUNITY ACTION MARIN" and r["review_contract"])
        assert cam_pdf["properties"]["review_contract_url"].startswith("http")
        no_pdf = next(build_record_node(r) for r in rows
                      if r["vendor_name_raw"] == "DIMENSION REPORT LLC")
        assert "review_contract_url" not in no_pdf["properties"]


class TestFlowEdges:
    def test_from_source_and_evidenced_by_no_to_target(self):
        rows = parse_contract_rows(FIXTURE)
        cam = next(r for r in rows if r["vendor_name_raw"] == "COMMUNITY ACTION MARIN")
        edges = build_flow_edges(cam)
        rels = {e["relationship_type"] for e in edges}
        assert rels == {"FROM_SOURCE", "EVIDENCED_BY"}        # NO TO_TARGET until approved
        fs = next(e for e in edges if e["relationship_type"] == "FROM_SOURCE")
        assert fs["source_id"] == department_id("HEALTH AND HUMAN SERVICES")
        assert fs["target_id"] == moneyflow_id(cam["data_portal_id"])
        ev = next(e for e in edges if e["relationship_type"] == "EVIDENCED_BY")
        assert ev["source_id"] == moneyflow_id(cam["data_portal_id"])
