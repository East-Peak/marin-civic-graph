"""Bounded network waits for every source fetch, and a bounded retry for transient failures.

The 2026-09-28 weekly run lost CourtListener to one ReadTimeout. A second try would
have fixed it; a fetch with no timeout at all could have hung the whole run. Every
transport here is a fake: nothing touches the network.
"""
from __future__ import annotations

import ast
import io
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest
import requests

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import ingest_courtlistener_cases  # noqa: E402
import ingest_form700  # noqa: E402
import ingest_socrata_permits  # noqa: E402
import net_retry  # noqa: E402
from adapters import civicplus, drupal_ross, granicus, netfile, proudcity  # noqa: E402

FETCHING_MODULES = [*sorted((SCRIPTS / "adapters").glob("*.py")),
                    SCRIPTS / "ingest_socrata_permits.py", SCRIPTS / "ingest_form700.py",
                    SCRIPTS / "ingest_courtlistener_cases.py"]


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr(net_retry, "sleep", slept.append)
    return slept


def _http_error(code: int, headers: dict | None = None) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://example.test", code, "status", headers or {}, io.BytesIO())


def _requests_error(code: int, headers: dict | None = None) -> requests.HTTPError:
    response = requests.Response()
    response.status_code = code
    response.headers.update(headers or {})
    return requests.HTTPError(f"{code}", response=response)


# --- what counts as transient ------------------------------------------------


@pytest.mark.parametrize("exc", [
    TimeoutError("timed out"),
    ConnectionResetError("reset by peer"),
    ConnectionRefusedError("refused"),
    urllib.error.URLError(TimeoutError("timed out")),
    urllib.error.URLError(ConnectionResetError("reset")),
    _http_error(502), _http_error(503),
    requests.ReadTimeout("Read timed out. (read timeout=30)"),
    requests.ConnectTimeout("connect timed out"),
    requests.ConnectionError("Connection aborted."),
    _requests_error(500),
])
def test_timeouts_dropped_connections_and_5xx_are_transient(exc):
    assert net_retry.is_transient(exc)


@pytest.mark.parametrize("exc", [
    _http_error(404), _http_error(403), _http_error(429),
    _requests_error(400), _requests_error(404),
    urllib.error.URLError("unknown url type: htp"),
    ValueError("bad json"), KeyError("results"),
])
def test_4xx_and_everything_else_is_not(exc):
    assert not net_retry.is_transient(exc)


# --- the retry itself ----------------------------------------------------------


def _flaky(*failures: BaseException, result="ok"):
    calls = []

    @net_retry.retry_transient
    def fetch():
        calls.append(1)
        if len(calls) <= len(failures):
            raise failures[len(calls) - 1]
        return result
    return fetch, calls


def test_a_transient_failure_is_retried_with_backoff_until_it_succeeds(no_sleep, capsys):
    fetch, calls = _flaky(TimeoutError("timed out"), _http_error(503))

    assert fetch() == "ok"
    assert len(calls) == 3 and no_sleep == [2, 4]
    assert "retry 2/3" in capsys.readouterr().err


def test_retries_stop_after_three_attempts_and_the_last_failure_propagates(no_sleep):
    fetch, calls = _flaky(TimeoutError("1"), TimeoutError("2"), TimeoutError("3"))

    with pytest.raises(TimeoutError, match="3"):
        fetch()
    assert len(calls) == 3


@pytest.mark.parametrize("exc", [_http_error(404), _requests_error(403), ValueError("parse")])
def test_a_client_error_or_a_bug_is_never_retried(exc, no_sleep):
    fetch, calls = _flaky(exc)

    with pytest.raises(type(exc)):
        fetch()
    assert len(calls) == 1 and no_sleep == []


# --- 429: the server says how long to wait -------------------------------------
# The 2026-09-29 weekly run lost CourtListener to a 429 mid-pagination. A throttle
# that names a short wait is honoured once the wait is over; one with no wait, or a
# wait past the cap, is a quota problem a retry can't fix, so it fails as before.


@pytest.mark.parametrize("exc", [_requests_error(429, {"Retry-After": "30"}),
                                 _http_error(429, {"Retry-After": "30"})])
def test_a_429_naming_a_short_wait_is_transient(exc):
    assert net_retry.is_transient(exc)
    assert net_retry.retry_after_secs(exc) == 30


@pytest.mark.parametrize("headers", [{}, {"Retry-After": str(net_retry.RETRY_AFTER_CAP_SECS + 1)},
                                     {"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"},
                                     {"Retry-After": "-5"}, {"Retry-After": "\u00b2"},
                                     {"Retry-After": "9" * 5000}, {"Retry-After": "1.5"}])
def test_a_429_with_no_usable_short_wait_is_not_retried(headers, no_sleep):
    fetch, calls = _flaky(_requests_error(429, headers))

    with pytest.raises(requests.HTTPError):
        fetch()
    assert len(calls) == 1 and no_sleep == []


def test_a_retried_429_waits_exactly_as_long_as_the_server_asked(no_sleep):
    fetch, calls = _flaky(_requests_error(429, {"Retry-After": "45"}))

    assert fetch() == "ok"
    assert len(calls) == 2 and no_sleep == [45]


@pytest.mark.parametrize("raw, secs", [("0", 0), ("120", 120), (" 7 ", 7)])
def test_the_retry_after_bounds_are_inclusive(raw, secs):
    assert net_retry.retry_after_secs(_requests_error(429, {"Retry-After": raw})) == secs


def test_repeated_429s_exhaust_the_attempts_and_the_last_one_propagates(no_sleep):
    fetch, calls = _flaky(*[_requests_error(429, {"Retry-After": "10"})] * 3)

    with pytest.raises(requests.HTTPError):
        fetch()
    assert len(calls) == 3 and no_sleep == [10, 10]


def test_a_retry_after_on_any_other_4xx_is_ignored(no_sleep):
    fetch, calls = _flaky(_requests_error(403, {"Retry-After": "5"}))

    with pytest.raises(requests.HTTPError):
        fetch()
    assert len(calls) == 1


def test_the_retry_log_never_quotes_the_exception_text(capsys):
    fetch, _ = _flaky(urllib.error.URLError(TimeoutError("https://hc-ping.com/secret-uuid")))

    fetch()
    assert "secret-uuid" not in capsys.readouterr().err


# --- every fetch helper: explicit timeout, retried on a transient failure ------


class FakeResponse:
    def __init__(self, body: bytes):
        self.body = body
        self.headers = self

    def get_content_charset(self, default=None):
        return default

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FlakyTransport:
    """Fails once with `first`, then serves `body`; records the timeout of every call."""

    def __init__(self, body: bytes, first: BaseException):
        self.body, self.first, self.timeouts = body, first, []

    def __call__(self, req, timeout=None, **kwargs):
        self.timeouts.append(timeout if timeout is not None else kwargs.get("timeout"))
        if len(self.timeouts) == 1:
            raise self.first
        return FakeResponse(self.body)

    def open(self, req, timeout=None):  # an OpenerDirector
        return self(req, timeout)


class FlakyRequests(FlakyTransport):
    def __call__(self, url, params=None, timeout=None, headers=None):
        if len(self.timeouts) == 0:
            self.timeouts.append(timeout)
            raise self.first
        self.timeouts.append(timeout)
        response = requests.Response()
        response.status_code, response._content = 200, self.body
        return response


CONFIG = {"id": "src", "url": "https://example.test/meetings", "jurisdiction_id": "j", "institution_id": "i"}


def _adapter(cls, tmp_path):
    return cls(dict(CONFIG), tmp_path)


URLLIB_HELPERS = {
    "granicus.fetch_html": lambda tmp: granicus.fetch_html("https://example.test"),
    "civicplus._fetch_page": lambda tmp: _adapter(civicplus.CivicPlusAdapter, tmp)._fetch_page("https://example.test"),
    "civicplus._fetch_year": lambda tmp: _adapter(civicplus.CivicPlusAdapter, tmp)._fetch_year(
        "https://example.test/AgendaCenter", "1", 2026, None),
    "proudcity._fetch_page": lambda tmp: _adapter(proudcity.ProudCityAdapter, tmp)._fetch_page("https://example.test"),
    "drupal_ross._fetch_page": lambda tmp: _adapter(drupal_ross.DrupalRossAdapter, tmp)._fetch_page(
        "https://example.test"),
    "netfile._fetch_page": lambda tmp: _adapter(netfile.NetFileAdapter, tmp)._fetch_page("https://example.test"),
    "netfile._post_export": lambda tmp: _adapter(netfile.NetFileAdapter, tmp)._post_export(
        "https://example.test", {"a": "b"}),
    "ingest_form700._post_json": lambda tmp: ingest_form700._post_json("https://example.test", {"aid": "X"}),
}


@pytest.mark.parametrize("helper", sorted(URLLIB_HELPERS))
def test_each_urllib_fetch_helper_waits_a_bounded_time_and_retries_a_timeout(helper, monkeypatch, tmp_path):
    transport = FlakyTransport(b'{"ok": true}', urllib.error.URLError(TimeoutError("timed out")))
    monkeypatch.setattr(urllib.request, "urlopen", transport)
    monkeypatch.setattr(urllib.request, "build_opener", lambda *handlers: transport)

    out = URLLIB_HELPERS[helper](tmp_path)

    assert out in ('{"ok": true}', b'{"ok": true}', {"ok": True})
    assert len(transport.timeouts) == 2
    assert all(isinstance(t, (int, float)) and t > 0 for t in transport.timeouts)


def test_a_urllib_fetch_helper_never_retries_a_404(monkeypatch):
    transport = FlakyTransport(b"", _http_error(404))
    monkeypatch.setattr(urllib.request, "urlopen", transport)

    with pytest.raises(urllib.error.HTTPError):
        granicus.fetch_html("https://example.test")
    assert len(transport.timeouts) == 1


REQUESTS_HELPERS = {
    "ingest_socrata_permits.fetch_page": (ingest_socrata_permits, lambda: ingest_socrata_permits.fetch_page(0)),
    "ingest_courtlistener_cases.fetch_page": (ingest_courtlistener_cases,
                                              lambda: ingest_courtlistener_cases.fetch_page("q")),
}


@pytest.mark.parametrize("helper", sorted(REQUESTS_HELPERS))
def test_each_requests_fetch_helper_retries_the_read_timeout_that_cost_a_weekly_run(helper, monkeypatch):
    module, call = REQUESTS_HELPERS[helper]
    transport = FlakyRequests(json.dumps({"results": []}).encode(),
                              requests.ReadTimeout("Read timed out. (read timeout=30)"))
    monkeypatch.setattr(module.requests, "get", transport)

    assert call() == {"results": []}
    assert len(transport.timeouts) == 2 and all(t and t > 0 for t in transport.timeouts)


def test_a_requests_fetch_helper_never_retries_a_4xx(monkeypatch):
    calls = []

    def get(url, params=None, timeout=None, headers=None):
        calls.append(timeout)
        response = requests.Response()
        response.status_code, response._content, response.url = 404, b"{}", url
        return response
    monkeypatch.setattr(ingest_courtlistener_cases.requests, "get", get)

    with pytest.raises(requests.HTTPError):
        ingest_courtlistener_cases.fetch_page("q")
    assert len(calls) == 1


# --- a static guard: no network call without an explicit timeout ---------------


def _network_calls(tree: ast.AST):
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        receiver = node.func.value
        name = receiver.id if isinstance(receiver, ast.Name) else getattr(receiver, "attr", None)
        if node.func.attr == "urlopen" or (node.func.attr == "open" and name == "opener") or (
                name == "requests" and node.func.attr in {"get", "post", "put", "head", "request"}):
            yield node


@pytest.mark.parametrize("path", FETCHING_MODULES, ids=lambda p: p.name)
def test_every_network_call_in_the_weekly_sources_has_an_explicit_timeout(path):
    missing = [f"{path.name}:{call.lineno}" for call in _network_calls(ast.parse(path.read_text()))
               if not any(kw.arg == "timeout" for kw in call.keywords)]
    assert not missing, f"network calls with no timeout (they can hang a weekly run): {missing}"
