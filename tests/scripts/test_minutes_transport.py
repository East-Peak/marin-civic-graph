"""Minutes coverage: the one transport every request goes through (mocked network; fictional hosts and text)."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import minutes_sources as ms  # noqa: E402
import minutes_transport as mt  # noqa: E402

PDF = b"%PDF-1.4 fictional minutes of the Pinewood council"
CHALLENGE_HTML = b"<!doctype html><html><head><title>Just a moment...</title></head><body>cf-challenge</body></html>"

ROSS = ms.SOURCE_MAP["ross-town-council"]
FAIRFAX = ms.SOURCE_MAP["fairfax-town-council"]
BELVEDERE = ms.SOURCE_MAP["belvedere-city-council"]
NOVATO = ms.SOURCE_MAP["novato-city-council"]
ROSS_DOC = "https://www.townofrossca.gov/sites/default/files/fileattachments/town_council/meeting/1/m.pdf"
FX_DOC = "https://storage.googleapis.com/proudcity/fairfaxca/uploads/2020/12/m.pdf"
BV_DOC = "https://storage.googleapis.com/proudcity/belvedereca/uploads/2021/01/m.pdf"
NOV_DOC = "https://novato.granicus.com/MinutesViewer.php?clip_id=7"


class Net:
    """A fake clock and a fake network: records (time, url, headers) for every request made."""

    def __init__(self, responses):
        self.responses, self.t, self.calls = dict(responses), 1000.0, []

    def now(self):
        return self.t

    def sleep(self, s):
        assert s > 0
        self.t += s

    def http(self, url, headers):
        self.calls.append((self.t, url, dict(headers)))
        self.t += 0.25  # every request takes a little time
        r = self.responses.get(url, (404, b"not found", {}))
        if isinstance(r, Exception):
            raise r
        return r

    def urls(self):
        return [u for _, u, _ in self.calls]


def transport(tmp_path, net):
    return mt.Transport(tmp_path, http=net.http, sleep=net.sleep, now=net.now, wallclock=lambda: "2030-01-01T00:00:00Z")


def robots(text, status=200, headers=None):
    return status, text.encode(), headers or {"content-type": "text/plain"}


def test_one_agent_identity_for_robots_and_documents(tmp_path):
    net = Net({"https://www.townofrossca.gov/robots.txt": robots("User-agent: *\nDisallow: /private/\n"),
               ROSS_DOC: (200, PDF, {})})
    resp = transport(tmp_path, net).get(ROSS_DOC, ROSS)
    assert resp.status == 200 and resp.body == PDF
    agents = {h["User-Agent"] for _, _, h in net.calls}
    assert agents == {mt.USER_AGENT} and mt.PRODUCT_TOKEN in mt.USER_AGENT
    assert net.urls() == ["https://www.townofrossca.gov/robots.txt", ROSS_DOC]


def test_robots_is_matched_for_the_agent_we_send(tmp_path):
    text = f"User-agent: *\nAllow: /\n\nUser-agent: {mt.PRODUCT_TOKEN}\nDisallow: /sites/\n"
    net = Net({"https://www.townofrossca.gov/robots.txt": robots(text), ROSS_DOC: (200, PDF, {})})
    with pytest.raises(mt.Refused) as exc:
        transport(tmp_path, net).get(ROSS_DOC, ROSS)
    assert exc.value.kind == "robots-disallowed" and "Disallow: /sites/" in str(exc.value)
    assert net.urls() == ["https://www.townofrossca.gov/robots.txt"]


def test_robots_is_fetched_once_per_host_per_transport(tmp_path):
    doc2 = ROSS_DOC.replace("m.pdf", "n.pdf")
    net = Net({"https://www.townofrossca.gov/robots.txt": robots("User-agent: *\nDisallow:\n"),
               ROSS_DOC: (200, PDF, {}), doc2: (200, PDF, {})})
    t = transport(tmp_path, net)
    t.get(ROSS_DOC, ROSS)
    t.get(doc2, ROSS)
    assert net.urls().count("https://www.townofrossca.gov/robots.txt") == 1


def test_pacing_spans_robots_documents_and_redirect_hops_per_family(tmp_path):
    hop = "https://novato.granicus.com/DocumentViewer.php?file=7.pdf"
    net = Net({"https://www.townofrossca.gov/robots.txt": robots("User-agent: *\nDisallow:\n"),
               ROSS_DOC: (302, b"", {"location": "/sites/default/files/fileattachments/x/2.pdf"}),
               "https://www.townofrossca.gov/sites/default/files/fileattachments/x/2.pdf": (200, PDF, {}),
               NOV_DOC: (302, b"", {"location": hop}), hop: (200, PDF, {})})
    t = transport(tmp_path, net)
    r = t.get(ROSS_DOC, ROSS)
    assert r.location == "https://www.townofrossca.gov/sites/default/files/fileattachments/x/2.pdf"
    t.get(r.location, ROSS, purpose="redirect")
    t.get(NOV_DOC, NOVATO)
    t.get(hop, NOVATO, purpose="redirect")
    by_family: dict[str, list[float]] = {}
    for at, url, _ in net.calls:
        by_family.setdefault(ms.host_family(url.split("/")[2]), []).append(at)
    assert set(by_family) == {"townofrossca.gov", "granicus.com"}
    for times in by_family.values():
        # each request starts >= 3 s after the previous one to the family FINISHED (0.25 s each here)
        assert all(b - a >= mt.MIN_INTERVAL_S + 0.25 for a, b in zip(times, times[1:]))
    log = [json.loads(x) for x in (tmp_path / mt.REQUEST_LOG).read_text().splitlines()]
    assert [e["purpose"] for e in log if "status" in e] == ["robots", "document", "redirect", "document", "redirect"]


def test_granicus_documents_never_consult_robots(tmp_path):
    net = Net({NOV_DOC: (200, PDF, {})})
    transport(tmp_path, net).get(NOV_DOC, NOVATO)
    assert net.urls() == [NOV_DOC]


@pytest.mark.parametrize("response", [
    (200, CHALLENGE_HTML, {"content-type": "text/html"}),
    (200, b"User-agent: *\nDisallow:\n", {"cf-mitigated": "challenge"}),
    (403, b"forbidden", {}),
    (429, b"slow down", {}),
])
def test_a_challenge_or_block_on_robots_is_a_stop_not_an_allow(tmp_path, response):
    net = Net({"https://www.townofrossca.gov/robots.txt": response, ROSS_DOC: (200, PDF, {})})
    with pytest.raises(mt.StopNow):
        transport(tmp_path, net).get(ROSS_DOC, ROSS)
    assert net.urls() == ["https://www.townofrossca.gov/robots.txt"]
    stops = json.loads((tmp_path / mt.STOPS_FILE).read_text())["stops"]
    assert [(s["host_family"], s["source"]) for s in stops] == [("townofrossca.gov", "ross-town-council")]
    assert stops[0]["at"] and stops[0]["evidence"]


@pytest.mark.parametrize("response", [
    (200, CHALLENGE_HTML, {"content-type": "text/html"}),
    (200, b"<html><body>Please complete the CAPTCHA to continue</body></html>", {}),
    (429, b"", {}),
    (403, PDF, {}),
])
def test_a_challenge_or_block_on_a_document_is_a_stop(tmp_path, response):
    net = Net({NOV_DOC: response})
    with pytest.raises(mt.StopNow):
        transport(tmp_path, net).get(NOV_DOC, NOVATO)
    assert json.loads((tmp_path / mt.STOPS_FILE).read_text())["stops"][0]["host_family"] == "granicus.com"


def test_a_pdf_that_mentions_captcha_is_not_a_challenge(tmp_path):
    net = Net({NOV_DOC: (200, PDF + b" the council discussed a captcha on the permit portal", {})})
    assert transport(tmp_path, net).get(NOV_DOC, NOVATO).status == 200


def test_plain_text_robots_naming_a_captcha_path_is_read_as_robots(tmp_path):
    net = Net({"https://www.townofrossca.gov/robots.txt": robots("User-agent: *\nDisallow: /captcha/\n"),
               ROSS_DOC: (200, PDF, {})})
    assert transport(tmp_path, net).get(ROSS_DOC, ROSS).status == 200


@pytest.mark.parametrize("response", [
    (500, b"oops", {}),
    (200, b"<html><body>Welcome to the town site</body></html>", {"content-type": "text/html"}),
    OSError("connection reset"),
    (301, b"", {"location": "https://elsewhere.example/robots.txt"}),
])
def test_unreadable_robots_fails_closed(tmp_path, response):
    net = Net({"https://www.townofrossca.gov/robots.txt": response, ROSS_DOC: (200, PDF, {})})
    with pytest.raises(mt.Refused) as exc:
        transport(tmp_path, net).get(ROSS_DOC, ROSS)
    assert exc.value.kind == "robots-unreadable"
    assert ROSS_DOC not in net.urls() and "https://elsewhere.example/robots.txt" not in net.urls()
    assert not (tmp_path / mt.STOPS_FILE).exists()


def test_robots_absent_admits_everything(tmp_path):
    net = Net({"https://www.townofrossca.gov/robots.txt": (404, b"", {}), ROSS_DOC: (200, PDF, {})})
    assert transport(tmp_path, net).get(ROSS_DOC, ROSS).status == 200


def test_robots_redirect_to_an_allow_listed_host_is_followed_and_paced(tmp_path):
    src = ms.Source("t", "T", "t", ("numeric",), (
        ms.HostRule("old.example.org", None, "fixture"), ms.HostRule("www.example.org", None, "fixture")))
    net = Net({"https://old.example.org/robots.txt": (301, b"", {"location": "https://www.example.org/robots.txt"}),
               "https://www.example.org/robots.txt": robots("User-agent: *\nDisallow: /no/\n"),
               "https://old.example.org/yes.pdf": (200, PDF, {})})
    t = transport(tmp_path, net)
    assert t.get("https://old.example.org/yes.pdf", src).status == 200
    with pytest.raises(mt.Refused):
        t.get("https://old.example.org/no/x.pdf", src)
    times = [at for at, _, _ in net.calls]
    assert all(b - a >= mt.MIN_INTERVAL_S for a, b in zip(times, times[1:]))


@pytest.mark.parametrize("url", ["https://www.novato.gov/minutes.pdf", "https://www.marincounty.gov/x.pdf"])
def test_off_limits_hosts_are_refused_without_a_request(tmp_path, url):
    src = ms.Source("t", "T", "t", ("numeric",), ())
    object.__setattr__(src, "doc_hosts", (ms.HostRule(url.split("/")[2], None, "a mistaken rule"),))
    net = Net({})
    with pytest.raises(mt.Refused) as exc:
        transport(tmp_path, net).get(url, src)
    assert exc.value.kind == "off-limits" and net.calls == []


@pytest.mark.parametrize("url", [
    "https://storage.googleapis.com/proudcity/belvedereca/uploads/x.pdf",  # another publisher's folder
    "https://storage.googleapis.com/proudcity/2024/03/x.pdf",              # no publisher folder at all
    "https://unknown.example/x.pdf",
    "http://storage.googleapis.com/proudcity/fairfaxca/x.pdf",
])
def test_urls_outside_the_allow_list_are_refused_without_a_request(tmp_path, url):
    net = Net({})
    with pytest.raises(mt.Refused) as exc:
        transport(tmp_path, net).get(url, FAIRFAX)
    assert exc.value.kind == "not-allow-listed" and net.calls == []


def test_a_stop_record_blocks_every_later_invocation_for_every_source_on_the_family(tmp_path):
    gcs_robots = "https://storage.googleapis.com/robots.txt"
    first = Net({gcs_robots: robots("User-agent: *\nDisallow:\n"), FX_DOC: (429, b"", {})})
    with pytest.raises(mt.StopNow):
        transport(tmp_path, first).get(FX_DOC, FAIRFAX)
    later = Net({gcs_robots: robots("User-agent: *\nDisallow:\n"), BV_DOC: (200, PDF, {}),
                 NOV_DOC: (200, PDF, {})})
    t = transport(tmp_path, later)  # a new process: only the stops file carries the stop
    with pytest.raises(mt.Refused) as exc:
        t.get(BV_DOC, BELVEDERE)
    assert exc.value.kind == "stopped" and later.calls == []
    assert t.get(NOV_DOC, NOVATO).status == 200  # another family continues
    assert t.stopped("storage.googleapis.com")["source"] == "fairfax-town-council"


def test_a_stop_written_by_another_process_mid_run_is_honoured(tmp_path):
    net = Net({NOV_DOC: (200, PDF, {})})
    t = transport(tmp_path, net)
    t.get(NOV_DOC, NOVATO)
    (tmp_path / mt.STOPS_FILE).write_text(json.dumps({"stops": [
        {"host_family": "granicus.com", "source": "marin-county-bos", "at": "x", "url": "u", "status": 429,
         "evidence": "fixture"}]}))
    with pytest.raises(mt.Refused):
        t.get(NOV_DOC, NOVATO)
    assert len(net.calls) == 1


def test_stops_accumulate_and_are_never_cleared(tmp_path):
    net = Net({NOV_DOC: (429, b"", {}), "https://www.townofrossca.gov/robots.txt": (403, b"", {})})
    t = transport(tmp_path, net)
    for url, src in ((NOV_DOC, NOVATO), (ROSS_DOC, ROSS)):
        with pytest.raises(mt.StopNow):
            t.get(url, src)
    stops = json.loads((tmp_path / mt.STOPS_FILE).read_text())["stops"]
    assert [s["host_family"] for s in stops] == ["granicus.com", "townofrossca.gov"]


def test_a_network_error_on_a_document_is_a_failure_not_a_stop(tmp_path):
    net = Net({NOV_DOC: OSError("timed out")})
    with pytest.raises(mt.NetworkError):
        transport(tmp_path, net).get(NOV_DOC, NOVATO)
    assert not (tmp_path / mt.STOPS_FILE).exists()


def test_the_default_http_follows_no_redirects_and_sends_the_agent(monkeypatch):
    seen = {}

    class Resp:
        status_code, content, headers = 302, b"", {"Location": "/next", "Content-Type": "text/html"}

    def fake_get(url, **kw):
        seen.update(kw, url=url)
        return Resp()

    import requests
    monkeypatch.setattr(requests, "get", fake_get)
    status, body, headers = mt.http_get("https://x.example/a", {"User-Agent": mt.USER_AGENT})
    assert seen["allow_redirects"] is False and seen["headers"]["User-Agent"] == mt.USER_AGENT
    assert status == 302 and headers["location"] == "/next"
