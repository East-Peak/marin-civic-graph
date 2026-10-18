"""`identity: native-only` sources (Larkspur's Archive Center): the adapter's own ids, the no-overwrite load.

A native-only source never touches the date/title identity map (scripts/meeting_identity.py): its ids are
the city's item ids. Its capture carries the load policy it was staged under, so the load can refuse a
registry that changed since. Until the guarded load supports it, a native-only capture is held there and
never reaches the ordinary MERGE loader. Fictional fixtures (Lakeport); nothing touches the network.
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
from adapters.civicplus_archive import CivicPlusArchiveAdapter  # noqa: E402
from ingest_guard import RunLedger  # noqa: E402
from meeting_identity import MeetingIdentityMap  # noqa: E402

FIXTURE = REPO / "tests" / "fixtures" / "civicplus-archive-lakeport.html"
SID = "lakeport-city-council"
INST = "org-lakeport-city-council"
PLACE = "place-lakeport"


def _config(**extra):
    return {"id": SID, "adapter": "civicplus_archive", "url": "https://www.lakeport.example/Archive.aspx?AMID=49",
            "allowed_hosts": ["www.lakeport.example"], "archive_title": "City Council Agendas",
            "jurisdiction_id": PLACE, "institution_id": INST, "backfill_from": "2019-01-01", "schedule": "manual",
            "identity": "native-only", "create_missing_stubs": True,
            "floors": {"max_newest_age_days": None}, **extra}


class _Reply:
    def __init__(self, body: bytes):
        self.body = body
        self.headers = type("H", (), {"get_content_charset": lambda self, d=None: "utf-8"})()

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _Gate:
    def __init__(self, page: str):
        self.page, self.refusals = page, []

    def open(self, request, *, timeout, handlers=(), hosts=None):
        return _Reply(self.page.encode())


def _run(root, *, config=None, page=None, identity=None):
    page = page if page is not None else FIXTURE.read_text(encoding="utf-8")
    ledger = RunLedger(root / "ledger.jsonl")
    result, verdict = ingest.run_source(config or _config(), root, ledger=ledger, today=date(2026, 10, 19),
                                        identity=identity, gate=_Gate(page))
    return result, verdict, [json.loads(line) for line in (root / "ledger.jsonl").read_text().splitlines()]


def _capture_file(root) -> Path:
    return CivicPlusArchiveAdapter(_config(), root).extracted_path()


def test_policy_helpers():
    assert cw.guarded(_config()) and cw.guarded({"identity": "crosswalk-required"}) and not cw.guarded({})
    assert not cw.required(_config())
    assert cw.load_policy(_config()) == {"identity": "native-only", "source_id": SID, "institution_id": INST,
                                         "jurisdiction_id": PLACE, "stubs": [[INST, "Organization"], [PLACE, "Place"]]}
    assert cw.load_policy(_config(create_missing_stubs=False))["stubs"] == []


def test_a_native_source_keeps_its_ids_and_pins_its_load_policy(tmp_path):
    result, verdict, ledger = _run(tmp_path)
    assert verdict.ok, verdict.reasons
    capture = json.loads(_capture_file(tmp_path).read_text())
    assert capture["identity"] == {"mode": "native-only", "meetings": 24}
    assert capture["load_policy"] == cw.load_policy(_config())
    assert all(m["adapter_meeting_id"] == m["meeting_id"] for m in capture["meetings"])
    assert "crosswalk" not in capture
    assert ledger[-1]["identity"] == "native-only" and "crosswalk_sha256" not in ledger[-1]


def test_the_identity_map_is_neither_consulted_nor_changed(tmp_path):
    cache = tmp_path / "ids.json"
    cache.write_text(json.dumps({"by_id": {f"{SID}|meeting-{SID}-adid-9533": "meeting-wrong"},
                                 "by_key": {f"{SID}|2026-10-21||october 21 2026 city council agenda": "meeting-x"},
                                 "ambiguous_keys": []}))
    before = cache.read_bytes()
    empty = tmp_path / "empty"
    empty.mkdir()
    _run(tmp_path, identity=MeetingIdentityMap(cache))
    _run(empty, identity=MeetingIdentityMap(empty / "ids.json"))
    populated = json.loads(_capture_file(tmp_path).read_text())["meetings"]
    fresh = json.loads(_capture_file(empty).read_text())["meetings"]
    assert populated == fresh and cache.read_bytes() == before and not (empty / "ids.json").exists()


def test_a_malformed_identity_cache_cannot_stop_a_native_source(tmp_path, monkeypatch):
    (tmp_path / "registry").mkdir()
    (tmp_path / "registry" / "civicplus-sources.yaml").write_text(json.dumps({"sources": [_config()]}))
    (tmp_path / "data" / "ingest-runs").mkdir(parents=True)
    (tmp_path / "data" / "ingest-runs" / "meeting-identity.json").write_text("{not json")
    monkeypatch.setattr(ingest, "RobotsGate", lambda **_: _Gate(FIXTURE.read_text(encoding="utf-8")))
    assert ingest.main(["--source", SID, "--registry", "registry/civicplus-sources.yaml", "--root", str(tmp_path)]) == 0


@pytest.mark.parametrize("bad", ["meeting-elsewhere-adid-1", "meeting-lakeport-city-council-", None])
def test_a_meeting_id_not_in_the_adapters_form_fails_closed(bad):
    with pytest.raises(cw.CrosswalkError):
        cw.native(SID, [{"meeting_id": bad}])


def test_two_meetings_with_one_id_fail_closed():
    with pytest.raises(cw.CrosswalkError, match="both"):
        cw.native(SID, [{"meeting_id": f"meeting-{SID}-adid-1"}, {"meeting_id": f"meeting-{SID}-adid-1"}])


def test_an_unresolved_row_fails_the_pull_and_names_itself(tmp_path):
    page = FIXTURE.read_text(encoding="utf-8").replace("<span>October 7, 2026, City Council Agenda",
                                                       "<span>October 7, 2026, Council Retreat")
    result, verdict, ledger = _run(tmp_path, page=page)
    assert not verdict.ok and not _capture_file(tmp_path).exists()
    assert any(r.startswith("adapter error: unresolved row ADID 9533: no_type_word") for r in ledger[-1]["reasons"])


def test_the_first_run_floor_rejects_a_partial_parse_with_no_baseline(tmp_path):
    result, verdict, ledger = _run(tmp_path, config=_config(floors={"max_newest_age_days": None, "min_rows": 25}))
    assert not verdict.ok and not _capture_file(tmp_path).exists()
    assert any("below this source's floor of 25" in r for r in verdict.reasons)


# --- the load: until the guarded load supports native-only, it holds; it never MERGE-loads -------------


def test_a_native_capture_never_reaches_the_ordinary_loader(tmp_path, monkeypatch):
    import normalize_meetings as nm
    import load_neo4j_v2
    import guarded_load as gl

    _run(tmp_path)
    root = tmp_path
    (root / "registry").mkdir(exist_ok=True)
    plain = {k: v for k, v in _config().items() if k != "identity"}  # changed after staging: still guarded
    (root / "registry" / "civicplus-sources.yaml").write_text(json.dumps({"sources": [plain]}))
    export = tmp_path / "export"
    export.mkdir()
    (export / "nodes.jsonl").write_text("")
    (export / "edges.jsonl").write_text("")
    graph = gl.FakeGraphPort.create(tmp_path / "graph", seed=export)
    monkeypatch.setenv("NEO4J_URI", f"fakegraph://{graph}")
    monkeypatch.setenv("NEO4J_USER", "neo4j")
    monkeypatch.setenv("NEO4J_PASSWORD", "unused")
    monkeypatch.setattr(load_neo4j_v2, "load_nodes", lambda *a, **k: pytest.fail("ordinary loader reached"))
    report = tmp_path / "r.json"
    assert nm.main(["--source", SID, "--capture", str(_capture_file(root)), "--root", str(root), "--load",
                    "--report", str(report)]) == 0
    assert json.loads(report.read_text())["outcome"] == "held"
    assert gl.FakeGraphPort(graph).overlay() == ([], [])
