"""Tests for scripts/enrich_fppc_keys.py — Identity Enrichment Lane 3 (FPPC
committee_id). Unit 1: the strict committee_id normalizer + idempotent,
non-clobbering runtime registration into the shared resolver (org_resolution.py
stays byte-identical). Tests snapshot/restore KEY_NORMALIZERS so a lane
registration never leaks across tests.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from org_resolution import KEY_NORMALIZERS  # noqa: E402
from enrich_fppc_keys import (  # noqa: E402
    _normalize_committee_id,
    register_committee_id_normalizer,
)


@pytest.fixture(autouse=True)
def _restore_key_normalizers():
    snapshot = dict(KEY_NORMALIZERS)
    try:
        yield
    finally:
        KEY_NORMALIZERS.clear()
        KEY_NORMALIZERS.update(snapshot)


# --------------------------------------------------------------------------
# _normalize_committee_id — strict numeric FPPC id (Predeclared 1, Codex r1/r2)
# --------------------------------------------------------------------------

def test_normalize_accepts_clean_numeric_ids():
    assert _normalize_committee_id("1352318") == "1352318"
    assert _normalize_committee_id(1419944) == "1419944"          # int
    assert _normalize_committee_id("  1392466  ") == "1392466"    # whitespace stripped
    assert _normalize_committee_id("123456789") == "123456789"    # 9 digits ok (CAL allows <=9)


def test_normalize_rejects_pending_unknown_empty_and_none():
    for bad in ("Pending", "PENDING", "Unknown", "", "   ", None):
        assert _normalize_committee_id(bad) is None


def test_normalize_rejects_overlength_and_alphanumeric_garbage():
    assert _normalize_committee_id("1234567890") is None   # 10 digits — overlength
    assert _normalize_committee_id("abc123") is None       # letters — not a clean id
    assert _normalize_committee_id("C1352318") is None     # SOS-style prefix is not an FPPC id
    assert _normalize_committee_id("1352318.0") is None    # float-ish garbage


# --------------------------------------------------------------------------
# register_committee_id_normalizer — idempotent, non-clobbering (Lane-2 pattern)
# --------------------------------------------------------------------------

def test_register_adds_committee_id_normalizer():
    KEY_NORMALIZERS.pop("committee_id", None)
    register_committee_id_normalizer()
    assert KEY_NORMALIZERS["committee_id"] is _normalize_committee_id


def test_register_is_idempotent():
    register_committee_id_normalizer()
    register_committee_id_normalizer()  # second call must not raise
    assert KEY_NORMALIZERS["committee_id"] is _normalize_committee_id


def test_register_refuses_to_clobber_a_foreign_registration():
    KEY_NORMALIZERS["committee_id"] = lambda v: "foreign"
    with pytest.raises(RuntimeError, match="committee_id"):
        register_committee_id_normalizer()
