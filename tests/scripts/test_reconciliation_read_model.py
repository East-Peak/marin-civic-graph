"""Goal 1 — reconciliation read-model emitter. Grows unit by unit:
Unit 3 (redaction primitives: public_hash + the leak gate) and Unit 6 (the full
versioned ReconciliationCase-envelope emitter).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import reconciliation_read_model as rm  # noqa: E402
from enrich_casos_keys import scan_for_forbidden  # noqa: E402
from identity_ledger import fingerprint  # noqa: E402


# --- Unit 3: redaction boundary primitives --------------------------------

def test_public_hash_deterministic_and_order_independent():
    pf = {"sos_id": "0289793", "display_label": "Example LLC"}
    assert rm.public_hash(pf) == rm.public_hash({"display_label": "Example LLC", "sos_id": "0289793"})
    assert rm.public_hash({"a": 1}) != rm.public_hash({"a": 2})
    assert rm.public_hash(pf).startswith("pub-")  # distinguishable from ledger hashes


def test_public_hash_never_equals_private_ledger_fingerprint():
    # the read model may emit ONLY public_hash(public_fields); a ledger assertion's
    # fingerprint hashes the FULL (possibly-PII) ref and must never appear in output.
    public = {"sos_id": "0289793", "display_label": "Example LLC"}
    addr = "142 " + "Imaginary" + " Rd"  # runtime-built; no committed address literal
    private_ref = {**public, "principal_address": addr, "agent_name": "A. Person"}
    assert rm.public_hash(public) != fingerprint(private_ref)
    assert rm.public_hash(public) != fingerprint(public)  # even same input: prefixed/distinct format


def test_leak_gate_clean_on_public_rows():
    row = {"sos_id": "0289793", "display_label": "Example LLC", "entity_type": "LLC"}
    assert rm.forbidden_violations(row) == []
    assert scan_for_forbidden(row) == []


def test_leak_gate_catches_runtime_sentinel_and_forbidden_key():
    sentinel = "142 " + "Imaginary" + " Rd"  # built at runtime — never committed as a literal
    leaked_value = {"display_label": "ok", "note": f"address {sentinel}"}
    assert scan_for_forbidden(leaked_value, sentinels=(sentinel,))  # value sentinel caught
    assert scan_for_forbidden({"home_address": "x"}, forbidden_keys=("address",))  # key name caught
