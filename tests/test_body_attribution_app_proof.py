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
    after = bake(tmp_path / "after.sqlite", edges=GOOD + [])
    planned = {"nodes_added": [], "at_institution": [("meeting-lakeport-town-council-11", COUNCIL, HARBOR)],
               "in_jurisdiction_added": []}
    # the seat edge is in both? no: only in `after`, so it is an unplanned difference
    assert failing(ap.diff_checks(before, after, planned)) == ["the bake differs from the baseline's only by the planned rows"]
    before2 = bake(tmp_path / "before2.sqlite", edges=[(r["id"], r["from"]) for r in ROWS] + [("seat-lakeport-seat-1", COUNCIL)])
    assert failing(ap.diff_checks(before2, after, planned)) == []


def test_the_org_page_preview_is_the_first_forty_of_exactly_the_expected_meetings():
    expected = {f"meeting-x-{n:03d}" for n in range(100)}
    payload = {"neighbors": [{"id": i, "type": "Meeting"} for i in sorted(expected)[:40]]}
    assert failing(ap.preview_checks("org-x", payload, expected)) == []
    wrong = {"neighbors": [{"id": i, "type": "Meeting"} for i in sorted(expected)[1:41]]}
    assert failing(ap.preview_checks("org-x", wrong, expected)) == ["org-x's page previews the first 40 expected meetings"]
    small = {"neighbors": [{"id": "meeting-x-1", "type": "Meeting"}, {"id": "seat-1", "type": "Seat"}]}
    assert failing(ap.preview_checks("org-x", small, {"meeting-x-1"})) == []
    assert failing(ap.preview_checks("org-x", small, {"meeting-x-1", "meeting-x-2"})) == [
        "org-x's page previews the first 2 expected meetings"]


def test_a_meeting_page_names_its_body():
    payload = {"neighbors": [{"id": HARBOR, "type": "Organization", "label": "Lakeport Harbor Commission"}]}
    assert failing(ap.meeting_checks("m", payload, "<h1>Lakeport Harbor Commission</h1>", HARBOR,
                                     "Lakeport Harbor Commission")) == []
    other = {"neighbors": [{"id": COUNCIL, "type": "Organization", "label": "Lakeport Town Council"}]}
    assert len(failing(ap.meeting_checks("m", other, "<h1>Lakeport Town Council</h1>", HARBOR,
                                         "Lakeport Harbor Commission"))) == 2
