"""Tests for scripts/robots_gate.py: the one robots.txt gate every meeting adapter goes through.

Hosts are fictional (*.example.test) or a loopback server; nothing here reaches the internet.
"""
from __future__ import annotations

import http.server
import json
import sys
import threading
import urllib.request
from pathlib import Path
from urllib.robotparser import RobotFileParser

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import robots_gate as rg  # noqa: E402

UA = "Mozilla/5.0 (compatible; MarinCivicGraph/1.0)"
HOST = "https://agendas.example.test"


# --- the parser ----------------------------------------------------------------------


def test_disallow_all_refuses_every_path_and_names_the_rule():
    robots = rg.parse("User-agent: *\nDisallow: /\n")
    assert robots.decide(f"{HOST}/ViewPublisher.php?view_id=7") == (False, "Disallow: /")
    assert robots.decide(f"{HOST}/") == (False, "Disallow: /")


def test_a_path_disallow_refuses_only_that_path():
    robots = rg.parse("User-agent: *\nCrawl-delay: 15\nDisallow: /search/\nDisallow: /login\n")
    assert robots.decide(f"{HOST}/search/council") == (False, "Disallow: /search/")
    assert robots.decide(f"{HOST}/meetings") == (True, None)
    assert robots.decide(f"{HOST}/login-help") == (False, "Disallow: /login")


def test_a_wildcard_query_disallow_matches_where_the_stdlib_parser_does_not():
    text = "User-agent: *\nDisallow: /*?pager=\n"
    robots = rg.parse(text)
    assert robots.decide(f"{HOST}/meetings/?pager=2") == (False, "Disallow: /*?pager=")
    assert robots.decide(f"{HOST}/agendas-town-council/?pager=1&x=y") == (False, "Disallow: /*?pager=")
    assert robots.decide(f"{HOST}/meetings/") == (True, None)
    assert robots.decide(f"{HOST}/meetings/?page=2") == (True, None)
    # Why the gate carries its own matcher: urllib.robotparser only prefix-matches, so it would fetch.
    stdlib = RobotFileParser()
    stdlib.parse(text.splitlines())
    assert stdlib.can_fetch(UA, f"{HOST}/meetings/?pager=2") is True


def test_an_end_anchor_matches_only_at_the_end():
    robots = rg.parse("User-agent: *\nDisallow: /*.pdf$\n")
    assert robots.decide(f"{HOST}/files/minutes.pdf")[0] is False
    assert robots.decide(f"{HOST}/files/minutes.pdf?download=1")[0] is True


def test_the_longest_match_wins_and_allow_wins_a_tie():
    robots = rg.parse("User-agent: *\nDisallow: /docs/\nAllow: /docs/public/\nAllow: /p\nDisallow: /p\n")
    assert robots.decide(f"{HOST}/docs/public/a.html") == (True, "Allow: /docs/public/")
    assert robots.decide(f"{HOST}/docs/private/a.html") == (False, "Disallow: /docs/")
    assert robots.decide(f"{HOST}/page") == (True, "Allow: /p")


def test_an_empty_disallow_is_no_rule():
    assert rg.parse("User-agent: *\nDisallow:\n").decide(f"{HOST}/anything") == (True, None)


def test_star_groups_merge_and_other_agents_groups_do_not_apply():
    robots = rg.parse(
        "User-agent: *\nDisallow: /search-site\nDisallow: /*?pager=\n\n"
        "User-agent: Applebot\nCrawl-delay: 10\nDisallow: /\n\n"
        "User-agent: Google-Extended\nDisallow: /\n\n"
        "# START PLUGIN BLOCK\nUser-agent: *\nDisallow:\n\nSitemap: https://agendas.example.test/sitemap.xml\n")
    assert robots.decide(f"{HOST}/meetings/") == (True, None)
    assert robots.decide(f"{HOST}/x?pager=3")[0] is False
    assert robots.decide(f"{HOST}/search-site/q")[0] is False
    assert robots.crawl_delay is None


def test_our_own_group_replaces_the_star_group_case_insensitively():
    robots = rg.parse("User-agent: marincivicgraph\nDisallow: /private\n\nUser-agent: *\nDisallow: /\n")
    assert robots.decide(f"{HOST}/meetings") == (True, None)
    assert robots.decide(f"{HOST}/private/x") == (False, "Disallow: /private")


def test_consecutive_agent_lines_share_a_group_and_a_sitemap_line_does_not_end_one():
    robots = rg.parse("user-agent: Crawler-A\nUser-agent: *\nDisallow: /admin\nSitemap: /sitemap.xml\n"
                      "Disallow: /RSS.aspx  # feeds\nUser-agent: Crawler-B\nCrawl-delay: 20\n")
    assert robots.decide(f"{HOST}/admin/x")[0] is False
    assert robots.decide(f"{HOST}/RSS.aspx")[0] is False
    assert robots.decide(f"{HOST}/AgendaCenter")[0] is True
    assert robots.crawl_delay is None


def test_crawl_delay_comes_from_the_selected_group():
    assert rg.parse("User-agent: *\nCrawl-delay: 15\nDisallow: /misc/\n").crawl_delay == 15.0
    assert rg.parse("User-agent: *\nCrawl-delay: soon\n").crawl_delay is None


def test_rules_before_any_agent_line_are_ignored():
    assert rg.parse("Disallow: /\nUser-agent: *\nDisallow: /x\n").decide(f"{HOST}/y") == (True, None)


# --- the gate, with a fake robots transport -------------------------------------------


class Clock:
    def __init__(self):
        self.t = 1_000.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.t += seconds


class Robots:
    """robots.txt by URL: (status, body) or (status, None, location) for a redirect; None = no answer."""

    def __init__(self, answers: dict):
        self.answers = answers
        self.asked: list[str] = []

    def __call__(self, url: str, timeout: float):
        assert timeout and timeout > 0
        self.asked.append(url)
        answer = self.answers[url]
        if answer is None:
            return rg.Reply(None, {}, b"", "timed out")
        status, body, *location = answer
        headers = {"Location": location[0]} if location else {}
        return rg.Reply(status, headers, (body or "").encode(), None)


def _gate(tmp_path, answers, clock=None, **kwargs):
    clock = clock or Clock()
    robots = Robots(answers)
    gate = rg.RobotsGate(robots_transport=robots, clock=clock, wall_clock=clock, sleep=clock.sleep,
                         request_log=tmp_path / "requests.jsonl", **kwargs)
    return gate, robots, clock


def _log(tmp_path) -> list[dict]:
    path = tmp_path / "requests.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def test_a_disallowed_url_is_refused_recorded_and_logged(tmp_path):
    gate, robots, _ = _gate(tmp_path, {f"{HOST}/robots.txt": (200, "User-agent: *\nDisallow: /\n")})
    with pytest.raises(rg.RobotsDisallowed) as refused:
        gate.admit(f"{HOST}/ViewPublisher.php?view_id=7")
    assert refused.value.outcome == "robots_disallowed"
    assert refused.value.detail["rule"] == "Disallow: /"
    assert refused.value.detail["robots_url"] == f"{HOST}/robots.txt"
    assert len(refused.value.detail["robots_sha256"]) == 64
    assert gate.refusals == [refused.value]
    kinds = [(e["kind"], e["decision"]) for e in _log(tmp_path)]
    assert kinds == [("robots", "fetched"), ("page", "disallowed")]


@pytest.mark.parametrize("status", [404, 410])
def test_an_absent_robots_txt_allows_everything(tmp_path, status):
    gate, _, _ = _gate(tmp_path, {f"{HOST}/robots.txt": (status, "not here")})
    gate.admit(f"{HOST}/anything")
    assert gate.refusals == []


@pytest.mark.parametrize("answer", [(500, "oops"), (503, ""), (403, "forbidden"), (401, ""), None],
                         ids=["500", "503", "403", "401", "timeout"])
def test_an_unreachable_or_erroring_robots_txt_skips_the_source(tmp_path, answer):
    gate, robots, _ = _gate(tmp_path, {f"{HOST}/robots.txt": answer})
    with pytest.raises(rg.RobotsUnavailable) as refused:
        gate.admit(f"{HOST}/meetings")
    assert refused.value.outcome == "robots_unavailable"
    with pytest.raises(rg.RobotsUnavailable):  # cached for the run: asked once, never retried
        gate.admit(f"{HOST}/other")
    assert robots.asked == [f"{HOST}/robots.txt"]


def test_robots_is_fetched_once_per_host_per_run_even_across_processes(tmp_path):
    answers = {f"{HOST}/robots.txt": (200, "User-agent: *\nDisallow: /private\n"),
               "https://town.example.test/robots.txt": (404, "")}
    cache = tmp_path / "robots.json"
    gate, robots, _ = _gate(tmp_path, answers, cache_path=cache)
    for path in ("/a", "/b", "/c"):
        gate.admit(f"{HOST}{path}")
    gate.admit("https://town.example.test/x")
    assert robots.asked == [f"{HOST}/robots.txt", "https://town.example.test/robots.txt"]

    later, robots_later, _ = _gate(tmp_path, answers, cache_path=cache)  # the next registry's ingest.py
    later.admit(f"{HOST}/d")
    with pytest.raises(rg.RobotsDisallowed):
        later.admit(f"{HOST}/private/e")
    assert robots_later.asked == []
    summary = later.summary()
    assert set(summary) == {HOST, "https://town.example.test"}
    assert summary[HOST]["status"] == 200 and "body" not in summary[HOST]
    assert summary[HOST]["sha256"] and summary[HOST]["fetched_at"]


def test_crawl_delay_spaces_every_request_to_that_host_including_the_robots_fetch(tmp_path):
    answers = {f"{HOST}/robots.txt": (200, "User-agent: *\nCrawl-delay: 15\n"),
               "https://town.example.test/robots.txt": (404, "")}
    gate, _, clock = _gate(tmp_path, answers)
    gate.admit(f"{HOST}/meetings")
    gate.admit(f"{HOST}/meetings/2")
    gate.admit("https://town.example.test/a")  # another host is not held back
    gate.admit("https://town.example.test/b")
    clock.t += 20  # time already passed: no wait
    gate.admit(f"{HOST}/meetings/3")
    assert clock.slept == [15.0, 15.0]
    times = [e["monotonic"] for e in _log(tmp_path) if e["url"].startswith(HOST)]
    assert all(b - a >= 15 for a, b in zip(times, times[1:]))


def test_a_redirected_robots_txt_is_followed_and_serves_its_final_host_too(tmp_path):
    answers = {"https://www.town.example.test/robots.txt": (302, None, "https://town.example.test/robots.txt"),
               "https://town.example.test/robots.txt": (200, "User-agent: *\nDisallow: /*?pager=\n")}
    gate, robots, _ = _gate(tmp_path, answers)
    gate.admit("https://www.town.example.test/council/")
    gate.admit("https://town.example.test/council/")  # where the page redirect lands
    with pytest.raises(rg.RobotsDisallowed):
        gate.admit("https://town.example.test/council/?pager=2")
    assert robots.asked == ["https://www.town.example.test/robots.txt", "https://town.example.test/robots.txt"]


def test_a_robots_redirect_loop_is_unavailable(tmp_path):
    loop = {f"{HOST}/robots.txt": (301, None, f"{HOST}/robots.txt")}
    gate, robots, _ = _gate(tmp_path, loop)
    with pytest.raises(rg.RobotsUnavailable):
        gate.admit(f"{HOST}/x")
    assert len(robots.asked) == 6  # the request plus five redirects, then it gives up


# --- the gate on a real (loopback) socket ---------------------------------------------


class _Handler(http.server.BaseHTTPRequestHandler):
    routes: dict = {}
    seen: list = []

    def do_GET(self):
        self.seen.append((self.headers["Host"], self.path))
        status, body, *location = self.routes.get(self.path, (404, "no"))
        self.send_response(status)
        if location:
            self.send_header("Location", location[0].format(port=self.server.server_port))
        self.end_headers()
        self.wfile.write(body.encode())

    def log_message(self, *args):
        pass


@pytest.fixture
def server():
    _Handler.routes, _Handler.seen = {}, []
    httpd = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd, _Handler
    httpd.shutdown()


def test_open_sends_the_request_only_after_the_gate_admits_it(tmp_path, server):
    httpd, handler = server
    handler.routes = {"/robots.txt": (200, "User-agent: *\nDisallow: /private\n"),
                      "/meetings": (200, "<html>meetings</html>"), "/private": (200, "secret")}
    base = f"http://127.0.0.1:{httpd.server_port}"
    gate = rg.RobotsGate(request_log=tmp_path / "requests.jsonl")
    with gate.open(urllib.request.Request(f"{base}/meetings", headers={"User-Agent": UA}), timeout=5) as resp:
        assert resp.read() == b"<html>meetings</html>"
    with pytest.raises(rg.RobotsDisallowed):
        gate.open(urllib.request.Request(f"{base}/private"), timeout=5)
    assert [path for _, path in handler.seen] == ["/robots.txt", "/meetings"]


def test_a_redirect_hop_to_a_disallowed_path_is_refused_before_it_is_contacted(tmp_path, server):
    httpd, handler = server
    handler.routes = {"/robots.txt": (200, "User-agent: *\nDisallow: /private\n"),
                      "/moved": (302, "", "http://localhost:{port}/private"), "/private": (200, "secret")}
    base = f"http://127.0.0.1:{httpd.server_port}"
    gate = rg.RobotsGate(request_log=tmp_path / "requests.jsonl")
    with pytest.raises(rg.RobotsDisallowed) as refused:
        gate.open(urllib.request.Request(f"{base}/moved"), timeout=5)
    assert refused.value.url.endswith("/private")
    # localhost is another origin: its robots.txt was read, its /private never requested.
    assert handler.seen == [(f"127.0.0.1:{httpd.server_port}", "/robots.txt"),
                            (f"127.0.0.1:{httpd.server_port}", "/moved"),
                            (f"localhost:{httpd.server_port}", "/robots.txt")]
    assert [e["kind"] for e in _log(tmp_path)] == ["robots", "page", "robots", "redirect"]


def test_the_default_robots_transport_reads_a_real_reply(server):
    httpd, handler = server
    handler.routes = {"/robots.txt": (200, "User-agent: *\nDisallow: /x\n")}
    reply = rg.http_get(f"http://127.0.0.1:{httpd.server_port}/robots.txt", 5)
    assert (reply.status, reply.body) == (200, b"User-agent: *\nDisallow: /x\n")
    gone = rg.http_get(f"http://127.0.0.1:{httpd.server_port}/nothing", 5)
    assert gone.status == 404
    dead = rg.http_get("http://127.0.0.1:9/robots.txt", 2)  # nothing listens on the discard port
    assert dead.status is None and dead.error


# --- review round 1 ---------------------------------------------------------------------


def test_percent_escapes_of_unreserved_characters_and_hex_case_do_not_slip_past_a_rule():
    robots = rg.parse("User-agent: *\nDisallow: /private\nDisallow: /x%aF\nDisallow: /a%2Fb\n")
    assert robots.decide(f"{HOST}/%70rivate/minutes")[0] is False
    assert robots.decide(f"{HOST}/x%AF")[0] is False
    assert robots.decide(f"{HOST}/x%af")[0] is False
    assert robots.decide(f"{HOST}/a%2fb")[0] is False
    assert robots.decide(f"{HOST}/a/b")[0] is True  # an escaped reserved "/" stays escaped


def test_a_redirect_is_paced_after_the_previous_reply_is_drained_not_before(tmp_path):
    gate, _, clock = _gate(tmp_path, {f"{HOST}/robots.txt": (200, "User-agent: *\nCrawl-delay: 15\n")})
    gate.admit(f"{HOST}/moved")  # t=1015 after the robots fetch at 1000

    class SlowBody:
        closed = False

        def read(self):
            clock.t += 20  # the redirect reply's body takes 20 s to arrive
            return b"moved"

        def close(self):
            self.closed = True
    body = SlowBody()
    request = urllib.request.Request(f"{HOST}/moved")
    rg._GatedRedirects(gate).redirect_request(request, body, 302, "Found", {}, f"{HOST}/meetings")
    assert body.closed
    times = [e["monotonic"] for e in _log(tmp_path)]
    assert times[-1] == clock.t == 1015 + 20  # stamped when the hop is sent, after the drain
    gate.admit(f"{HOST}/next")
    assert clock.t - times[-1] >= 15  # so the next request keeps its distance from the real send


def test_crawl_delay_holds_across_the_runs_processes(tmp_path):
    clock = Clock()
    answers = {f"{HOST}/robots.txt": (200, "User-agent: *\nCrawl-delay: 15\n")}
    cache = tmp_path / "robots.json"
    first, _, _ = _gate(tmp_path, answers, clock=clock, cache_path=cache)
    first.admit(f"{HOST}/a")
    second, robots, _ = _gate(tmp_path, answers, clock=clock, cache_path=cache)  # the next ingest.py
    second.admit(f"{HOST}/b")
    assert robots.asked == []
    assert clock.slept == [15.0, 15.0]


@pytest.mark.parametrize("cached_first", [True, False], ids=["destination-first", "alias-first"])
def test_a_robots_redirect_to_a_host_already_read_reuses_it(tmp_path, cached_first):
    answers = {"https://www.town.example.test/robots.txt": (301, None, "https://town.example.test/robots.txt"),
               "https://town.example.test/robots.txt": (200, "User-agent: *\nDisallow: /x\n")}
    gate, robots, _ = _gate(tmp_path, answers)
    order = ["https://town.example.test/a", "https://www.town.example.test/a"]
    for url in order if cached_first else order[::-1]:
        gate.admit(url)
    assert robots.asked.count("https://town.example.test/robots.txt") == 1
    with pytest.raises(rg.RobotsDisallowed):
        gate.admit("https://www.town.example.test/x")


class _Truncated(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200 if self.path == "/robots.txt" else 500)
        self.send_header("Content-Length", "1000")
        self.end_headers()
        self.wfile.write(b"User-agent: *\n")  # then hang up early

    def log_message(self, *args):
        pass


def test_a_truncated_robots_reply_is_unavailable_not_a_crash(tmp_path):
    httpd = http.server.HTTPServer(("127.0.0.1", 0), _Truncated)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        reply = rg.http_get(f"http://127.0.0.1:{httpd.server_port}/robots.txt", 5)
        error_body = rg.http_get(f"http://127.0.0.1:{httpd.server_port}/broken", 5)
    finally:
        httpd.shutdown()
    assert reply.status is None and reply.error == "IncompleteRead"
    assert error_body.status is None and error_body.error
