"""A meeting keeps one id for life.

I2 made ids stable run-to-run, but a Granicus meeting's *native key* upgrades
as it progresses: no key (title hash) -> event id once the agenda posts ->
clip id once the video posts. Each upgrade would mint a new id and a
duplicate Meeting node. The persisted identity map pins the first-seen id and
links later ids to it through (source, date, normalized title).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from meeting_identity import MeetingIdentityMap  # noqa: E402

SRC = "novato-city-council"


def _m(mid, date="2026-10-06", title="City Council Regular Meeting"):
    return {"meeting_id": mid, "date": date, "title": title}


def test_first_seen_id_survives_native_key_upgrades(tmp_path):
    idmap = MeetingIdentityMap(tmp_path / "ids.json")
    week1 = [_m("meeting-novato-city-council-2026-10-06-1a2b3c4d")]  # upcoming, title hash
    week2 = [_m("meeting-novato-city-council-event-8812")]            # agenda posted
    week3 = [_m("meeting-novato-city-council-5541")]                  # video posted
    for week in (week1, week2, week3):
        idmap.canonicalize(SRC, week)
        assert week[0]["meeting_id"] == "meeting-novato-city-council-2026-10-06-1a2b3c4d"


def test_existing_graph_ids_are_never_rewritten(tmp_path):
    idmap = MeetingIdentityMap(tmp_path / "ids.json")
    rows = [_m("meeting-novato-city-council-5541")]
    idmap.canonicalize(SRC, rows)
    assert rows[0]["meeting_id"] == "meeting-novato-city-council-5541"


def test_distinct_meetings_same_day_stay_distinct(tmp_path):
    idmap = MeetingIdentityMap(tmp_path / "ids.json")
    rows = [_m("meeting-a", title="City Council Regular"), _m("meeting-b", title="Closed Session")]
    idmap.canonicalize(SRC, rows)
    assert [r["meeting_id"] for r in rows] == ["meeting-a", "meeting-b"]


def test_sources_do_not_share_identity(tmp_path):
    idmap = MeetingIdentityMap(tmp_path / "ids.json")
    a, b = [_m("meeting-x")], [_m("meeting-y")]
    idmap.canonicalize("source-a", a)
    idmap.canonicalize("source-b", b)
    assert b[0]["meeting_id"] == "meeting-y"


def test_map_persists_across_processes(tmp_path):
    path = tmp_path / "ids.json"
    first = MeetingIdentityMap(path)
    first.canonicalize(SRC, [_m("meeting-first")])
    first.save()
    rows = [_m("meeting-upgraded")]
    MeetingIdentityMap(path).canonicalize(SRC, rows)
    assert rows[0]["meeting_id"] == "meeting-first"
    json.loads(path.read_text())  # valid JSON on disk


def test_undated_rows_are_left_alone(tmp_path):
    idmap = MeetingIdentityMap(tmp_path / "ids.json")
    rows = [{"meeting_id": "meeting-z", "date": None, "title": "Something"}]
    idmap.canonicalize(SRC, rows)
    assert rows[0]["meeting_id"] == "meeting-z"


def test_duplicate_listings_merge_into_one_meeting_keeping_every_artifact():
    from meeting_identity import merge_duplicate_meetings

    listed_twice = [
        {"meeting_id": "m-jun1", "date": "2022-06-01", "title": "Council",
         "artifacts": {"agenda": {"available": True, "url": "a"}, "minutes": {"available": False, "url": None}}},
        {"meeting_id": "m-jun1", "date": "2022-06-01", "title": "Council",
         "artifacts": {"agenda": {"available": True, "url": "a"}, "minutes": {"available": True, "url": "m"}}},
        {"meeting_id": "m-other", "date": "2022-06-02", "title": "Other", "artifacts": {}},
    ]
    merged = merge_duplicate_meetings(listed_twice)
    assert [m["meeting_id"] for m in merged] == ["m-jun1", "m-other"]
    assert merged[0]["artifacts"]["minutes"] == {"available": True, "url": "m"}
