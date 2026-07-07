"""reconciliation_overlay.py — queue read overlay for the Identity Attach Workbench.

Naming rule: reconciliation_* = domain/read side; reconcile_* = operator write actions.

Overlays the LIVE local ledger status onto the STATIC read-model JSONL so the workbench
queue (needs-review / recommended / rejected / done) reflects decisions made this
session. Pure file I/O — no live DB. NEVER mutates the read-model file (returns fresh
dicts). Attach-only (one join per case); the Neo4j context projection is the interactive
pass, not here.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from identity_confidence import mask_against_ledger
from reconciliation_read_model import _ACTIONABILITY, ledger_status, load_ledger
from reconciliation_refs import anchor_id_of, vendor_id_of


def _pair(case: dict[str, Any]) -> tuple[str, str]:
    """(subject_ref, target_ref) for the attach pair."""
    return anchor_id_of(case), vendor_id_of(case)


def _load_confidence_by_pair(
    confidence_path: str | Path,
    ledger_assertions: list[dict[str, Any]],
) -> dict[tuple[str, str], dict[str, str]]:
    records = [
        json.loads(ln)
        for ln in Path(confidence_path).read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]
    by_pair: dict[tuple[str, str], dict[str, str]] = {}
    for record in mask_against_ledger(records, ledger_assertions):
        pair = (record["subject_ref"], record["target_ref"])
        if pair in by_pair:
            raise ValueError(f"duplicate confidence record for pair {pair!r}")
        by_pair[pair] = {"band": record["band"], "status": record["status"]}
    return by_pair


def overlay_cases(
    read_model_path: str | Path,
    ledger_paths: list[str | Path] = (),
    *,
    confidence_path: str | Path | None = None,
    now: str | None = None,
) -> list[dict[str, Any]]:
    """Read the read-model JSONL and overlay current ledger status + refs (recomputing
    actionability from the overlaid status), defaulting the v2 fields. The source file is
    never modified."""
    rows = [
        json.loads(ln)
        for ln in Path(read_model_path).read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]
    assertions: list[dict[str, Any]] = []
    for p in ledger_paths:
        assertions.extend(load_ledger(p, allow_missing=True))
    confidence_by_pair = (
        _load_confidence_by_pair(confidence_path, assertions)
        if confidence_path is not None
        else {}
    )

    out: list[dict[str, Any]] = []
    for case in rows:
        c = dict(case)  # copy — never mutate the source row/file
        subject_ref, target_ref = _pair(case)
        st = ledger_status(assertions, subject_ref, target_ref, now=now)
        c["current_ledger_status"] = st["status"]
        c["ledger_assertion_refs"] = st["assertion_refs"]
        c["actionability"] = _ACTIONABILITY.get(st["status"], "actionable")
        c.setdefault("review_flags", {})
        c.setdefault("bulk_eligible", False)
        confidence = confidence_by_pair.get((subject_ref, target_ref))
        if confidence is not None:
            c["confidence"] = dict(confidence)
        out.append(c)
    return out


def main(argv: list[str] | None = None) -> int:
    """CLI: emit the overlaid cases as a JSON array to stdout (consumed by the operator
    workbench's /api/reconcile/cases route via subprocess)."""
    import argparse
    import json as _json

    p = argparse.ArgumentParser(description="Overlay live ledger status on the read model.")
    p.add_argument("--read-model", required=True)
    p.add_argument("--ledger", action="append", default=[], help="ledger JSONL (repeatable)")
    p.add_argument("--confidence", default=None, help="identity confidence JSONL projection")
    p.add_argument("--now", default=None)
    a = p.parse_args(argv)
    print(_json.dumps(overlay_cases(a.read_model, a.ledger, confidence_path=a.confidence, now=a.now)))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
