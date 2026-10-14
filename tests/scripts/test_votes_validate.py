"""Votes Part A: combined-evidence validation of every accepted event (goal Design 4).

The validator trusts nothing the event says about its evidence: it re-derives each category's region
from the raw text with its own label grammar, checks every named member lies in the region of their
own category, and re-runs the whole attendance trace to re-derive every inferred aye."""
import ast
import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from votes_attendance import resolve  # noqa: E402
from votes_blocks import parse_document  # noqa: E402
from votes_text import CanonicalText  # noqa: E402
from votes_validate import validate_document  # noqa: E402

BOS = "marin-county-bos"
ROLL = "Present: Supervisor Alder; Supervisor Birch; Supervisor Cedar; Supervisor Dogwood; Supervisor Elm"
SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def _world(lines, body=BOS):
    ct = CanonicalText.from_lines(lines)
    events = parse_document(ct, body=body, meeting_id="meeting-x-1", doc_sha256="d" * 64)
    out, _ = resolve(ct, body=body, events=events)
    return ct, out


GOAL_VECTOR = ["Roll Call", ROLL, "1.", "Item.", "M/s Supervisor Alder - Supervisor Birch to approve.",
               "AYES: ALL", "ABSENT: Supervisor Dogwood", "RECUSED: Supervisor Elm"]


def test_the_validator_imports_neither_the_parser_nor_the_scanner():
    tree = ast.parse((SCRIPTS / "votes_validate.py").read_text())
    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    imported |= {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert not imported & {"votes_blocks", "votes_candidates"}


def test_a_correct_expanded_event_passes():
    ct, evs = _world(GOAL_VECTOR)
    assert evs[0]["status"] == "expanded"
    assert validate_document(ct, BOS, evs) == []


def test_the_goals_swap_vector_fails_names_swapped():
    ct, evs = _world(GOAL_VECTOR)
    bad = copy.deepcopy(evs)
    cats = bad[0]["categories"]
    cats["absent"], cats["recused"] = cats["recused"], cats["absent"]
    assert validate_document(ct, BOS, bad)


def test_the_goals_swap_vector_fails_names_and_spans_swapped():
    ct, evs = _world(GOAL_VECTOR)
    bad = copy.deepcopy(evs)
    cats, spans = bad[0]["categories"], bad[0]["category_spans"]
    cats["absent"], cats["recused"] = cats["recused"], cats["absent"]
    spans["absent"], spans["recused"] = spans["recused"], spans["absent"]
    assert validate_document(ct, BOS, bad)


def test_overlapping_category_spans_fail():
    ct, evs = _world(GOAL_VECTOR)
    bad = copy.deepcopy(evs)
    bad[0]["category_spans"]["absent"] = dict(bad[0]["category_spans"]["absent"])
    bad[0]["category_spans"]["absent"]["end"] = bad[0]["category_spans"]["recused"]["end"]
    assert validate_document(ct, BOS, bad)


def test_an_inferred_aye_the_trace_does_not_derive_fails():
    ct, evs = _world(GOAL_VECTOR)
    bad = copy.deepcopy(evs)
    bad[0]["categories"]["aye"].append({"name": "DOGWOOD", "raw": None, "span": None, "inferred": True})
    assert validate_document(ct, BOS, bad)


def test_omitted_attendance_evidence_fails():
    lines = ["Roll Call", ROLL, "(Supervisor Elm absent at 10:00 a.m.)", "1.", "Item.",
             "M/s Supervisor Alder - Supervisor Birch to approve.", "AYES: ALL"]
    ct, evs = _world(lines)
    assert evs[0]["status"] == "expanded" and validate_document(ct, BOS, evs) == []
    bad = copy.deepcopy(evs)
    bad[0]["attendance"]["evidence"] = bad[0]["attendance"]["evidence"][:1]  # drop the departure
    assert validate_document(ct, BOS, bad)


def test_an_expanded_event_whose_state_is_uncertain_fails():
    lines = ["Roll Call", ROLL, "The President advised Supervisor Elm would rejoin the meeting soon.", "1.", "Item.",
             "M/s Supervisor Alder - Supervisor Birch to approve.", "AYES: ALL"]
    ct, evs = _world(lines)
    assert evs[0]["status"] == "held"
    forged = copy.deepcopy(evs)
    forged[0]["status"] = "expanded"
    forged[0]["hold_reasons"] = []
    forged[0]["categories"]["aye"] = [{"name": n, "raw": None, "span": None, "inferred": True}
                                      for n in ["ALDER", "BIRCH", "CEDAR", "DOGWOOD", "ELM"]]
    assert validate_document(ct, BOS, forged)


def test_a_sentinel_that_is_not_in_the_aye_region_fails():
    ct, evs = _world(GOAL_VECTOR)
    bad = copy.deepcopy(evs)
    bad[0]["sentinels"][0]["span"] = bad[0]["category_spans"]["absent"]
    assert validate_document(ct, BOS, bad)


def test_named_events_are_checked_too():
    lines = ["Roll Call", ROLL, "1.", "Item.", "M/s Supervisor Alder - Supervisor Birch to approve.",
             "Vote: Motion carried 3-2", "AYES: Supervisor Alder, Supervisor Birch, Supervisor Cedar",
             "NOES: Supervisor Dogwood, Supervisor Elm"]
    ct, evs = _world(lines)
    assert evs[0]["status"] == "named" and validate_document(ct, BOS, evs) == []
    bad = copy.deepcopy(evs)
    bad[0]["categories"]["aye"][0], bad[0]["categories"]["no"][0] = (bad[0]["categories"]["no"][0],
                                                                    bad[0]["categories"]["aye"][0])
    assert validate_document(ct, BOS, bad)


def test_a_name_key_that_does_not_match_its_text_fails():
    lines = ["Roll Call", ROLL, "1.", "Item.", "M/s Supervisor Alder - Supervisor Birch to approve.",
             "Vote: Motion carried 3-2", "AYES: Supervisor Alder, Supervisor Birch, Supervisor Cedar",
             "NOES: Supervisor Dogwood, Supervisor Elm"]
    ct, evs = _world(lines)
    bad = copy.deepcopy(evs)
    bad[0]["categories"]["aye"][0]["name"] = "FIR"
    assert validate_document(ct, BOS, bad)


def test_ayes_all_without_a_colon_validates():
    lines = ["Roll Call", ROLL, "1.", "Item.", "M/s Supervisor Alder - Supervisor Birch to approve.",
             "Thereafter, the vote on the pending motion was AYES ALL"]
    ct, evs = _world(lines)
    assert evs[0]["status"] == "expanded" and validate_document(ct, BOS, evs) == []


def test_a_deleted_category_member_fails_even_with_the_name_inferred_instead():
    lines = ["Roll Call", ROLL, "1.", "Item.", "M/s Supervisor Alder - Supervisor Birch to approve.",
             "AYES: ALL", "ABSENT: Supervisor Elm"]
    ct, evs = _world(lines)
    bad = copy.deepcopy(evs)
    bad[0]["categories"]["absent"] = []
    bad[0]["categories"]["aye"].append({"name": "ELM", "raw": None, "span": None, "inferred": True})
    assert validate_document(ct, BOS, bad)


def test_a_fabricated_recusal_fails():
    ct, evs = _world(["Roll Call", ROLL, "1.", "Item.", "M/s Supervisor Alder - Supervisor Birch to approve.",
                      "AYES: ALL"])
    bad = copy.deepcopy(evs)
    bad[0]["item_exceptions"] = [{"name": "ELM", "kind": "recused", "span": bad[0]["motion"]["span"]}]
    bad[0]["categories"]["aye"] = [n for n in bad[0]["categories"]["aye"] if n["name"] != "ELM"]
    assert validate_document(ct, BOS, bad)


def test_a_consumed_span_hiding_a_departure_fails():
    lines = ["Roll Call", ROLL, "(Supervisor Elm absent at 10:00 a.m.)", "1.", "Item.",
             "M/s Supervisor Alder - Supervisor Birch to approve.", "AYES: ALL"]
    ct, evs = _world(lines)
    bad = copy.deepcopy(evs)
    dep = ct.text.index("(Supervisor Elm absent")
    bad[0]["consumed"].append(ct.locate(dep, dep + len("(Supervisor Elm absent at 10:00 a.m.)")))
    bad[0]["categories"]["aye"].append({"name": "ELM", "raw": None, "span": None, "inferred": True})
    bad[0]["attendance"]["evidence"] = bad[0]["attendance"]["evidence"][:1]
    assert validate_document(ct, BOS, bad)


def test_held_events_are_not_validated_as_accepted():
    lines = ["1.", "Item.", "AYES: ALDER"]
    ct, evs = _world(lines)
    assert evs[0]["status"] == "held" and validate_document(ct, BOS, evs) == []
