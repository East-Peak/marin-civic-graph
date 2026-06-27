"""Goal 1 Unit 7 — the 5 golden UI packets: the read-model emitter's acceptance
contract. All synthetic (no real PII; no committed address literal). Each packet pins
one §5.7 invariant; the global contract asserts emitted rows >= 5, >= 1 normalized
candidate from EACH of EIN/SOS/committee, and the leak gate clean over BOTH parsed rows
and the raw JSONL text.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import reconciliation_cases as rc  # noqa: E402
import reconciliation_read_model as rm  # noqa: E402
from enrich_casos_keys import scan_for_forbidden  # noqa: E402
from reconciliation_adapters import CommitteeAdapter, EinAdapter, SosAdapter  # noqa: E402

EIN_RAW = {
    "subject_ref": "org-bmf-ein-953667812", "candidate_ref": "org-marincontract-recipient-x",
    "vendor_ref": "org-marincontract-recipient-x", "signals": ["normalized_name_exact"],
    "signal_strength": 0.9, "registry_ein": "953667812", "registry_city": "San Rafael",
    "registry_state": "CA", "registry_irs_subsection_class": "charity", "display_label": "EXAMPLE YOUTH",
}
SOS_RAW = {
    "subject_ref": "org-casos-0289793", "candidate_ref": "org-marincontract-recipient-y",
    "vendor_ref": "org-marincontract-recipient-y", "signals": ["name_similarity:0.88"],
    "confidence": 0.88, "sos_ref": {"sos_id": "0289793", "display_label": "Example Services LLC",
    "entity_type": "LLC", "entity_status": "active", "formation_date": "2001-01-01",
    "principal_city": "San Rafael", "principal_state": "CA"}, "display_label": "EXAMPLE SERVICES",
}
FPPC_RAW = {
    "subject_ref": "org-fppc-1470249", "candidate_ref": "org-example-committee",
    "committee_id": "1470249", "signals": ["name_similarity:0.9"], "confidence": 0.9,
    "display_label": "Example for Council 2024",
}


def _ref(source_id, local_id):
    return rc.EntityRef(source_id=source_id, local_id=local_id, display_label=local_id,
                        public_fields={"display_label": local_id}, provenance={"adapter": source_id})


def _attach_case(adapter_cls, raw, case_id, **kw):
    join = adapter_cls([raw]).emit_candidates()[0]
    base = dict(schema_version=rc.SCHEMA_VERSION, case_id=case_id, case_type="identity_key_attach",
                candidate_joins=[join], actionability="actionable")
    base.update(kw)
    return rc.ReconciliationCase(**base)


def _packets():
    cases = []
    # Packet 1 — exact key attach (EIN); also provides EIN source coverage
    cases.append(_attach_case(EinAdapter, EIN_RAW, "p1-exact-attach"))
    # Source coverage — SOS + committee attach cases
    cases.append(_attach_case(SosAdapter, SOS_RAW, "cov-sos"))
    cases.append(_attach_case(CommitteeAdapter, FPPC_RAW, "cov-committee"))
    # Packet 2 — many candidates for one org (competing siblings)
    cases.append(_attach_case(
        EinAdapter, EIN_RAW, "p2-many-candidates", actionability="needs_review",
        component={"component_id": None, "competing_candidates_per_endpoint":
                   {"org-marincontract-recipient-x": ["org-bmf-ein-953667812", "org-bmf-ein-111111111"]},
                   "sibling_candidates": ["org-bmf-ein-111111111"], "refused_reasons": [],
                   "hard_key_conflicts": []},
    ))
    # Packet 3 — prior rejection (current_ledger_status reflects the ledger; not fresh)
    cases.append(_attach_case(
        EinAdapter, EIN_RAW, "p3-prior-rejection",
        current_ledger_status="rejected_entity_distinct", actionability="resolved",
        ledger_assertion_refs=["assert-prior-1"],
    ))
    # Packet 4 — dedup component merge (component_id + merge_plan + ONE case-scoped actionability)
    graph = {"nodes": {"org-a": {"properties": {}}, "org-b": {"properties": {}}, "org-x": {"properties": {}}},
             "edges": {("org-b", "TO_TARGET", "org-x"): {"amount": 1}}}
    plan = rm.build_merge_plan({"members": ["org-a", "org-b"], "canonical": "org-a"}, graph)
    dj = rc.CandidateJoin(candidate_id="dj-ab", left_ref=_ref("dedup", "org-a"),
                          right_ref=_ref("dedup", "org-b"), signals=["org_dedup_operator_approved"],
                          signal_strength=1.0)
    cases.append(rc.ReconciliationCase(
        schema_version=rc.SCHEMA_VERSION, case_id="p4-dedup-merge", case_type="entity_dedup_merge",
        candidate_joins=[dj], actionability="actionable", merge_plan=plan,
        component={"component_id": "comp-ab", "competing_candidates_per_endpoint": {},
                   "sibling_candidates": ["org-b"], "refused_reasons": [], "hard_key_conflicts": []},
    ))
    # Packet 5 — relationship-demotion (ONLY a refused/competing signal; never a reserved-type row)
    cases.append(_attach_case(
        EinAdapter, EIN_RAW, "p5-relationship-demotion",
        component={"component_id": None, "competing_candidates_per_endpoint": {},
                   "sibling_candidates": [],
                   "refused_reasons": ["relationship_demotion: committee_id pointer on a non-committee endpoint"],
                   "hard_key_conflicts": []},
    ))
    return cases


def test_golden_packets_contract():
    lines = rm.emit_jsonl(_packets())
    rows = [json.loads(ln) for ln in lines]
    by_id = {r["case_id"]: r for r in rows}

    # global: >= 5 rows; >= 1 per EIN/SOS/committee source; leak gate clean (parsed + raw)
    assert len(rows) >= 5
    attach_sources = {r["candidate_joins"][0]["left_ref"]["source_id"]
                      for r in rows if r["case_type"] == "identity_key_attach"}
    assert {"ein", "sos_id", "committee_id"} <= attach_sources
    assert rm.forbidden_violations(rows) == []
    assert scan_for_forbidden("".join(lines)) == []  # raw JSONL text
    assert all(r["case_type"] in rc.ACTIVE_CASE_TYPES for r in rows)  # never a reserved-type row

    # Packet 1 — exact attach: one join, no component
    assert len(by_id["p1-exact-attach"]["candidate_joins"]) == 1
    assert "component" not in by_id["p1-exact-attach"]

    # Packet 2 — competing siblings surface in the component
    assert by_id["p2-many-candidates"]["component"]["competing_candidates_per_endpoint"]

    # Packet 3 — rejection reflected; not freshly actionable
    assert by_id["p3-prior-rejection"]["current_ledger_status"] == "rejected_entity_distinct"
    assert by_id["p3-prior-rejection"]["actionability"] != "actionable"

    # Packet 4 — dedup component: component_id + merge_plan + ONE case-scoped actionability
    p4 = by_id["p4-dedup-merge"]
    assert p4["case_type"] == "entity_dedup_merge"
    assert p4["component"]["component_id"] == "comp-ab"
    assert p4["merge_plan"]["canonical_id"] == "org-a"
    assert isinstance(p4["actionability"], str)  # one per case, not per join

    # Packet 5 — relationship-demotion only as a refused signal
    assert any("relationship" in rr for rr in by_id["p5-relationship-demotion"]["component"]["refused_reasons"])
