"""Tests for scripts/ingest_usaspending.py — parser unit (M2c, Decisions 1–2).

Fixtures are verbatim USASpending `spending_by_award` API responses
(tests/fixtures/usaspending/, see SOURCES.md). The parser is type-agnostic
over rows from any award-type group; it extracts the predeclared fields,
fails loud on missing identity, and SKIPS (never errors) aggregate rows —
`generated_internal_id` prefix `ASST_AGG_`, published in aggregate precisely
because the underlying recipients are individuals/PII-redacted.

Ethics floor pinned here: the skip log carries the award id + marker ONLY —
never the recipient string (logs and evidence files are artifacts too). The
caplog no-leak test is the negative proof.

Degraded-input variants are produced by deleting fields from REAL fixture
rows (M2b parser precedent) — the two used here are the permitted mutations
(a) UEI-stripped and (b) generated_internal_id-removed; no row is fabricated.
"""
from __future__ import annotations

import copy
import json
import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from ingest_usaspending import (  # noqa: E402
    parse_award_row,
    parse_awards_file,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "usaspending"
GRANTS_P1 = FIXTURES / "spending-by-award-grants-p1.json"
GRANTS_P2 = FIXTURES / "spending-by-award-grants-p2.json"
DIRECT_PAYMENTS = FIXTURES / "spending-by-award-direct-payments-p1.json"


def real_row(path: Path, index: int) -> dict:
    """A REAL fixture row (deep copy so permitted deletions never mutate
    the shared file-backed data)."""
    return copy.deepcopy(json.loads(path.read_text())["results"][index])


# ---------------------------------------------------------------------------
# Field extraction — asserted against real captured values
# ---------------------------------------------------------------------------


def test_parses_real_grant_row_exactly():
    # spending-by-award-grants-p1.json row 0 — COMMUNITY ACTION MARIN.
    award = parse_award_row(real_row(GRANTS_P1, 0))
    assert award == {
        "award_id": "ASST_NON_09CH011669_075",
        "recipient_name": "COMMUNITY ACTION MARIN",
        "recipient_id": "cf3072ee-ffc8-260e-4fc3-57dc5b893427-C",
        "uei": "JZ9FLAVMPEB9",
        "amount": 31949723.2,
        "start_date": "2020-07-01",
        "end_date": "2025-08-31",
        "awarding_agency": "Department of Health and Human Services",
        "awarding_sub_agency": "Administration for Children and Families",
        "funding_agency": "Department of Health and Human Services",
        "funding_sub_agency": "Administration for Children and Families",
        "award_type": "PROJECT GRANT (B)",
        "cfda_number": "93.600",
        "agency_slug": "department-of-health-and-human-services",
    }


def test_null_optional_fields_stay_none():
    # spending-by-award-grants-p2.json row 0 — EAH INC has a real null
    # "End Date"; optional fields pass through as None, never "".
    award = parse_award_row(real_row(GRANTS_P2, 0))
    assert award["award_id"] == "ASST_NON_231CM062378-G_020"
    assert award["start_date"] == "2023-10-04"
    assert award["end_date"] is None
    assert award["uei"] == "LJEEECK1KYZ6"
    assert award["agency_slug"] == "department-of-the-treasury"


def test_parses_full_grant_pages():
    # Both grant pages parse completely — no skips, no errors.
    assert len(parse_awards_file(GRANTS_P1)) == 10
    assert len(parse_awards_file(GRANTS_P2)) == 10


# ---------------------------------------------------------------------------
# Skip rule — real aggregate rows, marker-only logging (ethics floor)
# ---------------------------------------------------------------------------


def test_aggregate_rows_skip_with_marker_only_logging(caplog):
    # All 5 direct-payments rows are real ASST_AGG_ aggregates (individuals,
    # PII-redacted) — skipped with a logged reason, never an error.
    with caplog.at_level(logging.INFO, logger="ingest_usaspending"):
        awards = parse_awards_file(DIRECT_PAYMENTS)
    assert awards == []
    skip_lines = [r.getMessage() for r in caplog.records if "skipping" in r.getMessage()]
    assert len(skip_lines) == 5
    for line in skip_lines:
        assert "ASST_AGG_" in line  # the structural marker
    # Every skipped award id appears in exactly one log line.
    data = json.loads(DIRECT_PAYMENTS.read_text())
    for row in data["results"]:
        assert sum(row["generated_internal_id"] in line for line in skip_lines) == 1


def test_skip_log_never_leaks_recipient_string(caplog):
    # The caplog negative test (Decision 2): the skipped rows' recipient
    # string appears in NO captured log line and NO output artifact.
    with caplog.at_level(logging.DEBUG):
        awards = parse_awards_file(DIRECT_PAYMENTS)
    assert "MULTIPLE RECIPIENTS" not in caplog.text
    assert "MULTIPLE RECIPIENTS" not in repr(awards)


# ---------------------------------------------------------------------------
# Fail-loud identity + permitted degraded variants
# ---------------------------------------------------------------------------


def test_missing_generated_internal_id_fails_loud():
    # Permitted mutation (b): a REAL row with generated_internal_id REMOVED.
    row = real_row(GRANTS_P1, 0)
    del row["generated_internal_id"]
    with pytest.raises(ValueError, match="generated_internal_id"):
        parse_award_row(row)


def test_uei_stripped_row_parses_with_none_uei():
    # Permitted mutation (a): a REAL row with the UEI REMOVED — parses fine,
    # recipient_id preserved (feeds the unit-3 fallback-id case).
    row = real_row(GRANTS_P1, 0)
    row["Recipient UEI"] = None
    award = parse_award_row(row)
    assert award["uei"] is None
    assert award["recipient_id"] == "cf3072ee-ffc8-260e-4fc3-57dc5b893427-C"
