"""Tests for export_existing_orgs.py — Lane 2 Unit 5: surface sos_id (+ static
normalizer view + the operator-gated enriched export mode).

The export is refactored to an identity-key config and extended to surface
`sos_id` with the SAME ledger-validation as `ein`/`uei` (orientation
direct/inverse/wrong-pair, supersession, key-bearing basis, multi-key conflict,
own-key provenance) plus the SOS entity-level attributes. The shipped `ein`/`uei`
behavior is FROZEN (guarded by the unchanged Lane-1 test file). Codex r2 #2/#5:
the enriched path consumes the immutable registry view, and an operator-gated
`--enriched` write path emits the approved key as real JSON (fake-session tested).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from org_resolution import KEY_NORMALIZERS  # noqa: E402
import export_existing_orgs as eeo  # noqa: E402
from export_existing_orgs import (  # noqa: E402
    enrich_existing_orgs,
    org_ref_from_enriched_record,
    write_enriched_orgs,
)
from identity_ledger import make_assertion  # noqa: E402

KEY_NODE = {
    "id": "org-casos-1819837", "display_label": "Ghilotti Construction Company, Inc.",
    "sos_id": "1819837", "entity_status": "Active",
    "entity_type": "Stock Corporation - CA - General", "formation_date": "04/23/1992",
}
EXISTING = {"id": "org-ghilotti-construction-company", "display_label": "Ghilotti Construction Company"}


def _approved():
    return make_assertion(
        subject_ref=KEY_NODE["id"], target_ref=EXISTING["id"], status="approved",
        basis="operator_approved_sos_id", subject=KEY_NODE, target=EXISTING,
        reviewer="stuart@eastpeak.cc", decided_at="2026-06-21", policy_version="v1",
        evidence_refs=["record-casos-1819837"],
    )


def _link(aid, *, edge_source, edge_target, sos_id="1819837", node=None):
    return {
        "linked_node_id": node or KEY_NODE["id"],
        "edge_source_id": edge_source, "edge_target_id": edge_target, "assertion_id": aid,
        "ein": None, "uei": None, "sos_id": sos_id, "irs_subsection_class": None,
        "entity_status": "Active", "entity_type": "Stock Corporation - CA - General",
        "formation_date": "04/23/1992",
    }


def _record(**over):
    base = {
        "id": EXISTING["id"], "display_label": EXISTING["display_label"],
        "own_ein": None, "own_uei": None, "own_sos_id": None, "own_source": None,
        "own_irs_subsection_class": None, "degree": 5, "key_links": [],
    }
    base.update(over)
    return base


# --------------------------------------------------------------------------
# sos_id orientation rule — direct / inverse / wrong-pair
# --------------------------------------------------------------------------


def test_enriched_query_link_filter_includes_sos_id():
    """The link WHERE must accept sos_id-only key nodes — else CA-SOS keys are
    filtered out against the real DB (a fake session can't catch this; found live)."""
    from export_existing_orgs import ENRICHED_ORGS_QUERY
    link_filter = ENRICHED_ORGS_QUERY.split("WITH n")[0]
    assert "m.sos_id IS NOT NULL" in link_filter


def test_sos_id_direct_orientation_surfaces_key_and_attributes():
    a = _approved()
    rec = _record(key_links=[_link(a["id"], edge_source=KEY_NODE["id"], edge_target=EXISTING["id"])])
    ref = org_ref_from_enriched_record(rec, {a["id"]: a})
    assert ref["sos_id"] == "1819837"
    assert ref["entity_status"] == "Active"
    assert ref["entity_type"] == "Stock Corporation - CA - General"
    assert ref["formation_date"] == "04/23/1992"


def test_sos_id_inverse_orientation_surfaces_key():
    a = _approved()
    rec = _record(key_links=[_link(a["id"], edge_source=EXISTING["id"], edge_target=KEY_NODE["id"])])
    assert org_ref_from_enriched_record(rec, {a["id"]: a})["sos_id"] == "1819837"


def test_sos_id_wrong_pair_rejected():
    a = _approved()
    rec = _record(key_links=[_link(a["id"], edge_source=EXISTING["id"], edge_target="org-unrelated-999")])
    assert "sos_id" not in org_ref_from_enriched_record(rec, {a["id"]: a})


def test_sos_id_queued_assertion_surfaces_no_key():
    a = _approved()
    a["status"] = "queued"
    rec = _record(key_links=[_link(a["id"], edge_source=KEY_NODE["id"], edge_target=EXISTING["id"])])
    assert "sos_id" not in org_ref_from_enriched_record(rec, {a["id"]: a})


def test_sos_id_conflict_withheld():
    a1 = _approved()
    other = {"id": "org-casos-1819849", "display_label": "Ghilotti Brothers Construction, Inc.", "sos_id": "1819849"}
    a2 = make_assertion(
        subject_ref=other["id"], target_ref=EXISTING["id"], status="approved",
        basis="operator_approved_sos_id", subject=other, target=EXISTING,
        reviewer="x", decided_at="2026-06-21", policy_version="v1",
    )
    rec = _record(key_links=[
        _link(a1["id"], edge_source=KEY_NODE["id"], edge_target=EXISTING["id"]),
        _link(a2["id"], edge_source=other["id"], edge_target=EXISTING["id"], sos_id="1819849", node=other["id"]),
    ])
    ref = org_ref_from_enriched_record(rec, {a1["id"]: a1, a2["id"]: a2})
    assert "sos_id" not in ref
    assert any(c["key"] == "sos_id" for c in ref["identity_key_conflict"])


# --------------------------------------------------------------------------
# own-key provenance via the org-casos- prefix
# --------------------------------------------------------------------------


def test_own_sos_id_trusted_via_casos_prefix():
    rec = _record(id="org-casos-1628638", own_sos_id="1628638", display_label="Miller Pacific Engineering Group")
    assert org_ref_from_enriched_record(rec, {})["sos_id"] == "1628638"


def test_own_sos_id_without_provenance_is_review_only():
    rec = _record(id="org-adhoc", own_sos_id="1628638", own_source="manual")
    ref = org_ref_from_enriched_record(rec, {})
    assert "sos_id" not in ref
    assert ref["review_keys"]["sos_id"] == "1628638"


# --------------------------------------------------------------------------
# ein/uei still work (the frozen file is the real guard; this is a smoke check)
# --------------------------------------------------------------------------


def test_ein_still_surfaces_via_own_recognized_source():
    rec = _record(id="org-990-ein-942689383", own_ein="942689383", own_source="irs-990")
    assert org_ref_from_enriched_record(rec, {})["ein"] == "942689383"


# --------------------------------------------------------------------------
# Defensive registration (Codex r2 #2) + operator enriched write mode (#5)
# --------------------------------------------------------------------------


class _FakeSession:
    def __init__(self, records):
        self._records = records

    def run(self, _query):
        return iter(self._records)


def test_enriched_path_consumes_static_sos_id_normalizer():
    assert KEY_NORMALIZERS["sos_id"] is not None
    a = _approved()
    rec = _record(key_links=[_link(a["id"], edge_source=KEY_NODE["id"], edge_target=EXISTING["id"])])
    refs = enrich_existing_orgs(_FakeSession([rec]), [a])
    assert refs[0]["sos_id"] == "1819837"


def test_operator_enriched_write_emits_exactly_one_approved_sos_id(tmp_path):
    a = _approved()
    records = [
        _record(key_links=[_link(a["id"], edge_source=KEY_NODE["id"], edge_target=EXISTING["id"])]),
        _record(id="org-keyless", display_label="Keyless", key_links=[]),
    ]
    out = tmp_path / "enriched.json"
    n = write_enriched_orgs(out, _FakeSession(records), [a])
    assert n == 2
    emitted = json.loads(out.read_text())
    with_sos = [r for r in emitted if "sos_id" in r]
    assert len(with_sos) == 1
    assert with_sos[0]["sos_id"] == "1819837"
    # the emitted JSON is redaction-clean (no street/ZIP/person ever)
    from enrich_casos_keys import scan_for_forbidden
    assert scan_for_forbidden(emitted) == []
