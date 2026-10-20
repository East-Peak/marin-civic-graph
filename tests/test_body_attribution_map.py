"""Body attribution, increment (a): every combined-capture Meeting is mapped to the body that held it, or held.

The map is drawn from evidence only (the Meeting's category, its title where that contradicts), never guessed.
Fictional fixtures (Lakeport).
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import body_attribution as ba  # noqa: E402

COUNCIL = "org-lakeport-town-council"
COMMITTEES = "org-shoreview-committees"

BODIES = {
    "sources": {
        COUNCIL: {
            "own_category": "Town Council",
            "own_aliases": ["town council"],
            "other_aliases": {},
            "bodies": [
                {"category": "Harbor Commission", "institution_id": "org-lakeport-harbor-commission",
                 "name": "Lakeport Harbor Commission", "jurisdiction_id": "place-lakeport",
                 "aliases": ["harbor commission"], "source": "category label"},
                {"category": "Water District No. 1 Board", "institution_id": "org-lakeport-water-district-no-1",
                 "name": "Lakeport Water District No. 1", "jurisdiction_id": "place-lakeport",
                 "aliases": ["water district no. 1", "board of directors of water district"],
                 "source": "a subsidiary district (fictional filing)"},
                {"category": "Trail Pedestrian Advisory Committee (TPAC)",
                 "institution_id": "org-lakeport-trail-pedestrian-advisory-committee",
                 "name": "Lakeport Trail Pedestrian Advisory Committee", "jurisdiction_id": "place-lakeport",
                 "aliases": ["trail pedestrian advisory committee", "tpac"], "source": "category label"},
            ],
        },
        COMMITTEES: {
            "own_category": None,
            "own_aliases": [],
            "other_aliases": {"Shoreview City Council": ["city council"],
                              "Shoreview Ferry & Dock Committee": ["ferry & dock committee"]},
            "bodies": [
                {"category": "Planning Commission", "institution_id": "org-shoreview-planning-commission",
                 "name": "Shoreview Planning Commission", "jurisdiction_id": "place-shoreview",
                 "aliases": ["planning commission", "plannig commission"], "source": "category label"},
                {"category": "Harbor & Mobility Committee", "institution_id": "org-shoreview-harbor-mobility-committee",
                 "name": "Shoreview Harbor & Mobility Committee", "jurisdiction_id": "place-shoreview",
                 "aliases": ["harbor & mobility committee", "harbor and mobility committee"],
                 "source": "category label"},
            ],
        },
    }
}


def meeting(mid, inst, category, title, date="2023-02-01"):
    return {"id": mid, "labels": ["Meeting"], "properties": {
        "id": mid, "institution_id": inst, "category": category, "title": title, "meeting_date": date}}


@pytest.fixture
def bodies():
    return ba.Bodies.from_dict(BODIES)


# --- the classifier --------------------------------------------------------------------------------------------

@pytest.mark.parametrize("category,title,rule,to", [
    ("Harbor Commission", "Agenda for the March 3 meeting of the Harbor Commission", "move",
     "org-lakeport-harbor-commission"),
    ("Water District No. 1 Board", "Notice of Cancellation of the meeting of the Board of Directors of Water "
     "District No. 1", "move", "org-lakeport-water-district-no-1"),
    ("Water District No. 1 Board", "The agenda for the Water District No. 1 Board special meeting (held BEFORE the "
     "Council meeting)", "move", "org-lakeport-water-district-no-1"),
    ("Harbor Commission", "Notice is hereby given that the April meeting has been cancelled.", "move",
     "org-lakeport-harbor-commission"),
    ("Town Council", "The agenda for the May 4 Town Council regular meeting", "stays", COUNCIL),
    ("Town Council", "The agenda for the Town Council Special Meeting for Harbor Commission Interviews", "stays",
     COUNCIL),
])
def test_category_decides_when_the_title_agrees_or_is_silent(bodies, category, title, rule, to):
    verdict = bodies.classify(meeting("m1", COUNCIL, category, title)["properties"])
    assert (verdict.rule, verdict.to) == (rule, to)


@pytest.mark.parametrize("inst,category,title,reason", [
    (COUNCIL, "Harbor Commission", "The Agenda for the Special Joint Meeting / Ethics Training for the Lakeport Town "
     "Council/Water District No. 1 Board, and all Town Boards", "joint"),
    (COUNCIL, "Town Council", "Agenda for the January Joint Special Meeting - Town Council/Water District No. 1 "
     "Board Workshop", "joint"),
    (COUNCIL, "Trail Pedestrian Advisory Committee (TPAC)", "Agenda and packet for the Town Council Special "
     "Meeting for TPAC Interviews", "title names another body"),
    (COMMITTEES, "Harbor & Mobility Committee", "Ferry & Dock Committee Regular Meeting Agenda (PDF)",
     "title names another body"),
    (COUNCIL, "Library Board", "Library Board Agenda", "unknown category"),
    (COUNCIL, None, "Harbor Commission Agenda", "missing category"),
    (COUNCIL, "", "Harbor Commission Agenda", "missing category"),
])
def test_ambiguous_meetings_are_held_never_guessed(bodies, inst, category, title, reason):
    verdict = bodies.classify(meeting("m1", inst, category, title)["properties"])
    assert verdict.rule == "held"
    assert verdict.to == inst  # a held meeting keeps its current attribution
    assert reason in verdict.reason


def test_alias_matching_ignores_ampersands_case_and_word_fragments(bodies):
    props = meeting("m1", COMMITTEES, "Harbor & Mobility Committee", "HARBOR AND MOBILITY COMMITTEE agenda")["properties"]
    assert bodies.classify(props).rule == "move"
    # "council" inside another word or body never counts as the town council
    props = meeting("m2", COUNCIL, "Harbor Commission", "Harbor Commission agenda (Councilmember liaison)")["properties"]
    assert bodies.classify(props).rule == "move"


def test_a_meeting_of_another_institution_is_refused(bodies):
    with pytest.raises(ba.AttributionError, match="org-elsewhere"):
        bodies.classify(meeting("m1", "org-elsewhere", "Harbor Commission", "x")["properties"])


# --- the registry ---------------------------------------------------------------------------------------------

def test_a_body_without_a_source_citation_or_jurisdiction_is_refused():
    broken = json.loads(json.dumps(BODIES))
    del broken["sources"][COUNCIL]["bodies"][0]["source"]
    with pytest.raises(ba.AttributionError, match="source"):
        ba.Bodies.from_dict(broken)
    broken = json.loads(json.dumps(BODIES))
    broken["sources"][COUNCIL]["bodies"][0]["jurisdiction_id"] = "lakeport"
    with pytest.raises(ba.AttributionError, match="jurisdiction_id"):
        ba.Bodies.from_dict(broken)


def test_an_institution_id_off_convention_is_refused():
    broken = json.loads(json.dumps(BODIES))
    broken["sources"][COUNCIL]["bodies"][0]["institution_id"] = "harbor-commission"
    with pytest.raises(ba.AttributionError, match="org-"):
        ba.Bodies.from_dict(broken)


def test_the_real_registry_loads_and_names_every_category_once():
    real = ba.Bodies.load(REPO / "registry" / "body-attribution.yaml")
    for source in real.sources.values():
        cats = [b["category"] for b in source["bodies"]]
        assert len(cats) == len(set(cats))
        assert all(b["jurisdiction_id"].startswith("place-") and b["source"] for b in source["bodies"])


# --- near-duplicates ----------------------------------------------------------------------------------------------

def test_reuse_an_existing_node_but_refuse_a_near_duplicate(bodies):
    existing = {"org-lakeport-harbor-commission": "Lakeport Harbor Commission"}
    assert bodies.new_institutions(existing) == ["org-lakeport-trail-pedestrian-advisory-committee",
                                                 "org-lakeport-water-district-no-1",
                                                 "org-shoreview-harbor-mobility-committee",
                                                 "org-shoreview-planning-commission"]
    for near in ({"org-lakeport-water-district-no-1-board": "x"},          # an id that extends a new one
                 {"org-lakeport-water-district": "x"},                     # an id a new one extends
                 {"org-lakeport_water_district_no_1": "x"},                # punctuation only
                 {"org-other-id": "Lakeport Water District No. 1"}):       # same name, other id
        with pytest.raises(ba.AttributionError, match="near-duplicate"):
            bodies.new_institutions(near)


# --- the map ------------------------------------------------------------------------------------------------------

def _nodes():
    return [
        meeting("meeting-lakeport-town-council-10", COUNCIL, "Town Council", "Town Council regular meeting"),
        meeting("meeting-lakeport-town-council-11", COUNCIL, "Harbor Commission", "Harbor Commission agenda"),
        meeting("meeting-lakeport-town-council-12", COUNCIL, "Harbor Commission", "Special Joint Meeting of all "
                "Town Boards"),
        meeting("meeting-shoreview-committees-1", COMMITTEES, "Planning Commission", "Plannig Commission Agenda"),
        meeting("meeting-elsewhere-1", "org-elsewhere", "Harbor Commission", "Harbor Commission agenda"),
        {"id": "org-lakeport-town-council", "labels": ["Government", "Organization"], "properties": {
            "id": COUNCIL, "name": "Lakeport Town Council"}},
        {"id": "org-shoreview-planning-commission", "labels": ["Government", "Organization"], "properties": {
            "id": "org-shoreview-planning-commission", "name": "org-shoreview-planning-commission"}},
    ]


def test_map_covers_exactly_the_source_institutions_meetings(bodies):
    result = ba.build_map(_nodes(), bodies)
    assert [r["id"] for r in result.rows] == ["meeting-lakeport-town-council-10", "meeting-lakeport-town-council-11",
                                              "meeting-lakeport-town-council-12", "meeting-shoreview-committees-1"]
    by_id = {r["id"]: r for r in result.rows}
    assert by_id["meeting-lakeport-town-council-11"] | {} == {
        "id": "meeting-lakeport-town-council-11", "category": "Harbor Commission", "title": "Harbor Commission agenda",
        "meeting_date": "2023-02-01", "from": COUNCIL, "to": "org-lakeport-harbor-commission", "rule": "move",
        "reason": "category Harbor Commission"}
    assert by_id["meeting-lakeport-town-council-12"]["rule"] == "held"
    assert by_id["meeting-shoreview-committees-1"]["to"] == "org-shoreview-planning-commission"
    assert result.counts == {
        "before": {COUNCIL: 3, COMMITTEES: 1},
        "after": {COUNCIL: 2, "org-lakeport-harbor-commission": 1, "org-shoreview-planning-commission": 1},
        "rules": {"held": 1, "move": 2, "stays": 1},
        "total": 4,
    }
    assert result.new_institutions == ["org-lakeport-harbor-commission", "org-lakeport-trail-pedestrian-advisory-committee",
                                       "org-lakeport-water-district-no-1", "org-shoreview-harbor-mobility-committee"]
    assert result.reused_institutions == ["org-shoreview-planning-commission"]


def test_map_cli_writes_a_deterministic_reviewed_map_with_hashes(tmp_path):
    export = tmp_path / "export"
    export.mkdir()
    (export / "nodes.jsonl").write_text("".join(json.dumps(n) + "\n" for n in _nodes()))
    (export / "edges.jsonl").write_text("")
    registry = tmp_path / "bodies.yaml"
    registry.write_text(yaml.safe_dump(BODIES))
    outs = []
    for name in ("one", "two"):
        out = tmp_path / "staging" / name
        assert ba.main(["map", "--export", str(export), "--bodies", str(registry), "--out", str(out),
                        "--staging-root", str(tmp_path / "staging")]) == 0
        outs.append(out)
    for name in ("map.jsonl", "held.jsonl", "summary.json", "report.md"):
        assert (outs[0] / name).read_bytes() == (outs[1] / name).read_bytes()
    summary = json.loads((outs[0] / "summary.json").read_text())
    assert summary["export"]["sha256"] == {
        n: hashlib.sha256((export / n).read_bytes()).hexdigest() for n in ("nodes.jsonl", "edges.jsonl")}
    assert summary["map_sha256"] == hashlib.sha256((outs[0] / "map.jsonl").read_bytes()).hexdigest()
    assert summary["bodies_sha256"] == hashlib.sha256(registry.read_bytes()).hexdigest()
    held = [json.loads(x) for x in (outs[0] / "held.jsonl").read_text().splitlines()]
    assert [h["id"] for h in held] == ["meeting-lakeport-town-council-12"]
    report = (outs[0] / "report.md").read_text()
    assert "meeting-lakeport-town-council-12" in report and "joint" in report
    assert "Lakeport Water District No. 1" in report and "a subsidiary district (fictional filing)" in report


def test_map_cli_refuses_outside_staging_or_into_a_nonempty_dir(tmp_path):
    export = tmp_path / "export"
    export.mkdir()
    (export / "nodes.jsonl").write_text("")
    (export / "edges.jsonl").write_text("")
    registry = tmp_path / "bodies.yaml"
    registry.write_text(yaml.safe_dump(BODIES))
    args = ["map", "--export", str(export), "--bodies", str(registry), "--staging-root", str(tmp_path / "staging")]
    assert ba.main(args + ["--out", str(tmp_path / "elsewhere")]) == 2
    full = tmp_path / "staging" / "full"
    full.mkdir(parents=True)
    (full / "x").write_text("")
    assert ba.main(args + ["--out", str(full)]) == 2
