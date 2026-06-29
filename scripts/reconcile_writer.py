"""reconcile_writer.py — the operator-decision writer for the Identity Attach Workbench
(Tranche 2, Goal A). ATTACH-ONLY.

The decide route (interactive pass) shells to this. It is file-locked, atomic, and
idempotent, and persists decisions to the local Identity Control A ledger. A changed
decision SUPERSEDES the prior live one (the new assertion's id is the canonical id the
SAME_AS edge references — id excludes decided_at/status, so a re-submit is a no-op
`existing`, while a changed basis/snapshot is a new id that supersedes). The SAME_AS
node+edge handoff is added in Unit 4. No live DB; pure file I/O.
"""
from __future__ import annotations

import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from identity_ledger import read_assertions
from reconciliation_cases import OperatorAction, validate_action
from reconciliation_read_model import POLICY_VERSION, operator_action_to_ledger


@contextmanager
def _file_lock(lock_path: Path):
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    f = open(lock_path, "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(f, fcntl.LOCK_UN)
        f.close()


def _atomic_write_assertions(assertions: list[dict[str, Any]], path: Path) -> None:
    """Deterministic sorted JSONL written atomically: .bak the current file, write a temp
    (fsync temp + parent dir), then os.replace. No partial file on failure."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(assertions, key=lambda a: a["id"])
    body = "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows)
    if path.exists():
        path.with_suffix(path.suffix + ".bak").write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(body)
            f.flush()
            os.fsync(f.fileno())
        dir_fd = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _live_for_pair(ledger: list[dict[str, Any]], subject_ref: str, target_ref: str) -> list[dict[str, Any]]:
    return [
        a for a in ledger
        if a["subject_ref"] == subject_ref and a["target_ref"] == target_ref
        and a.get("superseded_by") is None
    ]


_REQUIRED_NODE_FIELDS = ("id", "node_type", "display_label")


def _atomic_write_jsonl(items: list[dict[str, Any]], path: Path, key) -> None:
    """Sorted JSONL written atomically (temp + fsync + os.replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(items, key=key)
    body = "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(body)
            f.flush()
            os.fsync(f.fileno())
        dir_fd = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _upsert_jsonl(path: Path, new_items: list[dict[str, Any]], key) -> None:
    """Last-write-wins upsert by ``key`` over the existing JSONL, written atomically."""
    existing = []
    if path.exists():
        existing = [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    merged: dict[Any, dict[str, Any]] = {key(x): x for x in existing}
    for it in new_items:
        merged[key(it)] = it  # last-write-wins → a re-approval refreshes assertion_id
    _atomic_write_jsonl(list(merged.values()), path, key)


def _materialize_handoff(same_as: dict[str, Any], anchor_node: dict[str, Any] | None, attach_dir: Path) -> None:
    """Upsert the key-anchor NODE (load_neo4j_v2 shape) + the SAME_AS EDGE into
    data/review/attach/{nodes,edges}.jsonl so the existing gated run_load can apply both
    (load_neo4j_v2 creates an edge only when BOTH endpoint nodes exist)."""
    if anchor_node is None:
        raise ValueError("approve handoff requires anchor_node (the key-anchor org node)")
    missing = [k for k in _REQUIRED_NODE_FIELDS if k not in anchor_node]
    if missing:
        raise ValueError(f"anchor_node missing load fields {missing}")
    attach_dir = Path(attach_dir)
    _upsert_jsonl(attach_dir / "nodes.jsonl", [anchor_node], key=lambda n: n["id"])
    _upsert_jsonl(
        attach_dir / "edges.jsonl", [same_as],
        key=lambda e: (e["source_id"], e["relationship_type"], e["target_id"]),
    )


def apply_decision(
    action: OperatorAction,
    *,
    candidate: dict[str, Any] | None = None,
    vendor_ref: dict[str, Any] | None = None,
    attach_builder=None,
    subject: dict[str, Any] | None = None,
    target: dict[str, Any] | None = None,
    ledger_path: str | Path,
    attach_dir: str | Path | None = None,
    anchor_node: dict[str, Any] | None = None,
    now: str | None = None,
    policy_version: str = POLICY_VERSION,
) -> dict[str, Any]:
    """Persist one operator decision. ATTACH-ONLY. Returns
    ``{result: created|existing|superseded|unsure, assertion, same_as}``. File-locked +
    atomic. Idempotent (same canonical id → ``existing``, regenerated decided_at ignored);
    a changed decision supersedes the prior live assertion (one live per pair)."""
    if action.case_type == "entity_dedup_merge":
        raise ValueError("reconcile_writer is ATTACH-ONLY; entity_dedup_merge is out of scope (Goal A)")
    validate_action(action.case_type, action.action, action.rejection_kind)

    write = operator_action_to_ledger(
        action, attach_builder=attach_builder, candidate=candidate, vendor_ref=vendor_ref,
        subject=subject, target=target, policy_version=policy_version,
    )
    if write is None:  # unsure → no write
        return {"result": "unsure", "assertion": None, "same_as": None}

    ledger_path = Path(ledger_path)
    lock = ledger_path.parent / (ledger_path.name + ".lock")
    with _file_lock(lock):
        ledger = read_assertions(ledger_path) if ledger_path.exists() else []
        canonical = write["assertion"]
        cid = canonical["id"]
        sref, tref = canonical["subject_ref"], canonical["target_ref"]

        existing = next((a for a in ledger if a["id"] == cid), None)
        if existing is not None and existing.get("superseded_by") is None:
            # live + identical decision → idempotent no-op (decided_at excluded from the id)
            result, persisted, wrote = "existing", existing, False
        else:
            wrote = True
            # Drop any STALE (superseded) row carrying the canonical id — reactivation (e.g.
            # approve → reject → approve) re-adds the canonical assertion as the LIVE one.
            ledger = [a for a in ledger if a["id"] != cid]
            prior_live = _live_for_pair(ledger, sref, tref)  # current live row(s) for the pair (different id)
            superseded_ids = {a["id"] for a in prior_live}
            ledger = [
                ({**a, "status": "superseded", "superseded_by": cid} if a["id"] in superseded_ids else a)
                for a in ledger
            ]
            persisted = {**canonical, "supersedes": (sorted(superseded_ids)[0] if superseded_ids else None)}
            ledger.append(persisted)
            live = _live_for_pair(ledger, sref, tref)
            assert len(live) == 1 and live[0]["id"] == cid, "must leave exactly one live per pair"
            result = "superseded" if superseded_ids else "created"

        if wrote:
            _atomic_write_assertions(ledger, ledger_path)
        # SAME_AS node+edge handoff (approve only; idempotent upsert even on `existing`)
        if write["same_as"] is not None and attach_dir is not None:
            _materialize_handoff(write["same_as"], anchor_node, Path(attach_dir))
        return {"result": result, "assertion": persisted, "same_as": write["same_as"]}
