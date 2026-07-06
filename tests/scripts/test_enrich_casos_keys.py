"""Tests for scripts/enrich_casos_keys.py — Lane 2 Unit 1.

The CA Secretary-of-State Filings parser. The teeth:
- `_normalize_sos_id` is FORMAT-AGNOSTIC: 7-digit zero-padded corps, 12-digit
  LLC/LP, AND `B`-prefixed numbers all normalize; a leading `C` (OpenCorporates'
  display form) is stripped; leading zeros are PRESERVED; empty → None.
- `register_sos_id_normalizer()` is an idempotent validating shim that refuses a
  foreign registration — so `org_resolution.py` stays byte-identical and there is
  no import-order hazard.
- `parse_casos_filings` STREAMS (yields per row; never materializes the 3.6 GB
  file) and reads ONLY the entity-level whitelist into refs — never the street
  address / ZIP columns the fixture carries as sentinels.
- byte-identical duplicate ENTITY_NUM rows dedupe; same-number rows disagreeing
  on name/type → `casos_row_conflict`, withheld.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import MappingProxyType

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import enrich_casos_keys  # noqa: E402
from enrich_casos_keys import (  # noqa: E402
    _normalize_sos_id,
    dedupe_casos_refs,
    entity_num_prefix_shape,
    parse_casos_filings,
    register_sos_id_normalizer,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "identity_enrichment_casos"
FILINGS_SLICE = FIXTURES / "filings_slice.csv"


# --------------------------------------------------------------------------
# _normalize_sos_id — format-agnostic (Predeclared 1)
# --------------------------------------------------------------------------


def test_normalize_preserves_leading_zeros_and_digits():
    assert _normalize_sos_id("1819837") == "1819837"
    assert _normalize_sos_id("0257045") == "0257045"  # zeros preserved
    assert _normalize_sos_id("202118310837") == "202118310837"


def test_normalize_strips_leading_c_prefix():
    assert _normalize_sos_id("C0254285") == "0254285"
    assert _normalize_sos_id("c2968448") == "2968448"


def test_normalize_keeps_b_prefixed_numbers():
    assert _normalize_sos_id("B20260076487") == "B20260076487"  # B is part of the number


def test_normalize_strips_whitespace_and_punctuation():
    assert _normalize_sos_id("  1819837  ") == "1819837"
    assert _normalize_sos_id("C123-456") == "123456"


def test_normalize_empty_is_none_never_fabricated():
    assert _normalize_sos_id("") is None
    assert _normalize_sos_id("   ") is None
    assert _normalize_sos_id("C") is None
    assert _normalize_sos_id(None) is None


# --------------------------------------------------------------------------
# register_sos_id_normalizer — idempotent, non-clobbering (Predeclared 1)
# --------------------------------------------------------------------------


def test_register_validates_sos_id_normalizer():
    register_sos_id_normalizer()
    assert enrich_casos_keys.KEY_NORMALIZERS["sos_id"] is _normalize_sos_id


def test_register_is_idempotent():
    register_sos_id_normalizer()
    register_sos_id_normalizer()  # second call must not raise
    assert enrich_casos_keys.KEY_NORMALIZERS["sos_id"] is _normalize_sos_id


def test_register_refuses_foreign_registration(monkeypatch):
    monkeypatch.setattr(
        enrich_casos_keys,
        "KEY_NORMALIZERS",
        MappingProxyType({"sos_id": lambda v: "foreign"}),
    )
    with pytest.raises(Exception):
        register_sos_id_normalizer()


# --------------------------------------------------------------------------
# entity_num_prefix_shape — coverage honesty
# --------------------------------------------------------------------------


def test_prefix_shape():
    assert entity_num_prefix_shape("1819837") == "digits"
    assert entity_num_prefix_shape("202118310837") == "digits"
    assert entity_num_prefix_shape("B20260076487") == "b_prefixed"


# --------------------------------------------------------------------------
# parse_casos_filings — streaming, whitelist-only refs (Predeclared 2)
# --------------------------------------------------------------------------


def test_parse_yields_keyed_refs_with_only_whitelist_fields():
    refs = [ref for ref, skip in parse_casos_filings(FILINGS_SLICE.read_text().splitlines()) if ref]
    by_num = {r["sos_id"]: r for r in refs}

    mb = by_num["1628638"]
    assert mb["id"] == "org-casos-1628638"
    assert mb["entity_class"] == "organization"
    assert mb["display_label"] == "Miller Pacific Engineering Group"
    assert mb["entity_status"] == "Active"
    assert mb["entity_type"] == "Stock Corporation - CA - General"
    assert mb["formation_date"] == "05/03/1991"
    assert mb["principal_city"] == "Novato"
    assert mb["principal_state"] == "CA"
    assert mb["evidence_record_ids"] == ["record-casos-1628638"]
    # the parser NEVER reads the street/ZIP columns into the ref (redaction at source)
    assert not any("REDACT_ME" in str(v) for v in mb.values())
    assert not any(k for k in mb if "address" in k.lower() or "postal" in k.lower() or "zip" in k.lower())


def test_parse_keeps_b_prefixed_and_skips_missing_entity_num():
    results = list(parse_casos_filings(FILINGS_SLICE.read_text().splitlines()))
    refs = [ref for ref, skip in results if ref]
    skips = [skip for ref, skip in results if skip]
    assert any(r["sos_id"] == "B20260076487" for r in refs)
    assert "entity_num_missing" in skips


def test_parse_is_streaming_never_materializes():
    """The parser must consume an iterable lazily — a wrapper whose read()/
    read_text() raise must still parse fine (proves no whole-file load)."""

    class _NoSlurp:
        def __init__(self, text):
            self._lines = text.splitlines()

        def read(self, *a):
            raise AssertionError("parser must not call .read()")

        def read_text(self, *a):
            raise AssertionError("parser must not call .read_text()")

        def __iter__(self):
            return iter(self._lines)

    refs = [ref for ref, skip in parse_casos_filings(_NoSlurp(FILINGS_SLICE.read_text())) if ref]
    assert any(r["sos_id"] == "1819837" for r in refs)


# --------------------------------------------------------------------------
# dedupe_casos_refs — dedupe + casos_row_conflict (Predeclared 2)
# --------------------------------------------------------------------------


def test_dedupe_collapses_byte_identical_and_flags_conflicts():
    refs = [ref for ref, skip in parse_casos_filings(FILINGS_SLICE.read_text().splitlines()) if ref]
    deduped, conflicts = dedupe_casos_refs(refs)
    by_num = {r["sos_id"]: r for r in deduped}

    # the duplicate Ghilotti Construction Company row collapses to one
    assert sum(1 for r in deduped if r["sos_id"] == "1819837") == 1
    # the same-number conflict pair (9990001 ALPHA vs BETA) is withheld
    assert "9990001" not in by_num
    conflict_nums = {c["sos_id"] for c in conflicts}
    assert "9990001" in conflict_nums
    assert all(c["reason"] == "casos_row_conflict" for c in conflicts)
