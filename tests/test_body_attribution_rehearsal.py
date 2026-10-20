"""The weekly no-revert proof's checks: each fails on exactly the breakage it names. Fictional fixtures (Lakeport)."""
from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import body_attribution_rehearsal as rh  # noqa: E402

COUNCIL, HARBOR = "org-lakeport-town-council", "org-lakeport-harbor-commission"
MOVED, CONTROL = "meeting-lakeport-town-council-11", "meeting-lakeport-town-council-10"
GUARD = {MOVED: HARBOR}


def world():
    nodes = [{"id": i, "labels": ["Meeting"], "properties": {"id": i, "institution_id": inst}}
             for i, inst in ((CONTROL, COUNCIL), (MOVED, HARBOR))]
    edges = [{"start_id": CONTROL, "type": "AT_INSTITUTION", "end_id": COUNCIL, "properties": {}},
             {"start_id": MOVED, "type": "AT_INSTITUTION", "end_id": HARBOR, "properties": {}}]
    return {"candidate": (nodes, edges), "post": copy.deepcopy((nodes, edges)),
            "capture": {"meetings": [{"meeting_id": CONTROL}]},
            "overlay": [{"merge_node": {"id": CONTROL}},
                        {"merge_edge": {"start_id": CONTROL, "type": "AT_INSTITUTION", "end_id": COUNCIL}}],
            "source_state": {"ok": True, "rows": 1, "last_good_rows": 1, "reasons": []},
            "run_status": "awaiting_publish_approval", "guard": GUARD, "control": CONTROL}


def failing(w, **extra):
    return [c["name"] for c in rh.checks(**w, **extra) if not c["ok"]]


def test_a_clean_run_passes_every_check():
    assert failing(world()) == []
    w = world()
    w["overlay"].append({"node": {"id": "agenda-item-10-1", "labels": ["AgendaItem"]}})
    assert failing(w, agenda={"ok": True}, agenda_required=True) == []


@pytest.mark.parametrize("breakage,name", [
    (lambda w: w.update(run_status="held"), "the run loaded"),
    (lambda w: w["source_state"].update(ok=False), "accepted"),
    (lambda w: w.update(capture={"meetings": []}), "accepted"),
    (lambda w: w["overlay"].pop(0), "was loaded (a MERGE row)"),
    (lambda w: w["capture"]["meetings"].append({"meeting_id": MOVED}), "no moved meeting is in the capture"),
    (lambda w: w["overlay"].append({"merge_edge": {"start_id": MOVED, "type": "AT_INSTITUTION", "end_id": COUNCIL}}),
     "no MERGE row touches a moved meeting"),
    (lambda w: w["overlay"].append({"node": {"id": "x", "labels": ["AgendaItem"]}}) or
     w["overlay"].append({"edge": {"start_id": "x", "type": "PART_OF_MEETING", "end_id": MOVED}}),
     "no create touches a moved meeting"),
    (lambda w: w["post"][0][1]["properties"].update(institution_id=COUNCIL), "node is exactly the candidate's"),
    (lambda w: w["post"][1].append({"start_id": MOVED, "type": "AT_INSTITUTION", "end_id": COUNCIL, "properties": {}}),
     "exactly one AT_INSTITUTION"),
    (lambda w: w["post"][1].append({"start_id": "x", "type": "PART_OF_MEETING", "end_id": MOVED, "properties": {}}),
     "relationship touching a moved meeting"),
])
def test_each_breakage_fails_its_own_check(breakage, name):
    w = world()
    breakage(w)
    assert any(name in f for f in failing(w)), failing(w)


def test_the_agenda_variant_fails_when_its_stage_failed_or_created_nothing():
    assert failing(world(), agenda={"ok": False, "error": "replay has no recorded response"},
                   agenda_required=True) == [
        "the agenda-items stage ran and created AgendaItems"]
    assert failing(world(), agenda={"ok": True}, agenda_required=True) == [
        "the agenda-items stage ran and created AgendaItems"]
    # the stage switched on but no result at all (a regression that skips it) fails too
    assert failing(world(), agenda=None, agenda_required=True) == ["the agenda-items stage ran and created AgendaItems"]
