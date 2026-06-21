"""identity_resolution_adapter.py — signal_strength adapter + deterministic-merge guardrail (A, Unit 3).

Additive helpers for the egress wrapper (Unit 4). The resolver `org_resolution.py`
is NOT edited — it keeps emitting `confidence`; this module renames at the
artifact edge and supplies the entity-class guardrail the wrapper enforces.

1. `normalize_resolution_candidate_for_artifact()` — `confidence` →
   `signal_strength` for identity-resolution artifacts ONLY (ledger records,
   normalized candidates, egress join metadata). A signal, never a calibrated
   probability, never an approval threshold. Graph-node `confidence`
   (`membership_builders` / `economic_interest_builders`) is a separate code
   path and is left untouched.
2. The resolver-ref class schema + the deterministic-merge guardrail. EIN/UEI
   equality may become a `SAME_AS` (a `deterministic` ledger assertion) ONLY
   when the key is the org's OWN identity (`key_semantics == "self"`) and both
   sides are the same entity class. A parent UEI, fiscal-sponsor EIN, DBA name,
   PAC/committee id, or project name (`key_semantics` in RELATIONSHIP_SEMANTICS)
   is a RELATIONSHIP candidate, never a `SAME_AS` (Predeclared 4).
"""
from __future__ import annotations

from typing import Any

# key_semantics values whose equality must NEVER be a SAME_AS — the key relates
# two distinct entities (parent/sponsor/dba/PAC/project), it does not assert they
# are the same legal entity.
RELATIONSHIP_SEMANTICS: frozenset[str] = frozenset(
    {"parent", "fiscal_sponsor", "dba", "committee", "project"}
)

# The class fields an egress-capable resolver ref must carry (Predeclared 4).
_EGRESS_REF_FIELDS = ("entity_class", "source_system", "key_semantics")


def normalize_resolution_candidate_for_artifact(candidate: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of a resolution candidate with `confidence` renamed to
    `signal_strength` (idempotent; input never mutated)."""
    out = dict(candidate)
    if "confidence" in out:
        out["signal_strength"] = out.pop("confidence")
    return out


def deterministic_merge_allowed(
    subject_ref: dict[str, Any], target_ref: dict[str, Any] | None = None
) -> bool:
    """True iff a hard-key equality between these refs may become a `SAME_AS`.

    Requires the key to be the org's OWN identity on the subject side
    (`key_semantics == "self"`); any RELATIONSHIP semantics → False (relationship
    candidate, not a merge). When `target_ref` is given, both entity classes must
    match (an org's EIN must not merge to a committee/PAC entity)."""
    if subject_ref.get("key_semantics") in RELATIONSHIP_SEMANTICS:
        return False
    if subject_ref.get("key_semantics") != "self":
        return False
    if target_ref is not None:
        if target_ref.get("key_semantics") in RELATIONSHIP_SEMANTICS:
            return False
        if subject_ref.get("entity_class") != target_ref.get("entity_class"):
            return False
    return True


def egress_ref_complete(ref: dict[str, Any]) -> bool:
    """True iff a ref carries the full class schema an egress-capable caller must
    populate (the wrapper fails closed otherwise — Predeclared 4)."""
    return all(ref.get(field) for field in _EGRESS_REF_FIELDS)
