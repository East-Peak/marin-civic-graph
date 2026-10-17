#!/usr/bin/env python3
"""Votes refresh: turn hand-saved Novato and Board of Supervisors minutes into a reviewed, apply-ready CAST_VOTE batch.

Part A + B2 were a one-time backfill (minutes windows Novato ..2026-03-10, Board ..2026-03-20). This keeps them
current as a BACKLOG, not an advancing window: every known in-scope Meeting after those windows is tracked by state,
any pending meeting may be taken whatever its date, and a meeting's minutes are processed once — a second, different
file for a slot that was ever claimed is held (`document_version_conflict`), never re-parsed.

Nothing here fetches: both bodies' minutes live on *.granicus.com, whose robots.txt disallows every agent. Stuart
saves each file by hand to `data/raw/manual/<YYYY-MM-DD>/minutes/<body>/<meeting_id>.<pdf|docx|html>`; a file is
accepted only with heading evidence for its meeting (jurisdiction, date, session).

Durable state under REFRESH_ROOT (~/open-marin-staging/votes-refresh):
  registry.jsonl  append-only, written under `.lock`: batch claims (meeting → slot → sha256), slot identities,
                  releases, conflicts, roster holds and their resolutions
  applied.jsonl   the applied journal: only after a verified apply (post-apply MATCH)
  history.jsonl   one line per todo/prepare run: the backlog per body (excluded from determinism)

    python scripts/votes_refresh.py init                       # verify the reviewed roster once, pin it
    python scripts/votes_refresh.py todo --export <export_live_graph --backup dir>
    python scripts/votes_refresh.py prepare --export <dir> [--batch N --reviewer-holds F]
    python scripts/votes_refresh.py approve --batch N --review R --bake-check B
    python scripts/votes_refresh.py status --export <dir>    # also: abandon, resolve, check
The runbook is docs/runbooks/votes-refresh.md.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from votes_inventory import BODIES, classify_meeting, sniff_format

REFRESH_ROOT = Path.home() / "open-marin-staging" / "votes-refresh"
REPO_ROOT = Path(__file__).resolve().parent.parent
MANUAL_DIR = Path("data") / "raw" / "manual"
RUNS_DIR = Path("data") / "ingest-runs"
WINDOW_END = {"novato-city-council": "2026-03-10", "marin-county-bos": "2026-03-20"}  # Part A's minutes windows
BODY_ORG = {"novato-city-council": "org-novato-city-council",
            "marin-county-bos": "org-marin-county-board-of-supervisors"}
BODY_HOST = {"novato-city-council": "novato.granicus.com", "marin-county-bos": "marin.granicus.com"}
EXTENSIONS = ("pdf", "docx", "html")
SLOT = "minutes"
LISTING_STALE_DAYS = 14


class RefreshError(Exception):
    pass


def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _jsonl(path: Path):
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


# ---------------------------------------------------------------------------------------------------------------
# Minutes URLs
# ---------------------------------------------------------------------------------------------------------------

def minutes_url(props: dict, body: str) -> tuple[str | None, str | None]:
    """(the URL Stuart opens to save the minutes, or None + why). `preferred_public_url` wins; otherwise the
    record's `source_url`, normalized (`//` → https) and accepted only as the body's own MinutesViewer page."""
    if props.get("preferred_public_url"):
        return props["preferred_public_url"], None
    url = props.get("source_url")
    if not url:
        return None, "no_minutes_link"
    if url.startswith("//"):
        url = "https:" + url
    parts = urlsplit(url)
    if parts.scheme != "https":
        return None, "source_url_not_https"
    if parts.hostname != BODY_HOST[body]:
        return None, "source_url_wrong_host"
    if parts.path != "/MinutesViewer.php":
        return None, "source_url_not_minutes_viewer"
    query = parse_qs(parts.query, keep_blank_values=True)
    clip, doc = query.get("clip_id", []), query.get("doc_id", [])
    if len(clip) != 1 or not clip[0].isdigit() or len(doc) != 1 or not doc[0]:
        return None, "source_url_bad_query"
    return url, None


# ---------------------------------------------------------------------------------------------------------------
# Known meetings (from a frozen export; nothing connects)
# ---------------------------------------------------------------------------------------------------------------

def known_meetings(export: Path) -> dict[str, list[dict]]:
    """Per body, every in-scope Meeting dated after Part A's window, with its minutes record and URL."""
    export = Path(export)
    meetings, records = {}, {}
    for n in _jsonl(export / "nodes.jsonl"):
        p = n.get("properties") or {}
        if "Meeting" in n["labels"]:
            body = next((b for b in BODIES if n["id"].startswith(f"meeting-{b}-")), None)
            if body and (p.get("meeting_date") or "") > WINDOW_END[body] \
                    and classify_meeting(body, p.get("title") or "") not in BODIES[body]["out_of_scope_classes"]:
                meetings[n["id"]] = {"meeting_id": n["id"], "body": body, "date": p["meeting_date"],
                                     "title": p.get("title") or "", "clip_id": p.get("clip_id")}
        elif "Record" in n["labels"] and p.get("record_type") == "meeting_minutes":
            records[n["id"]] = p
    recs: dict[str, list[str]] = {}
    for e in _jsonl(export / "edges.jsonl"):
        if e["type"] == "EVIDENCED_BY" and e["start_id"] in meetings and e["end_id"] in records:
            recs.setdefault(e["start_id"], []).append(e["end_id"])
    out = {b: [] for b in sorted(BODIES)}
    for mid, m in sorted(meetings.items(), key=lambda kv: (kv[1]["date"], kv[0])):
        rids = sorted(recs.get(mid, []))
        url, why = (None, "no_minutes_record") if not rids else \
            (None, "several_minutes_records") if len(rids) > 1 else minutes_url(records[rids[0]], m["body"])
        out[m["body"]].append({**m, "record_id": rids[0] if len(rids) == 1 else None, "url": url, "url_reason": why})
    return out


# ---------------------------------------------------------------------------------------------------------------
# Heading evidence
# ---------------------------------------------------------------------------------------------------------------

_MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
           "november", "december")
_DATE_RE = re.compile(r"\b(" + "|".join(_MONTHS) + r")\s+(\d{1,2}),?\s+(\d{4})\b", re.I)
_HEADING_END = re.compile(r"(?m)^\s*(?:[A-Z]|\d{1,2})\.\s|\bcall\s+to\s+order\b|\bconvene\b|\broll\s+call\b|"
                          r"\bpresent\s*:", re.I)
HEADING_MAX = 600
_JURISDICTION = {"novato-city-council": (r"\bnovato\b", r"\bcity\s+council\b"),
                 "marin-county-bos": (r"\bmarin\b", r"\bboard\s+of\s+supervisors\b")}
_OTHER_JURISDICTIONS = {  # a heading naming one of these is another body's minutes (or a joint meeting): pending
    "novato-city-council": ("san rafael", "mill valley", "sausalito", "tiburon", "belvedere", "corte madera",
                            "larkspur", "san anselmo", "fairfax", "ross"),
    "marin-county-bos": ("sonoma", "napa", "san francisco", "contra costa", "solano", "alameda", "san mateo"),
}
_CLOSED = re.compile(r"\bclosed\s+(?:session|meeting)\b", re.I)
_SPECIAL = re.compile(r"\bspecial\b", re.I)
_REGULAR = re.compile(r"\bregular\s+meeting\b|\bregular\b", re.I)
_PLEDGE = re.compile(r"\bpledge\s+of\s+allegiance\b", re.I)
_CLIP_RE = re.compile(rb"clip_id=(\d+)")


def title_session(body: str, title: str) -> str | None:
    """The session a listing title names. Novato's titles are typed (a plain "City Council" is the regular
    meeting); the Board's are not ("Board of Supervisors 2030") unless they say closed or special."""
    t = title.lower()
    if "closed" in t:
        return "closed"
    if "special" in t:
        return "special"
    return "regular" if body == "novato-city-council" else None


def heading_of(text: str) -> tuple[str | None, str]:
    """(the heading: text before the first structural marker, ≤ HEADING_MAX chars — or None when no marker is
    found in that span; the first item line, where an opening ceremony is named)."""
    m = _HEADING_END.search(text[:HEADING_MAX + 200])
    if m is None or m.start() > HEADING_MAX:
        return None, ""
    rest = text[m.start():].lstrip()
    return text[:m.start()], rest.split("\n", 1)[0]


def heading_session(heading: str, first_line: str) -> tuple[str | None, str | None]:
    closed, special = bool(_CLOSED.search(heading)), bool(_SPECIAL.search(heading))
    regular = bool(_REGULAR.search(heading))
    pledge = bool(_PLEDGE.search(heading + " " + first_line))
    if (closed and (regular or pledge)) or (special and regular):
        return None, "heading_combined_sessions"
    if closed:
        return "closed", None
    if special:
        return "special", None
    if regular or pledge:
        return "regular", None
    return None, "heading_session_unproven"


def check_heading(text: str, raw: bytes, meeting: dict, siblings: list[dict]) -> str | None:
    """None when the saved file's own heading proves it is this meeting's minutes; else the reason it does not.
    Only the heading is read: "approve the minutes of <date>" further down is never evidence."""
    body = meeting["body"]
    clips = sorted(set(_CLIP_RE.findall(raw)))
    if clips and (len(clips) > 1 or clips[0].decode() != str(meeting.get("clip_id"))):
        return f"clip_id_mismatch:{','.join(c.decode() for c in clips)}"
    heading, first_line = heading_of(text)
    if heading is None:
        return "heading_unbounded"
    flat = " ".join(heading.split())
    if not all(re.search(p, flat, re.I) for p in _JURISDICTION[body]):
        return "heading_jurisdiction_missing"
    other = next((o for o in _OTHER_JURISDICTIONS[body] if re.search(rf"\b{o}\b", flat, re.I)), None)
    if other:
        return f"heading_other_jurisdiction:{other}"
    dates = sorted({f"{int(y):04d}-{_MONTHS.index(mo.lower()) + 1:02d}-{int(d):02d}"
                    for mo, d, y in _DATE_RE.findall(flat)})
    if not dates:
        return "heading_date_missing"
    if len(dates) > 1:
        return "heading_date_ambiguous"
    if dates[0] != meeting["date"]:
        return f"heading_date_mismatch:{dates[0]}"
    have, why = heading_session(flat, first_line)
    if why:
        return why
    want = title_session(body, meeting["title"])
    if want is None:  # an untyped title: only the file's own primary-source id proves which session it is
        return None if clips else "session_identity_unproven"
    return None if have == want else f"heading_session_mismatch:{have}≠{want}"


# ---------------------------------------------------------------------------------------------------------------
# Saved files
# ---------------------------------------------------------------------------------------------------------------

def _is_date(name: str) -> bool:
    try:
        return dt.date.fromisoformat(name).isoformat() == name
    except ValueError:
        return False


def saved_files(repo: Path, body: str, meeting_id: str) -> list[dict]:
    """Every saved file for this meeting, oldest save first: {path (repo-relative), saved_on, ext, sha256}."""
    base = Path(repo) / MANUAL_DIR
    out = []
    for ext in EXTENSIONS:
        for p in base.glob(f"*/minutes/{body}/{meeting_id}.{ext}"):
            if _is_date(p.parent.parent.parent.name) and p.is_file():
                out.append({"path": p.relative_to(repo).as_posix(), "saved_on": p.parent.parent.parent.name,
                            "ext": ext, "sha256": _sha_bytes(p.read_bytes())})
    return sorted(out, key=lambda f: (f["saved_on"], f["ext"]))


def evaluate_file(repo: Path, f: dict, meeting: dict, siblings: list[dict]) -> str | None:
    from votes_text import canonical_text

    path = Path(repo) / f["path"]
    raw = path.read_bytes()
    fmt = sniff_format(raw) or "unknown"
    if fmt != f["ext"]:
        return f"format_mismatch:{fmt}≠{f['ext']}"
    try:
        text = canonical_text(path, fmt).text
    except Exception as exc:  # an unreadable file stays pending with its reason
        return f"unreadable:{type(exc).__name__}"
    return check_heading(text, raw, meeting, siblings)


# ---------------------------------------------------------------------------------------------------------------
# Durable records
# ---------------------------------------------------------------------------------------------------------------

class Registry:
    """The append-only preparation registry. Reads never repair; appends happen only under the exclusive lock,
    which first quarantines an unterminated final line (an interrupted write) so it can never be glued to the
    next record."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.path = self.root / "registry.jsonl"
        self._locked = False

    _held: set[str] = set()  # roots this process has locked: flock is not re-entrant, so a nested lock would hang

    @contextlib.contextmanager
    def locked(self, wait: bool = True):
        self.root.mkdir(parents=True, exist_ok=True)
        key = str(self.root.resolve())
        if key in Registry._held:
            raise RefreshError(f"{self.root}: the refresh lock is already held by this process (pass its Registry)")
        fh = open(self.root / ".lock", "a+")
        try:
            try:
                fcntl.flock(fh, fcntl.LOCK_EX | (0 if wait else fcntl.LOCK_NB))
            except BlockingIOError:
                raise RefreshError(f"{self.root} is locked by another refresh process") from None
            self._locked = True
            Registry._held.add(key)
            self._repair_tail()
            yield self
        finally:
            if self._locked:
                Registry._held.discard(key)
            self._locked = False
            fh.close()

    def _repair_tail(self) -> None:
        if not self.path.is_file():
            return
        data = self.path.read_bytes()
        if not data or data.endswith(b"\n"):
            return
        cut = data.rfind(b"\n") + 1
        tail = data[cut:]
        (self.root / f"registry.tail-{_sha_bytes(tail)[:8]}.quarantine").write_bytes(tail)
        with open(self.path, "r+b") as fh:
            fh.truncate(cut)
            fh.flush()
            os.fsync(fh.fileno())
        _fsync_dir(self.root)

    def records(self) -> list[dict]:
        if not self.path.is_file():
            return []
        data = self.path.read_bytes()
        lines = data.split(b"\n")
        committed = lines[:-1]  # the last element is b"" or an unterminated (uncommitted) tail
        out = []
        for i, line in enumerate(committed, 1):
            if not line.strip():
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                raise RefreshError(f"{self.path}:{i} is corrupt; refusing to read the registry") from None
        return out

    def append(self, record: dict) -> None:
        if not self._locked:
            raise RefreshError("registry appends need the refresh lock")
        with open(self.path, "ab") as fh:
            fh.write((_canonical(record) + "\n").encode("utf-8"))
            fh.flush()
            os.fsync(fh.fileno())
        _fsync_dir(self.root)


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def journal(root: Path) -> list[dict]:
    path = Path(root) / "applied.jsonl"
    return list(_jsonl(path)) if path.is_file() else []


def slot_view(records: list[dict], applied: list[dict]) -> dict:
    """(meeting, slot) → {"sha256": the slot's permanent identity (its first claim's file), "owner": the batch that
    holds it now or None, "applied"}. Ownership replays in log order: a batch or claim takes, a release frees."""
    view: dict[tuple[str, str], dict] = {}

    def take(batch: str, c: dict) -> None:
        entry = view.setdefault((c["meeting_id"], c["slot"]), {"sha256": c["sha256"], "owner": None,
                                                               "applied": False})
        entry["owner"] = batch

    for r in records:
        if r["kind"] == "batch":
            for c in r["claims"]:
                take(r["batch"], c)
        elif r["kind"] == "claim":
            take(r["batch"], r)
        elif r["kind"] == "release":
            for entry in view.values():
                if entry["owner"] == r["batch"]:
                    entry["owner"] = None
    for a in applied:
        view.setdefault((a["meeting_id"], a["slot"]), {"sha256": a["sha256"], "owner": None})["applied"] = True
    return view


def current_revisions(records: list[dict]) -> dict[str, dict]:
    """batch → {"rev", "manifest_sha256", "bodies"} of its current revision (the last batch/revision line)."""
    out: dict[str, dict] = {}
    for r in records:
        if r["kind"] == "batch":
            out[r["batch"]] = {"rev": r.get("rev", 1), "manifest_sha256": r["manifest_sha256"],
                               "bodies": list(r.get("bodies", []))}
        elif r["kind"] == "revision" and r["batch"] in out:
            out[r["batch"]].update(rev=r["rev"], manifest_sha256=r["manifest_sha256"])
    return out


def manifest_path(refresh: Path, batch: str, rev: int) -> Path:
    return Path(refresh) / "batches" / batch / f"rev-{rev}" / "manifest.json"


def batch_integrity(refresh: Path, records: list[dict]) -> dict[str, str]:
    """batch → what is wrong with its committed metadata (the current revision's manifest missing or altered)."""
    problems = {}
    for batch, cur in sorted(current_revisions(records).items()):
        path = manifest_path(refresh, batch, cur["rev"])
        if not path.is_file():
            problems[batch] = f"manifest rev-{cur['rev']} missing"
        elif _sha_bytes(path.read_bytes()) != cur["manifest_sha256"]:
            problems[batch] = f"manifest rev-{cur['rev']} altered"
    return problems


def blocked_bodies(refresh: Path, records: list[dict]) -> dict[str, list[str]]:
    """body → why no new batch may be prepared for it (damaged committed metadata; later: unresolved applies)."""
    revs = current_revisions(records)
    out: dict[str, list[str]] = {}
    for batch, why in batch_integrity(refresh, records).items():
        for body in revs[batch]["bodies"]:
            out.setdefault(body, []).append(f"{batch}: {why}")
    return out


def record_conflicts(reg: Registry, b: dict) -> int:
    """Under the lock: one `conflict` line per (meeting, slot, sha256) a saved file has against its slot."""
    seen = {(r["meeting_id"], r["slot"], r["sha256"]) for r in reg.records() if r["kind"] == "conflict"}
    n = 0
    for rows in b.values():
        for row in rows:
            for c in row["conflicts"]:
                key = (row["meeting_id"], row["slot"], c["sha256"])
                if key not in seen:
                    reg.append({"kind": "conflict", "meeting_id": key[0], "slot": key[1], "sha256": key[2],
                                "path": c["path"], "held_against": c["held_against"]})
                    seen.add(key)
                    n += 1
    return n


# ---------------------------------------------------------------------------------------------------------------
# The backlog
# ---------------------------------------------------------------------------------------------------------------

STATES = ("applied", "prepared", "held", "file_saved", "awaiting_file", "no_minutes_record")


def backlog(export: Path, repo: Path, refresh: Path, today: str | None = None) -> dict[str, list[dict]]:
    """Per body, every known meeting with its state (first that holds wins): applied (journal) · prepared (a live
    batch owns the slot) · held (a saved file conflicts with the slot's identity) · file_saved (an accepted file) ·
    awaiting_file (a minutes URL, no accepted file) · no_minutes_record (nothing to open)."""
    today = today or dt.date.today().isoformat()
    meetings = known_meetings(export)
    view = slot_view(Registry(refresh).records(), journal(refresh))
    out = {}
    for body, rows in meetings.items():
        by_date: dict[str, list[dict]] = {}
        for m in rows:
            by_date.setdefault(m["date"], []).append(m)
        out[body] = []
        for m in rows:
            siblings = [s for s in by_date[m["date"]] if s["meeting_id"] != m["meeting_id"]]
            files = saved_files(repo, body, m["meeting_id"])
            slot = view.get((m["meeting_id"], SLOT))
            conflicts = [{"path": f["path"], "sha256": f["sha256"], "reason": "document_version_conflict",
                          "held_against": slot["sha256"]} for f in files if slot and f["sha256"] != slot["sha256"]]
            row = {**m, "slot": SLOT, "files": files, "conflicts": conflicts, "file": None,
                   "target": f"{MANUAL_DIR.as_posix()}/{today}/minutes/{body}/{m['meeting_id']}."
                             # an untyped title is proven only by the MinutesViewer page's own clip_id
                             + ("html" if title_session(body, m["title"]) is None else "<pdf|docx|html>")}
            # a slot that was ever claimed may only ever take its first file again (after a release)
            usable = [f for f in files if not slot or f["sha256"] == slot["sha256"]]
            if usable and not (slot and (slot["applied"] or slot.get("owner"))):
                newest = [f for f in usable if f["saved_on"] == usable[-1]["saved_on"]]
                if len(newest) > 1:
                    row["file"] = {**newest[0], "reason": "several_files_saved_together"}
                else:
                    row["file"] = {**newest[0], "reason": evaluate_file(repo, newest[0], m, siblings)}
            if slot and slot["applied"]:
                row["state"] = "applied"
            elif slot and slot.get("owner"):
                row["state"] = "prepared"
            elif row["file"] and row["file"]["reason"] is None:
                row["state"] = "file_saved"
            elif conflicts:
                row["state"] = "held"
            elif m["url"] or row["file"]:
                row["state"] = "awaiting_file"
            else:
                row["state"] = "no_minutes_record"
            out[body].append(row)
    return out


# ---------------------------------------------------------------------------------------------------------------
# Listing freshness
# ---------------------------------------------------------------------------------------------------------------

def listing_freshness(repo: Path, today: str) -> dict[str, dict]:
    """Per body: the newest LOADED listing capture (a run that loaded the source, with its capture file) and the
    newest run's saved-page outcome. Older than LISTING_STALE_DAYS is a warning, never a failure."""
    runs = sorted(p.parent.name for p in (Path(repo) / RUNS_DIR).glob("*/state.json"))
    out = {}
    for body in sorted(BODIES):
        capture, saved = None, None
        for run in reversed(runs):
            state = json.loads((Path(repo) / RUNS_DIR / run / "state.json").read_text(encoding="utf-8"))
            if saved is None and run == runs[-1]:
                saved = ((state.get("saved_pages") or {}).get(body) or {}).get("outcome")
            src = (state.get("sources") or {}).get(body) or {}
            if body in (state.get("loaded") or []) and src.get("capture"):
                capture = Path(src["capture"]["path"]).stem
                break
        age = (dt.date.fromisoformat(today) - dt.date.fromisoformat(capture)).days if capture else None
        out[body] = {"capture_date": capture, "age_days": age,
                     "stale": capture is None or age > LISTING_STALE_DAYS, "saved_page": saved}
    return out


def freshness_lines(fresh: dict) -> list[str]:
    lines = []
    for body, f in sorted(fresh.items()):
        if f["capture_date"] is None:
            lines.append(f"- **WARNING: listing stale** — {body}: no loaded listing capture; coverage of known "
                         "Meetings is unknown")
            continue
        warn = "**WARNING: listing stale** — " if f["stale"] else ""
        saved = f"; newest saved-page outcome: {f['saved_page']}" if f["saved_page"] else ""
        lines.append(f"- {warn}{body}: coverage of known Meetings as of {f['capture_date']} "
                     f"(listing {f['age_days']} days old{saved})")
    return lines


# ---------------------------------------------------------------------------------------------------------------
# todo / history / digest
# ---------------------------------------------------------------------------------------------------------------

def _counts(rows: list[dict]) -> dict[str, int]:
    return {s: sum(1 for r in rows if r["state"] == s) for s in STATES}


def todo_items(b: dict) -> list[dict]:
    return [{"body": body, "meeting_id": r["meeting_id"], "date": r["date"], "title": r["title"], "url": r["url"],
             "target": r["target"], "reason": (r["file"] or {}).get("reason")}
            for body, rows in sorted(b.items()) for r in rows if r["state"] == "awaiting_file" and r["url"]]


def append_history(refresh: Path, entry: dict) -> None:
    with open(Path(refresh) / "history.jsonl", "a", encoding="utf-8") as fh:
        fh.write(_canonical(entry) + "\n")


def other_rows(b: dict) -> list[dict]:
    """Every meeting the to-do list does not ask Stuart to save, with what is known about it."""
    return [{"body": body, "meeting_id": r["meeting_id"], "date": r["date"], "state": r["state"],
             "url_reason": r["url_reason"], "file": r["file"], "conflicts": r["conflicts"]}
            for body, rows in sorted(b.items()) for r in rows if not (r["state"] == "awaiting_file" and r["url"])]


def _other_lines(rows: list[dict]) -> list[str]:
    other = [r for r in rows if not (r["state"] == "awaiting_file" and r["url"])]
    if not other:
        return []
    lines = ["", "Not on the list:"]
    for r in other:
        lines.append(f"- {r['date']} `{r['meeting_id']}` — {r['state']}"
                     + (f" ({r['url_reason']})" if r["state"] == "no_minutes_record" and r["url_reason"] != r["state"]
                        else "")
                     + (f"; saved file not accepted: {r['file']['reason']}" if r["file"] and r["file"]["reason"] else ""))
        lines += [f"  - document_version_conflict: `{c['path']}` (sha256 {c['sha256'][:12]}…) differs from the "
                  f"slot's file ({c['held_against'][:12]}…); it is never parsed" for c in r["conflicts"]]
    return lines


def write_todo(export: Path, repo: Path, refresh: Path, today: str | None = None, reg: Registry | None = None) -> dict:
    """`reg`: a Registry whose lock the caller already holds (the lock is not re-entrant)."""
    today = today or dt.date.today().isoformat()
    refresh = Path(refresh)
    b = backlog(export, repo, refresh, today=today)
    if reg is not None:
        record_conflicts(reg, b)
        records = reg.records()
    else:
        reg = Registry(refresh)
        with reg.locked():
            record_conflicts(reg, b)
            records = reg.records()
    blocked = blocked_bodies(refresh, records)
    fresh = listing_freshness(repo, today)
    items = todo_items(b)
    pending = [r for rows in b.values() for r in rows if r["state"] not in ("applied", "prepared")]
    state = "NOTHING_ELIGIBLE" if not pending else \
        "AWAITING_MINUTES" if not any(r["state"] == "file_saved" for r in pending) else "MINUTES_SAVED"
    lines = [f"# Votes refresh — minutes to save ({today})", "", *freshness_lines(fresh), "",
             f"State: **{state}**. Open each URL in your browser, save the minutes (PDF, or for the Board the "
             "MinutesViewer page as HTML) to the path shown. Nothing here is fetched by a script.", ""]
    for body, why in sorted(blocked.items()):
        lines += [f"**BLOCKED — {body}:** " + "; ".join(why), ""]
    for body in sorted(b):
        mine = [i for i in items if i["body"] == body]
        lines += [f"## {body} ({len(mine)} to save)", ""]
        for i in mine:
            lines += [f"- {i['date']} — {i['title']} (`{i['meeting_id']}`)", f"  {i['url']}", f"  → `{i['target']}`"]
            if i["reason"]:
                lines.append(f"  saved file not accepted: {i['reason']}")
        lines += _other_lines(b[body])
        lines.append("")
    (refresh / "todo.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (refresh / "todo.json").write_text(json.dumps({"today": today, "state": state, "freshness": fresh,
                                                   "items": items, "other": other_rows(b), "blocked": blocked},
                                                  indent=1, sort_keys=True) + "\n")
    append_history(refresh, {"command": "todo", "today": today, "freshness": fresh,
                             "bodies": {body: {**_counts(rows), "meetings": [[r["meeting_id"], r["state"]]
                                                                             for r in rows]}
                                        for body, rows in sorted(b.items())}})
    return {"state": state, "items": len(items), "blocked": blocked}


def digest_snapshot(repo: Path, export: Path, refresh: Path, today: str | None = None) -> dict:
    """For the weekly digest: read-only (no history, no registry repair), never raises."""
    today = today or dt.date.today().isoformat()
    try:
        b = backlog(export, repo, refresh, today=today)
        return {"today": today, "freshness": listing_freshness(repo, today), "items": todo_items(b),
                "counts": {body: _counts(rows) for body, rows in sorted(b.items())}}
    except Exception as exc:  # the weekly run must never fail on this list
        return {"today": today, "error": f"{type(exc).__name__}: {exc}"}


def render_digest_section(snap: dict) -> list[str]:
    lines = ["## Votes minutes to save", ""]
    if snap.get("error"):
        return lines + [f"- unavailable: {snap['error']}", ""]
    lines += freshness_lines(snap["freshness"])
    lines += ["", f"{len(snap['items'])} minutes to save by hand (docs/runbooks/votes-refresh.md):", ""]
    lines += [f"- {i['date']} {i['body']} `{i['meeting_id']}`: {i['url']} → `{i['target']}`"
              + (f" (saved file not accepted: {i['reason']})" if i["reason"] else "") for i in snap["items"]]
    return lines + [""]


# ---------------------------------------------------------------------------------------------------------------
# Batches: prepare → (review, bake) → approve → Stuart's apply (votes_apply.py) → journal
# ---------------------------------------------------------------------------------------------------------------

LIVE_STATES = ("AWAITING_REVIEW", "AWAITING_APPLY", "ALL_HELD", "AWAITING_ROSTER_REVIEW")
UNRESOLVED_STATES = ("APPLY_IN_PROGRESS", "APPLY_UNVERIFIED")
REVISABLE = ("AWAITING_REVIEW", "AWAITING_APPLY", "ALL_HELD", "AWAITING_ROSTER_REVIEW", "ROLLED_BACK")
CODE_MODULES = ("votes_text", "votes_blocks", "votes_candidates", "votes_attendance", "votes_exceptions",
                "votes_validate", "votes_reconcile", "votes_ledger", "votes_bundle", "votes_persons",
                "votes_refresh_ledger", "votes_refresh_expected", "case_additive_plan")
SAMPLE_PER_BODY = 10
NOTABLE = ("no", "abstain", "recused")
MARKER = "refresh-batch.json"


def rev_dir(refresh: Path, batch: str, rev: int) -> Path:
    return Path(refresh) / "batches" / batch / f"rev-{rev}"


def _read_state(path: Path) -> str | None:
    """The revision's state, or None when its state.json is missing or unreadable (= unresolved for a committed
    batch: it can never be mistaken for a clean one)."""
    try:
        return json.loads((Path(path) / "state.json").read_text())["state"]
    except (OSError, ValueError, KeyError):
        return None


def batch_states(refresh: Path, records: list[dict]) -> dict[str, dict]:
    """batch → {rev, bodies, state, released, claims} for every committed batch."""
    released = set()
    for r in records:
        if r["kind"] == "release":
            released.add(r["batch"])
        elif r["kind"] in ("claim", "revision"):
            released.discard(r["batch"])  # a re-claim takes the batch back
    out = {}
    for batch, cur in current_revisions(records).items():
        claims = next(r["claims"] for r in records if r["kind"] == "batch" and r["batch"] == batch)
        out[batch] = {**cur, "state": _read_state(rev_dir(refresh, batch, cur["rev"])), "released": batch in released,
                      "claims": claims}
    return out


def blocked(refresh: Path, records: list[dict]) -> dict[str, list[str]]:
    """body → why no new batch may be prepared for it: damaged metadata, or an apply whose outcome is unresolved
    (APPLY_IN_PROGRESS / APPLY_UNVERIFIED / a missing or corrupt state)."""
    out = blocked_bodies(refresh, records)
    for batch, b in sorted(batch_states(refresh, records).items()):
        if b["state"] in UNRESOLVED_STATES or b["state"] is None:
            for body in b["bodies"]:
                out.setdefault(body, []).append(f"{batch}: apply outcome unresolved ({b['state'] or 'no readable state'}); "
                                                f"run `votes_refresh.py resolve --batch {batch}`")
    return out


def roster_holds(records: list[dict]) -> list[dict]:
    resolved = {r["hold_id"] for r in records if r["kind"] == "hold_resolved"}
    return [{**r["hold"], "resolved": r["hold"]["hold_id"] in resolved} for r in records if r["kind"] == "roster_hold"]


def _code_versions() -> dict[str, str]:
    here = Path(__file__).resolve().parent
    return {m: _sha_bytes((here / f"{m}.py").read_bytes()) for m in CODE_MODULES}


def _pdftotext() -> str:
    from votes_inventory import _pdftotext_version
    return _pdftotext_version()


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(_canonical(r) + "\n" for r in rows), encoding="utf-8")


def _publish(path: Path, data: bytes) -> None:
    from votes_refresh_ledger import _write_atomic
    _write_atomic(path, data)


def _read_jsonl(path: Path) -> list[dict]:
    return list(_jsonl(path)) if Path(path).is_file() else []


def _resolutions(refresh: Path, records: list[dict], reg: Registry) -> list[str]:
    """Record `<hold_id> dismiss: <why>` lines from roster-holds/resolutions.txt, each bound to the packet Stuart
    read (its sha256 must be the one recorded with the hold). Returns problems with lines that do not apply."""
    path = Path(refresh) / "roster-holds" / "resolutions.txt"
    if not path.is_file():
        return []
    holds = {r["hold"]["hold_id"]: r for r in records if r["kind"] == "roster_hold"}
    done = {r["hold_id"] for r in records if r["kind"] == "hold_resolved"}
    problems = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.fullmatch(r"(hold-[0-9a-f]{8})\s+dismiss:\s*(\S.*)", line)
        if not m:
            problems.append(f"resolutions.txt: `{line}` is not `<hold_id> dismiss: <why>`")
            continue
        hid, why = m.groups()
        if hid not in holds:
            problems.append(f"resolutions.txt: {hid} is not a recorded roster hold")
        elif hid not in done:
            packet = Path(refresh) / "roster-holds" / f"{hid}.md"
            if not packet.is_file() or _sha_bytes(packet.read_bytes()) != holds[hid]["packet_sha256"]:
                problems.append(f"resolutions.txt: {hid}'s packet changed since it was written; not applied")
                continue
            reg.append({"kind": "hold_resolved", "hold_id": hid, "note": why, "packet_sha256": holds[hid]["packet_sha256"]})
            done.add(hid)
    return problems


def sync_journal(refresh: Path, reg: Registry) -> list[str]:
    """Under the lock: journal every verified apply (APPLIED/PUBLISHED_VERIFIED under its own approval, post-apply
    export == planned candidate) once; release a batch whose apply rolled back. Never journals an unresolved one."""
    from case_additive_plan import fingerprint

    records = reg.records()
    journaled = {a["batch"] for a in journal(refresh)}
    done = []
    for batch, b in sorted(batch_states(refresh, records).items()):
        d = rev_dir(refresh, batch, b["rev"])
        if b["state"] == "ROLLED_BACK" and not b["released"]:
            reg.append({"kind": "release", "batch": batch, "reason": "rolled_back"})
            done.append(f"{batch}: released (rolled back)")
            continue
        if b["state"] not in ("APPLIED", "PUBLISHED_VERIFIED") or batch in journaled:
            continue
        st = json.loads((d / "state.json").read_text())
        if st.get("approval_sha256") != _sha_bytes((d / "plan" / "approval-inputs.json").read_bytes()):
            continue
        report = json.loads((d / "plan" / "plan-report.json").read_text())
        post = d / "apply" / "post-apply-export"
        if not post.is_dir() or fingerprint(post) != report["candidate_sha256"]:
            continue
        manifest = json.loads(manifest_path(refresh, batch, b["rev"]).read_text())
        attached = defaultdict_list((x["meeting_id"], x["event_id"]) for x in _read_jsonl(d / "bundle" / "dispositions.jsonl")
                                    if x["reason"] == "attached")
        with open(Path(refresh) / "applied.jsonl", "a", encoding="utf-8") as fh:
            for doc in manifest["documents"]:
                fh.write(_canonical({"batch": batch, "rev": b["rev"], "approval_sha256": st["approval_sha256"],
                                     "meeting_id": doc["meeting_id"], "slot": SLOT, "sha256": doc["sha256"],
                                     "extraction": {"pdftotext": manifest["pdftotext"],
                                                    "text_sha256": doc["text_sha256"]},
                                     "parser": manifest["code"], "event_ids": attached.get(doc["meeting_id"], [])})
                         + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        done.append(f"{batch}: journaled")
    return done


def defaultdict_list(pairs) -> dict[str, list]:
    out: dict[str, list] = {}
    for k, v in pairs:
        out.setdefault(k, []).append(v)
    return {k: sorted(v) for k, v in out.items()}


def _load_export(export: Path):
    nodes = list(_jsonl(Path(export) / "nodes.jsonl"))
    edges = list(_jsonl(Path(export) / "edges.jsonl"))
    return nodes, edges


def build_revision(refresh: Path, repo: Path, manifest: dict, out: Path, cfg: dict) -> dict:
    """Every artifact of one revision, a pure function of its manifest (documents and baseline re-verified by sha256,
    holds and reviewer holds from the manifest itself) and the pinned config. Nothing else is read."""
    import case_additive_plan as cap
    import votes_bundle
    import votes_refresh_ledger as rl
    from votes_apply import expected_edges

    base = Path(manifest["baseline"]["dir"])
    if cap.fingerprint(base) != manifest["baseline"]["sha256"]:
        raise RefreshError(f"the baseline export {base} is not the one this revision was prepared on")
    if manifest["config_sha256"] != cfg["config_sha256"]:
        raise RefreshError("the pinned roster/mapping config changed since this revision was prepared")
    nodes, edges = _load_export(base)
    docs = [{k: d[k] for k in ("body", "meeting_id", "date", "title", "record_id", "url", "path", "format", "sha256")}
            for d in manifest["documents"]]
    built = rl.build_batch(docs, repo, nodes, edges, cfg, holds=manifest["holds"],
                           reviewer_holds=manifest["reviewer_holds"])
    for d in manifest["documents"]:
        key = f"{d['meeting_id']}.{d['sha256'][:8]}"
        if _sha_bytes(built["texts"][key].encode("utf-8")) != d["text_sha256"]:
            raise RefreshError(f"{d['meeting_id']}: canonical text differs from the manifest's (pdftotext changed?)")
    led, bundle = built["ledger"], built["bundle"]
    if out.exists():
        import shutil
        shutil.rmtree(out)
    out.mkdir(parents=True)
    _write_jsonl(out / "ledger" / "events.jsonl", sorted(led["events"], key=lambda e: e["event_id"]))
    _write_jsonl(out / "ledger" / "candidates.jsonl", sorted(led["candidates"], key=lambda c: c["cand_id"]))
    _write_jsonl(out / "ledger" / "dispositions.jsonl", sorted(led["dispositions"], key=lambda c: c["cand_id"]))
    _write_jsonl(out / "ledger" / "documents.jsonl", sorted(led["documents"], key=lambda x: (x["meeting_id"],
                                                                                           x.get("doc_sha256") or "")))
    _write_jsonl(out / "ledger" / "reconciliation.jsonl", built["reconciliation"])
    _write_json(out / "ledger" / "problems.json", {"problems": sorted(led["problems"])})
    cap.write_export(out / "bundle", bundle["nodes"], bundle["edges"])
    _write_jsonl(out / "bundle" / "dispositions.jsonl", bundle["dispositions"])
    _write_jsonl(out / "bundle" / "repair.jsonl", bundle["repair"])
    _write_json(out / "bundle" / "accounting.json", {**built["bundle_accounting"], **{
        "matches_expected": built["accounting"]["matches_expected"]}})
    _write_json(out / "bundle" / "expected.json", built["expected"])
    _write_json(out / "bundle" / "candidate-accounting.json", built["accounting"])
    _write_json(out / "holds.json", {"new": built["new_holds"], "event_holds": built["event_holds"],
                                     "reviewer_holds": built["reviewer_holds"]})
    _write_json(out / "hints.json", built["hints"])
    result = {"attached": built["attached"], "new_holds": built["new_holds"], "accounting": built["accounting"],
              "dispositions": bundle["dispositions"]}
    if not built["attached"]:
        return result
    # the additive plan (votes-refresh profile), written with paths relative to the revision
    ops = cap.plan_additive(nodes, edges, bundle["nodes"], bundle["edges"], constraints=cap.PROFILES["votes-refresh"])
    cand_nodes, cand_edges = cap.apply_additive(nodes, edges, ops)
    problems = cap.verify_additive(cand_nodes, cand_edges, nodes, edges, bundle["nodes"], bundle["edges"])
    plan = out / "plan"
    cand = cap.write_export(plan / "candidate", cand_nodes, cand_edges)
    rest = cap.write_export(plan / "baseline-reexport", *cap.strip_additions(cand_nodes, cand_edges, ops))
    if rest != manifest["baseline"]["sha256"]:
        problems.append("the candidate minus the additions does not re-export as the baseline")
    report = {"baseline": {"dir": "manifest:baseline", "sha256": manifest["baseline"]["sha256"]},
              "case": {"dir": "bundle", "sha256": cap.fingerprint(out / "bundle")}, "candidate_sha256": cand,
              "baseline_reexport_sha256": rest, "baseline_reexport_identical": rest == manifest["baseline"]["sha256"],
              "summary": ops["summary"], "verification": problems, "profile": "votes-refresh"}
    (plan / "ops.json").write_text(json.dumps(ops, indent=1, sort_keys=True) + "\n")
    (plan / "plan-report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    (plan / "plan.md").write_text(cap._render(report, ops))
    (plan / "inverse.json").write_text(json.dumps({"statements": cap.inverse_statements(ops)}, indent=1,
                                                  sort_keys=True) + "\n")
    exp = expected_edges(ops)
    from export_live_graph import _stable_line
    (plan / "expected-edges.jsonl").write_text("".join(_stable_line(r) + "\n" for r in exp))
    _write_json(plan / "targets.json", {"targets": sorted({e["end_id"] for e in exp})})
    # the spot-check sheet
    events = {e["event_id"]: e for e in led["events"]}
    texts = {d["sha256"]: built["texts"][f"{d['meeting_id']}.{d['sha256'][:8]}"] for d in manifest["documents"]}
    sources = {d["sha256"]: d["path"] for d in manifest["documents"]}
    names = {n["id"]: n["properties"].get("name") for n in nodes if "Person" in n["labels"]}
    sel = spot_selection(bundle, seed=manifest["seed"])
    sheet = votes_bundle.render_samples(sel, bundle, events, texts, names, seed=manifest["seed"], sources=sources,
                                        bundle_fp=cap.fingerprint(out / "bundle"))
    (out / "spot-check.md").write_text(sheet.replace("# Votes B2 spot check", f"# Votes refresh {manifest['batch']} "
                                                     f"rev-{manifest['rev']} spot check", 1), encoding="utf-8")
    result["plan_problems"] = problems
    return result


def spot_selection(bundle: dict, *, seed: int) -> dict:
    """Per body: min(10, N) seeded random attached events, then every other attached event with a no / abstain /
    recused vote (uncapped)."""
    import random

    flagged = {e["properties"]["ledger_event_id"] for e in bundle["edges"]
               if e["type"] == "CAST_VOTE" and e["properties"]["vote"] in NOTABLE}
    out = {}
    for body in sorted({d["body"] for d in bundle["dispositions"]}):
        attached = sorted(d["event_id"] for d in bundle["dispositions"] if d["body"] == body and d["reason"] == "attached")
        if not attached:
            continue
        rng = random.Random(f"{seed}:{body}")
        picked = sorted(rng.sample(attached, min(SAMPLE_PER_BODY, len(attached))))
        out[body] = {"random": picked, "notable": [e for e in attached if e in flagged and e not in picked]}
    return out


def _manifest(refresh, repo, batch, rev, docs, export, cfg, holds, reviewer_holds) -> dict:
    import case_additive_plan as cap
    from votes_text import canonical_text

    documents = []
    for d in sorted(docs, key=lambda d: (d["body"], d["date"], d["meeting_id"])):
        text = canonical_text(Path(repo) / d["path"], d["format"]).text
        documents.append({**d, "text_sha256": _sha_bytes(text.encode("utf-8"))})
    m = {"schema": "votes-refresh-manifest-v1", "batch": batch, "rev": rev,
         "bodies": sorted({d["body"] for d in documents}), "documents": documents,
         "baseline": {"dir": str(Path(export).resolve()), "sha256": cap.fingerprint(Path(export))},
         "config_sha256": cfg["config_sha256"], "holds": sorted(holds, key=lambda h: h["hold_id"]),
         "reviewer_holds": sorted(reviewer_holds, key=lambda h: h["event_id"]), "code": _code_versions(),
         "pdftotext": _pdftotext()}
    m["seed"] = int(_sha_bytes(_canonical(m).encode())[:8], 16)
    return m


def _selected_docs(b: dict, skip_bodies: set[str]) -> list[dict]:
    out = []
    for body, rows in sorted(b.items()):
        if body in skip_bodies:
            continue
        for r in rows:
            if r["state"] == "file_saved":
                f = r["file"]
                out.append({"body": body, "meeting_id": r["meeting_id"], "date": r["date"], "title": r["title"],
                            "record_id": r["record_id"], "url": r["url"], "path": f["path"], "format": f["ext"],
                            "sha256": f["sha256"]})
    return out


def _finish_revision(refresh: Path, reg: Registry, batch: str, rev: int, result: dict) -> str:
    """Record new holds (+ packets) and the revision's state."""
    import votes_apply
    import votes_refresh_ledger as rl

    d = rev_dir(refresh, batch, rev)
    known = {r["hold"]["hold_id"] for r in reg.records() if r["kind"] == "roster_hold"}
    for h in result["new_holds"]:
        if h["hold_id"] in known:
            continue
        packet = (Path(refresh) / "roster-holds" / f"{h['hold_id']}.md")
        packet.parent.mkdir(parents=True, exist_ok=True)
        packet.write_text(rl.render_packet(h), encoding="utf-8")
        reg.append({"kind": "roster_hold", "batch": batch, "rev": rev, "hold": h,
                    "packet_sha256": _sha_bytes(packet.read_bytes())})
    (d / MARKER).write_text(json.dumps({"batch": batch, "rev": rev}, sort_keys=True) + "\n")
    if result["attached"]:
        state = "AWAITING_REVIEW"
    elif any(x["reason"] == "roster_hold" for x in result["dispositions"]) or result["new_holds"]:
        state = "AWAITING_ROSTER_REVIEW"
    else:
        state = "ALL_HELD"
    votes_apply.set_state(d, state, batch=batch, rev=rev)
    return state


def prepare(export: Path, repo: Path, refresh: Path, *, today: str | None = None, batch: str | None = None,
            reviewer_holds: Path | None = None) -> dict:
    """A new batch from every pending meeting with an accepted saved file (bodies blocked by an unresolved apply or
    damaged metadata are skipped), or — with `batch` — a new revision of that batch (same slots; --export rebases,
    --reviewer-holds adds the spot check's holds). Offline: reads files only."""
    import votes_refresh_ledger as rl

    refresh, today = Path(refresh), today or dt.date.today().isoformat()
    cfg = rl.load_config(refresh)
    reg = Registry(refresh)
    with reg.locked():
        sync_journal(refresh, reg)
        res_problems = _resolutions(refresh, reg.records(), reg)
        b = backlog(export, repo, refresh, today=today)
        record_conflicts(reg, b)
        records = reg.records()
        stop = blocked(refresh, records)
        holds = roster_holds(records)
        rh = json.loads(Path(reviewer_holds).read_text())["holds"] if reviewer_holds else []
        if batch is None:
            docs = _selected_docs(b, set(stop))
            if not docs:
                todo = write_todo(export, repo, refresh, today=today, reg=reg)
                waiting = any(r["state"] == "file_saved" for body in stop for r in b.get(body, []))
                return {"state": "BLOCKED" if waiting else todo["state"], "blocked": stop,
                        "resolution_problems": res_problems}
            n = 1 + max([int(x.split("-")[1]) for x in current_revisions(records)] or [0])
            batch, rev = f"batch-{n:03d}", 1
        else:
            states = batch_states(refresh, records)
            if batch not in states:
                raise RefreshError(f"{batch} is not a committed batch")
            st = states[batch]
            if st["state"] not in REVISABLE:
                raise RefreshError(f"{batch} is {st['state'] or 'without a readable state'}; it cannot be revised")
            if batch in batch_integrity(refresh, records):
                raise RefreshError(f"{batch}: {batch_integrity(refresh, records)[batch]}")
            view = slot_view(records, journal(refresh))
            for c in st["claims"]:
                owner = view[(c["meeting_id"], c["slot"])]
                if owner["applied"] or (owner.get("owner") not in (None, batch)):
                    raise RefreshError(f"{batch}: {c['meeting_id']} is applied or owned by {owner.get('owner')}")
            old = json.loads(manifest_path(refresh, batch, st["rev"]).read_text())
            docs = [{k: d[k] for k in ("body", "meeting_id", "date", "title", "record_id", "url", "path", "format",
                                       "sha256")} for d in old["documents"]]
            rev = st["rev"] + 1
        manifest = _manifest(refresh, repo, batch, rev, docs, export, cfg, holds, rh)
        data = (json.dumps(manifest, indent=1, sort_keys=True) + "\n").encode()
        _publish(manifest_path(refresh, batch, rev), data)  # durable before the registry references it
        sha = _sha_bytes(data)
        if rev == 1:
            reg.append({"kind": "batch", "batch": batch, "rev": 1, "bodies": manifest["bodies"],
                        "manifest_sha256": sha, "claims": [{"meeting_id": d["meeting_id"], "slot": SLOT,
                                                            "sha256": d["sha256"]} for d in docs]})
        else:
            if batch_states(refresh, reg.records())[batch]["released"]:
                for d in docs:
                    reg.append({"kind": "claim", "batch": batch, "meeting_id": d["meeting_id"], "slot": SLOT,
                                "sha256": d["sha256"]})
            reg.append({"kind": "revision", "batch": batch, "rev": rev, "manifest_sha256": sha})
        result = build_revision(refresh, repo, manifest, rev_dir(refresh, batch, rev) / "build", cfg)
        _move_build(rev_dir(refresh, batch, rev))
        state = _finish_revision(refresh, reg, batch, rev, result)
    append_history(refresh, {"command": "prepare", "today": today, "batch": batch, "rev": rev, "state": state,
                             "documents": [[d["meeting_id"], d["sha256"]] for d in docs],
                             "attached": result["attached"], "new_holds": [h["hold_id"] for h in result["new_holds"]]})
    write_todo(export, repo, refresh, today=today)
    return {"state": state, "batch": batch, "rev": rev, "attached": result["attached"], "blocked": stop,
            "new_holds": result["new_holds"], "resolution_problems": res_problems,
            "accounting_problems": result["accounting"]["problems"], "plan_problems": result.get("plan_problems", [])}


def _move_build(d: Path) -> None:
    """build/ → the revision's top level (ledger/, bundle/, plan/, spot-check.md, holds.json, hints.json)."""
    import shutil
    for p in sorted((d / "build").iterdir()):
        target = d / p.name
        if target.exists():
            shutil.rmtree(target) if target.is_dir() else target.unlink()
        shutil.move(str(p), str(target))
    (d / "build").rmdir()


DETERMINISTIC = ("ledger", "bundle", "plan", "spot-check.md", "holds.json", "hints.json")


def check_revision(refresh: Path, repo: Path, batch: str, rev: int) -> list[str]:
    """Rebuild one revision from its manifest into a temporary dir; every artifact must be byte-identical."""
    import tempfile

    import votes_refresh_ledger as rl
    d = rev_dir(refresh, batch, rev)
    manifest = json.loads(manifest_path(refresh, batch, rev).read_text())
    cfg = rl.load_config(refresh)
    with tempfile.TemporaryDirectory(dir=refresh, prefix=".check-") as tmp:
        again = Path(tmp) / "rev"
        build_revision(refresh, repo, manifest, again, cfg)
        mine = sorted(p.relative_to(d) for p in d.rglob("*") if p.is_file() and p.relative_to(d).parts[0] in DETERMINISTIC)
        theirs = sorted(p.relative_to(again) for p in again.rglob("*") if p.is_file())
        problems = [] if mine == theirs else [f"file lists differ: {sorted(set(mine) ^ set(theirs))[:5]}"]
        problems += [f"{rel} differs from a rebuild" for rel in sorted(set(mine) & set(theirs))
                     if (d / rel).read_bytes() != (again / rel).read_bytes()]
    return problems


def apply_guard(state_dir: Path, reg: Registry) -> None:
    """Called by votes_apply under the refresh lock: this revision is its batch's current one, the batch still owns
    its slots, and no unresolved roster hold covers any vote it attaches."""
    d = Path(state_dir).resolve()
    marker = json.loads((d / MARKER).read_text())
    refresh = d.parents[2]
    records = reg.records()
    st = batch_states(refresh, records).get(marker["batch"])
    if st is None or st["rev"] != marker["rev"] or d != rev_dir(refresh, marker["batch"], marker["rev"]).resolve():
        raise RefreshError(f"{d} is not the current revision of a committed batch")
    if st["released"]:
        raise RefreshError(f"{marker['batch']} was released")
    if marker["batch"] in batch_integrity(refresh, records):
        raise RefreshError(f"{marker['batch']}: {batch_integrity(refresh, records)[marker['batch']]}")
    live = [h for h in roster_holds(records) if not h["resolved"]]
    for x in _read_jsonl(d / "bundle" / "dispositions.jsonl"):
        if x["reason"] != "attached":
            continue
        h = next((h for h in live if h["body"] == x["body"] and x["date"] >= h["from_date"]), None)
        if h:
            raise RefreshError(f"{x['event_id']} is covered by unresolved roster hold {h['hold_id']} (recorded after "
                               "this batch was approved): re-prepare the batch")


def approve(refresh: Path, batch: str, *, review: Path, bake_check: Path) -> str:
    """AWAITING_APPLY for the current revision of `batch`, only with a fully answered independent review of exactly
    its spot-check sheet (every doubt held), a clean staging bake check of exactly its candidate / bundle / baseline
    / targets, matching accounting, and no covering roster hold. Returns the approval sha256."""
    import case_additive_plan as cap
    import votes_apply

    refresh = Path(refresh)
    reg = Registry(refresh)
    with reg.locked():
        records = reg.records()
        st = batch_states(refresh, records).get(batch)
        if st is None or st["state"] != "AWAITING_REVIEW":
            raise RefreshError(f"{batch} is {st and st['state']}, not AWAITING_REVIEW")
        d = rev_dir(refresh, batch, st["rev"])
        apply_guard(d, reg)
        manifest = json.loads(manifest_path(refresh, batch, st["rev"]).read_text())
        report = json.loads((d / "plan" / "plan-report.json").read_text())
        if report.get("profile") != "votes-refresh" or report.get("verification") \
                or not report.get("baseline_reexport_identical"):
            raise RefreshError("the plan is not a clean votes-refresh plan")
        if report["case"]["sha256"] != cap.fingerprint(d / "bundle"):
            raise RefreshError("the plan was made from another bundle")
        acc = json.loads((d / "bundle" / "candidate-accounting.json").read_text())
        if acc["problems"] or acc.get("matches_expected") is not True:
            raise RefreshError(f"accounting: {acc['problems'][:3] or ['does not match the expected manifest']}")
        sheet = (d / "spot-check.md").read_text()
        review_text = Path(review).read_text()
        if (review_text.splitlines() or [""])[0] != f"Sheet sha256: {_sha_bytes(sheet.encode())}":
            raise RefreshError("the review is not of this revision's sheet (first line `Sheet sha256: <sha>`)")
        attached = {x["event_id"] for x in _read_jsonl(d / "bundle" / "dispositions.jsonl") if x["reason"] == "attached"}
        problems = votes_apply.review_problems(sheet, review_text, attached=attached)
        if problems:
            raise RefreshError(f"spot check: {problems[:5]} — hold them (reviewer-holds.json) and re-prepare")
        bake = json.loads(Path(bake_check).read_text())
        want = {"candidate_sha256": report["candidate_sha256"], "bundle_sha256": cap.fingerprint(d / "bundle"),
                "baseline_sha256": manifest["baseline"]["sha256"],
                "targets_sha256": _sha_bytes((d / "plan" / "targets.json").read_bytes())}
        if bake.get("problems") != [] or any(bake.get(k) != v for k, v in want.items()):
            raise RefreshError("the staging bake check is not a clean check of this revision's candidate, bundle, "
                               "baseline and targets")
        (d / "spot-check-review.md").write_text(review_text)
        (d / "bake-check.json").write_text(Path(bake_check).read_text())
        base = Path(manifest["baseline"]["dir"])
        files = {f"plan/{rel}": d / "plan" / rel for rel in ("ops.json", "plan-report.json", "inverse.json",
                                                              "expected-edges.jsonl", "targets.json",
                                                              "candidate/nodes.jsonl", "candidate/edges.jsonl")}
        files.update({f"bundle/{p.name}": p for p in sorted((d / "bundle").iterdir()) if p.is_file()})
        files.update({"baseline/nodes.jsonl": base / "nodes.jsonl", "baseline/edges.jsonl": base / "edges.jsonl",
                      "manifest.json": manifest_path(refresh, batch, st["rev"]), "spot-check.md": d / "spot-check.md",
                      "spot-check-review.md": d / "spot-check-review.md", "bake-check.json": d / "bake-check.json",
                      MARKER: d / MARKER})
        return votes_apply.write_approval(d, files)


def abandon(refresh: Path, batch: str) -> None:
    reg = Registry(refresh)
    with reg.locked():
        st = batch_states(refresh, reg.records()).get(batch)
        if st is None:
            raise RefreshError(f"{batch} is not a committed batch")
        if st["state"] not in REVISABLE:
            raise RefreshError(f"{batch} is {st['state'] or 'without a readable state'}; it cannot be abandoned")
        if not st["released"]:
            reg.append({"kind": "release", "batch": batch, "reason": "abandoned"})


def resolve(refresh: Path, batch: str, *, canonical_root: Path, driver_factory, database: str = "neo4j",
            exporter=None) -> str:
    """An unresolved apply (APPLY_IN_PROGRESS / APPLY_UNVERIFIED / unreadable state), proved against the LIVE
    operator graph: under refresh → weekly locks, a fresh read-only export; == candidate → APPLIED (journaled);
    == baseline → ROLLED_BACK (released); anything else stays unresolved. No export can be supplied by hand."""
    import case_additive_plan as cap
    import votes_apply
    from export_live_graph import export_live_graph
    from run_lock import run_lock

    exporter = exporter or export_live_graph
    refresh = Path(refresh)
    reg = Registry(refresh)
    with reg.locked():
        st = batch_states(refresh, reg.records()).get(batch)
        if st is None or not (st["state"] in UNRESOLVED_STATES or st["state"] is None):
            raise RefreshError(f"{batch} is {st and st['state']}; nothing to resolve")
        d = rev_dir(refresh, batch, st["rev"])
        report = json.loads((d / "plan" / "plan-report.json").read_text())
        with run_lock(Path(canonical_root)):
            n = len(list((d / "apply").glob("resolve-*"))) + 1 if (d / "apply").is_dir() else 1
            out = d / "apply" / f"resolve-{n}"
            driver = driver_factory()
            try:
                exporter(driver, database=database, out_dir=out, backup=True, progress=None)
            finally:
                driver.close()
            live = cap.fingerprint(out)
            if live == report["candidate_sha256"]:
                post = d / "apply" / "post-apply-export"
                if post.exists():
                    import shutil
                    shutil.rmtree(post)
                import shutil
                shutil.copytree(out, post)
                approval = _sha_bytes((d / "plan" / "approval-inputs.json").read_bytes())
                votes_apply.set_state(d, "APPLIED", approval_sha256=approval, resolved_by=out.name)
                sync_journal(refresh, reg)
                return "APPLIED"
            if live == report["baseline"]["sha256"]:
                votes_apply.set_state(d, "ROLLED_BACK", reason="resolved: the live graph equals the baseline",
                                      resolved_by=out.name)
                sync_journal(refresh, reg)
                return "ROLLED_BACK"
            return "UNRESOLVED"


def status_lines(export: Path, repo: Path, refresh: Path, today: str) -> tuple[list[str], bool]:
    """(the status report, whether anything blocks). Read-only."""
    b = backlog(export, repo, refresh, today=today)
    records = Registry(refresh).records()
    stop = blocked(refresh, records)
    lines = freshness_lines(listing_freshness(repo, today)) + [""]
    lines += [f"BLOCKED — {body}: " + "; ".join(why) for body, why in sorted(stop.items())]
    for body, rows in sorted(b.items()):
        lines.append(f"{body}: {_counts(rows)}")
        lines += _other_lines(rows)
        lines += [f"- {r['date']} `{r['meeting_id']}` — awaiting_file; saved file not accepted: {r['file']['reason']}"
                  for r in rows if r["state"] == "awaiting_file" and r["url"] and r["file"] and r["file"]["reason"]]
    states = batch_states(refresh, records)
    if states:
        lines += ["", "Batches:"]
        lines += [f"- {batch} rev-{st['rev']}: {st['state'] or 'NO READABLE STATE'}"
                  f"{' (released)' if st['released'] else ''} — {len(st['claims'])} meeting(s)"
                  for batch, st in sorted(states.items())]
    holds = roster_holds(records)
    if holds:
        lines += ["", "Roster holds:"]
        lines += [f"- {h['hold_id']} {h['body']} from {h['from_date']} ({h['kind']}"
                  f"{': ' + h['key'] if h.get('key') else ''}) — {'dismissed' if h['resolved'] else 'OPEN'}: "
                  f"roster-holds/{h['hold_id']}.md" for h in holds]
    return lines, bool(stop)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--refresh-root", type=Path, default=REFRESH_ROOT)
    common.add_argument("--repo-root", type=Path, default=REPO_ROOT, help="where data/raw/manual and run states live")
    common.add_argument("--today")
    for name in ("todo", "status"):
        sub.add_parser(name, parents=[common]).add_argument("--export", type=Path, required=True)
    i = sub.add_parser("init", parents=[common])
    i.add_argument("--part-a", type=Path, default=Path.home() / "open-marin-staging" / "votes")
    i.add_argument("--votes-b", type=Path, default=Path.home() / "open-marin-staging" / "votes-b")
    pr = sub.add_parser("prepare", parents=[common])
    pr.add_argument("--export", type=Path, required=True, help="a read-only export_live_graph.py --backup dir")
    pr.add_argument("--batch", help="make a new revision of this batch")
    pr.add_argument("--reviewer-holds", type=Path, help='{"holds": [{"event_id", "reason"}]} from the spot check')
    a = sub.add_parser("approve", parents=[common])
    a.add_argument("--batch", required=True)
    a.add_argument("--review", type=Path, required=True)
    a.add_argument("--bake-check", type=Path, required=True)
    sub.add_parser("abandon", parents=[common]).add_argument("--batch", required=True)
    r = sub.add_parser("resolve", parents=[common])
    r.add_argument("--batch", required=True)
    r.add_argument("--canonical-root", type=Path, required=True)
    c = sub.add_parser("check", parents=[common])
    c.add_argument("--batch", required=True)
    c.add_argument("--rev", type=int, required=True)
    args = ap.parse_args(argv)
    args.refresh_root.mkdir(parents=True, exist_ok=True)
    today = args.today or dt.date.today().isoformat()
    try:
        if args.cmd == "init":
            import votes_refresh_ledger as rl
            cfg = rl.init_config(args.refresh_root, part_a=args.part_a, votes_b=args.votes_b)
            print(f"verified once and pinned {len(cfg['files'])} files; roster problems {cfg['verification']}; "
                  f"applied persons {cfg['applied_persons']}")
            return 0
        if args.cmd == "todo":
            out = write_todo(args.export, args.repo_root, args.refresh_root, today=today)
            print((args.refresh_root / "todo.md").read_text())
            print(f"{out['state']} — {out['items']} minutes to save; {args.refresh_root / 'todo.md'}")
            return 0
        if args.cmd == "status":
            lines, stop = status_lines(args.export, args.repo_root, args.refresh_root, today)
            print("\n".join(lines))
            return 1 if stop else 0
        if args.cmd == "prepare":
            out = prepare(args.export, args.repo_root, args.refresh_root, today=today, batch=args.batch,
                          reviewer_holds=args.reviewer_holds)
            print(json.dumps({k: v for k, v in out.items() if k != "new_holds"}, indent=1, sort_keys=True, default=str))
            for h in out.get("new_holds", []):
                print(f"roster hold {h['hold_id']}: {args.refresh_root / 'roster-holds' / (h['hold_id'] + '.md')}")
            return 0
        if args.cmd == "approve":
            sha = approve(args.refresh_root, args.batch, review=args.review, bake_check=args.bake_check)
            st = batch_states(args.refresh_root, Registry(args.refresh_root).records())[args.batch]
            print(f"AWAITING_APPLY — approval sha256 {sha}\napply (Stuart): python scripts/votes_apply.py apply "
                  f"--state-dir {rev_dir(args.refresh_root, args.batch, st['rev'])} --approve {sha} "
                  f"--canonical-root {REPO_ROOT}")
            return 0
        if args.cmd == "abandon":
            abandon(args.refresh_root, args.batch)
            print(f"{args.batch} released")
            return 0
        if args.cmd == "check":
            problems = check_revision(args.refresh_root, args.repo_root, args.batch, args.rev)
            for p in problems:
                print(p)
            print(f"determinism check: {len(problems)} problem(s)")
            return 1 if problems else 0
        import os as _os

        from neo4j_target import open_driver
        uri = _os.environ.get("NEO4J_URI")
        print(resolve(args.refresh_root, args.batch, canonical_root=args.canonical_root,
                      database=_os.environ.get("NEO4J_DATABASE", "neo4j"),
                      driver_factory=lambda: open_driver(uri, auth=(_os.environ["NEO4J_USER"],
                                                                    _os.environ["NEO4J_PASSWORD"]))))
        return 0
    except RefreshError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    sys.exit(main())
