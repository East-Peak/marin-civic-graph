"""Crosswalk-required meeting identity: an exact, reviewed slug -> existing-id map, and nothing else.

A source whose graph ids were built by hand (San Rafael's wave-01 scripts) cannot use the date/title
identity map: it would either mint a duplicate of every meeting or, worse, link two distinct meetings
that share a date and title. Its identity is the crosswalk entry or the adapter's own id; anything
missing, malformed or conflicting fails the source closed. Fixtures are fictional (Lakeport).
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import crosswalk as cw  # noqa: E402
import ingest  # noqa: E402
from ingest_guard import RunLedger  # noqa: E402
from meeting_identity import MeetingIdentityMap  # noqa: E402

SID = "lakeport-city-council"
INST = "org-lakeport-city-council"
XW_REL = "registry/crosswalks/lakeport-city-council.json"
PAGE = "https://www.lakeport.example/meetings/{}/"

ENTRIES = {
    "city-council-march-2-2020": "meeting-2020-03-02-lakeport-city-council",
    "city-council-march-2-2020-closed-session": "meeting-2020-03-02-lakeport-city-council-closed-session",
    "city-council-march-9-2020-special": "meeting-2020-03-09-lakeport-city-council-special",
    "city-council-june-1-2020-revised": "meeting-2020-06-01-lakeport-city-council-b",
}


def _write_xw(root: Path, entries=None, **overrides) -> Path:
    body = {"format": 1, "source_id": SID, "entries": ENTRIES if entries is None else entries, **overrides}
    path = root / XW_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body))
    return path


def _meeting(slug, date_="2020-03-02", title="City Council – March 2, 2020"):
    return {"meeting_id": f"meeting-{SID}-{slug}", "date": date_, "title": title,
            "source_url": PAGE.format(slug), "artifacts": {}}


# --- loading and validation ---------------------------------------------------------------------------


def test_a_valid_crosswalk_loads_with_its_version(tmp_path):
    path = _write_xw(tmp_path)
    xw = cw.load(path, SID)
    assert xw.entries == ENTRIES
    assert xw.sha256 == cw.sha256_file(path)


@pytest.mark.parametrize("damage", [
    "missing", "unreadable", "not-json", "format-2", "other-source", "empty", "bad-slug",
    "native-target", "not-a-meeting", "two-slugs-one-target", "duplicate-key",
])
def test_a_crosswalk_that_is_not_exactly_valid_is_refused(tmp_path, damage):
    path = tmp_path / XW_REL
    if damage != "missing":
        path = _write_xw(tmp_path)
    if damage == "unreadable":
        path.unlink()
        path.mkdir()
    elif damage == "not-json":
        path.write_text("{entries:")
    elif damage == "format-2":
        _write_xw(tmp_path, format=2)
    elif damage == "other-source":
        _write_xw(tmp_path, source_id="elsewhere-city-council")
    elif damage == "empty":
        _write_xw(tmp_path, entries={})
    elif damage == "bad-slug":
        _write_xw(tmp_path, entries={"City Council/March": "meeting-2020-03-02-lakeport-city-council"})
    elif damage == "native-target":
        _write_xw(tmp_path, entries={"a": f"meeting-{SID}-b"})
    elif damage == "not-a-meeting":
        _write_xw(tmp_path, entries={"a": "record-2020-03-02-lakeport-city-council-minutes"})
    elif damage == "duplicate-key":  # json.loads would keep only the last
        path.write_text('{"format": 1, "source_id": "%s", "entries": {"a": "meeting-2020-01-01-x", '
                        '"a": "meeting-2020-01-02-x"}}' % SID)
    elif damage == "two-slugs-one-target":
        _write_xw(tmp_path, entries={"a": "meeting-2020-03-02-lakeport-city-council",
                                     "b": "meeting-2020-03-02-lakeport-city-council"})
    with pytest.raises(cw.CrosswalkError):
        cw.load(path, SID)


# --- applying it --------------------------------------------------------------------------------------


def _apply(rows):
    xw = cw.Crosswalk(source_id=SID, entries=dict(ENTRIES), sha256="x", path=Path(XW_REL))
    summary = cw.apply(xw, rows)
    return [r["meeting_id"] for r in rows], summary


def test_regular_special_closed_session_and_legacy_suffix_map_exactly():
    ids, summary = _apply([_meeting("city-council-march-2-2020"),
                           _meeting("city-council-march-2-2020-closed-session", title="Closed Session"),
                           _meeting("city-council-march-9-2020-special", "2020-03-09"),
                           _meeting("city-council-june-1-2020-revised", "2020-06-01")])
    assert ids == ["meeting-2020-03-02-lakeport-city-council",
                   "meeting-2020-03-02-lakeport-city-council-closed-session",
                   "meeting-2020-03-09-lakeport-city-council-special",
                   "meeting-2020-06-01-lakeport-city-council-b"]
    assert summary == {"mapped": 4, "native": 0}


def test_each_meeting_keeps_the_adapter_id_it_arrived_with():
    rows = [_meeting("city-council-march-2-2020")]
    _apply(rows)
    assert rows[0]["adapter_meeting_id"] == f"meeting-{SID}-city-council-march-2-2020"


def test_unmapped_meetings_keep_their_own_ids_even_with_the_same_date_and_title():
    title = "City Council – May 4, 2026"
    ids, summary = _apply([_meeting("city-council-may-4-2026", "2026-05-04", title),
                           _meeting("city-council-may-4-2026-2", "2026-05-04", title)])
    assert ids == [f"meeting-{SID}-city-council-may-4-2026", f"meeting-{SID}-city-council-may-4-2026-2"]
    assert summary == {"mapped": 0, "native": 2}


def test_reordered_and_separate_pulls_give_the_same_ids():
    rows = [_meeting(s) for s in ("city-council-may-4-2026", "city-council-march-2-2020",
                                  "city-council-march-2-2020-closed-session")]
    together, _ = _apply([dict(r) for r in rows])
    reordered, _ = _apply([dict(r) for r in reversed(rows)])
    separate = [_apply([dict(r)])[0][0] for r in rows]
    assert together == list(reversed(reordered)) == separate


def test_two_meetings_claiming_one_canonical_id_fail_closed():
    xw = cw.Crosswalk(source_id=SID, entries=dict(ENTRIES), sha256="x", path=Path(XW_REL))
    rows = [_meeting("city-council-march-2-2020"), _meeting("city-council-march-2-2020")]
    with pytest.raises(cw.CrosswalkError, match="claim"):
        cw.apply(xw, rows)


@pytest.mark.parametrize("bad", ["meeting-elsewhere-x", None, 123, f"meeting-{SID}-", f"meeting-{SID}-a/b"])
def test_a_meeting_id_not_in_the_adapters_form_fails_closed(bad):
    xw = cw.Crosswalk(source_id=SID, entries=dict(ENTRIES), sha256="x", path=Path(XW_REL))
    with pytest.raises(cw.CrosswalkError):
        cw.apply(xw, [{"meeting_id": bad, "date": "2020-03-02"}])


def test_a_malformed_meeting_id_in_the_pull_is_a_crosswalk_conflict(tmp_path, adapter):
    _write_xw(tmp_path)
    adapter.rows = [{**_meeting("city-council-march-2-2020"), "meeting_id": None}]
    result, verdict, ledger = _run(tmp_path, adapter)
    assert not verdict.ok and ledger[-1]["outcome"] == "crosswalk_conflict"


# --- ingest.run_source in crosswalk-required mode -------------------------------------------------------


def _config(**extra):
    return {"id": SID, "adapter": "proudcity", "url": "https://www.lakeport.example/city-council-meetings/",
            "jurisdiction_id": "place-lakeport", "institution_id": INST, "backfill_from": "2019-01-01",
            "schedule": "manual", "identity": "crosswalk-required", "crosswalk": XW_REL,
            "floors": {"max_newest_age_days": None}, **extra}


class _Adapter:
    """Stands in for the ProudCity adapter: no network; counts captures."""
    rows: list[dict] = []
    captures = 0

    def __init__(self, config, root, **_):
        self.config, self.root = config, Path(root)

    def capture(self):
        type(self).captures += 1
        rows = [dict(r) for r in self.rows]
        return {"capture_id": "c1", "source_id": SID, "meetings": rows, "meeting_count": len(rows),
                "record_refs": [], "errors": []}

    def extracted_path(self):
        return self.root / "data" / "extracted" / SID / "2026-10-19.json"


@pytest.fixture
def adapter():
    _Adapter.rows = [_meeting("city-council-march-2-2020"), _meeting("city-council-may-4-2026", "2026-05-04")]
    _Adapter.captures = 0
    return _Adapter


def _run(root, adapter, identity=None, config=None):
    ledger = RunLedger(root / "ledger.jsonl")
    result, verdict = ingest.run_source(config or _config(), root, ledger=ledger, today=date(2026, 10, 19),
                                        adapter_cls=adapter, identity=identity)
    return result, verdict, [json.loads(line) for line in (root / "ledger.jsonl").read_text().splitlines()]


def test_ingest_maps_through_the_crosswalk_and_pins_its_version(tmp_path, adapter):
    path = _write_xw(tmp_path)
    result, verdict, ledger = _run(tmp_path, adapter)
    assert verdict.ok
    capture = json.loads(adapter(_config(), tmp_path).extracted_path().read_text())
    assert [m["meeting_id"] for m in capture["meetings"]] == [
        "meeting-2020-03-02-lakeport-city-council", f"meeting-{SID}-city-council-may-4-2026"]
    assert capture["crosswalk"] == {"path": XW_REL, "sha256": cw.sha256_file(path), "mapped": 1, "native": 1}
    assert ledger[-1]["crosswalk_sha256"] == cw.sha256_file(path)


@pytest.mark.parametrize("damage", ["missing", "invalid"])
def test_a_missing_or_invalid_crosswalk_fails_the_source_before_any_fetch(tmp_path, adapter, damage):
    if damage == "invalid":
        _write_xw(tmp_path, format=2)
    result, verdict, ledger = _run(tmp_path, adapter)
    assert not verdict.ok and adapter.captures == 0
    assert ledger[-1]["outcome"] == "crosswalk_invalid" and not ledger[-1]["ok"]
    assert not adapter(_config(), tmp_path).extracted_path().exists()


def test_a_crosswalk_conflict_in_the_pull_writes_nothing(tmp_path, adapter):
    _write_xw(tmp_path)
    adapter.rows = [_meeting("city-council-march-2-2020"), _meeting("city-council-march-2-2020")]
    result, verdict, ledger = _run(tmp_path, adapter)
    assert not verdict.ok
    assert ledger[-1]["outcome"] == "crosswalk_conflict"
    assert not adapter(_config(), tmp_path).extracted_path().exists()


def test_week_a_maps_then_week_b_without_the_file_fails_closed(tmp_path, adapter):
    path = _write_xw(tmp_path)
    assert _run(tmp_path, adapter)[1].ok
    week_a = adapter(_config(), tmp_path).extracted_path().read_bytes()
    path.unlink()
    assert not _run(tmp_path, adapter)[1].ok
    assert adapter(_config(), tmp_path).extracted_path().read_bytes() == week_a  # last good capture kept


def test_the_identity_map_is_neither_consulted_nor_changed(tmp_path, adapter):
    _write_xw(tmp_path)
    cache = tmp_path / "ids.json"
    wrong = {"by_id": {f"{SID}|meeting-{SID}-city-council-march-2-2020": "meeting-wrong"},
             "by_key": {f"{SID}|2026-05-04||city council may 4 2026": "meeting-wrong-2"}, "ambiguous_keys": []}
    cache.write_text(json.dumps(wrong))
    before = cache.read_bytes()
    empty = tmp_path / "empty"
    empty.mkdir()
    _write_xw(empty)
    _run(tmp_path, adapter, identity=MeetingIdentityMap(cache))
    _run(empty, adapter, identity=MeetingIdentityMap(empty / "ids.json"))
    populated = json.loads(adapter(_config(), tmp_path).extracted_path().read_text())["meetings"]
    fresh = json.loads(adapter(_config(), empty).extracted_path().read_text())["meetings"]
    assert populated == fresh
    assert cache.read_bytes() == before and not (empty / "ids.json").exists()


def test_a_malformed_identity_cache_cannot_stop_a_crosswalk_source(tmp_path, monkeypatch):
    root = tmp_path
    (root / "registry").mkdir()
    _write_xw(root)
    (root / "registry" / "s.yaml").write_text(json.dumps({"sources": [_config()]}))
    (root / ingest.IDENTITY_PATH).parent.mkdir(parents=True)
    (root / ingest.IDENTITY_PATH).write_text("{not json")
    _Adapter.rows = [_meeting("city-council-march-2-2020")]
    monkeypatch.setattr(ingest, "get_adapter_class", lambda name: _Adapter)
    monkeypatch.setattr(ingest, "seed_ledger", lambda *a, **k: [])
    assert ingest._capture(ingest.load_sources(root / "registry" / "s.yaml"), root, gate=None) == 0


# --- the generator ------------------------------------------------------------------------------------


def _export(tmp_path, meetings: dict[str, dict]) -> Path:
    out = tmp_path / "export"
    out.mkdir()
    rows = [{"id": mid, "labels": ["Meeting"], "properties": {"institution_id": INST, **props}}
            for mid, props in meetings.items()]
    rows.append({"id": "meeting-2020-03-02-elsewhere", "labels": ["Meeting"],
                 "properties": {"institution_id": "org-elsewhere", "meeting_page_url": PAGE.format("city-council-march-2-2020")}})
    (out / "nodes.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    (out / "edges.jsonl").write_text("")
    return out


def _listing(slugs_dates):
    links = "".join(f'<a href="/meetings/{s}/">City Council – {d}</a>' for s, d in slugs_dates)
    return f"<html><body>{links}</body></html>"


GRAPH = {
    "meeting-2020-03-02-lakeport-city-council": {"meeting_date": "2020-03-02",
                                                 "meeting_page_url": PAGE.format("city-council-march-2-2020")},
    "meeting-2020-03-02-lakeport-city-council-closed-session": {
        "meeting_date": "2020-03-02", "meeting_page_url": PAGE.format("city-council-march-2-2020-closed-session")},
    "meeting-2015-06-15-lakeport-city-council": {"meeting_date": "2015-06-15"},
    "meeting-2024-08-19-lakeport-city-council": {},
}
LISTING = [("city-council-march-2-2020", "March 2, 2020"),
           ("city-council-march-2-2020-closed-session", "March 2, 2020"),
           ("city-council-may-4-2026", "May 4, 2026")]


def _generate(tmp_path, graph=GRAPH, listing=LISTING, previous=None):
    return cw.generate(SID, INST, _export(tmp_path, graph), _listing(listing), base_url="https://www.lakeport.example",
                       backfill_from="2019-01-01", previous=previous)


def test_generate_matches_exact_slugs_and_classifies_everything_else(tmp_path):
    entries, report = _generate(tmp_path)
    assert entries == {k: v for k, v in ENTRIES.items() if "march-2" in k}
    assert report["matched"] == sorted(entries)
    assert report["listing_only"] == ["city-council-may-4-2026"]
    assert report["graph_only"] == [
        {"id": "meeting-2015-06-15-lakeport-city-council", "reason": "before_backfill_from"},
        {"id": "meeting-2024-08-19-lakeport-city-council", "reason": "no_meeting_page_url"}]
    assert report["conflicts"] == [] and report["kept"] == [] and report["native"] == []


def test_generate_refuses_a_slug_carried_by_two_meetings(tmp_path):
    graph = {**GRAPH, "meeting-2020-03-02-lakeport-city-council-x": {
        "meeting_date": "2020-03-02", "meeting_page_url": PAGE.format("city-council-march-2-2020")}}
    entries, report = _generate(tmp_path, graph)
    assert report["conflicts"] and "city-council-march-2-2020" not in entries


@pytest.mark.parametrize("other", ["meeting-2015-06-15-lakeport-city-council-x", f"meeting-{SID}-elsewhere"])
def test_any_slug_carried_by_two_meetings_is_a_conflict_listed_or_not(tmp_path, other):
    slug = "city-council-june-1-2020-gone"  # no longer listed, never mapped
    graph = {**GRAPH, "meeting-2020-06-01-lakeport-city-council": {"meeting_page_url": PAGE.format(slug)},
             other: {"meeting_page_url": PAGE.format(slug)}}
    entries, report = _generate(tmp_path, graph)
    assert any(slug in c for c in report["conflicts"])


def test_the_cli_writes_nothing_when_there_are_conflicts(tmp_path):
    graph = {**GRAPH, "meeting-2020-03-02-lakeport-city-council-x": {
        "meeting_date": "2020-03-02", "meeting_page_url": PAGE.format("city-council-march-2-2020")}}
    export = _export(tmp_path, graph)
    listing = tmp_path / "listing.html"
    listing.write_text(_listing(LISTING))
    registry = tmp_path / "registry" / "sources.yaml"
    registry.parent.mkdir()
    registry.write_text(json.dumps({"sources": [{**_config(), "url": "https://www.lakeport.example/m/",
                                                 "crosswalk": str(tmp_path / XW_REL)}]}))
    code = cw.main(["generate", "--source", SID, "--export", str(export), "--listing", str(listing),
                    "--registry", str(registry), "--write"])
    assert code == 1 and not (tmp_path / XW_REL).exists()


def test_entries_are_append_only_across_regenerations(tmp_path):
    previous = {"city-council-june-1-2020-revised": "meeting-2020-06-01-lakeport-city-council-b"}
    graph = {**GRAPH, "meeting-2020-06-01-lakeport-city-council-b": {
        "meeting_date": "2020-06-01", "meeting_page_url": PAGE.format("city-council-june-1-2020-revised")}}
    entries, report = _generate(tmp_path, graph, previous=previous)  # June 1 has left the listing
    assert entries["city-council-june-1-2020-revised"] == "meeting-2020-06-01-lakeport-city-council-b"
    assert report["kept"] == ["city-council-june-1-2020-revised"] and report["conflicts"] == []


def test_a_regeneration_that_would_reassign_an_entry_is_a_conflict(tmp_path):
    previous = {"city-council-march-2-2020": "meeting-2020-03-02-lakeport-city-council-closed-session"}
    entries, report = _generate(tmp_path, previous=previous)
    assert report["conflicts"]
    assert entries["city-council-march-2-2020"] == "meeting-2020-03-02-lakeport-city-council-closed-session"


def test_regeneration_after_the_first_weekly_load_sees_native_meetings(tmp_path):
    native = f"meeting-{SID}-city-council-may-4-2026"
    graph = {**GRAPH, native: {"meeting_date": "2026-05-04", "meeting_page_url": PAGE.format("city-council-may-4-2026")}}
    entries, report = _generate(tmp_path, graph, previous={k: v for k, v in ENTRIES.items() if "march-2" in k})
    assert "city-council-may-4-2026" not in entries
    assert report["native"] == [native] and report["listing_only"] == [] and report["conflicts"] == []


def test_an_entry_whose_native_id_also_exists_is_a_conflict(tmp_path):
    native = f"meeting-{SID}-city-council-march-2-2020"
    entries, report = _generate(tmp_path, {**GRAPH, native: {"meeting_date": "2020-03-02"}})
    assert report["conflicts"]


def test_real_slugs_may_carry_url_path_characters(tmp_path):
    entries = {"city-council-november-7-2022-special-study-session_": "meeting-2022-11-07-lakeport-city-council"}
    assert cw.load(_write_xw(tmp_path, entries=entries), SID).entries == entries


def test_write_refuses_what_load_would_refuse(tmp_path):
    with pytest.raises(cw.CrosswalkError):
        cw.write(tmp_path / XW_REL, SID, {"a/b": "meeting-2020-01-01-x"})
    assert not (tmp_path / XW_REL).exists()


def test_write_is_deterministic_and_round_trips(tmp_path):
    path = tmp_path / XW_REL
    cw.write(path, SID, {"b": "meeting-2020-01-02-x", "a": "meeting-2020-01-01-x"})
    first = path.read_bytes()
    cw.write(path, SID, {"a": "meeting-2020-01-01-x", "b": "meeting-2020-01-02-x"})
    assert path.read_bytes() == first
    assert cw.load(path, SID).entries == {"a": "meeting-2020-01-01-x", "b": "meeting-2020-01-02-x"}
