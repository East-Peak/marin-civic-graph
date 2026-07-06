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
from types import MappingProxyType
from typing import Any, Callable, Mapping

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
    public_key_field: str
    anchor_source: str
    attach_basis: str
    anchor_subject_fields: tuple[tuple[str, str], ...]


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
        public_key_field="registry_ein", anchor_source="irs_bmf",
        attach_basis="operator_approved_ein",
        anchor_subject_fields=(
            ("display_label", "vendor_ref.display_label|anchor_id"),
            ("ein", "candidate.ein|anchor_suffix"),
            ("source", "const:irs_bmf"),
        ),
    ),
    IdentityKeyEntry(
        key_type="sos_id", semantics_scope="self", normalizer=_kn._normalize_sos_id,
        anchor_prefix="org-casos-", eligible_entity_classes=("organization",),
        key_semantics="self", allowed_merge_semantics=("self",),
        relationship_only=False, dedup_eligibility=True, runtime_registered=True,
        public_key_field="sos_id", anchor_source="ca_sos",
        attach_basis="operator_approved_sos_id",
        anchor_subject_fields=(
            ("display_label", "candidate.sos_ref.display_label|anchor_id"),
            ("sos_id", "candidate.sos_ref.sos_id"),
            ("source", "const:ca_sos"),
        ),
    ),
    IdentityKeyEntry(
        key_type="uei", semantics_scope="self", normalizer=_kn._normalize_uei,
        anchor_prefix="org-usasp-uei-", eligible_entity_classes=("organization",),
        key_semantics="self", allowed_merge_semantics=("self",),
        relationship_only=False, dedup_eligibility=True, runtime_registered=False,
        public_key_field="uei", anchor_source="usaspending",
        attach_basis="operator_approved_uei",
        anchor_subject_fields=(
            ("display_label", "vendor_ref.display_label|anchor_id"),
            ("uei", "candidate.uei|anchor_suffix"),
            ("source", "const:usaspending"),
        ),
    ),
    IdentityKeyEntry(
        key_type="committee_id", semantics_scope="self_committee",
        normalizer=_kn._normalize_committee_id, anchor_prefix="org-fppc-",
        eligible_entity_classes=("committee",), key_semantics="self",
        allowed_merge_semantics=("self",), relationship_only=False,
        dedup_eligibility=True, runtime_registered=True,
        public_key_field="committee_id", anchor_source="fppc",
        attach_basis="operator_approved_committee_id",
        anchor_subject_fields=(
            ("display_label", "vendor_ref.display_label|anchor_id"),
            ("committee_id", "candidate.committee_id"),
            ("entity_class", "const:committee"),
            ("source", "const:fppc"),
        ),
    ),
    IdentityKeyEntry(
        key_type="committee_id", semantics_scope="related_committee_pointer",
        normalizer=_kn._normalize_committee_id, anchor_prefix="org-fppc-",
        eligible_entity_classes=("organization",), key_semantics="committee",
        allowed_merge_semantics=(), relationship_only=True,
        dedup_eligibility=False, runtime_registered=True,
        public_key_field="committee_id", anchor_source="fppc",
        attach_basis="operator_approved_committee_id",
        anchor_subject_fields=(
            ("display_label", "vendor_ref.display_label|anchor_id"),
            ("committee_id", "candidate.committee_id"),
            ("entity_class", "const:committee"),
            ("source", "const:fppc"),
        ),
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
KNOWN_ANCHOR_SOURCES = frozenset({"irs_bmf", "ca_sos", "usaspending", "fppc"})
_KNOWN_NORMALIZERS = frozenset(
    {_kn._normalize_ein, _kn._normalize_uei, _kn._normalize_sos_id, _kn._normalize_committee_id}
)
_PUBLIC_KEY_FIELDS = {
    "ein": "registry_ein",
    "uei": "uei",
    "sos_id": "sos_id",
    "committee_id": "committee_id",
}
_SELECTOR_PREFIXES = ("candidate.", "vendor_ref.", "const:")


def _validate_anchor_selector(tag: str, selector: str) -> None:
    if not isinstance(selector, str) or not selector:
        raise ValueError(f"{tag}: anchor_subject_fields selector must be a non-empty string")
    for part in selector.split("|"):
        if part in {"anchor_id", "anchor_suffix"}:
            continue
        if any(part.startswith(prefix) and len(part) > len(prefix) for prefix in _SELECTOR_PREFIXES):
            continue
        raise ValueError(f"{tag}: invalid anchor_subject_fields selector {selector!r}")


def _anchor_subject_map(e: IdentityKeyEntry) -> dict[str, str]:
    if (
        not isinstance(e.anchor_subject_fields, tuple)
        or not e.anchor_subject_fields
        or not all(isinstance(pair, tuple) and len(pair) == 2 for pair in e.anchor_subject_fields)
    ):
        raise ValueError(
            f"{e.key_type}/{e.semantics_scope}: anchor_subject_fields must be a non-empty "
            "tuple of (field, selector) pairs"
        )
    out: dict[str, str] = {}
    for field, selector in e.anchor_subject_fields:
        tag = f"{e.key_type}/{e.semantics_scope}"
        if not isinstance(field, str) or not field:
            raise ValueError(f"{tag}: anchor_subject_fields field must be a non-empty string")
        if field in out:
            raise ValueError(f"{tag}: duplicate anchor_subject_fields field {field!r}")
        _validate_anchor_selector(tag, selector)
        out[field] = selector
    return out


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
        if e.public_key_field != _PUBLIC_KEY_FIELDS.get(e.key_type):
            raise ValueError(
                f"{tag}: public_key_field {e.public_key_field!r} does not match "
                f"expected {_PUBLIC_KEY_FIELDS.get(e.key_type)!r}"
            )
        if e.anchor_source not in KNOWN_ANCHOR_SOURCES:
            raise ValueError(f"{tag}: unknown anchor_source {e.anchor_source!r}")
        expected_basis = f"operator_approved_{e.key_type}"
        if e.attach_basis != expected_basis:
            raise ValueError(
                f"{tag}: attach_basis {e.attach_basis!r} does not match {expected_basis!r}"
            )
        subject_fields = _anchor_subject_map(e)
        if e.key_type not in subject_fields:
            raise ValueError(
                f"{tag}: anchor_subject_fields must include public key field {e.key_type!r}"
            )
        if subject_fields.get("source") != f"const:{e.anchor_source}":
            raise ValueError(
                f"{tag}: anchor_subject_fields source must be const:{e.anchor_source}"
            )
        if e.key_type == "committee_id" and e.semantics_scope == "self_committee":
            if subject_fields.get("entity_class") != "const:committee":
                raise ValueError(
                    f"{tag}: committee anchor_subject_fields must keep entity_class committee"
                )
            if subject_fields.get("source") != "const:fppc":
                raise ValueError(f"{tag}: committee anchor_subject_fields must keep source fppc")

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


# --- generated compatibility views (parity-locked to BASE_SHA) --------------
# Consumers import these names in place of their former inline literals. The
# parity tests prove each equals its BASE_SHA value before any consumer rewires.

def generate_anchor_prefixes() -> tuple[str, ...]:
    """Distinct anchor prefixes in REGISTRY order (committee_id's two scoped
    entries collapse to one). DERIVED — the entry order reproduces the BASE_SHA
    tuple exactly."""
    out: list[str] = []
    for e in REGISTRY:
        if e.anchor_prefix not in out:
            out.append(e.anchor_prefix)
    return tuple(out)


# BASE_SHA-historical view order; MEMBERSHIP is cross-checked against the
# registry so order and registry cannot drift apart.
_DEDUP_KEY_ORDER: tuple[str, ...] = ("ein", "uei", "sos_id", "committee_id")


def generate_dedup_keys() -> tuple[str, ...]:
    """Dedup-eligible key_types. Membership derives from the registry
    (``dedup_eligibility``); the order is the BASE_SHA-historical sequence,
    cross-checked against that membership."""
    eligible = {e.key_type for e in REGISTRY if e.dedup_eligibility}
    if set(_DEDUP_KEY_ORDER) != eligible:
        raise ValueError(
            f"_DEDUP_KEYS order/registry drift: {_DEDUP_KEY_ORDER} vs "
            f"dedup-eligible {sorted(eligible)}"
        )
    return _DEDUP_KEY_ORDER


_KEY_BEARING_BASES_HISTORICAL: frozenset[str] = frozenset(
    {
        "ein_exact", "uei_exact", "operator_approved_ein", "operator_approved_uei",
        "sos_id_exact", "operator_approved_sos_id",  # Lane 2
        "operator_approved_committee_id",  # Lane 3 (committee_id — name-resolved, operator-approved)
    }
)


def generate_key_bearing_bases() -> frozenset[str]:
    """Bases on a SAME_AS that legitimately carry a hard key (self-identity exact
    merges + operator key-approvals). Cross-checked: every dedup-eligible key has
    its ``operator_approved_<key>`` basis present (committee_id is operator-only —
    name-resolved, never deterministic-``_exact``)."""
    for e in REGISTRY:
        if e.dedup_eligibility:
            basis = f"operator_approved_{e.key_type}"
            if basis not in _KEY_BEARING_BASES_HISTORICAL:
                raise ValueError(f"missing key-bearing basis {basis!r} for dedup key {e.key_type!r}")
    return _KEY_BEARING_BASES_HISTORICAL


def generate_key_normalizers() -> dict[str, Callable[[Any], str | None]]:
    """Complete ``KEY_NORMALIZERS`` mapping generated from the registry.

    Returns a fresh dict for parity tests and construction; the exported
    ``KEY_NORMALIZERS`` below is an immutable read-through view over this table.
    Scoped entries that share a key_type must share the same normalizer (already
    validated at import), so duplicate key_types collapse deterministically.
    """
    out: dict[str, Callable[[Any], str | None]] = {}
    for e in REGISTRY:
        existing = out.get(e.key_type)
        if existing is None:
            out[e.key_type] = e.normalizer
        elif existing is not e.normalizer:
            raise ValueError(f"key_type {e.key_type!r} has multiple normalizers")
    return out


ANCHOR_PREFIXES: tuple[str, ...] = generate_anchor_prefixes()
_DEDUP_KEYS: tuple[str, ...] = generate_dedup_keys()
_KEY_BEARING_BASES: frozenset[str] = generate_key_bearing_bases()
_KEY_NORMALIZER_TABLE = generate_key_normalizers()
KEY_NORMALIZERS: Mapping[str, Callable[[Any], str | None]] = MappingProxyType(_KEY_NORMALIZER_TABLE)
