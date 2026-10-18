"""The robots.txt gate: every request a meeting adapter makes goes through `RobotsGate.open`.

Before any request (and before each redirect hop) the URL is checked against its host's
robots.txt for our product token. The file is fetched at most once per host per run: the
outcome, outages included, is cached in memory and, when the run names one, in a JSON cache
file that later processes of the same run share. Disallowed -> `RobotsDisallowed` (with the
matching rule) and no request; robots.txt unreachable, timed out or answering anything but
2xx / 404 / 410 -> `RobotsUnavailable` (conservative); 404 / 410 -> everything allowed.
`Crawl-delay` spaces every request to that host, the robots fetch included.

Matching follows RFC 9309 (`*` and `$` wildcards, longest match wins, Allow wins a tie,
same-agent groups merge). `urllib.robotparser` only prefix-matches, so it would read
`Disallow: /*?pager=` as allowing every pager URL; this module is the one parser here
(scripts/capture_case_source.py uses it too).
"""
from __future__ import annotations

import hashlib
import http.client
import json
import os
import re
import string
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, NamedTuple
from urllib.parse import quote, urljoin, urlsplit

PRODUCT_TOKEN = "MarinCivicGraph"
USER_AGENT = f"Mozilla/5.0 (compatible; {PRODUCT_TOKEN}/1.0)"
ROBOTS_TIMEOUT = 30
MAX_REDIRECTS = 5  # RFC 9309 asks crawlers to follow at least five
REDIRECTS = (301, 302, 303, 307, 308)
ABSENT = (404, 410)  # no robots.txt: everything is allowed

_SAFE = "".join(chr(c) for c in range(33, 127))  # leave printable ASCII (and existing %XX) alone
_UNRESERVED = frozenset(string.ascii_letters + string.digits + "-._~")


# --- the parser ----------------------------------------------------------------------


def _norm(text: str) -> str:
    """RFC 9309 / 3986 comparison form: non-ASCII percent-encoded, escaped unreserved characters decoded,
    every other escape upper-cased; so `/%70rivate` meets `Disallow: /private`, and `%2F` stays a non-slash."""
    def escape(match: re.Match) -> str:
        char = chr(int(match.group(1), 16))
        return char if char in _UNRESERVED else match.group().upper()
    return re.sub(r"%([0-9A-Fa-f]{2})", escape, quote(text, safe=_SAFE))


class Rule(NamedTuple):
    allow: bool
    pattern: str
    regex: re.Pattern

    @property
    def line(self) -> str:
        return f"{'Allow' if self.allow else 'Disallow'}: {self.pattern}"


def _rule(allow: bool, pattern: str) -> Rule:
    anchored = pattern.endswith("$")
    body = _norm(pattern[:-1] if anchored else pattern)
    regex = ".*".join(re.escape(part) for part in body.split("*")) + (r"\Z" if anchored else "")
    return Rule(allow, pattern, re.compile(regex, re.S))


class Robots(NamedTuple):
    rules: tuple[Rule, ...]
    crawl_delay: float | None

    def decide(self, url: str) -> tuple[bool, str | None]:
        """(allowed, the matching rule's line or None when no rule matched)."""
        parts = urlsplit(url)
        path = _norm((parts.path or "/") + (f"?{parts.query}" if parts.query else ""))
        matches = [rule for rule in self.rules if rule.regex.match(path)]
        if not matches:
            return True, None
        best = max(matches, key=lambda rule: (len(_norm(rule.pattern)), rule.allow))
        return best.allow, best.line


def parse(text: str, token: str = PRODUCT_TOKEN) -> Robots:
    """The rules that apply to `token`: its own groups if any name it, else every `*` group, merged."""
    groups: list[dict] = []
    current, in_agents = None, False
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        key, sep, value = line.partition(":")
        if not sep:
            continue
        key, value = key.strip().lower(), value.strip()
        if key == "user-agent":
            if current is None or not in_agents:
                current = {"agents": [], "rules": [], "delays": []}
                groups.append(current)
            current["agents"].append(value.split("/", 1)[0].strip().lower())
            in_agents = True
        elif key in ("allow", "disallow", "crawl-delay"):
            in_agents = False
            if current is None:  # a rule before any user-agent line belongs to no group
                continue
            if key == "crawl-delay":
                try:
                    delay = float(value)
                except ValueError:
                    continue
                if delay >= 0:
                    current["delays"].append(delay)
            elif value:  # an empty Disallow (or Allow) is no rule
                current["rules"].append(_rule(key == "allow", value))
    ours = [g for g in groups if token.lower() in g["agents"]] or [g for g in groups if "*" in g["agents"]]
    delays = [d for g in ours for d in g["delays"]]
    return Robots(tuple(rule for g in ours for rule in g["rules"]), max(delays) if delays else None)


# --- refusals ------------------------------------------------------------------------


class RobotsRefused(Exception):
    """The gate said no; no request was made. `outcome` names it in the run's state and digest."""

    outcome = "robots_refused"

    def __init__(self, url: str, detail: dict):
        self.url, self.detail = url, detail
        why = detail.get("rule") or f"robots.txt status {detail.get('robots_status')} {detail.get('error') or ''}"
        super().__init__(f"{self.outcome}: {url} ({why.strip()}; {detail.get('robots_url')})")


class RobotsDisallowed(RobotsRefused):
    outcome = "robots_disallowed"


class RobotsUnavailable(RobotsRefused):
    outcome = "robots_unavailable"


class HostNotAllowed(RobotsRefused):
    """The URL's host is outside the source's allowlist: not even its robots.txt is requested."""

    outcome = "host_not_allowed"


# --- transport -----------------------------------------------------------------------


class Reply(NamedTuple):
    status: int | None  # None: no HTTP answer at all (timeout, refused, DNS)
    headers: dict
    body: bytes
    error: str | None


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # the gate walks robots.txt redirects itself, one logged hop at a time


def http_get(url: str, timeout: float) -> Reply:
    """One GET, no retries, redirects returned rather than followed."""
    opener = urllib.request.build_opener(_NoRedirects)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        try:
            with opener.open(request, timeout=timeout) as resp:
                return Reply(resp.status, dict(resp.headers), resp.read(), None)
        except urllib.error.HTTPError as err:
            with err:
                return Reply(err.code, dict(err.headers or {}), err.read() or b"", None)
    except (urllib.error.URLError, http.client.HTTPException, OSError) as exc:  # incl. a truncated body
        return Reply(None, {}, b"", type(getattr(exc, "reason", exc)).__name__)


class _GatedRedirects(urllib.request.HTTPRedirectHandler):
    """urllib's own redirect handling, with every hop admitted by the gate first."""

    def __init__(self, gate: "RobotsGate", hosts: frozenset[str] | None = None):
        self.gate, self.hosts = gate, hosts

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None:
            # Drain this reply first (urllib would, right after us), so the hop is paced from when it is sent.
            fp.read()
            fp.close()
            self.gate.admit(new.full_url, kind="redirect", method=new.get_method(), hosts=self.hosts)
        return new


# --- the gate ------------------------------------------------------------------------


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme.lower()}://{parts.netloc.lower()}"


PRIVATE = ("body", "last_request_wall")  # kept in the cache file, never in a run's state


def summarize(cache: dict[str, dict]) -> dict[str, dict]:
    """A robots cache as a run records it: per origin, its robots.txt URL, status, sha256, fetch time."""
    return {origin: {k: v for k, v in entry.items() if k not in PRIVATE} for origin, entry in cache.items()}


class RobotsGate:
    def __init__(self, *, cache_path: Path | None = None, request_log: Path | None = None,
                 token: str = PRODUCT_TOKEN, robots_transport: Callable[[str, float], Reply] = http_get,
                 clock: Callable[[], float] = time.monotonic, wall_clock: Callable[[], float] = time.time,
                 sleep: Callable[[float], None] = time.sleep, robots_timeout: float = ROBOTS_TIMEOUT):
        self.cache_path = Path(cache_path) if cache_path else None
        self.request_log = Path(request_log) if request_log else None
        self.token, self.transport, self.robots_timeout = token, robots_transport, robots_timeout
        self.clock, self.wall_clock, self.sleep = clock, wall_clock, sleep
        self.cache: dict[str, dict] = {}
        if self.cache_path and self.cache_path.is_file():
            self.cache = json.loads(self.cache_path.read_text(encoding="utf-8"))
        self.refusals: list[RobotsRefused] = []
        self._last: dict[str, float] = {}  # netloc -> when (on `clock`) we last sent it a request
        for origin, entry in self.cache.items():  # an earlier process of this run: keep its pacing
            if "last_request_wall" in entry:
                ago = max(0.0, self.wall_clock() - entry["last_request_wall"])
                self._last[urlsplit(origin).netloc] = self.clock() - ago
        self._parsed: dict[str, Robots] = {}

    def open(self, request: urllib.request.Request, *, timeout: float, handlers=(), hosts=None):
        """Admit the request, then send it; each redirect hop is admitted before it is followed.

        `hosts`, when given, is the source's allowlist: a URL (or redirect hop, or robots.txt redirect) on any
        other host is refused before anything is sent to it.
        """
        hosts = frozenset(hosts) if hosts is not None else None
        self.admit(request.full_url, method=request.get_method(), hosts=hosts)
        opener = urllib.request.build_opener(_GatedRedirects(self, hosts), *handlers)
        return opener.open(request, timeout=timeout)

    def admit(self, url: str, *, kind: str = "page", method: str = "GET", hosts=None) -> None:
        """Return when `url` may be requested now (after any Crawl-delay wait); raise if it may not."""
        if hosts is not None and _host(url) not in hosts:
            self._refuse(HostNotAllowed(url, {"url": url, "robots_url": None, "robots_status": None,
                                              "rule": f"host not in {sorted(hosts)}"}), kind, method)
        origin = _origin(url)
        entry = self._robots(origin, hosts)
        status = entry["status"]
        detail = {"url": url, "robots_url": entry["url"], "robots_status": status}
        if status is not None and 200 <= status < 300:
            robots = self._parsed.setdefault(origin, parse(entry["body"], self.token))
            allowed, rule = robots.decide(url)
            if not allowed:
                self._refuse(RobotsDisallowed(url, {**detail, "rule": rule, "robots_sha256": entry["sha256"]}),
                             kind, method)
        elif status not in ABSENT:
            self._refuse(RobotsUnavailable(url, {**detail, "error": entry.get("error")}), kind, method)
        waited = self._pace(url)
        self._log(kind=kind, method=method, url=url, decision="allowed", waited=waited)

    def summary(self) -> dict[str, dict]:
        """The run's robots record for state.json: everything but the bodies."""
        return summarize(self.cache)

    # internals

    def _refuse(self, refusal: RobotsRefused, kind: str, method: str):
        self.refusals.append(refusal)
        self._log(kind=kind, method=method, url=refusal.url, decision=refusal.outcome.removeprefix("robots_"),
                  rule=refusal.detail.get("rule"), waited=0.0)
        raise refusal

    def _robots(self, origin: str, hosts=None) -> dict:
        """`origin`'s robots.txt entry. Under an allowlist, an answer that came via another host is not one."""
        if origin not in self.cache:
            stopped = self._fetch_robots(origin, hosts)
            if stopped is not None:
                return stopped
        entry = self.cache[origin]
        if hosts is not None and _host(entry["final_url"]) not in hosts:
            return {**entry, "status": None, "error": "robots.txt answered via a host not allowed"}
        return entry

    def _fetch_robots(self, origin: str, hosts=None) -> dict | None:
        """Read `origin`'s robots.txt, following redirects; every host's /robots.txt on the way gets the answer.

        A redirect to a host outside `hosts` is not followed: the robots.txt counts as unavailable for this
        caller only, so it is returned rather than cached (a source without that allowlist reads it normally)."""
        url = f"{origin}/robots.txt"
        chain = [origin]  # origins whose /robots.txt this chain answers
        entry = None
        for hop in range(MAX_REDIRECTS + 1):
            waited = self._pace(url)  # a hop to a host we already know keeps its Crawl-delay
            sent = (self.clock(), self.wall_clock())
            reply = self.transport(url, self.robots_timeout)
            self._log(kind="robots", method="GET", url=url, decision="fetched", status=reply.status,
                      error=reply.error, waited=waited, sent=sent)
            location = {k.lower(): v for k, v in reply.headers.items()}.get("location")
            if not (reply.status in REDIRECTS and location and hop < MAX_REDIRECTS):
                break
            url = urljoin(url, location)
            if hosts is not None and _host(url) not in hosts:
                return {"url": f"{origin}/robots.txt", "final_url": url, "status": None,
                        "error": "redirect to a host not allowed", "sha256": None, "body": ""}
            if urlsplit(url).path == "/robots.txt":
                if _origin(url) in self.cache:  # already read this run
                    entry = self.cache[_origin(url)]
                    break
                chain.append(_origin(url))
        if entry is None:
            ok = reply.status is not None and 200 <= reply.status < 300
            entry = {"final_url": url, "status": reply.status, "error": reply.error,
                     "sha256": hashlib.sha256(reply.body).hexdigest() if ok else None,
                     "fetched_at": self._now_iso(), "body": reply.body.decode("utf-8", "replace") if ok else ""}
        for host in chain:
            if host not in self.cache:
                self.cache[host] = {**entry, "url": f"{host}/robots.txt", "last_request_wall": self.wall_clock()}
        self._save()
        return None

    def _crawl_delay(self, origin: str) -> float:
        entry = self.cache[origin]
        if entry["status"] is None or not 200 <= entry["status"] < 300:
            return 0.0
        return self._parsed.setdefault(origin, parse(entry["body"], self.token)).crawl_delay or 0.0

    def _pace(self, url: str) -> float:
        """Wait out the host's Crawl-delay (when its robots.txt is known) since our last request to it,
        then mark this request as sent. Returns the seconds waited."""
        netloc = urlsplit(url).netloc.lower()
        delay = max((self._crawl_delay(origin) for origin in self.cache if urlsplit(origin).netloc == netloc),
                    default=0.0)  # http and https of one host share its delay
        waited = 0.0
        if netloc in self._last:
            waited = max(0.0, self._last[netloc] + delay - self.clock())
            if waited:
                self.sleep(waited)
        self._mark(url)
        return waited

    def _save(self) -> None:
        if not self.cache_path:
            return
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.cache_path.parent, prefix=f".{self.cache_path.name}.")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(self.cache, fh, indent=2, sort_keys=True)
        os.replace(tmp, self.cache_path)

    def _mark(self, url: str) -> None:
        """A request to `url`'s host goes out now; recorded in the cache file too, for the run's next process."""
        self._last[urlsplit(url).netloc.lower()] = self.clock()
        entry = self.cache.get(_origin(url))
        if entry is not None:
            entry["last_request_wall"] = self.wall_clock()
            self._save()

    def _now_iso(self) -> str:
        return datetime.fromtimestamp(self.wall_clock(), timezone.utc).isoformat(timespec="milliseconds")

    def _log(self, *, sent: tuple[float, float] | None = None, **fields) -> None:
        """One request decision; stamped when the request was sent (`sent`: monotonic, wall) or now."""
        if not self.request_log:
            return
        self.request_log.parent.mkdir(parents=True, exist_ok=True)
        monotonic, wall = sent or (self.clock(), self.wall_clock())
        entry = {"at": datetime.fromtimestamp(wall, timezone.utc).isoformat(timespec="milliseconds"),
                 "monotonic": monotonic, **{k: v for k, v in fields.items() if v is not None}}
        with self.request_log.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, sort_keys=True) + "\n")
