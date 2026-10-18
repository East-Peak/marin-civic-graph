#!/usr/bin/env python3
"""The weekly agenda-items stage: agenda files of eligible council sources -> AgendaItems, create-only.

A source is eligible from its registry entry alone (`eligibility`): weekly, not Granicus, an `agenda_items` block,
and a parser qualified at its current version. For each eligible source the stage reads the institution's Meetings
from the graph, selects candidates (`select`: the body confirmed, exactly one agenda Record no other meeting shares,
no AgendaItems; newest first, up to the cap; held ones retried on their own slower budget), fetches each agenda
through the robots gate with the source's host allowlist, parses it, and writes a normalized bundle that
`guarded_load.load_agenda_bundle` creates in one transaction. Nothing existing is written or deleted. A meeting that
does not fit holds alone, with a reason; it never loads as an empty success.
"""
from __future__ import annotations

import hashlib
import http.client
import json
import os
import re
import tempfile
import urllib.error
import urllib.request
from collections import Counter
from datetime import date
from pathlib import Path

import yaml

import guarded_load
import robots_gate
from agenda_parsers import PARSERS

MEETING_REGISTRIES = ("granicus", "civicplus", "drupal", "proudcity")  # registry/<name>-sources.yaml
CAP = 20  # fresh candidates per source per run; `agenda_items.cap` overrides
HELD_RETRY_DAYS = 28
HELD_RETRY_CAP = 5
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
        if not pick["retry"]:
            fresh.append(pick)
        elif _days_since((entry.get("hold") or {}).get("last_attempt"), today) >= held_retry_days:
            due.append(pick)
        else:
            waiting += 1
    selected = fresh[:cap] + due[:held_retry_cap]
    return {"selected": selected, "holds": holds, "excluded": dict(excluded), "backlog": len(fresh),
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


def session_hold(header: str, title: str, *, siblings: bool) -> str | None:
    """`agenda_session_mismatch` when the file's session is not the meeting's (Ross: one closed-session file filed
    under both of a day's meetings). With a same-day sibling the header must name the meeting's kind; without one,
    only a closed-only file (a closed session named, and no header line naming an open meeting) under a meeting
    that is not a closed session holds."""
    said, named = _kind(header), _kind(title)
    meeting = "closed" if "closed" in named else "special" if "special" in named else "regular"
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
