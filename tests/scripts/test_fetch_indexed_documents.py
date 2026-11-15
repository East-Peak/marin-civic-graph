"""Manual single-document minutes fetcher: every rule of the 2026-10-15 decision, with mocked HTTP."""
import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import fetch_indexed_documents as fid  # noqa: E402

SRC = "novato-city-council"
HOST = "https://novato.granicus.com"
PDF = b"%PDF-1.4 fictional minutes"
HTML = b"<html><body>Fictional minutes of the Pinewood Council</body></html>"
CHALLENGE = b"<html><body>Just a moment... cf-challenge</body></html>"


def _url(n):
    return f"{HOST}/MinutesViewer.php?clip_id={n}"


@pytest.fixture
def substrate(tmp_path):
    path = tmp_path / "sub.sqlite"
    db = sqlite3.connect(path)
    db.execute("create table nodes(id, type, search_label, props)")
    db.execute("create table edges(source, rel, target, props)")
    meetings = [(1, "2020-01-01", "City Council"), (2, "2021-01-01", "City Council"),
                (3, "2022-01-01", "Planning Commission"), (4, "2023-01-01", "City Council - Special")]
    for n, date, title in meetings:
        mid = f"meeting-{SRC}-{n}"
        rid = f"record-{n}"
        db.execute("insert into nodes values(?,?,?,?)", (mid, "Meeting", title,
                   json.dumps({"meeting_date": date, "title": title})))
        db.execute("insert into nodes values(?,?,?,?)", (rid, "Record", "m", json.dumps(
            {"record_type": "meeting_minutes", "preferred_public_url": _url(n).replace("https:", "")})))
        db.execute("insert into edges values(?,?,?,?)", (mid, "EVIDENCED_BY", rid, ""))
    db.commit()
    db.close()
    return path


class Net:
    """Fake clock + fake HTTP; records (time, url) per request."""

    def __init__(self, responses):
        self.responses, self.t, self.calls = dict(responses), 100.0, []

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += s

    def fetch(self, url):
        self.calls.append((self.t, url))
        resp = self.responses.get(url, (404, b"", None))
        return resp(url) if callable(resp) else resp


def run(substrate, tmp_path, net, body="council", limit=25):
    return fid.fetch_indexed(SRC, body, substrate, tmp_path / "raw", limit=limit,
                             fetch=net.fetch, sleep=net.sleep, now=net.now)


def log(tmp_path):
    p = tmp_path / "raw" / SRC / "minutes-fetch-log.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines()]


def test_candidates_newest_first_and_body_filter(substrate):
    ids = [c[0] for c in fid.candidates(substrate, SRC, "COUNCIL")]
    assert ids == [f"meeting-{SRC}-{n}" for n in (4, 2, 1)]
    assert [c[0] for c in fid.candidates(substrate, SRC, "planning")] == [f"meeting-{SRC}-3"]


def test_caches_pdf_and_html_and_logs(substrate, tmp_path):
    net = Net({_url(2): (200, PDF, None), _url(4): (200, HTML, None), _url(1): (404, b"", None)})
    run(substrate, tmp_path, net)
    d = tmp_path / "raw" / SRC / "minutes"
    assert (d / f"meeting-{SRC}-2.pdf").read_bytes() == PDF
    assert (d / f"meeting-{SRC}-4.html").read_bytes() == HTML
    assert not list(d.glob("*.tmp")) and not (d / "minutes-fetch-log.jsonl").exists()
    entries = {e["meeting_id"]: e for e in log(tmp_path)}
    e = entries[f"meeting-{SRC}-2"]
    assert e["status"] == "ok" and e["http_status"] == 200 and len(e["sha256"]) == 64
    assert e["path"] == f"meeting-{SRC}-2.pdf"  # the name minutes_text_index orders saved versions by
    assert "sha256" not in entries[f"meeting-{SRC}-1"] and entries[f"meeting-{SRC}-1"]["error"]


def test_cache_hit_makes_no_request(substrate, tmp_path):
    d = tmp_path / "raw" / SRC / "minutes"
    d.mkdir(parents=True)
    (d / f"meeting-{SRC}-4.docx").write_bytes(b"x")
    (d / f"meeting-{SRC}-3.htm").write_bytes(b"x")  # the index accepts .htm: so must the cache check
    assert fid.CACHE_EXTENSIONS == ("pdf", "html", "htm", "docx")
    net = Net({_url(2): (200, PDF, None), _url(1): (200, PDF, None)})
    run(substrate, tmp_path, net)
    assert [u for _, u in net.calls] == [_url(2), _url(1)]
    run(substrate, tmp_path, net)
    assert len(net.calls) == 2  # everything cached now


def test_throttle_between_requests_and_hops(substrate, tmp_path):
    hop = f"{HOST}/real.pdf"
    net = Net({_url(4): (302, b"", "/real.pdf"), hop: (200, PDF, None), _url(2): (200, PDF, None),
               _url(1): (200, PDF, None)})
    run(substrate, tmp_path, net)
    times = [t for t, _ in net.calls]
    assert [u for _, u in net.calls][:2] == [_url(4), hop]
    assert all(b - a >= 3.0 for a, b in zip(times, times[1:], strict=False)) and len(times) == 4
    assert (tmp_path / "raw" / SRC / "minutes" / f"meeting-{SRC}-4.pdf").exists()


@pytest.mark.parametrize("stop", [(403, b"denied", None), (429, b"", None), (200, CHALLENGE, None),
                                  (200, b"Access denied: are you a robot?", None),  # a challenge that is not HTML
                                  (200, b"<div>Checking your browser before you continue</div>", None)])
def test_whole_run_stops_on_block(substrate, tmp_path, stop):
    net = Net({_url(4): (200, PDF, None), _url(2): stop, _url(1): (200, PDF, None)})
    result = run(substrate, tmp_path, net)
    assert [u for _, u in net.calls] == [_url(4), _url(2)]
    assert result.stop_reason
    assert not (tmp_path / "raw" / SRC / "minutes" / f"meeting-{SRC}-2.pdf").exists()
    assert not (tmp_path / "raw" / SRC / "minutes" / f"meeting-{SRC}-2.html").exists()
    assert log(tmp_path)[-1]["error"]


def test_challenge_in_redirect_hop_stops_run(substrate, tmp_path):
    net = Net({_url(4): (302, b"", "/wall"), f"{HOST}/wall": (200, CHALLENGE, None)})
    assert run(substrate, tmp_path, net).stop_reason
    assert len(net.calls) == 2


def test_disallowed_redirect_host_skips_document_without_request(substrate, tmp_path):
    net = Net({_url(4): (302, b"", "https://evil.example.com/x.pdf"), _url(2): (200, PDF, None),
               _url(1): (200, PDF, None)})
    result = run(substrate, tmp_path, net)
    assert result.stop_reason is None
    assert "https://evil.example.com/x.pdf" not in [u for _, u in net.calls]
    assert not (tmp_path / "raw" / SRC / "minutes" / f"meeting-{SRC}-4.pdf").exists()
    assert "host" in log(tmp_path)[0]["error"]
    assert len(net.calls) == 3


def test_redirect_loop_is_capped(substrate, tmp_path):
    net = Net({_url(n): (302, b"", f"/loop{n}") for n in (4, 2, 1)})
    for n in (4, 2, 1):
        net.responses[f"{HOST}/loop{n}"] = (302, b"", f"/loop{n}")
    run(substrate, tmp_path, net, limit=1)
    assert len(net.calls) == fid.MAX_HOPS + 1


def test_refuses_url_not_in_substrate(substrate):
    with pytest.raises(fid.RefusedUrl):
        fid.fetch_document(SRC, f"{HOST}/ViewPublisher.php?view_id=7", substrate)
    with pytest.raises(fid.RefusedUrl):
        fid.fetch_document(SRC, "https://evil.example.com/x", substrate)


@pytest.mark.parametrize("data", [b"", b"plain text bytes", b"PK\x03\x04zip", b"\x00\x01\x02"])
def test_non_document_bytes_never_cached(substrate, tmp_path, data):
    net = Net({_url(4): (200, data, None)})
    result = run(substrate, tmp_path, net, limit=1)
    assert result.stop_reason is None
    assert not list((tmp_path / "raw").rglob("meeting-*"))
    assert log(tmp_path)[0]["error"]


def test_default_fetch_uses_no_redirects_and_honest_ua(monkeypatch):
    seen = {}

    class Resp:
        status_code, content, headers = 302, b"", {"Location": "/b"}

    def fake_get(url, **kw):
        seen.update(kw, url=url)
        return Resp()

    import requests
    monkeypatch.setattr(requests, "get", fake_get)
    assert fid.http_fetch("https://x.test/a") == (302, b"", "https://x.test/b")
    assert seen["allow_redirects"] is False
    ua = seen["headers"]["User-Agent"]
    assert ua == fid.USER_AGENT and "@" not in ua


def test_main_exits_nonzero_on_stop_and_rejects_bad_source(substrate, tmp_path, monkeypatch):
    def fake(*a, **k):
        return fid.Result(attempted=1, cached=0, stop_reason="HTTP 403")

    monkeypatch.setattr(fid, "fetch_indexed", fake)
    argv = ["--source", SRC, "--body", "council", "--substrate", str(substrate), "--raw", str(tmp_path)]
    assert fid.main(argv) == 1
    monkeypatch.setattr(fid, "fetch_indexed", lambda *a, **k: fid.Result(1, 1, None))
    assert fid.main(argv) == 0
    with pytest.raises(SystemExit):
        fid.main(["--source", "nowhere", "--body", "x"])
