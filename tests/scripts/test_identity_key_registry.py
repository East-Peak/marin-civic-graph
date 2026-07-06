"""Goal 0 Units 2-5 — the IdentityKey registry: entries (composite key +
semantics), validator (contradiction rules), and generated compatibility views
(parity-locked to BASE_SHA). This file grows unit by unit.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import MappingProxyType

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import identity_key_normalizers as kn  # noqa: E402
import identity_key_registry as reg  # noqa: E402


# --- Unit 2: entries + composite key + semantics ---------------------------

def test_composite_key_unique():
    keys = [(e.key_type, e.semantics_scope) for e in reg.REGISTRY]
    assert len(keys) == len(set(keys)), "duplicate (key_type, semantics_scope)"


def test_key_types_present():
    assert {"ein", "uei", "sos_id", "committee_id"} <= {e.key_type for e in reg.REGISTRY}


def test_committee_id_two_scoped_entries():
    ce = reg.entries_for("committee_id")
    assert {e.semantics_scope for e in ce} == {"self_committee", "related_committee_pointer"}
    self_c = reg.entry("committee_id", "self_committee")
    rel = reg.entry("committee_id", "related_committee_pointer")
    # self_committee: a committee's OWN identity — mergeable + dedup-eligible
    assert self_c.key_semantics == "self"
    assert self_c.eligible_entity_classes == ("committee",)
    assert self_c.allowed_merge_semantics == ("self",)
    assert self_c.dedup_eligibility is True
    assert self_c.relationship_only is False
    # related_committee_pointer: a pointer on a non-committee endpoint — never merges
    assert rel.relationship_only is True
    assert rel.dedup_eligibility is False
    assert rel.allowed_merge_semantics == ()
    assert rel.key_semantics != "self"


def test_normalizer_is_shared_callable():
    shared = {kn._normalize_ein, kn._normalize_uei, kn._normalize_sos_id, kn._normalize_committee_id}
    for e in reg.REGISTRY:
        assert e.normalizer in shared, f"{e.key_type}/{e.semantics_scope} normalizer not shared"
    assert reg.entry("ein", "self").normalizer is kn._normalize_ein
    assert reg.entry("uei", "self").normalizer is kn._normalize_uei
    assert reg.entry("sos_id", "self").normalizer is kn._normalize_sos_id
    assert reg.entry("committee_id", "self_committee").normalizer is kn._normalize_committee_id


def test_runtime_registered_flags():
    # Historical lane shims still carry import-order coverage, but the registry
    # now owns every normalizer statically.
    assert reg.entry("ein", "self").runtime_registered is False
    assert reg.entry("uei", "self").runtime_registered is False
    assert reg.entry("sos_id", "self").runtime_registered is True
    assert reg.entry("committee_id", "self_committee").runtime_registered is True


def test_anchor_prefix_per_key_type():
    assert reg.entry("ein", "self").anchor_prefix == "org-bmf-ein-"
    assert reg.entry("sos_id", "self").anchor_prefix == "org-casos-"
    assert reg.entry("uei", "self").anchor_prefix == "org-usasp-uei-"
    assert reg.entry("committee_id", "self_committee").anchor_prefix == "org-fppc-"
    # scoped entries of one key_type share the anchor prefix
    assert reg.entry("committee_id", "related_committee_pointer").anchor_prefix == "org-fppc-"


def test_entry_missing_raises():
    with pytest.raises(KeyError):
        reg.entry("nope", "self")


# --- Unit 3: validator (fail-loud contradiction rules) ---------------------

def _mk(**over):
    base = dict(
        key_type="ein", semantics_scope="self", normalizer=kn._normalize_ein,
        anchor_prefix="org-x-", eligible_entity_classes=("organization",),
        key_semantics="self", allowed_merge_semantics=("self",), relationship_only=False,
        dedup_eligibility=True, runtime_registered=False,
    )
    base.update(over)
    return reg.IdentityKeyEntry(**base)


def test_validator_passes_real_registry():
    reg.validate_registry(reg.REGISTRY)  # must not raise


def test_reject_relationship_only_with_dedup():
    bad = _mk(relationship_only=True, dedup_eligibility=True,
              allowed_merge_semantics=(), key_semantics="committee")
    with pytest.raises(ValueError, match="relationship_only"):
        reg.validate_registry([bad])


def test_reject_nonself_merge_eligible():
    bad = _mk(key_semantics="committee", allowed_merge_semantics=("self",))
    with pytest.raises(ValueError, match="merge"):
        reg.validate_registry([bad])


def test_reject_duplicate_anchor_across_keytypes():
    a = _mk(key_type="ein", anchor_prefix="org-dup-")
    b = _mk(key_type="uei", normalizer=kn._normalize_uei, anchor_prefix="org-dup-")
    with pytest.raises(ValueError, match="anchor_prefix"):
        reg.validate_registry([a, b])


def test_reject_unknown_normalizer():
    bad = _mk(normalizer=lambda v: v)
    with pytest.raises(ValueError, match="normalizer"):
        reg.validate_registry([bad])


def test_reject_bad_entity_class():
    with pytest.raises(ValueError, match="entity_class"):
        reg.validate_registry([_mk(eligible_entity_classes=("martian",))])
    with pytest.raises(ValueError, match="entity_class"):
        reg.validate_registry([_mk(eligible_entity_classes=())])


def test_reject_mismatched_normalizer_within_keytype():
    a = _mk(key_type="committee_id", semantics_scope="a",
            normalizer=kn._normalize_committee_id, anchor_prefix="org-fppc-")
    b = _mk(key_type="committee_id", semantics_scope="b",
            normalizer=kn._normalize_ein, anchor_prefix="org-fppc-")
    with pytest.raises(ValueError, match="normalizer"):
        reg.validate_registry([a, b])


def test_same_anchor_and_normalizer_within_keytype_ok():
    a = _mk(key_type="committee_id", semantics_scope="self_committee",
            normalizer=kn._normalize_committee_id, anchor_prefix="org-fppc-",
            eligible_entity_classes=("committee",))
    b = _mk(key_type="committee_id", semantics_scope="rel",
            normalizer=kn._normalize_committee_id, anchor_prefix="org-fppc-",
            relationship_only=True, dedup_eligibility=False,
            allowed_merge_semantics=(), key_semantics="committee")
    reg.validate_registry([a, b])  # must not raise


# --- Unit 4: generated views parity (locked to BASE_SHA) -------------------

def test_anchor_prefixes_parity():
    assert reg.ANCHOR_PREFIXES == ("org-bmf-ein-", "org-casos-", "org-usasp-uei-", "org-fppc-")
    assert type(reg.ANCHOR_PREFIXES) is tuple


def test_dedup_keys_parity():
    expected = ("ein", "uei", "sos_id", "committee_id")
    assert reg.generate_dedup_keys() == expected
    assert reg._DEDUP_KEYS == expected
    assert type(reg._DEDUP_KEYS) is tuple


def test_key_bearing_bases_parity():
    expected = frozenset({
        "ein_exact", "uei_exact", "operator_approved_ein", "operator_approved_uei",
        "sos_id_exact", "operator_approved_sos_id", "operator_approved_committee_id",
    })
    assert reg._KEY_BEARING_BASES == expected
    assert type(reg._KEY_BEARING_BASES) is frozenset


def test_dedup_keys_membership_crosscheck_fires_on_drift(monkeypatch):
    # if the registry adds a dedup-eligible key not in the historical order, fail loud
    extra = _mk(key_type="duns", normalizer=kn._normalize_ein, anchor_prefix="org-duns-",
                dedup_eligibility=True)
    monkeypatch.setattr(reg, "REGISTRY", reg.REGISTRY + (extra,))
    with pytest.raises(ValueError, match="drift"):
        reg.generate_dedup_keys()


# --- Unit 5: KEY_NORMALIZERS complete immutable view (R2) -------------------

def test_key_normalizers_generated_complete_matches_post_registration_dict():
    # R2 parity lock: the new complete generator must equal the old world after
    # lane import-time registration populated the shared mutable dict.
    import org_resolution as o  # noqa: E402
    import enrich_casos_keys  # noqa: E402
    import enrich_fppc_keys  # noqa: E402

    enrich_casos_keys.register_sos_id_normalizer()
    enrich_fppc_keys.register_committee_id_normalizer()

    generated = reg.generate_key_normalizers()
    post_registration = dict(o.KEY_NORMALIZERS)
    assert generated == post_registration
    assert set(generated) == {"ein", "uei", "sos_id", "committee_id"}
    assert generated["ein"] is kn._normalize_ein
    assert generated["uei"] is kn._normalize_uei
    assert generated["sos_id"] is kn._normalize_sos_id
    assert generated["committee_id"] is kn._normalize_committee_id


def test_key_normalizers_view_is_immutable():
    assert type(reg.KEY_NORMALIZERS) is MappingProxyType
    with pytest.raises(TypeError):
        reg.KEY_NORMALIZERS["sos_id"] = kn._normalize_sos_id


# --- Unit 6: object-identity (one shared KEY_NORMALIZERS dict) --------------

def test_key_normalizers_object_identity():
    import org_resolution as o  # noqa: E402
    # the matcher imports the registry's immutable view — the SAME object, not a copy
    assert reg.KEY_NORMALIZERS is o.KEY_NORMALIZERS
    # importing a consumer still exercises the lane shim path; the shim validates
    # that the view already carries the expected callable.
    import export_existing_orgs  # noqa: F401, E402  (register_sos_id + register_committee_id at import)
    assert reg.KEY_NORMALIZERS is o.KEY_NORMALIZERS  # still the same object after register_*
    assert o.KEY_NORMALIZERS["sos_id"] is kn._normalize_sos_id
    assert o.KEY_NORMALIZERS["committee_id"] is kn._normalize_committee_id
