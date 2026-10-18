"""The no-overwrite load for crosswalk-required meeting sources (scripts/guarded_load.py).

An existing node or relationship is never written: no property, label, display_label or promotion_state
changes, whatever the capture says. The only writes are creates: new Meetings, new Records, and edges
touching a node created in the same load. Record identity is resolved once, for nodes and edges alike.
Anything that does not fit (a changed artifact url, a crosswalk that disagrees with the graph) holds the
whole source: nothing is written. Fixtures are fictional (Lakeport); the graph is a FakeGraphPort over a
tiny export, so nothing touches Neo4j.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import crosswalk as cw  # noqa: E402
import guarded_load as gl  # noqa: E402

SID = "lakeport-city-council"
INST = "org-lakeport-city-council"
PLACE = "place-lakeport"
XW_REL = "registry/crosswalks/lakeport-city-council.json"
PAGE = "https://www.lakeport.example/meetings/{}/"
PDF = "https://storage.example/lakeport/{}.pdf"

REG = "meeting-2020-03-02-lakeport-city-council"
CLOSED = "meeting-2020-03-02-lakeport-city-council-closed-session"
SPECIAL = "meeting-2020-03-09-lakeport-city-council-special"
REG_MIN = "record-2020-03-02-lakeport-city-council-minutes"
SPECIAL_MIN = "record-2020-03-09-lakeport-city-council-special-minutes"
ENTRIES = {"city-council-march-2-2020": REG, "city-council-march-2-2020-closed-session": CLOSED,
           "city-council-march-9-2020-special": SPECIAL}
CONFIG = {"id": SID, "adapter": "proudcity", "institution_id": INST, "jurisdiction_id": PLACE,
          "identity": "crosswalk-required", "crosswalk": XW_REL}


def _node(nid, labels, **props):
    return {"id": nid, "labels": labels, "properties": {"id": nid, **props}}


def _edge(s, rel, t):
    return {"start_id": s, "type": rel, "end_id": t, "properties": {}}


def _meeting_node(mid, slug, **props):
    base = {"institution_id": INST, "meeting_date": mid[8:18], "meeting_type": "regular_meeting",
            "title": "Lakeport City Council meeting", "display_label": "Lakeport City Council meeting",
            "promotion_state": "promoted", "meeting_page_url": PAGE.format(slug)}
    return _node(mid, ["Meeting"], **{**base, **props})


def _minutes_node(rid, url, mid):
    return _node(rid, ["Record"], record_type="minutes_pdf", source_id=f"{SID}-minutes", source_url=url,
                 meeting_id=mid, display_label="minutes", promotion_state="promoted")


SEED_NODES = [
    _node(INST, ["Government", "Organization"], name="Lakeport City Council", subtype="council",
          display_label="Lakeport City Council", promotion_state="canonical"),
    _node(PLACE, ["Place"], name="Lakeport", place_type="city", display_label="Lakeport", promotion_state="",
          source="elsewhere"),
    _meeting_node(REG, "city-council-march-2-2020"),
    _meeting_node(CLOSED, "city-council-march-2-2020-closed-session", meeting_type="closed_session"),
    _meeting_node(SPECIAL, "city-council-march-9-2020-special", meeting_type="special_meeting"),
    _minutes_node(REG_MIN, PDF.format("minutes-2020-03-02"), REG),
    _minutes_node(SPECIAL_MIN, PDF.format("minutes-2020-03-09"), SPECIAL),
    _node("meeting-2020-03-02-elsewhere", ["Meeting"], institution_id="org-elsewhere",
          meeting_page_url=PAGE.format("city-council-march-2-2020")),
    _node("agenda-item-2020-03-02-lakeport-city-council-1", ["AgendaItem"], heading="Open Session"),
]
SEED_EDGES = [
    _edge(REG, "AT_INSTITUTION", INST), _edge(CLOSED, "AT_INSTITUTION", INST), _edge(SPECIAL, "AT_INSTITUTION", INST),
    _edge(REG, "EVIDENCED_BY", REG_MIN), _edge(REG_MIN, "RELATES_TO_MEETING", REG),
    _edge(SPECIAL_MIN, "RELATES_TO_MEETING", SPECIAL),  # wave-01 linked this Record from its side only
    _edge("agenda-item-2020-03-02-lakeport-city-council-1", "PART_OF_MEETING", REG),
]


@pytest.fixture
def root(tmp_path):
    path = tmp_path / XW_REL
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"format": 1, "source_id": SID, "entries": ENTRIES}))
    return tmp_path


@pytest.fixture
def graph_dir(tmp_path):
    export = tmp_path / "export"
    export.mkdir()
    (export / "nodes.jsonl").write_text("".join(json.dumps(n) + "\n" for n in SEED_NODES))
    (export / "edges.jsonl").write_text("".join(json.dumps(e) + "\n" for e in SEED_EDGES))
    return gl.FakeGraphPort.create(tmp_path / "graph", seed=export)


def _arts(**urls):
    arts = {k: {"available": False, "url": None} for k in ("agenda", "packet", "minutes", "video")}
    arts.update({k: {"available": True, "url": u} for k, u in urls.items()})
    return arts


def _m(slug, date, title=None, **urls):
    own = cw.adapter_id(SID, slug)
    return {"meeting_id": ENTRIES.get(slug, own), "adapter_meeting_id": own, "date": date,
            "title": title or f"City Council – {date}", "meeting_type": "regular", "institution_id": INST,
            "source_url": PAGE.format(slug), "artifacts": _arts(**urls)}


def _capture(root, meetings, day="2026-10-19"):
    xw = cw.load(root / XW_REL, SID)
    return {"capture_id": f"{SID}-{day}", "source_id": SID, "adapter": "proudcity",
            "captured_at": f"{day}T12:00:00Z", "jurisdiction_id": PLACE, "institution_id": INST,
            "meetings": meetings, "meeting_count": len(meetings),
            "record_refs": [{"id": f"record-{SID}-meetings-page-{day}", "record_type": "meeting_list_page",
                             "source_id": SID, "artifact_path": f"data/raw/{SID}/{day}/source.html",
                             "captured_at": f"{day}T12:00:00Z"}],
            "crosswalk": {"path": XW_REL, "sha256": xw.sha256, "mapped": 0, "native": 0}}


def _load(root, graph_dir, capture, config=CONFIG):
    with gl.open_port(f"fakegraph://{graph_dir}") as graph:
        return gl.load_capture(graph, capture, config, root=root)


def _overlay(graph_dir):
    return gl.FakeGraphPort(graph_dir).overlay()


def _created(report, node_type):
    return report["created"]["nodes"].get(node_type, [])


LISTING = f"record-{SID}-meetings-page-2026-10-19"


# --- crosswalked meetings: a no-op ----------------------------------------------------------------------


def test_a_crosswalked_meeting_with_its_existing_minutes_loads_as_a_no_op(root, graph_dir):
    report = _load(root, graph_dir, _capture(root, [_m("city-council-march-2-2020", "2020-03-02",
                                                       minutes=PDF.format("minutes-2020-03-02"))]))
    assert report["outcome"] == "loaded" and report["holds"] == []
    assert report["created"]["nodes"] == {"Record": [LISTING]}  # only this run's listing snapshot
    assert report["created"]["edges"] == []
    nodes, edges = _overlay(graph_dir)
    assert [n["id"] for n in nodes] == [LISTING] and edges == []


def test_protected_properties_that_differ_in_the_capture_are_left_unchanged(root, graph_dir):
    m = _m("city-council-march-2-2020-closed-session", "2020-03-02", title="City Council – Closed Session")
    m["meeting_type"] = "regular"  # the adapter's guess; the graph says closed_session
    report = _load(root, graph_dir, _capture(root, [m]))
    assert report["outcome"] == "loaded"
    graph = gl.FakeGraphPort(graph_dir)
    closed = graph.nodes([CLOSED])[CLOSED]
    assert closed["props"]["meeting_type"] == "closed_session"
    assert closed["props"]["title"] == "Lakeport City Council meeting"
    assert report["protected_differences"]["Meeting.meeting_type"] == 1
    assert report["protected_differences"]["Meeting.title"] == 1


def test_shared_stubs_are_never_written(root, graph_dir):
    report = _load(root, graph_dir, _capture(root, [_m("city-council-may-4-2026", "2026-05-04")]))
    graph = gl.FakeGraphPort(graph_dir)
    stubs = graph.nodes([INST, PLACE])
    assert stubs[INST]["props"]["promotion_state"] == "canonical" and stubs[INST]["props"]["subtype"] == "council"
    assert stubs[PLACE]["props"]["promotion_state"] == "" and stubs[PLACE]["labels"] == ["Place"]
    assert report["skipped_edges"] == {"IN_JURISDICTION": 1}  # Organization -> Place: two existing nodes


def test_edges_between_two_existing_nodes_are_never_added(root, graph_dir):
    report = _load(root, graph_dir, _capture(root, [_m("city-council-march-9-2020-special", "2020-03-09",
                                                       minutes=PDF.format("minutes-2020-03-09"))]))
    _, edges = _overlay(graph_dir)
    assert edges == []  # neither Meeting->Place nor the missing Meeting->minutes direction
    assert report["skipped_edges"] == {"EVIDENCED_BY": 1, "IN_JURISDICTION": 2}


# --- new meetings and records ---------------------------------------------------------------------------


def test_an_adapter_only_meeting_loads_as_new_with_its_page_and_artifacts(root, graph_dir):
    native = cw.adapter_id(SID, "city-council-may-4-2026")
    report = _load(root, graph_dir, _capture(root, [_m("city-council-may-4-2026", "2026-05-04",
                                                       agenda=PDF.format("agenda-2026-05-04"))]))
    agenda = f"record-{SID}-{SID}-city-council-may-4-2026-agenda"
    assert _created(report, "Meeting") == [native]
    assert sorted(_created(report, "Record")) == sorted([agenda, LISTING])
    assert sorted(report["created"]["edges"]) == sorted([
        [native, "AT_INSTITUTION", INST], [native, "IN_JURISDICTION", PLACE], [native, "EVIDENCED_BY", agenda]])
    meeting = gl.FakeGraphPort(graph_dir).nodes([native])[native]
    assert meeting["props"]["meeting_page_url"] == PAGE.format("city-council-may-4-2026")
    assert meeting["props"]["promotion_state"] == "promoted"


def test_same_day_regular_and_closed_session_stay_distinct(root, graph_dir):
    report = _load(root, graph_dir, _capture(root, [
        _m("city-council-march-2-2020", "2020-03-02", agenda=PDF.format("agenda-regular")),
        _m("city-council-march-2-2020-closed-session", "2020-03-02", agenda=PDF.format("agenda-closed"))]))
    assert _created(report, "Meeting") == []
    assert sorted(_created(report, "Record")) == sorted([
        f"record-{SID}-2020-03-02-lakeport-city-council-agenda",
        f"record-{SID}-2020-03-02-lakeport-city-council-closed-session-agenda", LISTING])


def test_same_date_and_title_with_different_slugs_stay_distinct(root, graph_dir):
    title = "City Council – May 4, 2026"
    report = _load(root, graph_dir, _capture(root, [_m("city-council-may-4-2026", "2026-05-04", title),
                                                    _m("city-council-may-4-2026-2", "2026-05-04", title)]))
    assert sorted(_created(report, "Meeting")) == [cw.adapter_id(SID, "city-council-may-4-2026"),
                                                   cw.adapter_id(SID, "city-council-may-4-2026-2")]


def test_an_artifact_appearing_in_a_later_week_adds_exactly_one_record(root, graph_dir):
    week1 = _capture(root, [_m("city-council-march-2-2020", "2020-03-02")], day="2026-10-19")
    week2 = _capture(root, [_m("city-council-march-2-2020", "2020-03-02", packet=PDF.format("packet"))],
                     day="2026-10-26")
    _load(root, graph_dir, week1)
    report = _load(root, graph_dir, week2)
    packet = f"record-{SID}-2020-03-02-lakeport-city-council-packet"
    assert sorted(_created(report, "Record")) == sorted([packet, f"record-{SID}-meetings-page-2026-10-26"])
    assert report["created"]["edges"] == [[REG, "EVIDENCED_BY", packet]]


def test_a_repeated_load_writes_nothing(root, graph_dir):
    capture = _capture(root, [_m("city-council-may-4-2026", "2026-05-04", agenda=PDF.format("a")),
                              _m("city-council-march-2-2020", "2020-03-02", packet=PDF.format("p"))])
    _load(root, graph_dir, capture)
    before = _overlay(graph_dir)
    report = _load(root, graph_dir, copy.deepcopy(capture))
    assert report["outcome"] == "loaded"
    assert report["created"] == {"nodes": {}, "edges": []}
    assert _overlay(graph_dir) == before


def test_a_new_meeting_reuses_the_record_another_meeting_already_holds_for_its_url(root, graph_dir):
    report = _load(root, graph_dir, _capture(root, [_m("city-council-march-9-2020-special-regular", "2020-03-09",
                                                       minutes=PDF.format("minutes-2020-03-09"))]))
    native = cw.adapter_id(SID, "city-council-march-9-2020-special-regular")
    assert _created(report, "Record") == [LISTING]
    assert [native, "EVIDENCED_BY", SPECIAL_MIN] in report["created"]["edges"]


def test_meetings_sharing_a_new_url_share_one_record(root, graph_dir):
    shared = PDF.format("agenda-shared")
    report = _load(root, graph_dir, _capture(root, [
        _m("city-council-march-2-2020-closed-session", "2020-03-02", agenda=shared),
        _m("city-council-march-2-2020", "2020-03-02", agenda=shared)]))
    owner = f"record-{SID}-2020-03-02-lakeport-city-council-agenda"  # the smallest meeting id owns it
    assert sorted(_created(report, "Record")) == sorted([owner, LISTING])
    assert sorted(e for e in report["created"]["edges"]) == sorted([[REG, "EVIDENCED_BY", owner],
                                                                   [CLOSED, "EVIDENCED_BY", owner]])
    again = _load(root, graph_dir, _capture(root, [
        _m("city-council-march-2-2020", "2020-03-02", agenda=shared),
        _m("city-council-march-2-2020-closed-session", "2020-03-02", agenda=shared)]))
    assert again["outcome"] == "loaded" and again["created"] == {"nodes": {}, "edges": []}


# --- holds: nothing is written ----------------------------------------------------------------------------


def _held(root, graph_dir, capture, reason, config=CONFIG):
    report = _load(root, graph_dir, capture, config)
    assert report["outcome"] == "held", report
    assert reason in {h["reason"] for h in report["holds"]}, report["holds"]
    assert report["created"] == {"nodes": {}, "edges": []}
    assert _overlay(graph_dir) == ([], [])
    return report


def test_a_changed_url_for_existing_minutes_holds_the_source(root, graph_dir):
    _held(root, graph_dir, _capture(root, [_m("city-council-march-2-2020", "2020-03-02",
                                              minutes=PDF.format("minutes-2020-03-02-v2"))]), "artifact_url_changed")


def test_a_changed_url_for_a_weekly_created_record_holds_the_source(root, graph_dir):
    _load(root, graph_dir, _capture(root, [_m("city-council-march-2-2020", "2020-03-02", agenda=PDF.format("a1"))]))
    before = _overlay(graph_dir)
    report = _load(root, graph_dir, _capture(root, [_m("city-council-march-2-2020", "2020-03-02",
                                                       agenda=PDF.format("a2"))], day="2026-10-26"))
    assert report["outcome"] == "held" and report["holds"][0]["reason"] == "artifact_url_changed"
    assert _overlay(graph_dir) == before


def test_one_url_on_two_artifacts_of_a_meeting_holds(root, graph_dir):
    url = PDF.format("same")
    _held(root, graph_dir, _capture(root, [_m("city-council-may-4-2026", "2026-05-04", agenda=url, packet=url)]),
          "artifact_url_shared")


def test_one_new_url_shared_across_kinds_holds(root, graph_dir):
    url = PDF.format("same")
    _held(root, graph_dir, _capture(root, [_m("city-council-may-4-2026", "2026-05-04", agenda=url),
                                           _m("city-council-may-18-2026", "2026-05-18", packet=url)]),
          "artifact_url_shared_across_kinds")


def test_a_url_already_on_another_record_of_an_existing_meeting_holds(root, graph_dir):
    _held(root, graph_dir, _capture(root, [_m("city-council-march-2-2020-closed-session", "2020-03-02",
                                              minutes=PDF.format("minutes-2020-03-02"))]),
          "artifact_url_on_other_record")


@pytest.mark.parametrize("target", [CLOSED, "meeting-2020-03-02-elsewhere", "meeting-2020-03-02-lakeport-missing"])
def test_a_crosswalk_target_that_is_not_the_slugs_own_meeting_holds(root, graph_dir, target):
    m = _m("city-council-march-2-2020", "2020-03-02")
    m["meeting_id"] = target
    entries = {**ENTRIES, "city-council-march-2-2020": target}
    if target == CLOSED:
        entries.pop("city-council-march-2-2020-closed-session")
    (root / XW_REL).write_text(json.dumps({"format": 1, "source_id": SID, "entries": entries}))
    _held(root, graph_dir, _capture(root, [m]), "crosswalk_target_mismatch")


def test_a_mapped_meeting_whose_adapter_id_also_exists_holds(root, graph_dir):
    native = cw.adapter_id(SID, "city-council-march-2-2020")
    nodes = gl.FakeGraphPort(graph_dir)
    nodes.add_seed_node(_meeting_node(native, "city-council-march-2-2020-dup"))
    _held(root, graph_dir, _capture(root, [_m("city-council-march-2-2020", "2020-03-02")]), "duplicate_native_meeting")


def test_a_lost_crosswalk_entry_is_caught_by_the_graph(root, graph_dir):
    m = _m("city-council-march-2-2020", "2020-03-02")
    m["meeting_id"] = m["adapter_meeting_id"]  # week B: the entry vanished, the meeting arrived native
    entries = {k: v for k, v in ENTRIES.items() if k != "city-council-march-2-2020"}
    (root / XW_REL).write_text(json.dumps({"format": 1, "source_id": SID, "entries": entries}))
    _held(root, graph_dir, _capture(root, [m]), "crosswalk_entry_missing")


def test_a_capture_whose_ids_disagree_with_the_crosswalk_holds(root, graph_dir):
    m = _m("city-council-march-2-2020", "2020-03-02")
    m["meeting_id"] = m["adapter_meeting_id"]
    _held(root, graph_dir, _capture(root, [m]), "crosswalk_disagrees")


@pytest.mark.parametrize("change", ["edited", "missing", "invalid"])
def test_a_crosswalk_that_changed_since_staging_holds(root, graph_dir, change):
    capture = _capture(root, [_m("city-council-may-4-2026", "2026-05-04")])
    path = root / XW_REL
    if change == "edited":
        path.write_text(json.dumps({"format": 1, "source_id": SID, "entries": {**ENTRIES, "x": "meeting-2020-01-01-x"}}))
    elif change == "missing":
        path.unlink()
    else:
        path.write_text("{")
    _held(root, graph_dir, capture, "crosswalk_changed" if change == "edited" else "crosswalk_invalid")


def test_a_capture_made_under_a_crosswalk_never_loads_under_another_policy(root, graph_dir):
    capture = _capture(root, [_m("city-council-may-4-2026", "2026-05-04")])
    plain = {k: v for k, v in CONFIG.items() if k not in ("identity", "crosswalk")}
    _held(root, graph_dir, capture, "policy_mismatch", config=plain)


def test_a_crosswalk_source_capture_without_its_header_holds(root, graph_dir):
    capture = _capture(root, [_m("city-council-may-4-2026", "2026-05-04")])
    del capture["crosswalk"]
    _held(root, graph_dir, capture, "policy_mismatch")


def test_a_missing_shared_stub_holds_rather_than_being_created(root, graph_dir, tmp_path):
    config = {**CONFIG, "jurisdiction_id": "place-lakeport-missing"}
    capture = _capture(root, [_m("city-council-may-4-2026", "2026-05-04")])
    capture["jurisdiction_id"] = "place-lakeport-missing"
    _held(root, graph_dir, capture, "missing_node", config=config)


# --- the fake graph honours the same contract as the real one ----------------------------------------------


def test_the_fake_graph_refuses_to_create_an_existing_id(graph_dir):
    graph = gl.FakeGraphPort(graph_dir)
    with pytest.raises(gl.GraphWriteError):
        with graph.transaction() as tx:
            tx.create([{"id": REG, "labels": ["Meeting"], "properties": {"id": REG}}], [])
    assert graph.overlay() == ([], [])


def test_the_fake_uri_is_only_ever_a_directory(tmp_path):
    with pytest.raises(ValueError):
        with gl.open_port("fakegraph://relative/path"):
            pass


# --- the real port: one transaction, CREATE only ---------------------------------------------------------


class _Result(list):
    def single(self):
        return self[0]


class _ScriptedTx:
    def __init__(self, session):
        self.session, self.state = session, "open"

    def run(self, query, **params):
        self.session.queries.append(query)
        if "CREATE" in query:
            n = len(params["batch"]) - self.session.short_by
            return _Result([{"n": n}])
        if "labels(n)" in query:
            return _Result([{"id": i, "labels": self.session.graph[i][0], "props": self.session.graph[i][1]}
                            for i in params["ids"] if i in self.session.graph
                            and query.split("(n:`")[1].split("`")[0] in self.session.graph[i][0]])
        return _Result([])

    def commit(self):
        self.state = "committed"

    def rollback(self):
        self.state = "rolled back"

    def close(self):
        pass


class _ScriptedSession:
    def __init__(self, constraints, graph, short_by=0):
        self.constraints, self.graph, self.short_by = constraints, graph, short_by
        self.queries, self.txs = [], []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def run(self, query, **params):
        assert query.startswith("SHOW CONSTRAINTS")
        return [{"labelsOrTypes": [label], "properties": ["id"], "type": kind, "entityType": entity}
                for label, kind, entity in ((c, "NODE_PROPERTY_UNIQUENESS", "NODE") if isinstance(c, str) else c
                                            for c in self.constraints)]

    def begin_transaction(self):
        self.txs.append(_ScriptedTx(self))
        return self.txs[-1]


class _ScriptedDriver:
    def __init__(self, session):
        self._session = session

    def session(self, database=None):
        assert database == "neo4j"
        return self._session


def _real(session):
    return gl.Neo4jPort(_ScriptedDriver(session), "neo4j")


def test_the_real_port_refuses_to_write_without_id_constraints():
    session = _ScriptedSession(["Meeting"], {})
    with pytest.raises(gl.GraphWriteError, match="Record"):
        with _real(session).transaction():
            pass
    assert session.txs == []


@pytest.mark.parametrize("record", [("Record", "NODE_PROPERTY_EXISTENCE", "NODE"),
                                    ("Record", "NODE_PROPERTY_TYPE", "NODE"),
                                    ("Record", "RELATIONSHIP_PROPERTY_UNIQUENESS", "RELATIONSHIP")])
def test_only_a_node_uniqueness_constraint_counts(record):
    session = _ScriptedSession(["Meeting", record], {})
    with pytest.raises(gl.GraphWriteError, match="Record"):
        with _real(session).transaction():
            pass


@pytest.mark.parametrize("kind", ["UNIQUENESS", "NODE_KEY"])
def test_older_and_key_uniqueness_constraints_count(kind):
    session = _ScriptedSession(["Meeting", ("Record", kind, "NODE")], {})
    with _real(session).transaction():
        pass
    assert [t.state for t in session.txs] == ["committed"]


def test_the_real_port_creates_in_one_transaction_and_never_merges():
    session = _ScriptedSession(["Meeting", "Record", "Organization"], {INST: (["Organization"], {})})
    with _real(session).transaction() as tx:
        tx.create([{"id": "meeting-x", "labels": ["Meeting"], "properties": {"id": "meeting-x"}}],
                  [{"start_id": "meeting-x", "type": "AT_INSTITUTION", "end_id": INST, "properties": {}}])
    assert [t.state for t in session.txs] == ["committed"]
    assert not any("MERGE" in q or "SET n +=" in q for q in session.queries)
    assert any(q.startswith("UNWIND $batch AS row CREATE (n:`Meeting`)") for q in session.queries)


def test_a_create_the_graph_did_not_fully_perform_rolls_everything_back():
    session = _ScriptedSession(["Meeting", "Record"], {}, short_by=1)
    with pytest.raises(gl.GraphWriteError):
        with _real(session).transaction() as tx:
            tx.create([{"id": "meeting-x", "labels": ["Meeting"], "properties": {"id": "meeting-x"}}], [])
    assert [t.state for t in session.txs] == ["rolled back"]


def test_created_nodes_carry_no_null_properties_as_neo4j_would_store_them(root, graph_dir):
    m = _m("city-council-may-4-2026", "2026-05-04")
    m["meeting_type"] = None
    _load(root, graph_dir, _capture(root, [m]))
    nodes, _ = _overlay(graph_dir)
    assert all(v is not None for n in nodes for v in n["properties"].values())


def test_a_crosswalk_capture_cannot_grant_itself_stub_creation(root, tmp_path):
    export = tmp_path / "bare-export"
    export.mkdir()
    (export / "nodes.jsonl").write_text("".join(json.dumps(n) + "\n" for n in SEED_NODES if n["id"] not in (INST, PLACE)))
    (export / "edges.jsonl").write_text("")
    graph_dir = gl.FakeGraphPort.create(tmp_path / "bare-graph", seed=export)
    capture = _capture(root, [_m("city-council-may-4-2026", "2026-05-04")])
    capture["load_policy"] = {"stubs": [[INST, "Organization"], [PLACE, "Place"]]}
    report = _load(root, graph_dir, capture)
    assert report["outcome"] == "held" and {h["reason"] for h in report["holds"]} == {"policy_mismatch"}
    del capture["load_policy"]
    report = _load(root, graph_dir, capture)
    assert report["outcome"] == "held" and {h["reason"] for h in report["holds"]} == {"missing_node"}
    assert _overlay(graph_dir) == ([], [])
