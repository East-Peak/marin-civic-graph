"""Votes Part B2, increment b: the additive bundle — new Decisions, CAST_VOTE edges, holds, the status rule.

A fictional council `body-x` (org `org-body-x`), fictional members and a fictional baseline export."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import votes_bundle  # noqa: E402
from case_additive_plan import _neo4j_value, _read_jsonl, write_export  # noqa: E402
from export_live_graph import _clean_props  # noqa: E402
from votes_bundle import (  # noqa: E402
    BundleError,
    accounting,
    build_bundle,
    decision_label,
    evidence_string,
    item_number,
)
from votes_persons import Resolver  # noqa: E402

BODY = "body-x"
ORG = "org-body-x"
BODY_ORG = {BODY: ORG}
BODY_NAME = {BODY: "Example Council"}


def _n(id_, labels, **props):
    return {"id": id_, "labels": labels, "properties": {"id": id_, **props}}


def _e(s, t, rel, **props):
    return {"start_id": s, "end_id": t, "type": rel, "properties": props}


def _term(draft_id, key, start, end=None, end_kind="stated"):
    return {"draft_id": draft_id, "key": key, "member": key.title(), "seat": "District 1", "start": start,
            "start_kind": "stated", "end": end, "end_kind": end_kind if end else None}


TERMS = [_term("x-alder", "ALDER", "2020-01-01"), _term("x-birch", "BIRCH", "2020-01-01"),
         _term("x-cedar", "CEDAR", "2020-01-01", "2021-06-30"), _term("x-dogwood", "DOGWOOD", "2020-01-01")]
# DOGWOOD is (wrongly, for the test) mapped to Alder's Person: two keys, one Person
PERSON = {"x-alder": "person-ann-alder", "x-birch": "person-bea-birch", "x-cedar": "person-cy-cedar",
          "x-dogwood": "person-ann-alder"}


def _resolver():
    drafts = {BODY: {"body": BODY, "terms": TERMS}}
    items = [{"item": str(i + 1), "draft_id": t["draft_id"], "body": BODY} for i, t in enumerate(TERMS)]
    answers = [{"item": i["item"], "option": "confirm", "note": None} for i in items]
    rows = [{"item": i["item"], "draft_id": i["draft_id"], "body": BODY, "key": t["key"], "member": t["member"],
             "term_start": t["start"], "term_end": t["end"], "person_id": PERSON[t["draft_id"]],
             "status": "verified_no_person" if t["key"] == "CEDAR" else "mapped", "provenance": [],
             "alternates": [], "notes": ""} for i, t in zip(items, TERMS)]
    return Resolver(drafts, items, answers, rows, answers, as_of="2026-10-14"), rows


def _span(s, e):
    return {"start": s, "end": e, "line_start": 1, "line_end": 1}


def _member(name, s=None, inferred=False):
    if inferred:
        return {"name": name, "inferred": True, "raw": None, "span": None}
    return {"name": name, "raw": name.title(), "span": _span(s, s + len(name))}


def _event(eid, meeting, date, *, status="named", outcome="carried", aye=(), no=(), absent=(), recused=(),
           abstain=(), top="5", sub=None, motion="approve the example item"):
    cats = {"aye": list(aye), "no": list(no), "absent": list(absent), "recused": list(recused),
            "abstain": list(abstain)}
    ev = {"event_id": eid, "meeting_id": meeting, "date": date, "body": BODY, "status": status, "outcome": outcome,
          "doc_sha256": "d" * 64, "categories": cats, "item": {"top": top, "sub": sub, "title": "x", "scope": None},
          "motion": {"text": motion, "mover": None, "seconder": None, "kind": "main", "span": _span(1, 2),
                     "group_of": None},
          "sentinels": [], "attendance": {"evidence": []}, "hold_reasons": []}
    if status == "expanded":
        ev["sentinels"] = [{"category": "aye", "span": _span(500, 503), "token": "ALL"}]
        ev["attendance"] = {"evidence": [_span(10, 40), _span(300, 330)]}
    return ev


MEET = "meeting-body-x-1"
MEET2 = "meeting-body-x-2"


def _baseline(extra_nodes=(), extra_edges=()):
    nodes = [
        _n("person-ann-alder", ["Person"], name="Ann Alder"),
        _n("person-bea-birch", ["Person"], name="Bea Birch"),
        _n(MEET, ["Meeting"], meeting_date="2020-06-09", institution_id=ORG),
        _n(MEET2, ["Meeting"], meeting_date="2021-09-14", institution_id=ORG),
        _n("decision-body-x-1-vote-0", ["Decision"], meeting_id=MEET, source_id=BODY, status="carried",
           outcome="carried", motion_text="approve the minutes", decision_type="roll_call_vote"),
        *extra_nodes,
    ]
    edges = [_e("decision-body-x-1-vote-0", MEET, "DECIDED_AT"), *extra_edges]
    return nodes, edges


def _recon(matched=(), new=(), other=()):
    rows = [{"kind": "decision", "decision_id": d, "meeting_id": MEET, "status": "matched", "event_id": e,
             "candidates": [e], "reason": None, "differences": {}, "notes": []} for e, d in matched]
    rows += [{"kind": "event", "event_id": e, "meeting_id": MEET, "status": "new", "proposed_id": e,
              "event_status": "named"} for e in new]
    rows += [{"kind": "decision", "decision_id": d, "meeting_id": MEET, "status": "conflicting", "event_id": e,
              "candidates": [e], "reason": None, "differences": {"ayes": {}}, "notes": []} for e, d in other]
    return rows


def _build(events, recon, nodes=None, edges=None, resolver=None, holds=None):
    if nodes is None:
        nodes, edges = _baseline()
    resolver = resolver or _resolver()[0]
    rows = _resolver()[1]
    return build_bundle(events, recon, resolver, rows, nodes, edges, body_org=BODY_ORG, body_name=BODY_NAME,
                        revalidate=False, holds=holds)


MATCHED = _event("vev-body-x-1-aaaa-L10", MEET, "2020-06-09", motion="approve the minutes",
                 aye=[_member("ALDER", 100), _member("BIRCH", 110)], absent=[_member("CEDAR", 130)])
NEW = _event("vev-body-x-1-aaaa-L40", MEET, "2020-06-09", status="expanded", outcome="not_printed", top="7",
             sub="a", aye=[_member("ALDER", inferred=True), _member("BIRCH", inferred=True),
                           _member("CEDAR", inferred=True)])


def _disp(bundle):
    return {d["event_id"]: d["reason"] for d in bundle["dispositions"]}


class TestItemsAndLabels:
    @pytest.mark.parametrize("top, sub, want", [("5", None, "5"), ("8", "a", "8a"), ("J", "J.1", "J.1"),
                                                (None, None, None), ("10", "c", "10c"),
                                                ("J", "G.2", "G.2"), ("L", "G.10", "G.10"), ("5", "CB-2", "CB-2"),
                                                ("4", "CA-11", "CA-11"), ("9", "ii", None), ("9", "a b", None)])
    def test_item_number(self, top, sub, want):
        assert item_number({"top": top, "sub": sub}) == want

    def test_label_from_allowlisted_fields_only(self):
        assert decision_label("Example Council", "7a", "carried") == "Example Council vote, item 7a — carried"
        assert decision_label("Example Council", None, "failed") == "Example Council vote — failed"
        assert decision_label("Example Council", "3", "unknown") == "Example Council vote, item 3 — outcome not recorded"


class TestEvidence:
    def test_named_and_inferred_are_distinguishable_strings(self):
        named = evidence_string(MATCHED, MATCHED["categories"]["aye"][0], "aye")
        inferred = evidence_string(NEW, NEW["categories"]["aye"][0], "aye")
        assert named == '{"kind":"named","span":[100,105]}'
        assert inferred == '{"kind":"inferred","sentinel":[500,503],"trace":[[10,40],[300,330]]}'
        assert json.loads(named)["kind"] != json.loads(inferred)["kind"]

    def test_inferred_needs_its_category_sentinel(self):
        ev = {**NEW, "sentinels": [{"category": "no", "span": _span(1, 2), "token": "NONE"}]}
        with pytest.raises(BundleError, match="sentinel"):
            evidence_string(ev, ev["categories"]["aye"][0], "aye")


class TestBuild:
    def test_matched_event_gets_edges_on_the_existing_decision(self):
        b = _build([MATCHED], _recon(matched=[(MATCHED["event_id"], "decision-body-x-1-vote-0")]))
        assert _disp(b) == {MATCHED["event_id"]: "attached"}
        assert [n["id"] for n in b["nodes"]] == ["person-cy-cedar"]  # no Decision node: the target exists
        got = {(e["start_id"], e["end_id"], e["properties"]["vote"]) for e in b["edges"]}
        assert got == {("person-ann-alder", "decision-body-x-1-vote-0", "aye"),
                       ("person-bea-birch", "decision-body-x-1-vote-0", "aye"),
                       ("person-cy-cedar", "decision-body-x-1-vote-0", "absent")}
        e = b["edges"][0]
        assert set(e["properties"]) == {"vote", "ledger_event_id", "doc_sha256", "evidence", "disposition"}
        assert e["properties"]["ledger_event_id"] == MATCHED["event_id"] and e["properties"]["disposition"] == "named"

    def test_new_event_gets_a_decision_with_exactly_the_allowlist(self):
        b = _build([NEW], _recon(new=[NEW["event_id"]]))
        dec = [n for n in b["nodes"] if "Decision" in n["labels"]]
        assert len(dec) == 1 and dec[0]["id"] == NEW["event_id"] and dec[0]["labels"] == ["Decision"]
        label = "Example Council vote, item 7a — outcome not recorded"
        assert dec[0]["properties"] == {
            "id": NEW["event_id"], "meeting_id": MEET, "source_id": BODY, "decision_type": "roll_call_vote",
            "status": "unknown", "outcome": "not_printed", "item_number": "7a", "display_label": label,
            "search_label": label, "search_terms": f"{NEW['event_id']} {label.lower()}"}
        assert set(dec[0]["properties"]) <= votes_bundle.NEW_DECISION_PROPS
        decided = [e for e in b["edges"] if e["type"] == "DECIDED_AT"]
        assert decided == [{"start_id": NEW["event_id"], "end_id": MEET, "type": "DECIDED_AT", "properties": {}}]
        votes = [e for e in b["edges"] if e["type"] == "CAST_VOTE"]
        assert {e["properties"]["disposition"] for e in votes} == {"inferred"} and len(votes) == 3

    @pytest.mark.parametrize("outcome, status", [("carried", "carried"), ("failed", "failed"),
                                                 ("not_printed", "unknown")])
    def test_status_mapping_never_from_counts(self, outcome, status):
        ev = {**NEW, "outcome": outcome, "categories": {**NEW["categories"], "no": [_member("ALDER", 9)],
                                                        "aye": NEW["categories"]["aye"][1:]}}
        b = _build([ev], _recon(new=[ev["event_id"]]))
        assert [n["properties"]["status"] for n in b["nodes"] if "Decision" in n["labels"]] == [status]

    def test_missing_item_number_stays_missing(self):
        ev = {**NEW, "item": {"top": None, "sub": None, "title": None, "scope": None}}
        b = _build([ev], _recon(new=[ev["event_id"]]))
        props = [n for n in b["nodes"] if "Decision" in n["labels"]][0]["properties"]
        assert "item_number" not in props and props["search_label"] == "Example Council vote — outcome not recorded"

    def test_new_person_for_verified_no_person(self):
        b = _build([NEW], _recon(new=[NEW["event_id"]]))
        person = [n for n in b["nodes"] if "Person" in n["labels"]]
        assert person == [{"id": "person-cy-cedar", "labels": ["Person"], "properties": {
            "id": "person-cy-cedar", "name": "Cedar", "display_label": "Cedar", "search_label": "Cedar",
            "search_terms": "person-cy-cedar cedar"}}]

    def test_new_person_only_when_it_gets_an_edge(self):
        ev = {**NEW, "categories": {**NEW["categories"], "aye": NEW["categories"]["aye"][:2]}}
        b = _build([ev], _recon(new=[ev["event_id"]]))
        assert not [n for n in b["nodes"] if "Person" in n["labels"]]

    def test_unpaired_event_is_held(self):
        b = _build([MATCHED], _recon(other=[(MATCHED["event_id"], "decision-body-x-1-vote-0")]))
        assert _disp(b) == {MATCHED["event_id"]: "decision_not_matched"} and b["edges"] == []

    def test_held_ledger_events_are_not_part_of_the_bundle(self):
        held = {**MATCHED, "status": "held", "hold_reasons": ["tally_mismatch"]}
        assert _build([held], _recon())["dispositions"] == []

    def test_a_voter_out_of_term_holds_the_whole_roll_call(self):
        ev = {**NEW, "date": "2021-09-14", "meeting_id": MEET2}
        b = _build([ev], _recon(new=[ev["event_id"]]))
        d = b["dispositions"][0]
        assert d["reason"] == "voter_out_of_term" and b["edges"] == [] and b["nodes"] == []
        assert d["voters"] == [{"key": "CEDAR", "reason": "out_of_term", "nearest_term": "x-cedar"}]

    def test_unknown_key_holds(self):
        ev = {**MATCHED, "categories": {**MATCHED["categories"], "aye": [_member("ALDEER", 100)]}}
        b = _build([ev], _recon(matched=[(ev["event_id"], "decision-body-x-1-vote-0")]))
        assert _disp(b) == {ev["event_id"]: "voter_unknown_key"}
        assert b["dispositions"][0]["voters"] == [{"key": "ALDEER", "reason": "unknown_key", "nearest_term": None}]

    def test_member_twice_in_one_event_holds(self):
        ev = {**MATCHED, "categories": {**MATCHED["categories"], "no": [_member("ALDER", 200)]}}
        b = _build([ev], _recon(matched=[(ev["event_id"], "decision-body-x-1-vote-0")]))
        assert _disp(b) == {ev["event_id"]: "duplicate_member"}

    def test_two_events_on_one_decision_hold_both(self):
        other = {**MATCHED, "event_id": "vev-body-x-1-aaaa-L12"}
        recon = _recon(matched=[(MATCHED["event_id"], "decision-body-x-1-vote-0"),
                                (other["event_id"], "decision-body-x-1-vote-0")])
        assert set(_disp(_build([MATCHED, other], recon)).values()) == {"target_collision"}

    def test_existing_votes_on_the_target_hold(self):
        nodes, edges = _baseline(extra_edges=[_e("person-ann-alder", "decision-body-x-1-vote-0", "CAST_VOTE",
                                                 vote="aye")])
        b = _build([MATCHED], _recon(matched=[(MATCHED["event_id"], "decision-body-x-1-vote-0")]), nodes, edges)
        assert _disp(b) == {MATCHED["event_id"]: "existing_votes"}

    def test_genuine_status_contradiction_holds_and_unknown_is_reported(self):
        failed = {**MATCHED, "outcome": "failed"}
        b = _build([failed], _recon(matched=[(failed["event_id"], "decision-body-x-1-vote-0")]))
        assert _disp(b) == {failed["event_id"]: "status_contradiction"} and b["edges"] == []
        nodes, edges = _baseline()
        nodes = [{**n, "properties": {**n["properties"], "status": "unknown"}} if n["id"].startswith("decision")
                 else n for n in nodes]
        b = _build([MATCHED], _recon(matched=[(MATCHED["event_id"], "decision-body-x-1-vote-0")]), nodes, edges)
        assert _disp(b) == {MATCHED["event_id"]: "attached"}
        assert b["status_report"] == [{"decision_id": "decision-body-x-1-vote-0", "event_id": MATCHED["event_id"],
                                       "decision_status": "unknown", "ledger_outcome": "carried"}]
        not_printed = {**MATCHED, "outcome": "not_printed"}
        b = _build([not_printed], _recon(matched=[(not_printed["event_id"], "decision-body-x-1-vote-0")]))
        assert _disp(b) == {not_printed["event_id"]: "attached"} and b["status_report"] == []

    def test_a_reviewer_hold_holds_first_and_is_listed(self):
        holds = [{"event_id": MATCHED["event_id"], "reason": "spot check S6: arrival not recorded"}]
        b = _build([MATCHED], _recon(matched=[(MATCHED["event_id"], "decision-body-x-1-vote-0")]), holds=holds)
        assert _disp(b) == {MATCHED["event_id"]: "reviewer_hold"} and b["edges"] == []
        assert [r["note"] for r in b["repair"] if r["kind"] == "event"] == ["spot check S6: arrival not recorded"]
        with pytest.raises(BundleError, match="not an accepted event"):
            _build([MATCHED], _recon(), holds=[{"event_id": "vev-nope", "reason": "x"}])

    def test_an_inferred_roll_call_omitting_a_member_who_moved_at_that_meeting_is_doubtful(self):
        # Birch is not inferred present for this ALL, yet moves another motion at the same meeting
        ev = {**NEW, "categories": {**NEW["categories"], "aye": [_member("ALDER", inferred=True),
                                                                 _member("CEDAR", inferred=True)]},
              "attendance": {**NEW["attendance"], "roster": ["ALDER", "BIRCH", "CEDAR"]}}
        other = {**MATCHED, "event_id": "vev-body-x-1-aaaa-L90", "status": "held", "hold_reasons": ["x"],
                 "motion": {**MATCHED["motion"], "mover": "BIRCH"}}
        b = _build([ev, other], _recon(new=[ev["event_id"]]))
        assert _disp(b) == {ev["event_id"]: "attendance_doubt"} and b["edges"] == []
        seconded = {**other, "motion": {**other["motion"], "mover": None, "seconder": "BIRCH"}}
        assert _disp(_build([ev, seconded], _recon(new=[ev["event_id"]]))) == {ev["event_id"]: "attendance_doubt"}
        elsewhere = {**other, "meeting_id": MEET2}
        assert _disp(_build([ev, elsewhere], _recon(new=[ev["event_id"]]))) == {ev["event_id"]: "attached"}
        named = {**MATCHED, "categories": {**MATCHED["categories"], "absent": []}}  # named events are not inferred
        assert _disp(_build([named, other], _recon(matched=[(named["event_id"], "decision-body-x-1-vote-0")]))) \
            == {named["event_id"]: "attached"}

    def test_duplicate_or_conflicting_assignments_hold(self):
        twice = _recon(matched=[(MATCHED["event_id"], "decision-body-x-1-vote-0")]) * 2
        assert _disp(_build([MATCHED], twice)) == {MATCHED["event_id"]: "assignment_conflict"}
        both = _recon(matched=[(MATCHED["event_id"], "decision-body-x-1-vote-0")], new=[MATCHED["event_id"]])
        assert _disp(_build([MATCHED], both)) == {MATCHED["event_id"]: "assignment_conflict"}

    def test_voter_diagnostics_survive_an_earlier_hold(self):
        ev = {**NEW, "date": "2021-09-14", "meeting_id": MEET2}
        b = _build([ev], _recon())  # no target: held decision_not_matched, but Cedar's term problem is still listed
        assert _disp(b) == {ev["event_id"]: "decision_not_matched"}
        assert [(r["kind"], r["key"], r["reason"]) for r in b["repair"] if r["kind"] == "voter"] == [
            ("voter", "CEDAR", "out_of_term")]

    def test_fresh_reconciliation_failures_are_in_the_repair_list(self):
        nodes, edges = _baseline()
        nodes = nodes + [_n("decision-body-x-1-vote-1", ["Decision"], meeting_id=MEET, source_id=BODY,
                            status="carried", outcome="carried", motion_text="approve the example item",
                            ayes=["ALDER"], noes=[], decision_type="roll_call_vote")]
        edges = edges + [_e("decision-body-x-1-vote-1", MEET, "DECIDED_AT")]
        resolver, rows = _resolver()
        b = build_bundle([NEW], _recon(new=[NEW["event_id"]]), resolver, rows, nodes, edges, body_org=BODY_ORG,
                         body_name=BODY_NAME, revalidate=True)
        fresh = [r for r in b["repair"] if r["kind"] == "decision" and r.get("source") == "fresh_baseline"]
        # vote-1 is new on this baseline; vote-0 has no Part A row in this fixture, so it differs too
        assert sorted(r["decision_id"] for r in fresh) == ["decision-body-x-1-vote-0", "decision-body-x-1-vote-1"]
        assert [r["event_id"] for r in fresh if r["decision_id"].endswith("vote-1")] == [NEW["event_id"]]

    def test_two_keys_resolving_to_one_person_hold(self):
        ev = {**MATCHED, "categories": {**MATCHED["categories"], "no": [_member("DOGWOOD", 200)]}}
        b = _build([ev], _recon(matched=[(ev["event_id"], "decision-body-x-1-vote-0")]))
        assert _disp(b) == {ev["event_id"]: "person_collision"} and b["edges"] == []

    def test_matched_targets_get_the_meeting_checks_too(self):
        nodes, edges = _baseline()
        for bad in ({"meeting_date": "2020-06-10"}, {"institution_id": "org-other"}):
            wrong = [{**n, "properties": {**n["properties"], **bad}} if n["id"] == MEET else n for n in nodes]
            b = _build([MATCHED], _recon(matched=[(MATCHED["event_id"], "decision-body-x-1-vote-0")]), wrong, edges)
            assert _disp(b) == {MATCHED["event_id"]: "meeting_mismatch"}
        other_body = [{**n, "properties": {**n["properties"], "source_id": "body-y"}}
                      if n["id"].startswith("decision") else n for n in nodes]
        b = _build([MATCHED], _recon(matched=[(MATCHED["event_id"], "decision-body-x-1-vote-0")]), other_body, edges)
        assert _disp(b) == {MATCHED["event_id"]: "decision_shape"}
        two = edges + [_e("decision-body-x-1-vote-0", MEET2, "DECIDED_AT")]
        b = _build([MATCHED], _recon(matched=[(MATCHED["event_id"], "decision-body-x-1-vote-0")]), nodes, two)
        assert _disp(b) == {MATCHED["event_id"]: "decision_shape"}

    def test_repair_inventory_covers_every_unmatched_decision_and_held_event(self):
        recon = _recon(matched=[(MATCHED["event_id"], "decision-body-x-1-vote-0")])
        recon.append({"kind": "decision", "decision_id": "decision-body-x-1-vote-9", "meeting_id": MEET,
                      "status": "unmatched", "event_id": None, "candidates": [], "reason": "text_mismatch",
                      "differences": {}, "notes": []})
        ev = {**NEW, "date": "2021-09-14", "meeting_id": MEET2}
        b = _build([MATCHED, ev], recon + _recon(new=[ev["event_id"]]))
        kinds = sorted((r["kind"], r.get("decision_id") or r.get("event_id")) for r in b["repair"])
        assert kinds == [("decision", "decision-body-x-1-vote-9"), ("event", ev["event_id"]),
                         ("voter", ev["event_id"])]
        voter = [r for r in b["repair"] if r["kind"] == "voter"][0]
        assert voter["key"] == "CEDAR" and voter["nearest_term"] == "x-cedar" and voter["reason"] == "out_of_term"

    def test_decision_shape_and_meeting_checks(self):
        nodes, edges = _baseline()
        b = _build([MATCHED], _recon(matched=[(MATCHED["event_id"], "decision-body-x-1-vote-0")]), nodes, [])
        assert _disp(b) == {MATCHED["event_id"]: "decision_shape"}
        moved = [{**n, "properties": {**n["properties"], "meeting_id": MEET2}} if n["id"].startswith("decision")
                 else n for n in nodes]
        b = _build([MATCHED], _recon(matched=[(MATCHED["event_id"], "decision-body-x-1-vote-0")]), moved, edges)
        assert _disp(b) == {MATCHED["event_id"]: "decision_shape"}
        for bad in ({"meeting_date": "2020-06-10"}, {"institution_id": "org-other"}):
            wrong = [{**n, "properties": {**n["properties"], **bad}} if n["id"] == MEET else n for n in nodes]
            assert _disp(_build([NEW], _recon(new=[NEW["event_id"]]), wrong, edges)) == \
                {NEW["event_id"]: "meeting_mismatch"}
        taken = nodes + [_n(NEW["event_id"], ["Decision"])]
        assert _disp(_build([NEW], _recon(new=[NEW["event_id"]]), taken, edges)) == {NEW["event_id"]: "new_id_taken"}

    def test_revalidation_holds_changed_assignments(self):
        nodes, edges = _baseline()
        # a Decision now in the baseline with the new event's motion text: re-reconciliation pairs them
        nodes = nodes + [_n("decision-body-x-1-vote-1", ["Decision"], meeting_id=MEET, source_id=BODY,
                            status="carried", outcome="carried", motion_text="approve the example item",
                            decision_type="roll_call_vote")]
        edges = edges + [_e("decision-body-x-1-vote-1", MEET, "DECIDED_AT")]
        resolver, rows = _resolver()
        b = build_bundle([NEW], _recon(new=[NEW["event_id"]]), resolver, rows, nodes, edges, body_org=BODY_ORG,
                         body_name=BODY_NAME, revalidate=True)
        assert _disp(b) == {NEW["event_id"]: "assignment_changed"}

    def test_every_accepted_event_exactly_once_and_deterministic(self):
        recon = _recon(matched=[(MATCHED["event_id"], "decision-body-x-1-vote-0")], new=[NEW["event_id"]])
        a, b = _build([MATCHED, NEW], recon), _build([NEW, MATCHED], recon)
        assert a == b
        assert sorted(d["event_id"] for d in a["dispositions"]) == sorted([MATCHED["event_id"], NEW["event_id"]])


class TestStorable:
    def test_bundle_values_round_trip_through_planner_and_export(self, tmp_path):
        recon = _recon(matched=[(MATCHED["event_id"], "decision-body-x-1-vote-0")], new=[NEW["event_id"]])
        b = _build([MATCHED, NEW], recon)
        for row in b["nodes"] + b["edges"]:
            assert all(_neo4j_value(v) for v in row["properties"].values())
            assert _clean_props(row["properties"], keep_all=True) == row["properties"]
        write_export(tmp_path, b["nodes"], b["edges"])
        assert _read_jsonl(tmp_path / "edges.jsonl") == sorted(b["edges"], key=lambda e: (
            e["start_id"], e["type"], e["end_id"]))
        for e in _read_jsonl(tmp_path / "edges.jsonl"):
            if e["type"] == "CAST_VOTE":
                assert json.loads(e["properties"]["evidence"])["kind"] in ("named", "inferred")


class TestAccounting:
    def test_counts_and_manifest(self):
        recon = _recon(matched=[(MATCHED["event_id"], "decision-body-x-1-vote-0")], new=[NEW["event_id"]])
        b = _build([MATCHED, NEW], recon)
        acc = accounting(b)
        assert acc["by_body"][BODY] == {"attached": 2}
        assert acc["edges_by_vote"] == {"absent": 1, "aye": 5}
        assert acc["new_decisions"] == {BODY: 1} and acc["new_persons"] == 1
        assert accounting(b, expected=acc)["matches_expected"] is True
        held_all = {**acc, "by_body": {BODY: {"voter_out_of_term": 2}}}
        assert accounting(b, expected=held_all)["matches_expected"] is False


class TestCli:
    """The files: pinned inputs, the mapping batch, provisional builds, the manifest gate, determinism."""

    NOV = "novato-city-council"

    def _world(self, tmp_path, monkeypatch):
        monkeypatch.setattr(votes_bundle, "STAGING_ROOT", tmp_path)
        ledger, roster, mapping, baseline = (tmp_path / d for d in ("ledger", "roster", "mapping", "baseline"))
        for d in (ledger, roster, mapping, baseline):
            d.mkdir()
        nov, org = self.NOV, "org-novato-city-council"
        terms = [_term("n-alder", "ALDER", "2020-01-01"), _term("n-birch", "BIRCH", "2020-01-01")]
        (roster / "drafts.json").write_text(json.dumps({nov: {"body": nov, "terms": terms}}))
        items = [{"item": str(i + 1), "draft_id": t["draft_id"], "body": nov, "options": []}
                 for i, t in enumerate(terms)]
        (roster / "batch-001.json").write_text(json.dumps({"batch": "roster-001", "items": items}))
        (roster / "answers-001.txt").write_text("batch roster-001\n1 confirm\n2 confirm\n")
        filings = {"ALDER": "filing-form700-nvo-2020-alder-ann", "BIRCH": "filing-form700-nvo-2020-birch-bea"}
        persons = {"ALDER": "person-ann-alder", "BIRCH": "person-bea-birch"}
        rows = [{"item": i["item"], "draft_id": t["draft_id"], "body": nov, "key": t["key"], "member": t["member"],
                 "term_start": t["start"], "term_end": t["end"], "status": "mapped", "person_id": persons[t["key"]],
                 "provenance": [{"kind": "filing", "filing_id": filings[t["key"]]}], "alternates": [], "notes": ""}
                for i, t in zip(items, terms)]
        (mapping / "mapping.json").write_text(json.dumps({"batch": "map-001", "rows": rows}))
        meet = "meeting-novato-city-council-1"
        nodes = [_n(persons[k], ["Person"], name=k.title()) for k in persons] + [
            _n(filings[k], ["Filing"], agency_id="nvo", department="City Council", job_title="Council Member")
            for k in filings] + [_n(meet, ["Meeting"], meeting_date="2020-06-09", institution_id=org)]
        edges = [_e(filings[k], persons[k], "FILED_BY") for k in filings]
        write_export(baseline, nodes, edges)
        ev = {**NEW, "event_id": "vev-novato-city-council-1-aaaa-L40", "body": nov, "meeting_id": meet,
              "categories": {**NEW["categories"], "aye": NEW["categories"]["aye"][:2]}}
        (ledger / "events.jsonl").write_text(json.dumps(ev) + "\n")
        (ledger / "reconciliation.jsonl").write_text(json.dumps(
            {"kind": "event", "event_id": ev["event_id"], "meeting_id": meet, "status": "new",
             "proposed_id": ev["event_id"], "event_status": "expanded"}) + "\n")
        (ledger / "build.json").write_text(json.dumps({"as_of": "2026-10-14"}))
        expected = tmp_path / "expected-dispositions.json"
        expected.write_text(json.dumps({"events": 1, "by_body": {nov: {"attached": 1}}, "edges_by_vote": {"aye": 2},
                                        "new_decisions": {nov: 1}, "new_persons": 0}))
        (tmp_path / "reviewer-holds.json").write_text(json.dumps({"holds": []}))
        self.holds = ["--holds", str(tmp_path / "reviewer-holds.json")]
        args = ["--ledger", str(ledger), "--roster", str(roster), "--mapping", str(mapping), "--baseline",
                str(baseline)]
        return args, mapping, expected

    def test_batch_then_answers_then_build(self, tmp_path, monkeypatch):
        args, mapping, expected = self._world(tmp_path, monkeypatch)
        assert votes_bundle.main(["mapping-batch", *args]) == 0
        assert "Person: `person-ann-alder`" in (mapping / "batch-map-001.md").read_text()
        out = tmp_path / "bundle"
        assert votes_bundle.main(["build", *args, "--expected", str(expected), *self.holds, "--out", str(out)]) == 1  # no answers
        (mapping / "answers-map-001.txt").write_text("batch map-001\n1 confirm\n2 confirm\n")
        assert votes_bundle.main(["build", *args, "--expected", str(expected), *self.holds, "--out", str(out)]) == 0
        inputs = json.loads((out / "inputs.json").read_text())
        assert inputs["provisional"] is False and inputs["as_of"] == "2026-10-14"
        assert set(inputs["inputs"]) >= {"ledger/events.jsonl", "ledger/build.json", "mapping/answers-map-001.txt",
                                         "mapping/batch-map-001.json", "baseline/nodes.jsonl",
                                         "expected-dispositions.json"}
        assert json.loads((out / "accounting.json").read_text())["matches_expected"] is True
        assert [e["type"] for e in _read_jsonl(out / "edges.jsonl")] == ["CAST_VOTE", "CAST_VOTE", "DECIDED_AT"]
        assert votes_bundle.main(["check", *args, "--expected", str(expected), *self.holds, "--out", str(out)]) == 0

    def test_hold_everything_cannot_pass_the_manifest(self, tmp_path, monkeypatch):
        args, mapping, expected = self._world(tmp_path, monkeypatch)
        votes_bundle.main(["mapping-batch", *args])
        (mapping / "answers-map-001.txt").write_text("batch map-001\n1 reject\n2 confirm\n")
        out = tmp_path / "bundle"
        assert votes_bundle.main(["build", *args, "--expected", str(expected), *self.holds, "--out", str(out)]) == 1
        assert json.loads((out / "accounting.json").read_text())["by_body"] == {
            self.NOV: {"voter_missing_mapping": 1}}

    def test_a_changed_table_invalidates_the_answers(self, tmp_path, monkeypatch):
        args, mapping, expected = self._world(tmp_path, monkeypatch)
        votes_bundle.main(["mapping-batch", *args])
        (mapping / "answers-map-001.txt").write_text("batch map-001\n1 confirm\n2 confirm\n")
        table = json.loads((mapping / "mapping.json").read_text())
        table["rows"][0]["notes"] = "edited after review"
        (mapping / "mapping.json").write_text(json.dumps(table))
        assert votes_bundle.main(["build", *args, "--expected", str(expected), *self.holds, "--out",
                                  str(tmp_path / "bundle")]) == 1

    def test_the_manifest_is_required_and_check_fails_on_a_mismatch(self, tmp_path, monkeypatch):
        args, mapping, expected = self._world(tmp_path, monkeypatch)
        votes_bundle.main(["mapping-batch", *args])
        (mapping / "answers-map-001.txt").write_text("batch map-001\n1 confirm\n2 confirm\n")
        out = tmp_path / "bundle"
        with pytest.raises(SystemExit):
            votes_bundle.main(["build", *args, "--out", str(out)])
        assert votes_bundle.main(["build", *args, "--expected", str(expected), *self.holds, "--out", str(out)]) == 0
        wrong = tmp_path / "wrong.json"
        wrong.write_text(json.dumps({**json.loads(expected.read_text()), "edges_by_vote": {"aye": 3}}))
        assert votes_bundle.main(["check", *args, "--expected", str(wrong), *self.holds, "--out", str(out)]) == 1

    def test_provisional_build_is_marked(self, tmp_path, monkeypatch):
        args, mapping, expected = self._world(tmp_path, monkeypatch)
        votes_bundle.main(["mapping-batch", *args])
        out = tmp_path / "bundle"
        assert votes_bundle.main(["build", *args, "--expected", str(expected), *self.holds, "--out", str(out),
                                  "--provisional"]) == 0
        inputs = json.loads((out / "inputs.json").read_text())
        assert inputs["provisional"] is True and "mapping/answers-map-001.txt" not in inputs["inputs"]

    def test_out_must_be_inside_the_staging_root(self, tmp_path, monkeypatch):
        args, mapping, expected = self._world(tmp_path, monkeypatch)
        votes_bundle.main(["mapping-batch", *args])
        (mapping / "answers-map-001.txt").write_text("batch map-001\n1 confirm\n2 confirm\n")
        assert votes_bundle.main(["build", *args, "--expected", str(expected), *self.holds, "--out",
                                  str(tmp_path.parent / "elsewhere")]) == 1
        (tmp_path / "keep").mkdir()
        (tmp_path / "keep" / "x.txt").write_text("not a bundle")
        assert votes_bundle.main(["build", *args, "--expected", str(expected), *self.holds, "--out", str(tmp_path / "keep")]) == 1
        assert (tmp_path / "keep" / "x.txt").exists()


class TestSamples:
    def _bundle(self):
        evs = []
        for i in range(30):
            no = [_member("BIRCH", 110)] if i % 7 == 0 else []
            aye = [_member("ALDER", 100)] + ([] if no else [_member("BIRCH", 110)])
            evs.append(_event(f"vev-body-x-1-aaaa-L{i:03d}", MEET, "2020-06-09", aye=aye, no=no,
                              motion=f"motion {i}"))
        return evs, _build(evs, _recon(new=[e["event_id"] for e in evs]))

    def test_selection_is_seeded_and_lists_every_notable_vote(self):
        evs, b = self._bundle()
        sel = votes_bundle.select_samples(b, seed=7, n=5, notable=30)
        again = votes_bundle.select_samples(b, seed=7, n=5, notable=30)
        assert sel == again and len(sel[BODY]["random"]) == 5
        notable = {e for e in sel[BODY]["notable"]}
        assert notable == {f"vev-body-x-1-aaaa-L{i:03d}" for i in range(30) if i % 7 == 0} - set(sel[BODY]["random"])
        assert votes_bundle.select_samples(b, seed=8, n=5, notable=30)[BODY]["random"] != sel[BODY]["random"]

    def test_render_shows_excerpt_and_resolved_person(self):
        evs, b = self._bundle()
        text = "x" * 100 + "ALDER" + "x" * 5 + "BIRCH" + "x" * 400
        sel = {BODY: {"random": [evs[0]["event_id"]], "notable": []}}
        md = votes_bundle.render_samples(sel, b, {e["event_id"]: e for e in evs}, {"d" * 64: text},
                                         {"person-ann-alder": "Ann Alder", "person-bea-birch": "Bea Birch"}, seed=7,
                                         sources={"d" * 64: "/x/minutes.pdf"})
        assert "- source: /x/minutes.pdf" in md
        assert "### S1. vev-body-x-1-aaaa-L000" in md
        assert "- person-bea-birch (Bea Birch): **no** (named) — “BIRCH”" in md
        assert "Reviewer: `S1 agree` / `S1 disagree: …`" in md
