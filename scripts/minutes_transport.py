#!/usr/bin/env python3
"""Minutes coverage: the one transport. Every request of the minutes-coverage goal, robots.txt included, goes
through `Transport.get`, which enforces, in this order and before any byte leaves the machine:

  1. off-limits hosts (marincounty.gov, novato.gov and their subdomains) are refused outright;
  2. the URL must be admitted by the source's exact-host (plus path-prefix) allow-list (minutes_sources);
  3. a host family with a stop record (<raw>/minutes-fetch-stops.json, re-read before every request, so a stop
     written by any process applies at once) is refused, for every source;
  4. a non-Granicus host must be admitted by its robots.txt, matched for the same product token the User-Agent
     sends; robots that cannot be read (network error, 5xx, an HTML page, a redirect off the allow-list) fail closed;
  5. at least MIN_INTERVAL_S (or the host's larger Crawl-delay) between the end of one request and the start of
     the next to the same host family, robots fetches and redirect hops included.

Every response is checked for a block: a 403, a 429 or a challenge page (a 200 included, robots included) writes a
stop record BEFORE `StopNow` is raised. Redirects are never followed here: the 3xx comes back to the caller, which
requests the next hop only if the source admits it. Every request and robots decision is appended to
<raw>/minutes-fetch-requests.jsonl; that log is the record of what was asked of whom, and when.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from minutes_sources import Source, granicus_authorized, host_family, off_limits
from robots_gate import parse as parse_robots

PRODUCT_TOKEN = "MarinCivicGraph"
USER_AGENT = f"Mozilla/5.0 (compatible; {PRODUCT_TOKEN}/1.0; civic records research; single documents)"
MIN_INTERVAL_S = 3.0
MAX_ROBOTS_HOPS = 5
STOPS_FILE = "minutes-fetch-stops.json"
REQUEST_LOG = "minutes-fetch-requests.jsonl"
CHALLENGE_MARKERS = (b"cf-challenge", b"challenge-platform", b"cf_chl_", b"just a moment", b"attention required",
                     b"checking your browser", b"captcha", b"access denied", b"request unsuccessful. incapsula",
                     b"_incapsula_resource", b"are you a robot", b"bot detection", b"verify you are human")
HTML_SIGNS = (b"<!doctype html", b"<html", b"<head", b"<body", b"<script")

HttpGet = Callable[[str, dict], tuple[int, bytes, dict]]


class Refused(Exception):
    """No request was made. kind: off-limits | not-allow-listed | stopped | robots-disallowed | robots-unreadable."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


class StopNow(Exception):
    """This response was a block; its stop record is already on disk. End the run."""

    def __init__(self, record: dict):
        super().__init__(f"stopped on {record['host_family']}: {record['evidence']}")
        self.record = record


class NetworkError(Exception):
    """The request was made and failed without a response (timeout, reset): a failure, not a stop."""


@dataclass(frozen=True)
class Response:
    url: str
    status: int
    body: bytes
    headers: dict
    location: str | None  # absolute; only on a 3xx with a Location


def http_get(url: str, headers: dict) -> tuple[int, bytes, dict]:
    """One request; redirects are never followed (the caller validates and paces every hop)."""
    import requests  # only the live path needs the network stack

    resp = requests.get(url, headers=headers, timeout=60, allow_redirects=False)
    return resp.status_code, resp.content, {k.lower(): v for k, v in resp.headers.items()}


def _looks_html(body: bytes) -> bool:
    head = body[:4096].lstrip().lower()
    return any(s in head for s in HTML_SIGNS)


def is_challenge(body: bytes, headers: dict, *, robots: bool = False) -> bool:
    """A bot wall. A PDF is never one; a robots file is one only if it is an HTML page naming a wall (a plain-text
    robots file may legitimately disallow `/captcha/`); any other non-PDF naming a wall is one."""
    if (headers.get("cf-mitigated") or "").lower() == "challenge":
        return True
    if body[:5] == b"%PDF-":
        return False
    named = any(m in body[:65536].lower() for m in CHALLENGE_MARKERS)
    return named and (_looks_html(body) or not robots)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Transport:
    def __init__(self, raw: Path, *, http: HttpGet = http_get, sleep=time.sleep, now=time.monotonic,
                 wallclock: Callable[[], str] = _now_iso):
        self.raw = Path(raw)
        self._http, self._sleep, self._now, self._clock = http, sleep, now, wallclock
        self._last: dict[str, float] = {}
        self._delay: dict[str, float] = {}
        self._robots: dict[str, object] = {}  # host → Robots | None (absent) | Refused (cached outcome)
        self.robots_decisions: dict[str, dict] = {}

    # --- stops ------------------------------------------------------------------------------------------------

    def stops(self) -> list[dict]:
        path = self.raw / STOPS_FILE
        return json.loads(path.read_text(encoding="utf-8"))["stops"] if path.is_file() else []

    def stopped(self, family: str) -> dict | None:
        return next((s for s in self.stops() if s["host_family"] == family), None)

    def _write_stop(self, record: dict) -> None:
        path = self.raw / STOPS_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {"stops": self.stops() + [record]}
        fd, tmp = tempfile.mkstemp(prefix=f".{STOPS_FILE}.", dir=path.parent)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=1)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)

    # --- log --------------------------------------------------------------------------------------------------

    def _log(self, entry: dict) -> None:
        path = self.raw / REQUEST_LOG
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, sort_keys=True) + "\n")

    # --- the public entry -------------------------------------------------------------------------------------

    def get(self, url: str, source: Source, *, purpose: str = "document") -> Response:
        host = (urlsplit(url).hostname or "").lower()
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
        if rec := self.stopped(host_family(host)):
            raise Refused("stopped", f"{host_family(host)} has a stop record ({rec['at']}, {rec['source']}: "
                                     f"{rec['evidence']})")

    def _send(self, url: str, source: Source, purpose: str, *, robots: bool = False) -> Response:
        host = (urlsplit(url).hostname or "").lower()
        family = host_family(host)
        self._check_stop(host)
        interval = max(MIN_INTERVAL_S, self._delay.get(family, 0.0))
        if family in self._last and (wait := interval - (self._now() - self._last[family])) > 0:
            self._sleep(wait)
        entry = {"at": self._clock(), "url": url, "purpose": purpose, "source": source.id, "host_family": family}
        try:
            status, body, headers = self._http(url, {"User-Agent": USER_AGENT})
        except Exception as exc:
            self._log(entry | {"error": f"{type(exc).__name__}: {exc}"})
            raise NetworkError(f"{type(exc).__name__}: {exc}") from exc
        finally:
            self._last[family] = self._now()
        headers = {k.lower(): v for k, v in (headers or {}).items()}
        loc = headers.get("location")
        resp = Response(url, status, body, headers, urljoin(url, loc) if loc and 300 <= status < 400 else None)
        self._log(entry | {"status": status, "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(),
                           "location": resp.location})
        challenge = is_challenge(body, headers, robots=robots)
        if status in (403, 429) or challenge:
            evidence = f"HTTP {status}" + (" challenge page" if challenge else "") + f" on {purpose} {url}"
            record = {"host_family": family, "source": source.id, "at": entry["at"], "url": url, "status": status,
                      "evidence": evidence, "body_head": body[:300].decode("utf-8", "replace")}
            self._write_stop(record)
            raise StopNow(record)
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

    def _read_robots(self, host: str, source: Source):
        url = f"https://{host}/robots.txt"
        allowed_hosts = source.robots_hosts() | {host}
        for _ in range(MAX_ROBOTS_HOPS + 1):
            try:
                resp = self._send(url, source, "robots", robots=True)
            except NetworkError as exc:
                self._decide(host, "unreadable", str(exc), source)
                return Refused("robots-unreadable", f"robots.txt of {host} could not be read: {exc}")
            if resp.location:
                target = urlsplit(resp.location)
                t_host = (target.hostname or "").lower()
                if target.scheme != "https" or t_host not in allowed_hosts or off_limits(t_host):
                    detail = f"robots redirect to {resp.location} (not on the allow-list; not requested)"
                    self._decide(host, "unreadable", detail, source)
                    return Refused("robots-unreadable", f"robots.txt of {host}: {detail}")
                url = resp.location
                continue
            if resp.status in (404, 410):
                self._decide(host, "absent", f"HTTP {resp.status}: no robots.txt, everything allowed", source)
                return None
            if resp.status == 200 and not _looks_html(resp.body):
                rules = parse_robots(resp.body.decode("utf-8", "replace"), PRODUCT_TOKEN)
                if rules.crawl_delay:
                    self._delay[host_family(host)] = max(self._delay.get(host_family(host), 0.0), rules.crawl_delay)
                self._decide(host, "read", f"{len(rules.rules)} rules for {PRODUCT_TOKEN}"
                             + (f"; Crawl-delay {rules.crawl_delay}" if rules.crawl_delay else ""), source)
                return rules
            detail = f"HTTP {resp.status}" + (" HTML page, not a robots file" if resp.status == 200 else "")
            self._decide(host, "unreadable", detail, source)
            return Refused("robots-unreadable", f"robots.txt of {host} could not be read: {detail}")
        self._decide(host, "unreadable", "too many robots redirects", source)
        return Refused("robots-unreadable", f"robots.txt of {host}: too many redirects")
