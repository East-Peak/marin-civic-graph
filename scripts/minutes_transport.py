#!/usr/bin/env python3
"""Minutes coverage: the one transport. Every request of the minutes-coverage goal, robots.txt included, goes
through `Transport.get`, which enforces, in this order and before any byte leaves the machine:

  1. the URL is canonical (minutes_sources.canonical_url): what is authorized is byte for byte what is sent, and
     the live client re-checks that `requests` prepares it unchanged;
  2. off-limits hosts (marincounty.gov, novato.gov and their subdomains) are refused outright;
  3. the URL must be admitted by the source's exact-host (plus path-prefix) allow-list (minutes_sources);
  4. a host family with a stop record (<raw>/minutes-fetch-stops.json, re-read before every request, so a stop
     written by any process applies at once; an unreadable file refuses everything) is refused, for every source;
  5. a non-Granicus host must be admitted by its robots.txt, matched for the same product token the User-Agent
     sends; a robots file that is not plainly a robots file (an error page, HTML, a login, bad encoding, 5xx, 401,
     a redirect anywhere but another admitted host's /robots.txt) fails closed;
  6. at least MIN_INTERVAL_S (or the host's larger Crawl-delay) between the end of one request and the start of
     the next to the same host family, robots and redirect hops included, across processes
     (<raw>/minutes-fetch-pacing.json);
  7. the caller's guard (the weekly job window) is asked immediately before the request, after any pacing sleep.

A 403 or 429 writes a stop record as soon as the status line arrives, before the body is read; a challenge or
login page (a 200 included, robots included) writes one after. Either is written BEFORE `StopNow` is raised.
Redirects are never followed here: the 3xx comes back to the caller, which requests the next hop only if the source
admits it. Every request and robots decision is appended to <raw>/minutes-fetch-requests.jsonl.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from minutes_sources import Source, UnsafeUrl, canonical_url, granicus_authorized, host_family, off_limits
from robots_gate import parse as parse_robots

PRODUCT_TOKEN = "MarinCivicGraph"
USER_AGENT = f"Mozilla/5.0 (compatible; {PRODUCT_TOKEN}/1.0; civic records research; single documents)"
MIN_INTERVAL_S = 3.0
MAX_ROBOTS_HOPS = 5
MAX_BODY = 200 * 1024 * 1024
MAX_ROBOTS = 512 * 1024
STOPS_FILE = "minutes-fetch-stops.json"
PACING_FILE = "minutes-fetch-pacing.json"
REQUEST_LOG = "minutes-fetch-requests.jsonl"

# A vendor wall names itself structurally; these anywhere in the first 64 KB of a non-PDF response are a wall.
STRONG_MARKERS = (b"cf-challenge", b"challenge-platform", b"cf_chl_", b"/cdn-cgi/challenge", b"_incapsula_resource",
                  b"request unsuccessful. incapsula", b"g-recaptcha", b"recaptcha/api.js", b"h-captcha",
                  b"hcaptcha.com/1/api.js", b"px-captcha", b"captcha-delivery.com", b"awswaf", b"aws-waf-token")
# Words a wall uses, but so might minutes: a wall only in a page's <title> or on a short page.
WEAK_MARKERS = (b"just a moment", b"attention required", b"checking your browser", b"access denied",
                b"are you a robot", b"verify you are human", b"captcha", b"bot detection", b"unusual traffic",
                b"enable javascript and cookies", b"request blocked")
SHORT_PAGE = 3000  # visible characters
PASSWORD_INPUT = re.compile(rb"<input\b[^>]*\btype\s*=\s*[\"']?password", re.I)
HTML_SIGNS = (b"<!doctype html", b"<html", b"<head", b"<body", b"<script", b"<form", b"<div", b"<input")
ROBOTS_LINE = re.compile(r"^\s*[A-Za-z][A-Za-z-]*\s*:")

OnHead = Callable[[int, dict], None]
HttpGet = Callable[[str, dict, OnHead], tuple[int, bytes, dict]]


class Refused(Exception):
    """No request was made. kind: malformed | off-limits | not-allow-listed | stopped | robots-disallowed |
    robots-unreadable | window."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


class StopNow(Exception):
    """This response was a block; its stop record is already on disk. End the run."""

    def __init__(self, record: dict):
        super().__init__(f"stopped on {record['host_family']}: {record['evidence']}")
        self.record = record


class NetworkError(Exception):
    """The request was made and failed without a usable response (timeout, reset, oversize)."""


@dataclass(frozen=True)
class Response:
    url: str
    status: int
    body: bytes
    headers: dict
    location: str | None  # absolute; only on a 3xx with a Location


def http_get(url: str, headers: dict, on_head: OnHead) -> tuple[int, bytes, dict]:
    """One request, exactly `url`: no redirects, no proxies, no .netrc or other ambient settings, streamed so that
    `on_head` sees the status and headers before any of the body is read (it may raise to abandon the body)."""
    import requests  # only the live path needs the network stack

    session = requests.Session()
    session.trust_env = False  # no proxy variables, no .netrc credentials, no REQUESTS_CA_BUNDLE surprises
    prepared = session.prepare_request(requests.Request("GET", url, headers=headers))
    if prepared.url != url or "Authorization" in prepared.headers:
        raise UnsafeUrl(f"requests would send {prepared.url!r}, not the authorized {url!r}")
    resp = session.send(prepared, allow_redirects=False, stream=True, timeout=(20, 90), proxies={}, verify=True)
    try:
        hdrs = {k.lower(): v for k, v in resp.headers.items()}
        on_head(resp.status_code, hdrs)
        body = bytearray()
        for chunk in resp.iter_content(65536):
            body += chunk
            if len(body) > MAX_BODY:
                raise NetworkError(f"response larger than {MAX_BODY} bytes")
        return resp.status_code, bytes(body), hdrs
    finally:
        resp.close()
        session.close()


def _looks_html(body: bytes) -> bool:
    head = body[:4096].lstrip().lower()
    return any(s in head for s in HTML_SIGNS)


def _visible(body: bytes) -> bytes:
    text = re.sub(rb"(?is)<(script|style)\b.*?</\1>", b" ", body[:262144])
    return re.sub(rb"\s+", b" ", re.sub(rb"(?s)<[^>]*>", b" ", text)).strip()


def wall(body: bytes, headers: dict, *, robots: bool = False) -> str | None:
    """Why this response is a bot wall, CAPTCHA or login page, or None. A PDF never is. A plain-text robots file
    is judged only by vendor markers (it may legitimately disallow `/captcha/`)."""
    if (headers.get("cf-mitigated") or "").lower() == "challenge":
        return "cf-mitigated: challenge header"
    if body[:5] == b"%PDF-":
        return None
    head = body[:65536].lower()
    if strong := next((m for m in STRONG_MARKERS if m in head), None):
        return f"challenge marker {strong.decode()!r}"
    html = _looks_html(body)
    if robots and not html:
        return None
    if html and PASSWORD_INPUT.search(body[:262144]):
        return "login form (password field)"
    title = re.search(rb"(?is)<title[^>]*>(.*?)</title>", head)
    if title and (weak := next((m for m in WEAK_MARKERS if m in title.group(1)), None)):
        return f"wall title {weak.decode()!r}"
    text = _visible(body).lower() if html else head
    if len(text) < SHORT_PAGE and (weak := next((m for m in WEAK_MARKERS if m in text), None)):
        return f"short page naming {weak.decode()!r}"
    return None


def robots_text(body: bytes, headers: dict) -> str | None:
    """The body as robots.txt text, or None when it is not plainly one: wrong type, bad encoding, HTML, or any
    non-comment line that is not a `field: value` line. An empty or comment-only file is a valid empty policy."""
    ctype = (headers.get("content-type") or "").split(";")[0].strip().lower()
    if ctype not in ("", "text/plain") or len(body) > MAX_ROBOTS or _looks_html(body):
        return None
    try:
        text = body.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None
    for line in text.splitlines():
        content = line.split("#", 1)[0].strip()
        if content and not ROBOTS_LINE.match(content):
            return None
    return text


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _atomic_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1, sort_keys=True)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


class Transport:
    def __init__(self, raw: Path, *, http: HttpGet = http_get, sleep=time.sleep, now=time.time,
                 wallclock: Callable[[], str] = _now_iso, guard: Callable[[], None] | None = None):
        self.raw = Path(raw)
        self._http, self._sleep, self._now, self._clock = http, sleep, now, wallclock
        self.guard = guard
        self._robots: dict[str, object] = {}  # host → Robots | None (absent) | Refused (cached outcome)
        self.robots_decisions: dict[str, dict] = {}
        self.sent = 0  # wire requests made by this transport

    # --- stops ------------------------------------------------------------------------------------------------

    def stops(self) -> list[dict]:
        path = self.raw / STOPS_FILE
        return json.loads(path.read_text(encoding="utf-8"))["stops"] if path.is_file() else []

    def stopped(self, family: str) -> dict | None:
        return next((s for s in self.stops() if s["host_family"] == family), None)

    def _write_stop(self, record: dict) -> None:
        _atomic_json(self.raw / STOPS_FILE, {"stops": self.stops() + [record]})

    # --- pacing (persisted: a new process waits for the last one's requests) -----------------------------------

    def _pacing(self) -> dict:
        path = self.raw / PACING_FILE
        data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        return {"last": data.get("last", {}), "delay": data.get("delay", {})}

    def _set_pacing(self, family: str, *, last: float | None = None, delay: float | None = None) -> None:
        data = self._pacing()
        if last is not None:
            data["last"][family] = last
        if delay is not None:
            data["delay"][family] = max(delay, data["delay"].get(family, 0.0))
        _atomic_json(self.raw / PACING_FILE, data)

    # --- log --------------------------------------------------------------------------------------------------

    def _log(self, entry: dict) -> None:
        path = self.raw / REQUEST_LOG
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, sort_keys=True) + "\n")
            fh.flush()
            os.fsync(fh.fileno())

    # --- the public entry -------------------------------------------------------------------------------------

    def get(self, url: str, source: Source, *, purpose: str = "document") -> Response:
        try:
            canonical_url(url)
        except UnsafeUrl as exc:
            raise Refused("malformed", str(exc)) from None
        host = urlsplit(url).hostname
        if off_limits(host):
            raise Refused("off-limits", f"{host} is off-limits to automation")
        if not source.admits(url):
            raise Refused("not-allow-listed", f"not on {source.id}'s allow-list: {url}")
        self._check_stop(host)
        if not granicus_authorized(url, source.rules):
            self._admit_by_robots(url, host, source)
        return self._send(url, source, purpose)

    # --- internals --------------------------------------------------------------------------------------------

    def _check_stop(self, host: str) -> None:
        try:
            rec = self.stopped(host_family(host))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise Refused("stopped", f"the stops file cannot be read ({type(exc).__name__}); refusing all") from None
        if rec:
            raise Refused("stopped", f"{host_family(host)} has a stop record ({rec['at']}, {rec['source']}: "
                                     f"{rec['evidence']})")

    def _stop(self, family: str, source: Source, url: str, purpose: str, status: int, why: str, at: str,
              body: bytes = b"") -> StopNow:
        record = {"host_family": family, "source": source.id, "at": at, "url": url, "status": status,
                  "evidence": f"HTTP {status} {why} on {purpose} {url}",
                  "body_head": body[:300].decode("utf-8", "replace")}
        self._write_stop(record)
        return StopNow(record)

    def _send(self, url: str, source: Source, purpose: str, *, robots: bool = False) -> Response:
        host = urlsplit(url).hostname
        family = host_family(host)
        self._check_stop(host)
        pacing = self._pacing()
        interval = max(MIN_INTERVAL_S, pacing["delay"].get(family, 0.0))
        if family in pacing["last"] and (wait := interval - (self._now() - pacing["last"][family])) > 0:
            self._sleep(wait)
        if self.guard:
            self.guard()
        self._check_stop(host)
        entry = {"at": self._clock(), "url": url, "purpose": purpose, "source": source.id, "host_family": family}

        def on_head(status: int, headers: dict) -> None:
            if status in (403, 429):
                shown = {k: v for k, v in headers.items() if k in ("retry-after", "server", "cf-ray")}
                self._log(entry | {"status": status, "head_only": True})
                raise self._stop(family, source, url, purpose, status, f"(headers {shown})", entry["at"])

        self.sent += 1
        try:
            status, body, headers = self._http(url, {"User-Agent": USER_AGENT}, on_head)
        except StopNow:
            raise
        except UnsafeUrl as exc:
            self.sent -= 1
            raise Refused("malformed", str(exc)) from None
        except Exception as exc:
            self._log(entry | {"error": f"{type(exc).__name__}: {exc}"})
            raise NetworkError(f"{type(exc).__name__}: {exc}") from exc
        finally:
            self._set_pacing(family, last=self._now())
        headers = {k.lower(): v for k, v in (headers or {}).items()}
        loc = headers.get("location")
        resp = Response(url, status, body, headers, urljoin(url, loc) if loc and 300 <= status < 400 else None)
        self._log(entry | {"status": status, "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(),
                           "location": resp.location})
        if why := wall(body, headers, robots=robots):
            raise self._stop(family, source, url, purpose, status, why, entry["at"], body)
        return resp

    def _admit_by_robots(self, url: str, host: str, source: Source) -> None:
        if host not in self._robots:
            self._robots[host] = self._read_robots(host, source)
        outcome = self._robots[host]
        if isinstance(outcome, Refused):
            raise outcome
        if outcome is None:
            return
        allowed, rule = outcome.decide(url)
        if not allowed:
            raise Refused("robots-disallowed", f"robots.txt of {host} disallows {url} ({rule})")

    def _decide(self, host: str, decision: str, detail: str, source: Source) -> None:
        self.robots_decisions[host] = {"decision": decision, "detail": detail}
        self._log({"at": self._clock(), "purpose": "robots-decision", "host": host, "source": source.id,
                   "decision": decision, "detail": detail})

    def _unreadable(self, host: str, detail: str, source: Source) -> Refused:
        self._decide(host, "unreadable", detail, source)
        return Refused("robots-unreadable", f"robots.txt of {host} could not be read ({detail}); fail closed")

    def _read_robots(self, host: str, source: Source):
        url = f"https://{host}/robots.txt"
        robots_hosts = source.robots_hosts() | {host}
        for _ in range(MAX_ROBOTS_HOPS + 1):
            try:
                resp = self._send(url, source, "robots", robots=True)
            except NetworkError as exc:
                return self._unreadable(host, str(exc), source)
            if 300 <= resp.status < 400:
                target = resp.location
                ok = False
                if target:
                    try:
                        canonical_url(target)
                        t = urlsplit(target)
                        ok = t.path == "/robots.txt" and not t.query and t.hostname in robots_hosts \
                            and not off_limits(t.hostname)
                    except UnsafeUrl:
                        ok = False
                if not ok:
                    return self._unreadable(host, f"HTTP {resp.status} redirect to {target or '(no Location)'} "
                                                  "(not an admitted host's /robots.txt; not requested)", source)
                url = target
                continue
            if resp.status in (404, 410):
                self._decide(host, "absent", f"HTTP {resp.status}: no robots.txt, everything allowed", source)
                return None
            if resp.status != 200:
                return self._unreadable(host, f"HTTP {resp.status}", source)
            text = robots_text(resp.body, resp.headers)
            if text is None:
                return self._unreadable(host, "HTTP 200 but not plainly a robots.txt file", source)
            rules = parse_robots(text, PRODUCT_TOKEN)
            if rules.crawl_delay:
                self._set_pacing(host_family(host), delay=rules.crawl_delay)
            self._decide(host, "read", f"{len(rules.rules)} rules for {PRODUCT_TOKEN}"
                         + (f"; Crawl-delay {rules.crawl_delay}" if rules.crawl_delay else ""), source)
            return rules
        return self._unreadable(host, "too many robots redirects", source)
