"""The app proof's checks: the baked serving data and the app's own entity payloads follow the migration exactly.
Fictional fixtures (Lakeport)."""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import body_attribution_app_proof as ap  # noqa: E402

COUNCIL, HARBOR, COMMITTEES = "org-lakeport-town-council", "org-lakeport-harbor-commission", "org-shoreview-committees"
ROWS = [{"id": f"meeting-lakeport-town-council-{n}", "from": COUNCIL, "to": to, "rule": rule}
        for n, to, rule in ((10, COUNCIL, "stays"), (11, HARBOR, "move"), (12, COUNCIL, "held"))] + \
    [{"id": "meeting-shoreview-committees-1", "from": COMMITTEES, "to": COMMITTEES, "rule": "held"}]
NAMES = {HARBOR: "Lakeport Harbor Commission"}


def bake(path: Path, *, edges, nodes=()):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE nodes (id TEXT PRIMARY KEY, type TEXT NOT NULL, search_label TEXT NOT NULL, props TEXT)")
    con.execute("CREATE TABLE edges (source TEXT NOT NULL, rel TEXT NOT NULL, target TEXT NOT NULL, props TEXT)")
    for r in ROWS:
        con.execute("INSERT INTO nodes VALUES (?, 'Meeting', 'x', ?)", (r["id"], json.dumps({"title": "x"})))
    for i, typ, label in ((COUNCIL, "Organization", "Lakeport Town Council"), (HARBOR, "Organization",
                                                                                "Lakeport Harbor Commission"),
                          (COMMITTEES, "Organization", "Shoreview Committees"), *nodes):
        con.execute("INSERT OR REPLACE INTO nodes VALUES (?, ?, ?, '{}')", (i, typ, label))
    con.executemany("INSERT INTO edges VALUES (?, 'AT_INSTITUTION', ?, NULL)", edges)
    con.commit()
    con.close()
    return path


GOOD = [(r["id"], r["to"]) for r in ROWS] + [("seat-lakeport-seat-1", COUNCIL)]


def failing(results):
    return [c["name"] for c in results if not c["ok"]]


def test_a_baked_artifact_that_follows_the_map_passes(tmp_path):
    assert failing(ap.sqlite_checks(bake(tmp_path / "s.sqlite", edges=GOOD), ROWS, NAMES)) == []


@pytest.mark.parametrize("edges,nodes,name", [
    ([e for e in GOOD if e[0] != "meeting-lakeport-town-council-12"], (), f"{COUNCIL} lists exactly"),
    (GOOD + [("meeting-lakeport-town-council-11", COUNCIL)], (), f"{COUNCIL} lists exactly"),
    (GOOD + [("meeting-lakeport-town-council-11", COUNCIL)], (), "exactly one AT_INSTITUTION"),
    ([e for e in GOOD if e[0] != "meeting-shoreview-committees-1"], (), f"{COMMITTEES} lists exactly"),
    (GOOD, ((HARBOR, "Organization", HARBOR),), "is baked under its name"),
])
def test_each_departure_fails_its_own_check(tmp_path, edges, nodes, name):
    got = failing(ap.sqlite_checks(bake(tmp_path / "s.sqlite", edges=edges, nodes=nodes), ROWS, NAMES))
    assert any(name in g for g in got), got


def test_a_meeting_carrying_an_institution_name_fails(tmp_path):
    path = bake(tmp_path / "s.sqlite", edges=GOOD)
    con = sqlite3.connect(path)
    con.execute("UPDATE nodes SET props = ? WHERE id = 'meeting-lakeport-town-council-11'",
                (json.dumps({"institution_name": "Lakeport Town Council"}),))
    con.commit()
    con.close()
    assert "no moved or held meeting carries an institution_name" in failing(ap.sqlite_checks(path, ROWS, NAMES))


def test_the_bake_diff_must_be_exactly_the_planned_rows(tmp_path):
    before = bake(tmp_path / "before.sqlite", edges=[(r["id"], r["from"]) for r in ROWS])
    after = bake(tmp_path / "after.sqlite", edges=GOOD)
    planned = {"nodes_added": {}, "at_institution": [("meeting-lakeport-town-council-11", COUNCIL, HARBOR)],
               "in_jurisdiction_added": [], "template": COUNCIL}
    # the seat edge is only in `after`: an unplanned difference
    assert "the bake differs from the baseline's only by the planned rows (full rows)" in \
        failing(ap.diff_checks(before, after, planned))
    before2 = bake(tmp_path / "before2.sqlite",
                   edges=[(r["id"], r["from"]) for r in ROWS] + [("seat-lakeport-seat-1", COUNCIL)])
    assert failing(ap.diff_checks(before2, after, planned)) == []


def test_the_expected_neighborhood_comes_from_the_map_and_the_baseline_not_the_page(tmp_path):
    before = bake(tmp_path / "before.sqlite", edges=[(r["id"], r["from"]) for r in ROWS] +
                  [("seat-lakeport-seat-1", COUNCIL), ("place-lakeport", COUNCIL)],
                  nodes=(("seat-lakeport-seat-1", "Seat", "Seat 1"), ("place-lakeport", "Place", "Lakeport")))
    assert ap.expected_neighborhood(before, COUNCIL, {"meeting-lakeport-town-council-10"}) == [
        ("Meeting", "meeting-lakeport-town-council-10"), ("Seat", "seat-lakeport-seat-1")]


def test_the_org_page_preview_is_exactly_the_first_forty_expected_peers():
    expected = [("Meeting", f"meeting-x-{n:03d}") for n in range(100)] + [("Seat", "seat-1")]
    links = lambda ids: "".join(f'<a href="/meeting/{i.removeprefix("meeting-")}">' for i in ids)  # noqa: E731
    first = sorted(expected)[:40]
    payload = {"neighbors": [{"id": i, "type": t} for t, i in first]}
    assert failing(ap.preview_checks("org-x", payload, expected, links(i for _, i in first))) == []
    wrong = {"neighbors": [{"id": i, "type": t} for t, i in sorted(expected)[1:41]]}
    assert failing(ap.preview_checks("org-x", wrong, expected, links(i for _, i in first))) == [
        "org-x's page previews exactly the first 40 expected peers"]
    seats = {"neighbors": [{"id": f"seat-{n}", "type": "Seat"} for n in range(40)]}  # a page of other peers
    assert "org-x's page previews exactly the first 40 expected peers" in failing(
        ap.preview_checks("org-x", seats, expected, ""))
    assert failing(ap.preview_checks("org-x", payload, expected, links(i for _, i in first[:39]))) == [
        "org-x's rendered page links exactly the previewed meetings"]


def test_a_meeting_page_names_its_body():
    payload = {"neighbors": [{"id": HARBOR, "type": "Organization", "label": "Lakeport Harbor Commission"}]}
    assert failing(ap.meeting_checks("m", payload, "<h1>Lakeport Harbor Commission</h1>", HARBOR,
                                     "Lakeport Harbor Commission")) == []
    other = {"neighbors": [{"id": COUNCIL, "type": "Organization", "label": "Lakeport Town Council"}]}
    assert len(failing(ap.meeting_checks("m", other, "<h1>Lakeport Town Council</h1>", HARBOR,
                                         "Lakeport Harbor Commission"))) == 2


def test_a_decision_of_a_moved_meeting_shows_its_body_not_the_old_institution():
    good = {"neighbors": [{"id": HARBOR, "type": "Organization"}, {"id": "m", "type": "Meeting"}]}
    assert failing(ap.decision_checks("d", good, HARBOR, COUNCIL)) == []
    stale = {"neighbors": [{"id": COUNCIL, "type": "Organization"}]}
    assert len(failing(ap.decision_checks("d", stale, HARBOR, COUNCIL))) == 1


def test_bakes_need_a_read_only_overlay_and_prove_refuses_bakes_of_another_candidate(tmp_path, monkeypatch):
    monkeypatch.setattr(ap.ba, "STAGING_ROOT", tmp_path)
    attach = tmp_path / "attach"
    attach.mkdir()
    (attach / "nodes.jsonl").write_text("")
    plan = tmp_path / "plan"
    (plan / "candidate").mkdir(parents=True)
    for n in ("nodes.jsonl", "edges.jsonl"):
        (plan / "candidate" / n).write_text("")
    (plan / "plan-report.json").write_text(json.dumps({"baseline": {"dir": str(plan / "candidate"),
                                                                    "sha256": {}}, "candidate_sha256": {}}))
    with pytest.raises(ap.ba.AttributionError, match="read-only"):
        ap.run_bakes(plan, attach, tmp_path / "bake")
    bakedir = tmp_path / "bake2"
    bakedir.mkdir()
    (bakedir / "bake-inputs.json").write_text(json.dumps({"candidate": {"nodes.jsonl": "x"}, "baseline": {},
                                                          "attach_dir": str(attach), "attach": {}}))
    with pytest.raises(ap.ba.AttributionError, match="this plan's"):
        ap.prove(plan, tmp_path, bakedir, "http://127.0.0.1:1")
