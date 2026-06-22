"""Tests for export_existing_orgs.py — Lane 3 Unit 6: surface committee_id with
the SAME ledger-validation as ein/uei/sos_id (orientation + key-bearing basis +
conflict-withholding), the `org-fppc-` trusted prefix, and the enriched query
link-filter accepting committee_id-only key nodes.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from org_resolution import KEY_NORMALIZERS  # noqa: E402
from export_existing_orgs import (  # noqa: E402
    ENRICHED_ORGS_QUERY,
    IDENTITY_KEYS,
    _KEY_BEARING_BASES,
    _TRUSTED_ID_PREFIXES,
    org_ref_from_enriched_record,
)
from identity_ledger import make_assertion  # noqa: E402

KEY_NODE = {"id": "org-fppc-1439160", "display_label": "Bonta for Attorney General 2022",
            "committee_id": "1439160"}
EXISTING = {"id": "org-bonta-for-attorney-general-2022",
            "display_label": "Bonta for Attorney General 2022"}


@pytest.fixture(autouse=True)
def _restore_key_normalizers():
    snapshot = dict(KEY_NORMALIZERS)
    try:
        yield
    finally:
        KEY_NORMALIZERS.clear()
        KEY_NORMALIZERS.update(snapshot)


def _approved(target=EXISTING):
    return make_assertion(
        subject_ref=KEY_NODE["id"], target_ref=target["id"], status="approved",
        basis="operator_approved_committee_id", subject=KEY_NODE, target=target,
        reviewer="stuart@eastpeak.cc", decided_at="2026-06-22", policy_version="v1",
        evidence_refs=[],
    )


def _link(aid, *, edge_source, edge_target, committee_id="1439160", node=None):
    return {
        "linked_node_id": node or KEY_NODE["id"],
        "edge_source_id": edge_source, "edge_target_id": edge_target, "assertion_id": aid,
        "ein": None, "uei": None, "sos_id": None, "committee_id": committee_id,
        "irs_subsection_class": None, "entity_status": None, "entity_type": None,
        "formation_date": None,
    }


def _record(**over):
    base = {
        "id": EXISTING["id"], "display_label": EXISTING["display_label"],
        "own_ein": None, "own_uei": None, "own_sos_id": None, "own_committee_id": None,
        "own_source": None, "own_irs_subsection_class": None, "degree": 5, "key_links": [],
    }
    base.update(over)
    return base


def test_committee_id_in_identity_keys_and_query_link_filter():
    assert "committee_id" in IDENTITY_KEYS
    assert "m.committee_id IS NOT NULL" in ENRICHED_ORGS_QUERY  # link filter accepts committee-id key nodes
    assert "committee_id: m.committee_id" in ENRICHED_ORGS_QUERY
    assert "n.committee_id AS own_committee_id" in ENRICHED_ORGS_QUERY


def test_operator_approved_committee_id_is_key_bearing_and_prefix_trusted():
    assert "operator_approved_committee_id" in _KEY_BEARING_BASES
    assert "org-fppc-" in _TRUSTED_ID_PREFIXES


def test_committee_id_link_surfaces_key():
    a = _approved()
    rec = _record(key_links=[_link(a["id"], edge_source=KEY_NODE["id"], edge_target=EXISTING["id"])])
    ref = org_ref_from_enriched_record(rec, {a["id"]: a})
    assert ref["committee_id"] == "1439160"


def test_committee_id_conflict_withheld():
    a1 = _approved()
    # a second valid link carrying a DIFFERENT committee_id -> conflict -> withheld
    other_anchor = {"id": "org-fppc-1456428", "display_label": EXISTING["display_label"],
                    "committee_id": "1456428"}
    a2 = make_assertion(
        subject_ref=other_anchor["id"], target_ref=EXISTING["id"], status="approved",
        basis="operator_approved_committee_id", subject=other_anchor, target=EXISTING,
        reviewer="stuart@eastpeak.cc", decided_at="2026-06-22", policy_version="v1", evidence_refs=[],
    )
    rec = _record(key_links=[
        _link(a1["id"], edge_source=KEY_NODE["id"], edge_target=EXISTING["id"]),
        _link(a2["id"], edge_source=other_anchor["id"], edge_target=EXISTING["id"],
              committee_id="1456428", node=other_anchor["id"]),
    ])
    ref = org_ref_from_enriched_record(rec, {a1["id"]: a1, a2["id"]: a2})
    assert "committee_id" not in ref  # conflicting committee_ids -> withheld
