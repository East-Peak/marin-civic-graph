"""Reconciliation read-model emitter — the versioned, ledger-aware, redaction-bounded
candidate read model the Tranche-2 workbench UI consumes.

Goal 1 of the civic reconciliation toolkit (Tranche 1; spec §5). Built across two
units: Unit 3 (the redaction boundary primitives below) and Unit 6 (the full
``ReconciliationCase``-envelope emitter that collapses the EIN/sos/committee adapters
+ AI-adjudicator verdicts + the ledger into one contract).

REDACTION BOUNDARY (spec §5.4): the emitter serializes ONLY each adapter's declared
public fields, runs ``scan_for_forbidden`` over the FINAL output, and may emit ONLY
``public_hash(public_fields)`` for any hash — it must NEVER copy a ledger assertion's
``subject_fingerprint`` / ``target_fingerprint`` / ``source_snapshot_hash`` (those
derive from the full, possibly-PII subject/target).
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from enrich_casos_keys import scan_for_forbidden  # consume the shipped recursive leak scan


def public_hash(public_fields: dict[str, Any]) -> str:
    """A stable hash over ONLY the given public fields — the sole hash the read model
    may emit. Order-independent; ``pub-`` prefixed so it can never be mistaken for (or
    collide with) a ledger assertion's private-derived fingerprint/snapshot hash."""
    blob = json.dumps(public_fields, sort_keys=True, separators=(",", ":"), default=str)
    return "pub-" + hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def forbidden_violations(obj: Any) -> list[str]:
    """The read model's leak gate: recursive ``scan_for_forbidden`` over emitted output.
    Returns a list of violations ([] = clean). The emitter asserts this is empty over
    the FINAL serialized rows before writing."""
    return scan_for_forbidden(obj)
