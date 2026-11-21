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
  - a stop (403, 429, a challenge page) ends the run; a stopped host family is never asked again (any source);
  - never during the weekly job window (Mondays 05:00–07:00 local), never two fetch processes at once.
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
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))

from minutes_bodies import normalize_body  # noqa: E402
from minutes_sources import MINUTES_EXTENSIONS, SOURCE_MAP, host_family, off_limits, source_of  # noqa: E402
from minutes_transport import NetworkError, Refused, StopNow, Transport  # noqa: E402
from votes_inventory import normalize_url, sniff_format  # noqa: E402

HOME = Path.home()
DEFAULT_SUBSTRATE = HOME / "projects/marin-civic-graph/data/exports/public-substrate.sqlite"
DEFAULT_RAW = HOME / "projects/marin-civic-graph/data/raw"
STAGING = HOME / "open-marin-staging/minutes-coverage"
INVENTORY = "inventory.json"
FETCH_LOG = "minutes-fetch-log.jsonl"
LOCK = "minutes-fetch.lock"
PROBE_MAX = 3
MAX_HOPS = 5
STATES = ("already-cached", "fetched", "failed", "excluded-by-authorization", "no-url", "unattempted-after-stop")
TERMINAL = ("fetched", "failed", "excluded-by-authorization")


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
    path = out_dir / INVENTORY
    path.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    (out_dir / f"{INVENTORY}.sha256").write_text(f"{sha256_file(path)}  {INVENTORY}\n")
    return path


def load_inventory(path: Path) -> dict:
    path = Path(path)
    want = (path.parent / f"{path.name}.sha256").read_text().split()[0]
    if sha256_file(path) != want:
        raise FetchError(f"{path} no longer matches its sha256 ({want}); the inventory is frozen")
    return json.loads(path.read_text(encoding="utf-8"))


# --- the ledger -----------------------------------------------------------------------------------------------------

def read_ledger(raw: Path, source: str) -> list[dict]:
    path = Path(raw) / SOURCE_MAP[source].raw_dir / FETCH_LOG
    if not path.is_file():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def _append(raw: Path, source: str, entry: dict) -> None:
    path = Path(raw) / SOURCE_MAP[source].raw_dir / FETCH_LOG
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, sort_keys=True) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def _family_stops(transport: Transport, source: str) -> list[dict]:
    fams = {host_family(r.host) for r in SOURCE_MAP[source].rules}
    return [s for s in transport.stops() if s["host_family"] in fams]


# --- the fetch ------------------------------------------------------------------------------------------------------

@dataclass
class Result:
    attempted: int = 0
    fetched: int = 0
    stop: dict | None = None
    skipped: str | None = None
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


def _write_new(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.part")
    tmp.write_bytes(data)
    os.link(tmp, path)  # fails if the name exists: never overwrites
    tmp.unlink()


def _fetch_one(transport: Transport, source: str, url: str) -> tuple[str, str, dict]:
    """(state, reason, details) for one URL; raises StopNow / Refused('stopped') to end the run."""
    src = SOURCE_MAP[source]
    chain: list[dict] = []
    details = {"chain": chain, "final_url": url}
    if off_limits(urlsplit(url).hostname or "") or not src.admits_initial(url):
        return "excluded-by-authorization", f"initial URL is not on {source}'s allow-list (no request made)", details
    purpose = "document"
    for _ in range(MAX_HOPS + 1):
        try:
            resp = transport.get(url, src, purpose=purpose)
        except Refused as exc:
            if exc.kind == "stopped":
                raise
            return "excluded-by-authorization", str(exc), details
        except NetworkError as exc:
            return "failed", f"request failed: {exc}", details
        chain.append({"url": url, "status": resp.status, "location": resp.location})
        details["final_url"] = url
        if resp.location:
            target = resp.location
            if off_limits(urlsplit(target).hostname or "") or not src.admits(target):
                return "failed", f"redirect to {target} is not on {source}'s allow-list (logged, not requested)", \
                    details
            url, purpose = target, "redirect"
            continue
        if resp.status != 200:
            return "failed", f"HTTP {resp.status}", details
        kind = sniff_format(resp.body)
        if kind is None:
            return "failed", "response is not a PDF, HTML or DOCX document", details
        details |= {"data": resp.body, "kind": kind}
        return "fetched", "", details
    return "failed", f"more than {MAX_HOPS} redirects", details


def fetch_source(inventory: Path, source: str, raw: Path, *, mode: str = "bulk", limit: int | None = None,
                 transport: Transport | None = None, clock=dt.datetime.now) -> Result:
    if source not in SOURCE_MAP:
        raise FetchError(f"unknown source {source}")
    if mode not in ("probe", "bulk"):
        raise FetchError(f"unknown mode {mode}")
    inv = load_inventory(inventory)
    raw = Path(raw)
    if in_weekly_window(clock()):
        raise FetchError("refusing to run inside the weekly job window (Mondays 05:00–07:00 local)")
    transport = transport or Transport(raw)
    result = Result()
    if stops := _family_stops(transport, source):
        result.skipped = f"a stop record covers {', '.join(s['host_family'] for s in stops)}; no request made"
        return result
    ledger = read_ledger(raw, source)
    done = {e["meeting_id"] for e in ledger if e.get("state") in TERMINAL}
    by_url = {e["url"]: e for e in ledger if e.get("state") == "fetched"}
    tried_urls = {e["url"] for e in ledger if e.get("state") in ("failed", "excluded-by-authorization")}
    todo = sorted((c for c in inv["candidates"] if c["source"] == source and c["url"] and not c["cached"]
                   and c["meeting_id"] not in done), key=lambda c: (c["meeting_date"], c["meeting_id"]), reverse=True)
    cap = min(limit or PROBE_MAX, PROBE_MAX) if mode == "probe" else limit
    minutes_dir = raw / SOURCE_MAP[source].raw_dir / "minutes"
    with run_lock(raw):
        for c in todo:
            if cap is not None and result.attempted >= cap:
                break
            if in_weekly_window(clock()):
                result.skipped = "reached the weekly job window; the rest waits"
                break
            mid, url = c["meeting_id"], c["url"]
            if _cached(raw, source, mid):
                continue  # on disk already (saved by hand since the freeze): never refetched, never overwritten
            entry = {"meeting_id": mid, "url": url, "mode": mode, "fetched_at": dt.datetime.now(dt.UTC).isoformat(
                timespec="seconds")}
            if url in by_url:  # the same document under another meeting: no request
                prior = by_url[url]
                data = (minutes_dir / prior["path"]).read_bytes()
                name = f"{mid}.{prior['path'].rsplit('.', 1)[1]}"
                _write_new(minutes_dir / name, data)
                entry |= {"state": "fetched", "status": "ok", "path": name, "sha256": sha256_bytes(data),
                          "final_url": prior.get("final_url"), "chain": [],
                          "reason": f"same URL as {prior['meeting_id']}; bytes copied, no request"}
                _append(raw, source, entry)
                result.entries.append(entry)
                continue
            if url in tried_urls:
                prior = next(e for e in ledger if e["url"] == url and e.get("state") in TERMINAL)
                entry |= {"state": prior["state"], "status": "failed" if prior["state"] == "failed" else "excluded",
                          "chain": [], "final_url": url, "reason": f"same URL as {prior['meeting_id']}: "
                                                                  f"{prior['reason']} (not retried)"}
                _append(raw, source, entry)
                result.entries.append(entry)
                continue
            result.attempted += 1
            try:
                state, reason, details = _fetch_one(transport, source, url)
            except Refused as exc:  # a stop written by another process since this run began
                result.skipped = str(exc)
                break
            except StopNow as stop:
                entry |= {"state": "failed", "status": "failed", "reason": f"stop: {stop.record['evidence']}",
                          "chain": [], "final_url": stop.record["url"]}
                _append(raw, source, entry)
                result.entries.append(entry)
                result.stop = stop.record
                break
            entry |= {"state": state, "reason": reason, "chain": details["chain"], "final_url": details["final_url"]}
            if state == "fetched":
                name = f"{mid}.{details['kind']}"
                _write_new(minutes_dir / name, details["data"])
                entry |= {"status": "ok", "http_status": 200, "path": name, "sha256": sha256_bytes(details["data"])}
                by_url[url] = entry
                result.fetched += 1
            else:
                entry["status"] = "failed" if state == "failed" else "excluded"
                tried_urls.add(url)
                ledger.append(entry)
            _append(raw, source, entry)
            result.entries.append(entry)
    return result


# --- states ---------------------------------------------------------------------------------------------------------

def candidate_states(inventory: Path, raw: Path, transport: Transport | None = None) -> dict:
    """Every candidate's one state. `pending` (no terminal state yet) is not a goal state: it must reach zero."""
    inv = load_inventory(inventory)
    transport = transport or Transport(raw)
    last: dict[str, dict] = {}
    for source in SOURCE_MAP:
        for e in read_ledger(raw, source):
            if e.get("state") in TERMINAL:
                last[e["meeting_id"]] = e
    out, counts = {}, {}
    for c in inv["candidates"]:
        mid, source = c["meeting_id"], c["source"]
        if not c["url"]:
            state = "no-url"
        elif c["cached"]:
            state = "already-cached"
        elif mid in last:
            state = last[mid]["state"]
        elif _family_stops(transport, source):
            state = "unattempted-after-stop"
        else:
            state = "pending"
        out[mid] = state
        counts.setdefault(source, {})
        counts[source][state] = counts[source].get(state, 0) + 1
    return {"inventory_sha256": sha256_file(inventory), "states": out,
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
        if args.cmd == "states":
            print(json.dumps(candidate_states(args.inventory, args.raw)["counts"], indent=1))
            return 0
        res = fetch_source(args.inventory, args.source, args.raw, mode=args.cmd, limit=args.limit)
    except FetchError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    for e in res.entries:
        print(f"{e['state']:<26} {e['meeting_id']}  {e.get('reason') or ''}")
        for hop in e.get("chain") or []:
            print(f"    {hop['status']} {hop['url']}" + (f" -> {hop['location']}" if hop["location"] else ""))
    print(f"attempted {res.attempted}, fetched {res.fetched}")
    if res.skipped:
        print(f"SKIPPED: {res.skipped}", file=sys.stderr)
    if res.stop:
        print(f"STOPPED: {res.stop['evidence']}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
