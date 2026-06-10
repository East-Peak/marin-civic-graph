"""Tests for scripts/ingest_990.py — parser unit (M2b).

Parses IRS Form 990 e-file XML (real committed fixtures, tests/fixtures/990/)
into typed return dicts per the M2b predeclared decisions: namespace-agnostic
by local name; identity fields scoped to the Filer element of ReturnHeader
(first-match-in-document-order returns the PREPARER firm); TaxYr with a
TaxPeriodEndDt-year fallback; Part VII Section A inclusion flags with former /
highest-comp-only exclusions; non-IRS990 returns skipped with a logged reason.

Degraded-input variants (missing TaxYr / missing EIN) are produced by deleting
one element from the REAL fixture text in-memory — they exercise the fallback
and fail-loud paths; no fixture return is ever fabricated.
"""
from __future__ import annotations

import logging
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from ingest_990 import parse_return_file, parse_return_xml  # noqa: E402

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "990"
MCF_2022 = FIXTURES / "202421369349304932.xml"
MCF_2023 = FIXTURES / "202541349349313719.xml"
MALT_2022 = FIXTURES / "202421309349304522.xml"
SAUSALITO_EZ = FIXTURES / "202530769349201418.xml"


# ---------------------------------------------------------------------------
# Identity — Filer-scoped, namespace-agnostic
# ---------------------------------------------------------------------------


def test_mcf_2022_identity_is_filer_scoped_not_preparer():
    parsed = parse_return_file(MCF_2022)
    assert parsed["ein"] == "943007979"
    # The preparer trap: the first BusinessNameLine1Txt in document order on
    # this return is the preparer firm (ARMANINO LLP), NOT the filer.
    assert parsed["legal_name_raw"] == "MARIN COMMUNITY FOUNDATION"
    assert parsed["legal_name"] == "Marin Community Foundation"
    assert parsed["tax_year"] == "2022"


def test_parsing_is_namespace_agnostic():
    text = MCF_2023.read_text(encoding="utf-8")
    # The real e-file XML carries the IRS default namespace — parsing it at
    # all proves local-name matching; assert the namespace is really there.
    assert 'xmlns="http://www.irs.gov/efile"' in text
    parsed = parse_return_xml(text)
    assert parsed["ein"] == "943007979"
    assert parsed["tax_year"] == "2023"


def test_object_id_derived_from_filename():
    parsed = parse_return_file(MALT_2022)
    assert parsed["object_id"] == "202421309349304522"


def test_nonprofit_status_501c3():
    parsed = parse_return_file(MCF_2022)
    assert parsed["nonprofit_status"] == "501c3"


# ---------------------------------------------------------------------------
# Tax year — TaxYr with TaxPeriodEndDt fallback; identity fails loud
# ---------------------------------------------------------------------------


def test_tax_year_falls_back_to_tax_period_end_year():
    text = MCF_2022.read_text(encoding="utf-8")
    degraded = re.sub(r"<TaxYr>\d{4}</TaxYr>", "", text)
    assert "<TaxYr>" not in degraded
    parsed = parse_return_xml(degraded)
    # TaxPeriodEndDt on this return is 2023-06-30 — fallback year is 2023.
    assert parsed["tax_year"] == "2023"


def test_missing_ein_fails_loud():
    text = MCF_2022.read_text(encoding="utf-8")
    degraded = re.sub(r"<Filer>", "<Filer><!--ein-removed-->", text)
    degraded = re.sub(
        r"(<Filer><!--ein-removed-->\s*)<EIN>\d+</EIN>", r"\1", degraded
    )
    with pytest.raises(ValueError, match="EIN"):
        parse_return_xml(degraded)


def test_missing_tax_year_and_period_fails_loud():
    text = MCF_2022.read_text(encoding="utf-8")
    degraded = re.sub(r"<TaxYr>\d{4}</TaxYr>", "", text)
    degraded = re.sub(r"<TaxPeriodEndDt>[\d-]+</TaxPeriodEndDt>", "", degraded)
    with pytest.raises(ValueError, match="tax year"):
        parse_return_xml(degraded)


# ---------------------------------------------------------------------------
# Return-type gate — only exact IRS990; EZ/PF/N skip with a logged reason
# ---------------------------------------------------------------------------


def test_990ez_return_is_skipped_with_logged_reason(caplog):
    with caplog.at_level(logging.INFO, logger="ingest_990"):
        parsed = parse_return_file(SAUSALITO_EZ)
    assert parsed is None
    assert any("IRS990EZ" in rec.message for rec in caplog.records)
    assert any("skip" in rec.message.lower() for rec in caplog.records)


# ---------------------------------------------------------------------------
# Part VII Section A — exact inclusion flags, exact exclusions
# ---------------------------------------------------------------------------


def test_mcf_2022_officers_exact_inclusion_and_exclusion():
    parsed = parse_return_file(MCF_2022)
    officers = parsed["officers"]
    names_raw = [o["name_raw"] for o in officers]

    # 22 Part VII rows on this return: 2 former-flagged + 5 highest-comp-only
    # are excluded, 15 qualify.
    assert len(officers) == 15

    # Former-flagged rows must never appear (FormerOfcrDirectorTrusteeInd=X).
    assert "THOMAS PETERS" not in names_raw
    assert "ALEXANDRA DERBY" not in names_raw
    # Highest-comp-only rows must never appear.
    assert "SAUL MACIAS" not in names_raw
    assert "VIKKI GARROD" not in names_raw
    # Officer + trustee rows qualify.
    assert "RHEA SUH" in names_raw
    assert "MARK BUELL" in names_raw
    # A trustee whose only "former" signal is title text (no flag) stays in —
    # the flag governs, not the title.
    assert "LAWRENCE BANCROFT" in names_raw

    buell = next(o for o in officers if o["name_raw"] == "MARK BUELL")
    assert buell["name"] == "Mark Buell"
    assert buell["role_raw"] == "BOARD CHAIR"
    assert buell["role"] == "Board Chair"


def test_mcf_2023_officers_count():
    parsed = parse_return_file(MCF_2023)
    # 21 rows: 1 former + 5 highest-comp-only excluded → 15 qualify.
    assert len(parsed["officers"]) == 15
    names_raw = [o["name_raw"] for o in parsed["officers"]]
    assert "MARK BUELL" in names_raw  # recurs from 2022 — drives dedupe tests
    assert "THOMAS PETERS" not in names_raw


def test_malt_2022_officers_count():
    parsed = parse_return_file(MALT_2022)
    # 28 rows: 4 highest-comp-only excluded → 24 qualify (no former rows).
    assert len(parsed["officers"]) == 24
    names_raw = [o["name_raw"] for o in parsed["officers"]]
    assert "TAMARA HICKS" in names_raw
    assert "ERIC RUBENSTAHL" not in names_raw  # highest-comp-only


# ---------------------------------------------------------------------------
# Revenue facts — present when present, omitted when absent
# ---------------------------------------------------------------------------


def test_malt_revenue_and_gov_grants():
    parsed = parse_return_file(MALT_2022)
    assert parsed["total_revenue"] == 7362936
    assert parsed["gov_grants_amount"] == 3150000


def test_mcf_2022_revenue_no_gov_grants_key():
    parsed = parse_return_file(MCF_2022)
    assert parsed["total_revenue"] == 232749407
    assert "gov_grants_amount" not in parsed
