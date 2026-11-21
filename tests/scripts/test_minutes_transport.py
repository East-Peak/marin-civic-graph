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
LONG_MINUTES = ("<html><head><title>Council minutes</title></head><body>"
                + "The invented Pinewood council heard public comment on many matters. " * 80
                + "One speaker asked why the permit portal shows a CAPTCHA. Access denied appeals were heard."
                + "</body></html>").encode()

ROSS = ms.SOURCE_MAP["ross-town-council"]
FAIRFAX = ms.SOURCE_MAP["fairfax-town-council"]
BELVEDERE = ms.SOURCE_MAP["belvedere-city-council"]
NOVATO = ms.SOURCE_MAP["novato-city-council"]
ROSS_ROBOTS = "https://www.townofrossca.gov/robots.txt"
ROSS_DOC = "https://www.townofrossca.gov/sites/default/files/fileattachments/town_council/meeting/1/m.pdf"
FX_DOC = "https://storage.googleapis.com/proudcity/fairfaxca/uploads/2020/12/m.pdf"
BV_DOC = "https://storage.googleapis.com/proudcity/belvedereca/uploads/2021/01/m.pdf"
NOV_DOC = "https://novato.granicus.com/MinutesViewer.php?clip_id=7"


class Net:
    """A fake epoch clock and a fake network: records (time, url, headers) for every request made. A response is
    (status, body, headers) or an Exception; `body` may be an Exception raised only after the head is seen."""

    def __init__(self, responses, t=1000.0):
        self.responses, self.t, self.calls = dict(responses), t, []

    def now(self):
        return self.t

    def sleep(self, s):
        assert s > 0
        self.t += s

    def http(self, url, headers, on_head):
        self.calls.append((self.t, url, dict(headers)))
        self.t += 0.25  # every request takes a little time
        r = self.responses.get(url, (404, b"not found", {}))
        if isinstance(r, Exception):
            raise r
        status, body, hdrs = r
        on_head(status, hdrs)
        if isinstance(body, Exception):
            raise body
        return status, body, hdrs

    def urls(self):
        return [u for _, u, _ in self.calls]


def transport(tmp_path, net, **kw):
    return mt.Transport(tmp_path, http=net.http, sleep=net.sleep, now=net.now,
                        wallclock=lambda: "2030-01-01T00:00:00Z", **kw)


def robots(text, status=200, headers=None):
    return status, text.encode(), headers or {"content-type": "text/plain"}


# --- identity, robots ---------------------------------------------------------------------------------------------

def test_one_agent_identity_for_robots_and_documents(tmp_path):
    net = Net({ROSS_ROBOTS: robots("User-agent: *\nDisallow: /private/\n"), ROSS_DOC: (200, PDF, {})})
    resp = transport(tmp_path, net).get(ROSS_DOC, ROSS)
    assert resp.status == 200 and resp.body == PDF
    assert {h["User-Agent"] for _, _, h in net.calls} == {mt.USER_AGENT} and mt.PRODUCT_TOKEN in mt.USER_AGENT
    assert net.urls() == [ROSS_ROBOTS, ROSS_DOC]


def test_robots_is_matched_for_the_agent_we_send(tmp_path):
    text = f"User-agent: *\nAllow: /\n\nUser-agent: {mt.PRODUCT_TOKEN}\nDisallow: /sites/\n"
    net = Net({ROSS_ROBOTS: robots(text), ROSS_DOC: (200, PDF, {})})
    with pytest.raises(mt.Refused) as exc:
        transport(tmp_path, net).get(ROSS_DOC, ROSS)
    assert exc.value.kind == "robots-disallowed" and "Disallow: /sites/" in str(exc.value)
    assert net.urls() == [ROSS_ROBOTS]


def test_robots_is_fetched_once_per_host_per_transport(tmp_path):
    doc2 = ROSS_DOC.replace("m.pdf", "n.pdf")
    net = Net({ROSS_ROBOTS: robots("User-agent: *\nDisallow:\n"), ROSS_DOC: (200, PDF, {}), doc2: (200, PDF, {})})
    t = transport(tmp_path, net)
    t.get(ROSS_DOC, ROSS)
    t.get(doc2, ROSS)
    assert net.urls().count(ROSS_ROBOTS) == 1


def test_granicus_documents_never_consult_robots(tmp_path):
    net = Net({NOV_DOC: (200, PDF, {})})
    transport(tmp_path, net).get(NOV_DOC, NOVATO)
    assert net.urls() == [NOV_DOC]


def test_plain_text_robots_naming_a_captcha_path_is_read_as_robots(tmp_path):
    net = Net({ROSS_ROBOTS: robots("User-agent: *\nDisallow: /captcha/\n# access denied pages\n"),
               ROSS_DOC: (200, PDF, {})})
    assert transport(tmp_path, net).get(ROSS_DOC, ROSS).status == 200


@pytest.mark.parametrize("body", [b"", b"# nothing here\n", b"\xef\xbb\xbfUser-agent: *\nDisallow:\n"])
def test_an_empty_or_comment_only_robots_is_a_valid_empty_policy(tmp_path, body):
    net = Net({ROSS_ROBOTS: (200, body, {"content-type": "text/plain; charset=utf-8"}), ROSS_DOC: (200, PDF, {})})
    assert transport(tmp_path, net).get(ROSS_DOC, ROSS).status == 200


def test_robots_absent_admits_everything(tmp_path):
    net = Net({ROSS_ROBOTS: (404, b"", {}), ROSS_DOC: (200, PDF, {})})
    assert transport(tmp_path, net).get(ROSS_DOC, ROSS).status == 200


@pytest.mark.parametrize("response", [
    (500, b"oops", {}),
    (401, b"login", {}),
    (200, b"<html><body>Welcome to the town site</body></html>", {"content-type": "text/html"}),
    (200, b"Service temporarily unavailable", {"content-type": "text/plain"}),
    (200, b"User-agent: *\nDisallow: /\n", {"content-type": "application/json"}),
    (200, b"User-agent: *\n\xff\xfe broken bytes\n", {"content-type": "text/plain"}),
    (302, b"", {}),  # a redirect without a Location
    (301, b"", {"location": "https://elsewhere.example/robots.txt"}),
    (301, b"", {"location": "https://www.townofrossca.gov/policy/robots"}),  # admitted host, not /robots.txt
    OSError("connection reset"),
])
def test_unreadable_robots_fails_closed(tmp_path, response):
    net = Net({ROSS_ROBOTS: response, ROSS_DOC: (200, PDF, {}),
               "https://www.townofrossca.gov/policy/robots": robots("User-agent: *\nDisallow:\n")})
    with pytest.raises(mt.Refused) as exc:
        transport(tmp_path, net).get(ROSS_DOC, ROSS)
    assert exc.value.kind == "robots-unreadable"
    assert net.urls() == [ROSS_ROBOTS]  # neither the document nor any redirect target was requested
    assert not (tmp_path / mt.STOPS_FILE).exists()


def test_a_robots_redirect_outside_the_publisher_path_is_never_requested(tmp_path):
    other = "https://storage.googleapis.com/other-publisher/policy"
    net = Net({"https://storage.googleapis.com/robots.txt": (302, b"", {"location": other}), other: robots("")})
    with pytest.raises(mt.Refused) as exc:
        transport(tmp_path, net).get(FX_DOC, FAIRFAX)
    assert exc.value.kind == "robots-unreadable" and other not in net.urls()


def test_robots_redirect_to_another_admitted_hosts_robots_is_followed_and_paced(tmp_path):
    src = ms.Source("t", "T", "t", ("numeric",), (
        ms.HostRule("old.example.org", None, "fixture"), ms.HostRule("www.example.net", None, "fixture")))
    net = Net({"https://old.example.org/robots.txt": (301, b"", {"location": "https://www.example.net/robots.txt"}),
               "https://www.example.net/robots.txt": robots("User-agent: *\nDisallow: /no/\n"),
               "https://old.example.org/yes.pdf": (200, PDF, {})})
    t = transport(tmp_path, net)
    assert t.get("https://old.example.org/yes.pdf", src).status == 200
    with pytest.raises(mt.Refused):
        t.get("https://old.example.org/no/x.pdf", src)


# --- canonical URLs and the wire ---------------------------------------------------------------------------------

@pytest.mark.parametrize("url", [
    "https://novato.gov\\@novato.granicus.com/a",
    "https://user:pw@novato.granicus.com/MinutesViewer.php",
    "https://novato.granicus.com:8443/MinutesViewer.php",
    "https://novato.granicus.com/public/../private/x",
    "https://NOVATO.granicus.com/MinutesViewer.php",
])
def test_non_canonical_urls_are_refused_without_a_request(tmp_path, url):
    net = Net({})
    with pytest.raises(mt.Refused) as exc:
        transport(tmp_path, net).get(url, NOVATO)
    assert exc.value.kind in ("malformed", "not-allow-listed", "off-limits") and net.calls == []


def test_the_live_client_sends_exactly_the_authorized_url_with_no_ambient_settings(monkeypatch, tmp_path):
    import requests
    sent = {}

    class Raw:
        def __init__(self):
            self.chunks = [b"%PDF-1.4 ", b"body"]

    class Resp:
        status_code = 200
        headers = {"Content-Type": "application/pdf"}

        def iter_content(self, n):
            yield from [b"%PDF-1.4 ", b"body"]

        def close(self):
            pass

    def fake_send(self, prepared, **kw):
        sent.update(kw, url=prepared.url, headers=dict(prepared.headers), trust_env=self.trust_env)
        return Resp()

    monkeypatch.setattr(requests.Session, "send", fake_send)
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid:1")
    (tmp_path / ".netrc").write_text("machine novato.granicus.com login a password b\n")
    monkeypatch.setenv("NETRC", str(tmp_path / ".netrc"))
    seen = []
    status, body, headers = mt.http_get(NOV_DOC, {"User-Agent": mt.USER_AGENT}, lambda s, h: seen.append(s))
    assert sent["url"] == NOV_DOC and sent["allow_redirects"] is False and sent["stream"] is True
    assert sent["trust_env"] is False and sent["proxies"] == {}
    assert "Authorization" not in sent["headers"] and sent["headers"]["User-Agent"] == mt.USER_AGENT
    assert seen == [200] and body == b"%PDF-1.4 body" and headers["content-type"] == "application/pdf"


def test_the_live_client_refuses_a_url_requests_would_rewrite(monkeypatch):
    import requests
    monkeypatch.setattr(requests.Session, "send", lambda *a, **k: pytest.fail("sent"))
    with pytest.raises(mt.UnsafeUrl):
        mt.http_get("https://x.granicus.com/a b", {"User-Agent": mt.USER_AGENT}, lambda s, h: None)


# --- pacing --------------------------------------------------------------------------------------------------------

def _gaps(net, family):
    times = [at for at, url, _ in net.calls if ms.host_family(url.split("/")[2]) == family]
    return [b - a for a, b in zip(times, times[1:])]


def test_pacing_spans_robots_documents_and_redirect_hops_per_family(tmp_path):
    hop = "https://novato.granicus.com/DocumentViewer.php?file=7.pdf"
    ross_hop = "https://www.townofrossca.gov/sites/default/files/fileattachments/x/2.pdf"
    net = Net({ROSS_ROBOTS: robots("User-agent: *\nDisallow:\n"),
               ROSS_DOC: (302, b"", {"location": "/sites/default/files/fileattachments/x/2.pdf"}),
               ross_hop: (200, PDF, {}), NOV_DOC: (302, b"", {"location": hop}), hop: (200, PDF, {})})
    t = transport(tmp_path, net)
    r = t.get(ROSS_DOC, ROSS)
    assert r.location == ross_hop
    t.get(r.location, ROSS, purpose="redirect")
    t.get(NOV_DOC, NOVATO)
    t.get(hop, NOVATO, purpose="redirect")
    for family in ("townofrossca.gov", "granicus.com"):
        gaps = _gaps(net, family)
        assert gaps and all(g >= mt.MIN_INTERVAL_S + 0.25 for g in gaps)  # 3 s after the previous FINISHED
    log = [json.loads(x) for x in (tmp_path / mt.REQUEST_LOG).read_text().splitlines()]
    assert [e["purpose"] for e in log if "status" in e] == ["robots", "document", "redirect", "document", "redirect"]


def test_pacing_persists_across_invocations(tmp_path):
    net = Net({NOV_DOC: (200, PDF, {})})
    transport(tmp_path, net).get(NOV_DOC, NOVATO)
    transport(tmp_path, net).get(NOV_DOC, NOVATO)  # a new process, same clock
    assert _gaps(net, "granicus.com") == [pytest.approx(mt.MIN_INTERVAL_S + 0.25)]


def test_crawl_delay_widens_the_interval_and_persists(tmp_path):
    doc2 = ROSS_DOC.replace("m.pdf", "n.pdf")
    net = Net({ROSS_ROBOTS: robots("User-agent: *\nCrawl-delay: 10\nDisallow:\n"), ROSS_DOC: (200, PDF, {}),
               doc2: (200, PDF, {})})
    transport(tmp_path, net).get(ROSS_DOC, ROSS)
    transport(tmp_path, net).get(doc2, ROSS)  # new process: re-reads robots, still 10 s apart
    assert all(g >= 10 for g in _gaps(net, "townofrossca.gov"))


# --- blocks and stops ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("response", [
    (200, CHALLENGE_HTML, {"content-type": "text/html"}),
    (200, b"User-agent: *\nDisallow:\n", {"cf-mitigated": "challenge"}),
    (200, b"<form>Password: <input type=password></form>", {}),  # a login wall: never worked around
    (403, b"forbidden", {}),
    (429, b"slow down", {}),
])
def test_a_challenge_or_block_on_robots_is_a_stop_not_an_allow(tmp_path, response):
    net = Net({ROSS_ROBOTS: response, ROSS_DOC: (200, PDF, {})})
    with pytest.raises(mt.StopNow):
        transport(tmp_path, net).get(ROSS_DOC, ROSS)
    assert net.urls() == [ROSS_ROBOTS]
    stops = json.loads((tmp_path / mt.STOPS_FILE).read_text())["stops"]
    assert [(s["host_family"], s["source"]) for s in stops] == [("townofrossca.gov", "ross-town-council")]
    assert stops[0]["at"] and stops[0]["evidence"]


@pytest.mark.parametrize("response", [
    (200, CHALLENGE_HTML, {"content-type": "text/html"}),
    (200, b"<html><body>Please complete the CAPTCHA to continue</body></html>", {}),
    (200, b"<html><head><script src='https://www.google.com/recaptcha/api.js'></script></head>"
          + b"<body>" + b"x" * 9000 + b"</body></html>", {}),
    (200, b"<html><body><form><input name=user><input type='password' name=pw></form></body></html>", {}),
    (429, b"", {}),
    (403, PDF, {}),
])
def test_a_challenge_login_or_block_on_a_document_is_a_stop(tmp_path, response):
    net = Net({NOV_DOC: response})
    with pytest.raises(mt.StopNow):
        transport(tmp_path, net).get(NOV_DOC, NOVATO)
    assert json.loads((tmp_path / mt.STOPS_FILE).read_text())["stops"][0]["host_family"] == "granicus.com"


def test_a_block_status_stops_before_the_body_is_read(tmp_path):
    net = Net({NOV_DOC: (429, TimeoutError("body never arrives"), {"retry-after": "3600"})})
    with pytest.raises(mt.StopNow):
        transport(tmp_path, net).get(NOV_DOC, NOVATO)
    stop = json.loads((tmp_path / mt.STOPS_FILE).read_text())["stops"][0]
    assert stop["status"] == 429 and "retry-after" in stop["evidence"]


@pytest.mark.parametrize("body", [PDF + b" the council discussed a captcha on the permit portal", LONG_MINUTES])
def test_minutes_that_mention_captcha_or_access_denied_are_not_challenges(tmp_path, body):
    net = Net({NOV_DOC: (200, body, {})})
    assert transport(tmp_path, net).get(NOV_DOC, NOVATO).status == 200


def test_a_stop_record_blocks_every_later_invocation_for_every_source_on_the_family(tmp_path):
    gcs_robots = "https://storage.googleapis.com/robots.txt"
    first = Net({gcs_robots: robots("User-agent: *\nDisallow:\n"), FX_DOC: (429, b"", {})})
    with pytest.raises(mt.StopNow):
        transport(tmp_path, first).get(FX_DOC, FAIRFAX)
    later = Net({gcs_robots: robots("User-agent: *\nDisallow:\n"), BV_DOC: (200, PDF, {}),
                 NOV_DOC: (200, PDF, {})}, t=first.t + 100)
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
    net = Net({NOV_DOC: (429, b"", {}), ROSS_ROBOTS: (403, b"", {})})
    t = transport(tmp_path, net)
    for url, src in ((NOV_DOC, NOVATO), (ROSS_DOC, ROSS)):
        with pytest.raises(mt.StopNow):
            t.get(url, src)
    stops = json.loads((tmp_path / mt.STOPS_FILE).read_text())["stops"]
    assert [s["host_family"] for s in stops] == ["granicus.com", "townofrossca.gov"]


def test_an_unreadable_stops_file_refuses_everything(tmp_path):
    (tmp_path / mt.STOPS_FILE).write_text("{ torn")
    net = Net({NOV_DOC: (200, PDF, {})})
    with pytest.raises(mt.Refused) as exc:
        transport(tmp_path, net).get(NOV_DOC, NOVATO)
    assert exc.value.kind == "stopped" and net.calls == []


def test_a_network_error_on_a_document_is_a_failure_not_a_stop(tmp_path):
    net = Net({NOV_DOC: OSError("timed out")})
    with pytest.raises(mt.NetworkError):
        transport(tmp_path, net).get(NOV_DOC, NOVATO)
    assert not (tmp_path / mt.STOPS_FILE).exists()


# --- allow-lists, off-limits, the window --------------------------------------------------------------------------

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
])
def test_urls_outside_the_allow_list_are_refused_without_a_request(tmp_path, url):
    net = Net({})
    with pytest.raises(mt.Refused) as exc:
        transport(tmp_path, net).get(url, FAIRFAX)
    assert exc.value.kind == "not-allow-listed" and net.calls == []


def test_the_guard_runs_before_every_wire_request_including_robots_and_after_pacing(tmp_path):
    net = Net({ROSS_ROBOTS: robots("User-agent: *\nDisallow:\n"), ROSS_DOC: (200, PDF, {})})
    checked = []

    def guard():
        checked.append(net.t)
        if len(checked) > 1:
            raise mt.Refused("window", "inside the weekly job window")

    t = transport(tmp_path, net, guard=guard)
    with pytest.raises(mt.Refused) as exc:
        t.get(ROSS_DOC, ROSS)
    assert exc.value.kind == "window" and net.urls() == [ROSS_ROBOTS]
    assert checked[1] >= net.calls[0][0] + 0.25 + mt.MIN_INTERVAL_S  # checked after the pacing sleep
