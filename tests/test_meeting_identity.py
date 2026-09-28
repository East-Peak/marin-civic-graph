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


# --- Review P0 (2026-09-28): distinct meetings sharing date + title must never merge.
# Reproduced on real data: Marin BOS clips on the same date with identical titles
# collapsed onto one id, and merge_duplicate_meetings then dropped the second
# clip's minutes/video.

def test_two_native_meetings_same_date_and_title_in_one_pull_stay_distinct(tmp_path):
    idmap = MeetingIdentityMap(tmp_path / "ids.json")
    rows = [_m("meeting-bos-12726"), _m("meeting-bos-12727")]
    idmap.canonicalize("marin-county-bos", rows)
    assert [r["meeting_id"] for r in rows] == ["meeting-bos-12726", "meeting-bos-12727"]


def test_an_ambiguous_key_never_links_later(tmp_path):
    idmap = MeetingIdentityMap(tmp_path / "ids.json")
    idmap.canonicalize(SRC, [_m("meeting-hash-a"), _m("meeting-hash-b")])  # ambiguous day
    week2 = [_m("meeting-clip-1")]
    idmap.canonicalize(SRC, week2)
    assert week2[0]["meeting_id"] == "meeting-clip-1"


def test_a_known_native_id_is_never_relinked_to_another_meeting(tmp_path):
    idmap = MeetingIdentityMap(tmp_path / "ids.json")
    idmap.canonicalize(SRC, [_m("meeting-clip-1")])
    rows = [_m("meeting-clip-2")]  # a DIFFERENT clip, same date+title, next week
    idmap.canonicalize(SRC, [_m("meeting-clip-1"), *rows])
    assert rows[0]["meeting_id"] == "meeting-clip-2"


def test_upgrade_still_links_when_unambiguous(tmp_path):
    idmap = MeetingIdentityMap(tmp_path / "ids.json")
    idmap.canonicalize(SRC, [_m("meeting-hash")])
    rows = [_m("meeting-clip")]
    idmap.canonicalize(SRC, rows)
    assert rows[0]["meeting_id"] == "meeting-hash"


def test_category_separates_bodies_meeting_the_same_day(tmp_path):
    idmap = MeetingIdentityMap(tmp_path / "ids.json")
    tc = {**_m("meeting-cm-tc", title=""), "category": "Town Council"}
    pc = {**_m("meeting-cm-pc", title=""), "category": "Planning Commission"}
    idmap.canonicalize("corte-madera", [tc, pc])
    assert (tc["meeting_id"], pc["meeting_id"]) == ("meeting-cm-tc", "meeting-cm-pc")


def test_no_merge_ever_drops_a_distinct_meetings_artifacts(tmp_path):
    from meeting_identity import merge_duplicate_meetings

    idmap = MeetingIdentityMap(tmp_path / "ids.json")
    a = {**_m("meeting-bos-12726"), "artifacts": {"minutes": {"available": True, "url": "m1"}}}
    b = {**_m("meeting-bos-12727"), "artifacts": {"minutes": {"available": True, "url": "m2"}}}
    rows = [a, b]
    idmap.canonicalize("marin-county-bos", rows)
    merged = merge_duplicate_meetings(rows)
    assert sorted(m["artifacts"]["minutes"]["url"] for m in merged) == ["m1", "m2"]
