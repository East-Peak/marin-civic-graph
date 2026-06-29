"""reconcile_cases.py — the queue read path for the Identity Attach Workbench (Goal A).

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

from reconciliation_read_model import _ACTIONABILITY, ledger_status, load_ledger


def _pair(case: dict[str, Any]) -> tuple[str, str]:
    """(subject_ref, target_ref) for the attach pair — matches build_attach_read_model:
    subject = right_ref (registry anchor), target = left_ref (vendor)."""
    join = case["candidate_joins"][0]
    return join["right_ref"]["local_id"], join["left_ref"]["local_id"]


def overlay_cases(
    read_model_path: str | Path,
    ledger_paths: list[str | Path] = (),
    *,
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
    p.add_argument("--now", default=None)
    a = p.parse_args(argv)
    print(_json.dumps(overlay_cases(a.read_model, a.ledger, now=a.now)))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
