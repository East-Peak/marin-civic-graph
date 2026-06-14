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
