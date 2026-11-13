"""Reviewed Record-URL aliases in the no-overwrite load (scripts/guarded_load.py, scripts/record_url_aliases.py).

A city re-hosts its files: the page links an existing Record's artifact at a new url. Without review that holds
(`artifact_url_changed`). With an entry that matches exactly (source, Record, art, the Record's url now, the page's
url) and a capture that pinned the list at stage time, the artifact resolves to the Record it already has: no
Record is created, re-pointed or written. A new Meeting linking the aliased url reuses that Record. Everything
else still holds. Fixtures are fictional (Lakeport), reused from test_guarded_load.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import crosswalk as cw  # noqa: E402
import guarded_load as gl  # noqa: E402
import record_url_aliases as rua  # noqa: E402
from test_guarded_load import (  # noqa: E402,F401  (fixtures)
    CONFIG, LISTING, PDF, REG, REG_MIN, SID, SPECIAL_MIN, _capture, _created, _held, _load, _m, _minutes_node,
    _overlay, graph_dir, root)

NEW = "https://storage.example/lakeport-rehosted/{}.pdf"
REG_OLD, REG_NEW = PDF.format("minutes-2020-03-02"), NEW.format("minutes-2020-03-02")
SPECIAL_OLD, SPECIAL_NEW = PDF.format("minutes-2020-03-09"), NEW.format("minutes-2020-03-09")


def alias(rid=REG_MIN, art="minutes", old=REG_OLD, new=REG_NEW):
    return {"record_id": rid, "art": art, "established_url": old, "page_url": new,
            "evidence": {"kind": "identical_bytes", "sha256": "c" * 64}, "reviewed": "2026-11-12"}


def write_aliases(root: Path, *entries, sid=SID) -> dict:
    path = root / rua.PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({"format": 1, "sources": {sid: list(entries)}}, sort_keys=False))
    return rua.binding(root, sid) or {"path": rua.PATH, "sha256": rua.load(root).sha256}


def bound(root, meetings, binding, **kw):
    return {**_capture(root, meetings, **kw), "record_url_aliases": binding}


def reg(url=REG_NEW):
    return _m("city-council-march-2-2020", "2020-03-02", minutes=url)


# --- an exact match resolves to the established Record ------------------------------------------------------


def test_a_listed_pair_resolves_to_the_established_record_and_writes_nothing_existing(root, graph_dir):
    binding = write_aliases(root, alias())
    report = _load(root, graph_dir, bound(root, [reg()], binding))
    assert report["outcome"] == "loaded" and report["holds"] == []
    assert report["created"]["nodes"] == {"Record": [LISTING]} and report["created"]["edges"] == []
    assert report["record_url_aliases_sha256"] == binding["sha256"]
    assert report["protected_differences"]["Record.source_url"] == 1  # counted, never applied
    record = gl.FakeGraphPort(graph_dir).nodes([REG_MIN])[REG_MIN]
    assert record["props"]["source_url"] == REG_OLD
    nodes, edges = _overlay(graph_dir)
    assert [n["id"] for n in nodes] == [LISTING] and edges == []


def test_the_established_url_itself_still_resolves_with_aliases_bound(root, graph_dir):
    binding = write_aliases(root, alias())
    assert _load(root, graph_dir, bound(root, [reg(REG_OLD)], binding))["outcome"] == "loaded"


def test_one_of_several_reviewed_page_urls_for_a_record_resolves(root, graph_dir):
    binding = write_aliases(root, alias(new=NEW.format("first")), alias())
    assert _load(root, graph_dir, bound(root, [reg()], binding))["outcome"] == "loaded"


def test_a_repeated_aliased_load_is_a_no_op(root, graph_dir):
    binding = write_aliases(root, alias())
    _load(root, graph_dir, bound(root, [reg()], binding))
    before = _overlay(graph_dir)
    again = _load(root, graph_dir, bound(root, [reg()], binding))
    assert again["outcome"] == "loaded" and again["created"] == {"nodes": {}, "edges": []}
    assert _overlay(graph_dir) == before


# --- anything short of an exact match holds -----------------------------------------------------------------


def test_an_unlisted_pair_holds_url_changed(root, graph_dir):
    binding = write_aliases(root, alias(rid=SPECIAL_MIN, old=SPECIAL_OLD, new=SPECIAL_NEW))
    _held(root, graph_dir, bound(root, [reg()], binding), "artifact_url_changed")


@pytest.mark.parametrize("entry", [
    alias(old=PDF.format("minutes-2020-03-02-stale")),  # the Record's url is no longer the one reviewed
    alias(new=NEW.format("another-copy")),             # the page links a url nobody reviewed
    alias(art="agenda"),                               # the entry is for another artifact of the Record
], ids=["stale", "other-page-url", "other-art"])
def test_a_record_with_entries_but_no_exact_match_holds_alias_mismatch_naming_them(root, graph_dir, entry):
    binding = write_aliases(root, entry)
    report = _held(root, graph_dir, bound(root, [reg()], binding), "artifact_alias_mismatch")
    hold = next(h for h in report["holds"] if h["reason"] == "artifact_alias_mismatch")
    assert hold["record"] == REG_MIN and hold["url"] == REG_NEW
    assert hold["entries"] == [{"art": entry["art"], "established_url": entry["established_url"],
                                "page_url": entry["page_url"]}]


def test_an_unbound_capture_never_consumes_aliases(root, graph_dir):
    write_aliases(root, alias())
    _held(root, graph_dir, _capture(root, [reg()]), "artifact_url_changed")


def test_aliases_of_another_source_never_apply(root, graph_dir):
    write_aliases(root, alias(), sid="another-city-council")
    binding = {"path": rua.PATH, "sha256": rua.load(root).sha256}
    _held(root, graph_dir, bound(root, [reg()], binding), "artifact_url_changed")


# --- the binding: the list the stage pinned, or a hold ------------------------------------------------------


@pytest.mark.parametrize("change", ["changed", "deleted", "invalid", "wrong-path", "no-hash"])
def test_a_list_that_is_not_the_one_staged_is_a_policy_mismatch(root, graph_dir, change):
    binding = write_aliases(root, alias())
    path = root / rua.PATH
    if change == "changed":
        write_aliases(root, alias(), alias(rid=SPECIAL_MIN, old=SPECIAL_OLD, new=SPECIAL_NEW))
    elif change == "deleted":
        path.unlink()
    elif change == "invalid":
        path.write_text("format: 1\nsources: {}\n")
    elif change == "wrong-path":
        binding = {**binding, "path": "registry/other.yaml"}
    else:
        binding = {"path": rua.PATH}
    report = _held(root, graph_dir, bound(root, [reg()], binding), "policy_mismatch")
    assert report["holds"][0]["detail"].startswith("record url aliases")


# --- a new Meeting linking an aliased url reuses that Record ------------------------------------------------


def special_regular(url=SPECIAL_NEW):
    return _m("city-council-march-9-2020-special-regular", "2020-03-09", minutes=url)


def test_a_new_meeting_linking_an_aliased_url_reuses_the_record(root, graph_dir):
    binding = write_aliases(root, alias(rid=SPECIAL_MIN, old=SPECIAL_OLD, new=SPECIAL_NEW))
    special = _m("city-council-march-9-2020-special", "2020-03-09", minutes=SPECIAL_NEW)
    report = _load(root, graph_dir, bound(root, [special, special_regular()], binding))
    native = cw.adapter_id(SID, "city-council-march-9-2020-special-regular")
    assert report["outcome"] == "loaded", report["holds"]
    assert _created(report, "Record") == [LISTING]  # one Record for the shared minutes: the existing one
    assert [native, "EVIDENCED_BY", SPECIAL_MIN] in report["created"]["edges"]
    assert gl.FakeGraphPort(graph_dir).nodes([SPECIAL_MIN])[SPECIAL_MIN]["props"]["source_url"] == SPECIAL_OLD


def test_an_unbound_new_meeting_linking_the_url_makes_a_new_record_as_before(root, graph_dir):
    write_aliases(root, alias(rid=SPECIAL_MIN, old=SPECIAL_OLD, new=SPECIAL_NEW))
    report = _load(root, graph_dir, _capture(root, [special_regular()]))
    assert len(_created(report, "Record")) == 2  # what the alias exists to prevent, without one


@pytest.mark.parametrize("entry", [alias(rid=SPECIAL_MIN, old=PDF.format("stale"), new=SPECIAL_NEW),
                                   alias(rid="record-lakeport-gone-minutes", old=PDF.format("gone"), new=SPECIAL_NEW)],
                         ids=["stale", "missing-record"])
def test_a_new_meeting_linking_a_reviewed_url_whose_alias_no_longer_holds_is_held_never_minted(root, graph_dir, entry):
    binding = write_aliases(root, entry)
    report = _held(root, graph_dir, bound(root, [special_regular()], binding), "artifact_alias_mismatch")
    assert report["holds"][0]["url"] == SPECIAL_NEW


def test_a_new_meeting_reusing_an_aliased_url_must_be_the_reviewed_art(root, graph_dir):
    binding = write_aliases(root, alias(rid=SPECIAL_MIN, art="agenda", old=SPECIAL_OLD, new=SPECIAL_NEW))
    _held(root, graph_dir, bound(root, [special_regular()], binding), "artifact_alias_mismatch")


@pytest.mark.parametrize("pinned", [["registry/record-url-aliases.yaml"], "x", 7])
def test_a_malformed_binding_is_a_policy_mismatch_not_a_crash(root, graph_dir, pinned):
    write_aliases(root, alias())
    report = _held(root, graph_dir, bound(root, [reg()], pinned), "policy_mismatch")
    assert report["record_url_aliases_sha256"] is None


def test_an_aliased_url_on_a_second_record_is_ambiguous_and_holds(root, graph_dir):
    other = "record-2020-03-09-lakeport-city-council-special-minutes-copy"
    gl.FakeGraphPort(graph_dir).add_seed_node(_minutes_node(other, SPECIAL_NEW, REG))
    with open(graph_dir / "seed" / "edges.jsonl", "a") as fh:
        fh.write('{"start_id": "%s", "type": "RELATES_TO_MEETING", "end_id": "%s", "properties": {}}\n' % (other, REG))
    binding = write_aliases(root, alias(rid=SPECIAL_MIN, old=SPECIAL_OLD, new=SPECIAL_NEW))
    _held(root, graph_dir, bound(root, [special_regular()], binding), "artifact_url_on_other_record")


def test_an_alias_never_bypasses_url_on_other_record_for_an_existing_meeting(root, graph_dir):
    binding = write_aliases(root, alias(rid=SPECIAL_MIN, old=SPECIAL_OLD, new=SPECIAL_NEW))
    closed = _m("city-council-march-2-2020-closed-session", "2020-03-02", minutes=SPECIAL_NEW)
    _held(root, graph_dir, bound(root, [closed], binding), "artifact_url_on_other_record")


def test_an_alias_onto_a_url_another_record_holds_never_resolves(root, graph_dir):
    """The page links, for this meeting's Record, a url another meeting's Record already holds."""
    binding = write_aliases(root, alias(new=SPECIAL_OLD))
    _held(root, graph_dir, bound(root, [reg(SPECIAL_OLD)], binding), "artifact_url_on_other_record")


def test_an_alias_never_bypasses_one_url_on_two_artifacts(root, graph_dir):
    binding = write_aliases(root, alias())
    m = _m("city-council-march-2-2020", "2020-03-02", minutes=REG_NEW, packet=REG_NEW)
    _held(root, graph_dir, bound(root, [m], binding), "artifact_url_shared")


def test_the_config_without_aliases_behaves_exactly_as_before(root, graph_dir):
    report = _load(root, graph_dir, _capture(root, [reg(REG_OLD)]), CONFIG)
    assert report["outcome"] == "loaded" and report["record_url_aliases_sha256"] is None
