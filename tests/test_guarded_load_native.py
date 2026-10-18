"""The no-overwrite load for `identity: native-only` sources (scripts/guarded_load.py).

Same rules as for crosswalk sources (nothing existing is ever written; only creates), plus:
  * the load policy pinned in the capture must equal the registry's now, field by field;
  * the institution and place stubs may be created, once, when absent (the only other node creates);
  * the graph remembers the listing: a loaded meeting whose item left the listing, a new item on a listing
    key an existing meeting holds, a meeting whose key changed, a cancellation and a regular meeting on one
    date across loads: each holds the source, and nothing is written.
Captures come from the real parser on the fictional Lakeport fixture; the graph is a FakeGraphPort.
"""
from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import crosswalk as cw  # noqa: E402
import guarded_load as gl  # noqa: E402
from adapters.civicplus_archive import parse_listing  # noqa: E402

FIXTURE = REPO / "tests" / "fixtures" / "civicplus-archive-lakeport.html"
SID = "lakeport-city-council"
INST = "org-lakeport-city-council"
PLACE = "place-lakeport"
BASE = "https://www.lakeport.example"
CONFIG = {"id": SID, "adapter": "civicplus_archive", "url": BASE + "/Archive.aspx?AMID=49",
          "allowed_hosts": ["www.lakeport.example"], "archive_title": "City Council Agendas",
          "institution_id": INST, "jurisdiction_id": PLACE, "backfill_from": "2019-01-01",
          "identity": "native-only", "create_missing_stubs": True}
OTHER = {"id": "x", "labels": ["Meeting"], "properties": {"id": "x", "institution_id": "org-elsewhere",
                                                         "listing_key": "2026-10-07|regular|1"}}


def _mid(key):
    return f"meeting-{SID}-adid-{key}"


def _page(edit=lambda rows: rows) -> str:
    """The fixture, its row tables passed through `edit` ([(adid, title, table html)] -> same)."""
    html = FIXTURE.read_text(encoding="utf-8")
    tables = re.findall(r'<table summary="Archive Details">.*?</table>', html, re.S)
    head, tail = html[:html.index(tables[0])], html[html.index(tables[-1]) + len(tables[-1]):]
    rows = [(int(re.search(r"ADID=(\d+)", t).group(1)), re.search(r"<span>(.*?)\s*</span>", t, re.S).group(1), t)
            for t in tables]
    out = []
    for adid, title, _ in edit(rows):
        template = tables[0]
        out.append(re.sub(r"<span>.*?</span>", f"<span>{title}  </span>",
                          template.replace("ADID=9537", f"ADID={adid}"), count=1, flags=re.S))
    return head + "".join(out) + tail


def _capture(page=None, day="2026-10-19", config=CONFIG):
    out = parse_listing(page or _page(), source_id=SID, base_url=BASE, backfill_from="2019-01-01",
                        archive_title="City Council Agendas")
    assert out["errors"] == [], out["errors"]
    meetings = out["meetings"]
    for m in meetings:
        m["institution_id"] = INST
    cw.native(SID, meetings)
    return {"capture_id": f"{SID}__{day}", "source_id": SID, "adapter": "civicplus_archive",
            "captured_at": f"{day}T12:00:00Z", "jurisdiction_id": PLACE, "institution_id": INST,
            "inventory": out["inventory"], "meetings": meetings, "meeting_count": len(meetings),
            "record_refs": [{"id": f"record-{SID}-archive-page-{day}", "record_type": "archive_center_page",
                             "source_id": SID, "artifact_path": f"data/raw/{SID}/{day}/source.html",
                             "captured_at": f"{day}T12:00:00Z"}],
            "identity": {"mode": "native-only", "meetings": len(meetings)}, "load_policy": cw.load_policy(config),
            "errors": []}


def _graph(tmp_path, nodes=(), edges=()):
    export = tmp_path / "export"
    export.mkdir(exist_ok=True)
    (export / "nodes.jsonl").write_text("".join(json.dumps(n) + "\n" for n in [OTHER, *nodes]))
    (export / "edges.jsonl").write_text("".join(json.dumps(e) + "\n" for e in edges))
    return gl.FakeGraphPort.create(tmp_path / "graph", seed=export)


def _load(graph_dir, capture, config=CONFIG, root=Path("/nonexistent")):
    with gl.open_port(f"fakegraph://{graph_dir}") as graph:
        return gl.load_capture(graph, copy.deepcopy(capture), config, root=root)


def _reasons(report):
    return sorted({h["reason"] for h in report["holds"]})


@pytest.fixture
def empty(tmp_path):
    return _graph(tmp_path)


# --- the first load -------------------------------------------------------------------------------------


def test_a_first_load_creates_meetings_records_and_the_missing_stubs_once(empty):
    capture = _capture()
    report = _load(empty, capture)
    assert report["outcome"] == "loaded" and report["identity"] == "native-only"
    created = report["created"]["nodes"]
    assert created["Organization"] == [INST] and created["Place"] == [PLACE]
    assert sorted(created["Meeting"]) == sorted(m["meeting_id"] for m in capture["meetings"])
    assert len(created["Meeting"]) == 24
    # 24 artifacts, the two-date cancellation shares one notice Record, plus the listing snapshot
    assert len(created["Record"]) == 23 + 1
    edges = {tuple(e) for e in report["created"]["edges"]}
    assert (INST, "IN_JURISDICTION", PLACE) in edges
    assert (_mid(9533), "AT_INSTITUTION", INST) in edges and (_mid(9533), "IN_JURISDICTION", PLACE) in edges
    notice = f"record-{SID}-{SID}-adid-9138-2023-12-06-notice"
    assert {(_mid("9138-2023-12-06"), "EVIDENCED_BY", notice), (_mid("9138-2023-12-20"), "EVIDENCED_BY", notice)} <= edges
    meeting = gl.FakeGraphPort(empty).nodes([_mid(9129)])[_mid(9129)]["props"]
    assert (meeting["listing_key"], meeting["archive_item_id"], meeting["superseded_item_ids"]) == \
        ("2023-11-01|regular|1", 9129, [9127])
    org = gl.FakeGraphPort(empty).nodes([INST])[INST]
    assert sorted(org["labels"]) == ["Government", "Organization"] and org["props"]["name"] == "Lakeport City Council"


def test_a_second_identical_load_writes_nothing(empty):
    _load(empty, _capture())
    before = gl.FakeGraphPort(empty).overlay()
    report = _load(empty, _capture())
    assert report["outcome"] == "loaded" and report["created"] == {"nodes": {}, "edges": []}
    assert gl.FakeGraphPort(empty).overlay() == before


def test_a_later_week_adds_only_its_listing_record(empty):
    _load(empty, _capture())
    report = _load(empty, _capture(day="2026-10-26"))
    assert report["created"] == {"nodes": {"Record": [f"record-{SID}-archive-page-2026-10-26"]}, "edges": []}


def test_existing_stubs_are_never_written_and_not_created(tmp_path):
    stubs = [{"id": INST, "labels": ["Government", "Organization"], "properties": {"id": INST, "name": INST}},
             {"id": PLACE, "labels": ["Place"], "properties": {"id": PLACE, "name": "Lakeport", "source": "courts"}}]
    graph = _graph(tmp_path, stubs, [{"start_id": INST, "type": "SAME_AS", "end_id": "org-city-of-lakeport",
                                      "properties": {}}])
    report = _load(graph, _capture())
    assert report["outcome"] == "loaded"
    assert "Organization" not in report["created"]["nodes"] and "Place" not in report["created"]["nodes"]
    nodes, edges = gl.FakeGraphPort(graph).overlay()
    assert not {INST, PLACE} & {n["id"] for n in nodes}
    assert not [e for e in edges if e["start_id"] in (INST, PLACE)]  # Org -> Place between existing: skipped
    assert gl.FakeGraphPort(graph).nodes([INST])[INST]["props"] == {"id": INST, "name": INST}
    assert report["protected_differences"]["Organization.name"] == 1


def test_without_the_allowance_a_missing_stub_holds(empty):
    config = {**CONFIG, "create_missing_stubs": False}
    report = _load(empty, _capture(config=config), config=config)
    assert report["outcome"] == "held" and _reasons(report) == ["missing_node"]
    assert gl.FakeGraphPort(empty).overlay() == ([], [])


def test_the_allowance_covers_only_the_two_stubs():
    holds = gl._Holds()
    rows = [{"id": "org-somebody-else", "node_type": "Organization", "labels": ["Organization"], "properties": {}}]

    class Tx:
        def nodes(self, ids):
            return {}

        def existing_edges(self, triples):
            return set()

    plan = gl._plan(Tx(), rows, [], holds, stubs={(INST, "Organization"), (PLACE, "Place")})
    assert plan["nodes"] == [] and [h["reason"] for h in holds] == ["missing_node"]


# --- the pinned load policy ----------------------------------------------------------------------------


@pytest.mark.parametrize("change", [
    {"create_missing_stubs": False}, {"institution_id": "org-lakeport-council"},
    {"jurisdiction_id": "place-lakeport-ca"}, {"identity": "crosswalk-required", "crosswalk": "x.json"}])
def test_a_registry_that_changed_since_staging_holds(empty, change):
    report = _load(empty, _capture(), config={**CONFIG, **change})
    assert report["outcome"] == "held" and _reasons(report) == ["policy_mismatch"]
    assert gl.FakeGraphPort(empty).overlay() == ([], [])


@pytest.mark.parametrize("damage", ["no_identity", "no_policy", "crosswalk_header", "capture_institution"])
def test_a_capture_whose_header_disagrees_holds(empty, damage):
    capture = _capture()
    if damage == "no_identity":
        del capture["identity"]
    elif damage == "no_policy":
        del capture["load_policy"]
    elif damage == "crosswalk_header":
        capture["crosswalk"] = {"path": "x.json", "sha256": "0" * 64}
    else:
        capture["institution_id"] = "org-elsewhere"
    report = _load(empty, capture)
    assert report["outcome"] == "held" and _reasons(report) == ["policy_mismatch"]


# --- the listing memory and the repost policy -----------------------------------------------------------


def _drop(*adids):
    return lambda rows: [r for r in rows if r[0] not in adids]


def _add(*new, drop=()):
    return lambda rows: [*[(a, t, None) for a, t in new], *[r for r in rows if r[0] not in drop]]


@pytest.fixture
def loaded(empty):
    assert _load(empty, _capture())["outcome"] == "loaded"
    return empty


def test_a_loaded_item_gone_from_the_listing_holds(loaded):
    # 2 of the 3 pre-2019 rows are gone too: the reach-back alone would still pass
    report = _load(loaded, _capture(_page(_drop(9533, 8149, 7957))))
    assert report["outcome"] == "held" and _reasons(report) == ["listing_item_missing"]
    assert report["holds"][0]["archive_item_id"] == 9533


def test_a_loss_masked_by_new_rows_still_holds(loaded):
    page = _page(_add((9600, "October 28, 2026, City Council Agenda"),
                      (9601, "November 4, 2026, City Council Agenda"), drop=(9441,)))
    report = _load(loaded, _capture(page))
    assert report["outcome"] == "held" and _reasons(report) == ["listing_item_missing"]


def test_a_replacement_only_repost_holds(loaded):
    page = _page(_add((9540, "October 7, 2026, City Council Agenda"), drop=(9533,)))
    report = _load(loaded, _capture(page))
    assert _reasons(report) == ["listing_item_missing", "repost_suspected"]


def test_a_replacement_that_also_changes_the_type_holds(loaded):
    page = _page(_add((9540, "October 7, 2026, Special City Council Agenda"), drop=(9533,)))
    assert _reasons(_load(loaded, _capture(page))) == ["listing_item_missing"]


def test_a_repost_added_beside_the_original_holds(loaded):
    page = _page(_add((9540, "October 7, 2026, City Council Agenda")))  # parser: one meeting at 9540
    report = _load(loaded, _capture(page))
    assert report["outcome"] == "held" and _reasons(report) == ["listing_item_reassigned", "repost_suspected"]


def test_both_postings_present_from_the_first_load_are_one_meeting(loaded):
    meetings = gl.FakeGraphPort(loaded).nodes([_mid(9129), _mid(9127)])
    assert list(meetings) == [_mid(9129)]


def test_an_amended_title_on_the_same_key_maps_to_the_one_meeting(loaded):
    page = _page(lambda rows: [(a, "October 7, 2026, City Council Agenda - Amended" if a == 9533 else t, x)
                               for a, t, x in rows])
    report = _load(loaded, _capture(page))
    assert report["outcome"] == "loaded" and report["created"] == {"nodes": {}, "edges": []}
    assert report["protected_differences"]["Meeting.title"] == 1
    assert gl.FakeGraphPort(loaded).nodes([_mid(9533)])[_mid(9533)]["props"]["title"] == \
        "October 7, 2026, City Council Agenda"


def test_an_amendment_that_changes_the_type_holds(loaded):
    page = _page(lambda rows: [(a, "October 7, 2026, Special City Council Agenda" if a == 9533 else t, x)
                               for a, t, x in rows])
    assert _reasons(_load(loaded, _capture(page))) == ["listing_key_changed"]


def test_a_new_cancellation_on_a_loaded_regular_meetings_date_holds(loaded):
    capture = _capture(_page(_add((9541, "October 21, 2026 - Meeting Cancelled"), drop=(9537,))))
    capture["inventory"]["items"] = sorted(capture["inventory"]["items"] + [9537])  # still listed, unparsed
    assert _reasons(_load(loaded, capture)) == ["cancellation_conflict", "listing_item_dropped"]


def test_reordered_rows_and_a_fresh_graph_give_the_same_writes(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    a, b = _graph(tmp_path / "a"), _graph(tmp_path / "b")
    _load(a, _capture())
    _load(b, _capture(_page(lambda rows: list(reversed(rows)))))
    key = lambda overlay: (sorted(json.dumps(n, sort_keys=True) for n in overlay[0]),  # noqa: E731
                           sorted(json.dumps(e, sort_keys=True) for e in overlay[1]))
    assert key(gl.FakeGraphPort(a).overlay()) == key(gl.FakeGraphPort(b).overlay())


def test_other_institutions_meetings_on_the_same_key_do_not_count(empty):
    assert _load(empty, _capture())["outcome"] == "loaded"  # OTHER holds 2026-10-07|regular|1 elsewhere


# --- Codex review (b): every loaded item keeps its listing keys; superseded items stay absorbed ----------


def _retitle(adid, title):
    return lambda rows: [(a, title if a == adid else t, x) for a, t, x in rows]


@pytest.mark.parametrize("title", [
    "December 6, 2023 and December 21, 2023 - Meeting Cancelled",  # one date corrected
    "December 6, 2023 - Meeting Cancelled",  # two dates -> one
    "December 6, 2023, December 20, 2023 and January 3, 2024 - Meeting Cancelled"])  # two -> three
def test_a_multi_date_notice_whose_dates_change_holds(loaded, title):
    report = _load(loaded, _capture(_page(_retitle(9138, title))))
    assert report["outcome"] == "held" and "listing_key_changed" in _reasons(report)
    assert [h["archive_item_id"] for h in report["holds"] if h["reason"] == "listing_key_changed"] == [9138]


def test_a_single_date_item_that_gains_a_date_holds(loaded):
    page = _page(_retitle(9249, "October 2, 2024 and October 16, 2024 - Meeting Cancelled"))
    assert _reasons(_load(loaded, _capture(page))) == ["listing_key_changed", "repost_suspected"]


def test_a_superseded_posting_that_becomes_its_own_meeting_holds(loaded):
    page = _page(_retitle(9127, "November 1, 2023 City Council Workshop Agenda"))
    report = _load(loaded, _capture(page))
    assert report["outcome"] == "held" and _reasons(report) == ["superseded_item_reappeared"]


def test_a_loaded_item_that_is_no_longer_a_meeting_holds(loaded):
    page = _page(_retitle(9533, "October 7, 2026, Courtesy Notice of Council Attendance at Workshop"))
    assert _reasons(_load(loaded, _capture(page))) == ["listing_item_dropped"]


# --- Codex review (b) round 2: a loaded winner never becomes absorbed; no new re-posts on loaded meetings --


def test_a_loaded_item_absorbed_by_a_new_repost_on_another_key_holds(loaded):
    page = _page(lambda rows: [(9540, "October 8, 2026, City Council Agenda", None)] +
                 [(a, "October 8, 2026, City Council Agenda" if a == 9533 else t, x) for a, t, x in rows])
    report = _load(loaded, _capture(page))
    assert report["outcome"] == "held" and "listing_item_reassigned" in _reasons(report)


def test_a_new_lower_repost_of_a_loaded_meeting_holds_rather_than_being_forgotten(loaded):
    page = _page(_add((9532, "October 7, 2026, City Council Agenda")))  # parser: winner stays 9533
    report = _load(loaded, _capture(page))
    assert report["outcome"] == "held" and _reasons(report) == ["new_repost_on_loaded_meeting"]


def test_a_stored_repost_that_later_disappears_is_fine(loaded):
    assert _load(loaded, _capture(_page(_drop(9127))))["outcome"] == "loaded"
