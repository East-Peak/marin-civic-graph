#!/usr/bin/env python3
"""The weekly agenda-items stage: agenda files of eligible council sources -> AgendaItems, create-only.

A source is eligible from its registry entry alone (`eligibility`): weekly, not Granicus, an `agenda_items` block,
and a parser qualified at its current version. For each eligible source the stage reads the institution's Meetings
from the graph, selects candidates (`select`: the body confirmed, exactly one agenda Record no other meeting shares,
no AgendaItems; newest first, up to the cap; held ones retried on their own slower budget), fetches each agenda
through the robots gate with the source's host allowlist, parses it, and writes a normalized bundle that
`guarded_load.load_agenda_bundle` creates in one transaction. Nothing existing is written or deleted. A meeting that
does not fit holds alone, with a reason; it never loads as an empty success.

The run's own directory holds every phase once (`<run>/agenda-items/`: selection, fetched results, bundle,
report), so re-running the stage for a run resumes it with the same selection, and re-running a finished run
does nothing. The ledger (data/ingest-runs/agenda-items-ledger.json) remembers, across runs, which agendas this
stage loaded (url + sha256) and which are held.
"""
from __future__ import annotations

import hashlib
import http.client
import json
import os
import re
import tempfile
import time
import urllib.error
import urllib.request
from collections import Counter
from contextlib import nullcontext
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

import yaml

import guarded_load
import robots_gate
from agenda_parsers import PARSERS, Unparseable, extract_text
from graph_lock import graph_lock

MEETING_REGISTRIES = ("granicus", "civicplus", "drupal", "proudcity")  # registry/<name>-sources.yaml
LEDGER = Path("data/ingest-runs/agenda-items-ledger.json")
CAP = 20  # fresh candidates per source per run; `agenda_items.cap` overrides
HELD_RETRY_DAYS = 28
HELD_RETRY_CAP = 5
REVISION_DAYS = 28  # a loaded agenda is re-checked weekly until this long after its meeting
REVISION_EVERY = 6
REVISION_CAP = 10  # re-checks per source per run, never from the cap
MIN_SPACING = 5.0  # seconds between our requests to one host, on top of its Crawl-delay
FETCH_TIMEOUT = 60
MAX_BYTES = 50 * 1024 * 1024
STATUS = "parsed_from_agenda"
LOADED_STATES = ("pending", "loaded", "revised")


class AgendaHold(Exception):
    """This meeting's agenda cannot load now; `reason` names why (the meeting holds, the stage goes on)."""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason, self.detail = reason, detail


# --- eligibility and the body check ---------------------------------------------------------------------


def eligibility(config: dict, parsers=None) -> tuple[bool, str]:
    """(eligible, reason) for one meeting source, from its registry entry alone."""
    parsers = PARSERS if parsers is None else parsers
    if config.get("adapter") == "granicus":
        return False, "adapter granicus"
    if config.get("schedule") != "weekly":
        return False, f"schedule {config.get('schedule')}"
    block = config.get("agenda_items")
    if not isinstance(block, dict):
        return False, "no agenda_items block"
    for field in ("artifact", "hosts", "body"):
        if not block.get(field):
            return False, f"agenda_items.{field} missing"
    parser = parsers.get(block.get("parser"))
    if parser is None:
        return False, f"unknown parser {block.get('parser')}"
    qualified = block.get("qualified") or {}
    if qualified.get("parser") != block["parser"] or qualified.get("version") != parser.version:
        return False, "parser not qualified"
    return True, "eligible"


def eligible_sources(root: Path, parsers=None) -> list[tuple[dict, bool, str]]:
    """Every meeting source in the registries, with its verdict, in registry order."""
    out = []
    for name in MEETING_REGISTRIES:
        path = Path(root) / "registry" / f"{name}-sources.yaml"
        if path.is_file():
            for config in yaml.safe_load(path.read_text(encoding="utf-8")).get("sources") or []:
                out.append((config, *eligibility(config, parsers)))
    return out


def body_class(config: dict, props: dict) -> str:
    """'council' (positive evidence), 'other' (another body's meeting) or 'unconfirmed'."""
    body = config["agenda_items"]["body"]
    if "category" in body:
        category = props.get("category")
        return "unconfirmed" if not category else "council" if category in body["category"] else "other"
    title = props.get("title") or ""
    if body.get("other") and re.search(body["other"], title):
        return "other"
    return "council" if re.search(body["title"], title) else "unconfirmed"


# --- candidates --------------------------------------------------------------------------------------------


def _kinds(config: dict) -> set[str]:
    art = config["agenda_items"]["artifact"]
    return guarded_load.ARTIFACT_KINDS.get(art, {f"meeting_{art}"})


def _url_users(meetings: dict[str, dict], kinds: set[str]) -> dict[str, set[str]]:
    users: dict[str, set[str]] = {}
    for mid, m in meetings.items():
        for r in m["records"]:
            if r.get("record_type") in kinds and r.get("source_url"):
                users.setdefault(r["source_url"], set()).add(mid)
    return users


def classify(mid: str, m: dict, config: dict, users: dict[str, set[str]]) -> tuple[str, str, dict | None]:
    """('excluded' | 'hold' | 'candidate', reason, the agenda Record) for one meeting, ledger aside."""
    if (m["props"].get("meeting_date") or "") < config.get("backfill_from", ""):
        return "excluded", "before_backfill", None
    if m.get("item_ids"):
        return "excluded", "has_items", None
    agendas = [r for r in m["records"] if r.get("record_type") in _kinds(config)]
    if not agendas:
        return "excluded", "no_agenda_record", None
    body = body_class(config, m["props"])
    if body == "other":
        return "excluded", "other_body", None
    if body == "unconfirmed":
        return "hold", "body_unconfirmed", None
    if len(agendas) > 1:
        return "hold", "agenda_records_ambiguous", None
    if len(users.get(agendas[0].get("source_url"), ())) > 1 or not agendas[0].get("source_url"):
        return "hold", "agenda_url_shared", None
    return "candidate", "", agendas[0]


def _days_since(day: str | None, today: str) -> int:
    return (date.fromisoformat(today) - date.fromisoformat(day)).days if day else 10**6


def select(meetings: dict[str, dict], config: dict, *, ledger: dict, today: str, cap: int | None = None,
           held_retry_cap: int = HELD_RETRY_CAP, held_retry_days: int = HELD_RETRY_DAYS) -> dict:
    """This run's candidates for one source: up to `cap` fresh ones, newest first, plus due held retries."""
    cap = config["agenda_items"].get("cap", CAP) if cap is None else cap
    session = config["agenda_items"].get("session")
    users = _url_users(meetings, _kinds(config))
    council_days = Counter(m["props"].get("meeting_date") for m in meetings.values()
                           if body_class(config, m["props"]) == "council")
    fresh, due, holds, excluded, waiting = [], [], [], Counter(), 0
    by_id = sorted(meetings.items())  # newest first; a tie on date goes by id
    for mid, m in sorted(by_id, key=lambda kv: kv[1]["props"].get("meeting_date") or "", reverse=True):
        status, reason, record = classify(mid, m, config, users)
        if status == "excluded":
            excluded[reason] += 1
            continue
        if status == "hold":
            holds.append({"meeting_id": mid, "reason": reason})
            continue
        entry = ledger.get(mid) or {}
        if entry.get("state") in LOADED_STATES:
            excluded["managed"] += 1
            continue
        pick = {"meeting_id": mid, "meeting_date": m["props"]["meeting_date"], "record_id": record["id"],
                "url": record["source_url"], "retry": entry.get("state") == "held",
                "title": m["props"].get("title") or "", "siblings": council_days[m["props"]["meeting_date"]] > 1}
        if session:  # the meeting's session, read from the configured fields (an id's hyphens as spaces)
            pick["session_text"] = " ".join(str(mid if f == "id" else m["props"].get(f) or "")
                                            for f in session["from"]).replace("-", " ")
        if not pick["retry"]:
            fresh.append(pick)
        elif _days_since((entry.get("hold") or {}).get("last_attempt"), today) >= held_retry_days:
            due.append(pick)
        else:
            waiting += 1
    selected = fresh[:cap] + due[:held_retry_cap]
    return {"selected": selected, "holds": holds, "excluded": dict(excluded), "backlog": len(fresh), "cap": cap,
            "held_waiting": waiting + max(0, len(due) - held_retry_cap)}


# --- fetch -------------------------------------------------------------------------------------------------


def fetch(gate, url: str, hosts, *, timeout: float = FETCH_TIMEOUT, max_bytes: int = MAX_BYTES) -> bytes:
    """The agenda file's bytes, through the robots gate, every hop on `hosts`; else AgendaHold."""
    request = urllib.request.Request(url, headers={"User-Agent": robots_gate.USER_AGENT})
    try:
        with gate.open(request, timeout=timeout, hosts=frozenset(hosts)) as resp:
            data = resp.read(max_bytes + 1)
    except robots_gate.RobotsRefused as exc:
        raise AgendaHold(exc.outcome, str(exc)) from None
    except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError) as exc:
        raise AgendaHold("fetch_failed", f"{type(exc).__name__}: {exc}") from None
    if len(data) > max_bytes:
        raise AgendaHold("too_large", f"over {max_bytes} bytes")
    return data


# --- items and the bundle ----------------------------------------------------------------------------------


def parse_hold(parsed: dict, meeting_date: str, document: str | None = None) -> str | None:
    """Why this parse cannot load for a meeting on `meeting_date`, or None."""
    if parsed.get("notice"):
        return f"{parsed['notice']}_notice"
    if document and not re.search(document, " ".join((parsed.get("header") or "").split()), re.IGNORECASE):
        return "agenda_body_mismatch"
    items = parsed.get("items") or []
    if not items:
        return "zero_items"
    if not parsed.get("printed_date"):
        return "agenda_date_missing"
    if parsed["printed_date"] != meeting_date:
        return "agenda_date_mismatch"
    keys = [item["key"] for item in items]
    if len(set(keys)) != len(keys):
        return "duplicate_item_key"
    if any(not (item.get("title") or "").strip() for item in items):
        return "item_without_title"
    return None


_CLOSED = re.compile(r"closed\s+session", re.IGNORECASE)


def _kind(text: str) -> set[str]:
    return {k for k, pattern in (("closed", _CLOSED.pattern), ("special", r"special"),
                                 ("regular", r"regular|open\s+session")) if re.search(pattern, text, re.IGNORECASE)}


def _one_kind(kinds: set[str]) -> str:
    return "closed" if "closed" in kinds else "special" if "special" in kinds else "regular"


def session_hold(header: str, title: str, *, siblings: bool, exact: bool = False) -> str | None:
    """`agenda_session_mismatch` when the file's session is not the meeting's (Ross: one closed-session file filed
    under both of a day's meetings). With a same-day sibling the header must name the meeting's kind; without one,
    only a closed-only file (a closed session named, and no header line naming an open meeting) under a meeting
    that is not a closed session holds.

    `exact` (a source whose `session` block says `match: exact`, its meetings told apart by the configured fields):
    file and meeting each have one kind (closed > special > regular); with a sibling they must be equal, without one
    only a closed-session file under a regular meeting holds (a special meeting may be agendized as a closed session)."""
    said, named = _kind(header), _kind(title)
    meeting = _one_kind(named)
    if exact:
        file = _one_kind(said)
        if siblings:
            return None if file == meeting else "agenda_session_mismatch"
        return "agenda_session_mismatch" if file == "closed" and meeting == "regular" else None
    open_line = any(re.search(r"regular|open\s+session|special", line, re.IGNORECASE)
                    and not _CLOSED.search(line) for line in header.splitlines())
    closed_only = "closed" in said and not open_line
    if siblings:
        ok = meeting in said if meeting != "regular" else ("regular" in said or not said & {"special", "closed"})
        return None if ok else "agenda_session_mismatch"
    return "agenda_session_mismatch" if closed_only and meeting != "closed" else None


def item_id(meeting_id: str, key: str) -> str:
    return f"agenda-item-{meeting_id.split('meeting-', 1)[-1]}-{key}"


def item_rows(meeting_id: str, source_id: str, record_id: str, parsed: dict, parser_tag: str):
    """(AgendaItem nodes, edges) for one meeting, in the existing agenda-item shape (export-row form)."""
    nodes, edges = [], []
    for order, item in enumerate(parsed["items"], 1):
        nid = item_id(meeting_id, item["key"])
        props = {"id": nid, "display_label": item["title"][:120], "promotion_state": "promoted",
                 "heading": item.get("heading") or "", "title": item["title"],
                 "section_number": item.get("section_number"), "item_number": item.get("item_number"),
                 "meeting_id": meeting_id, "source_id": source_id, "status": STATUS, "item_order": order,
                 "parser": parser_tag}
        nodes.append({"id": nid, "labels": ["AgendaItem"],
                      "properties": {k: v for k, v in props.items() if v not in (None, "") or k == "heading"}})
        edges += [{"start_id": nid, "type": "PART_OF_MEETING", "end_id": meeting_id, "properties": {}},
                  {"start_id": nid, "type": "EVIDENCED_BY", "end_id": record_id, "properties": {}}]
    return nodes, edges


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_bundle(path: Path, entries: list[dict]) -> Path:
    """Write the bundle once (atomically): nodes.jsonl, edges.jsonl, manifest.json (meetings + file hashes)."""
    path = Path(path)
    if path.exists():
        raise FileExistsError(f"{path}: a bundle is written once")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(dir=path.parent, prefix=f".{path.name}."))
    nodes = [n for e in entries for n in e["nodes"]]
    edges = [x for e in entries for x in e["edges"]]
    (tmp / "nodes.jsonl").write_text("".join(json.dumps(n, sort_keys=True) + "\n" for n in nodes), encoding="utf-8")
    (tmp / "edges.jsonl").write_text("".join(json.dumps(e, sort_keys=True) + "\n" for e in edges), encoding="utf-8")
    meetings = [{**{k: v for k, v in e.items() if k not in ("nodes", "edges")},
                 "item_ids": [n["id"] for n in e["nodes"]]} for e in entries]
    manifest = {"meetings": meetings, "files": {f: _sha256(tmp / f) for f in ("nodes.jsonl", "edges.jsonl")}}
    (tmp / "manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


# --- ledger ------------------------------------------------------------------------------------------------


def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(value, fh, indent=1, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, path)


def read_ledger(root: Path) -> dict:
    path = Path(root) / LEDGER
    return json.loads(path.read_text(encoding="utf-8"))["meetings"] if path.is_file() else {}


def write_ledger(root: Path, meetings: dict) -> None:
    _write_json(Path(root) / LEDGER, {"version": 1, "meetings": meetings})


# --- the stage ---------------------------------------------------------------------------------------------


class _Pacer:
    def __init__(self, sleep, monotonic):
        self.sleep, self.monotonic, self.last = sleep, monotonic, {}

    def wait(self, url: str) -> None:
        host = urlsplit(url).netloc.lower()
        if host in self.last:
            left = self.last[host] + MIN_SPACING - self.monotonic()
            if left > 0:
                self.sleep(left)
        self.last[host] = self.monotonic()


def _institution_meetings(port, institution_id: str) -> dict[str, dict]:
    with port.transaction(constrained=()) as tx:
        return tx.agenda_meetings(institution_id)


def _fetch_and_parse(pick: dict, config: dict, *, gate, pacer, files: Path, parser, parser_tag, extract) -> dict:
    """One selected meeting's result: {sha256, file, parsed} or {hold, detail}, plus the url."""
    block = config["agenda_items"]
    out = {"url": pick["url"]}
    try:
        pacer.wait(pick["url"])
        data = fetch(gate, pick["url"], block["hosts"])
        out["sha256"] = hashlib.sha256(data).hexdigest()
        is_pdf = data[:4] == b"%PDF"
        saved = files / f"{out['sha256']}.{'pdf' if is_pdf else 'html'}"
        if not saved.exists():
            saved.parent.mkdir(parents=True, exist_ok=True)
            saved.write_bytes(data)
        out["file"] = saved.name
        if not is_pdf:
            raise AgendaHold("not_pdf")
        try:
            text = extract(data)
            if not text.strip():
                raise AgendaHold("text_empty")
            parsed = parser.parse(text)
        except Unparseable as exc:
            raise AgendaHold(exc.reason, str(exc)) from None
        reason = parse_hold(parsed, pick["meeting_date"], block["body"].get("document")) \
            or session_hold(parsed.get("header") or "", pick.get("session_text", pick.get("title") or ""),
                            siblings=pick.get("siblings", False),
                            exact=(block.get("session") or {}).get("match") == "exact") \
            or ("multi_session_sibling" if parsed.get("sessions", 1) > 1 and pick.get("siblings") else None)
        if reason:
            raise AgendaHold(reason)
        out["parsed"] = parsed
    except AgendaHold as hold:
        out.update(hold=hold.reason, detail=hold.detail)
    out["parser"] = parser_tag
    return out


def _recheck(config: dict):
    """The candidate predicate again, inside the load transaction, for one bundle meeting."""
    def check(entry: dict, meetings: dict[str, dict]) -> str | None:
        m = meetings.get(entry["meeting_id"])
        status, reason, record = classify(entry["meeting_id"], m, config, _url_users(meetings, _kinds(config)))
        if status != "candidate":
            return reason
        if (record["id"], record.get("source_url")) != (entry["record_id"], entry["url"]):
            return "agenda_record_changed"
        if m["props"].get("meeting_date") != entry["meeting_date"]:
            return "meeting_date_changed"
        return None
    return check


def run_stage(*, root: Path, run_dir: Path, port, gate, today: str, run_id: str = "", parsers=None,
              extract=extract_text, sleep=None, monotonic=None, cap: int | None = None,
              graph_uri: str | None = None) -> dict:
    """The stage for one run; returns (and writes) its report. Re-running a finished run returns its report.

    With `graph_uri`, the whole stage holds that graph's writer lock (scripts/graph_lock.py)."""
    work = Path(run_dir) / "agenda-items"
    if (work / "report.json").is_file():
        return json.loads((work / "report.json").read_text(encoding="utf-8"))
    with graph_lock(graph_uri) if graph_uri else nullcontext():
        return _run_stage(root=root, work=work, port=port, gate=gate, today=today, run_id=run_id,
                          parsers=PARSERS if parsers is None else parsers, extract=extract,
                          sleep=sleep or time.sleep, monotonic=monotonic or time.monotonic, cap=cap)


def _run_stage(*, root, work, port, gate, today, run_id, parsers, extract, sleep, monotonic, cap) -> dict:
    verdicts = eligible_sources(root, parsers)
    report = {"run_id": run_id, "today": today, "sources": {}}
    eligible = {}
    for config, ok, reason in verdicts:
        if ok:
            eligible[config["id"]] = config
        elif config.get("agenda_items") or config.get("schedule") == "weekly":
            report["sources"][config["id"]] = {"eligible": False, "reason": reason}
    ledger = _settle_pending(read_ledger(root), port, eligible, run_id, root, today)

    views: dict[str, dict] = {}

    def view(sid: str) -> dict:  # the institution's meetings, read once per stage
        if sid not in views:
            views[sid] = _institution_meetings(port, eligible[sid]["institution_id"])
        return views[sid]

    pacer = _Pacer(sleep, monotonic)
    revised = _revisions(work, eligible, view, ledger, today, gate, pacer)
    write_ledger(root, ledger)
    selection = _selection(work, eligible, view, ledger, today, cap)
    results: dict[str, dict] = {}
    for sid, chosen in selection.items():
        config = eligible[sid]
        name = config["agenda_items"]["parser"]
        for pick in chosen["selected"]:
            path = work / "fetched" / f"{pick['meeting_id']}.json"
            if not path.is_file():  # each meeting is fetched once per run, even across a resumed stage
                _write_json(path, {**pick, "source_id": sid, **_fetch_and_parse(
                    pick, config, gate=gate, pacer=pacer, files=work / "files", parser=parsers[name],
                    parser_tag=f"{name}@{parsers[name].version}", extract=extract)})
            results[pick["meeting_id"]] = json.loads(path.read_text(encoding="utf-8"))
    _hold_shared_content(results, ledger)

    entries = []
    for mid, r in results.items():
        if "hold" not in r:
            config = eligible[r["source_id"]]
            nodes, edges = item_rows(mid, r["source_id"], r["record_id"], r["parsed"], r["parser"])
            entries.append({"meeting_id": mid, "source_id": r["source_id"], "institution_id": config["institution_id"],
                            "meeting_date": r["meeting_date"], "record_id": r["record_id"], "url": r["url"],
                            "sha256": r["sha256"], "parser": r["parser"], "nodes": nodes, "edges": edges})
    bundle = work / "bundle"
    if not bundle.exists():
        write_bundle(bundle, entries)
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    for e in manifest["meetings"]:
        ledger[e["meeting_id"]] = {**_ledger_entry(e, "pending", today, run_id),
                                   "bundle": _ref(bundle, root)}
    write_ledger(root, ledger)

    rechecks = {sid: _recheck(config) for sid, config in eligible.items()}
    loaded = guarded_load.load_agenda_bundle(port, bundle, recheck=lambda e, ms: rechecks[e["source_id"]](e, ms))
    load_holds = {h["meeting_id"]: h["reason"] for h in loaded["holds"]}
    for e in manifest["meetings"]:
        mid = e["meeting_id"]
        if mid in loaded["created"]["meetings"] or mid in loaded["already_loaded"]:
            ledger[mid] = {**_ledger_entry(e, "loaded", today, run_id), "bundle": _ref(bundle, root)}
        else:
            ledger[mid] = _held(ledger.get(mid), e, load_holds.get(mid, "load_conflict"), today)
    for mid, r in results.items():
        if "hold" in r:
            ledger[mid] = _held(ledger.get(mid), r, r["hold"], today)
    write_ledger(root, ledger)

    for sid, chosen in selection.items():
        mine = {mid: r for mid, r in results.items() if r["source_id"] == sid}
        report["sources"][sid] = {
            "eligible": True, "reason": "eligible",
            "loaded": {mid: len(e["item_ids"]) for e in manifest["meetings"] for mid in [e["meeting_id"]]
                       if e["source_id"] == sid and ledger[mid]["state"] == "loaded"},
            "held": {**{h["meeting_id"]: h["reason"] for h in chosen["holds"]},
                     **{mid: ledger[mid]["hold"]["reason"] for mid in mine if ledger[mid]["state"] == "held"}},
            "selected": len(chosen["selected"]), "excluded": chosen["excluded"], "backlog": chosen["backlog"],
            "cap": chosen["cap"],
            "backlog_after": chosen["backlog"] - sum(1 for p in chosen["selected"] if not p["retry"]),
            "held_waiting": chosen["held_waiting"], "unverifiable_legacy": chosen["unverifiable_legacy"],
            "revised": {mid: e["revision"]["reason"] for mid, e in sorted(ledger.items())  # outstanding, every run
                        if e.get("source_id") == sid and e.get("state") == "revised"},
            "revision_unchecked": {mid: r["unchecked"] for mid, r in sorted(revised.items())
                                   if "unchecked" in r and ledger[mid]["source_id"] == sid}}
    report["load"] = {k: loaded[k] for k in ("outcome", "holds", "already_loaded")} | {
        "created": loaded["created"]}
    _write_json(work / "report.json", report)
    return report


def _selection(work: Path, eligible: dict, view, ledger: dict, today: str, cap: int | None) -> dict:
    """This run's selection, made once and kept: a resumed stage never reselects."""
    path = work / "selection.json"
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    selection = {}
    for sid, config in eligible.items():
        meetings = view(sid)
        selection[sid] = select(meetings, config, ledger=ledger, today=today, cap=cap)
        selection[sid]["unverifiable_legacy"] = sum(1 for mid, m in meetings.items()
                                                    if m.get("item_ids") and mid not in ledger)
    _write_json(path, selection)
    return selection


def _revision_due(entry: dict, today: str) -> bool:
    return (entry.get("state") == "loaded" and _days_since(entry.get("meeting_date"), today) <= REVISION_DAYS
            and _days_since(entry.get("last_checked"), today) >= REVISION_EVERY)


def _revisions(work: Path, eligible: dict, view, ledger: dict, today: str, gate, pacer) -> dict:
    """Re-check the agendas this stage loaded, weekly until REVISION_DAYS after the meeting: a changed url (no
    fetch) or new bytes at the same url marks the entry `revised` (reported, never re-parsed, items untouched).
    Legacy items have no baseline and are never fetched. Results are kept per run, so a resumed stage reuses them."""
    path = work / "revisions.json"
    if path.is_file():
        done = json.loads(path.read_text(encoding="utf-8"))
    else:
        done = {}
        for sid, config in eligible.items():
            due = sorted((mid for mid, e in ledger.items() if e.get("source_id") == sid and _revision_due(e, today)),
                         key=lambda mid: ledger[mid]["meeting_date"], reverse=True)[:REVISION_CAP]
            meetings = view(sid) if due else {}
            for mid in due:
                entry = ledger[mid]
                record = next((r for r in (meetings.get(mid) or {}).get("records", ()) if r["id"] == entry["record_id"]),
                              None)
                if record is None or record.get("source_url") != entry["url"]:
                    done[mid] = {"reason": "url_changed", "url": (record or {}).get("source_url")}
                    continue
                try:
                    pacer.wait(entry["url"])
                    sha = hashlib.sha256(fetch(gate, entry["url"], config["agenda_items"]["hosts"])).hexdigest()
                except AgendaHold as hold:
                    done[mid] = {"reason": None, "unchecked": hold.reason}
                    continue
                done[mid] = {"reason": "content_changed", "sha256": sha} if sha != entry["sha256"] else {"reason": None}
        work.mkdir(parents=True, exist_ok=True)
        _write_json(path, done)
    for mid, result in done.items():
        entry = ledger[mid]
        if result["reason"]:
            ledger[mid] = {**entry, "state": "revised", "revision": {**result, "detected": today}}
        elif "unchecked" not in result:
            ledger[mid] = {**entry, "last_checked": today}
    return done


def _settle_pending(ledger: dict, port, eligible: dict, run_id: str, root: Path, today: str) -> dict:
    """An earlier run's `pending` entry (its commit acknowledgement was lost): `loaded` only if the graph holds
    exactly its bundle's items for the meeting; forgotten (selected again) if the meeting has no items; else
    held `pending_mismatch` for a human."""
    stale = {mid: e for mid, e in ledger.items() if e["state"] == "pending" and e.get("loaded_run") != run_id}
    institutions = {eligible[e["source_id"]]["institution_id"] for e in stale.values() if e["source_id"] in eligible}
    items = {mid: m.get("item_ids") or [] for inst in sorted(institutions)
             for mid, m in _institution_meetings(port, inst).items()}
    for mid, e in stale.items():
        bundle = Path(root) / e["bundle"] if e.get("bundle") else None
        if not items.get(mid):
            del ledger[mid]
        elif sorted(items[mid]) == sorted(e["item_ids"]) and bundle and bundle.is_dir() \
                and guarded_load.bundle_meeting_loaded(port, bundle, mid):
            ledger[mid] = {**e, "state": "loaded"}
        else:
            ledger[mid] = _held(e, e, "pending_mismatch", today)
    return ledger


def _hold_shared_content(results: dict[str, dict], ledger: dict) -> None:
    """One file under two meetings (two urls, same bytes) is no meeting's agenda for sure: hold them all."""
    owners: dict[str, set[str]] = {}
    for mid, r in results.items():
        if r.get("sha256"):
            owners.setdefault(r["sha256"], set()).add(mid)
    for mid, entry in ledger.items():
        if entry.get("sha256") and entry.get("state") in LOADED_STATES and entry["sha256"] in owners:
            owners[entry["sha256"]].add(mid)
    for sha, mids in owners.items():
        if len(mids) > 1:
            for mid in mids & set(results):
                results[mid].update(hold="agenda_content_shared", detail=", ".join(sorted(mids - {mid})))
                results[mid].pop("parsed", None)


def _ref(path: Path, root: Path) -> str:
    """A path as the ledger keeps it: relative to the root when inside it (a real run), else absolute."""
    path, root = Path(path).resolve(), Path(root).resolve()
    return path.relative_to(root).as_posix() if path.is_relative_to(root) else str(path)


def _ledger_entry(e: dict, state: str, today: str, run_id: str) -> dict:
    return {"state": state, "source_id": e["source_id"], "url": e["url"], "sha256": e["sha256"],
            "record_id": e["record_id"], "item_ids": e["item_ids"], "meeting_date": e["meeting_date"],
            "loaded_run": run_id, "last_checked": today}


def _held(previous: dict | None, e: dict, reason: str, today: str) -> dict:
    attempts = ((previous or {}).get("hold") or {}).get("attempts", 0) + 1
    return {"state": "held", "source_id": e["source_id"], "url": e["url"], "sha256": e.get("sha256"),
            "record_id": e["record_id"], "meeting_date": e["meeting_date"],
            "hold": {"reason": reason, "detail": e.get("detail", ""), "attempts": attempts, "last_attempt": today}}


# --- command line ------------------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """`agenda_items.py run --root <repo> --run-id <id>`: the stage for one weekly run (refresh_weekly calls it).

    The graph is NEO4J_URI (a checked Open Marin target, or fakegraph:/// in a rehearsal); every request goes
    through the robots gate with the run's robots cache and its own request log. Writes
    <run>/agenda-items/report.json; exits 0 when the stage ran (holds included), 1 when it could not."""
    import argparse
    import os

    from run_lock import run_lock

    parser = argparse.ArgumentParser(description="The weekly agenda-items stage")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--root", type=Path, required=True)
    run.add_argument("--run-id", required=True)
    run.add_argument("--today", help="YYYY-MM-DD (default: the run id's date)")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    run_dir = root / "data" / "ingest-runs" / args.run_id
    uri = os.environ.get("NEO4J_URI") or ""
    auth = None
    if not guarded_load.is_fake(uri):
        from neo4j_target import check_target

        check_target(uri)
        auth = (os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"])
    gate = robots_gate.RobotsGate(cache_path=run_dir / "robots.json",
                                  request_log=run_dir / "logs" / "requests-agenda-items.jsonl")
    with run_lock(root), guarded_load.open_port(uri, auth=auth, database=os.environ.get("NEO4J_DATABASE")) as port:
        report = run_stage(root=root, run_dir=run_dir, port=port, gate=gate, run_id=args.run_id,
                           today=args.today or args.run_id[:10], graph_uri=uri)
    for sid, s in sorted(report["sources"].items()):
        if s.get("eligible"):
            print(f"{sid}: {len(s['loaded'])} loaded, {len(s['held'])} held, {len(s['revised'])} revised, "
                  f"{s['backlog_after']} left")
        else:
            print(f"{sid}: not eligible ({s['reason']})")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
