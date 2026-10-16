"""ingest.py and the robots gate: refusals become the source's outcome; Granicus listings arrive as saved pages.

Hosts are fictional or a loopback server. Nothing here writes under the real repo (one test proves it for
a whole `ingest.py --root` subprocess).
"""
from __future__ import annotations

import hashlib
import http.server
import json
import os
import subprocess
import sys
import threading
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import ingest  # noqa: E402
import robots_gate as rg  # noqa: E402
from adapters.granicus import GranicusAdapter  # noqa: E402
from ingest_guard import RunLedger  # noqa: E402

FIXTURES = REPO / "tests" / "fixtures"
LEGACY = FIXTURES / "granicus-marin-county-bos.html"  # <!-- YYYY Start --> sections
MODERN = FIXTURES / "granicus-novato-city-council.html"  # tabbed panels
TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")
NO_FLOOR_AGE = {"max_newest_age_days": None}  # fixtures are months old


def _config(sid="townsville-council", url="https://agendas.example.test/ViewPublisher.php?view_id=3"):
    return {"id": sid, "adapter": "granicus", "url": url, "jurisdiction_id": "place-townsville",
            "institution_id": "org-townsville-council", "backfill_from": "2019-01-01", "schedule": "saved-page",
            "floors": NO_FLOOR_AGE}


def _no_network_gate():
    def refuse(url, timeout):
        raise AssertionError(f"reached for robots.txt: {url}")
    return rg.RobotsGate(robots_transport=refuse)


def _save(root: Path, sid: str, body: bytes, day: str = "2026-10-12") -> Path:
    path = root / "data" / "raw" / "manual" / day / "granicus" / f"{sid}.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return path


# --- robots refusals are the source's outcome --------------------------------------------


class _Refused:
    """An adapter whose fetch the gate refuses: raised, or swallowed into errors[] like ProudCity's detail pages."""

    swallow = False

    def __init__(self, source_config, root, *, gate):
        self.gate, self.out = gate, root / "out.json"

    def capture(self):
        try:
            self.gate.admit("https://agendas.example.test/meetings/?pager=2")
        except rg.RobotsRefused as exc:
            if not self.swallow:
                raise
            return {"meetings": [{"date": "2026-09-22"}] * 10, "errors": [str(exc)]}
        raise AssertionError("the gate admitted a disallowed URL")

    def extracted_path(self):
        return self.out


def _gate(answer):
    return rg.RobotsGate(robots_transport=lambda url, timeout: answer)


@pytest.mark.parametrize("swallow", [False, True], ids=["raised", "swallowed-by-the-adapter"])
def test_a_disallowed_request_ends_the_source_robots_disallowed_with_its_rule(tmp_path, swallow):
    adapter = type("Adapter", (_Refused,), {"swallow": swallow})
    ledger = RunLedger(tmp_path / "ledger.jsonl")
    gate = _gate(rg.Reply(200, {}, b"User-agent: *\nDisallow: /*?pager=\n", None))
    _, verdict = ingest.run_source({"id": "src", "adapter": "f"}, tmp_path, ledger=ledger, today=date(2026, 10, 12),
                                   adapter_cls=adapter, gate=gate)
    assert not verdict.ok and "Disallow: /*?pager=" in verdict.reasons[0]
    assert not (tmp_path / "out.json").exists()
    entry = ledger.latest("src")
    assert entry["ok"] is False and entry["outcome"] == "robots_disallowed"
    assert entry["robots"]["rule"] == "Disallow: /*?pager="
    assert entry["robots"]["robots_url"] == "https://agendas.example.test/robots.txt"


def test_an_unavailable_robots_txt_ends_the_source_robots_unavailable(tmp_path):
    ledger = RunLedger(tmp_path / "ledger.jsonl")
    _, verdict = ingest.run_source({"id": "src", "adapter": "f"}, tmp_path, ledger=ledger, today=date(2026, 10, 12),
                                   adapter_cls=_Refused, gate=_gate(rg.Reply(503, {}, b"", None)))
    assert not verdict.ok
    assert ledger.latest("src")["outcome"] == "robots_unavailable"
    assert ledger.latest("src")["robots"]["robots_status"] == 503


# --- the schedule ---------------------------------------------------------------------------


def test_all_never_takes_a_saved_page_source():
    sources = [{"id": "a", "schedule": "weekly"}, {"id": "b", "schedule": "saved-page"}]
    assert "saved-page" in ingest.SCHEDULES
    assert [s["id"] for s in ingest.resolve_sources(sources, all_sources=True)] == ["a"]
    assert ingest.resolve_sources(sources, source="b") == [sources[1]]


def test_every_granicus_listing_is_a_saved_page_source_because_its_robots_txt_disallows_us():
    registry = yaml.safe_load((REPO / "registry" / "granicus-sources.yaml").read_text())["sources"]
    granicus = [s for s in registry if s["adapter"] == "granicus"]
    assert len(granicus) == 5
    assert {s["schedule"] for s in granicus} == {"saved-page"}
    assert all("robots" in s["schedule_note"] for s in granicus)


# --- saved pages ----------------------------------------------------------------------------


@pytest.mark.parametrize("fixture", [LEGACY, MODERN], ids=["legacy", "modern"])
def test_a_saved_page_parses_exactly_as_the_same_bytes_fetched(tmp_path, fixture):
    body = fixture.read_bytes()
    fetched = GranicusAdapter(_config(), tmp_path / "fetched", gate=_no_network_gate())
    fetched._fetch = lambda url: body.decode("utf-8")
    saved_root = tmp_path / "saved"
    saved = GranicusAdapter(_config(), saved_root, gate=_no_network_gate(),
                            saved_page=_save(saved_root, "townsville-council", body))

    a, b = fetched.capture(), saved.capture()
    for key in ("variant", "meeting_count", "artifact_counts", "meetings", "raw_sha256"):
        assert a[key] == b[key], key
    assert a["meeting_count"] > 10
    assert (a["raw_origin"], b["raw_origin"]) == ("fetched", "saved_page")
    assert a["raw_sha256"] == hashlib.sha256(body).hexdigest()


def test_a_saved_page_is_kept_immutably_and_the_manual_file_is_left_alone(tmp_path):
    first, second = MODERN.read_bytes(), MODERN.read_bytes().replace(b"</body>", b"<!-- re-saved --></body>")
    manual = _save(tmp_path, "townsville-council", first)
    one = GranicusAdapter(_config(), tmp_path, gate=_no_network_gate(), saved_page=manual).capture()
    manual.write_bytes(second)  # Stuart saves again the same day, over the same file
    two = GranicusAdapter(_config(), tmp_path, gate=_no_network_gate(), saved_page=manual).capture()

    assert one["raw_artifact"] != two["raw_artifact"]
    for capture, body in ((one, first), (two, second)):
        copy = tmp_path / capture["raw_artifact"]
        assert copy.read_bytes() == body and capture["raw_sha256"] == hashlib.sha256(body).hexdigest()
        assert copy.name == f"saved-{capture['raw_sha256'][:16]}.html"
        assert copy.parent == tmp_path / "data" / "raw" / "townsville-council" / TODAY
        assert capture["record_refs"][0]["artifact_path"] == capture["raw_artifact"]
        assert capture["saved_page"] == {"path": "data/raw/manual/2026-10-12/granicus/townsville-council.html",
                                         "saved_on": "2026-10-12"}
    assert manual.read_bytes() == second


def test_a_saved_page_is_decoded_by_its_own_meta_charset(tmp_path):
    body = MODERN.read_bytes().replace(b'<meta charset="utf-8" />', b'<meta charset="windows-1252" />')
    body = body.replace(b"<td class=\"listItem\"", b"<td class=\"listItem\"", 1)
    title = "Caf\xe9 Licensing Hearing".encode("cp1252")
    body = body.replace(b"</title>", b" " + title + b"</title>", 1)
    capture = GranicusAdapter(_config(), tmp_path, gate=_no_network_gate(),
                              saved_page=_save(tmp_path, "townsville-council", body)).capture()
    raw = (tmp_path / capture["raw_artifact"]).read_bytes()
    assert raw == body  # the evidence copy is the saved bytes, untouched
    assert capture["meeting_count"] > 10
    assert GranicusAdapter.decode_saved_page(body).count("Café Licensing Hearing") == 1


def _registry(root: Path, *configs) -> Path:
    path = root / "registry" / "granicus-sources.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({"sources": list(configs)}))
    return path


def test_ingest_saved_page_records_the_capture_and_its_ledger_line_under_root(tmp_path):
    _registry(tmp_path, _config())
    manual = _save(tmp_path, "townsville-council", MODERN.read_bytes())
    assert ingest.main(["--root", str(tmp_path), "--source", "townsville-council", "--saved-page", str(manual)]) == 0

    capture = json.loads((tmp_path / "data" / "extracted" / "townsville-council" / f"{TODAY}.json").read_text())
    assert capture["raw_origin"] == "saved_page"
    entry = RunLedger(tmp_path / "data" / "ingest-runs" / "ledger.jsonl").latest("townsville-council")
    assert entry["ok"] is True
    assert entry["raw_origin"] == "saved_page" and entry["raw_sha256"] == capture["raw_sha256"]
    assert entry["saved_page"] == "data/raw/manual/2026-10-12/granicus/townsville-council.html"


@pytest.mark.parametrize("problem", ["elsewhere", "wrong-name", "not-a-date", "no-source", "not-granicus"])
def test_ingest_refuses_a_saved_page_outside_the_convention(tmp_path, problem, capsys):
    config = _config()
    if problem == "not-granicus":
        config["adapter"] = "proudcity"
    _registry(tmp_path, config)
    manual = _save(tmp_path, "townsville-council", MODERN.read_bytes())
    if problem == "elsewhere":
        manual = manual.rename(tmp_path / "townsville-council.html")
    elif problem == "wrong-name":
        manual = manual.rename(manual.with_name("othertown.html"))
    elif problem == "not-a-date":
        target = tmp_path / "data/raw/manual/latest/granicus/townsville-council.html"
        target.parent.mkdir(parents=True)
        manual = manual.rename(target)
    argv = ["--root", str(tmp_path), "--saved-page", str(manual)]
    argv += [] if problem == "no-source" else ["--source", "townsville-council"]
    assert ingest.main(argv) != 0
    assert "saved" in capsys.readouterr().err.lower()
    assert not (tmp_path / "data" / "extracted").exists()


# --- a whole ingest.py run in another root, against a loopback server --------------------------


class _Handler(http.server.BaseHTTPRequestHandler):
    routes: dict = {}
    seen: list = []

    def do_GET(self):
        self.seen.append((self.headers["Host"].split(":")[0], self.path))
        status, body = self.routes.get((self.headers["Host"].split(":")[0], self.path), (404, b"no"))
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def _tree(path: Path) -> dict:
    return {str(p): p.stat().st_mtime_ns for p in path.rglob("*")} if path.exists() else {}


def test_ingest_with_root_honors_the_gate_and_writes_nothing_under_the_real_root(tmp_path):
    page = MODERN.read_bytes()
    _Handler.seen = []
    _Handler.routes = {("127.0.0.1", "/robots.txt"): (200, b"User-agent: *\nDisallow: /private\n"),
                       ("127.0.0.1", "/ViewPublisher.php?view_id=3"): (200, page),
                       ("localhost", "/robots.txt"): (200, b"User-agent: *\nDisallow: /\n"),
                       ("localhost", "/ViewPublisher.php?view_id=4"): (200, page)}
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    port = httpd.server_port
    root = tmp_path / "iso"
    allowed = {**_config("allowed-town", f"http://127.0.0.1:{port}/ViewPublisher.php?view_id=3"), "schedule": "weekly"}
    refused = {**_config("refused-town", f"http://localhost:{port}/ViewPublisher.php?view_id=4"), "schedule": "weekly"}
    _registry(root, allowed, refused)
    before = {name: _tree(REPO / name) for name in ("data", "registry")}
    try:
        run = subprocess.run(
            [sys.executable, str(REPO / "scripts" / "ingest.py"), "--root", str(root), "--all",
             "--robots-cache", str(root / "run" / "robots.json"),
             "--request-log", str(root / "run" / "requests.jsonl")],
            cwd=tmp_path, capture_output=True, text=True, timeout=120,
            env={k: v for k, v in os.environ.items() if not k.startswith("OPEN_MARIN")})
    finally:
        httpd.shutdown()

    assert run.returncode == 1, run.stdout + run.stderr  # one source refused
    assert ("localhost", "/ViewPublisher.php?view_id=4") not in _Handler.seen
    assert sorted(_Handler.seen) == [("127.0.0.1", "/ViewPublisher.php?view_id=3"), ("127.0.0.1", "/robots.txt"),
                                     ("localhost", "/robots.txt")]
    ledger = RunLedger(root / "data" / "ingest-runs" / "ledger.jsonl")
    assert ledger.latest("allowed-town")["ok"] is True
    assert ledger.latest("refused-town")["outcome"] == "robots_disallowed"
    assert (root / "data" / "extracted" / "allowed-town" / f"{TODAY}.json").is_file()
    assert set(json.loads((root / "run" / "robots.json").read_text())) == {
        f"http://127.0.0.1:{port}", f"http://localhost:{port}"}
    assert len((root / "run" / "requests.jsonl").read_text().splitlines()) == 4
    assert {name: _tree(REPO / name) for name in ("data", "registry")} == before


def test_a_relative_saved_page_path_resolves_under_root_not_the_working_directory(tmp_path, monkeypatch):
    _registry(tmp_path, _config())
    _save(tmp_path, "townsville-council", MODERN.read_bytes())
    elsewhere = tmp_path.parent / f"{tmp_path.name}-cwd"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    rel = "data/raw/manual/2026-10-12/granicus/townsville-council.html"
    assert ingest.main(["--root", str(tmp_path), "--source", "townsville-council", "--saved-page", rel]) == 0


def test_a_saved_page_under_an_impossible_date_is_refused(tmp_path, capsys):
    _registry(tmp_path, _config())
    manual = _save(tmp_path, "townsville-council", MODERN.read_bytes(), day="2026-10-99")
    assert ingest.main(["--root", str(tmp_path), "--source", "townsville-council", "--saved-page", str(manual)]) == 1
