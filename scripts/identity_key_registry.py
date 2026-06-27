"""IdentityKey registry — the single declaration point for the identity keys the
reconciliation engine understands, carrying each key's full SEMANTICS.

Generic-by-design (toolkit Goal 0): a new region declares its keys here once.
Today's scattered constants (``KEY_NORMALIZERS``, ``ANCHOR_PREFIXES``,
``_DEDUP_KEYS``, ``_KEY_BEARING_BASES``) are GENERATED from this registry as
compatibility views (later units), parity-locked to BASE_SHA so behavior is
byte-identical.

Imports ONLY ``identity_key_normalizers`` (which imports stdlib only) — never
``org_resolution`` or the enrich lanes — so the import DAG stays acyclic:
``identity_key_registry -> identity_key_normalizers``, while ``org_resolution``
and the lanes import both this module and ``identity_key_normalizers``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import identity_key_normalizers as _kn


@dataclass(frozen=True)
class IdentityKeyEntry:
    """One scoped identity-key declaration, keyed by ``(key_type, semantics_scope)``.

    A single ``key_type`` may hold several scoped entries (e.g. ``committee_id`` is
    both a committee's self-identity and a relationship pointer on a non-committee
    endpoint). The semantics fields gate what the engine may do with the key: only
    ``key_semantics == "self"`` with merge eligibility may become a SAME_AS;
    ``relationship_only`` entries never merge and never form dedup components.
    """

    key_type: str
    semantics_scope: str
    normalizer: Callable[[Any], str | None]
    anchor_prefix: str
    eligible_entity_classes: tuple[str, ...]
    key_semantics: str
    allowed_merge_semantics: tuple[str, ...]
    relationship_only: bool
    dedup_eligibility: bool
    runtime_registered: bool


# Entry order is chosen so the generated ANCHOR_PREFIXES view (deduped in this
# order) reproduces the BASE_SHA tuple exactly. _DEDUP_KEYS uses its own explicit
# historical order (see the views unit) because the two BASE_SHA tuples order
# {uei, sos_id} differently.
REGISTRY: tuple[IdentityKeyEntry, ...] = (
    IdentityKeyEntry(
        key_type="ein", semantics_scope="self", normalizer=_kn._normalize_ein,
        anchor_prefix="org-bmf-ein-", eligible_entity_classes=("organization",),
        key_semantics="self", allowed_merge_semantics=("self",),
        relationship_only=False, dedup_eligibility=True, runtime_registered=False,
    ),
    IdentityKeyEntry(
        key_type="sos_id", semantics_scope="self", normalizer=_kn._normalize_sos_id,
        anchor_prefix="org-casos-", eligible_entity_classes=("organization",),
        key_semantics="self", allowed_merge_semantics=("self",),
        relationship_only=False, dedup_eligibility=True, runtime_registered=True,
    ),
    IdentityKeyEntry(
        key_type="uei", semantics_scope="self", normalizer=_kn._normalize_uei,
        anchor_prefix="org-usasp-uei-", eligible_entity_classes=("organization",),
        key_semantics="self", allowed_merge_semantics=("self",),
        relationship_only=False, dedup_eligibility=True, runtime_registered=False,
    ),
    IdentityKeyEntry(
        key_type="committee_id", semantics_scope="self_committee",
        normalizer=_kn._normalize_committee_id, anchor_prefix="org-fppc-",
        eligible_entity_classes=("committee",), key_semantics="self",
        allowed_merge_semantics=("self",), relationship_only=False,
        dedup_eligibility=True, runtime_registered=True,
    ),
    IdentityKeyEntry(
        key_type="committee_id", semantics_scope="related_committee_pointer",
        normalizer=_kn._normalize_committee_id, anchor_prefix="org-fppc-",
        eligible_entity_classes=("organization",), key_semantics="committee",
        allowed_merge_semantics=(), relationship_only=True,
        dedup_eligibility=False, runtime_registered=True,
    ),
)


def entry(key_type: str, semantics_scope: str) -> IdentityKeyEntry:
    """The single entry for ``(key_type, semantics_scope)``; ``KeyError`` if absent."""
    for e in REGISTRY:
        if e.key_type == key_type and e.semantics_scope == semantics_scope:
            return e
    raise KeyError((key_type, semantics_scope))


def entries_for(key_type: str) -> tuple[IdentityKeyEntry, ...]:
    """All scoped entries for a ``key_type`` (one or more)."""
    return tuple(e for e in REGISTRY if e.key_type == key_type)


# --- validator (fail-loud; runs at import over the real REGISTRY) -----------

KNOWN_ENTITY_CLASSES = frozenset({"organization", "committee"})
_KNOWN_NORMALIZERS = frozenset(
    {_kn._normalize_ein, _kn._normalize_uei, _kn._normalize_sos_id, _kn._normalize_committee_id}
)


def validate_registry(entries) -> None:
    """Fail loud on a contradictory registry. A wrong identity merge is a false
    public claim, so the registry refuses to load if any entry could authorize one
    it shouldn't (or duplicate/garble the policy the engine relies on)."""
    for e in entries:
        tag = f"{e.key_type}/{e.semantics_scope}"
        if e.relationship_only and e.dedup_eligibility:
            raise ValueError(f"{tag}: relationship_only entry cannot be dedup_eligible")
        if e.allowed_merge_semantics and e.key_semantics != "self":
            raise ValueError(
                f"{tag}: non-self key_semantics {e.key_semantics!r} cannot be merge-eligible"
            )
        if set(e.allowed_merge_semantics) - {"self"}:
            raise ValueError(f"{tag}: allowed_merge_semantics must be a subset of {{'self'}}")
        if e.normalizer not in _KNOWN_NORMALIZERS:
            raise ValueError(f"{tag}: unknown normalizer {e.normalizer!r}")
        if not e.eligible_entity_classes or not set(e.eligible_entity_classes) <= KNOWN_ENTITY_CLASSES:
            raise ValueError(
                f"{tag}: invalid eligible_entity_classes {e.eligible_entity_classes!r} "
                f"(known: {sorted(KNOWN_ENTITY_CLASSES)})"
            )

    by_anchor: dict[str, set[str]] = {}
    for e in entries:
        by_anchor.setdefault(e.anchor_prefix, set()).add(e.key_type)
    for anchor, kts in by_anchor.items():
        if len(kts) > 1:
            raise ValueError(
                f"duplicate anchor_prefix {anchor!r} across distinct key_types {sorted(kts)}"
            )

    by_keytype: dict[str, set] = {}
    for e in entries:
        by_keytype.setdefault(e.key_type, set()).add(e.normalizer)
    for kt, norms in by_keytype.items():
        if len(norms) > 1:
            raise ValueError(
                f"key_type {kt!r} has multiple normalizers; all scoped entries must share one"
            )


validate_registry(REGISTRY)
