"""Tests for scripts/export_existing_orgs.py — Unit 3: read-only enrichment.

Lane 1, Unit 3 (Predeclared 4). The export is extended so each existing org ref
carries `ein`/`uei`/`irs_subsection_class`/`degree` — but a key only ever
surfaces when its backing identity is REAL in the current ledger. The guards are
the whole point:

- a graph SAME_AS edge stamped with an `assertion_id` is NOT trusted on its
  face — the assertion must resolve in the ledger to `deterministic|approved`,
  `superseded_by is None`, an allowed basis, AND its unordered
  `{subject_ref, target_ref}` must equal the edge's `{source, target}` endpoints
  (A's ids are directional, so a copied id on the wrong pair must fail) — with
  `direct`, `inverse`, and `wrong-pair` tests;
- a `queued`/rejected/superseded/stale-edge SAME_AS surfaces NO key;
- two validated links to DIFFERENT EINs → withhold + `identity_key_conflict`;
- an own `n.ein` whose node has no recognized `source`/key-prefix is review-only,
  never a deterministic key;
- the pure transform handles degree-present and degree-null records.

The live query is operator-gated and tested against a FAKE session — never a DB.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from export_existing_orgs import (  # noqa: E402
    enrich_existing_orgs,
    org_ref_from_enriched_record,
)
from identity_ledger import make_assertion  # noqa: E402

KEY_NODE = {
    "id": "org-bmf-ein-941415040",
    "display_label": "Marin Builders Association",
    "ein": "941415040",
    "irs_subsection_class": "trade_association",
}
EXISTING = {"id": "org-existing-marin-builders", "display_label": "Marin Builders Association"}


def _approved_assertion():
    return make_assertion(
        subject_ref=KEY_NODE["id"],
        target_ref=EXISTING["id"],
        status="approved",
        basis="operator_approved_ein",
        subject=KEY_NODE,
        target=EXISTING,
        reviewer="stuart@eastpeak.cc",
        decided_at="2026-06-21",
        policy_version="v1",
        evidence_refs=["record-bmf-941415040"],
    )


def _link(assertion_id, *, edge_source, edge_target, ein="941415040",
          subtype="trade_association", linked_node_id=None):
    return {
        "linked_node_id": linked_node_id or KEY_NODE["id"],
        "edge_source_id": edge_source,
        "edge_target_id": edge_target,
        "assertion_id": assertion_id,
        "ein": ein,
        "uei": None,
        "irs_subsection_class": subtype,
    }


def _record(**over):
    base = {
        "id": EXISTING["id"],
        "display_label": EXISTING["display_label"],
        "own_ein": None,
        "own_uei": None,
        "own_source": None,
        "own_irs_subsection_class": None,
        "degree": 7,
        "key_links": [],
    }
    base.update(over)
    return base


# --------------------------------------------------------------------------
# Orientation rule — direct / inverse / wrong-pair (Codex r2 blocker)
# --------------------------------------------------------------------------


def test_direct_orientation_surfaces_key():
    a = _approved_assertion()
    rec = _record(key_links=[_link(a["id"], edge_source=KEY_NODE["id"], edge_target=EXISTING["id"])])
    ref = org_ref_from_enriched_record(rec, {a["id"]: a})
    assert ref["ein"] == "941415040"
    assert ref["irs_subsection_class"] == "trade_association"
    assert ref["degree"] == 7


def test_inverse_orientation_surfaces_key():
    """Edge endpoints swapped vs the assertion's subject/target — the UNORDERED
    set still matches, so the link is valid (inverse)."""
    a = _approved_assertion()
    rec = _record(key_links=[_link(a["id"], edge_source=EXISTING["id"], edge_target=KEY_NODE["id"])])
    ref = org_ref_from_enriched_record(rec, {a["id"]: a})
    assert ref["ein"] == "941415040"


def test_wrong_pair_assertion_id_is_rejected():
    """A REAL assertion id stamped on a DIFFERENT edge (endpoints don't match the
    assertion's subject/target as a set) surfaces NO key."""
    a = _approved_assertion()
    rec = _record(key_links=[_link(a["id"], edge_source=EXISTING["id"], edge_target="org-unrelated-999")])
    ref = org_ref_from_enriched_record(rec, {a["id"]: a})
    assert "ein" not in ref


# --------------------------------------------------------------------------
# Non-publishing / stale assertions surface nothing
# --------------------------------------------------------------------------


def test_queued_assertion_surfaces_no_key():
    a = _approved_assertion()
    a["status"] = "queued"
    rec = _record(key_links=[_link(a["id"], edge_source=KEY_NODE["id"], edge_target=EXISTING["id"])])
    assert "ein" not in org_ref_from_enriched_record(rec, {a["id"]: a})


def test_superseded_assertion_surfaces_no_key():
    a = _approved_assertion()
    a["superseded_by"] = "assertion-newer000000000"
    rec = _record(key_links=[_link(a["id"], edge_source=KEY_NODE["id"], edge_target=EXISTING["id"])])
    assert "ein" not in org_ref_from_enriched_record(rec, {a["id"]: a})


def test_relationship_basis_assertion_surfaces_no_key():
    """An approved assertion whose basis is a RELATIONSHIP (not an identity key)
    must not carry an EIN."""
    a = _approved_assertion()
    a["basis"] = "relationship_candidate"
    rec = _record(key_links=[_link(a["id"], edge_source=KEY_NODE["id"], edge_target=EXISTING["id"])])
    assert "ein" not in org_ref_from_enriched_record(rec, {a["id"]: a})


def test_missing_assertion_in_ledger_surfaces_no_key():
    rec = _record(key_links=[_link("assertion-doesnotexist", edge_source=KEY_NODE["id"], edge_target=EXISTING["id"])])
    assert "ein" not in org_ref_from_enriched_record(rec, {})


# --------------------------------------------------------------------------
# Multi-key conflict — withhold + identity_key_conflict (Codex r1 blocker 3)
# --------------------------------------------------------------------------


def test_two_links_to_different_eins_withholds_and_records_conflict():
    a1 = _approved_assertion()
    other_node = {"id": "org-bmf-ein-999999999", "display_label": "Other Org", "ein": "999999999"}
    a2 = make_assertion(
        subject_ref=other_node["id"], target_ref=EXISTING["id"], status="approved",
        basis="operator_approved_ein", subject=other_node, target=EXISTING,
        reviewer="stuart@eastpeak.cc", decided_at="2026-06-21", policy_version="v1",
    )
    rec = _record(key_links=[
        _link(a1["id"], edge_source=KEY_NODE["id"], edge_target=EXISTING["id"]),
        _link(a2["id"], edge_source=other_node["id"], edge_target=EXISTING["id"],
              ein="999999999", linked_node_id=other_node["id"]),
    ])
    ref = org_ref_from_enriched_record(rec, {a1["id"]: a1, a2["id"]: a2})
    assert "ein" not in ref  # withheld — never first-wins
    conflicts = ref["identity_key_conflict"]
    conflict = [c for c in conflicts if c["key"] == "ein"][0]
    assert set(conflict["values"]) == {"941415040", "999999999"}


# --------------------------------------------------------------------------
# Own-key provenance via EXISTING fields (Codex r2 blocker)
# --------------------------------------------------------------------------


def test_own_key_with_recognized_source_is_deterministic():
    rec = _record(id="org-990-ein-942689383", own_ein="942689383", own_source="irs-990",
                  display_label="Marin Agricultural Land Trust", key_links=[])
    ref = org_ref_from_enriched_record(rec, {})
    assert ref["ein"] == "942689383"


def test_own_key_with_recognized_id_prefix_is_deterministic():
    rec = _record(id="org-bmf-ein-237172128", own_ein="237172128", own_source=None,
                  display_label="San Geronimo Valley Community Center", key_links=[])
    ref = org_ref_from_enriched_record(rec, {})
    assert ref["ein"] == "237172128"


def test_own_key_without_recognized_provenance_is_review_only():
    rec = _record(id="org-adhoc-vendor-foo", own_ein="123456789", own_source="manual_paste",
                  display_label="Ad-hoc Vendor", key_links=[])
    ref = org_ref_from_enriched_record(rec, {})
    assert "ein" not in ref  # NOT a deterministic key
    assert ref["review_keys"]["ein"] == "123456789"


# --------------------------------------------------------------------------
# degree contract
# --------------------------------------------------------------------------


def test_degree_present_and_null():
    assert org_ref_from_enriched_record(_record(degree=12), {})["degree"] == 12
    assert "degree" not in org_ref_from_enriched_record(_record(degree=None), {})


# --------------------------------------------------------------------------
# Live query against a FAKE session — no real DB
# --------------------------------------------------------------------------


class _FakeSession:
    def __init__(self, records):
        self._records = records

    def run(self, _query):
        return iter(self._records)


def test_enrich_existing_orgs_against_fake_session():
    a = _approved_assertion()
    records = [
        _record(key_links=[_link(a["id"], edge_source=KEY_NODE["id"], edge_target=EXISTING["id"])]),
        _record(id="org-keyless-tail", display_label="Keyless Org", degree=2, key_links=[]),
    ]
    refs = enrich_existing_orgs(_FakeSession(records), [a])
    by_id = {r["id"]: r for r in refs}
    assert by_id["org-existing-marin-builders"]["ein"] == "941415040"
    assert "ein" not in by_id["org-keyless-tail"]  # the keyless tail stays keyless
