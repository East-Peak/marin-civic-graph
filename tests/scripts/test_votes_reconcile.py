"""Votes Part A, increment e: every existing Decision accounted for against the new vote events,
both ways, by evidence (meeting, motion wording, mover, seconder) — never by positional index."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from votes_reconcile import check_reconciliation, reconcile  # noqa: E402

NOV = "novato-city-council"
BOS = "marin-county-bos"


def _dec(i, meeting, text, mover="ALDER", seconder="BIRCH", ayes=("ALDER", "BIRCH", "CEDAR"), noes=(),
         recused=(), outcome="carried", tally=None, source=NOV):
    return {"id": f"decision-{meeting.removeprefix('meeting-')}-vote-{i}", "meeting_id": meeting,
            "source_id": source, "motion_text": text, "mover": mover, "seconder": seconder, "ayes": list(ayes),
            "noes": list(noes), "recused": list(recused), "absent": [], "outcome": outcome, "tally": tally}


def _ev(eid, meeting, text, mover="ALDER", seconder="BIRCH", ayes=("ALDER", "BIRCH", "CEDAR"), noes=(),
        recused=(), absent=(), status="named", outcome="carried", tally=None, body=NOV, sentinel=None):
    def names(xs, inferred=False):
        return [{"name": x, "raw": None if inferred else x, "span": None, "inferred": inferred} for x in xs]
    return {"event_id": eid, "meeting_id": meeting, "body": body, "status": status,
            "motion": {"text": text, "mover": mover, "seconder": seconder, "kind": "main"},
            "categories": {"aye": names(ayes, status == "expanded"), "no": names(noes), "abstain": [],
                           "recused": names(recused), "absent": names(absent)},
            "sentinels": [{"token": sentinel, "category": "aye"}] if sentinel else [],
            "outcome": outcome, "tally": {"printed": tally} if tally else None}


M = "meeting-novato-city-council-1"


def _by(rows, key, value):
    return [r for r in rows if r.get(key) == value]


def test_an_exact_match():
    rows = reconcile([_dec(0, M, "approve the Final Agenda.")], [_ev("vev-1", M, "approve the Final Agenda.")], {})
    [d] = _by(rows, "kind", "decision")
    assert (d["status"], d["event_id"]) == ("matched", "vev-1")
    assert _by(rows, "kind", "event") == []


def test_a_truncated_decision_text_matches_by_prefix():
    d = _dec(0, M, "determine that the need to take action arose subsequent to the agenda being posted to add the "
                   "additional item to today's", ayes=["ALL"], source=BOS)
    e = _ev("vev-1", M, "determine that the need to take action arose subsequent to the agenda being posted to add "
                        "the additional item to today's agenda. related budget adjustments.", status="expanded",
            ayes=("ALDER", "BIRCH", "CEDAR", "DOGWOOD", "ELM"), body=BOS, sentinel="ALL")
    [row] = _by(reconcile([d], [e], {}), "kind", "decision")
    assert row["status"] == "matched"


def test_all_versus_an_expanded_set_and_none_versus_empty_are_not_conflicts():
    d = _dec(0, M, "approve it.", ayes=["ALL"], noes=["NONE."], source=BOS)
    e = _ev("vev-1", M, "approve it.", status="expanded", ayes=("ALDER", "BIRCH"), body=BOS, sentinel="ALL")
    [row] = _by(reconcile([d], [e], {}), "kind", "decision")
    assert row["status"] == "matched" and row["differences"] == {}


def test_all_versus_a_named_set_is_a_conflict():
    d = _dec(0, M, "approve it.", ayes=["ALL"], source=BOS)
    e = _ev("vev-1", M, "approve it.", ayes=("ALDER", "BIRCH"), absent=("CEDAR",), body=BOS)
    [row] = _by(reconcile([d], [e], {}), "kind", "decision")
    assert row["status"] == "conflicting" and "aye" in row["differences"]


def test_merged_names_in_an_old_array_are_noted_not_conflicts():
    d = _dec(0, M, "approve it.", ayes=["ALDER", "BIRCH CEDAR"])
    e = _ev("vev-1", M, "approve it.")
    [row] = _by(reconcile([d], [e], {}), "kind", "decision")
    assert row["status"] == "matched" and "decision_array_merged_names" in row["notes"]


def test_a_recusal_only_difference_is_a_conflict():
    d = _dec(0, M, "approve it.", ayes=["ALDER", "BIRCH"], recused=[])
    e = _ev("vev-1", M, "approve it.", ayes=("ALDER", "BIRCH"), recused=("CEDAR",))
    [row] = _by(reconcile([d], [e], {}), "kind", "decision")
    assert row["status"] == "conflicting" and set(row["differences"]) == {"recused"}


def test_fields_the_old_pipeline_never_recorded_are_not_compared():
    d = _dec(0, M, "approve it.", ayes=["ALL"], source=BOS)
    e = _ev("vev-1", M, "approve it.", status="expanded", ayes=("ALDER", "BIRCH"), absent=("CEDAR",), body=BOS,
            sentinel="ALL")
    [row] = _by(reconcile([d], [e], {}), "kind", "decision")
    assert row["status"] == "matched" and "absent" not in row["differences"]


def test_outcome_tally_and_mover_differences_are_conflicts():
    d = _dec(0, M, "approve it.", outcome="failed", tally="3-0", mover="CEDAR")
    e = _ev("vev-1", M, "approve it.", tally="2-1", noes=("CEDAR",), ayes=("ALDER", "BIRCH"))
    [row] = _by(reconcile([d], [e], {}), "kind", "decision")
    assert row["status"] == "conflicting"
    assert {"outcome", "tally", "mover"} <= set(row["differences"])


def test_duplicate_decisions_for_one_event_are_ambiguous_and_the_event_is_not_new():
    ds = [_dec(0, M, "approve it."), _dec(1, M, "approve it.")]
    rows = reconcile(ds, [_ev("vev-1", M, "approve it.")], {})
    assert [r["status"] for r in _by(rows, "kind", "decision")] == ["ambiguous", "ambiguous"]
    assert all(r["candidates"] == ["vev-1"] for r in _by(rows, "kind", "decision"))
    assert _by(rows, "kind", "event") == []


def test_repeated_identical_motions_are_told_apart_by_mover_or_held():
    ds = [_dec(0, M, "approve it.", mover="ALDER"), _dec(1, M, "approve it.", mover="CEDAR")]
    es = [_ev("vev-1", M, "approve it.", mover="ALDER"), _ev("vev-2", M, "approve it.", mover="CEDAR")]
    rows = _by(reconcile(ds, es, {}), "kind", "decision")
    assert [(r["status"], r["event_id"]) for r in rows] == [("matched", "vev-1"), ("matched", "vev-2")]
    ds2 = [_dec(0, M, "approve it."), _dec(1, M, "approve it.")]
    es2 = [_ev("vev-1", M, "approve it."), _ev("vev-2", M, "approve it.")]
    rows2 = _by(reconcile(ds2, es2, {}), "kind", "decision")
    assert [r["status"] for r in rows2] == ["ambiguous", "ambiguous"]


def test_an_event_with_no_decision_is_new_with_its_stable_id():
    rows = reconcile([], [_ev("vev-x-1-abcdabcd-L12", M, "approve it.")], {})
    [e] = _by(rows, "kind", "event")
    assert (e["status"], e["proposed_id"]) == ("new", "vev-x-1-abcdabcd-L12")


def test_unmatched_reasons():
    ds = [_dec(0, M, "approve it."), _dec(0, "meeting-novato-city-council-2", "approve it."),
          _dec(0, "meeting-novato-city-council-3", "approve it."),
          _dec(0, "meeting-novato-city-council-4", "approve it.")]
    es = [_ev("vev-1", M, "something else entirely different.")]
    gaps = {"meeting-novato-city-council-2": "document_of_other_meeting:meeting-novato-city-council-9",
            "meeting-novato-city-council-3": "out_of_window"}
    rows = {r["decision_id"]: r for r in _by(reconcile(ds, es, gaps), "kind", "decision")}
    assert rows[ds[0]["id"]]["reason"] == "text_mismatch"
    assert rows[ds[1]["id"]]["reason"] == "document_of_other_meeting:meeting-novato-city-council-9"
    assert rows[ds[2]["id"]]["reason"] == "out_of_window"
    assert rows[ds[3]["id"]]["reason"] == "no_event_in_meeting"


def test_the_check_requires_every_decision_once():
    ds = [_dec(0, M, "approve it."), _dec(1, M, "deny it.")]
    rows = reconcile(ds, [_ev("vev-1", M, "approve it.")], {})
    assert check_reconciliation(ds, [_ev("vev-1", M, "approve it.")], rows) == []
    assert check_reconciliation(ds, [], rows[:1])
    assert check_reconciliation(ds, [_ev("vev-1", M, "approve it.")], rows + rows[:1])


def test_deterministic():
    ds = [_dec(1, M, "deny it."), _dec(0, M, "approve it.")]
    es = [_ev("vev-2", M, "deny it."), _ev("vev-1", M, "approve it.")]
    assert reconcile(ds, es, {}) == reconcile(list(reversed(ds)), list(reversed(es)), {})
