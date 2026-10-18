"""The agenda-items stage writes a bundle and loads it create-only (scripts/agenda_items.py, guarded_load.py).

Fetches go through the robots gate with the source's host allowlist; a forbidden host gets no request at all,
not even for its robots.txt. Parsed items become a normalized bundle (AgendaItem nodes, PART_OF_MEETING and
EVIDENCED_BY edges) that `guarded_load.load_agenda_bundle` creates in one transaction: nothing existing is
written, and a meeting that no longer fits holds alone. Fixtures are fictional (Lakeport); the graph is a
FakeGraphPort over a tiny export.
"""
from __future__ import annotations

import hashlib
import http.server
import json
import socket
import sys
import threading
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import agenda_items as ai  # noqa: E402
import guarded_load as gl  # noqa: E402
import robots_gate as rg  # noqa: E402
from agenda_parsers import Parser  # noqa: E402

SID = "lakeport-town-council"
INST = "org-lakeport-town-council"
HOST = "www.lakeport.example"
AGENDA = "https://www.lakeport.example/AgendaCenter/ViewFile/Agenda/_{}"
M1, M2, M3, M4 = (f"meeting-{SID}-{n}" for n in (101, 102, 103, 104))


def _node(nid, labels, **props):
    return {"id": nid, "labels": labels, "properties": {"id": nid, **props}}


def _edge(s, rel, t):
    return {"start_id": s, "type": rel, "end_id": t, "properties": {}}


def _meeting(mid, day, category="Town Council"):
    return _node(mid, ["Meeting"], institution_id=INST, meeting_date=day, category=category,
                 title=f"Lakeport Town Council {day}", meeting_type="regular", display_label="m", promotion_state="promoted")


def _record(mid, n):
    return _node(f"record-{SID}-{mid.split('meeting-', 1)[1]}-agenda", ["Record"], record_type="meeting_agenda",
                 source_url=AGENDA.format(n), source_id=SID, display_label="meeting_agenda", promotion_state="promoted")


def _rid(mid):
    return f"record-{SID}-{mid.split('meeting-', 1)[1]}-agenda"


@pytest.fixture
def graph(tmp_path):
    seed = tmp_path / "seed"
    seed.mkdir()
    nodes = [_node(INST, ["Government", "Organization"], name="Lakeport Town Council"),
             _meeting(M1, "2026-10-06"), _meeting(M2, "2026-09-15"), _meeting(M3, "2026-09-01"),
             _meeting(M4, "2026-08-04"), _record(M1, 1), _record(M2, 2), _record(M3, 3), _record(M4, 4),
             _node(f"agenda-item-{SID}-102-1", ["AgendaItem"], title="Existing item", meeting_id=M2)]
    edges = [_edge(m, "EVIDENCED_BY", _rid(m)) for m in (M1, M2, M3, M4)]
    edges.append(_edge(f"agenda-item-{SID}-102-1", "PART_OF_MEETING", M2))
    (seed / "nodes.jsonl").write_text("".join(json.dumps(n) + "\n" for n in nodes))
    (seed / "edges.jsonl").write_text("".join(json.dumps(e) + "\n" for e in edges))
    return gl.FakeGraphPort(gl.FakeGraphPort.create(tmp_path / "graph", seed=seed))


def _parsed(day, *titles):
    return {"printed_date": day, "notice": None,
            "items": [{"section_number": "4", "item_number": chr(65 + i), "key": f"4{chr(97 + i)}",
                       "heading": "Consent Calendar", "title": t} for i, t in enumerate(titles)]}


# --- items and bundle --------------------------------------------------------------------------------


def test_item_rows_follow_the_existing_agenda_item_shape():
    nodes, edges = ai.item_rows(M1, SID, _rid(M1), _parsed("2026-10-06", "Approve the minutes", "Adopt a budget"),
                                "outline@2")
    assert nodes[0] == {"id": f"agenda-item-{SID}-101-4a", "labels": ["AgendaItem"], "properties": {
        "id": f"agenda-item-{SID}-101-4a", "display_label": "Approve the minutes", "promotion_state": "promoted",
        "heading": "Consent Calendar", "title": "Approve the minutes", "section_number": "4", "item_number": "A",
        "meeting_id": M1, "source_id": SID, "status": "parsed_from_agenda", "item_order": 1, "parser": "outline@2"}}
    assert [n["properties"]["item_order"] for n in nodes] == [1, 2]
    assert edges == [_edge(f"agenda-item-{SID}-101-4a", "PART_OF_MEETING", M1),
                     _edge(f"agenda-item-{SID}-101-4a", "EVIDENCED_BY", _rid(M1)),
                     _edge(f"agenda-item-{SID}-101-4b", "PART_OF_MEETING", M1),
                     _edge(f"agenda-item-{SID}-101-4b", "EVIDENCED_BY", _rid(M1))]


def test_a_display_label_is_the_title_cut_to_120_and_empty_numbers_are_not_stored():
    parsed = {"printed_date": "2026-10-06", "notice": None,
              "items": [{"section_number": "10", "item_number": "", "key": "10", "heading": "", "title": "x" * 300}]}
    (node,), _ = ai.item_rows(M1, SID, _rid(M1), parsed, "outline@2")
    assert node["properties"]["display_label"] == "x" * 120 and "item_number" not in node["properties"]
    assert node["id"] == f"agenda-item-{SID}-101-10"


@pytest.mark.parametrize("parsed, reason", [
    ({"printed_date": "2026-10-06", "notice": "cancellation", "items": []}, "cancellation_notice"),
    ({"printed_date": "2026-10-06", "notice": None, "items": []}, "zero_items"),
    ({"printed_date": None, "notice": None, "items": [{"key": "1", "title": "x"}]}, "agenda_date_missing"),
    ({"printed_date": "2026-04-29", "notice": None, "items": [{"key": "1", "title": "x"}]}, "agenda_date_mismatch"),
    ({"printed_date": "2026-10-06", "notice": None, "items": [{"key": "1", "title": "x"}, {"key": "1", "title": "y"}]},
     "duplicate_item_key"),
    ({"printed_date": "2026-10-06", "notice": None, "items": [{"key": "1", "title": "  "}]}, "item_without_title"),
])
def test_a_parse_that_cannot_load_holds_with_a_reason(parsed, reason):
    assert ai.parse_hold(parsed, "2026-10-06") == reason


def test_a_good_parse_does_not_hold():
    assert ai.parse_hold(_parsed("2026-10-06", "a", "b"), "2026-10-06") is None


def _bundle(tmp_path, entries):
    return ai.write_bundle(tmp_path / "bundle", entries)


def _entry(mid, day, *titles, url_n=None):
    n = int(mid.rsplit("-", 1)[1]) - 100
    nodes, edges = ai.item_rows(mid, SID, _rid(mid), _parsed(day, *titles), "outline@2")
    return {"meeting_id": mid, "source_id": SID, "institution_id": INST, "record_id": _rid(mid),
            "url": AGENDA.format(url_n or n), "sha256": "ab" * 32, "parser": "outline@2", "nodes": nodes, "edges": edges}


def test_the_bundle_loads_create_only(tmp_path, graph):
    bundle = _bundle(tmp_path, [_entry(M1, "2026-10-06", "Approve the minutes", "Adopt a budget"),
                                _entry(M3, "2026-09-01", "Hear a report")])
    report = gl.load_agenda_bundle(graph, bundle, recheck=_ok)
    assert report["outcome"] == "loaded" and report["holds"] == []
    assert report["created"]["meetings"] == {M1: [f"agenda-item-{SID}-101-4a", f"agenda-item-{SID}-101-4b"],
                                             M3: [f"agenda-item-{SID}-103-4a"]}
    nodes, edges = graph.overlay()
    assert {n["id"] for n in nodes} == {f"agenda-item-{SID}-101-4a", f"agenda-item-{SID}-101-4b",
                                        f"agenda-item-{SID}-103-4a"}
    assert all(n["labels"] == ["AgendaItem"] for n in nodes)
    assert sorted((e["type"], e["end_id"]) for e in edges) == sorted(
        [("PART_OF_MEETING", M1)] * 2 + [("EVIDENCED_BY", _rid(M1))] * 2 + [("PART_OF_MEETING", M3),
                                                                            ("EVIDENCED_BY", _rid(M3))])
    rows = (graph.path / "overlay.jsonl").read_text().splitlines()
    assert all(set(json.loads(r)) <= {"node", "edge"} for r in rows)  # creates only: no merge rows


def test_loading_the_same_bundle_twice_creates_nothing_the_second_time(tmp_path, graph):
    bundle = _bundle(tmp_path, [_entry(M1, "2026-10-06", "Approve the minutes")])
    gl.load_agenda_bundle(graph, bundle, recheck=_ok)
    again = gl.load_agenda_bundle(gl.FakeGraphPort(graph.path), bundle, recheck=_ok)
    assert again["created"]["meetings"] == {} and again["holds"] == [] and again["already_loaded"] == [M1]
    assert len(gl.FakeGraphPort(graph.path).overlay()[0]) == 1


def test_a_meeting_with_items_is_skipped_and_holds_alone(tmp_path, graph):
    bundle = _bundle(tmp_path, [_entry(M2, "2026-09-15", "A new item"), _entry(M1, "2026-10-06", "Fine")])
    report = gl.load_agenda_bundle(graph, bundle, recheck=_ok)
    assert [(h["meeting_id"], h["reason"]) for h in report["holds"]] == [(M2, "meeting_has_items")]
    assert list(report["created"]["meetings"]) == [M1]


def test_a_record_whose_url_changed_since_the_fetch_holds(tmp_path, graph):
    bundle = _bundle(tmp_path, [_entry(M1, "2026-10-06", "Fine", url_n=99)])
    report = gl.load_agenda_bundle(graph, bundle, recheck=_ok)
    assert [h["reason"] for h in report["holds"]] == ["agenda_record_changed"] and graph.overlay() == ([], [])


def test_a_record_no_longer_linked_to_the_meeting_holds(tmp_path, graph):
    entry = _entry(M1, "2026-10-06", "Fine")
    entry["record_id"] = _rid(M3)  # a real Record, but not this meeting's
    entry["url"] = AGENDA.format(3)
    for e in entry["edges"]:
        if e["type"] == "EVIDENCED_BY":
            e["end_id"] = _rid(M3)
    report = gl.load_agenda_bundle(graph, _bundle(tmp_path, [entry]), recheck=_ok)
    assert [h["reason"] for h in report["holds"]] == ["agenda_record_changed"]


def test_an_item_id_that_already_exists_holds_its_meeting(tmp_path, graph):
    entry = _entry(M1, "2026-10-06", "Fine")
    graph.add_seed_node(_node(entry["nodes"][0]["id"], ["AgendaItem"], title="someone else's"))
    report = gl.load_agenda_bundle(gl.FakeGraphPort(graph.path), _bundle(tmp_path, [entry]), recheck=_ok)
    assert [h["reason"] for h in report["holds"]] == ["item_id_exists"]


def test_a_missing_meeting_holds(tmp_path, graph):
    entry = _entry(M1, "2026-10-06", "Fine")
    entry = json.loads(json.dumps(entry).replace(M1, f"meeting-{SID}-199"))
    report = gl.load_agenda_bundle(graph, _bundle(tmp_path, [entry]), recheck=_ok)
    assert [h["reason"] for h in report["holds"]] == ["meeting_missing"]


def test_a_bundle_whose_files_changed_after_writing_is_refused(tmp_path, graph):
    bundle = _bundle(tmp_path, [_entry(M1, "2026-10-06", "Fine")])
    (bundle / "nodes.jsonl").write_text((bundle / "nodes.jsonl").read_text().replace("Fine", "Altered"))
    with pytest.raises(gl.BundleError, match="nodes.jsonl"):
        gl.load_agenda_bundle(graph, bundle, recheck=_ok)
    assert graph.overlay() == ([], [])


@pytest.mark.parametrize("tamper", [
    lambda e: e["nodes"][0].update(labels=["Decision"]),
    lambda e: e["edges"].append(_edge(e["nodes"][0]["id"], "PART_OF_MEETING", M3)),
    lambda e: e["edges"].append(_edge(e["nodes"][0]["id"], "ABOUT", M1)),
    lambda e: e["nodes"][0]["properties"].update(meeting_id=M3),
    lambda e: e["edges"].pop(),
])
def test_a_malformed_bundle_writes_nothing(tmp_path, graph, tamper):
    entry = _entry(M1, "2026-10-06", "Fine")
    tamper(entry)
    with pytest.raises(gl.BundleError):
        gl.load_agenda_bundle(graph, _bundle(tmp_path, [entry]), recheck=_ok)
    assert graph.overlay() == ([], [])


def test_the_load_rechecks_the_candidate_predicate_in_its_transaction(tmp_path, graph):
    entry = _entry(M1, "2026-10-06", "Fine")
    entry["meeting_date"] = "2026-10-06"
    calls = []

    def recheck(e, meetings):
        calls.append((e["meeting_id"], sorted(meetings)))
        return "body_unconfirmed"

    report = gl.load_agenda_bundle(graph, _bundle(tmp_path, [entry]), recheck=recheck)
    assert calls == [(M1, sorted([M1, M2, M3, M4]))]
    assert report["holds"] == [{"meeting_id": M1, "reason": "body_unconfirmed"}] and graph.overlay() == ([], [])


def test_a_concurrent_writer_rolls_the_whole_load_back(tmp_path, graph):
    bundle = _bundle(tmp_path, [_entry(M1, "2026-10-06", "Ours"), _entry(M3, "2026-09-01", "Ours too")])
    real = gl._FakeTx.create

    def create_then_interleave(self, nodes, edges):  # another writer's item lands on M1 inside our window
        real(self, nodes, edges)
        self.port._nodes["agenda-item-intruder"] = _node("agenda-item-intruder", ["AgendaItem"])
        self.port._edges.append(_edge("agenda-item-intruder", "PART_OF_MEETING", M1))

    import unittest.mock as mock

    with mock.patch.object(gl._FakeTx, "create", create_then_interleave):
        with pytest.raises(gl.GraphWriteError, match="load_conflict"):
            gl.load_agenda_bundle(graph, bundle, recheck=_ok)
    assert gl.FakeGraphPort(graph.path).overlay() == ([], [])


# --- the fetch: robots gate + host allowlist ---------------------------------------------------------


class _Spy:
    """Every TCP connection attempted; loopback ones go through, everything else is refused and recorded."""

    def __init__(self, monkeypatch):
        self.connections: list[str] = []
        real = socket.create_connection

        def connect(address, *args, **kwargs):
            self.connections.append(address[0])
            if address[0] in ("127.0.0.1", "localhost"):
                return real(address, *args, **kwargs)
            raise OSError(f"test: no network to {address[0]}")

        monkeypatch.setattr(socket, "create_connection", connect)


@pytest.fixture
def server():
    hits = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            hits.append(self.path)
            if self.path == "/redirect":
                self.send_response(302)
                self.send_header("Location", "http://forbidden.example/agenda.pdf")
                self.end_headers()
            elif self.path == "/big":
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"%PDF" + b"0" * 2000)
            else:
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"%PDF-1.4 fictional agenda")

        def log_message(self, *args):
            pass

    httpd = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_port}", hits
    httpd.shutdown()


def _gate(robots_seen):
    def robots(url, timeout):
        robots_seen.append(url)
        return rg.Reply(404, {}, b"", None)

    return rg.RobotsGate(robots_transport=robots, sleep=lambda s: None)


def test_a_fetch_reads_the_file_through_the_gate(server, monkeypatch):
    base, hits = server
    spy, seen = _Spy(monkeypatch), []
    body = ai.fetch(_gate(seen), base + "/agenda.pdf", ["127.0.0.1"])
    assert body == b"%PDF-1.4 fictional agenda" and hits == ["/agenda.pdf"]
    assert seen == [base + "/robots.txt"] and set(spy.connections) == {"127.0.0.1"}


def test_a_redirect_to_a_forbidden_host_makes_no_request_to_it(server, monkeypatch):
    base, hits = server
    spy, seen = _Spy(monkeypatch), []
    with pytest.raises(ai.AgendaHold) as held:
        ai.fetch(_gate(seen), base + "/redirect", ["127.0.0.1"])
    assert held.value.reason == "host_not_allowed"
    assert "forbidden.example" not in spy.connections and all("forbidden" not in u for u in seen)
    assert hits == ["/redirect"]


def test_a_start_url_on_a_forbidden_host_makes_no_request_at_all(monkeypatch):
    spy, seen = _Spy(monkeypatch), []
    with pytest.raises(ai.AgendaHold) as held:
        ai.fetch(_gate(seen), "http://forbidden.example/agenda.pdf", ["127.0.0.1"])
    assert held.value.reason == "host_not_allowed" and spy.connections == [] and seen == []


def test_a_disallowed_url_is_refused_without_a_request(server, monkeypatch):
    base, hits = server
    spy = _Spy(monkeypatch)
    gate = rg.RobotsGate(robots_transport=lambda url, timeout: rg.Reply(200, {}, b"User-agent: *\nDisallow: /\n", None))
    with pytest.raises(ai.AgendaHold) as held:
        ai.fetch(gate, base + "/agenda.pdf", ["127.0.0.1"])
    assert held.value.reason == "robots_disallowed" and hits == [] and spy.connections == []


def test_a_file_over_the_size_limit_holds(server, monkeypatch):
    base, _ = server
    _Spy(monkeypatch)
    with pytest.raises(ai.AgendaHold) as held:
        ai.fetch(_gate([]), base + "/big", ["127.0.0.1"], max_bytes=1000)
    assert held.value.reason == "too_large"


def test_a_failed_fetch_holds(monkeypatch):
    _Spy(monkeypatch)
    with pytest.raises(ai.AgendaHold) as held:
        ai.fetch(_gate([]), "http://127.0.0.1:9/agenda.pdf", ["127.0.0.1"])
    assert held.value.reason == "fetch_failed"


# --- review round 1 ---------------------------------------------------------------------------------------


def _ok(entry, meetings):
    return None


def test_the_recheck_is_required():
    with pytest.raises(TypeError):
        gl.load_agenda_bundle(None, Path("x"))


def test_the_candidate_predicate_is_checked_again_after_the_creates(tmp_path, graph):
    bundle = _bundle(tmp_path, [_entry(M1, "2026-10-06", "Ours")])
    calls = []

    def recheck(entry, meetings):
        calls.append(sorted(meetings[entry["meeting_id"]]["item_ids"]))
        return None if len(calls) == 1 else "other_body"  # the meeting changed inside our window

    with pytest.raises(gl.GraphWriteError, match="load_conflict"):
        gl.load_agenda_bundle(graph, bundle, recheck=recheck)
    assert calls == [[], []]  # after the creates, our own items are not "has items"
    assert gl.FakeGraphPort(graph.path).overlay() == ([], [])


def test_a_meeting_gone_after_the_creates_rolls_back(tmp_path, graph):
    bundle = _bundle(tmp_path, [_entry(M1, "2026-10-06", "Ours")])
    real = gl._FakeTx.create

    def create_then_delete(self, nodes, edges):
        real(self, nodes, edges)
        self.port._nodes.pop(M1)

    import unittest.mock as mock

    with mock.patch.object(gl._FakeTx, "create", create_then_delete):
        with pytest.raises(gl.GraphWriteError, match="load_conflict"):
            gl.load_agenda_bundle(graph, bundle, recheck=_ok)


@pytest.mark.parametrize("extra", [
    lambda item: _edge(item, "ABOUT", M3),  # another relationship
    lambda item: _edge(item, "EVIDENCED_BY", _rid(M1)),  # a duplicate
    lambda item: {**_edge(item, "PART_OF_MEETING", M1), "properties": {"page": 2}},  # same triple, other props
])
def test_already_loaded_means_exactly_the_bundles_edges(tmp_path, graph, extra):
    bundle = _bundle(tmp_path, [_entry(M1, "2026-10-06", "Ours")])
    gl.load_agenda_bundle(graph, bundle, recheck=_ok)
    item = f"agenda-item-{SID}-101-4a"
    with open(graph.path / "overlay.jsonl", "a") as fh:
        fh.write(json.dumps({"edge": extra(item)}) + "\n")
    again = gl.load_agenda_bundle(gl.FakeGraphPort(graph.path), bundle, recheck=_ok)
    assert again["already_loaded"] == [] and [h["reason"] for h in again["holds"]] == ["meeting_has_items"]


def test_a_meeting_with_no_items_is_refused_at_the_bundle(tmp_path, graph):
    entry = _entry(M1, "2026-10-06")
    assert entry["nodes"] == []
    with pytest.raises(gl.BundleError, match="no items"):
        gl.load_agenda_bundle(graph, _bundle(tmp_path, [entry]), recheck=_ok)


def test_a_truncated_response_holds(monkeypatch):
    import http.client
    import io

    class Gate:
        def open(self, request, **kw):
            class Body(io.BytesIO):
                def read(self, *a):
                    raise http.client.IncompleteRead(b"%PDF", 100)
            return Body()

    with pytest.raises(ai.AgendaHold) as held:
        ai.fetch(Gate(), AGENDA.format(1), [HOST])
    assert held.value.reason == "fetch_failed"


def test_a_meeting_listed_twice_in_a_bundle_is_refused(tmp_path, graph):
    a, b = _entry(M1, "2026-10-06", "One"), _entry(M1, "2026-10-06", "One", "Two")
    b["nodes"], b["edges"] = b["nodes"][1:], b["edges"][2:]
    with pytest.raises(gl.BundleError, match="twice"):
        gl.load_agenda_bundle(graph, _bundle(tmp_path, [a, b]), recheck=_ok)
    assert graph.overlay() == ([], [])


@pytest.mark.parametrize("files", [{}, {"nodes.jsonl": None}])
def test_a_manifest_must_hash_both_files(tmp_path, graph, files):
    bundle = _bundle(tmp_path, [_entry(M1, "2026-10-06", "One")])
    manifest = json.loads((bundle / "manifest.json").read_text())
    manifest["files"] = {k: manifest["files"][k] for k in files}
    (bundle / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(gl.BundleError, match="hash"):
        gl.load_agenda_bundle(graph, bundle, recheck=_ok)
