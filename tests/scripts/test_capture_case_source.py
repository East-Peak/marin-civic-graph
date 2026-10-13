"""Tests for scripts/capture_case_source.py (CF6 increment a).

Everything runs against fictional documents served by a local http.server on
127.0.0.1; the clock and sleep are injected so the 1-second throttle and the
Retry-After waits cost nothing. Each test builds only the routes it needs.
"""
from __future__ import annotations

import email.utils
import io
import json
import mimetypes
import sys
import threading
import warnings
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import capture_case_source as ccs  # noqa: E402
from capture_case_source import (  # noqa: E402
    AccessRefused,
    BudgetExhausted,
    SourceRestricted,
    capture,
    capture_zip_member,
)

START = 1_790_000_000.0  # 2026-09-21T... UTC, arbitrary fixed instant
HTML = b"<html><body><h1>Example Fund minutes</h1></body></html>"


class Clock:
    """Fake wall clock: sleeping advances it, nothing else does."""

    def __init__(self):
        self.t = START
        self.sleeps: list[float] = []

    def __call__(self):
        return self.t

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.t += seconds


class Stream:
    """A large reply written piece by piece so the test can see how much the client pulled."""

    def __init__(self, total, piece=b"x" * 65536):
        self.total, self.piece = total, piece


class Site:
    """Local server; routes map a request path to fn(handler) -> (status, headers, body)."""

    def __init__(self, clock):
        self.routes: dict = {}
        self.hits: list[tuple[str, str, float]] = []
        self.sent = 0
        site = self

        class Handler(BaseHTTPRequestHandler):
            def _serve(self):
                site.hits.append((self.command, self.path, clock.t))
                route = site.routes.get(self.path)
                status, headers, body = route(self) if route else (404, {}, b"nope")
                self.send_response(status)
                for key, value in headers.items():
                    self.send_header(key, value)
                if isinstance(body, Stream):
                    self.send_header("Content-Length", str(body.total))
                    self.end_headers()
                    try:
                        for _ in range(body.total // len(body.piece)):
                            self.wfile.write(body.piece)
                            site.sent += len(body.piece)
                    except OSError:
                        pass  # the client hung up, which is the point
                    return
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(body)

            do_GET = do_HEAD = _serve

            def log_message(self, *args):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.httpd.serve_forever, args=(0.02,), daemon=True).start()
        self.host = f"127.0.0.1:{self.httpd.server_address[1]}"

    def url(self, path):
        return f"http://{self.host}{path}"

    def paths(self):
        return [path for _, path, _ in self.hits]

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def page(body=HTML, ctype="text/html", **headers):
    return lambda req: (200, {"Content-Type": ctype, **headers}, body)


def status(code, **headers):
    return lambda req: (code, headers, b"")


def host_entry(**extra):
    return {
        "decision": "allowed",
        "basis": "Example Fund terms permit research use",
        "terms_url": "http://example.invalid/terms",
        "licence": "CC0",
        "attribution": "Example Fund",
        **extra,
    }


class Env:
    def __init__(self, tmp_path):
        self.clock = Clock()
        self.raw = tmp_path / "data" / "raw"
        self.state = tmp_path / "stage" / "state.json"
        self.basis = tmp_path / "stage" / "basis.json"
        self.sites: list[Site] = []
        self.basis.parent.mkdir(parents=True)

    def site(self, *, approved=True, **entry):
        site = Site(self.clock)
        self.sites.append(site)
        if approved:
            self.approve(site, **entry)
        return site

    def approve(self, site, **entry):
        hosts = json.loads(self.basis.read_text())["hosts"] if self.basis.exists() else {}
        hosts[site.host] = host_entry(**entry)
        self.basis.write_text(json.dumps({"hosts": hosts}))

    def kw(self, **over):
        return dict(
            source="example-fund",
            raw_root=self.raw,
            state_path=self.state,
            basis_path=self.basis,
            clock=self.clock,
            sleep=self.clock.sleep,
            **over,
        )

    def capture(self, url, **over):
        return capture(url, **self.kw(**over))

    def zip_member(self, url, member, **over):
        return capture_zip_member(url, member, **self.kw(**over))

    def written(self):
        return sorted(p for p in self.raw.rglob("*") if p.is_file() and p.name != "manifest.jsonl")

    def state_json(self):
        return json.loads(self.state.read_text())


@pytest.fixture
def env(tmp_path, monkeypatch):
    e = Env(tmp_path)
    monkeypatch.setattr(ccs, "RAW_ROOT", e.raw)
    monkeypatch.setattr(ccs, "STAGING_ROOT", e.state.parent)
    yield e
    for site in e.sites:
        site.stop()


# --- the happy path and manifest ------------------------------------------------


def test_capture_writes_document_and_manifest_row(env):
    site = env.site()
    site.routes["/reports/minutes.html"] = page(ETag='"v1"', **{"Last-Modified": "Mon, 01 Jun 2026 00:00:00 GMT"})
    row = env.capture(site.url("/reports/minutes.html"))

    assert row["url"] == site.url("/reports/minutes.html")
    assert row["final_url"] == row["url"]
    assert row["retrieved_at"].endswith("Z") and row["retrieved_at"].startswith("2026-")
    assert row["bytes"] == len(HTML) and row["status"] == 200
    assert row["content_type"] == "text/html"
    assert (row["etag"], row["last_modified"]) == ('"v1"', "Mon, 01 Jun 2026 00:00:00 GMT")
    day = row["retrieved_at"][:10]
    assert row["path"] == f"example-fund/{day}/minutes.html"
    assert (env.raw / row["path"]).read_bytes() == HTML
    import hashlib

    assert row["sha256"] == hashlib.sha256(HTML).hexdigest()

    access = row["access"]
    assert access["robots"] == "allowed" and access["robots_status"] == 404
    assert access["robots_url"] == site.url("/robots.txt") and access["robots_sha256"] is None
    assert access["decision"] == "allowed" and access["licence"] == "CC0"
    assert access["basis"] and access["terms_url"] and access["attribution"] == "Example Fund"
    assert "robots_unavailable_basis" not in access and access["user_agent"] == ccs.USER_AGENT

    lines = (env.raw / "example-fund" / day / "manifest.jsonl").read_text().splitlines()
    assert [json.loads(line) for line in lines] == [row]


def test_explicit_date_and_user_agent(env):
    site = env.site()
    site.routes["/a.html"] = page()
    row = env.capture(site.url("/a.html"), date="2026-03-04", user_agent="FictionalBot/9")
    assert row["path"] == "example-fund/2026-03-04/a.html"
    assert row["access"]["user_agent"] == "FictionalBot/9"


def test_filenames_are_sanitised_and_collision_safe(env):
    site = env.site()
    site.routes["/x/..%2f..%2fevil%20name.html?a=1"] = page(b"one")
    site.routes["/x/evil%20name.html"] = page(b"two")
    site.routes["/"] = page(b"root")
    rows = [
        env.capture(site.url("/x/..%2f..%2fevil%20name.html?a=1")),
        env.capture(site.url("/x/evil%20name.html".replace(" ", "%20"))),
        env.capture(site.url("/")),
    ]
    for row in rows:
        assert Path(row["path"]).parent == Path(rows[0]["path"]).parent
        assert (env.raw / row["path"]).resolve().is_relative_to(env.raw.resolve())
    assert len({r["path"] for r in rows}) == 3
    assert "/" not in Path(rows[0]["path"]).name and " " not in Path(rows[1]["path"]).name


# --- basis -----------------------------------------------------------------------


def test_host_without_basis_is_refused_before_any_request(env):
    site = env.site(approved=False)
    site.routes["/a.html"] = page()
    with pytest.raises(AccessRefused):
        env.capture(site.url("/a.html"))
    assert site.hits == [] and env.written() == []


def test_host_not_affirmatively_allowed_is_refused(env):
    site = env.site(decision="pending")
    with pytest.raises(AccessRefused):
        env.capture(site.url("/a.html"))
    assert site.hits == []


# --- robots ----------------------------------------------------------------------


def test_robots_disallow_refuses_and_writes_nothing(env):
    site = env.site()
    site.routes["/robots.txt"] = page(b"User-agent: *\nDisallow: /private\n", "text/plain")
    site.routes["/private/a.html"] = page()
    with pytest.raises(SourceRestricted):
        env.capture(site.url("/private/a.html"))
    assert site.paths() == ["/robots.txt"] and env.written() == []


def test_robots_allow_is_cached_with_sha_once_per_host(env):
    site = env.site()
    robots = b"User-agent: *\nDisallow: /private\n"
    site.routes["/robots.txt"] = page(robots, "text/plain")
    site.routes["/a.html"] = page(b"a")
    site.routes["/b.html"] = page(b"b")
    first = env.capture(site.url("/a.html"))
    second = env.capture(site.url("/b.html"))
    assert site.paths().count("/robots.txt") == 1
    import hashlib

    assert first["access"]["robots_sha256"] == hashlib.sha256(robots).hexdigest()
    assert second["access"]["robots_sha256"] == first["access"]["robots_sha256"]
    assert first["access"]["robots_status"] == 200


def test_robots_5xx_refuses_unless_host_has_unavailable_basis(env):
    site = env.site()
    site.routes["/robots.txt"] = status(500)
    site.routes["/a.html"] = page()
    with pytest.raises(AccessRefused):
        env.capture(site.url("/a.html"))
    assert "/a.html" not in site.paths()

    env.approve(site, robots_unavailable_basis="Operator confirmed robots outage is permanent")
    env.state.unlink()
    row = env.capture(site.url("/a.html"))
    assert row["access"]["robots_unavailable_basis"].startswith("Operator confirmed")
    assert row["access"]["robots_status"] == 500


def test_robots_unreachable_refuses(env):
    site = env.site()
    site.stop()  # nothing is listening any more
    with pytest.raises(AccessRefused):
        env.capture(site.url("/a.html"))
    assert env.written() == []


# --- redirects -------------------------------------------------------------------


def test_redirect_hops_are_followed_one_by_one_and_throttled(env):
    site = env.site()
    site.routes["/old"] = status(301, Location="/new")
    site.routes["/new"] = page(b"new")
    row = env.capture(site.url("/old"))
    assert row["url"] == site.url("/old") and row["final_url"] == site.url("/new")
    assert row["path"].endswith("/new")
    stamps = [t for _, _, t in site.hits]
    assert all(b - a >= 1.0 for a, b in zip(stamps, stamps[1:]))


def test_redirect_to_unapproved_host_is_never_contacted(env):
    site = env.site()
    other = env.site(approved=False)
    other.routes["/doc"] = page()
    site.routes["/go"] = status(302, Location=other.url("/doc"))
    with pytest.raises(AccessRefused):
        env.capture(site.url("/go"))
    assert other.hits == [] and env.written() == []


def test_redirect_to_approved_host_checks_that_hosts_robots(env):
    site = env.site()
    other = env.site()
    other.routes["/robots.txt"] = page(b"User-agent: *\nDisallow: /doc\n", "text/plain")
    other.routes["/doc"] = page()
    site.routes["/go"] = status(302, Location=other.url("/doc"))
    with pytest.raises(SourceRestricted):
        env.capture(site.url("/go"))
    assert other.paths() == ["/robots.txt"]


def test_redirect_to_login_path_is_restricted_and_stops_source(env):
    site = env.site()
    site.routes["/members"] = status(302, Location="/account/Sign-In?next=/members")
    site.routes["/account/Sign-In?next=/members"] = page(b"login")
    with pytest.raises(SourceRestricted):
        env.capture(site.url("/members"))
    assert "/account/Sign-In?next=/members" not in site.paths()
    assert "example-fund" in env.state_json()["stopped"]


def test_too_many_redirects_refused(env):
    site = env.site()
    for i in range(10):
        site.routes[f"/r{i}"] = status(302, Location=f"/r{i + 1}")
    with pytest.raises(AccessRefused):
        env.capture(site.url("/r0"))
    assert len([p for p in site.paths() if p.startswith("/r") and p != "/robots.txt"]) <= 6


# --- throttle --------------------------------------------------------------------


def test_requests_are_spaced_at_least_a_second_apart_including_robots(env):
    site = env.site()
    site.routes["/a.html"] = page(b"a")
    site.routes["/b.html"] = page(b"b")
    env.capture(site.url("/a.html"))
    env.capture(site.url("/b.html"))
    assert site.paths() == ["/robots.txt", "/a.html", "/b.html"]
    stamps = [t for _, _, t in site.hits]
    assert all(b - a >= 1.0 for a, b in zip(stamps, stamps[1:]))


def test_throttle_is_shared_across_hosts_and_invocations(env):
    one, two = env.site(), env.site()
    one.routes["/a.html"] = page(b"a")
    two.routes["/b.html"] = page(b"b")
    env.capture(one.url("/a.html"))
    env.capture(two.url("/b.html"))  # a different host, still 1 s after the last request anywhere
    stamps = sorted(t for s in (one, two) for _, _, t in s.hits)
    assert all(b - a >= 1.0 for a, b in zip(stamps, stamps[1:]))
    last = env.state_json()["last_request"]
    assert last["*"] == max(stamps) and last[two.host] == max(stamps) and one.host in last


# --- Retry-After -----------------------------------------------------------------


def flaky(first, then):
    calls = {"n": 0}

    def route(req):
        calls["n"] += 1
        return first(req) if calls["n"] == 1 else then(req)

    return route


def test_429_retry_after_seconds_waits_fully_then_retries_once(env):
    site = env.site()
    site.routes["/a.html"] = flaky(status(429, **{"Retry-After": "30"}), page())
    row = env.capture(site.url("/a.html"))
    assert row["status"] == 200 and any(abs(s - 30) < 1e-6 for s in env.clock.sleeps)
    stamps = [t for _, p, t in site.hits if p == "/a.html"]
    assert stamps[1] - stamps[0] >= 30


def test_503_retry_after_http_date(env):
    site = env.site()
    date = email.utils.formatdate(START + 61, usegmt=True)
    site.routes["/a.html"] = flaky(status(503, **{"Retry-After": date}), page())
    env.capture(site.url("/a.html"))
    stamps = [t for _, p, t in site.hits if p == "/a.html"]
    assert stamps[1] >= START + 61  # the full HTTP-date deadline, never earlier


def test_retry_after_over_cap_stops_source_without_waiting(env):
    site = env.site()
    site.routes["/a.html"] = status(429, **{"Retry-After": "121"})
    with pytest.raises(SourceRestricted):
        env.capture(site.url("/a.html"))
    assert max(env.clock.sleeps, default=0) < 121
    assert "example-fund" in env.state_json()["stopped"]


def test_second_refusal_stops_source_and_later_captures_make_no_requests(env):
    site = env.site()
    site.routes["/a.html"] = status(429, **{"Retry-After": "5"})
    site.routes["/b.html"] = page()
    with pytest.raises(SourceRestricted):
        env.capture(site.url("/a.html"))
    assert site.paths().count("/a.html") == 2
    seen = len(site.hits)
    with pytest.raises(SourceRestricted):
        env.capture(site.url("/b.html"))
    assert len(site.hits) == seen


def test_503_without_retry_after_stops_source(env):
    site = env.site()
    site.routes["/a.html"] = status(503)
    with pytest.raises(SourceRestricted):
        env.capture(site.url("/a.html"))
    assert site.paths().count("/a.html") == 1


# --- restricted content ----------------------------------------------------------


@pytest.mark.parametrize("code", [401, 403])
def test_401_403_restricted_nothing_written(env, code):
    site = env.site()
    site.routes["/a.html"] = status(code)
    with pytest.raises(SourceRestricted):
        env.capture(site.url("/a.html"))
    assert env.written() == [] and "example-fund" in env.state_json()["stopped"]


@pytest.mark.parametrize(
    "body",
    [
        b'<form><input type="password" name="p"></form>',
        b"<input TYPE=password>",
        b'<div class="g-recaptcha"></div>',
        b"<script src='hcaptcha.com/1/api.js'></script>",
        b"<title>cf-challenge</title>",
        b"<div id=cf-turnstile></div>",
        b"<p>Please Subscribe to continue reading</p>",
        b"<div class='paywall'>x</div>",
        b"<p>complete the CAPTCHA</p>",
    ],
)
def test_login_captcha_paywall_markers_restricted(env, body):
    site = env.site()
    site.routes["/a.html"] = page(body)
    with pytest.raises(SourceRestricted):
        env.capture(site.url("/a.html"))
    assert env.written() == [] and "example-fund" in env.state_json()["stopped"]


def test_markers_in_binary_documents_are_not_sniffed(env):
    site = env.site()
    site.routes["/a.pdf"] = page(b"%PDF captcha paywall", "application/pdf")
    assert env.capture(site.url("/a.pdf"))["bytes"] == 20


def test_other_error_statuses_refuse_without_stopping(env):
    site = env.site()
    site.routes["/gone"] = status(410)
    with pytest.raises(AccessRefused):
        env.capture(site.url("/gone"))
    assert "stopped" not in env.state_json() or not env.state_json()["stopped"]


# --- captured once ---------------------------------------------------------------


def test_second_capture_of_same_url_returns_existing_row_without_request(env):
    site = env.site()
    site.routes["/a.html"] = page()
    first = env.capture(site.url("/a.html"), date="2026-03-04")
    seen = len(site.hits)
    again = env.capture(site.url("/a.html"), date="2026-05-06")
    assert again == first and len(site.hits) == seen
    assert len(env.written()) == 1


# --- budget ----------------------------------------------------------------------


def test_budget_cap_refuses_before_any_request(env):
    site = env.site()
    for name in "abc":
        site.routes[f"/{name}.html"] = page(name.encode())
    env.capture(site.url("/a.html"), cap=2)
    env.capture(site.url("/b.html"), cap=2)
    seen = len(site.hits)
    with pytest.raises(BudgetExhausted):
        env.capture(site.url("/c.html"), cap=2)
    assert len(site.hits) == seen
    assert env.state_json()["documents"] == 2


def test_robots_and_refused_captures_do_not_count_as_documents(env):
    site = env.site()
    site.routes["/robots.txt"] = page(b"User-agent: *\nDisallow: /no\n", "text/plain")
    with pytest.raises(SourceRestricted):
        env.capture(site.url("/no/a.html"))
    assert env.state_json().get("documents", 0) == 0


def test_default_cap_is_sixty():
    assert ccs.DEFAULT_CAP == 60


# --- zip members -----------------------------------------------------------------

MEMBER_XML = b"<Return>" + b"Example Fund grant ledger. " * 200 + b"</Return>"


def make_zip(member="Folder/202601234567_public.xml", payload=MEMBER_XML):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
        zf.writestr("other.xml", b"<Other/>" * 300)
        zf.writestr(member, payload)
    return buf.getvalue()


def ranged(blob, *, etag='"z1"', honour=True, etag_after=None):
    state = {"n": 0}

    def route(req):
        state["n"] += 1
        tag = etag_after if etag_after and state["n"] > 2 else etag
        header = req.headers.get("Range")
        if not honour or not header:
            return 200, {"ETag": tag}, blob
        first, _, last = header.removeprefix("bytes=").partition("-")
        start = int(first)
        stop = min(int(last), len(blob) - 1) if last else len(blob) - 1
        body = blob[start : stop + 1]
        return 206, {"ETag": tag, "Content-Range": f"bytes {start}-{stop}/{len(blob)}", "Last-Modified": "Mon, 01 Jun 2026 00:00:00 GMT"}, body

    return route


def test_zip_member_extracted_via_range_reads(env):
    import hashlib
    import zlib

    site = env.site()
    blob = make_zip()
    site.routes["/dist/2026_batch.zip"] = ranged(blob)
    row = env.zip_member(site.url("/dist/2026_batch.zip"), "folder/202601234567_PUBLIC.xml", range_chunk=512)

    assert row["member"] == "Folder/202601234567_public.xml"  # exact name reported
    assert row["zip_url"] == site.url("/dist/2026_batch.zip")
    assert row["zip_bytes"] == len(blob) and row["zip_etag"] == '"z1"'
    assert row["zip_last_modified"] == "Mon, 01 Jun 2026 00:00:00 GMT"
    assert row["member_crc32"] == f"{zlib.crc32(MEMBER_XML):08x}"
    assert row["sha256"] == hashlib.sha256(MEMBER_XML).hexdigest() and row["bytes"] == len(MEMBER_XML)
    assert row["range_requests"] == len([h for h in site.hits if h[1].endswith(".zip")]) >= 3
    assert row["path"].endswith("/202601234567_public.xml")
    assert (env.raw / row["path"]).read_bytes() == MEMBER_XML
    assert row["access"]["robots"] == "allowed"
    # only part of the archive was transferred, never a plain full GET
    assert all(h[0] == "GET" for h in site.hits)
    assert env.state_json()["documents"] == 1
    stamps = [t for _, _, t in site.hits]
    assert all(b - a >= 1.0 for a, b in zip(stamps, stamps[1:]))


def test_zip_member_captured_once(env):
    site = env.site()
    site.routes["/z.zip"] = ranged(make_zip())
    first = env.zip_member(site.url("/z.zip"), "Folder/202601234567_public.xml", range_chunk=512)
    seen = len(site.hits)
    assert env.zip_member(site.url("/z.zip"), "Folder/202601234567_public.xml") == first
    assert len(site.hits) == seen  # exact repeat: no request at all
    again = env.zip_member(site.url("/z.zip"), "folder/202601234567_PUBLIC.xml", range_chunk=512)
    assert again == first and len(env.written()) == 1  # resolved to the same exact member


def test_zip_refused_when_server_ignores_range(env):
    site = env.site()
    site.routes["/z.zip"] = ranged(make_zip(), honour=False)
    with pytest.raises(AccessRefused):
        env.zip_member(site.url("/z.zip"), "other.xml")
    assert env.written() == []


def test_zip_refused_when_etag_changes_mid_read(env):
    site = env.site()
    site.routes["/z.zip"] = ranged(make_zip(), etag_after='"z2"')
    with pytest.raises(AccessRefused):
        env.zip_member(site.url("/z.zip"), "Folder/202601234567_public.xml", range_chunk=256)
    assert env.written() == []


def test_zip_crc_failure_raises_and_writes_nothing(env):
    site = env.site()
    blob = bytearray(make_zip())
    at = blob.find(MEMBER_XML)
    blob[at + 10] ^= 0xFF
    site.routes["/z.zip"] = ranged(bytes(blob))
    with pytest.raises(zipfile.BadZipFile):
        env.zip_member(site.url("/z.zip"), "Folder/202601234567_public.xml", range_chunk=512)
    assert env.written() == [] and env.state_json().get("documents", 0) == 0


def test_zip_missing_member_refused(env):
    site = env.site()
    site.routes["/z.zip"] = ranged(make_zip())
    with pytest.raises(AccessRefused):
        env.zip_member(site.url("/z.zip"), "nope.xml")


def test_zip_host_without_basis_refused(env):
    site = env.site(approved=False)
    with pytest.raises(AccessRefused):
        env.zip_member(site.url("/z.zip"), "a.xml")
    assert site.hits == []


# --- CLI and path rules ----------------------------------------------------------


@pytest.fixture
def cli(env, tmp_path, monkeypatch):
    staging = tmp_path / "stage"
    monkeypatch.setattr(ccs, "STAGING_ROOT", staging)
    return env


def run_cli(env, *extra, raw=None, state=None, basis=None):
    return ccs.main(
        ["--source", "example-fund", "--raw-root", str(raw or env.raw), "--state", str(state or env.state),
         "--basis", str(basis or env.basis), *extra],
        clock=env.clock, sleep=env.clock.sleep,
    )


def test_cli_prints_manifest_row(cli, capsys):
    site = cli.site()
    site.routes["/a.html"] = page()
    assert run_cli(cli, "--url", site.url("/a.html")) == 0
    row = json.loads(capsys.readouterr().out)
    assert row["url"] == site.url("/a.html") and row["path"].startswith("example-fund/")


def test_cli_cap_option(cli, capsys):
    site = cli.site()
    site.routes["/a.html"] = page()
    site.routes["/b.html"] = page(b"b")
    assert run_cli(cli, "--url", site.url("/a.html"), "--cap", "1") == 0
    assert run_cli(cli, "--url", site.url("/b.html"), "--cap", "1") != 0
    assert "budget" in capsys.readouterr().err.lower()


def test_cli_zip_member(cli, capsys):
    site = cli.site()
    site.routes["/z.zip"] = ranged(make_zip())
    assert run_cli(cli, "--zip-url", site.url("/z.zip"), "--member", "other.xml") == 0
    assert json.loads(capsys.readouterr().out)["member"] == "other.xml"


def test_cli_requires_url_or_zip(cli):
    with pytest.raises(SystemExit):
        run_cli(cli)


def test_cli_raw_root_must_be_data_raw(cli, tmp_path, capsys):
    site = cli.site()
    for bad in (tmp_path / "raw", tmp_path / "data" / "extracted", tmp_path / "data" / "raw" / "sub",
                tmp_path / "other" / "data" / "raw"):
        assert run_cli(cli, "--url", site.url("/a.html"), raw=bad) != 0
    assert site.hits == []
    assert "raw" in capsys.readouterr().err.lower()


def test_cli_state_and_basis_must_be_under_staging(cli, tmp_path):
    site = cli.site()
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    assert run_cli(cli, "--url", site.url("/a.html"), state=outside / "s.json") != 0
    assert run_cli(cli, "--url", site.url("/a.html"), basis=outside / "b.json") != 0
    assert site.hits == []


def test_cli_symlink_escapes_refused(cli, tmp_path):
    site = cli.site()
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (cli.state.parent / "link").symlink_to(outside)
    assert run_cli(cli, "--url", site.url("/a.html"), state=cli.state.parent / "link" / "s.json") != 0
    elsewhere_raw = outside / "data" / "raw"
    elsewhere_raw.mkdir(parents=True)
    (tmp_path / "lnk").symlink_to(outside)
    # a symlink named like data/raw but pointing elsewhere still resolves to a non-data/raw path
    (tmp_path / "data2").mkdir()
    (tmp_path / "data2" / "raw").symlink_to(outside)
    assert run_cli(cli, "--url", site.url("/a.html"), raw=tmp_path / "data2" / "raw") != 0
    assert site.hits == []


def test_cli_refusal_exit_code_and_message(cli, capsys):
    site = cli.site(approved=False)
    assert run_cli(cli, "--url", site.url("/a.html")) != 0
    assert "refused" in capsys.readouterr().err.lower()


# --- review fixes (Codex) --------------------------------------------------------


@pytest.mark.parametrize("code", [401, 403])
def test_robots_401_403_stops_source_and_blocks_the_document(env, code):
    site = env.site()
    site.routes["/robots.txt"] = status(code)
    site.routes["/a.html"] = page()
    with pytest.raises(SourceRestricted):
        env.capture(site.url("/a.html"))
    assert site.paths() == ["/robots.txt"] and "example-fund" in env.state_json()["stopped"]


def test_robots_429_waits_retry_after_then_proceeds(env):
    site = env.site()
    site.routes["/robots.txt"] = flaky(status(429, **{"Retry-After": "40"}), status(404))
    site.routes["/a.html"] = page()
    env.capture(site.url("/a.html"))
    stamps = [t for _, p, t in site.hits if p == "/robots.txt"]
    assert stamps[1] - stamps[0] >= 40


def test_robots_429_over_cap_stops_source(env):
    site = env.site()
    site.routes["/robots.txt"] = status(429, **{"Retry-After": "900"})
    with pytest.raises(SourceRestricted):
        env.capture(site.url("/a.html"))
    assert "/a.html" not in site.paths() and "example-fund" in env.state_json()["stopped"]


def test_robots_html_challenge_stops_source(env):
    site = env.site()
    site.routes["/robots.txt"] = page(b"<html><div class='g-recaptcha'></div></html>", "text/plain")
    with pytest.raises(SourceRestricted):
        env.capture(site.url("/a.html"))
    assert "/a.html" not in site.paths() and "example-fund" in env.state_json()["stopped"]


def test_robots_disallow_persists_the_stop(env):
    site = env.site()
    site.routes["/robots.txt"] = page(b"User-agent: *\nDisallow: /\n", "text/plain")
    with pytest.raises(SourceRestricted):
        env.capture(site.url("/a.html"))
    assert "example-fund" in env.state_json()["stopped"]


@pytest.mark.parametrize("code", [404, 410])
def test_robots_absent_means_allowed(env, code):
    site = env.site()
    site.routes["/robots.txt"] = status(code)
    site.routes["/a.html"] = page()
    assert env.capture(site.url("/a.html"))["access"]["robots_status"] == code


def test_robots_other_4xx_is_unavailable_and_refuses(env):
    site = env.site()
    site.routes["/robots.txt"] = status(400)
    with pytest.raises(AccessRefused):
        env.capture(site.url("/a.html"))
    assert "/a.html" not in site.paths()


def test_concurrent_invocations_are_fully_serialised(env):
    site = env.site()
    for name in "ab":
        site.routes[f"/{name}.html"] = page(name.encode())
    site.routes["/same.html"] = page(b"same")
    errors = []

    def run(url):
        try:
            env.capture(url)
        except Exception as err:  # pragma: no cover - reported below
            errors.append(err)

    urls = [site.url(p) for p in ("/a.html", "/b.html", "/same.html", "/same.html")]
    threads = [threading.Thread(target=run, args=(u,)) for u in urls]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    stamps = sorted(t for _, _, t in site.hits)
    assert all(b - a >= 1.0 for a, b in zip(stamps, stamps[1:]))
    assert site.paths().count("/same.html") == 1
    assert env.state_json()["documents"] == 3


def test_cooldown_deadline_persists_across_invocations(env):
    site = env.site()
    site.routes["/a.html"] = page()
    env.state.write_text(json.dumps({"cooldown": {site.host: START + 50}}))
    env.capture(site.url("/a.html"))
    assert all(t >= START + 50 for _, _, t in site.hits)


def test_raw_root_must_be_the_pinned_main_checkout_root(env, tmp_path):
    site = env.site()
    for bad in (tmp_path / "data" / "raw" / "sub", tmp_path / "other" / "data" / "raw"):
        with pytest.raises(AccessRefused):
            capture(site.url("/a.html"), **{**env.kw(), "raw_root": bad})
    assert site.hits == []


def test_symlinked_source_or_date_dir_is_refused(env, tmp_path):
    site = env.site()
    site.routes["/a.html"] = page()
    outside = tmp_path / "outside"
    outside.mkdir()
    env.raw.mkdir(parents=True)
    (env.raw / "example-fund").symlink_to(outside)
    with pytest.raises(AccessRefused):
        env.capture(site.url("/a.html"))
    (env.raw / "example-fund").unlink()
    (env.raw / "example-fund").mkdir()
    (env.raw / "example-fund" / "2026-03-04").symlink_to(outside)
    with pytest.raises(AccessRefused):
        env.capture(site.url("/a.html"), date="2026-03-04")
    assert list(outside.iterdir()) == []


def test_symlinked_manifest_and_state_files_are_refused(env, tmp_path):
    site = env.site()
    site.routes["/a.html"] = page()
    outside = tmp_path / "outside.jsonl"
    outside.write_text("")
    folder = env.raw / "example-fund" / "2026-03-04"
    folder.mkdir(parents=True)
    (folder / "manifest.jsonl").symlink_to(outside)
    with pytest.raises(AccessRefused):
        env.capture(site.url("/a.html"), date="2026-03-04")
    assert outside.read_text() == ""
    (folder / "manifest.jsonl").unlink()
    real = tmp_path / "real-state.json"
    real.write_text("{}")
    env.state.unlink()
    env.state.symlink_to(real)
    with pytest.raises(AccessRefused):
        env.capture(site.url("/a.html"), date="2026-03-04")


@pytest.mark.parametrize("cap", [0, -1, 61])
def test_cap_must_be_between_1_and_60(env, cap):
    site = env.site()
    with pytest.raises(AccessRefused):
        env.capture(site.url("/a.html"), cap=cap)
    assert site.hits == []


def test_cli_rejects_cap_above_hard_ceiling(cli, capsys):
    site = cli.site()
    assert run_cli(cli, "--url", site.url("/a.html"), "--cap", "61") == 2
    assert site.hits == []


@pytest.mark.parametrize("missing", ["decision", "basis", "licence", "attribution", "terms_url"])
def test_incomplete_basis_entry_is_refused_before_any_request(env, missing):
    site = env.site(approved=False)
    entry = host_entry()
    del entry[missing]
    env.basis.write_text(json.dumps({"hosts": {site.host: entry}}))
    with pytest.raises(AccessRefused):
        env.capture(site.url("/a.html"))
    assert site.hits == []


def test_blank_basis_text_is_refused_but_null_terms_url_is_fine(env):
    site = env.site(basis="  ")
    with pytest.raises(AccessRefused):
        env.capture(site.url("/a.html"))
    env.approve(site, terms_url=None)
    site.routes["/a.html"] = page()
    assert env.capture(site.url("/a.html"))["access"]["terms_url"] is None


def test_every_hop_records_its_access_evidence(env):
    site = env.site()
    other = env.site(licence="ODbL")
    site.routes["/old"] = status(301, Location=other.url("/new"))
    other.routes["/new"] = page(b"new")
    row = env.capture(site.url("/old"))
    assert [h["url"] for h in row["hops"]] == [site.url("/old"), other.url("/new")]
    assert [h["status"] for h in row["hops"]] == [301, 200]
    assert row["hops"][0]["access"]["licence"] == "CC0" and row["hops"][1]["access"]["licence"] == "ODbL"
    assert row["access"] == row["hops"][-1]["access"]


def test_html_labelled_as_text_plain_is_still_sniffed(env):
    site = env.site()
    site.routes["/a.txt"] = page(b"<!DOCTYPE html><html><div class='h-captcha'>hcaptcha</div></html>", "text/plain")
    with pytest.raises(SourceRestricted):
        env.capture(site.url("/a.txt"))
    assert env.written() == []


def test_initial_login_path_is_refused_before_dispatch(env):
    site = env.site()
    site.routes["/login/data.html"] = page()
    with pytest.raises(SourceRestricted):
        env.capture(site.url("/login/data.html"))
    assert site.hits == [] and "example-fund" in env.state_json()["stopped"]


def test_challenge_page_on_a_range_request_stops_the_source(env):
    site = env.site()
    site.routes["/z.zip"] = page(b"<html><div class='g-recaptcha'></div></html>")
    with pytest.raises(SourceRestricted):
        env.zip_member(site.url("/z.zip"), "a.xml")
    assert "example-fund" in env.state_json()["stopped"]


def test_range_reply_longer_than_requested_or_misaligned_is_refused(env):
    site = env.site()
    blob = make_zip()
    good = ranged(blob)

    def too_long(req):
        status_code, headers, body = good(req)
        return status_code, headers, body + b"EXTRA" * 100

    site.routes["/long.zip"] = too_long
    site.routes["/skew.zip"] = lambda req: (206, {"Content-Range": f"bytes 5-5/{len(blob)}", "ETag": '"z1"'}, b"x")
    for path in ("/long.zip", "/skew.zip"):
        with pytest.raises(AccessRefused):
            env.zip_member(site.url(path), "other.xml")
    assert env.written() == []


def test_zip_duplicate_exact_member_names_are_refused(env):
    buf = io.BytesIO()
    with warnings.catch_warnings(), zipfile.ZipFile(buf, "w") as zf:
        warnings.simplefilter("ignore")
        zf.writestr("a.xml", b"<one/>")
        zf.writestr("a.xml", b"<two/>")
    site = env.site()
    site.routes["/z.zip"] = ranged(buf.getvalue())
    with pytest.raises(AccessRefused):
        env.zip_member(site.url("/z.zip"), "a.xml")
    assert env.written() == []


def test_zip_case_variants_are_distinct_members(env):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("A.xml", b"<upper/>")
        zf.writestr("a.xml", b"<lower/>")
    site = env.site()
    site.routes["/z.zip"] = ranged(buf.getvalue())
    with pytest.raises(AccessRefused):  # ambiguous fallback
        env.zip_member(site.url("/z.zip"), "A.XML")
    upper = env.zip_member(site.url("/z.zip"), "A.xml")
    lower = env.zip_member(site.url("/z.zip"), "a.xml")
    assert (upper["member"], lower["member"]) == ("A.xml", "a.xml") and upper["sha256"] != lower["sha256"]


def test_zip_member_in_a_folder_is_found_by_its_unique_file_name(env):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("batch-01/0001_public.xml", b"<one/>")
        zf.writestr("batch-01/0002_public.xml", b"<two/>")
    site = env.site()
    site.routes["/z.zip"] = ranged(buf.getvalue())
    row = env.zip_member(site.url("/z.zip"), "0002_public.xml")
    assert row["member"] == "batch-01/0002_public.xml"


def test_zip_file_name_in_two_folders_is_ambiguous(env):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("a/0001_public.xml", b"<one/>")
        zf.writestr("b/0001_public.xml", b"<two/>")
    site = env.site()
    site.routes["/z.zip"] = ranged(buf.getvalue())
    with pytest.raises(AccessRefused):
        env.zip_member(site.url("/z.zip"), "0001_public.xml")
    assert env.written() == []


def test_zip_row_records_member_and_archive_content_types(env):
    site = env.site()
    site.routes["/z.zip"] = lambda req: (lambda r: (r[0], {**r[1], "Content-Type": "application/zip"}, r[2]))(
        ranged(make_zip())(req)
    )
    row = env.zip_member(site.url("/z.zip"), "other.xml")
    assert row["content_type"] == mimetypes.guess_type("other.xml")[0] == "application/xml"
    assert row["zip_content_type"] == "application/zip"
    assert row["hops"] and row["hops"][0]["url"] == site.url("/z.zip")


def test_document_named_manifest_does_not_clobber_the_manifest(env):
    site = env.site()
    site.routes["/manifest.jsonl"] = page(b"not a manifest", "text/plain")
    site.routes["/b.html"] = page(b"b")
    row = env.capture(site.url("/manifest.jsonl"), date="2026-03-04")
    env.capture(site.url("/b.html"), date="2026-03-04")
    assert Path(row["path"]).name != "manifest.jsonl"
    assert (env.raw / row["path"]).read_bytes() == b"not a manifest"
    rows = (env.raw / "example-fund" / "2026-03-04" / "manifest.jsonl").read_text().splitlines()
    assert len(rows) == 2 and json.loads(rows[0])["sha256"] == row["sha256"]


# --- review round 2 --------------------------------------------------------------


def test_empty_206_is_refused_after_exactly_one_request_and_stops_source(env):
    site = env.site()
    blob = make_zip()
    site.routes["/z.zip"] = lambda req: (206, {"Content-Range": f"bytes 0-0/{len(blob)}", "ETag": '"z1"'}, b"")
    with pytest.raises(AccessRefused):
        env.zip_member(site.url("/z.zip"), "other.xml")
    assert site.paths().count("/z.zip") == 1
    assert "example-fund" in env.state_json()["stopped"]


def test_short_206_body_is_refused(env):
    site = env.site()
    blob = make_zip()
    good = ranged(blob)

    def short(req):
        code, headers, body = good(req)
        return code, headers, body[:-1] if len(body) > 1 else body

    site.routes["/z.zip"] = short
    with pytest.raises(AccessRefused):
        env.zip_member(site.url("/z.zip"), "other.xml", range_chunk=256)
    assert "example-fund" in env.state_json()["stopped"]


@pytest.mark.parametrize("path", ["/long.zip", "/skew.zip"])
def test_range_violations_latch_the_source_stopped(env, path):
    site = env.site()
    blob = make_zip()
    good = ranged(blob)
    site.routes["/long.zip"] = lambda req: (lambda r: (r[0], r[1], r[2] + b"EXTRA" * 50))(good(req))
    site.routes["/skew.zip"] = lambda req: (206, {"Content-Range": f"bytes 5-5/{len(blob)}", "ETag": '"z1"'}, b"x")
    with pytest.raises(AccessRefused):
        env.zip_member(site.url(path), "other.xml")
    assert "example-fund" in env.state_json()["stopped"]


def test_server_ignoring_range_cannot_make_us_download_the_archive(env):
    site = env.site()
    site.routes["/z.zip"] = lambda req: (200, {}, Stream(64 * 1024 * 1024))
    with pytest.raises(AccessRefused):
        env.zip_member(site.url("/z.zip"), "other.xml")
    assert site.sent < 8 * 1024 * 1024


def test_state_tmp_symlink_is_not_followed(env, tmp_path):
    site = env.site()
    site.routes["/a.html"] = page()
    victim = tmp_path / "victim.txt"
    victim.write_text("keep")
    (env.state.parent / "state.json.tmp").symlink_to(victim)
    env.capture(site.url("/a.html"))
    assert victim.read_text() == "keep" and json.loads(env.state.read_text())["documents"] == 1


def test_symlinked_lock_file_is_refused(env, tmp_path):
    site = env.site()
    (env.state.parent / "state.json.lock").symlink_to(tmp_path / "somewhere")
    with pytest.raises(AccessRefused):
        env.capture(site.url("/a.html"))
    assert site.hits == []


def test_library_state_and_basis_must_live_under_staging(env, tmp_path):
    site = env.site()
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    with pytest.raises(AccessRefused):
        capture(site.url("/a.html"), **{**env.kw(), "state_path": outside / "s.json"})
    with pytest.raises(AccessRefused):
        capture(site.url("/a.html"), **{**env.kw(), "basis_path": outside / "b.json"})
    assert site.hits == [] and list(outside.iterdir()) == []


def test_lost_state_after_a_crash_is_reconciled_from_the_manifests(env):
    site = env.site()
    for name in "abc":
        site.routes[f"/{name}.html"] = page(name.encode())
    env.capture(site.url("/a.html"), cap=1)
    # simulate dying after the manifest append but before the state save
    state = env.state_json()
    state["documents"] = 0
    env.state.write_text(json.dumps(state))
    seen = len(site.hits)
    with pytest.raises(BudgetExhausted):
        env.capture(site.url("/b.html"), cap=1)
    assert len(site.hits) == seen and env.state_json()["documents"] == 1


def test_other_tools_manifest_rows_do_not_count_against_the_budget(env):
    site = env.site()
    site.routes["/a.html"] = page()
    legacy = env.raw / "other-source" / "2026-01-01"
    legacy.mkdir(parents=True)
    (legacy / "manifest.jsonl").write_text(json.dumps({"url": "http://example.invalid/x"}) + "\n")
    env.capture(site.url("/a.html"), cap=1)


def test_deflated_member_is_extracted(env):
    payload = b"<Return>" + b"compressible grant ledger " * 400 + b"</Return>"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("pad.xml", b"<p/>" * 500)
        zf.writestr("data/return.xml", payload)
    assert len(buf.getvalue()) < len(payload)
    site = env.site()
    site.routes["/z.zip"] = ranged(buf.getvalue())
    row = env.zip_member(site.url("/z.zip"), "data/return.xml", range_chunk=256)
    assert (env.raw / row["path"]).read_bytes() == payload


def test_data_descriptor_member_is_extracted(env):
    class Sink(io.RawIOBase):  # not seekable, so zipfile must write a data descriptor
        def __init__(self):
            self.data = bytearray()

        def writable(self):
            return True

        def write(self, chunk):
            self.data += chunk
            return len(chunk)

    payload = b"<Return>descriptor member</Return>" * 50
    sink = Sink()
    with zipfile.ZipFile(sink, "w", zipfile.ZIP_DEFLATED) as zf:
        with zf.open("streamed.xml", "w") as member:
            member.write(payload)
    assert zipfile.ZipFile(io.BytesIO(bytes(sink.data))).infolist()[0].flag_bits & 0x08
    site = env.site()
    site.routes["/z.zip"] = ranged(bytes(sink.data))
    row = env.zip_member(site.url("/z.zip"), "streamed.xml", range_chunk=256)
    assert (env.raw / row["path"]).read_bytes() == payload


# --- external decompressor (Deflate64 and friends) ---------------------------------

needs_unzip = pytest.mark.skipif(not Path(ccs.UNZIP).exists(), reason="/usr/bin/unzip is absent")


def deflated_zip(payload):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("pad.xml", b"<p/>" * 500)
        zf.writestr("data/return.xml", payload)
    return buf.getvalue()


def test_zipfile_is_the_default_decompressor(env):
    site = env.site()
    site.routes["/z.zip"] = ranged(make_zip())
    row = env.zip_member(site.url("/z.zip"), "other.xml")
    assert row["decompressor"] == "zipfile" and row["member_compress_type"] == zipfile.ZIP_STORED


def test_deflate64_is_routed_to_the_external_path():
    assert 9 in ccs.EXTERNAL_METHODS


@needs_unzip
@pytest.mark.parametrize("kind", ["stored", "deflated"])
def test_external_path_yields_identical_bytes(env, monkeypatch, kind):
    monkeypatch.setattr(ccs, "EXTERNAL_METHODS", {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED})
    payload = b"<Return>" + b"external grant ledger " * 300 + b"</Return>"
    blob, name = (make_zip("data/return.xml", payload), "data/return.xml") if kind == "stored" \
        else (deflated_zip(payload), "data/return.xml")
    site = env.site()
    site.routes["/z.zip"] = ranged(blob)
    row = env.zip_member(site.url("/z.zip"), name, range_chunk=256)
    assert (env.raw / row["path"]).read_bytes() == payload == zipfile.ZipFile(io.BytesIO(blob)).read(name)
    assert row["decompressor"] == "unzip"
    assert row["member_compress_type"] == (zipfile.ZIP_STORED if kind == "stored" else zipfile.ZIP_DEFLATED)
    assert row["member_crc32"] and row["bytes"] == len(payload)


@needs_unzip
def test_external_path_crc_mismatch_raises_and_writes_nothing(env, monkeypatch):
    import tempfile

    monkeypatch.setattr(ccs, "EXTERNAL_METHODS", {zipfile.ZIP_STORED})
    made = []
    real = tempfile.mkdtemp
    monkeypatch.setattr(ccs.tempfile, "mkdtemp", lambda *a, **k: made.append(real(*a, **k)) or made[-1])
    blob = bytearray(make_zip())
    blob[blob.find(MEMBER_XML) + 10] ^= 0xFF
    site = env.site()
    site.routes["/z.zip"] = ranged(bytes(blob))
    with pytest.raises(zipfile.BadZipFile):
        env.zip_member(site.url("/z.zip"), "Folder/202601234567_public.xml", range_chunk=512)
    assert env.written() == [] and env.state_json().get("documents", 0) == 0
    assert made and not any(Path(d).exists() for d in made)


@needs_unzip
def test_external_path_removes_its_temp_dir_on_success(env, monkeypatch):
    import tempfile

    monkeypatch.setattr(ccs, "EXTERNAL_METHODS", {zipfile.ZIP_STORED})
    made = []
    real = tempfile.mkdtemp
    monkeypatch.setattr(ccs.tempfile, "mkdtemp", lambda *a, **k: made.append(real(*a, **k)) or made[-1])
    site = env.site()
    site.routes["/z.zip"] = ranged(make_zip())
    env.zip_member(site.url("/z.zip"), "other.xml")
    assert len(made) == 1 and not Path(made[0]).exists()


# --- challenge detection ignores inline code; audited clearance --------------------


def test_marker_only_inside_inline_script_or_style_or_comment_is_not_a_challenge(env):
    site = env.site()
    body = (b"<html><head><title>Minutes</title><script>var cfg={captcha:'public-key'};</script>"
            b"<style>.captcha{color:red}</style><!-- paywall hcaptcha --></head><body><p>Minutes</p></body></html>")
    site.routes["/a.html"] = page(body)
    assert env.capture(site.url("/a.html"))["bytes"] == len(body)


def test_marker_in_markup_is_still_a_challenge(env):
    site = env.site()
    site.routes["/a.html"] = page(b"<html><script>var x=1</script><div class='g-recaptcha'></div></html>")
    with pytest.raises(SourceRestricted):
        env.capture(site.url("/a.html"))


@pytest.mark.parametrize("script", [
    b"grecaptcha.render('box', {sitekey: 'k'})", b"grecaptcha.execute('k')", b"hcaptcha.render('box')",
    b"turnstile.render('#box')", b"window._cf_chl_opt={cvId:'3'}"])
def test_challenge_code_inside_a_script_is_still_a_challenge(env, script):
    site = env.site()
    site.routes["/a.html"] = page(b"<html><head><title>Sample</title><script>" + script + b"</script></head></html>")
    with pytest.raises(SourceRestricted):
        env.capture(site.url("/a.html"))


@pytest.mark.parametrize("title", ["Just a moment...", "Attention Required! | Example", "Access denied",
                                   "Security verification"])
def test_challenge_titles_are_stopped(env, title):
    site = env.site()
    site.routes["/a.html"] = page(f"<html><head><title>{title}</title></head><body>hello</body></html>".encode())
    with pytest.raises(SourceRestricted):
        env.capture(site.url("/a.html"))


def stopped_env(env):
    site = env.site()
    site.routes["/a.html"] = status(403)
    with pytest.raises(SourceRestricted):
        env.capture(site.url("/a.html"))
    return site


def test_clear_stop_removes_the_stop_and_audits_it(cli, capsys):
    site = stopped_env(cli)
    assert "example-fund" in cli.state_json()["stopped"]
    code = ccs.main(["--state", str(cli.state), "--clear-stop", "example-fund", "--reason", "Operator confirmed access"],
                    clock=cli.clock, sleep=cli.clock.sleep)
    assert code == 0
    state = cli.state_json()
    assert "example-fund" not in state.get("stopped", {})
    entry, = state["clearances"]
    assert entry["source"] == "example-fund" and entry["reason"] == "Operator confirmed access"
    assert "403" in entry["previous_stop"] and entry["cleared_at"].endswith("Z")
    site.routes["/a.html"] = page()
    assert cli.capture(site.url("/a.html"))["status"] == 200


def test_clear_stop_needs_a_reason_and_a_stopped_source(cli):
    stopped_env(cli)
    for argv in (["--clear-stop", "example-fund", "--reason", "  "], ["--clear-stop", "other-source", "--reason", "x"]):
        assert ccs.main(["--state", str(cli.state), *argv], clock=cli.clock, sleep=cli.clock.sleep) == 2
    assert "example-fund" in cli.state_json()["stopped"] and "clearances" not in cli.state_json()


def test_clear_stop_is_exclusive_with_capture(cli):
    with pytest.raises(SystemExit):
        ccs.main(["--state", str(cli.state), "--clear-stop", "example-fund", "--reason", "x",
                  "--url", "http://127.0.0.1:1/a"])
