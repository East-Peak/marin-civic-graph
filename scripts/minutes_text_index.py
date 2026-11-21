#!/usr/bin/env python3
"""Minutes text: an operator-local, page-level full-text index of the cached minutes documents.

Reads `<raw>/<source>/minutes/*` for each source (read-only) and the public substrate SQLite (read-only), and
writes ONE SQLite file outside every repo and worktree (default ~/open-marin-research/minutes-text.sqlite):

  pages(id, meeting_id, source, body, meeting_date, page, text, official_url, source_sha256) + pages_fts (FTS5)
  coverage(meeting_id, source, body, meeting_date, minutes_url, state)   every Meeting with a minutes link
  dispositions(path, source, meeting_id, sha256, disposition, reason)    every file enumerated

Minutes name private people (commenters, applicants, litigants): this file is never read by the bake, the snapshot
push or any export, no node is created from its text, and the build never touches Neo4j.

Every enumerated file gets exactly one disposition (DISPOSITIONS). The linkage rules never guess:
  - a file is a Meeting's only by its name `<meeting_id>.<ext>`, and only if the substrate holds that Meeting
    (San Anselmo's names come from its staging index.json via `import-san-anselmo`, which writes a manifest);
    (or, in a source with a manifest, a later fetch whose bytes minutes-fetch-log.jsonl records);
  - first, one document's bytes under several meeting ids are one document (`shared-indexed`), owned by the meeting
    `votes_inventory.shared_owner` resolves from the date it prints, otherwise `quarantined-ambiguous`;
  - then, several different documents owned by one meeting: the latest by saved date (minutes-manifest.json
    `fetch_date` or minutes-fetch-log.jsonl `fetched_at`, the votes-refresh convention) is kept and the others are
    `superseded`; without saved dates that order them, all are `quarantined-ambiguous`.
The body is the Meeting title normalized by `minutes_bodies`. The build is deterministic: same inputs, same bytes.

    python scripts/minutes_text_index.py import-san-anselmo     # once: staged San Anselmo files → raw store
    python scripts/minutes_text_index.py build                  # index + report (~/open-marin-staging/minutes-text)
    python scripts/minutes_text_index.py search "memorial park"
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from minutes_bodies import SOURCES, normalize_body
from minutes_sidecars import check as check_sidecar, read_sidecar, sidecar_path
from minutes_sources import SOURCE_MAP
from votes_inventory import normalize_url, printed_date, printed_date_in, shared_owner, sniff_format
from votes_text import _FOLD, docx_lines, html_lines

HOME = Path.home()
RAW_ROOT = Path(os.environ.get("MINUTES_RAW_ROOT") or HOME / "projects/marin-civic-graph/data/raw")
SUBSTRATE = HOME / "projects/marin-civic-graph/data/exports/public-substrate.sqlite"
INDEX_PATH = Path(os.environ.get("MINUTES_TEXT_DB_PATH") or HOME / "open-marin-research/minutes-text.sqlite")
REPORT_DIR = HOME / "open-marin-staging/minutes-text"
SA_STAGING = HOME / "open-marin-staging/san-anselmo-minutes"
SA = "san-anselmo-town-council"

DISPOSITIONS = ("indexed", "shared-indexed", "superseded", "quarantined-ambiguous", "unmapped", "no-text",
                "unreadable")
COVERAGE_STATES = ("indexed", "not cached", "no-text", "quarantined", "unmapped")
INDEXED = ("indexed", "shared-indexed")
MIN_TEXT_CHARS = 40  # fewer non-space characters than this in a whole document: no text layer
LEGACY_DOC_REASON = "a legacy Word .doc (OLE2) under this name; no .doc reader"
SHORTFALL_BELOW = 0.90
OLE2_MAGIC = bytes.fromhex("d0cf11e0a1b11ae1")
MANIFEST, FETCH_LOG = "minutes-manifest.json", "minutes-fetch-log.jsonl"

SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE pages (id INTEGER PRIMARY KEY, meeting_id TEXT NOT NULL, source TEXT NOT NULL, body TEXT NOT NULL,
    meeting_date TEXT NOT NULL, page INTEGER NOT NULL, text TEXT NOT NULL, official_url TEXT,
    source_sha256 TEXT NOT NULL, text_source TEXT NOT NULL CHECK (text_source IN ('text', 'ocr', 'converted')),
    UNIQUE (meeting_id, page));
CREATE VIRTUAL TABLE pages_fts USING fts5(text, content='pages', content_rowid='id',
    tokenize='unicode61 remove_diacritics 2');
CREATE TABLE coverage (meeting_id TEXT PRIMARY KEY, source TEXT NOT NULL, body TEXT NOT NULL,
    meeting_date TEXT NOT NULL, minutes_url TEXT, state TEXT NOT NULL);
CREATE TABLE dispositions (path TEXT PRIMARY KEY, source TEXT NOT NULL, meeting_id TEXT, sha256 TEXT,
    disposition TEXT NOT NULL, reason TEXT, text_source TEXT);
"""


class IndexBuildError(Exception):
    pass


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# --- inputs -----------------------------------------------------------------------------------------------------

def load_meetings(substrate: Path, sources) -> tuple[dict[str, dict], str]:
    """Every Meeting of the sources: {id: {source, date, title, url}} (url: its minutes record's, normalized)."""
    db = sqlite3.connect(f"file:{Path(substrate)}?mode=ro", uri=True)
    try:
        meetings: dict[str, dict] = {}
        shapes = [SOURCE_MAP[s] for s in sources]
        for mid, props in db.execute("SELECT id, props FROM nodes WHERE type = 'Meeting' AND id LIKE 'meeting-%' "
                                     "ORDER BY id"):
            src = next((s for s in shapes if s.matches(mid)), None)
            if src is None:
                continue
            p = json.loads(props)
            meetings[mid] = {"source": src.id, "date": p.get("meeting_date") or "", "title": p.get("title") or "",
                             "url": None}
        for mid, url in db.execute(
                "SELECT e.source, json_extract(r.props, '$.preferred_public_url') FROM edges e "
                "JOIN nodes r ON r.id = e.target WHERE e.rel = 'EVIDENCED_BY' AND e.source LIKE 'meeting-%' "
                "AND json_extract(r.props, '$.record_type') = 'meeting_minutes' ORDER BY e.source, r.id"):
            if mid in meetings and url and not meetings[mid]["url"]:
                meetings[mid]["url"] = normalize_url(url)
        row = db.execute("SELECT value FROM meta WHERE key = 'as_of_date'").fetchone()
        return meetings, row[0] if row else ""
    finally:
        db.close()


def _saved_dates(source_dir: Path) -> tuple[dict[str, str], dict[str, dict] | None, dict[str, set[str]]]:
    """({file name: saved date}, {file name: manifest entry} or None when the source has no manifest,
    {file name: sha256s the fetch log records for it})."""
    saved: dict[str, str] = {}
    fetched: dict[str, set[str]] = {}
    log = source_dir / FETCH_LOG
    if log.is_file():
        lines = log.read_text(encoding="utf-8", errors="replace").split("\n")
        for i, line in enumerate(lines):
            try:
                row = json.loads(line) if line.strip() else {}
            except json.JSONDecodeError:
                if i == len(lines) - 1:  # a torn final append (a crash mid-write): skipped
                    continue
                raise IndexBuildError(f"{log} line {i + 1} is not JSON") from None
            name = Path(row.get("path") or "").name
            if row.get("status") in ("ok", "cached") and name and row.get("fetched_at"):
                saved[name] = max(saved.get(name, ""), row["fetched_at"])
                if row.get("sha256"):
                    fetched.setdefault(name, set()).add(row["sha256"])
    manifest = None
    if (source_dir / MANIFEST).is_file():
        manifest = {d["file"]: d for d in json.loads((source_dir / MANIFEST).read_text())["documents"]}
        for name, d in manifest.items():
            saved.setdefault(name, d.get("fetch_date") or "")
    return {k: v for k, v in saved.items() if v}, manifest, fetched


# --- text ---------------------------------------------------------------------------------------------------------

def _clean(text: str) -> str:
    lines = (re.sub(r"[ \t]+", " ", line).strip() for line in text.translate(_FOLD).splitlines())
    return "\n".join(line for line in lines if line)


def extract_pages(path: Path, fmt: str) -> list[str]:
    """The document's text, one string per page (an HTML or DOCX document is one page)."""
    if fmt == "pdf":
        out = subprocess.run(["pdftotext", "-enc", "UTF-8", str(path), "-"], capture_output=True, timeout=300)
        if out.returncode != 0:
            raise IndexBuildError(f"pdftotext exit {out.returncode}: {out.stderr.decode('utf-8', 'replace')[:120]}")
        pages = out.stdout.decode("utf-8", "replace").split("\f")
        if pages and not pages[-1].strip():
            pages.pop()
        return [_clean(p) for p in pages]
    if fmt == "html":
        return [_clean("\n".join(html_lines(path.read_bytes().decode("utf-8", "replace"))))]
    if fmt == "docx":
        return [_clean("\n".join(docx_lines(path.read_bytes())))]
    raise IndexBuildError(f"unsupported format {fmt}")


# --- dispositions -------------------------------------------------------------------------------------------------

def _pdf_pages(path: Path) -> int | None:
    out = subprocess.run(["pdfinfo", str(path)], capture_output=True, timeout=60)
    m = re.search(rb"^Pages:\s+(\d+)", out.stdout, re.M) if out.returncode == 0 else None
    return int(m.group(1)) if m else None


def _sidecar(raw: Path, f: dict, text_source: str) -> tuple[list[str] | None, str | None]:
    """(pages, None) from this file's valid sidecar; (None, problem) for an invalid one; (None, None) for none.
    An OCR sidecar must match the original's page count, which pdfinfo has to read."""
    path = sidecar_path(raw, SOURCE_MAP[f["source"]].raw_dir, f["meeting_id"], text_source)
    try:
        doc = read_sidecar(path)
        if doc is None:
            return None, None
        page_count = _pdf_pages(f["abs"]) if text_source == "ocr" else None
        return check_sidecar(doc, f["path"], f["sha256"], text_source, page_count)
    except Exception as exc:  # a malformed or unreadable sidecar is a reported problem, never a crash
        return None, f"malformed sidecar ({type(exc).__name__})"


def _classify(raw: Path, sources, meetings: dict) -> tuple[list[dict], list[dict]]:
    """(every file with a disposition or None = still a candidate, the documents to index)."""
    files: list[dict] = []
    for source in sources:
        src = SOURCE_MAP[source]
        sdir = raw / src.raw_dir
        saved, manifest, fetched = _saved_dates(sdir)
        root = sdir / "minutes"
        for p in sorted(x for x in root.rglob("*") if x.is_file()) if root.is_dir() else []:
            f = {"path": p.relative_to(raw).as_posix(), "abs": p, "source": source, "meeting_id": None,
                 "sha256": None, "format": None, "saved": None, "disposition": None, "reason": None,
                 "text_source": None, "raw": raw}
            files.append(f)
            mid = src.file_meeting_id(p.name) if p.parent == root else None
            try:
                data = p.read_bytes()
            except OSError as exc:
                f.update(disposition="unreadable", reason=f"could not be read: {type(exc).__name__}", meeting_id=mid)
                continue
            f["sha256"] = _sha(data)
            if not mid:
                f.update(disposition="unmapped", reason="file name is not a meeting id")
                continue
            f["meeting_id"] = mid
            entry = (manifest or {}).get(p.name)
            if f["meeting_id"] not in meetings:
                f.update(disposition="unmapped", reason="no Meeting with this id in the substrate")
            elif manifest is not None and entry is None and f["sha256"] not in fetched.get(p.name, ()):
                f.update(disposition="unmapped", reason=f"not listed in {source}/{MANIFEST} "
                                                        f"or a matching {FETCH_LOG} entry")
            elif entry and entry.get("sha256") and entry["sha256"] != f["sha256"]:
                f.update(disposition="unmapped", reason=f"bytes differ from {source}/{MANIFEST}")
            elif (fmt := sniff_format(data)) is None and data[:8] == OLE2_MAGIC:
                pages, problem = _sidecar(raw, f, "converted")
                # still a candidate without a conversion: a byte-identical copy's sidecar may convert it
                f.update(format="converted" if pages is not None else "ole2", converted=pages, ole2_problem=problem,
                         saved=saved.get(p.name), url=(entry or {}).get("url"))
            elif fmt is None:
                f.update(disposition="unreadable", reason="not a PDF, HTML or DOCX document")
            else:
                f.update(format=fmt, saved=saved.get(p.name), url=(entry or {}).get("url"))
    return files, _supersede(_share(files, meetings))


def _supersede(docs: list[dict]) -> list[dict]:
    """Several different documents for one meeting (after shared bytes found their owner): keep the latest saved,
    never a guess. Returns the documents still to index."""
    by_meeting: dict[str, list[dict]] = {}
    for d in docs:
        own = [f["saved"] for f in d["files"] if f["meeting_id"] == d["meeting_id"]]
        d["saved"] = max(own) if own and all(own) else None
        by_meeting.setdefault(d["meeting_id"], []).append(d)
    keep = []
    for ds in by_meeting.values():
        if len(ds) == 1:
            keep += ds
            continue
        newest = max(ds, key=lambda d: d["saved"] or "")
        if all(d["saved"] for d in ds) and sum(d["saved"] == newest["saved"] for d in ds) == 1:
            name = Path(next(f["path"] for f in newest["files"] if f["meeting_id"] == newest["meeting_id"])).name
            keep.append(newest)
            for d in ds:
                if d is not newest:
                    for f in d["files"]:
                        f.update(disposition="superseded", reason=f"superseded by {name} (saved {newest['saved']}; "
                                                                  f"this {d['saved']})")
        else:
            for d in ds:
                for f in d["files"]:
                    f.update(disposition="quarantined-ambiguous",
                             reason="several versions of this meeting's minutes and no saved dates that order them")
    return sorted(keep, key=lambda d: d["files"][0]["sha256"])


def _share(files: list[dict], meetings: dict) -> list[dict]:
    """Group the candidates by bytes; one document per group, attached to one meeting or quarantined."""
    groups: dict[str, list[dict]] = {}
    for f in files:
        if f["disposition"] is None:
            groups.setdefault(f["sha256"], []).append(f)
    docs = []
    for sha, fs in sorted(groups.items()):
        mids = sorted({f["meeting_id"] for f in fs})
        if all(f["format"] == "ole2" for f in fs):  # a legacy .doc no copy of which has a valid conversion
            shared = f"same bytes under {', '.join(mids)}; " if len(mids) > 1 else ""
            for f in fs:
                f.update(disposition="unreadable", reason=shared + LEGACY_DOC_REASON
                         + (f"; converted sidecar ignored: {f['ole2_problem']}" if f["ole2_problem"] else ""))
                if f["ole2_problem"]:
                    f["sidecar_problem"] = f["ole2_problem"]
            continue
        if len(mids) == 1:
            docs.append({"files": fs, "meeting_id": mids[0], "shared": False})
            continue
        try:
            date, closed = _printed(fs)
        except Exception as exc:  # an unreadable shared document resolves nobody
            date, closed, why = None, False, f"its text could not be read ({type(exc).__name__})"
        else:
            why = f"the date it prints ({date or 'none'}) names none of them alone"
        owner = shared_owner(mids, meetings, date, closed)
        if owner is None:
            for f in fs:
                f.update(disposition="quarantined-ambiguous", reason=f"same bytes under {', '.join(mids)}; {why}")
            continue
        for f in fs:
            f["reason"] = f"same bytes under {', '.join(mids)}; attached to {owner}, the meeting whose date it prints"
        docs.append({"files": fs, "meeting_id": owner, "shared": True})
    return docs


def _printed(fs: list[dict]) -> tuple[str | None, bool]:
    """The date a shared document prints: from its own text, else from any one of its files' valid sidecars (the
    bytes are identical, so any copy's validated text is the document's)."""
    if (converted := _converted(fs)) is not None:
        return printed_date_in("\n".join(converted))
    f = fs[0]
    date, closed = printed_date(f["abs"], f["format"])
    if date is None and f["format"] == "pdf":
        pages, _ = _ocr(fs)
        if pages is not None:
            return printed_date_in("\n".join(_clean(p) for p in pages))
    return date, closed


def _converted(fs: list[dict]) -> list[str] | None:
    return next((x["converted"] for x in fs if x["format"] == "converted"), None)


def _ocr(fs: list[dict]) -> tuple[list[str] | None, str | None]:
    """The first valid OCR sidecar among byte-identical files (in the order given), else the first problem."""
    problem = None
    for x in fs:
        pages, p = _sidecar(x["raw"], x, "ocr")
        if pages is not None:
            return pages, None
        problem = problem or p
    return None, problem


def _chars(pages: list[str]) -> int:
    return sum(len(re.sub(r"\s", "", p)) for p in pages)


def _extract(doc: dict) -> dict:
    """The document's pages as (text, text_source); a scan with no text layer takes its valid OCR sidecar."""
    files = sorted(doc["files"], key=lambda x: x["meeting_id"] != doc["meeting_id"])  # the owner's copy first
    f = files[0]
    out = {**doc, "error": None, "url_hint": f.get("url"), "sidecar_problem": None}
    if (converted := _converted(files)) is not None:
        return out | {"pages": [(_clean(t), "converted") for t in converted]}
    try:
        pages = extract_pages(f["abs"], f["format"])
    except Exception as exc:
        return out | {"pages": None, "error": f"text extraction failed: {exc}"}
    if f["format"] == "pdf" and _chars(pages) < MIN_TEXT_CHARS:
        ocr, problem = _ocr(files)
        if ocr is not None:
            return out | {"pages": [(_clean(t), "ocr") for t in ocr]}
        out["sidecar_problem"] = problem
    return out | {"pages": [(t, "text") for t in pages]}


# --- build --------------------------------------------------------------------------------------------------------

def build_index(raw: Path = RAW_ROOT, substrate: Path = SUBSTRATE, out: Path = INDEX_PATH, sources=tuple(SOURCES),
                workers: int = 8) -> dict:
    raw, out = Path(raw), Path(out)
    meetings, as_of = load_meetings(substrate, sources)
    files, docs = _classify(raw, sources, meetings)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        extracted = list(pool.map(_extract, docs))

    rows, covered = [], {}
    for doc in extracted:
        text_chars = _chars([t for t, _ in doc["pages"] or []])
        kinds = sorted({k for t, k in doc["pages"] or [] if t})
        text_source = kinds[0] if len(kinds) == 1 else None
        if doc["pages"] is None:
            disp, reason = "unreadable", doc["error"]
        elif text_chars < MIN_TEXT_CHARS:
            disp, reason = "no-text", f"no text layer ({text_chars} characters; a scanned image or empty)"
            if doc["sidecar_problem"]:
                reason += f"; OCR sidecar ignored: {doc['sidecar_problem']}"
        else:
            disp = "shared-indexed" if doc["shared"] else "indexed"
            reason = {"ocr": "scanned; text by OCR (minutes-ocr sidecar, validated)",
                      "converted": "legacy Word .doc; text converted by textutil (minutes-converted sidecar, "
                                   "validated)"}.get(text_source)
        for f in doc["files"]:
            f.update(disposition=disp, text_source=text_source if disp in INDEXED else None,
                     reason="; ".join(r for r in (f["reason"], reason) if r) or None)
            if disp == "no-text" and doc["sidecar_problem"]:
                f["sidecar_problem"] = f"no text layer; OCR sidecar ignored: {doc['sidecar_problem']}"
        if disp not in INDEXED:
            continue
        mid = doc["meeting_id"]
        m = meetings[mid]
        covered[mid] = True
        body = normalize_body(m["source"], m["title"])[0]
        url = m["url"] or normalize_url(doc.get("url_hint"))
        sha = next(f["sha256"] for f in doc["files"])
        rows += [(mid, m["source"], body, m["date"], n, text, url, sha, kind)
                 for n, (text, kind) in enumerate(doc["pages"], start=1) if text]
    rows.sort(key=lambda r: (r[0], r[4]))

    coverage = _coverage(meetings, files, covered)
    _write(out, rows, coverage, files, as_of)
    return _report(files, coverage, meetings, sources, as_of)


def _coverage(meetings: dict, files: list[dict], covered: dict) -> list[tuple]:
    own: dict[str, set[str]] = {}
    for f in files:
        if f["meeting_id"] in meetings:
            own.setdefault(f["meeting_id"], set()).add(f["disposition"])
    out = []
    for mid, m in sorted(meetings.items()):
        if not m["url"] and mid not in covered:
            continue
        d = own.get(mid, set())
        state = ("indexed" if mid in covered else "quarantined" if "quarantined-ambiguous" in d
                 else "no-text" if d & {"no-text", "unreadable"} else "unmapped" if "unmapped" in d else "not cached")
        out.append((mid, m["source"], normalize_body(m["source"], m["title"])[0], m["date"], m["url"], state))
    return out


def _write(out: Path, rows: list[tuple], coverage: list[tuple], files: list[dict], as_of: str) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{out.name}.", suffix=".building", dir=out.parent)
    os.close(fd)
    tmp = Path(name)
    try:
        _fill(tmp, rows, coverage, files, as_of)
        os.chmod(tmp, 0o600)
        os.replace(tmp, out)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _fill(tmp: Path, rows: list[tuple], coverage: list[tuple], files: list[dict], as_of: str) -> None:
    db = sqlite3.connect(tmp)
    try:
        db.executescript(SCHEMA)
        db.executemany("INSERT INTO meta VALUES (?, ?)", [("schema", "minutes-text-v2"),
                                                          ("substrate_as_of_date", as_of)])
        db.executemany("INSERT INTO pages (meeting_id, source, body, meeting_date, page, text, official_url, "
                       "source_sha256, text_source) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
        db.execute("INSERT INTO pages_fts (pages_fts) VALUES ('rebuild')")
        db.executemany("INSERT INTO coverage VALUES (?, ?, ?, ?, ?, ?)", coverage)
        db.executemany("INSERT INTO dispositions VALUES (?, ?, ?, ?, ?, ?, ?)",
                       [(f["path"], f["source"], f["meeting_id"], f["sha256"], f["disposition"], f["reason"],
                         f.get("text_source")) for f in files])
        db.commit()
        db.execute("VACUUM")
    finally:
        db.close()


# --- report -------------------------------------------------------------------------------------------------------

def _report(files: list[dict], coverage: list[tuple], meetings: dict, sources, as_of: str) -> dict:
    per = {}
    for s in sources:
        fs = [f for f in files if f["source"] == s]
        counts = {d: sum(1 for f in fs if f["disposition"] == d) for d in DISPOSITIONS}
        ok = counts["indexed"] + counts["shared-indexed"]
        per[s] = {"files": len(fs), "dispositions": counts, "indexed_share": round(ok / len(fs), 4) if fs else 0.0}
    unknown: dict[tuple, int] = {}
    for mid, m in meetings.items():
        if not normalize_body(m["source"], m["title"])[1]:
            unknown[(m["source"], m["title"])] = unknown.get((m["source"], m["title"]), 0) + 1
    bodies: dict[str, dict] = {}
    for mid, source, body, date, url, state in coverage:
        b = bodies.setdefault(body, {"source": source, "first": date, "last": date,
                                     "states": {s: 0 for s in COVERAGE_STATES}})
        b["first"], b["last"] = min(b["first"], date), max(b["last"], date)
        b["states"][state] += 1
    return {
        "substrate_as_of_date": as_of,
        "sources": per,
        "shortfall": {s: v["indexed_share"] for s, v in per.items() if v["indexed_share"] < SHORTFALL_BELOW},
        "files": [{k: f.get(k) for k in ("path", "source", "meeting_id", "sha256", "disposition", "reason",
                                          "text_source")} for f in files],
        "sidecar_problems": [{"path": f["path"], "problem": f["sidecar_problem"].split("ignored: ", 1)[-1]
                              if f["sidecar_problem"].startswith("no text layer") else f["sidecar_problem"]}
                             for f in files if f.get("sidecar_problem")],
        "unknown_titles": [{"source": s, "title": t, "meetings": n} for (s, t), n in sorted(unknown.items())],
        "coverage": dict(sorted(bodies.items())),
    }


def render_report(r: dict) -> str:
    lines = [f"# Minutes text build report (substrate as of {r['substrate_as_of_date']})", "", "## Shortfall", ""]
    if r["shortfall"]:
        for s, share in r["shortfall"].items():
            missing = {d: n for d, n in r["sources"][s]["dispositions"].items() if d not in INDEXED and n}
            lines.append(f"- **{s}: {share:.1%} indexed** (below {SHORTFALL_BELOW:.0%}); not indexed: "
                         + ", ".join(f"{n} {d}" for d, n in missing.items())
                         + ". Every such file is listed below with its reason.")
    else:
        lines.append(f"None: every source has at least {SHORTFALL_BELOW:.0%} of its files indexed.")
    lines += ["", "## Dispositions", "", "| source | files | " + " | ".join(DISPOSITIONS) + " | indexed share |",
              "|---" * (len(DISPOSITIONS) + 3) + "|"]
    for s, v in r["sources"].items():
        lines.append(f"| {s} | {v['files']} | " + " | ".join(str(v["dispositions"][d]) for d in DISPOSITIONS)
                     + f" | {v['indexed_share']:.1%} |")
    total = sum(v["files"] for v in r["sources"].values())
    lines += ["", f"Total files enumerated: {total}.", "", "## Files not indexed", ""]
    for f in r["files"]:
        if f["disposition"] not in INDEXED:
            lines.append(f"- `{f['path']}` — {f['disposition']}: {f['reason']}")
    lines += ["", "## Sidecars ignored", ""]
    lines += [f"- `{p['path']}` — OCR sidecar ignored: {p['problem']}" for p in r.get("sidecar_problems", [])] \
        or ["None."]
    lines += ["", "## Shared documents", ""]
    lines += [f"- `{f['path']}` — {f['reason']}" for f in r["files"] if f["disposition"] == "shared-indexed"] or ["None."]
    lines += ["", "## Unknown meeting titles (passed through as the body)", ""]
    lines += [f"- {u['source']}: \"{u['title']}\" ({u['meetings']} meetings)" for u in r["unknown_titles"]] or ["None."]
    lines += ["", "## Coverage (meetings with a minutes link)", "",
              "| body | dates | " + " | ".join(COVERAGE_STATES) + " |", "|---" * (len(COVERAGE_STATES) + 2) + "|"]
    for body, b in r["coverage"].items():
        lines.append(f"| {body} | {b['first']} – {b['last']} | "
                     + " | ".join(str(b["states"][s]) for s in COVERAGE_STATES) + " |")
    return "\n".join(lines) + "\n"


# --- search (operator CLI; the app has its own reader) -----------------------------------------------------------

def fts_query(q: str) -> str | None:
    """Every word (or "quoted phrase") must appear on the page; FTS syntax in the input is never interpreted."""
    terms = [p or w for p, w in re.findall(r'"([^"]+)"|(\S+)', q)]
    terms = [re.sub(r"[^\w\s'-]", " ", t).strip() for t in terms]
    return " AND ".join('"' + t.replace('"', "") + '"' for t in terms if t) or None


def search(index: Path, q: str, limit: int = 200) -> list[dict]:
    match = fts_query(q)
    if match is None:
        return []
    db = sqlite3.connect(f"file:{Path(index)}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        rows = db.execute(
            "SELECT p.meeting_id, p.body, p.meeting_date, p.page, p.official_url, "
            "snippet(pages_fts, 0, '[', ']', '…', 24) AS snippet FROM pages_fts JOIN pages p ON p.id = pages_fts.rowid "
            "WHERE pages_fts MATCH ? ORDER BY p.meeting_date DESC, p.meeting_id, p.page LIMIT ?", (match, limit))
        return [dict(r) for r in rows]
    finally:
        db.close()


# --- San Anselmo: staged documents enter the raw store ------------------------------------------------------------

def import_san_anselmo(staging: Path = SA_STAGING, raw: Path = RAW_ROOT) -> dict:
    """Copy the staged San Anselmo minutes (never refetched) to <raw>/san-anselmo-town-council/minutes/
    <meeting_id>.<ext>, with minutes-manifest.json (meeting, url, fetch date, sha256). Idempotent; never overwrites
    different bytes."""
    staging, raw = Path(staging), Path(raw)
    entries = json.loads((staging / "index.json").read_text())
    if len({e["meeting"] for e in entries}) != len(entries):
        raise IndexBuildError("index.json lists a meeting twice")
    dest_dir = raw / SA / "minutes"
    dest_dir.mkdir(parents=True, exist_ok=True)
    docs = []
    for e in sorted(entries, key=lambda e: e["meeting"]):
        if not SOURCE_MAP[SA].file_meeting_id(e["meeting"] + ".pdf"):
            raise IndexBuildError(f"not a San Anselmo meeting id: {e['meeting']}")
        src = staging / "cache" / e["file"]
        data = src.read_bytes()
        dest = dest_dir / f"{e['meeting']}{src.suffix.lower()}"
        if dest.exists() and dest.read_bytes() != data:
            raise IndexBuildError(f"{dest} exists and differs from {src}")
        if not dest.exists():
            dest.write_bytes(data)
        fetched = dt.datetime.fromtimestamp(src.stat().st_mtime).date().isoformat()
        docs.append({"meeting_id": e["meeting"], "file": dest.name, "url": e["url"], "fetch_date": fetched,
                     "fetch_date_basis": "staged file modification time", "sha256": _sha(data),
                     "staged_file": e["file"]})
    manifest = {"source": SA, "from": "open-marin-staging/san-anselmo-minutes (fetched 2026-11-14; not refetched)",
                "documents": docs}
    (raw / SA / MANIFEST).write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n")
    return manifest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--raw", type=Path, default=RAW_ROOT)
    b.add_argument("--substrate", type=Path, default=SUBSTRATE)
    b.add_argument("--out", type=Path, default=INDEX_PATH)
    b.add_argument("--report-dir", type=Path, default=REPORT_DIR)
    i = sub.add_parser("import-san-anselmo")
    i.add_argument("--staging", type=Path, default=SA_STAGING)
    i.add_argument("--raw", type=Path, default=RAW_ROOT)
    s = sub.add_parser("search")
    s.add_argument("query")
    s.add_argument("--index", type=Path, default=INDEX_PATH)
    args = ap.parse_args(argv)
    if args.cmd == "import-san-anselmo":
        print(f"copied/verified {len(import_san_anselmo(args.staging, args.raw)['documents'])} documents")
    elif args.cmd == "search":
        for h in search(args.index, args.query):
            print(f"{h['meeting_date']} {h['body']} p{h['page']}: {h['snippet']}")
    else:
        report = build_index(args.raw, args.substrate, args.out)
        args.report_dir.mkdir(parents=True, exist_ok=True)
        (args.report_dir / "build-report.json").write_text(json.dumps(report, indent=1, sort_keys=True) + "\n")
        (args.report_dir / "build-report.md").write_text(render_report(report))
        for src, v in report["sources"].items():
            print(f"{src}: {v['files']} files, {v['indexed_share']:.1%} indexed")
        print(f"wrote {args.out} and {args.report_dir / 'build-report.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
