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

    python scripts/votes_refresh.py todo --export <export_live_graph --backup dir>
    python scripts/votes_refresh.py status --export <dir>
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

    @contextlib.contextmanager
    def locked(self, wait: bool = True):
        self.root.mkdir(parents=True, exist_ok=True)
        fh = open(self.root / ".lock", "a+")
        try:
            try:
                fcntl.flock(fh, fcntl.LOCK_EX | (0 if wait else fcntl.LOCK_NB))
            except BlockingIOError:
                raise RefreshError(f"{self.root} is locked by another refresh process") from None
            self._locked = True
            self._repair_tail()
            yield self
        finally:
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


def write_todo(export: Path, repo: Path, refresh: Path, today: str | None = None) -> dict:
    today = today or dt.date.today().isoformat()
    refresh = Path(refresh)
    b = backlog(export, repo, refresh, today=today)
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
        other = [r for r in b[body] if not (r["state"] == "awaiting_file" and r["url"])]
        if other:
            lines += ["", "Not on the list:"]
            for r in other:
                lines.append(f"- {r['date']} `{r['meeting_id']}` — {r['state']}"
                             + (f" ({r['url_reason']})" if r["state"] == "no_minutes_record"
                                and r["url_reason"] != r["state"] else "")
                             + (f"; saved file not accepted: {r['file']['reason']}"
                                if r["file"] and r["file"]["reason"] else ""))
                lines += [f"  - document_version_conflict: `{c['path']}` (sha256 {c['sha256'][:12]}…) differs from "
                          f"the slot's file ({c['held_against'][:12]}…); it is never parsed" for c in r["conflicts"]]
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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("todo", "status"):
        p = sub.add_parser(name)
        p.add_argument("--export", type=Path, required=True)
        p.add_argument("--refresh-root", type=Path, default=REFRESH_ROOT)
        p.add_argument("--repo-root", type=Path, default=REPO_ROOT, help="where data/raw/manual and run states live")
        p.add_argument("--today")
    args = ap.parse_args(argv)
    args.refresh_root.mkdir(parents=True, exist_ok=True)
    if args.cmd == "todo":
        out = write_todo(args.export, args.repo_root, args.refresh_root, today=args.today)
        print((args.refresh_root / "todo.md").read_text())
        print(f"{out['state']} — {out['items']} minutes to save; {args.refresh_root / 'todo.md'}")
        return 0
    b = backlog(args.export, args.repo_root, args.refresh_root, today=args.today)
    print("\n".join(freshness_lines(listing_freshness(args.repo_root, args.today or dt.date.today().isoformat()))))
    for body, rows in sorted(b.items()):
        print(f"{body}: {_counts(rows)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
