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
MIN_INTERVAL_S = 1.0

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
    """Latest logged outcome per meeting."""
    log = fetched / "fetch-log.jsonl"
    latest: dict[str, dict] = {}
    if log.is_file():
        for row in _iter_jsonl(log):
            latest[row["meeting_id"]] = row
    return latest


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

    unplaced: dict[str, list[dict]] = {b: [] for b in windows}
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
            rec_id = rec_ids[0] if rec_ids else None
            url = normalize_url(records[rec_id].get("preferred_public_url")) if rec_id else None
            body_class = classify_meeting(body, m["title"])
            documents = sorted(docs[mid], key=lambda d: (ORIGIN_ORDER[d["origin"]], d["paths"]))
            if body_class in BODIES[body]["out_of_scope_classes"]:
                gap = "not_in_scope_body"
            elif documents:
                gap = None
            elif rec_id is None:
                gap = "no_minutes_record"
            elif not url:
                gap = "no_minutes_link"
            elif fetch_log.get(mid, {}).get("status") == "failed":
                gap = f"fetch_failed:{fetch_log[mid]['error']}"
            else:
                gap = "not_cached"
            row = {"meeting_id": mid, "date": m["date"], "title": m["title"],
                   "body_class": body_class, "minutes_record_id": rec_id, "minutes_url": url,
                   "documents": documents, "gap": gap}
            if len(rec_ids) > 1:
                row["other_minutes_record_ids"] = rec_ids[1:]
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


def _http_fetch(url: str) -> tuple[int, bytes]:
    import requests  # only the fetch step needs the network stack

    resp = requests.get(url, timeout=60, allow_redirects=True,
                        headers={"User-Agent": "open-marin-votes-inventory (civic research)"})
    return resp.status_code, resp.content


def fetch_gaps(inv: dict, fetched: Path, *, fetch: Callable[[str], tuple[int, bytes]] = _http_fetch,
               sleep: Callable[[float], None] = time.sleep, max_docs: int = MAX_FETCH_DOCS) -> list[dict]:
    """Download minutes for rows whose record has a link and no document; returns the log rows
    (also appended to fetched/fetch-log.jsonl)."""
    fetched = Path(fetched)
    todo = [row for b in inv["bodies"].values() for row in b["meetings"]
            if row["gap"] == "not_cached" and row["minutes_url"]][:max_docs]
    log: list[dict] = []
    first = True
    for row in todo:
        attempts, error, entry = 0, None, None
        while attempts < MAX_ATTEMPTS:
            if not first:
                sleep(MIN_INTERVAL_S)
            first = False
            attempts += 1
            try:
                status, body = fetch(row["minutes_url"])
            except Exception as exc:  # network errors are recorded, never raised
                error = f"error:{type(exc).__name__}"
                continue
            if status != 200:
                error = f"http_{status}"
                continue
            if not body:
                error = "empty_body"
                continue
            fmt = sniff_format(body)
            if fmt is None:
                error = "unknown_format"
                continue
            fetched.mkdir(parents=True, exist_ok=True)
            (fetched / f"{row['meeting_id']}.{fmt}").write_bytes(body)
            entry = {"meeting_id": row["meeting_id"], "status": "ok", "attempts": attempts,
                     "url": row["minutes_url"], "format": fmt, "sha256": _sha256_bytes(body)}
            break
        if entry is None:
            entry = {"meeting_id": row["meeting_id"], "status": "failed", "attempts": attempts,
                     "url": row["minutes_url"], "error": error}
        log.append(entry)
    if log:
        fetched.mkdir(parents=True, exist_ok=True)
        with (fetched / "fetch-log.jsonl").open("a", encoding="utf-8") as fh:
            for entry in log:
                fh.write(json.dumps(entry, sort_keys=True) + "\n")
    return log


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
    log = fetch_gaps(load_inventory(args.inventory), args.fetched,
                     max_docs=min(args.max_docs, MAX_FETCH_DOCS))
    ok = sum(1 for r in log if r["status"] == "ok")
    print(f"fetched {ok}/{len(log)}; log {args.fetched / 'fetch-log.jsonl'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
