"""Body attribution, increment (b): the weekly run cannot undo the attribution.

A moved meeting re-filed under its old source (a clerk re-categorizing an agenda keeps its agenda id, so its
meeting id) or canonicalized onto a moved id by the identity map is dropped by the normalizer; a direct reload of an
old bundle that contradicts the guard is refused before any write. Fictional fixtures (Lakeport).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import body_attribution as ba  # noqa: E402
import load_neo4j_v2 as loader  # noqa: E402
import normalize_meetings as nm  # noqa: E402
from meeting_identity import MeetingIdentityMap  # noqa: E402

SOURCE = "lakeport-town-council"
COUNCIL = "org-lakeport-town-council"
HARBOR = "org-lakeport-harbor-commission"


def map_rows():
    rows = [("meeting-lakeport-town-council-10", COUNCIL, "stays"), ("meeting-lakeport-town-council-11", HARBOR, "move"),
            ("meeting-lakeport-town-council-12", COUNCIL, "held"), ("meeting-lakeport-town-council-13", HARBOR, "move"),
            ("meeting-shoreview-committees-1", "org-shoreview-planning-commission", "move")]
    return [{"id": i, "from": COUNCIL if "lakeport" in i else "org-shoreview-committees", "to": to, "rule": rule,
             "category": "x", "title": "x", "meeting_date": "2023-02-01", "reason": "x"} for i, to, rule in rows]


@pytest.fixture
def guard(tmp_path, monkeypatch):
    path = tmp_path / "guard.yaml"
    ba.write_guard_file(map_rows(), "f" * 64, path)
    monkeypatch.setattr(ba, "GUARD_PATH", path)
    return path


def capture(*meetings):
    return {"capture_id": "cap-1", "source_id": SOURCE, "adapter": "civicplus", "captured_at": "2026-10-18T12:00:00Z",
            "institution_id": COUNCIL, "jurisdiction_id": "place-lakeport", "record_refs": [],
            "meetings": [{"meeting_id": m, "title": "T", "date": "2026-10-06", "category": "Town Council",
                          "artifacts": {}} for m in meetings], "meeting_count": len(meetings)}


def test_the_guard_file_is_compact_and_names_only_moved_meetings(guard):
    data = yaml.safe_load(guard.read_text())
    assert data["map_sha256"] == "f" * 64
    assert data["sources"][SOURCE] == {"institution_id": COUNCIL, "moved": {HARBOR: [11, 13]}}
    assert ba.load_guard(guard) == {"meeting-lakeport-town-council-11": HARBOR,
                                    "meeting-lakeport-town-council-13": HARBOR,
                                    "meeting-shoreview-committees-1": "org-shoreview-planning-commission"}


def test_a_guard_id_without_a_numeric_agenda_suffix_is_refused(tmp_path):
    rows = map_rows() + [{"id": "meeting-lakeport-town-council-2026-01-01-abc", "from": COUNCIL, "to": HARBOR,
                          "rule": "move"}]
    with pytest.raises(ba.AttributionError, match="agenda id"):
        ba.write_guard_file(rows, "f" * 64, tmp_path / "g.yaml")


def test_normalize_drops_a_moved_meeting_its_old_source_lists_again(guard, tmp_path):
    nodes, edges, report = nm.normalize_source(
        capture("meeting-lakeport-town-council-10", "meeting-lakeport-town-council-11"), tmp_path / "out")
    meeting_ids = [n["id"] for n in nodes if n["node_type"] == "Meeting"]
    assert meeting_ids == ["meeting-lakeport-town-council-10"]
    assert not [e for e in edges if "meeting-lakeport-town-council-11" in (e["source_id"], e["target_id"])]
    assert report["attribution_guard"] == {"dropped": ["meeting-lakeport-town-council-11"]}
    written = (tmp_path / "out" / "nodes.jsonl").read_text()
    assert "meeting-lakeport-town-council-11" not in written


def test_an_unlisted_id_the_identity_map_canonicalizes_onto_a_moved_meeting_is_dropped(guard, tmp_path):
    """The guard is on the post-canonicalization meeting_id: a different native agenda id linked by the identity
    map's (source, date, category, title) key onto a moved meeting never re-points it."""
    cache = tmp_path / "meeting-identity.json"
    key = f"{SOURCE}|2026-10-06|town council|t"
    cache.write_text(json.dumps({"by_id": {f"{SOURCE}|meeting-lakeport-town-council-13": "meeting-lakeport-town-council-13"},
                                 "by_key": {key: "meeting-lakeport-town-council-13"}, "ambiguous_keys": []}))
    cap = capture("meeting-lakeport-town-council-99")
    MeetingIdentityMap(cache).canonicalize(SOURCE, cap["meetings"])
    assert cap["meetings"][0]["meeting_id"] == "meeting-lakeport-town-council-13"
    nodes, _, report = nm.normalize_source(cap, tmp_path / "out")
    assert not [n for n in nodes if n["node_type"] == "Meeting"]
    assert report["attribution_guard"]["dropped"] == ["meeting-lakeport-town-council-13"]


def test_without_a_guard_file_normalize_is_unchanged(tmp_path, monkeypatch):
    monkeypatch.setattr(ba, "GUARD_PATH", tmp_path / "absent.yaml")
    nodes, _, report = nm.normalize_source(capture("meeting-lakeport-town-council-11"), tmp_path / "out")
    assert [n["id"] for n in nodes if n["node_type"] == "Meeting"] == ["meeting-lakeport-town-council-11"]
    assert report["attribution_guard"] == {"dropped": []}


# --- the whole-input load preflight -------------------------------------------------------------------------------

class RecordingDriver:
    def __init__(self):
        self.runs = []

    def session(self, database=None):
        driver = self

        class S:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def run(self, query, **params):
                driver.runs.append(query)
                return type("R", (), {"single": lambda s: None, "data": lambda s: [], "__iter__": lambda s: iter([])})()
        return S()


def norm_node(nid, inst=None, node_type="Meeting"):
    props = {"title": "x"} | ({"institution_id": inst} if inst else {})
    return {"id": nid, "node_type": node_type, "labels": [node_type], "display_label": "x", "promotion_state": "p",
            "properties": props}


def test_a_contradiction_in_the_last_batch_refuses_before_any_node_write(guard):
    nodes = [norm_node(f"meeting-other-{i}", "org-other") for i in range(1200)]
    nodes.append(norm_node("meeting-lakeport-town-council-11", COUNCIL))
    driver = RecordingDriver()
    with pytest.raises(ba.AttributionError, match="meeting-lakeport-town-council-11"):
        loader.load_nodes(driver, nodes, batch_size=500)
    assert driver.runs == []


def test_an_edge_only_contradiction_refuses_before_any_edge_write(guard):
    edges = [{"source_id": "meeting-lakeport-town-council-13", "target_id": COUNCIL,
              "relationship_type": "AT_INSTITUTION", "properties": {}}]
    driver = RecordingDriver()
    with pytest.raises(ba.AttributionError, match="AT_INSTITUTION"):
        loader.load_edges(driver, edges)
    assert driver.runs == []


def test_rows_that_agree_with_the_guard_or_are_unrelated_pass(guard):
    ba.preflight([norm_node("meeting-lakeport-town-council-11", HARBOR), norm_node("meeting-other-1", COUNCIL),
                  norm_node("meeting-lakeport-town-council-11", None),
                  norm_node(HARBOR, None, node_type="Organization")],
                 [{"source_id": "meeting-lakeport-town-council-11", "target_id": HARBOR,
                   "relationship_type": "AT_INSTITUTION"},
                  {"source_id": "meeting-lakeport-town-council-11", "target_id": "record-1",
                   "relationship_type": "EVIDENCED_BY"}])


def test_normalize_load_preflights_the_whole_source_before_the_fake_merge(guard, tmp_path, monkeypatch):
    import guarded_load as gl

    root = tmp_path / "root"
    (root / "registry").mkdir(parents=True)
    (root / "registry" / "civicplus-sources.yaml").write_text(yaml.safe_dump({"sources": [
        {"id": SOURCE, "adapter": "civicplus", "url": "https://www.lakeport.example/AgendaCenter",
         "institution_id": COUNCIL, "jurisdiction_id": "place-lakeport", "schedule": "weekly"}]}))
    path = root / "data" / "extracted" / SOURCE / "2026-10-18.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(capture("meeting-lakeport-town-council-10")))
    seed = tmp_path / "seed"
    seed.mkdir()
    (seed / "nodes.jsonl").write_text("")
    (seed / "edges.jsonl").write_text("")
    graph = gl.FakeGraphPort.create(tmp_path / "graph", seed=seed)
    monkeypatch.setenv("NEO4J_URI", f"fakegraph://{graph}")

    def refuse(nodes, edges):
        raise ba.AttributionError("preflight saw the whole source")

    monkeypatch.setattr(ba, "preflight", refuse)
    with pytest.raises(ba.AttributionError, match="whole source"):
        nm.main(["--source", SOURCE, "--capture", str(path), "--load", "--root", str(root)])
    assert (graph / "overlay.jsonl").read_text() == ""


# --- the identity cache --------------------------------------------------------------------------------------------

def test_identity_check_flags_any_cache_entry_that_could_re_map_onto_a_moved_meeting(guard, tmp_path):
    guarded = ba.load_guard(guard)
    clean = {"by_id": {f"{SOURCE}|meeting-lakeport-town-council-11": "meeting-lakeport-town-council-11"},
             "by_key": {f"{SOURCE}|2023-02-01|harbor commission|agenda": "meeting-lakeport-town-council-11"},
             "ambiguous_keys": []}
    assert ba.identity_problems(clean, guarded, {SOURCE: ["Town Council"]}) == []
    foreign = json.loads(json.dumps(clean))
    foreign["by_id"][f"{SOURCE}|meeting-lakeport-town-council-77"] = "meeting-lakeport-town-council-11"
    own_key = json.loads(json.dumps(clean))
    own_key["by_key"][f"{SOURCE}|2023-02-01|town council|agenda"] = "meeting-lakeport-town-council-11"
    for cache, match in ((foreign, "meeting-lakeport-town-council-77"), (own_key, "town council")):
        problems = ba.identity_problems(cache, guarded, {SOURCE: ["Town Council"]})
        assert problems and match in problems[0]
