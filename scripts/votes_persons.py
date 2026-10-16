#!/usr/bin/env python3
"""Votes Part B2, increment a: voters → Person nodes through a reviewed mapping table. Nothing is written to the graph.

Part A's ledger names members by surname key (`ALDER`); its roster gives each confirmed term a body, key and dates.
A key is never turned into a Person id by its spelling — same-name Person nodes are common and formal first names
differ from the minutes'. Instead a mapping table (authored in staging, one row per confirmed term) names the Person
and cites provenance the baseline export can prove:

- `seat_service`: the SeatService is HELD_BY that Person and its Seat sits at the body's org — proves the body;
- `filing`: the Form 700 filing is FILED_BY that Person; it proves the body only when its agency and department
  name it, otherwise it is shown as a related role;
- `same_member`: another row of the same body and key and Person, itself body-proved;
- a row nothing proves needs a `reviewer_basis`, and the batch marks it WEAK;
- `searched` (status `verified_no_person`): no baseline Person's id or name contains any of the patterns, so a new
  Person node is created under the row's id.

`validate_mapping` proves all of that; `render_mapping_batch` writes the review batch (goal-4a answers, as in
votes_roster); `Resolver` answers (body, key, meeting date) → Person over confirmed terms whose mapping row was
confirmed in review. Starts are inclusive; a stated or observed end is inclusive (handover meetings), a bound end
exclusive (the member was gone by then); an open term runs through the ledger's as-of date.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from collections import Counter, defaultdict

from votes_roster import RosterError, parse_answers

STATUSES = ("mapped", "missing_mapping", "verified_no_person")
DIRECT = ("seat_service", "filing")
KINDS = {"mapped": (*DIRECT, "same_member"), "missing_mapping": (*DIRECT, "same_member"),
         "verified_no_person": ("searched",)}
BINDING_INPUTS = ("mapping.json", "drafts.json", "batch-001.json", "answers-001.txt")
TERM_FIELDS = (("key", "key"), ("member", "member"), ("term_start", "start"), ("term_end", "end"))


class MappingError(Exception):
    pass


def covers(term: dict, date: str, *, as_of: str) -> bool:
    """Does this term cover a meeting on `date` (ISO)?"""
    if date < term["start"]:
        return False
    end = term.get("end")
    if end is None:
        return date <= as_of
    return date < end if term.get("end_kind") == "bound" else date <= end


def _confirmed_terms(drafts: dict, items: list[dict], answers: list[dict]) -> dict[str, tuple[str, dict]]:
    """draft_id → (body, term) for every roster term confirmed in review."""
    confirmed = {a["item"] for a in answers if a["option"] == "confirm"}
    ids = {i["draft_id"] for i in items if i["item"] in confirmed}
    return {t["draft_id"]: (body, t) for body, d in drafts.items() for t in d["terms"] if t["draft_id"] in ids}


def _norm(text: str) -> str:
    return re.sub(r"[^a-z]", "", text.lower())


def _seat_body_orgs(nodes: list[dict], edges: list[dict]) -> dict[str, set[str]]:
    """SeatService id → the orgs its Seat sits at (SeatService -FOR_SEAT-> Seat -AT_INSTITUTION-> org)."""
    labels = {n["id"]: set(n["labels"]) for n in nodes}
    seat_of, inst = defaultdict(set), defaultdict(set)
    for e in edges:
        if e["type"] == "FOR_SEAT" and "Seat" in labels.get(e["end_id"], set()):
            seat_of[e["start_id"]].add(e["end_id"])
        elif e["type"] == "AT_INSTITUTION" and "Seat" in labels.get(e["start_id"], set()):
            inst[e["start_id"]].add(e["end_id"])
    return {sid: {org for seat in seats for org in inst[seat]} for sid, seats in seat_of.items()}


def _filing_names_body(props: dict, rule: tuple[str, str] | None) -> bool:
    return bool(rule) and props.get("agency_id") == rule[0] and rule[1] in (props.get("department") or "")


class _Evidence:
    """What the baseline says about a row's provenance entries — shared by the validator and the batch."""

    def __init__(self, nodes, edges, body_org, body_filing):
        self.nodes = {n["id"]: n for n in nodes}
        self.rels = {(e["start_id"], e["type"], e["end_id"]) for e in edges}
        self.seat_orgs = _seat_body_orgs(nodes, edges)
        self.body_org, self.body_filing = body_org, body_filing

    def labels(self, nid):
        return set(self.nodes.get(nid, {}).get("labels", []))

    def props(self, nid):
        return self.nodes.get(nid, {}).get("properties", {})

    def check(self, p: dict, row: dict) -> tuple[list[str], bool]:
        """(problems, proves the body) for one seat_service or filing entry."""
        did, pid, body = row["draft_id"], row.get("person_id"), row["body"]
        if p["kind"] == "seat_service":
            sid = p.get("seat_service_id")
            if "SeatService" not in self.labels(sid) or (sid, "HELD_BY", pid) not in self.rels:
                return [f"{did}: SeatService {sid} is not HELD_BY {pid}"], False
            if self.body_org.get(body) not in self.seat_orgs.get(sid, set()):
                return [f"{did}: SeatService {sid} is not a seat of {body}"], False
            return [], True
        fid = p.get("filing_id")
        if "Filing" not in self.labels(fid) or (fid, "FILED_BY", pid) not in self.rels:
            return [f"{did}: filing {fid} is not FILED_BY {pid}"], False
        return [], _filing_names_body(self.props(fid), self.body_filing.get(body))


def _duplicate_items(rows: list[dict]) -> list[str]:
    counts = Counter(r.get("item") for r in rows)
    return [f"review item {item} is used by {n} rows" for item, n in sorted(counts.items(), key=str) if n > 1]


def _body_proved(row: dict, ev: _Evidence) -> bool:
    return any(ev.check(p, row) == ([], True) for p in row.get("provenance", []) if p.get("kind") in DIRECT)


def validate_mapping(rows: list[dict], drafts: dict, items: list[dict], answers: list[dict],
                     nodes: list[dict], edges: list[dict], *, body_org: dict[str, str],
                     body_filing: dict[str, tuple[str, str]]) -> list[str]:
    """Every problem with the table, checked against the confirmed roster and the baseline export.

    body_org: body → its org id (seats); body_filing: body → (Form 700 agency_id, department substring)."""
    terms = _confirmed_terms(drafts, items, answers)
    ev = _Evidence(nodes, edges, body_org, body_filing)
    persons = [n for n in nodes if "Person" in n["labels"]]
    problems = []
    by_draft = defaultdict(list)
    for r in rows:
        by_draft[r["draft_id"]].append(r)
    for draft_id in sorted(set(terms) - set(by_draft)):
        problems.append(f"{draft_id} has no mapping row")
    for draft_id, rs in sorted(by_draft.items()):
        if len(rs) > 1:
            problems.append(f"{draft_id} has {len(rs)} mapping rows")
        if draft_id not in terms:
            problems.append(f"{draft_id} is not a confirmed term")
    problems += _duplicate_items(rows)
    rows_by_draft = {r["draft_id"]: r for r in rows}
    for r in rows:
        did, pid = r["draft_id"], r.get("person_id")
        if did in terms:
            body, term = terms[did]
            for field, draft_field in (("body", None), *TERM_FIELDS):
                want = body if draft_field is None else term.get(draft_field)
                if r.get(field) != want:
                    problems.append(f"{did}: {field} {r.get(field)!r} is not the confirmed term's {want!r}")
        status = r.get("status")
        if status not in STATUSES:
            problems.append(f"{did}: status {status!r} is not one of {STATUSES}")
            continue
        for alt in r.get("alternates", []):
            if "Person" not in ev.labels(alt):
                problems.append(f"{did}: alternate {alt} is not a baseline Person")
        for p in r.get("provenance", []):
            if p.get("kind") not in KINDS[status]:
                problems.append(f"{did}: provenance kind {p.get('kind')!r} is not allowed for {status}")
        if status == "missing_mapping":
            for p in r.get("provenance", []):
                if p.get("kind") in DIRECT:
                    problems += ev.check(p, {**r, "person_id": pid})[0]
            continue
        if not isinstance(pid, str) or not pid:
            problems.append(f"{did}: person_id {pid!r} must be a node id")
            continue
        if status == "verified_no_person":
            if pid in ev.nodes:
                problems.append(f"{did}: new Person {pid} already exists in the baseline")
            patterns = [_norm(x) for p in r.get("provenance", []) if p.get("kind") == "searched"
                        for x in p.get("patterns", [])]
            if _norm(r["key"]) not in patterns or not all(patterns):
                problems.append(f"{did}: verified_no_person search patterns must include the surname "
                                f"{_norm(r['key'])!r}")
            for n in persons:
                hay = _norm(f"{n['id']} {n['properties'].get('name') or ''}")
                for pat in patterns:
                    if pat and pat in hay:
                        problems.append(f"{did}: pattern {pat!r} matches baseline Person {n['id']}")
            continue
        if "Person" not in ev.labels(pid):
            problems.append(f"{did}: {pid} is not a Person in the baseline")
        proved = False
        for p in r.get("provenance", []):
            if p.get("kind") in DIRECT:
                bad, proves = ev.check(p, r)
                problems += bad
                proved |= proves
            elif p.get("kind") == "same_member":
                other = rows_by_draft.get(p.get("draft_id"))
                if (other is None or other is r or other["body"] != r["body"] or other["key"] != r["key"]
                        or other.get("status") != "mapped" or other.get("person_id") != pid
                        or not _body_proved(other, ev)):
                    problems.append(f"{did}: same_member {p.get('draft_id')} is not a body-proved row of the same "
                                    f"member and Person")
                else:
                    proved = True
        if not proved and not (r.get("reviewer_basis") or "").strip():
            problems.append(f"{did}: nothing proves the body {r['body']} and there is no reviewer_basis")
    return problems


class Resolver:
    """(body, key, date) → Person over confirmed roster terms whose mapping row was confirmed in review."""

    def __init__(self, drafts: dict, items: list[dict], answers: list[dict], rows: list[dict],
                 mapping_answers: list[dict], *, as_of: str):
        self.as_of = as_of
        confirmed = {a["item"] for a in mapping_answers if a["option"] == "confirm"}
        self.person = {r["draft_id"]: r["person_id"] for r in rows
                       if r["item"] in confirmed and r.get("status") in ("mapped", "verified_no_person")
                       and isinstance(r.get("person_id"), str) and r["person_id"]}
        self.terms = defaultdict(list)
        for draft_id, (body, term) in sorted(_confirmed_terms(drafts, items, answers).items()):
            self.terms[(body, term["key"])].append(term)

    def resolve(self, body: str, key: str, date: str) -> tuple:
        terms = self.terms.get((body, key))
        if not terms:
            return ("held", "unknown_key")
        covering = [t for t in terms if covers(t, date, as_of=self.as_of)]
        if not covering:
            return ("held", "out_of_term")
        if any(t["draft_id"] not in self.person for t in covering):
            return ("held", "missing_mapping")
        if len({self.person[t["draft_id"]] for t in covering}) > 1:
            return ("held", "ambiguous_person")
        term = max(covering, key=lambda t: t["start"])
        return ("ok", self.person[term["draft_id"]], term["draft_id"])

    def nearest_term(self, body: str, key: str, date: str) -> dict | None:
        """The term of this member closest to `date` (for the repair list), or None for an unknown key."""
        def distance(t):
            end = t.get("end") or self.as_of
            return 0 if t["start"] <= date <= end else min(abs(_days(date, t["start"])), abs(_days(date, end)))
        terms = self.terms.get((body, key))
        return min(terms, key=lambda t: (distance(t), t["start"])) if terms else None


def _days(a: str, b: str) -> int:
    return (date.fromisoformat(a) - date.fromisoformat(b)).days


def _last_day(term: dict) -> str:
    """The last date a term covers (covers()'s rule), or 9999 for an open term."""
    end = term.get("end")
    if end is None:
        return "9999"
    return (date.fromisoformat(end) - timedelta(days=1)).isoformat() if term.get("end_kind") == "bound" else end


def _evidence_line(p: dict, row: dict, rows_by_draft: dict, ev: _Evidence, term: dict) -> str:
    body = row["body"]
    if p["kind"] == "seat_service":
        sid = p["seat_service_id"]
        props = ev.props(sid)
        start, end = props.get("started_at") or "?", props.get("ended_at") or "open"
        overlap = (props.get("started_at") or "0000") <= _last_day(term) and \
            term["start"] <= (props.get("ended_at") or "9999")
        problems, proves = ev.check(p, row)
        tail = f"and is a seat of {body}" if proves else f"— PROBLEM: {'; '.join(problems)}"
        return (f"SeatService {sid} ({start} → {end}, {'overlaps' if overlap else 'does not overlap'} this term) "
                f"is HELD_BY this Person {tail}")
    if p["kind"] == "filing":
        fid = p["filing_id"]
        props = ev.props(fid)
        role = f"{props.get('department') or '?'} / {props.get('job_title') or '?'}"
        problems, proves = ev.check(p, row)
        if problems:
            return f"Form 700 filing {fid} — PROBLEM: {'; '.join(problems)}"
        if proves:
            return f"Form 700 filing {fid} ({role}) is FILED_BY this Person and names {body}"
        return f"Form 700 filing {fid} is FILED_BY this Person — related role only: {role} — it does not name {body}"
    if p["kind"] == "same_member":
        other = rows_by_draft.get(p["draft_id"], {})
        return f"Same Person as item {other.get('item', '?')} ({p['draft_id']})"
    pats = ", ".join(f"“{x}”" for x in p.get("patterns", []))
    return f"No Person node matches {pats}; a new Person {row['person_id']} is created"


def _require_binding(hashes: dict[str, str], what: str) -> None:
    missing = [n for n in BINDING_INPUTS if not hashes.get(n)]
    if missing:
        raise MappingError(f"{what} lacks the hash of {', '.join(missing)}")


def render_mapping_batch(batch_id: str, rows: list[dict], nodes: list[dict], edges: list[dict], *, drafts: dict,
                         body_org: dict[str, str], body_filing: dict[str, tuple[str, str]],
                         input_hashes: dict[str, str]) -> tuple[str, dict]:
    """The review batch for Stuart (markdown) and its machine-readable form, bound to the inputs it was drawn from."""
    _require_binding(input_hashes, "the batch")
    dup = _duplicate_items(rows)
    if dup:
        raise MappingError("; ".join(dup))
    term_of = {t["draft_id"]: t for d in drafts.values() for t in d["terms"]}
    ev = _Evidence(nodes, edges, body_org, body_filing)
    rows_by_draft = {r["draft_id"]: r for r in rows}
    persons_of = defaultdict(set)
    for r in rows:
        if r.get("person_id") and r["status"] != "missing_mapping":
            persons_of[(r["body"], r["key"])].add(r["person_id"])
    name = lambda pid: ev.props(pid).get("name") or "new"  # noqa: E731
    lines = [f"# Person mapping review — {batch_id}", "",
             "Each item maps one confirmed roster term to the Person node its votes will attach to. Nothing is "
             "written to the graph from this file.", "",
             f"To answer: start a file with the line `batch {batch_id}`, then one line per item: `<item> confirm`, "
             "`<item> reject`, `<item> defer`, or `<item> correct: <what is right>`. An item not confirmed holds "
             "that term's votes. The answers are bound to the table and roster files this batch was drawn from.", ""]
    items = []
    for r in sorted(rows, key=lambda r: int(r["item"])):
        n = r["item"]
        lines.append(f"### {n}. {r['member']} ({r['body']}, key {r['key']}) — {r['term_start']} → "
                     f"{r['term_end'] or 'open'}")
        if r["status"] == "missing_mapping":
            lines.append("- **No Person chosen** — this term's votes are held.")
        else:
            lines.append(f"- Person: `{r['person_id']}` ({name(r['person_id'])})"
                         + (" — new node" if r["status"] == "verified_no_person" else ""))
        term = term_of.get(r["draft_id"], {"start": r["term_start"], "end": r["term_end"], "end_kind": None})
        lines += [f"- {_evidence_line(p, r, rows_by_draft, ev, term)}" for p in r.get("provenance", [])]
        if r["status"] == "mapped" and not _body_proved(r, ev) and not any(
                p.get("kind") == "same_member" for p in r.get("provenance", [])):
            lines.append(f"- **WEAK — rests on your judgment:** {r.get('reviewer_basis') or '(no basis given)'}")
        if len(persons_of[(r["body"], r["key"])]) > 1:
            lines.append(f"- **Split member:** {r['key']} maps to different Persons in different terms: "
                         + ", ".join(sorted(persons_of[(r["body"], r["key"])])))
        if r.get("alternates"):
            lines.append("- Also in the graph, not chosen: "
                         + ", ".join(f"{a} ({name(a)})" for a in r["alternates"]))
        if r.get("notes"):
            lines.append(f"- _{r['notes']}_")
        lines += ["", f"Answer: `{n} confirm` · `{n} correct: …` · `{n} reject` · `{n} defer`", ""]
        items.append({"item": n, "draft_id": r["draft_id"], "body": r["body"], "person_id": r.get("person_id"),
                      "options": ["confirm", "correct", "reject", "defer"]})
    return "\n".join(lines), {"batch": batch_id, "inputs": dict(sorted(input_hashes.items())), "items": items}


def load_mapping_answers(text: str, batch: dict, current_hashes: dict[str, str]) -> list[dict]:
    """The review answers, only if every input the batch was drawn from is byte-for-byte what it was."""
    _require_binding(batch.get("inputs", {}), f"batch {batch.get('batch')}")
    for name, sha in sorted(batch["inputs"].items()):
        if current_hashes.get(name) != sha:
            raise MappingError(f"{name} changed since batch {batch['batch']} was rendered; re-render and re-review")
    try:
        return parse_answers(text, batch["batch"], batch["items"])
    except RosterError as exc:
        raise MappingError(str(exc)) from None
