"""Tests for scripts/enrich_casos_keys.py — Lane 2 Unit 4: the redaction gate.

The load-bearing new invariant: no street address, ZIP, person name,
registered-agent, or principal is EVER written to a published/egress artifact.
Open Marin's ethic — vulnerable individuals are never modeled; scrutiny up the
power gradient. Proven STRUCTURALLY (forbidden key names + published-keys ⊆
whitelist) AND by VALUE (synthetic sentinels never appear), with a negative test
that the scanner actually catches a planted leak (Codex r2 #4).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from org_resolution import KEY_NORMALIZERS  # noqa: E402
from enrich_casos_keys import (  # noqa: E402
    PUBLISHABLE_FIELDS,
    block_casos_against_existing,
    individual_agent_flags,
    parse_casos_agents,
    publishable_casos_fields,
    scan_for_forbidden,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "identity_enrichment_casos"
FILINGS_SLICE = FIXTURES / "filings_slice.csv"
AGENTS_SLICE = FIXTURES / "agents_slice.csv"
PRINCIPALS_SLICE = FIXTURES / "principals_slice.csv"


@pytest.fixture(autouse=True)
def _restore_key_normalizers():
    snapshot = dict(KEY_NORMALIZERS)
    try:
        yield
    finally:
        KEY_NORMALIZERS.clear()
        KEY_NORMALIZERS.update(snapshot)


POLLUTED_REF = {
    "id": "org-casos-1819837", "display_label": "Ghilotti Construction Company, Inc.",
    "sos_id": "1819837", "entity_class": "organization", "entity_status": "Active",
    "entity_type": "Stock Corporation - CA - General", "formation_date": "04/23/1992",
    "principal_city": "Santa Rosa", "principal_state": "CA",
    # pollution that MUST be dropped on publish:
    "principal_address": "REDACT_ME_STREET", "principal_postal_code": "REDACT_ME_ZIP",
    "agent_name": "REDACT_ME_AGENT_PERSON", "evidence_record_ids": ["record-casos-1819837"],
}


# --------------------------------------------------------------------------
# publishable_casos_fields — the whitelist
# --------------------------------------------------------------------------


def test_publishable_returns_only_the_whitelist():
    out = publishable_casos_fields(POLLUTED_REF)
    assert set(out.keys()) <= set(PUBLISHABLE_FIELDS)
    assert out["sos_id"] == "1819837"
    assert out["principal_city"] == "Santa Rosa"
    # the polluted person/address/ZIP fields are gone
    assert "principal_address" not in out
    assert "agent_name" not in out
    assert not any("REDACT_ME" in str(v) for v in out.values())


# --------------------------------------------------------------------------
# scan_for_forbidden — structural + value, and it MUST catch a real leak
# --------------------------------------------------------------------------


def test_scan_catches_planted_value_and_key_leaks():
    # a forbidden VALUE (sentinel)
    assert scan_for_forbidden({"note": "see REDACT_ME_STREET"})
    # a forbidden KEY name even with a benign value
    assert scan_for_forbidden({"principal_address": "123 Main St"})
    assert scan_for_forbidden({"agent_first_name": "Jane"})
    # nested
    assert scan_for_forbidden({"candidates": [{"mailing_postal_code": "94901"}]})


def test_scan_passes_clean_published_artifact():
    assert scan_for_forbidden(publishable_casos_fields(POLLUTED_REF)) == []


def test_block_candidates_are_redaction_clean():
    existing = [{"id": "org-mpeg", "display_label": "Miller Pacific Engineering Group"}]
    result = block_casos_against_existing(FILINGS_SLICE.read_text().splitlines(), existing)
    assert result["candidates"]
    assert scan_for_forbidden(result["candidates"]) == []


# --------------------------------------------------------------------------
# Agents — individual_agent signal reads ONLY entity_num + AGENT_TYPE
# --------------------------------------------------------------------------


def test_individual_agent_flag_never_reads_person_data():
    rows = list(parse_casos_agents(AGENTS_SLICE.read_text().splitlines()))
    # the parser output carries no person name / address — only num + a bool
    assert scan_for_forbidden(rows) == []
    flags = individual_agent_flags(AGENTS_SLICE.read_text().splitlines())
    assert flags["1819837"] is True   # Individual Agent
    assert flags["1628638"] is False  # corporate 1505 agent


def test_principals_are_never_read_into_any_artifact():
    """The lane never reads Principals.csv into a published artifact — so officer
    sentinels never appear even though the fixture carries them."""
    text = PRINCIPALS_SLICE.read_text()
    assert "REDACT_ME_OFFICER" in text  # the fixture really has them
    # nothing in the published path consumes Principals; an artifact built from the
    # other slices carries no officer sentinel
    existing = [{"id": "org-gcc", "display_label": "Ghilotti Construction Company"}]
    result = block_casos_against_existing(FILINGS_SLICE.read_text().splitlines(), existing)
    assert scan_for_forbidden(result["candidates"], sentinels=("REDACT_ME_OFFICER",)) == []
