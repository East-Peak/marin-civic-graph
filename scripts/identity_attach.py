"""Generic identity attach/candidate helpers for reconciliation lanes.

R3a keeps the public lane functions stable, but moves their shared mechanics
behind registry-driven helpers: approved attach construction and review-candidate
artifact emission.
"""
from __future__ import annotations

from typing import Any, Mapping

from identity_key_registry import IdentityKeyEntry
from identity_ledger import make_assertion
from identity_resolution_adapter import normalize_resolution_candidate_for_artifact


def _path_value(obj: Mapping[str, Any], path: str) -> Any:
    cur: Any = obj
    for part in path.split("."):
        if not isinstance(cur, Mapping):
            return None
        cur = cur.get(part)
        if cur is None:
            return None
    return cur


def _anchor_suffix(entry: IdentityKeyEntry, anchor_id: str) -> str:
    if not anchor_id.startswith(entry.anchor_prefix):
        raise ValueError(
            f"{entry.key_type}/{entry.semantics_scope}: subject_ref {anchor_id!r} "
            f"does not start with {entry.anchor_prefix!r}"
        )
    return anchor_id[len(entry.anchor_prefix):]


def _selector_value(
    selector: str,
    *,
    entry: IdentityKeyEntry,
    candidate: Mapping[str, Any],
    vendor_ref: Mapping[str, Any],
    anchor_id: str,
) -> Any:
    for part in selector.split("|"):
        if part == "anchor_id":
            value = anchor_id
        elif part == "anchor_suffix":
            value = _anchor_suffix(entry, anchor_id)
        elif part.startswith("const:"):
            value = part[len("const:"):]
        elif part.startswith("candidate."):
            value = _path_value(candidate, part[len("candidate."):])
        elif part.startswith("vendor_ref."):
            value = _path_value(vendor_ref, part[len("vendor_ref."):])
        else:
            raise ValueError(f"unknown anchor subject selector {part!r}")
        if value not in (None, ""):
            return value
    return None


def build_anchor_subject(
    entry: IdentityKeyEntry,
    candidate: Mapping[str, Any],
    vendor_ref: Mapping[str, Any],
) -> dict[str, Any]:
    """Project the registry-key anchor subject from the entry's field selectors."""
    anchor_id = candidate["subject_ref"]
    subject: dict[str, Any] = {"id": anchor_id}
    for field, selector in entry.anchor_subject_fields:
        value = _selector_value(
            selector,
            entry=entry,
            candidate=candidate,
            vendor_ref=vendor_ref,
            anchor_id=anchor_id,
        )
        if value is not None:
            subject[field] = value
    return subject


def build_attach(
    entry: IdentityKeyEntry,
    candidate: dict[str, Any],
    vendor_ref: dict[str, Any],
    *,
    reviewer: str,
    decided_at: str,
    policy_version: str,
    policy_hash: str | None = None,
    eligibility_snapshot_hash: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build the approved assertion + SAME_AS edge for a self-identity lane."""
    if entry.relationship_only or entry.key_semantics != "self" or not entry.dedup_eligibility:
        raise ValueError(
            f"{entry.key_type}/{entry.semantics_scope} is not an attachable self-identity key"
        )
    anchor_id = candidate["subject_ref"]
    subject = build_anchor_subject(entry, candidate, vendor_ref)
    target = vendor_ref if vendor_ref.get("id") else {"id": candidate["candidate_ref"]}
    assertion = make_assertion(
        subject_ref=candidate["subject_ref"],
        target_ref=candidate["candidate_ref"],
        status="approved",
        basis=entry.attach_basis,
        subject=subject,
        target=target,
        reviewer=reviewer,
        decided_at=decided_at,
        policy_version=policy_version,
        policy_hash=policy_hash,
        eligibility_snapshot_hash=eligibility_snapshot_hash,
        evidence_refs=list(candidate.get("evidence_record_ids", [])),
    )
    same_as = {
        "source_id": anchor_id,
        "target_id": candidate["candidate_ref"],
        "relationship_type": "SAME_AS",
        "properties": {"basis": entry.attach_basis, "assertion_id": assertion["id"]},
    }
    return assertion, same_as


def emit_candidate(
    entry: IdentityKeyEntry,
    candidate: Mapping[str, Any],
    registry_ref: Mapping[str, Any] | None,
    *,
    registry_evidence_fields: tuple[str, ...],
) -> dict[str, Any]:
    """Normalize one review candidate and attach lane-specific registry evidence."""
    out = normalize_resolution_candidate_for_artifact(dict(candidate))
    if registry_ref is None:
        return out
    for field in registry_evidence_fields:
        value = registry_ref.get(field)
        if value is None:
            continue
        out_field = entry.public_key_field if field == entry.key_type else f"registry_{field}"
        out[out_field] = value
    return out
