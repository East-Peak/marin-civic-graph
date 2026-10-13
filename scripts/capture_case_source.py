#!/usr/bin/env python3
"""Polite, auditable capture of single public documents for a case study (CF6).

Why this exists: a case file must show, for every document it rests on, that we
were allowed to fetch it and exactly what we fetched. So every capture is gated
by an operator-written host basis (explicit "allowed" + terms/licence text),
robots.txt, a 1 s global throttle, a per-run document budget and a
stopped-source latch, and every document lands with a manifest row recording the
bytes' sha256 and the access decision that permitted it.

Design notes:
  * urllib only, and redirects are NEVER followed automatically: each hop is
    re-checked (basis, robots, throttle) before it is requested, so a redirect
    to an unapproved host is never contacted.
  * Throttle timestamps, robots cache, document counter and stopped sources live
    in one JSON state file updated under an fcntl lock, so separate invocations
    share them.
  * `capture_zip_member` reads ONE member of a remote ZIP with HTTP Range
    requests through a seekable reader (central directory + member data only).

Usage:
  python scripts/capture_case_source.py --source S --raw-root .../data/raw \\
      --state STATE --basis BASIS (--url U | --zip-url Z --member M) [--cap N]
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import Message
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit
from urllib.robotparser import RobotFileParser

STAGING_ROOT = Path.home() / "open-marin-staging" / "cf6-case"
USER_AGENT = "OpenMarinCaseCapture/1.0 (public-records research; polite single-document fetches)"
DEFAULT_CAP = 60
MIN_INTERVAL = 1.0  # seconds between ANY two requests
MAX_RETRY_WAIT = 120.0  # longest Retry-After we are willing to sit out
MAX_HOPS = 5
RANGE_CHUNK = 512 * 1024  # read-ahead for ZIP member reads
TIMEOUT = 30

LOGIN_PATH_RE = re.compile(r"(?<![a-z0-9])(login|signin|sign-in|sso|auth|account)s?(?![a-z0-9])")
PASSWORD_INPUT_RE = re.compile(r"<input\b[^>]*\btype\s*=\s*[\"']?password", re.I)
RESTRICTION_MARKERS = (
    "captcha", "g-recaptcha", "hcaptcha", "cf-challenge", "cf-turnstile", "subscribe to continue", "paywall",
)
SOURCE_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class AccessRefused(Exception):
    """We may not (or cannot safely) make this request; nothing was written."""


class SourceRestricted(AccessRefused):
    """The source says no (robots, login, captcha, rate limit); further capture stops."""


class BudgetExhausted(AccessRefused):
    """The document cap would be exceeded."""


class NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # surfaces the 3xx as an HTTPError we inspect ourselves


@dataclass
class Response:
    status: int | None
    headers: Message
    body: bytes
    final_url: str
    access: dict


# --- state file ---------------------------------------------------------------------


def read_state(path: Path) -> dict:
    return json.loads(path.read_text()) if path.exists() else {}


@contextmanager
def locked_state(path: Path):
    """Yield the state dict; persist it atomically if the block completes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(f"{path}.lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = read_state(path)
        yield state
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(state, indent=2, sort_keys=True))
        os.replace(tmp, path)


def check_budget(state_path: Path, cap: int) -> None:
    if read_state(state_path).get("documents", 0) >= cap:
        raise BudgetExhausted(f"document budget of {cap} is used up")


def count_document(state_path: Path, cap: int) -> None:
    with locked_state(state_path) as state:
        if state.get("documents", 0) >= cap:
            raise BudgetExhausted(f"document budget of {cap} is used up")
        state["documents"] = state.get("documents", 0) + 1


# --- guarded fetching ---------------------------------------------------------------


def parse_retry_after(value: str | None, now: float) -> float | None:
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        return max(0.0, parsedate_to_datetime(value).timestamp() - now)
    except (TypeError, ValueError):
        return None


def looks_restricted(body: bytes, content_type: str | None) -> bool:
    if content_type and "html" not in content_type.lower():
        return False
    text = body[:500_000].decode("utf-8", "replace")
    lowered = text.lower()
    return bool(PASSWORD_INPUT_RE.search(text)) or any(m in lowered for m in RESTRICTION_MARKERS)


class Fetcher:
    """Every request this module makes goes through here."""

    def __init__(self, *, source, state_path, basis_path, user_agent, clock, sleep):
        if not SOURCE_RE.match(source):
            raise AccessRefused(f"source id {source!r} must match {SOURCE_RE.pattern}")
        self.source, self.state_path, self.user_agent = source, Path(state_path), user_agent
        self.hosts = read_state(Path(basis_path)).get("hosts", {})  # a missing basis file approves nothing
        self.clock, self.sleep = clock, sleep
        self.opener = urllib.request.build_opener(NoRedirects)
        self.robots_memo: dict[str, dict] = {}

    # state helpers
    def ensure_not_stopped(self) -> None:
        reason = read_state(self.state_path).get("stopped", {}).get(self.source)
        if reason:
            raise SourceRestricted(f"source {self.source!r} is stopped: {reason}")

    def stop(self, reason: str) -> SourceRestricted:
        with locked_state(self.state_path) as state:
            state.setdefault("stopped", {})[self.source] = reason
        return SourceRestricted(f"source {self.source!r} stopped: {reason}")

    def throttle(self, netloc: str) -> None:
        with locked_state(self.state_path) as state:
            last = state.setdefault("last_request", {})
            ready = max(last.get("*", 0.0), last.get(netloc, 0.0)) + MIN_INTERVAL
            if ready > self.clock():
                self.sleep(ready - self.clock())
            last["*"] = last[netloc] = self.clock()

    def send(self, url: str, method: str, headers: dict) -> tuple[int | None, Message, bytes]:
        """One throttled request; HTTP errors are returned, not raised."""
        self.throttle(urlsplit(url).netloc.lower())
        request = urllib.request.Request(url, method=method, headers={"User-Agent": self.user_agent, **headers})
        try:
            with self.opener.open(request, timeout=TIMEOUT) as response:
                return response.status, response.headers, response.read()
        except urllib.error.HTTPError as err:
            with err:
                return err.code, err.headers, err.read()
        except (urllib.error.URLError, OSError):
            return None, Message(), b""

    # policy checks
    def host_entry(self, netloc: str) -> dict:
        entry = self.hosts.get(netloc)
        if not entry or entry.get("decision") != "allowed":
            raise AccessRefused(f"host {netloc!r} has no affirmative 'allowed' decision in the basis file")
        return entry

    def robots_for(self, url: str) -> dict:
        parts = urlsplit(url)
        key = f"{parts.scheme}://{parts.netloc.lower()}"
        if key in self.robots_memo:
            return self.robots_memo[key]
        cached = read_state(self.state_path).get("robots", {}).get(key)
        if cached is None:
            robots_url = f"{key}/robots.txt"
            status, _, body = self.send(robots_url, "GET", {})
            cached = {
                "url": robots_url,
                "status": status,
                "sha256": hashlib.sha256(body).hexdigest() if status and 200 <= status < 300 else None,
                "body": body.decode("utf-8", "replace") if status and 200 <= status < 300 else "",
            }
            if status and (200 <= status < 300 or 400 <= status < 500):  # outages are not cached
                with locked_state(self.state_path) as state:
                    state.setdefault("robots", {})[key] = cached
        self.robots_memo[key] = cached
        return cached

    def check_robots(self, url: str, entry: dict) -> dict:
        robots = self.robots_for(url)
        status = robots["status"]
        access = {"robots": "allowed", "robots_url": robots["url"], "robots_status": status,
                  "robots_sha256": robots["sha256"]}
        if status is not None and 200 <= status < 300:
            parser = RobotFileParser()
            parser.parse(robots["body"].splitlines())
            if not parser.can_fetch(self.user_agent, url):
                raise SourceRestricted(f"robots.txt disallows {url}")
        elif status is None or status >= 500 or status >= 300 and status < 400:
            basis = entry.get("robots_unavailable_basis")
            if not basis:
                raise AccessRefused(f"robots.txt unavailable (status {status}) and the host has no robots_unavailable_basis")
            access["robots_unavailable_basis"] = basis
        return access  # 4xx: no robots file, everything allowed

    def request_with_retry(self, url: str, method: str, headers: dict) -> tuple[int | None, Message, bytes]:
        for attempt in (0, 1):
            status, response_headers, body = self.send(url, method, headers)
            if status not in (429, 503):
                return status, response_headers, body
            wait = parse_retry_after(response_headers.get("Retry-After"), self.clock())
            if attempt or wait is None or wait > MAX_RETRY_WAIT:
                raise self.stop(f"HTTP {status} from {urlsplit(url).netloc} (Retry-After {response_headers.get('Retry-After')})")
            self.sleep(wait)
        raise AssertionError("unreachable")

    def get(self, url: str, *, method="GET", headers=None, sniff=True) -> Response:
        """Fetch `url`, walking redirects hop by hop through every check."""
        for _ in range(MAX_HOPS + 1):
            parts = urlsplit(url)
            if parts.scheme not in ("http", "https"):
                raise AccessRefused(f"unsupported URL scheme in {url!r}")
            self.ensure_not_stopped()
            entry = self.host_entry(parts.netloc.lower())
            access = {**self.check_robots(url, entry), "user_agent": self.user_agent,
                      **{k: entry.get(k) for k in ("decision", "basis", "terms_url", "licence", "attribution")}}
            status, response_headers, body = self.request_with_retry(url, method, headers or {})
            if status is not None and 300 <= status < 400:
                location = response_headers.get("Location")
                if not location:
                    raise AccessRefused(f"HTTP {status} without Location from {url}")
                url = urljoin(url, location)
                if LOGIN_PATH_RE.search(urlsplit(url).path.lower()):
                    raise self.stop(f"redirect to a login-like path: {urlsplit(url).path}")
                continue
            if status in (401, 403):
                raise self.stop(f"HTTP {status} from {parts.netloc}")
            if status is None or not 200 <= status < 300:
                raise AccessRefused(f"HTTP {status} from {url}")
            if sniff and looks_restricted(body, response_headers.get("Content-Type")):
                raise self.stop(f"login, captcha or paywall page at {url}")
            return Response(status, response_headers, body, url, access)
        raise AccessRefused(f"more than {MAX_HOPS} redirects")


# --- manifest and files -------------------------------------------------------------


def manifest_rows(raw_root: Path, source: str):
    for manifest in sorted((raw_root / source).glob("*/manifest.jsonl")):
        for line in manifest.read_text().splitlines():
            if line.strip():
                yield json.loads(line)


def safe_filename(name: str) -> str:
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).lstrip("._")[-120:]
    return name or "index"


def write_document(raw_root: Path, source: str, day: str, name: str, data: bytes) -> Path:
    folder = raw_root / source / day
    folder.mkdir(parents=True, exist_ok=True)
    stem, dot, suffix = name.rpartition(".") if "." in name else (name, "", "")
    for n in range(10_000):
        candidate = folder / (name if n == 0 else f"{stem}-{n}{dot}{suffix}")
        try:
            with open(candidate, "xb") as handle:
                handle.write(data)
            return candidate
        except FileExistsError:
            continue
    raise AccessRefused(f"could not find a free filename for {name!r}")


def finish(fetcher: Fetcher, *, raw_root, day, name, data, cap, now, access, fields) -> dict:
    """Count the document, write it and its manifest row; return the row."""
    count_document(fetcher.state_path, cap)
    written = write_document(Path(raw_root), fetcher.source, day, name, data)
    row = {
        "retrieved_at": datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
        "path": written.relative_to(raw_root).as_posix(),
        **fields,
        "access": access,
    }
    with open(written.parent / "manifest.jsonl", "a") as manifest:
        manifest.write(json.dumps(row, sort_keys=True) + "\n")
    return row


def start(source, raw_root, state_path, basis_path, date, user_agent, clock, sleep):
    fetcher = Fetcher(source=source, state_path=state_path, basis_path=basis_path,
                      user_agent=user_agent, clock=clock, sleep=sleep)
    day = str(date) if date else datetime.fromtimestamp(clock(), timezone.utc).strftime("%Y-%m-%d")
    if not DATE_RE.match(day):
        raise AccessRefused(f"date {day!r} must be YYYY-MM-DD")
    return fetcher, day


# --- public API ---------------------------------------------------------------------


def capture(url, *, source, raw_root, state_path, basis_path, date=None, user_agent=USER_AGENT,
            cap=DEFAULT_CAP, clock=time.time, sleep=time.sleep) -> dict:
    """Fetch one document once; return its manifest row."""
    raw_root = Path(raw_root)
    fetcher, day = start(source, raw_root, state_path, basis_path, date, user_agent, clock, sleep)
    for row in manifest_rows(raw_root, source):
        if row["url"] == url and "member" not in row:
            return row
    fetcher.ensure_not_stopped()
    check_budget(fetcher.state_path, cap)
    response = fetcher.get(url)
    headers = response.headers
    name = safe_filename(unquote(urlsplit(response.final_url).path.rpartition("/")[2]))
    return finish(
        fetcher, raw_root=raw_root, day=day, name=name, data=response.body, cap=cap, now=clock(),
        access=response.access,
        fields={"url": url, "final_url": response.final_url, "content_type": headers.get_content_type()
                if headers.get("Content-Type") else None, "status": response.status,
                "etag": headers.get("ETag"), "last_modified": headers.get("Last-Modified")},
    )


class RangeReader(io.RawIOBase):
    """Seekable read-only view of a remote file, fetched with throttled Range requests."""

    def __init__(self, fetcher: Fetcher, url: str, chunk: int = RANGE_CHUNK):
        self.fetcher, self.chunk = fetcher, chunk
        self.requests, self.pos, self.block = 0, 0, (0, b"")
        probe = self.fetch(url, 0, 0)
        self.url, self.length = probe.final_url, int(probe.headers["Content-Range"].rpartition("/")[2])
        self.etag, self.last_modified = probe.headers.get("ETag"), probe.headers.get("Last-Modified")
        self.access = probe.access

    def fetch(self, url: str, first: int, last: int) -> Response:
        response = self.fetcher.get(url, headers={"Range": f"bytes={first}-{last}"}, sniff=False)
        self.requests += 1
        match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", response.headers.get("Content-Range", ""))
        if response.status != 206 or not match or int(match[1]) != first or int(match[2]) < first \
                or int(match[2]) > last or len(response.body) != int(match[2]) - first + 1:
            raise AccessRefused(f"server did not honour Range bytes={first}-{last} (status {response.status})")
        if hasattr(self, "length") and (int(match[3]) != self.length or
                                        response.headers.get("ETag") != self.etag):
            raise AccessRefused("remote file changed while it was being read")
        return response

    def readable(self): return True
    def seekable(self): return True
    def tell(self): return self.pos

    def seek(self, offset, whence=io.SEEK_SET):
        base = {io.SEEK_SET: 0, io.SEEK_CUR: self.pos, io.SEEK_END: self.length}[whence]
        self.pos = max(0, base + offset)
        return self.pos

    def read(self, size=-1):
        end = self.length if size is None or size < 0 else min(self.length, self.pos + size)
        out = bytearray()
        while self.pos < end:
            start, data = self.block
            if not start <= self.pos < start + len(data):
                last = min(self.length, self.pos + max(self.chunk, end - self.pos)) - 1
                start, data = self.pos, self.fetch(self.url, self.pos, last).body
                self.block = (start, data)
            piece = data[self.pos - start : end - start]
            out += piece
            self.pos += len(piece)
        return bytes(out)

    def readinto(self, buffer):
        data = self.read(len(buffer))
        buffer[: len(data)] = data
        return len(data)


def find_member(names: list[str], wanted: str) -> str:
    if wanted in names:
        return wanted
    matches = [n for n in names if n.lower() == wanted.lower()]
    if len(matches) != 1:
        raise AccessRefused(f"member {wanted!r} matches {len(matches)} entries in the archive")
    return matches[0]


def capture_zip_member(zip_url, member, *, source, raw_root, state_path, basis_path, date=None,
                       user_agent=USER_AGENT, cap=DEFAULT_CAP, clock=time.time, sleep=time.sleep,
                       range_chunk=RANGE_CHUNK) -> dict:
    """Extract ONE member of a remote ZIP via Range reads; return its manifest row."""
    raw_root = Path(raw_root)
    fetcher, day = start(source, raw_root, state_path, basis_path, date, user_agent, clock, sleep)
    for row in manifest_rows(raw_root, source):
        if row.get("zip_url") == zip_url and row.get("member", "").lower() == member.lower():
            return row
    fetcher.ensure_not_stopped()
    check_budget(fetcher.state_path, cap)
    reader = RangeReader(fetcher, zip_url, range_chunk)
    with zipfile.ZipFile(reader) as archive:
        exact = find_member(archive.namelist(), member)
        info = archive.getinfo(exact)
        data = archive.read(info)  # zipfile verifies the CRC and raises BadZipFile on mismatch
    return finish(
        fetcher, raw_root=raw_root, day=day, name=safe_filename(Path(exact).name), data=data, cap=cap,
        now=clock(), access=reader.access,
        fields={"url": zip_url, "final_url": reader.url, "content_type": None, "status": 206,
                "etag": None, "last_modified": None, "zip_url": zip_url, "zip_bytes": reader.length,
                "zip_etag": reader.etag, "zip_last_modified": reader.last_modified, "member": exact,
                "member_crc32": f"{info.CRC:08x}", "range_requests": reader.requests},
    )


# --- CLI ----------------------------------------------------------------------------


def resolve_under_staging(path: str, label: str) -> Path:
    resolved, root = Path(path).resolve(), STAGING_ROOT.resolve()
    if not resolved.is_relative_to(root):
        raise AccessRefused(f"{label} {resolved} must resolve under {root}")
    return resolved


def resolve_raw_root(path: str) -> Path:
    resolved = Path(path).resolve()
    if resolved.name != "raw" or resolved.parent.name != "data":
        raise AccessRefused(f"--raw-root {resolved} must resolve to a directory named data/raw")
    return resolved


def main(argv: list[str] | None = None, *, clock=time.time, sleep=time.sleep) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--source", required=True)
    parser.add_argument("--raw-root", required=True)
    parser.add_argument("--state", required=True)
    parser.add_argument("--basis", required=True)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--url")
    target.add_argument("--zip-url")
    parser.add_argument("--member")
    parser.add_argument("--cap", type=int, default=DEFAULT_CAP)
    args = parser.parse_args(argv)
    if bool(args.zip_url) != bool(args.member):
        parser.error("--zip-url and --member go together")
    try:
        common = dict(source=args.source, raw_root=resolve_raw_root(args.raw_root),
                      state_path=resolve_under_staging(args.state, "--state"),
                      basis_path=resolve_under_staging(args.basis, "--basis"), cap=args.cap,
                      clock=clock, sleep=sleep)
        row = capture(args.url, **common) if args.url else capture_zip_member(args.zip_url, args.member, **common)
    except AccessRefused as err:
        print(f"refused: {type(err).__name__}: {err}", file=sys.stderr)
        return 2
    print(json.dumps(row, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
