#!/usr/bin/env python3
"""Polite, auditable capture of single public documents for a case study (CF6).

Why this exists: a case file must show, for every document it rests on, that we
were allowed to fetch it and exactly what we fetched. So every capture is gated
by an operator-written host basis (explicit "allowed" + terms/licence text),
robots.txt, a 1 s global throttle, a per-run document budget and a
stopped-source latch, and every document lands with a manifest row recording the
bytes' sha256 and the access decision that permitted it.

Design notes:
  * One capture call holds an exclusive lock on the state file from start to
    finish, so invocations are fully serialised: dispatch, throttle, cooldown,
    dedupe and budget cannot race.
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
import mimetypes
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
import zlib
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.message import Message
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit
from urllib.robotparser import RobotFileParser

STAGING_ROOT = Path.home() / "open-marin-staging" / "cf6-case"
RAW_ROOT = Path.home() / "projects" / "marin-civic-graph" / "data" / "raw"  # main checkout only
USER_AGENT = "OpenMarinCaseCapture/1.0 (public-records research; polite single-document fetches)"
MAX_CAP = DEFAULT_CAP = 60
MIN_INTERVAL = 1.0  # seconds between ANY two requests
MAX_RETRY_WAIT = 120.0  # longest Retry-After we are willing to sit out
MAX_HOPS = 5
RANGE_CHUNK = 512 * 1024  # read-ahead for ZIP member reads
MAX_BODY = 256 * 1024 * 1024
PEEK_BYTES = 64 * 1024  # how much of an unexpected reply we look at for a challenge page
TIMEOUT = 30
REQUIRED_BASIS = ("decision", "basis", "licence", "attribution")
RESERVED_NAMES = {"manifest.jsonl"}
UNZIP = "/usr/bin/unzip"
EXTERNAL_METHODS = {9}  # compression methods zipfile cannot read (9 = Deflate64, used by IRS TEOS zips)
UNZIP_TIMEOUT = 120

LOGIN_PATH_RE = re.compile(r"(?<![a-z0-9])(login|signin|sign-in|sso|auth|account)s?(?![a-z0-9])")
PASSWORD_INPUT_RE = re.compile(r"<input\b[^>]*\btype\s*=\s*[\"']?password", re.I)
HTML_START_RE = re.compile(r"<\s*(!doctype\s+html|html|head|body|form|script|input|div)\b", re.I)
CONTENT_RANGE_RE = re.compile(r"bytes (\d+)-(\d+)/(\d+)")
RESTRICTION_MARKERS = (
    "captcha", "g-recaptcha", "hcaptcha", "cf-challenge", "cf-turnstile", "subscribe to continue", "paywall",
)
INLINE_CODE_RE = re.compile(r"(<(script|style)\b[^>]*>).*?(</\2\s*>)|<!--.*?-->", re.I | re.S)
TITLE_RE = re.compile(r"<title\b[^>]*>(.*?)</title\s*>", re.I | re.S)
CHALLENGE_TITLES = ("just a moment", "attention required", "access denied", "security verification")
# Calls that put a challenge on screen; they count even inside a script, unlike a mere widget key there.
CHALLENGE_CODE = ("grecaptcha.render", "grecaptcha.execute", "grecaptcha.enterprise.render",
                  "grecaptcha.enterprise.execute", "hcaptcha.render", "hcaptcha.execute",
                  "turnstile.render", "_cf_chl_", "challenge-platform")
SOURCE_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class AccessRefused(Exception):
    """We may not (or cannot safely) make this request; nothing was written."""


class SourceRestricted(AccessRefused):
    """The source says no (robots, login, captcha, rate limit); further capture stops."""


class RangeViolation(AccessRefused):
    """The server's answer to a Range request broke the protocol."""


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
    hops: list = field(default_factory=list)


# --- state file ---------------------------------------------------------------------


def refuse_symlink(path: Path) -> None:
    if path.is_symlink():
        raise AccessRefused(f"{path} is a symlink")


def resolve_under_staging(path, label: str) -> Path:
    resolved, root = Path(path).resolve(), STAGING_ROOT.resolve()
    if not resolved.is_relative_to(root):
        raise AccessRefused(f"{label} {resolved} must resolve under {root}")
    return resolved


class State:
    """The JSON state file, exclusively locked for the lifetime of one capture call."""

    def __init__(self, path: Path):
        self.path = resolve_under_staging(path, "state file")
        lock_path = Path(f"{self.path}.lock")
        for candidate in (Path(path), self.path, lock_path):
            refuse_symlink(candidate)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = os.fdopen(os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600), "r+")
        fcntl.flock(self.lock, fcntl.LOCK_EX)
        self.data = json.loads(self.path.read_text()) if self.path.exists() else {}

    def save(self) -> None:
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.unlink(missing_ok=True)  # under the lock, so any leftover is stale (or a planted link)
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w") as handle:
            handle.write(json.dumps(self.data, indent=2, sort_keys=True))
        os.replace(tmp, self.path)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        try:
            self.save()
        finally:
            self.lock.close()  # releases the flock


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
    """Login, captcha or paywall page: any reply that is HTML by type or by content."""
    text = body[:500_000].decode("utf-8", "replace")
    if "html" not in (content_type or "").lower() and not HTML_START_RE.search(text[:2048]):
        return False
    # inline script/style bodies and comments (site-builder widget keys etc.) are not evidence of a challenge
    markup = INLINE_CODE_RE.sub(lambda m: f"{m[1]}{m[3]}" if m[1] else " ", text).lower()
    title = TITLE_RE.search(markup)
    return (bool(PASSWORD_INPUT_RE.search(text)) or any(m in markup for m in RESTRICTION_MARKERS)
            or any(c in re.sub(r"\s+", "", text.lower()) for c in CHALLENGE_CODE)
            or bool(title and any(t in title[1] for t in CHALLENGE_TITLES)))


def read_body(response, status: int, headers: Message, wanted: tuple[int, int] | None) -> bytes:
    """Read no more than the request permits; judge a Range reply before reading it."""
    if wanted is None:
        limit = MAX_BODY
    elif status == 206:
        match = CONTENT_RANGE_RE.fullmatch(headers.get("Content-Range", ""))
        if not match or int(match[1]) != wanted[0] or not wanted[0] <= int(match[2]) <= wanted[1]:
            raise RangeViolation(f"Content-Range {headers.get('Content-Range')!r} does not match bytes={wanted[0]}-{wanted[1]}")
        limit = int(match[2]) - wanted[0] + 1
    else:
        limit = PEEK_BYTES  # Range ignored or refused: just enough to spot a challenge page
    body = response.read(limit + 1)
    if wanted is not None and status == 206 and len(body) != limit:
        raise RangeViolation(f"206 body is {len(body)} bytes, Content-Range promised {limit}")
    if len(body) > limit and wanted is None:
        raise AccessRefused("reply is larger than the request permits")
    return body[:limit]


class Fetcher:
    """Every request this module makes goes through here."""

    def __init__(self, *, source, state: State, basis_path, user_agent, clock, sleep):
        if not SOURCE_RE.match(source):
            raise AccessRefused(f"source id {source!r} must match {SOURCE_RE.pattern}")
        self.source, self.state, self.data, self.user_agent = source, state, state.data, user_agent
        path = resolve_under_staging(basis_path, "basis file")
        self.hosts = json.loads(path.read_text()).get("hosts", {}) if path.exists() else {}
        self.clock, self.sleep = clock, sleep
        self.opener = urllib.request.build_opener(NoRedirects)
        self.robots_memo: dict[str, dict] = {}

    # state helpers
    def ensure_not_stopped(self) -> None:
        reason = self.data.get("stopped", {}).get(self.source)
        if reason:
            raise SourceRestricted(f"source {self.source!r} is stopped: {reason}")

    def stop(self, reason: str) -> SourceRestricted:
        self.data.setdefault("stopped", {})[self.source] = reason
        self.state.save()
        return SourceRestricted(f"source {self.source!r} stopped: {reason}")

    def throttle(self, netloc: str) -> None:
        last = self.data.setdefault("last_request", {})
        ready = max(last.get("*", 0.0), last.get(netloc, 0.0)) + MIN_INTERVAL
        ready = max(ready, self.data.get("cooldown", {}).get(netloc, 0.0))
        if ready > self.clock():
            self.sleep(ready - self.clock())
        last["*"] = last[netloc] = self.clock()
        self.state.save()

    def send(self, url: str, method: str, headers: dict) -> tuple[int | None, Message, bytes]:
        """One throttled request; HTTP errors are returned, not raised."""
        self.ensure_not_stopped()
        self.throttle(urlsplit(url).netloc.lower())
        wanted = None
        if "Range" in headers:
            first, _, last = headers["Range"].removeprefix("bytes=").partition("-")
            wanted = (int(first), int(last))
        request = urllib.request.Request(url, method=method, headers={"User-Agent": self.user_agent, **headers})
        try:
            with self.opener.open(request, timeout=TIMEOUT) as response:
                return response.status, response.headers, read_body(response, response.status, response.headers, wanted)
        except urllib.error.HTTPError as err:
            with err:
                return err.code, err.headers, read_body(err, err.code, err.headers, wanted)
        except RangeViolation as err:
            raise self.stop(str(err))
        except (urllib.error.URLError, OSError):
            return None, Message(), b""

    def request_checked(self, url: str, method: str, headers: dict) -> tuple[int | None, Message, bytes]:
        """send() plus the rules every reply (documents and robots alike) must pass."""
        netloc = urlsplit(url).netloc.lower()
        for attempt in (0, 1):
            status, response_headers, body = self.send(url, method, headers)
            if status in (429, 503):
                wait = parse_retry_after(response_headers.get("Retry-After"), self.clock())
                if attempt or wait is None or wait > MAX_RETRY_WAIT:
                    raise self.stop(f"HTTP {status} from {netloc} (Retry-After {response_headers.get('Retry-After')})")
                self.data.setdefault("cooldown", {})[netloc] = self.clock() + wait
                self.state.save()
                continue
            break
        if status in (401, 403):
            raise self.stop(f"HTTP {status} from {netloc}")
        if status is not None and 200 <= status < 300 and looks_restricted(body, response_headers.get("Content-Type")):
            raise self.stop(f"login, captcha or paywall page at {url}")
        return status, response_headers, body

    # policy checks
    def host_entry(self, netloc: str) -> dict:
        entry = self.hosts.get(netloc)
        if not entry or entry.get("decision") != "allowed":
            raise AccessRefused(f"host {netloc!r} has no affirmative 'allowed' decision in the basis file")
        missing = [k for k in REQUIRED_BASIS if not str(entry.get(k) or "").strip()] + \
                  (["terms_url"] if "terms_url" not in entry else [])
        if missing:
            raise AccessRefused(f"basis entry for {netloc!r} lacks {', '.join(missing)}")
        return entry

    def refuse_login_path(self, url: str) -> None:
        path = unquote(urlsplit(url).path).lower()
        if LOGIN_PATH_RE.search(path):
            raise self.stop(f"login-like path: {path}")

    def robots_for(self, url: str) -> dict:
        parts = urlsplit(url)
        key = f"{parts.scheme}://{parts.netloc.lower()}"
        if key in self.robots_memo:
            return self.robots_memo[key]
        cached = self.data.get("robots", {}).get(key)
        if cached is None:
            robots_url = f"{key}/robots.txt"
            status, _, body = self.request_checked(robots_url, "GET", {})
            ok = status is not None and 200 <= status < 300
            cached = {"url": robots_url, "status": status,
                      "sha256": hashlib.sha256(body).hexdigest() if ok else None,
                      "body": body.decode("utf-8", "replace") if ok else ""}
            if ok or status in (404, 410):  # outages and odd statuses are never cached
                self.data.setdefault("robots", {})[key] = cached
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
                raise self.stop(f"robots.txt disallows {url}")
        elif status not in (404, 410):  # absent robots.txt allows everything; anything else is an outage
            basis = entry.get("robots_unavailable_basis")
            if not basis:
                raise AccessRefused(f"robots.txt unavailable (status {status}) and the host has no robots_unavailable_basis")
            access["robots_unavailable_basis"] = basis
        return access

    def get(self, url: str, *, headers=None) -> Response:
        """Fetch `url`, walking redirects hop by hop through every check."""
        hops = []
        for _ in range(MAX_HOPS + 1):
            parts = urlsplit(url)
            if parts.scheme not in ("http", "https"):
                raise AccessRefused(f"unsupported URL scheme in {url!r}")
            self.ensure_not_stopped()
            self.refuse_login_path(url)
            entry = self.host_entry(parts.netloc.lower())
            access = {**self.check_robots(url, entry), "user_agent": self.user_agent,
                      **{k: entry.get(k) for k in (*REQUIRED_BASIS, "terms_url")}}
            status, response_headers, body = self.request_checked(url, "GET", headers or {})
            hops.append({"url": url, "status": status, "access": access})
            if status is not None and 300 <= status < 400:
                location = response_headers.get("Location")
                if not location:
                    raise AccessRefused(f"HTTP {status} without Location from {url}")
                url = urljoin(url, location)
                continue
            if status is None or not 200 <= status < 300:
                raise AccessRefused(f"HTTP {status} from {url}")
            return Response(status, response_headers, body, url, access, hops)
        raise AccessRefused(f"more than {MAX_HOPS} redirects")


# --- manifest and files -------------------------------------------------------------


def manifest_rows(raw_root: Path, source: str):
    for manifest in sorted((raw_root / source).glob("*/manifest.jsonl")):
        refuse_symlink(manifest)
        for line in manifest.read_text().splitlines():
            if line.strip():
                yield json.loads(line)


def safe_filename(name: str) -> str:
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).lstrip("._")[-120:] or "index"
    return f"doc_{name}" if name.lower() in RESERVED_NAMES else name


def output_folder(raw_root: Path, source: str, day: str) -> Path:
    folder = raw_root / source / day
    for part in (raw_root / source, folder):
        refuse_symlink(part)
    folder.mkdir(parents=True, exist_ok=True)
    if not folder.resolve().is_relative_to(raw_root.resolve()):
        raise AccessRefused(f"{folder} escapes {raw_root}")
    return folder


def write_document(folder: Path, name: str, data: bytes) -> Path:
    stem, dot, suffix = name.rpartition(".") if "." in name else (name, "", "")
    for n in range(10_000):
        candidate = folder / (name if n == 0 else f"{stem}-{n}{dot}{suffix}")
        try:
            with open(candidate, "xb") as handle:  # O_EXCL: never follows or overwrites
                handle.write(data)
            return candidate
        except FileExistsError:
            continue
    raise AccessRefused(f"could not find a free filename for {name!r}")


def finish(fetcher: Fetcher, *, raw_root, day, name, data, now, cap, fields) -> dict:
    """Write the document and its manifest row, then count it; return the row."""
    folder = output_folder(raw_root, fetcher.source, day)
    manifest = folder / "manifest.jsonl"
    refuse_symlink(manifest)
    written = write_document(folder, name, data)
    row = {
        "retrieved_at": datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
        "path": written.relative_to(raw_root).as_posix(),
        **fields,
    }
    with open(manifest, "a") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")
    fetcher.data["documents"] = fetcher.data.get("documents", 0) + 1
    return row


def begin(state: State, *, source, raw_root, basis_path, date, user_agent, clock, sleep, cap):
    """Validate the call's inputs; return (fetcher, pinned raw root, date string)."""
    if not 1 <= cap <= MAX_CAP:
        raise AccessRefused(f"cap must be between 1 and {MAX_CAP}")
    raw_root = Path(raw_root)
    if raw_root.resolve() != RAW_ROOT.resolve():
        raise AccessRefused(f"raw root {raw_root.resolve()} is not the pinned {RAW_ROOT}")
    fetcher = Fetcher(source=source, state=state, basis_path=basis_path, user_agent=user_agent,
                      clock=clock, sleep=sleep)
    refuse_symlink(raw_root / source)
    day = str(date) if date else datetime.fromtimestamp(clock(), timezone.utc).strftime("%Y-%m-%d")
    if not DATE_RE.match(day):
        raise AccessRefused(f"date {day!r} must be YYYY-MM-DD")
    raw_root = raw_root.resolve()
    reconcile_document_count(fetcher, raw_root)
    return fetcher, raw_root, day


def reconcile_document_count(fetcher: Fetcher, raw_root: Path) -> None:
    """The manifests are the truth: a crash between manifest append and state save must not undercount."""
    written = sum("access" in row for manifest in raw_root.glob("*/*/manifest.jsonl")
                  for row in map(json.loads, filter(str.strip, manifest.read_text().splitlines())))
    fetcher.data["documents"] = max(fetcher.data.get("documents", 0), written)


def find_row(raw_root: Path, source: str, matches) -> dict | None:
    return next((row for row in manifest_rows(raw_root, source) if matches(row)), None)


def check_budget(fetcher: Fetcher, cap: int) -> None:
    if fetcher.data.get("documents", 0) >= cap:
        raise BudgetExhausted(f"document budget of {cap} is used up")


# --- public API ---------------------------------------------------------------------


def capture(url, *, source, raw_root, state_path, basis_path, date=None, user_agent=USER_AGENT,
            cap=DEFAULT_CAP, clock=time.time, sleep=time.sleep) -> dict:
    """Fetch one document once; return its manifest row."""
    with State(state_path) as state:
        fetcher, raw_root, day = begin(state, source=source, raw_root=raw_root, basis_path=basis_path,
                                       date=date, user_agent=user_agent, clock=clock, sleep=sleep, cap=cap)
        existing = find_row(raw_root, source, lambda r: r["url"] == url and "member" not in r)
        if existing:
            return existing
        fetcher.ensure_not_stopped()
        check_budget(fetcher, cap)
        response = fetcher.get(url)
        content_type = response.headers.get_content_type() if response.headers.get("Content-Type") else None
        return finish(
            fetcher, raw_root=raw_root, day=day, data=response.body, now=clock(), cap=cap,
            name=safe_filename(unquote(urlsplit(response.final_url).path.rpartition("/")[2])),
            fields={"url": url, "final_url": response.final_url, "content_type": content_type,
                    "status": response.status, "etag": response.headers.get("ETag"),
                    "last_modified": response.headers.get("Last-Modified"),
                    "access": response.access, "hops": response.hops},
        )


class RangeReader(io.RawIOBase):
    """Seekable read-only view of a remote file, fetched with throttled Range requests."""

    def __init__(self, fetcher: Fetcher, url: str, chunk: int = RANGE_CHUNK):
        self.fetcher, self.chunk = fetcher, chunk
        self.requests, self.pos, self.block = 0, 0, (0, b"")
        probe = self.fetch(url, 0, 0)
        self.url, self.length = probe.final_url, int(CONTENT_RANGE_RE.fullmatch(probe.headers["Content-Range"])[3])
        self.etag, self.last_modified = probe.headers.get("ETag"), probe.headers.get("Last-Modified")
        self.content_type = probe.headers.get("Content-Type")
        self.access, self.hops = probe.access, probe.hops

    def fetch(self, url: str, first: int, last: int) -> Response:
        response = self.fetcher.get(url, headers={"Range": f"bytes={first}-{last}"})
        self.requests += 1
        if response.status != 206:
            raise self.fetcher.stop(f"server did not honour Range bytes={first}-{last} (status {response.status})")
        if hasattr(self, "length") and (int(CONTENT_RANGE_RE.fullmatch(response.headers["Content-Range"])[3]) != self.length
                                        or response.headers.get("ETag") != self.etag):
            raise self.fetcher.stop("remote file changed while it was being read")
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
                if not data:
                    raise self.fetcher.stop("Range reply made no progress")
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
    """Exact name if exactly one entry has it, else a unique case-insensitive match, else a unique entry whose
    file name (the part after any folder) is the wanted name — IRS batches keep members in a folder."""
    base = wanted.rsplit("/", 1)[-1]
    matches = ([n for n in names if n == wanted] or [n for n in names if n.lower() == wanted.lower()]
               or ([n for n in names if n.rsplit("/", 1)[-1] == base] if "/" not in wanted else []))
    if len(matches) != 1:
        raise AccessRefused(f"member {wanted!r} matches {len(matches)} entries in the archive")
    return matches[0]


def extract_external(reader: RangeReader, info: zipfile.ZipInfo) -> bytes:
    """Decompress one member with unzip: rebuild a single-entry zip from its raw bytes (read via `reader`)."""
    if info.flag_bits & 0x1 or max(info.compress_size, info.file_size) > 0xFFFFFFFF:
        raise AccessRefused("encrypted or ZIP64-sized members cannot use the external decompressor")
    reader.seek(info.header_offset)
    local = reader.read(30)
    if local[:4] != b"PK\x03\x04":
        raise zipfile.BadZipFile("bad local file header")
    name_len, extra_len = struct.unpack("<HH", local[26:30])
    reader.seek(info.header_offset + 30 + name_len + extra_len)
    raw = reader.read(info.compress_size)
    name = b"member"  # neutral entry name: no glob characters for unzip to interpret
    year, month, day, hour, minute, second = info.date_time
    dos_time, dos_date = hour << 11 | minute << 5 | second // 2, (year - 1980) << 9 | month << 5 | day
    fields = (20, 0, info.compress_type, dos_time, dos_date, info.CRC,
              info.compress_size, info.file_size, len(name))
    local_header = b"PK\x03\x04" + struct.pack("<HHHHHIIIHH", fields[0], *fields[1:], 0) + name
    central = b"PK\x01\x02" + struct.pack("<HHHHHHIIIHHHHHII", 20, 20, 0, *fields[2:5], fields[5], fields[6],
                                            fields[7], fields[8], 0, 0, 0, 0, 0, 0) + name
    end = b"PK\x05\x06" + struct.pack("<HHHHIIH", 0, 0, 1, 1, len(central), len(local_header) + len(raw), 0)
    folder = tempfile.mkdtemp(prefix="capture-unzip-")
    try:
        archive = Path(folder) / "entry.zip"
        archive.write_bytes(local_header + raw + central + end)
        try:
            data = subprocess.run([UNZIP, "-p", str(archive), "member"], capture_output=True,
                                  timeout=UNZIP_TIMEOUT, check=True).stdout
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as err:
            raise zipfile.BadZipFile(f"external decompression failed: {err}") from err
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    if len(data) != info.file_size or zlib.crc32(data) != info.CRC:
        raise zipfile.BadZipFile("external decompression gave the wrong size or CRC")
    return data


def capture_zip_member(zip_url, member, *, source, raw_root, state_path, basis_path, date=None,
                       user_agent=USER_AGENT, cap=DEFAULT_CAP, clock=time.time, sleep=time.sleep,
                       range_chunk=RANGE_CHUNK) -> dict:
    """Extract ONE member of a remote ZIP via Range reads; return its manifest row."""
    with State(state_path) as state:
        fetcher, raw_root, day = begin(state, source=source, raw_root=raw_root, basis_path=basis_path,
                                       date=date, user_agent=user_agent, clock=clock, sleep=sleep, cap=cap)

        def same_member(name):
            return lambda r: r.get("zip_url") == zip_url and r.get("member") == name

        existing = find_row(raw_root, source, same_member(member))
        if existing:
            return existing
        fetcher.ensure_not_stopped()
        check_budget(fetcher, cap)
        reader = RangeReader(fetcher, zip_url, range_chunk)
        with zipfile.ZipFile(reader) as archive:
            exact = find_member(archive.namelist(), member)
            existing = find_row(raw_root, source, same_member(exact))
            if existing:
                return existing
            info = archive.getinfo(exact)
            external = info.compress_type in EXTERNAL_METHODS
            # zipfile verifies the CRC itself and raises BadZipFile on mismatch
            data = extract_external(reader, info) if external else archive.read(info)
        return finish(
            fetcher, raw_root=raw_root, day=day, name=safe_filename(Path(exact).name), data=data, cap=cap,
            now=clock(),
            fields={"url": zip_url, "final_url": reader.url,
                    "content_type": mimetypes.guess_type(exact)[0] or "application/octet-stream",
                    "status": 206, "etag": None, "last_modified": None, "zip_url": zip_url,
                    "zip_bytes": reader.length, "zip_etag": reader.etag,
                    "zip_last_modified": reader.last_modified, "zip_content_type": reader.content_type,
                    "member": exact, "member_crc32": f"{info.CRC:08x}",
                    "member_compress_type": info.compress_type,
                    "decompressor": "unzip" if external else "zipfile", "range_requests": reader.requests,
                    "access": reader.access, "hops": reader.hops},
        )


# --- CLI ----------------------------------------------------------------------------


def clear_stop(state_path, source: str, reason: str, clock=time.time) -> dict:
    """Lift a source's stop, leaving an audit entry in the state file."""
    if not reason.strip():
        raise AccessRefused("clearing a stop needs a non-empty reason")
    with State(state_path) as state:
        previous = state.data.get("stopped", {}).pop(source, None)
        if previous is None:
            raise AccessRefused(f"source {source!r} is not stopped")
        entry = {"source": source, "reason": reason.strip(), "previous_stop": previous,
                 "cleared_at": datetime.fromtimestamp(clock(), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
        state.data.setdefault("clearances", []).append(entry)
    return entry


def main(argv: list[str] | None = None, *, clock=time.time, sleep=time.sleep) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--state", required=True)
    parser.add_argument("--source")
    parser.add_argument("--raw-root")
    parser.add_argument("--basis")
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--url")
    target.add_argument("--zip-url")
    target.add_argument("--clear-stop", metavar="SOURCE", help="lift SOURCE's stop (audited; needs --reason)")
    parser.add_argument("--member")
    parser.add_argument("--reason")
    parser.add_argument("--cap", type=int, default=DEFAULT_CAP)
    args = parser.parse_args(argv)
    if args.clear_stop:
        if args.reason is None or any((args.source, args.raw_root, args.basis, args.member)):
            parser.error("--clear-stop takes only --state and --reason")
    elif not (args.source and args.raw_root and args.basis and (args.url or args.zip_url)):
        parser.error("capture needs --source, --raw-root, --basis and --url or --zip-url")
    elif bool(args.zip_url) != bool(args.member):
        parser.error("--zip-url and --member go together")
    try:
        state_path = resolve_under_staging(args.state, "--state")
        if args.clear_stop:
            row = clear_stop(state_path, args.clear_stop, args.reason, clock)
        else:
            common = dict(source=args.source, raw_root=Path(args.raw_root), state_path=state_path,
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
