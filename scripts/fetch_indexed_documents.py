#!/usr/bin/env python3
"""Minutes coverage: freeze the candidate inventory, then fetch the uncached minutes it lists, one source at a time.

    python scripts/fetch_indexed_documents.py inventory                 # once: the frozen candidate set (+ sha256)
    python scripts/fetch_indexed_documents.py probe --source <id>       # at most 3 documents; prints each chain
    python scripts/fetch_indexed_documents.py bulk --source <id> [--limit N]
    python scripts/fetch_indexed_documents.py states                    # every candidate's state, per source

The inventory (read-only on the substrate) is every Meeting with a minutes Record: its source (minutes_sources,
never a guess), its real body, its date and its `preferred_public_url`. A Record without a URL is `no-url` and is
never fetched or guessed. Every later count reconciles to this file; a changed file (sha256) is refused.

Every request goes through minutes_transport (one agent, pacing, allow-lists, robots, stops). This module adds:
  - only inventory URLs, only for their own source, newest first; a file already on disk is never refetched or
    overwritten; one URL under several meetings is requested once and the bytes are filed under each;
  - redirects are observed, not followed blindly: a hop is requested only if its source admits it, otherwise the
    target is logged in the ledger and NOT requested;
  - only real documents are filed (PDF, HTML, DOCX), as <raw>/<source>/minutes/<meeting_id>.<ext>;
  - the attempted-URL ledger, <raw>/<source>/minutes-fetch-log.jsonl: one line per attempt, ending the candidate in
    `fetched`, `failed` (with its reason; never retried in this goal) or `excluded-by-authorization`;
  - each attempt is journaled (`attempting`) before its first request; an attempt that never reached an outcome
    (the process died) becomes `failed` on the next run and is never retried; a URL that failed, initial or
    redirect hop, is never requested again for any candidate;
  - a stop (403, 429, a challenge or login page) ends the run; a stopped host family is never asked again;
  - the probe takes at most 3 documents per source over all runs, and bulk refuses a source with no probe;
  - live runs only against the canonical raw store the inventory was frozen against; the inventory is written
    once, exclusively, and never replaced;
  - all state is read under one lock (never two fetch processes at once), and the weekly job window
    (Mondays 05:00–07:00 local) is checked before every request.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
import sqlite3
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))

from minutes_bodies import normalize_body  # noqa: E402
from minutes_sources import MINUTES_EXTENSIONS, SOURCE_MAP, host_family, off_limits, source_of  # noqa: E402
from minutes_sources import UnsafeUrl, canonical_url  # noqa: E402
from minutes_transport import NetworkError, Refused, StopNow, Transport, https_upgrade  # noqa: E402
from votes_inventory import normalize_url, sniff_format  # noqa: E402

HOME = Path.home()
DEFAULT_SUBSTRATE = HOME / "projects/marin-civic-graph/data/exports/public-substrate.sqlite"
DEFAULT_RAW = HOME / "projects/marin-civic-graph/data/raw"
STAGING = HOME / "open-marin-staging/minutes-coverage"
INVENTORY = "inventory.json"
BASELINE = "cached-baseline.json"
FETCH_LOG = "minutes-fetch-log.jsonl"
LOCK = "minutes-fetch.lock"
PROBE_MAX = 3
MAX_HOPS = 5
STATES = ("already-cached", "fetched", "failed", "excluded-by-authorization", "no-url", "unattempted-after-stop")
TERMINAL = ("fetched", "failed", "excluded-by-authorization")
OLE2_MAGIC = bytes.fromhex("d0cf11e0a1b11ae1")


def _document_kind(body: bytes) -> str | None:
    """pdf | html | docx | doc (a legacy Word file, converted later by textutil) | None."""
    return sniff_format(body) or ("doc" if is_word_doc(body) else None)


def is_word_doc(body: bytes) -> bool:
    """A structurally valid OLE2 compound file holding a Word `WordDocument` stream: the signature, the byte-order
    mark, a version-3 (512-byte) or version-4 (4096-byte) sector size, the stream's directory entry, and its FAT
    allocation chain walked end to end — every sector inside the file, no loops, enough sectors for the declared
    length — with the Word FIB identifier (0xA5EC; 0xA5DC for Word 6/95) at the stream's first byte."""
    import struct
    end_of_chain, free = 0xFFFFFFFE, 0xFFFFFFFF
    if len(body) < 512 or body[:8] != OLE2_MAGIC:
        return False
    major, order, shift = struct.unpack_from("<HHH", body, 26)
    if order != 0xFFFE or (major, shift) not in ((3, 9), (4, 12)):
        return False
    size = 1 << shift
    base = max(512, size)
    n_sectors = (len(body) - base) // size

    def sector(i: int) -> bytes | None:
        return body[base + i * size: base + (i + 1) * size] if 0 <= i < n_sectors else None

    # the FAT: its sectors are listed in the header's 109 DIFAT slots (larger files chain more DIFAT sectors)
    n_fat, first_difat = struct.unpack_from("<I", body, 44)[0], struct.unpack_from("<I", body, 68)[0]
    fat_sectors = [v for v in struct.unpack_from("<109I", body, 76) if v not in (free, end_of_chain)]
    seen_difat = set()
    while first_difat not in (free, end_of_chain) and len(fat_sectors) < n_fat:
        block = sector(first_difat)
        if block is None or first_difat in seen_difat:
            return False
        seen_difat.add(first_difat)
        vals = struct.unpack_from(f"<{size // 4}I", block)
        fat_sectors += [v for v in vals[:-1] if v not in (free, end_of_chain)]
        first_difat = vals[-1]
    fat: list[int] = []
    for i in fat_sectors[:n_fat]:
        block = sector(i)
        if block is None:
            return False
        fat += struct.unpack_from(f"<{size // 4}I", block)

    def chain(start: int, limit: int) -> list[int] | None:
        out, cur = [], start
        while cur != end_of_chain:
            if cur >= len(fat) or sector(cur) is None or cur in out or len(out) > limit:
                return None
            out.append(cur)
            cur = fat[cur]
        return out

    directory = chain(struct.unpack_from("<I", body, 48)[0], n_sectors)
    if not directory:
        return False
    for d in directory:
        block = sector(d)
        for off in range(0, size, 128):
            name_len, kind = struct.unpack_from("<HB", block, off + 64)
            if kind != 2 or not 2 <= name_len <= 64:
                continue
            if block[off:off + name_len - 2].decode("utf-16-le", "replace") != "WordDocument":
                continue
            start, length = struct.unpack_from("<II", block, off + 116)  # v3 keeps a 32-bit size
            if major == 4:
                length = struct.unpack_from("<Q", block, off + 120)[0]
            if length < 4096:  # a real Word stream is never a mini stream
                return False
            sectors = chain(start, n_sectors)
            return bool(sectors) and len(sectors) * size >= length and sector(sectors[0])[:2] in (b"\xec\xa5",
                                                                                              b"\xdc\xa5")
    return False


def _resolve_redirect(src, target: str) -> tuple[str, dict]:
    """The URL a redirect leads to for this source: an http:// target upgraded to https only if the upgrade is
    admitted; a listed viewer wrapper replaced by the document it wraps, only if that is admitted. Never a request."""
    note: dict = {}
    upgraded = https_upgrade(target)
    if upgraded != target and src.admits(upgraded):
        note["upgraded"] = upgraded
        target = upgraded
    for prefix, _evidence in src.viewer_wrappers:
        if target.startswith(prefix):
            inner = parse_qs(urlsplit(target).query).get("url", [])
            if len(inner) == 1:
                try:
                    canonical_url(inner[0])
                except UnsafeUrl:
                    break
                if src.admits(inner[0]) and not off_limits(urlsplit(inner[0]).hostname or ""):
                    note["unwrapped"] = inner[0]
                    target = inner[0]
            break
    return target, note


def probe_completed(ledger: list[dict]) -> bool:
    """A probe that requested a document and reached an outcome (not one interrupted mid-way)."""
    return any(e.get("mode") == "probe" and e.get("state") in TERMINAL and e.get("chain")
               and not e.get("interrupted_urls") for e in ledger)


def probe_slots_used(ledger: list[dict]) -> int:
    """Probe attempts that used a slot: every probe attempt (its `attempting` line is written before any request)
    except one that ended excluded by authorization before any document request (an empty chain)."""
    attempted = {e["meeting_id"] for e in ledger if e.get("mode") == "probe" and e.get("state") == "attempting"}
    no_document = {e["meeting_id"] for e in ledger if e.get("mode") == "probe"
                   and e.get("state") == "excluded-by-authorization" and not e.get("chain")}
    return len(attempted - no_document)


class FetchError(Exception):
    pass


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(Path(path).read_bytes())


def _cached(raw: Path, source: str, meeting_id: str) -> str | None:
    d = Path(raw) / SOURCE_MAP[source].raw_dir / "minutes"
    return next((f"{meeting_id}.{ext}" for ext in MINUTES_EXTENSIONS if (d / f"{meeting_id}.{ext}").exists()), None)


# --- the inventory ------------------------------------------------------------------------------------------------

def freeze_inventory(substrate: Path, raw: Path, out_dir: Path) -> Path:
    """Write <out_dir>/inventory.json and its .sha256; returns the inventory path."""
    db = sqlite3.connect(f"file:{Path(substrate)}?mode=ro", uri=True)
    try:
        rows = db.execute(
            "SELECT m.id, m.props, r.id, r.props FROM edges e JOIN nodes m ON m.id = e.source AND m.type = 'Meeting' "
            "JOIN nodes r ON r.id = e.target WHERE e.rel = 'EVIDENCED_BY' "
            "AND json_extract(r.props, '$.record_type') = 'meeting_minutes' ORDER BY m.id, r.id").fetchall()
        inst = dict(db.execute("SELECT source, target FROM edges WHERE rel = 'AT_INSTITUTION'").fetchall())
        as_of = (db.execute("SELECT value FROM meta WHERE key = 'as_of_date'").fetchone() or [""])[0]
    finally:
        db.close()
    candidates, unassigned, seen = [], set(), set()
    for mid, mprops, rid, rprops in rows:
        source = source_of(mid)
        if source is None:
            unassigned.add(mid)
            continue
        if mid in seen:
            raise FetchError(f"{mid} has several minutes Records; the inventory holds one document per meeting")
        seen.add(mid)
        m, r = json.loads(mprops), json.loads(rprops)
        body, known = normalize_body(source, m.get("title") or "")
        candidates.append({
            "meeting_id": mid, "source": source, "body": body, "body_known": known,
            "meeting_date": m.get("meeting_date") or "", "title": m.get("title") or "",
            "institution": inst.get(mid), "record_id": rid, "url": normalize_url(r.get("preferred_public_url")) or None,
            "cached": _cached(raw, source, mid)})
    candidates.sort(key=lambda c: (c["source"], c["meeting_id"]))
    counts = {}
    for s in SOURCE_MAP:
        cs = [c for c in candidates if c["source"] == s]
        counts[s] = {"candidates": len(cs), "no-url": sum(not c["url"] for c in cs),
                     "cached": sum(bool(c["url"] and c["cached"]) for c in cs),
                     "to-fetch": sum(bool(c["url"] and not c["cached"]) for c in cs)}
    doc = {"schema": "minutes-coverage-inventory-v1", "substrate": str(substrate),
           "substrate_sha256": sha256_file(substrate), "substrate_as_of_date": as_of, "raw": str(raw),
           "counts": counts, "unassigned": sorted(unassigned), "candidates": candidates}
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path, sha_path = out_dir / INVENTORY, out_dir / f"{INVENTORY}.sha256"
    data = (json.dumps(doc, indent=1, sort_keys=True) + "\n").encode("utf-8")
    _publish_frozen(path, data)
    return path


def _publish_frozen(path: Path, data: bytes) -> None:
    """Write `path` and `path.sha256` exclusively, each fsynced in full before it gets its name (os.link refuses an
    existing name). The data file is named first: a crash between the two leaves a file with no checksum, which
    load_frozen refuses — never a checksum vouching for a partial file."""
    sha_path = path.with_name(path.name + ".sha256")
    if path.exists() or sha_path.exists():
        raise FetchError(f"{path} (or its .sha256) exists: it is frozen and is never replaced")
    for target, content in ((path, data), (sha_path, f"{sha256_bytes(data)}  {path.name}\n".encode())):
        fd, tmp = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(content)
                fh.flush()
                os.fsync(fh.fileno())
            try:
                os.link(tmp, target)
            except FileExistsError:
                raise FetchError(f"{target} exists: it is frozen and is never replaced") from None
        finally:
            os.unlink(tmp)


def load_frozen(path: Path) -> dict:
    path = Path(path)
    sha_path = path.parent / f"{path.name}.sha256"
    if not sha_path.is_file():
        raise FetchError(f"{path} has no .sha256: an incomplete freeze, never trusted")
    want = (sha_path.read_text().split() or [""])[0]
    if sha256_file(path) != want:
        raise FetchError(f"{path} no longer matches its sha256 ({want}); it is frozen")
    return json.loads(path.read_text(encoding="utf-8"))


load_inventory = load_frozen


def freeze_baseline(inventory: Path, raw: Path) -> Path:
    """The sha256 of every file the inventory recorded as cached, frozen beside it (before any live request), so
    `candidate_states` can prove the baseline files are still the bytes they were."""
    inv = load_inventory(inventory)
    files = {}
    for c in inv["candidates"]:
        if c["cached"]:
            f = Path(raw) / SOURCE_MAP[c["source"]].raw_dir / "minutes" / c["cached"]
            files[c["meeting_id"]] = {"path": c["cached"], "sha256": sha256_file(f)}
    path = Path(inventory).with_name(BASELINE)
    doc = {"inventory_sha256": sha256_file(inventory), "files": dict(sorted(files.items()))}
    _publish_frozen(path, (json.dumps(doc, indent=1, sort_keys=True) + "\n").encode("utf-8"))
    return path


# --- the ledger -----------------------------------------------------------------------------------------------------

def read_ledger(raw: Path, source: str) -> list[dict]:
    """Every ledger line. A torn final line (a crash mid-append) is skipped; a torn line anywhere else is
    corruption and refuses."""
    path = Path(raw) / SOURCE_MAP[source].raw_dir / FETCH_LOG
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8", errors="replace").split("\n")
    out = []
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            if i == len(lines) - 1:  # the last line, with no newline after it: a torn append
                continue
            raise FetchError(f"{path} line {i + 1} is not JSON: the ledger is corrupt") from None
    return out


def _append(raw: Path, source: str, entry: dict) -> None:
    path = Path(raw) / SOURCE_MAP[source].raw_dir / FETCH_LOG
    path.parent.mkdir(parents=True, exist_ok=True)
    data = path.read_bytes() if path.is_file() else b""
    if data and not data.endswith(b"\n"):
        # a torn final append (a crash mid-write) was never a complete record: keep it for audit beside the
        # ledger, then cut it off so the ledger stays whole lines. Its meeting's last whole line still stands.
        cut = data.rfind(b"\n") + 1
        with path.with_name(path.name + ".torn").open("ab") as torn:
            torn.write(data[cut:] + b"\n")
        with path.open("r+b") as fh:
            fh.truncate(cut)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, sort_keys=True) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def _family_stops(transport: Transport, source: str) -> list[dict]:
    fams = {host_family(r.host) for r in SOURCE_MAP[source].rules}
    return [s for s in transport.stops() if s["host_family"] in fams]


def _last_by_meeting(ledger: list[dict]) -> dict[str, dict]:
    last: dict[str, dict] = {}
    for e in ledger:
        last[e["meeting_id"]] = e
    return last


# --- the fetch ------------------------------------------------------------------------------------------------------

@dataclass
class Result:
    attempted: int = 0
    fetched: int = 0
    stop: dict | None = None
    skipped: str | None = None
    remaining: int = 0  # eligible candidates left untouched because a --limit was reached
    entries: list[dict] = field(default_factory=list)


@contextlib.contextmanager
def run_lock(raw: Path):
    path = Path(raw) / LOCK
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = path.open("w")
    try:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise FetchError(f"another fetch holds {path}; never two fetch processes at once") from None
        yield
    finally:
        fh.close()


def in_weekly_window(t: dt.datetime) -> bool:
    return t.weekday() == 0 and 5 <= t.hour < 7


def seconds_until_window(t: dt.datetime) -> float:
    """Seconds from `t` (local, naive) to the next Monday 05:00."""
    start = (t - dt.timedelta(days=t.weekday())).replace(hour=5, minute=0, second=0, microsecond=0)
    if start <= t:
        start += dt.timedelta(days=7)
    return (start - t).total_seconds()


def _write_new(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.part")
    tmp.write_bytes(data)
    try:
        os.link(tmp, path)  # fails if the name exists: never overwrites
    finally:
        tmp.unlink()


def _now_iso() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def _fetch_one(transport: Transport, source: str, url: str, failed: dict[str, str],
               journal=lambda hop: None) -> tuple[str, str, dict]:
    """(state, reason, details) for one URL. Raises StopNow, or Refused('stopped' | 'window'), to end the run."""
    src = SOURCE_MAP[source]
    chain: list[dict] = []
    details = {"chain": chain, "final_url": url}
    if off_limits(urlsplit(url).hostname or "") or not src.admits_initial(url):
        return "excluded-by-authorization", f"initial URL is not on {source}'s allow-list (no request made)", details
    purpose = "document"
    for _ in range(MAX_HOPS + 1):
        details["final_url"] = url
        if url in failed:
            return "failed", f"{url} already failed in this goal ({failed[url]}); not retried", details
        try:
            resp = transport.get(url, src, purpose=purpose)
        except Refused as exc:
            if exc.kind in ("stopped", "window"):
                raise
            return "excluded-by-authorization", str(exc), details
        except NetworkError as exc:
            return "failed", f"request failed: {exc}", details
        hop = {"url": url, "status": resp.status, "location": resp.location}
        chain.append(hop)
        if resp.location:
            target, note = _resolve_redirect(src, resp.location)
            hop.update(note)
            if off_limits(urlsplit(target).hostname or "") or not src.admits(target):
                return "failed", f"redirect to {target} is not on {source}'s allow-list (logged, not requested)", \
                    details
            url, purpose = target, "redirect"
            if url not in failed:
                journal(url)  # durably, before the hop's request: a crash never forgets it
            continue
        if resp.status != 200:
            return "failed", f"HTTP {resp.status}", details
        kind = _document_kind(resp.body)
        if kind is None:
            return "failed", "response is not a PDF, HTML, DOCX or Word .doc document", details
        details |= {"data": resp.body, "kind": kind}
        return "fetched", "", details
    return "failed", f"more than {MAX_HOPS} redirects", details


def fetch_source(inventory: Path, source: str, raw: Path, *, mode: str = "bulk", limit: int | None = None,
                 transport: Transport | None = None, clock=dt.datetime.now, require_probe: bool = True) -> Result:
    if source not in SOURCE_MAP:
        raise FetchError(f"unknown source {source}")
    if mode not in ("probe", "bulk"):
        raise FetchError(f"unknown mode {mode}")
    raw = Path(raw)
    if transport is None and raw.resolve() != DEFAULT_RAW.resolve():
        raise FetchError(f"live fetches run only against the canonical raw store {DEFAULT_RAW}, not {raw}")
    with run_lock(raw):  # every piece of mutable state is read under the lock
        inv = load_inventory(inventory)
        if Path(inv["raw"]).resolve() != raw.resolve():
            raise FetchError(f"the inventory was frozen against raw store {inv['raw']}, not {raw}")
        if in_weekly_window(clock()):
            raise FetchError("refusing to run inside the weekly job window (Mondays 05:00–07:00 local)")
        transport = transport or Transport(raw)

        def guard() -> float:
            now = clock()
            if in_weekly_window(now):
                raise Refused("window", "the weekly job window (Mondays 05:00–07:00 local) has begun")
            return seconds_until_window(now)

        transport.guard = guard
        return _fetch_locked(inv, source, raw, mode, limit, transport, clock, require_probe)


def _fetch_locked(inv: dict, source: str, raw: Path, mode: str, limit: int | None, transport: Transport, clock,
                  require_probe: bool) -> Result:
    result = Result()
    minutes_dir = raw / SOURCE_MAP[source].raw_dir / "minutes"
    ledger = read_ledger(raw, source)
    # an attempt that never reached a terminal line (the process died mid-request) is failed, never retried, and
    # every URL it had started (the initial one and each journaled hop) is never requested again
    open_attempts: dict[str, list[dict]] = {}
    for e in ledger:
        if e.get("state") == "attempting":
            open_attempts.setdefault(e["meeting_id"], []).append(e)
        else:
            open_attempts.pop(e["meeting_id"], None)
    for mid, lines in sorted(open_attempts.items()):
        urls = [lines[0]["url"]] + [x["hop"] for x in lines if x.get("hop")]
        entry = {"meeting_id": mid, "url": lines[0]["url"], "mode": lines[0].get("mode"), "fetched_at": _now_iso(),
                 "state": "failed", "status": "failed", "chain": [], "final_url": urls[-1], "interrupted_urls": urls,
                 "requests": len(urls),
                 "reason": f"interrupted attempt (started {lines[0]['fetched_at']}; the process ended mid-request); "
                           "not retried"}
        _append(raw, source, entry)
        ledger.append(entry)
    if stops := _family_stops(transport, source):
        result.skipped = f"a stop record covers {', '.join(s['host_family'] for s in stops)}; no request made"
        return result
    last = _last_by_meeting(ledger)
    done = {m for m, e in last.items() if e.get("state") in TERMINAL}
    by_url = {e["url"]: e for e in ledger if e.get("state") == "fetched" and e.get("path")}
    failed: dict[str, str] = {}  # URL (initial or hop) → why it failed; never requested again in this goal
    excluded: dict[str, str] = {}  # initial URL → why authorization excluded it
    for e in ledger:
        if e.get("state") == "excluded-by-authorization":
            excluded.setdefault(e["url"], e["reason"])
        elif e.get("state") == "failed" and e.get("http_attempted", True):
            failed.setdefault(e["url"], e["reason"])
            for u in [e.get("final_url")] + list(e.get("interrupted_urls") or []):
                if u:
                    failed.setdefault(u, e["reason"])
    todo = sorted((c for c in inv["candidates"] if c["source"] == source and c["url"] and not c["cached"]
                   and c["meeting_id"] not in done), key=lambda c: (c["meeting_date"], c["meeting_id"]), reverse=True)
    # a probe slot is taken by its `attempting` line, written before the first request, so a crash still counts
    probes_used = probe_slots_used(ledger)
    if mode == "probe":
        cap = max(0, min(limit or PROBE_MAX, PROBE_MAX - probes_used))
    else:
        if require_probe and todo and not probe_completed(ledger):
            raise FetchError(f"{source}: no completed probe recorded; run `probe` and read its chains before `bulk`")
        cap = limit

    for i, c in enumerate(todo):
        if cap is not None and result.attempted >= cap:
            result.remaining = sum(1 for x in todo[i:] if not _cached(raw, source, x["meeting_id"]))
            break
        mid, url = c["meeting_id"], c["url"]
        base = {"meeting_id": mid, "url": url, "mode": mode, "fetched_at": _now_iso()}
        if on_disk := _cached(raw, source, mid):  # saved by hand since the freeze: never refetched or overwritten
            f = minutes_dir / on_disk
            saved = dt.datetime.fromtimestamp(f.stat().st_mtime, dt.UTC).isoformat(timespec="seconds")
            entry = base | {"state": "already-cached", "status": "cached", "path": on_disk, "fetched_at": saved,
                            "sha256": sha256_file(f), "chain": [], "provenance": "on disk since the freeze",
                            "reason": "on disk since the inventory froze (not fetched in this goal); dated by its "
                                      "file time"}
            _append(raw, source, entry)
            result.entries.append(entry)
            continue
        if url in by_url:  # the same document under another meeting: no request
            prior = by_url[url]
            src_file = minutes_dir / prior["path"]
            if not src_file.is_file() or sha256_file(src_file) != prior["sha256"]:
                entry = base | {"state": "failed", "status": "failed", "chain": [], "final_url": url,
                                "http_attempted": False,
                                "reason": f"same URL as {prior['meeting_id']}, whose file is missing or changed since "
                                          "it was fetched; not copied, not refetched"}
            else:
                data = src_file.read_bytes()
                name = f"{mid}.{prior['path'].rsplit('.', 1)[1]}"
                _write_new(minutes_dir / name, data)
                entry = base | {"state": "fetched", "status": "ok", "path": name, "sha256": sha256_bytes(data),
                                "final_url": prior.get("final_url"), "chain": [], "requests": 0,
                                "reason": f"same URL as {prior['meeting_id']}; bytes copied, no request"}
            _append(raw, source, entry)
            result.entries.append(entry)
            continue
        if url in failed or url in excluded:
            state = "failed" if url in failed else "excluded-by-authorization"
            entry = base | {"state": state, "status": "failed" if url in failed else "excluded", "chain": [],
                            "final_url": url, "http_attempted": False,
                            "reason": f"same URL as an earlier candidate: {failed.get(url) or excluded[url]} "
                                      "(not retried)"}
            _append(raw, source, entry)
            result.entries.append(entry)
            continue
        result.attempted += 1
        _append(raw, source, base | {"state": "attempting", "status": "attempting"})
        sent_before = transport.sent
        started = [(url, sent_before)]  # (URL, requests sent before it was journaled)

        def journal(hop: str, base=base, started=started) -> None:
            _append(raw, source, base | {"state": "attempting", "status": "attempting", "hop": hop})
            started.append((hop, transport.sent))
        try:
            state, reason, details = _fetch_one(transport, source, url, failed, journal)
        except (Refused, StopNow) as exc:
            sent = transport.sent - sent_before
            if isinstance(exc, StopNow):
                result.stop = exc.record
                reason = f"stop: {exc.record['evidence']}"
            else:
                result.skipped = str(exc)
                reason = f"interrupted ({exc.kind}: {exc}) after {sent} request(s); not retried"
            if sent or isinstance(exc, StopNow):
                # every URL this attempt actually requested (the initial one and each hop that went out) is never
                # requested again; a hop journaled but refused before its request stays eligible
                reached = [u for u, before in started if transport.sent > before]
                entry = base | {"state": "failed", "status": "failed", "reason": reason, "chain": [],
                                "final_url": exc.record["url"] if isinstance(exc, StopNow) else reached[-1],
                                "requests": sent, "interrupted_urls": list(reached)}
            else:  # nothing went out: the candidate is untouched and stays eligible
                entry = base | {"state": "abandoned", "status": "abandoned", "requests": 0,
                                "reason": f"no request made ({exc.kind}: {exc})"}
                result.attempted -= 1
            _append(raw, source, entry)
            result.entries.append(entry)
            break
        entry = base | {"state": state, "reason": reason, "chain": details["chain"],
                        "final_url": details["final_url"], "requests": transport.sent - sent_before}
        if state == "fetched":
            name = f"{mid}.{details['kind']}"
            _write_new(minutes_dir / name, details["data"])
            entry |= {"status": "ok", "http_status": 200, "path": name, "sha256": sha256_bytes(details["data"])}
            by_url[url] = entry
            result.fetched += 1
        else:
            entry["status"] = "failed" if state == "failed" else "excluded"
            if state == "excluded-by-authorization":
                excluded.setdefault(url, reason)
            elif entry["requests"]:
                failed.setdefault(url, reason)
                failed.setdefault(details["final_url"], reason)
            else:
                failed.setdefault(url, reason)
        _append(raw, source, entry)
        result.entries.append(entry)
    return result


# --- states ---------------------------------------------------------------------------------------------------------

def candidate_states(inventory: Path, raw: Path, transport: Transport | None = None) -> dict:
    """Every candidate's one state, reconciled with the files on disk. `pending` (no terminal state yet) is not a
    goal state: it must reach zero. `anomalies` (a ledger claim the disk contradicts) must be empty."""
    inv = load_inventory(inventory)
    try:
        baseline = load_frozen(Path(inventory).with_name(BASELINE))["files"]
    except FileNotFoundError:
        raise FetchError("no frozen cached baseline beside the inventory (run `baseline`)") from None
    transport = transport or Transport(raw)
    last: dict[str, dict] = {}
    for source in SOURCE_MAP:
        for e in read_ledger(raw, source):
            if e.get("state") in TERMINAL + ("already-cached",):
                last[e["meeting_id"]] = e
    out, counts, anomalies = {}, {}, []
    for c in inv["candidates"]:
        mid, source = c["meeting_id"], c["source"]
        if not c["url"]:
            state = "no-url"
        elif c["cached"]:
            state = "already-cached"
            b = baseline.get(mid)
            f = Path(raw) / SOURCE_MAP[source].raw_dir / "minutes" / c["cached"]
            if b is None:
                anomalies.append({"meeting_id": mid, "problem": "cached at the freeze but missing from the baseline"})
            elif not f.is_file():
                anomalies.append({"meeting_id": mid, "problem": f"baseline file {c['cached']} is missing"})
            elif sha256_file(f) != b["sha256"]:
                anomalies.append({"meeting_id": mid, "problem": f"baseline file {c['cached']} changed since the freeze"})
        elif mid in last:
            e = last[mid]
            state = e["state"]
            if e.get("path"):
                f = Path(raw) / SOURCE_MAP[source].raw_dir / "minutes" / e["path"]
                if not f.is_file():
                    anomalies.append({"meeting_id": mid, "problem": f"{e['path']} is missing"})
                elif sha256_file(f) != e.get("sha256"):
                    anomalies.append({"meeting_id": mid, "problem": f"{e['path']} differs from its ledger sha256"})
        elif _family_stops(transport, source):
            state = "unattempted-after-stop"
        else:
            state = "pending"
        out[mid] = state
        counts.setdefault(source, {})
        counts[source][state] = counts[source].get(state, 0) + 1
    return {"inventory_sha256": sha256_file(inventory), "states": out, "anomalies": anomalies,
            "counts": {s: dict(sorted(v.items())) for s, v in sorted(counts.items())}}


# --- CLI ------------------------------------------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("inventory")
    i.add_argument("--substrate", type=Path, default=DEFAULT_SUBSTRATE)
    i.add_argument("--out", type=Path, default=STAGING)
    for name in ("probe", "bulk"):
        p = sub.add_parser(name)
        p.add_argument("--source", required=True, choices=sorted(SOURCE_MAP))
        p.add_argument("--limit", type=int)
    sub.add_parser("states")
    sub.add_parser("baseline")
    for p in sub.choices.values():
        p.add_argument("--raw", type=Path, default=DEFAULT_RAW)
        p.add_argument("--inventory", type=Path, default=STAGING / INVENTORY)
    args = ap.parse_args(argv)
    try:
        if args.cmd == "inventory":
            path = freeze_inventory(args.substrate, args.raw, args.out)
            print(f"wrote {path} (sha256 {sha256_file(path)})")
            for s, c in json.loads(path.read_text())["counts"].items():
                print(f"  {s}: {c}")
            return 0
        if args.cmd == "baseline":
            print(f"wrote {freeze_baseline(args.inventory, args.raw)}")
            return 0
        if args.cmd == "states":
            states = candidate_states(args.inventory, args.raw)
            print(json.dumps({"counts": states["counts"], "anomalies": states["anomalies"]}, indent=1))
            return 1 if states["anomalies"] else 0
        res = fetch_source(args.inventory, args.source, args.raw, mode=args.cmd, limit=args.limit)
    except FetchError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    for e in res.entries:
        print(f"{e['state']:<26} {e['meeting_id']}  {e.get('reason') or ''}")
        for hop in e.get("chain") or []:
            print(f"    {hop['status']} {hop['url']}" + (f" -> {hop['location']}" if hop["location"] else ""))
    print(f"attempted {res.attempted}, fetched {res.fetched}"
          + (f"; LIMIT REACHED: {res.remaining} eligible candidates left for a later run" if res.remaining else ""))
    if res.skipped:
        print(f"SKIPPED: {res.skipped}", file=sys.stderr)
    if res.stop:
        print(f"STOPPED: {res.stop['evidence']}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
