"""identity_ledger.py — the IdentityAssertion ledger (Open Marin Identity Control A).

The versioned, supersedable record of every cross-source identity decision: a
deterministic key-merge, a human approval, or a human rejection. Layer 2 of the
three-layer identity model (candidate generation → ledger → egress gate): the
resolver only proposes; the ledger DECIDES; the egress gate publishes ONLY a
`deterministic` or `approved` assertion (Predeclared 1, 3, 6 of the goal doc).

Pure module — read/write/supersede helpers over a JSONL file
(`data/identity/assertions.jsonl`, gitignored operator-local). NEVER a graph
node type (ALL_TYPES untouched). NO clock: `decided_at` is operator-supplied
(a deterministic merge uses the sentinel `"deterministic"`), so the same inputs
always produce byte-identical output.

Assertion id is deterministic from (subject_ref, target_ref, basis,
source_snapshot_hash): idempotent across runs when nothing changed, and a ref
change (drift) shifts the snapshot hash → a new id → which is exactly the
supersession signal.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

# The six assertion statuses (Predeclared 1). Only the first two publish.
STATUSES: frozenset[str] = frozenset({
    "deterministic",
    "approved",
    "queued",
    "rejected_current_evidence",
    "rejected_entity_distinct",
    "superseded",
})
PUBLISHING_STATUSES: frozenset[str] = frozenset({"deterministic", "approved"})

# The re-queue triggers (Predeclared 6).
REQUEUE_TRIGGERS: tuple[str, ...] = (
    "one_sided_new_key",
    "hard_key_conflict",
    "dup_target_merge",
    "fingerprint_drift",
    "review_after_elapsed",
)

# Status × trigger re-queue matrix (Predeclared 6, the pinned resolution of the
# r1/r2 contradiction). `rejected_entity_distinct` — the strong "genuinely
# different entities" verdict — reopens ONLY on a hard-key CONFLICT.
_REQUEUE_MATRIX: dict[str, dict[str, bool]] = {
    "approved": {t: True for t in REQUEUE_TRIGGERS},
    "rejected_current_evidence": {t: True for t in REQUEUE_TRIGGERS},
    "rejected_entity_distinct": {
        "one_sided_new_key": False,
        "hard_key_conflict": True,
        "dup_target_merge": False,
        "fingerprint_drift": False,
        "review_after_elapsed": False,
    },
}

# Identity-relevant ref fields a fingerprint covers (id + label + hard keys).
_FINGERPRINT_KEYS = ("id", "display_label", "ein", "uei", "sos_id", "committee_id")


def is_publishing(assertion: dict[str, Any]) -> bool:
    """True iff the assertion's status may power a public join."""
    return assertion["status"] in PUBLISHING_STATUSES


def _sha(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def fingerprint(ref: dict[str, Any]) -> str:
    """Stable, content-sensitive hash of a ref's identity-relevant fields. A
    change to the label or any hard key shifts the fingerprint (drift)."""
    payload = {k: ref.get(k) for k in _FINGERPRINT_KEYS if ref.get(k) is not None}
    return _sha(json.dumps(payload, sort_keys=True))


def source_snapshot_hash(subject: dict[str, Any], target: dict[str, Any]) -> str:
    """Combined snapshot of both refs — the state an assertion was decided
    against. A drift on either side changes it (a re-queue signal)."""
    return _sha(fingerprint(subject) + "|" + fingerprint(target))


def assertion_id(
    subject_ref: str, target_ref: str, basis: str, snapshot_hash: str
) -> str:
    """Deterministic id: idempotent for unchanged inputs; drift/basis change →
    a distinct id (the supersession key)."""
    return "assertion-" + _sha("|".join((subject_ref, target_ref, basis, snapshot_hash)))[:16]


def make_assertion(
    *,
    subject_ref: str,
    target_ref: str,
    status: str,
    basis: str,
    subject: dict[str, Any],
    target: dict[str, Any],
    reviewer: str,
    decided_at: str,
    policy_version: str,
    evidence_refs: list[str] | None = None,
    reviewed_raw_variants: list[str] | None = None,
    legacy_projection: bool = False,
    review_after: str | None = None,
    supersedes: str | None = None,
) -> dict[str, Any]:
    """Build one IdentityAssertion record (Predeclared 1 schema). `decided_at`
    is operator-supplied — NEVER a clock."""
    if status not in STATUSES:
        raise ValueError(f"unknown status {status!r}; must be one of {sorted(STATUSES)}")
    snap = source_snapshot_hash(subject, target)
    return {
        "id": assertion_id(subject_ref, target_ref, basis, snap),
        "subject_ref": subject_ref,
        "target_ref": target_ref,
        "status": status,
        "basis": basis,
        "reviewer": reviewer,
        "decided_at": decided_at,
        "evidence_refs": list(evidence_refs or []),
        "subject_fingerprint": fingerprint(subject),
        "target_fingerprint": fingerprint(target),
        "reviewed_raw_variants": list(reviewed_raw_variants or []),
        "source_snapshot_hash": snap,
        "policy_version": policy_version,
        "legacy_projection": legacy_projection,
        "supersedes": supersedes,
        "superseded_by": None,
        "review_after": review_after,
    }


def supersede(
    old: dict[str, Any],
    *,
    new_status: str,
    basis: str,
    reviewer: str,
    decided_at: str,
    policy_version: str,
    subject: dict[str, Any] | None = None,
    target: dict[str, Any] | None = None,
    evidence_refs: list[str] | None = None,
    reviewed_raw_variants: list[str] | None = None,
) -> dict[str, Any]:
    """Write a new assertion that supersedes `old`, linked via `supersedes`. The
    superseded copy of `old` (status `superseded`, `superseded_by` → new id) is
    stashed on `supersede.last_superseded` for the caller to persist alongside."""
    # Reuse the old refs' identity unless the caller supplies refreshed ones.
    subj = subject or {"id": old["subject_ref"]}
    targ = target or {"id": old["target_ref"]}
    if subject is None:
        # Preserve the old fingerprints when refs aren't refreshed.
        new = make_assertion(
            subject_ref=old["subject_ref"], target_ref=old["target_ref"],
            status=new_status, basis=basis, subject={"id": old["subject_ref"]},
            target={"id": old["target_ref"]}, reviewer=reviewer, decided_at=decided_at,
            policy_version=policy_version, evidence_refs=evidence_refs,
            reviewed_raw_variants=reviewed_raw_variants or old.get("reviewed_raw_variants"),
            legacy_projection=old.get("legacy_projection", False), supersedes=old["id"],
        )
    else:
        new = make_assertion(
            subject_ref=old["subject_ref"], target_ref=old["target_ref"],
            status=new_status, basis=basis, subject=subj, target=targ,
            reviewer=reviewer, decided_at=decided_at, policy_version=policy_version,
            evidence_refs=evidence_refs,
            reviewed_raw_variants=reviewed_raw_variants or old.get("reviewed_raw_variants"),
            legacy_projection=old.get("legacy_projection", False), supersedes=old["id"],
        )
    superseded_old = dict(old)
    superseded_old["status"] = "superseded"
    superseded_old["superseded_by"] = new["id"]
    supersede.last_superseded = superseded_old  # type: ignore[attr-defined]
    return new


def should_requeue(status: str, trigger: str) -> bool:
    """Predeclared-6 matrix lookup. `deterministic`/`queued`/`superseded` are not
    re-queueable decision states; a publishing/rejection status is."""
    if trigger not in REQUEUE_TRIGGERS:
        raise ValueError(f"unknown trigger {trigger!r}; must be one of {list(REQUEUE_TRIGGERS)}")
    if status not in _REQUEUE_MATRIX:
        if status in STATUSES:
            return False  # deterministic/queued/superseded never re-queue
        raise ValueError(f"unknown status {status!r}")
    return _REQUEUE_MATRIX[status][trigger]


def write_assertions(assertions: list[dict[str, Any]], path: Path) -> None:
    """Write assertions to JSONL, sorted by id, sort_keys per row — deterministic."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(assertions, key=lambda a: a["id"])
    path.write_text(
        "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows), encoding="utf-8"
    )


def read_assertions(path: Path) -> list[dict[str, Any]]:
    """Read assertions from JSONL (empty list when the file is absent/empty)."""
    if not path.is_file():
        return []
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
