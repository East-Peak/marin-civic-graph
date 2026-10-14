#!/usr/bin/env python3
"""Votes Part A, increment a: the frozen meeting/minutes inventory.

Every Meeting of the two bodies inside each body's window, from the frozen graph export, with its
minutes document(s) — cached under data/raw, dated files under minutes-test/, or fetched into the
staging dir — or the gap. Documents are identified by sha256; byte-identical files are one document
listing every path. Later stages read documents only through this inventory and re-verify each hash.

Usage:
    python scripts/votes_inventory.py build --export data/exports/live-graph-export --raw data/raw \
        --fetched ~/open-marin-staging/votes/fetched --out ~/open-marin-staging/votes/inventory \
        --window novato-city-council:2019-01-01:2026-03-10 --window marin-county-bos:2019-01-01:2026-03-20
    python scripts/votes_inventory.py fetch --inventory ~/open-marin-staging/votes/inventory \
        --fetched ~/open-marin-staging/votes/fetched

`fetch` downloads only rows whose minutes record has a link but no cached document (≤1 request/s,
≤150 documents, ≤3 attempts each) and appends every outcome to fetched/fetch-log.jsonl; `build`
never touches the network.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Iterable

BODIES = {
    "novato-city-council": {"out_of_scope_classes": {"planning_commission"}},
    "marin-county-bos": {"out_of_scope_classes": set()},
}

MAX_FETCH_DOCS = 150
MAX_ATTEMPTS = 3
MAX_REDIRECT_HOPS = 5
MIN_INTERVAL_S = 1.0
_BODY_MARKER_RE = re.compile(r"board of supervisors|city council|\bcouncil(member)?s?\b|\bsupervisors?\b", re.I)
_MEETING_MARKERS = (r"roll call", r"\bpresent:", r"called to order", r"\bconvened\b", r"\badjourn",
                    r"\bayes\b", r"\bmotion\b", r"\bminutes\b")

ORIGIN_ORDER = {"cache": 0, "fetched": 1, "cache_dated": 2}
_DATED_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.\w+$")


class InventoryError(Exception):
    pass


def classify_meeting(body: str, title: str) -> str:
    """The body actually meeting, from the listing title (Novato's id space also holds commission
    meetings; the Board's holds budget hearings and media duplicates)."""
    t = (title or "").lower()
    if body == "novato-city-council":
        if "joint" in t:
            return "council_joint"
        if "planning commission" in t and "council" not in t:
            return "planning_commission"
        if "council" in t:
            return "council"
        return "council_other"
    if "spanish audio" in t:
        return "bos_media_duplicate"
    if "joint" in t:
        return "bos_joint"
    if t.startswith(("board of supervisors", "budget")):
        return "bos"
    return "bos_other"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sniff_format(data: bytes) -> str | None:
    if data[:5] == b"%PDF-":
        return "pdf"
    if data[:4] == b"PK\x03\x04":
        import io
        import zipfile
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                return "docx" if "word/document.xml" in z.namelist() else None
        except zipfile.BadZipFile:
            return None
    head = data[:4096].lower()
    if b"<html" in head or b"<!doctype" in head or b"<script" in head or b"<body" in head:
        return "html"
    return None


def normalize_url(url: str | None) -> str | None:
    if url and url.startswith("//"):
        return "https:" + url
    return url


def _iter_jsonl(path: Path) -> Iterable[dict]:
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


def _pdftotext_version() -> str:
    try:
        out = subprocess.run(["pdftotext", "-v"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return "pdftotext unavailable"
    lines = (out.stderr or out.stdout).splitlines()
    return lines[0].strip() if lines else "pdftotext unknown"


def _read_fetch_log(fetched: Path) -> dict[str, dict]:
    """Per meeting: attempts used and the latest outcome. Each attempt is journaled `started`
    before its request and again with its result; a `started` with no result is an interrupted
    attempt and still counts."""
    log = fetched / "fetch-log.jsonl"
    history: dict[str, dict] = {}
    if log.is_file():
        for row in _iter_jsonl(log):
            h = history.setdefault(row["meeting_id"], {"attempts": 0, "latest": None})
            h["attempts"] = max(h["attempts"], row["attempt"])
            h["latest"] = row
    for h in history.values():
        if h["latest"]["status"] == "started":
            h["latest"] = {**h["latest"], "status": "failed", "error": "interrupted"}
    return history


def _load_export(export: Path, windows: dict[str, tuple[str, str]]):
    meetings: dict[str, dict] = {}
    records: dict[str, dict] = {}
    for n in _iter_jsonl(export / "nodes.jsonl"):
        nid = n["id"]
        labels = n.get("labels") or []
        p = n.get("properties") or {}
        if "Meeting" in labels:
            for body, (lo, hi) in windows.items():
                if nid.startswith(f"meeting-{body}-") and lo <= (p.get("meeting_date") or "") <= hi:
                    meetings[nid] = {"body": body, "date": p["meeting_date"],
                                     "title": p.get("title") or p.get("display_label") or ""}
        elif "Record" in labels and p.get("record_type") == "meeting_minutes":
            records[nid] = p
    minutes: dict[str, list[str]] = {}
    for e in _iter_jsonl(export / "edges.jsonl"):
        if e["type"] == "EVIDENCED_BY" and e["start_id"] in meetings and e["end_id"] in records:
            minutes.setdefault(e["start_id"], []).append(e["end_id"])
    return meetings, records, minutes


def _doc(paths: list[str], sha: str, data: bytes, origin: str) -> dict:
    return {"paths": sorted(paths), "sha256": sha, "bytes": len(data),
            "format": sniff_format(data) or "unknown", "origin": origin}


def _add_document(docs: list[dict], path: str, data: bytes, origin: str) -> None:
    sha = _sha256_bytes(data)
    for d in docs:
        if d["sha256"] == sha:
            d["paths"] = sorted(set(d["paths"]) | {path})
            if ORIGIN_ORDER[origin] < ORIGIN_ORDER[d["origin"]]:
                d["origin"] = origin
            return
    docs.append(_doc([path], sha, data, origin))


_MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
           "november", "december")
_PRINTED_DATE_RE = re.compile(r"\b(" + "|".join(_MONTHS) + r")\s+(\d{1,2}),?\s+(\d{4})\b", re.I)


def printed_date(path: Path, fmt: str) -> tuple[str | None, bool]:
    """(the first date the document prints, whether its heading says closed session)."""
    from votes_text import canonical_text

    head = canonical_text(path, fmt).text[:3000]
    m = _PRINTED_DATE_RE.search(head)
    date = None
    if m:
        date = f"{int(m.group(3)):04d}-{_MONTHS.index(m.group(1).lower()) + 1:02d}-{int(m.group(2)):02d}"
    return date, bool(re.search(r"closed\s+session", head[:400], re.I))


def _assign_shared(meetings: dict, docs: dict, raw: Path, fetched: Path) -> tuple[dict, list]:
    """A document (by sha256) attached to several meetings belongs to the one whose date it prints
    (a same-day tie goes to the meeting whose closed-session-ness matches its heading); the others
    record whose it is. Unresolvable shares are parsed for nobody and recorded."""
    owners: dict[str, list[str]] = {}
    for mid, ds in docs.items():
        for d in ds:
            owners.setdefault(d["sha256"], []).append(mid)
    gaps: dict[str, str] = {}
    unplaced: list = []
    for sha, mids in sorted(owners.items()):
        if len(mids) < 2:
            continue
        doc = next(d for d in docs[mids[0]] if d["sha256"] == sha)
        root, _, rest = doc["paths"][0].partition("/")
        path = (Path(raw) if root == "raw" else Path(fetched)) / rest
        date, closed = printed_date(path, doc["format"])
        cands = sorted(m for m in mids if meetings[m]["date"] == date)
        if len(cands) > 1:
            cands = [m for m in cands if bool(re.search(r"closed\s+session", meetings[m]["title"], re.I)) == closed]
        for m in mids:
            docs[m] = [d for d in docs[m] if d["sha256"] != sha]
        if len(cands) == 1:
            docs[cands[0]].append(doc)
            for m in mids:
                if m != cands[0]:
                    gaps[m] = f"document_of_other_meeting:{cands[0]}"
        else:
            for m in mids:
                gaps[m] = "document_meeting_ambiguous"
            unplaced.append((meetings[mids[0]]["body"], {**doc, "reason": "shared_by_several_meetings",
                                                        "candidates": sorted(mids)}))
    return gaps, unplaced


def build_inventory(export: Path, raw: Path, fetched: Path,
                    windows: dict[str, tuple[str, str]]) -> dict:
    export, raw, fetched = Path(export), Path(raw), Path(fetched)
    meetings, records, minutes = _load_export(export, windows)
    fetch_log = _read_fetch_log(fetched) if fetched.is_dir() else {}

    docs: dict[str, list[dict]] = {mid: [] for mid in meetings}
    for mid, m in meetings.items():
        cache_dir = raw / m["body"] / "minutes"
        for ext in ("pdf", "html"):
            f = cache_dir / f"{mid}.{ext}"
            if f.is_file():
                _add_document(docs[mid], f"raw/{m['body']}/minutes/{f.name}", f.read_bytes(), "cache")
        for ext in ("pdf", "html", "docx"):
            f = fetched / f"{mid}.{ext}"
            if f.is_file():
                _add_document(docs[mid], f"fetched/{f.name}", f.read_bytes(), "fetched")

    shared_gaps, shared_unplaced = _assign_shared(meetings, docs, raw, fetched)
    unplaced: dict[str, list[dict]] = {b: [] for b in windows}
    for b, d in shared_unplaced:
        unplaced[b].append(d)
    for body in windows:
        dated_dir = raw / body / "minutes-test"
        if not dated_dir.is_dir():
            continue
        for f in sorted(dated_dir.iterdir()):
            mt = _DATED_RE.match(f.name)
            if not mt or not f.is_file():
                continue
            rel = f"raw/{body}/minutes-test/{f.name}"
            same_day = sorted(mid for mid, m in meetings.items()
                              if m["body"] == body and m["date"] == mt.group(1))
            data = f.read_bytes()
            if len(same_day) == 1:
                _add_document(docs[same_day[0]], rel, data, "cache_dated")
            else:
                d = _doc([rel], _sha256_bytes(data), data, "cache_dated")
                d["reason"] = "no_meeting_on_date" if not same_day else "several_meetings_on_date"
                d["candidates"] = same_day
                unplaced[body].append(d)

    bodies: dict[str, dict] = {}
    for body in sorted(windows):
        rows = []
        for mid in sorted((k for k, m in meetings.items() if m["body"] == body),
                          key=lambda k: (meetings[k]["date"], k)):
            m = meetings[mid]
            rec_ids = sorted(minutes.get(mid, []))
            if len(rec_ids) > 1:
                raise InventoryError(f"{mid}: several minutes records {rec_ids}; each would need its own "
                                     "document or gap, which this inventory does not model")
            rec_id = rec_ids[0] if rec_ids else None
            url = normalize_url(records[rec_id].get("preferred_public_url")) if rec_id else None
            body_class = classify_meeting(body, m["title"])
            documents = sorted(docs[mid], key=lambda d: (ORIGIN_ORDER[d["origin"]], d["paths"]))
            if body_class in BODIES[body]["out_of_scope_classes"]:
                gap = "not_in_scope_body"
            elif mid in shared_gaps and not documents:
                gap = shared_gaps[mid]
            elif documents:
                gap = None
            elif rec_id is None:
                gap = "no_minutes_record"
            elif not url:
                gap = "no_minutes_link"
            elif (fetch_log.get(mid) or {}).get("latest", {}).get("status") == "failed":
                gap = f"fetch_failed:{fetch_log[mid]['latest']['error']}"
            else:
                gap = "not_cached"
            row = {"meeting_id": mid, "date": m["date"], "title": m["title"],
                   "body_class": body_class, "minutes_record_id": rec_id, "minutes_url": url,
                   "documents": documents, "gap": gap}
            rows.append(row)
        bodies[body] = {"meetings": rows, "unplaced_documents": unplaced[body]}

    return {
        "schema": "votes-inventory-v1",
        "export": {"path": str(export),
                   "nodes_sha256": _sha256(export / "nodes.jsonl"),
                   "edges_sha256": _sha256(export / "edges.jsonl")},
        "roots": {"raw": str(raw), "fetched": str(fetched)},
        "windows": {b: list(w) for b, w in sorted(windows.items())},
        "tools": {"pdftotext": _pdftotext_version()},
        "bodies": bodies,
    }


def write_inventory(inv: dict, out: Path) -> Path:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(inv, indent=1, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    (out / "inventory.json").write_bytes(data)
    (out / "inventory.sha256").write_text(f"{_sha256_bytes(data)}  inventory.json\n")
    return out / "inventory.json"


def load_inventory(out: Path) -> dict:
    out = Path(out)
    data = (out / "inventory.json").read_bytes()
    pinned = (out / "inventory.sha256").read_text().split()[0]
    if _sha256_bytes(data) != pinned:
        raise InventoryError(f"inventory.json sha256 does not match {out / 'inventory.sha256'}")
    return json.loads(data)


def resolve_path(inv: dict, rel: str, base: Path | None = None) -> Path:
    root, _, rest = rel.partition("/")
    root_dir = Path(base) / root if base is not None else Path(inv["roots"][root])
    return root_dir / rest


def iter_documents(inv: dict):
    """(body, meeting row, document) for every document of every meeting, in inventory order."""
    for body, b in sorted(inv["bodies"].items()):
        for row in b["meetings"]:
            for doc in row["documents"]:
                yield body, row, doc


def verify_documents(inv: dict, base: Path | None = None) -> None:
    for _, row, doc in iter_documents(inv):
        for rel in doc["paths"]:
            p = resolve_path(inv, rel, base)
            if not p.is_file() or _sha256(p) != doc["sha256"]:
                raise InventoryError(f"{row['meeting_id']}: {rel} does not match its inventoried sha256")


def _http_fetch(url: str) -> tuple[int, bytes, str | None]:
    """One HTTP request, redirects NOT followed (the caller rate-limits every hop)."""
    from urllib.parse import urljoin

    import requests  # only the fetch step needs the network stack

    resp = requests.get(url, timeout=60, allow_redirects=False,
                        headers={"User-Agent": "open-marin-votes-inventory (civic research)"})
    loc = resp.headers.get("Location")
    return resp.status_code, resp.content, urljoin(url, loc) if loc else None


def document_text(data: bytes, fmt: str) -> str:
    """Rough text for the minutes sanity check (the parser has its own canonical text)."""
    if fmt == "pdf":
        try:
            out = subprocess.run(["pdftotext", "-layout", "-", "-"], input=data,
                                 capture_output=True, timeout=120)
        except (OSError, subprocess.SubprocessError):
            return ""
        return out.stdout.decode("utf-8", "replace")
    if fmt == "docx":
        import io
        import zipfile
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            xml = z.read("word/document.xml").decode("utf-8", "replace")
        return re.sub(r"<[^>]+>", " ", xml)
    html = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", data.decode("utf-8", "replace"))
    return re.sub(r"<[^>]+>", " ", html)


def looks_like_minutes(data: bytes, fmt: str) -> bool:
    """Meeting-specific evidence: some length, the governing body named, and at least three
    distinct meeting-record markers (an error or maintenance page has none of these together)."""
    text = document_text(data, fmt)
    markers = sum(1 for m in _MEETING_MARKERS if re.search(m, text, re.I))
    return len(text.strip()) >= 200 and bool(_BODY_MARKER_RE.search(text)) and markers >= 3


def fetch_gaps(inv: dict, fetched: Path, *,
               fetch: Callable[[str], tuple[int, bytes, str | None]] = _http_fetch,
               sleep: Callable[[float], None] = time.sleep,
               now: Callable[[], float] = time.monotonic,
               max_docs: int = MAX_FETCH_DOCS,
               validate: Callable[[bytes, str], bool] = looks_like_minutes) -> list[dict]:
    """Download minutes for in-scope rows whose record has a link and no document.

    Budgets are cumulative over every run, read from fetched/fetch-log.jsonl (one line per
    attempt, appended as it happens): at most `max_docs` distinct meetings ever attempted and
    MAX_ATTEMPTS attempts per meeting. Every HTTP request, redirect hops included, is at least
    MIN_INTERVAL_S after the previous one. Returns one summary per meeting attempted this run."""
    if not 0 <= max_docs <= MAX_FETCH_DOCS:
        raise ValueError(f"max_docs must be within 0..{MAX_FETCH_DOCS}, got {max_docs}")
    fetched = Path(fetched)
    history = _read_fetch_log(fetched)
    new_budget = max_docs - len(history)
    last_request: list[float] = []

    def request(url: str):
        if last_request:
            wait = MIN_INTERVAL_S - (now() - last_request[0])
            if wait > 0:
                sleep(wait)
        last_request[:] = [now()]
        return fetch(url)

    def journal(entry: dict) -> None:
        fetched.mkdir(parents=True, exist_ok=True)
        with (fetched / "fetch-log.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, sort_keys=True) + "\n")
            fh.flush()

    summaries: list[dict] = []
    for row in (r for b in inv["bodies"].values() for r in b["meetings"]):
        if row["documents"] or not row["minutes_url"] or row["gap"] == "not_in_scope_body":
            continue
        h = history.get(row["meeting_id"], {"attempts": 0, "latest": None})
        if (h["latest"] or {}).get("status") == "ok" or h["attempts"] >= MAX_ATTEMPTS:
            continue
        if h["attempts"] == 0:
            if new_budget <= 0:
                continue
            new_budget -= 1
        attempts, summary = h["attempts"], None
        while attempts < MAX_ATTEMPTS and summary is None:
            attempts += 1
            entry = {"meeting_id": row["meeting_id"], "attempt": attempts, "url": row["minutes_url"]}
            journal({**entry, "status": "started"})
            url, error, body = row["minutes_url"], None, b""
            try:
                for _ in range(MAX_REDIRECT_HOPS + 1):
                    status, body, location = request(url)
                    if 300 <= status < 400 and location:
                        url = location
                        continue
                    break
                else:
                    status, error = None, "too_many_redirects"
            except Exception as exc:  # network errors are recorded, never raised
                error = f"error:{type(exc).__name__}"
            if error is None:
                fmt = sniff_format(body) if status == 200 and body else None
                if status != 200:
                    error = f"http_{status}"
                elif not body:
                    error = "empty_body"
                elif fmt is None:
                    error = "unknown_format"
                elif not validate(body, fmt):
                    error = "not_minutes"
            if error is None:
                fetched.mkdir(parents=True, exist_ok=True)
                (fetched / f"{row['meeting_id']}.{fmt}").write_bytes(body)
                entry.update(status="ok", format=fmt, sha256=_sha256_bytes(body))
                journal(entry)
                summary = {"meeting_id": row["meeting_id"], "status": "ok", "attempts": attempts,
                           "url": row["minutes_url"], "format": fmt, "sha256": entry["sha256"]}
            else:
                entry.update(status="failed", error=error)
                journal(entry)
                if attempts >= MAX_ATTEMPTS:
                    summary = {"meeting_id": row["meeting_id"], "status": "failed",
                               "attempts": attempts, "url": row["minutes_url"], "error": error}
        summaries.append(summary)
    return summaries


def _parse_window(spec: str) -> tuple[str, tuple[str, str]]:
    body, lo, hi = spec.split(":")
    if body not in BODIES:
        raise argparse.ArgumentTypeError(f"unknown body {body}")
    return body, (lo, hi)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--export", required=True, type=Path)
    b.add_argument("--raw", required=True, type=Path)
    b.add_argument("--fetched", required=True, type=Path)
    b.add_argument("--out", required=True, type=Path)
    b.add_argument("--window", action="append", required=True, type=_parse_window)
    f = sub.add_parser("fetch")
    f.add_argument("--inventory", required=True, type=Path)
    f.add_argument("--fetched", required=True, type=Path)
    f.add_argument("--max-docs", type=int, default=MAX_FETCH_DOCS)
    args = ap.parse_args(argv)

    if args.cmd == "build":
        inv = build_inventory(args.export, args.raw, args.fetched, dict(args.window))
        path = write_inventory(inv, args.out)
        for body, bd in inv["bodies"].items():
            gaps: dict[str, int] = {}
            for r in bd["meetings"]:
                gaps[r["gap"] or "ok"] = gaps.get(r["gap"] or "ok", 0) + 1
            print(f"{body}: {len(bd['meetings'])} meetings {dict(sorted(gaps.items()))}")
        print(f"wrote {path}")
        return 0
    summaries = fetch_gaps(load_inventory(args.inventory), args.fetched, max_docs=args.max_docs)
    ok = sum(1 for r in summaries if r["status"] == "ok")
    print(f"fetched {ok}/{len(summaries)}; log {args.fetched / 'fetch-log.jsonl'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
