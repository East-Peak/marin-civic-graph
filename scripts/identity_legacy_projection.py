"""identity_legacy_projection.py — project shipped flat approved-files into the ledger (A, Unit 2).

The M2d / County / M4 approved-resolutions files are a proto-ledger: flat
`{subject_ref, candidate_ref, status:"approved"}` with NO audit fields. This
adapter promotes each row to a real `IdentityAssertion` WITHOUT becoming an
audit bypass (Predeclared 2):

- fingerprints are DERIVED from the refs emitted THIS run — a ref absent from
  `refs_by_id` is stale and BLOCKS (never an assertion against a vanished node);
- audit fields are explicit: the caller supplies `legacy_reviewer` /
  `legacy_decided_at`, else the named sentinels `"unknown_legacy"` /
  `"legacy_unknown"` — never an invented reviewer, never a clock;
- a multi-raw-variant legacy COUNTY approval BLOCKS: the current recipient group
  can derive its raw variants but not which the operator actually REVIEWED, so
  back-filling them would recreate the blind group fan-out. It projects only
  when the group is single-variant or the row carries explicit
  `reviewed_raw_variants`.

`loader` ∈ {"m2d", "county", "m4"}. Every projected assertion carries
`legacy_projection: true` and `basis: operator_approved_name` (legacy human
approvals were name-based).
"""
from __future__ import annotations

from typing import Any

from identity_ledger import make_assertion

_LOADERS = {"m2d", "county", "m4"}


def project_legacy_approved_row(
    row: dict[str, Any],
    *,
    loader: str,
    refs_by_id: dict[str, dict[str, Any]],
    legacy_reviewer: str | None,
    legacy_decided_at: str | None,
    policy_version: str,
) -> dict[str, Any]:
    """Project one flat approved row → an `approved` ledger assertion, or raise
    (BLOCK) when it cannot be promoted without inventing audit state."""
    if loader not in _LOADERS:
        raise ValueError(f"unknown loader {loader!r}; must be one of {sorted(_LOADERS)}")
    if row.get("status") != "approved":
        raise ValueError(
            f"legacy projection: status is {row.get('status')!r}, expected 'approved'"
        )

    subject_ref = row.get("subject_ref")
    target_ref = row.get("candidate_ref")
    if subject_ref not in refs_by_id:
        raise ValueError(
            f"legacy projection: subject_ref {subject_ref!r} is not a ref emitted "
            f"this run (stale) — BLOCK, re-approve against current state"
        )
    if target_ref not in refs_by_id:
        raise ValueError(
            f"legacy projection: candidate_ref {target_ref!r} is not a ref emitted "
            f"this run (stale) — BLOCK, re-approve against current state"
        )
    subject = refs_by_id[subject_ref]
    target = refs_by_id[target_ref]

    explicit_variants = row.get("reviewed_raw_variants")
    if loader == "county":
        current_variants = list(subject.get("raw_variants", []))
        if len(current_variants) > 1 and not explicit_variants:
            raise ValueError(
                f"legacy projection: multi-raw-variant County group {subject_ref!r} "
                f"({len(current_variants)} variants) and the flat legacy row names no "
                f"reviewed variants — BLOCK; the operator must re-approve through B's "
                f"variant-aware flow (deriving variants ≠ knowing which were reviewed)"
            )
        reviewed = list(explicit_variants) if explicit_variants else current_variants
    else:
        reviewed = list(explicit_variants) if explicit_variants else []

    return make_assertion(
        subject_ref=subject_ref,
        target_ref=target_ref,
        status="approved",
        basis="operator_approved_name",
        subject=subject,
        target=target,
        reviewer=legacy_reviewer or "unknown_legacy",
        decided_at=legacy_decided_at or "legacy_unknown",
        policy_version=policy_version,
        reviewed_raw_variants=reviewed,
        legacy_projection=True,
    )
