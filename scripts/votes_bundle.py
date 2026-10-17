#!/usr/bin/env python3
"""Votes Part B2, increment b: the additive bundle of Novato and Board votes. Nothing here touches the graph.

Every accepted Part A event (named or expanded) is either attached — one CAST_VOTE per member on its target
Decision — or held with exactly one reason, checked in this order (the first failing rule wins):

1. target: the Decision Part A matched it to, or a new Decision (id = the event's stable `vev-…` id);
   `decision_not_matched` when its Decision is conflicting, ambiguous or unmatched;
2. revalidation against the fresh baseline: re-reconciled assignment unchanged (`assignment_changed`); the
   Meeting is the event's (date, body) (`meeting_mismatch`); a matched Decision has the event's body and meeting
   and exactly one DECIDED_AT, to that Meeting (`decision_shape`); a new id is not taken (`new_id_taken`);
3. no CAST_VOTE already on the target (`existing_votes`); 4. no other accepted event on it (`target_collision`);
5. a carried/failed Decision is not contradicted by a carried/failed ledger outcome (`status_contradiction`);
   `unknown` against carried/failed attaches and is reported; `not_printed` never contradicts; an inferred (ALL)
   roll call that leaves out a member who moved or seconded any motion at that meeting is `attendance_doubt` —
   the minutes cannot say whether that member was in the room for this vote;
6. every member resolves through the reviewed mapping (`duplicate_member`, `voter_<reason>`, `person_collision`).
   No partial roll calls.

A new Decision carries only NEW_DECISION_PROPS (status from the printed outcome, never from counts) and one
DECIDED_AT to its Meeting. Edge `evidence` is a canonical JSON string: the member's own span when named, the
ALL sentinel plus the attendance trace when inferred. The repair inventory is built from the whole reconciliation,
not only from the events that were tried.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import shutil
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

from case_additive_plan import fingerprint, write_export
from votes_persons import MappingError, Resolver, load_mapping_answers, render_mapping_batch, validate_mapping
from votes_reconcile import reconcile
from votes_roster import parse_answers

VOTES = ("aye", "no", "abstain", "absent", "recused")
STATUS_OF = {"carried": "carried", "failed": "failed", "not_printed": "unknown"}
DECIDED = ("carried", "failed")
NEW_DECISION_PROPS = frozenset({"id", "meeting_id", "source_id", "decision_type", "status", "outcome", "item_number",
                                "display_label", "search_label", "search_terms"})
NEW_PERSON_PROPS = frozenset({"id", "name", "display_label", "search_label", "search_terms"})
CAST_VOTE_PROPS = frozenset({"vote", "ledger_event_id", "doc_sha256", "evidence", "disposition"})
VOTER_REASONS = ("out_of_term", "unknown_key", "missing_mapping", "ambiguous_person")
BODY_ORG = {"novato-city-council": "org-novato-city-council",
            "marin-county-bos": "org-marin-county-board-of-supervisors"}
BODY_NAME = {"novato-city-council": "Novato City Council", "marin-county-bos": "Marin County Board of Supervisors"}
BODY_FILING = {"novato-city-council": ("nvo", "City Council"), "marin-county-bos": ("cmar", "Board of Supervisors")}


class BundleError(Exception):
    pass


def _canonical(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


_FULL_LABEL = re.compile(r"[A-Z]{1,3}[.-]\d{1,3}")


def item_number(item: dict) -> str | None:
    """The printed item label: the top item, a sub-label that is already a full label (`J.1`, or `G.2` heard
    under J, `CB-2`), or top + a one-letter sub (`8a`). Anything else gets no item number — never an invented one."""
    top, sub = item.get("top"), item.get("sub")
    if not top:
        return None
    if not sub:
        return top
    if sub.startswith(top) or _FULL_LABEL.fullmatch(sub):
        return sub
    return f"{top}{sub}" if re.fullmatch(r"[a-z]", sub) else None


def decision_label(body_name: str, number: str | None, status: str) -> str:
    tail = {"carried": "carried", "failed": "failed"}.get(status, "outcome not recorded")
    return f"{body_name} vote{f', item {number}' if number else ''} — {tail}"


def evidence_string(ev: dict, member: dict, category: str) -> str:
    if member.get("inferred"):
        sentinel = [s for s in ev.get("sentinels", []) if s["category"] == category]
        if len(sentinel) != 1:
            raise BundleError(f"{ev['event_id']}: inferred {member['name']} needs one {category} sentinel")
        trace = sorted([s["start"], s["end"]] for s in ev["attendance"]["evidence"])
        return _canonical({"kind": "inferred", "sentinel": [sentinel[0]["span"]["start"], sentinel[0]["span"]["end"]],
                           "trace": trace})
    span = member.get("span")
    if not span:
        raise BundleError(f"{ev['event_id']}: named {member['name']} has no span")
    return _canonical({"kind": "named", "span": [span["start"], span["end"]]})


def _assignments(rows: list[dict]) -> dict[str, tuple]:
    """event id → ("matched", decision id) | ("new", event id); an event with more than one such row is a
    ("conflict", None) — it never attaches to whichever row came last."""
    found = defaultdict(list)
    for r in rows:
        if r["kind"] == "decision" and r["status"] == "matched":
            found[r["event_id"]].append(("matched", r["decision_id"]))
        elif r["kind"] == "event" and r["status"] == "new":
            found[r["event_id"]].append(("new", r["event_id"]))
    return {eid: rows[0] if len(rows) == 1 else ("conflict", None) for eid, rows in found.items()}


def _revalidate(events, recon_rows, nodes, body_org, scope_meetings=None) -> tuple[set[str], list[dict]]:
    """(events whose assignment differs when re-reconciled on this baseline, the re-reconciled Decision rows that
    differ from Part A's). With `scope_meetings`, only those meetings' Decisions are re-reconciled."""
    decisions = [n["properties"] for n in nodes if "Decision" in n["labels"]
                 and n["properties"].get("source_id") in body_org
                 and (scope_meetings is None or n["properties"].get("meeting_id") in scope_meetings)]
    fresh = reconcile(decisions, events, {})
    before, after = _assignments(recon_rows), _assignments(fresh)
    changed = {eid for eid in set(before) | set(after) if before.get(eid) != after.get(eid)}
    keep = ("status", "event_id", "candidates", "differences")
    old = {r["decision_id"]: {k: r.get(k) for k in keep} for r in recon_rows if r["kind"] == "decision"}
    differ = [r for r in fresh if r["kind"] == "decision"
              and old.get(r["decision_id"]) != {k: r.get(k) for k in keep}]
    return changed, differ


def build_bundle(events: list[dict], recon_rows: list[dict], resolver, mapping_rows: list[dict],
                 nodes: list[dict], edges: list[dict], *, body_org: dict[str, str] = BODY_ORG,
                 body_name: dict[str, str] = BODY_NAME, revalidate: bool = True,
                 holds: list[dict] | None = None, scope_meetings: set[str] | None = None) -> dict:
    """`holds`: {event_id, reason[, rule]} — reviewer holds from the spot check (rule `reviewer_hold`, the default)
    or the votes refresh's roster holds (rule `roster_hold`); each holds its event before any rule.
    `scope_meetings`: revalidate only those meetings' Decisions (a refresh batch's)."""
    events = sorted(events, key=lambda e: e["event_id"])
    accepted = [e for e in events if e["status"] in ("named", "expanded")]
    held_by_reviewer = {h["event_id"]: h["reason"] for h in holds or []}
    hold_rule = {h["event_id"]: h.get("rule", "reviewer_hold") for h in holds or []}
    actors = defaultdict(set)  # meeting → every member who moved or seconded any motion there (held events too)
    for e in events:
        for role in ("mover", "seconder"):
            if (e.get("motion") or {}).get(role):
                actors[e["meeting_id"]].add(e["motion"][role])
    unknown = sorted(set(held_by_reviewer) - {e["event_id"] for e in accepted})
    if unknown:
        raise BundleError(f"reviewer hold {unknown[0]} is not an accepted event")
    by_id = {n["id"]: n for n in nodes}
    decided_at, votes_into = defaultdict(list), Counter()
    for e in edges:
        if e["type"] == "DECIDED_AT":
            decided_at[e["start_id"]].append(e["end_id"])
        elif e["type"] == "CAST_VOTE":
            votes_into[e["end_id"]] += 1
    assigned = _assignments(recon_rows)
    changed, fresh_rows = _revalidate(events, recon_rows, nodes, body_org, scope_meetings) if revalidate \
        else (set(), [])
    targets = Counter(assigned[e["event_id"]][1] for e in accepted
                      if assigned.get(e["event_id"], ("", None))[1] is not None)
    new_person_name = {r["person_id"]: r["member"] for r in mapping_rows if r.get("status") == "verified_no_person"}

    out_nodes, out_edges, dispositions, status_report, repair = [], [], [], [], []
    used_new_persons = set()
    for ev in accepted:
        eid, body = ev["event_id"], ev["body"]
        kind, target = assigned.get(eid, (None, None))
        reason, voters, persons = None, [], {}
        keys = [m["name"] for cat in VOTES for m in ev["categories"].get(cat, [])]
        for key in sorted(set(keys)):  # every member, whatever rule fails first: the repair list needs them all
            got = resolver.resolve(body, key, ev["date"])
            if got[0] == "ok":
                persons[key] = got[1]
            else:
                near = resolver.nearest_term(body, key, ev["date"])
                voters.append({"key": key, "reason": got[1], "nearest_term": near["draft_id"] if near else None})
        meeting = by_id.get(ev["meeting_id"], {"labels": [], "properties": {}})
        decision = by_id.get(target, {"labels": [], "properties": {}}) if kind == "matched" else None
        if eid in held_by_reviewer:
            reason = hold_rule[eid]
        elif kind is None:
            reason = "decision_not_matched"
        elif kind == "conflict":
            reason = "assignment_conflict"
        elif eid in changed:
            reason = "assignment_changed"
        elif ("Meeting" not in meeting["labels"] or meeting["properties"].get("meeting_date") != ev["date"]
              or meeting["properties"].get("institution_id") != body_org.get(body)):
            reason = "meeting_mismatch"
        elif kind == "matched" and ("Decision" not in decision["labels"]
                                    or decision["properties"].get("source_id") != body
                                    or decision["properties"].get("meeting_id") != ev["meeting_id"]
                                    or decided_at.get(target) != [ev["meeting_id"]]):
            reason = "decision_shape"
        elif kind == "new" and eid in by_id:
            reason = "new_id_taken"
        elif votes_into[target]:
            reason = "existing_votes"
        elif targets[target] > 1:
            reason = "target_collision"
        elif kind == "matched" and decision["properties"].get("status") in DECIDED and ev["outcome"] in DECIDED \
                and decision["properties"]["status"] != ev["outcome"]:
            reason = "status_contradiction"
        elif ev["status"] == "expanded" and (actors[ev["meeting_id"]] & set(ev["attendance"].get("roster") or [])) \
                - set(keys):
            reason = "attendance_doubt"  # an inferred ALL leaves out someone who moved or seconded at this meeting
        if reason is None:
            if kind == "matched" and decision["properties"].get("status") == "unknown" and ev["outcome"] in DECIDED:
                status_report.append({"decision_id": target, "event_id": eid, "decision_status": "unknown",
                                      "ledger_outcome": ev["outcome"]})
            if len(keys) != len(set(keys)):
                reason = "duplicate_member"
            elif voters:
                reason = "voter_" + min((v["reason"] for v in voters), key=VOTER_REASONS.index)
            elif len(set(persons.values())) != len(persons):
                reason = "person_collision"
        row = {"event_id": eid, "body": body, "meeting_id": ev["meeting_id"], "date": ev["date"],
               "ledger_status": ev["status"], "target_kind": kind, "target": target,
               "reason": reason or "attached", "edges": 0}
        if voters:
            row["voters"] = voters
        if reason is None:
            for cat in VOTES:
                for m in ev["categories"].get(cat, []):
                    out_edges.append({"start_id": persons[m["name"]], "end_id": target, "type": "CAST_VOTE",
                                      "properties": {"vote": cat, "ledger_event_id": eid,
                                                     "doc_sha256": ev["doc_sha256"],
                                                     "evidence": evidence_string(ev, m, cat),
                                                     "disposition": "inferred" if m.get("inferred") else "named"}})
                    row["edges"] += 1
                    if persons[m["name"]] in new_person_name:
                        used_new_persons.add(persons[m["name"]])
            if kind == "new":
                out_nodes.append(_new_decision(ev, body_name[body]))
                out_edges.append({"start_id": eid, "end_id": ev["meeting_id"], "type": "DECIDED_AT",
                                  "properties": {}})
        else:
            repair.append({"kind": "event", "event_id": eid, "body": body, "meeting_id": ev["meeting_id"],
                           "date": ev["date"], "reason": reason, "target": target,
                           **({"note": held_by_reviewer[eid]} if eid in held_by_reviewer else {})})
            repair += [{"kind": "voter", "event_id": eid, "body": body, "date": ev["date"], **v} for v in voters]
        dispositions.append(row)
    for pid in sorted(used_new_persons):
        name = new_person_name[pid]
        out_nodes.append({"id": pid, "labels": ["Person"], "properties": {
            "id": pid, "name": name, "display_label": name, "search_label": name,
            "search_terms": f"{pid} {name.lower()}"}})
    for source, rows in (("part_a", [r for r in recon_rows if r["kind"] == "decision" and r["status"] != "matched"]),
                         ("fresh_baseline", fresh_rows)):
        for r in rows:
            repair.append({"kind": "decision", "source": source, "decision_id": r["decision_id"],
                           "meeting_id": r["meeting_id"], "status": r["status"], "reason": r.get("reason"),
                           "event_id": r.get("event_id"), "candidates": r.get("candidates", []),
                           "differences": r.get("differences", {}), "notes": r.get("notes", [])})
    repair += [{"kind": "status", **s} for s in status_report]
    order = {"decision": 0, "event": 1, "voter": 2, "status": 3}
    repair.sort(key=lambda r: (order[r["kind"]], r.get("source") or "", r.get("decision_id") or "",
                               r.get("event_id") or "", r.get("key") or ""))
    return {
        "nodes": sorted(out_nodes, key=lambda n: n["id"]),
        "edges": sorted(out_edges, key=lambda e: (e["start_id"], e["type"], e["end_id"])),
        "dispositions": dispositions,
        "status_report": status_report,
        "repair": repair,
    }


def _new_decision(ev: dict, body_name: str) -> dict:
    status = STATUS_OF[ev["outcome"]]
    number = item_number(ev.get("item") or {})
    label = decision_label(body_name, number, status)
    props = {"id": ev["event_id"], "meeting_id": ev["meeting_id"], "source_id": ev["body"],
             "decision_type": "roll_call_vote", "status": status, "outcome": ev["outcome"],
             "display_label": label, "search_label": label, "search_terms": f"{ev['event_id']} {label.lower()}"}
    if number:
        props["item_number"] = number
    return {"id": ev["event_id"], "labels": ["Decision"], "properties": props}


def accounting(bundle: dict, expected: dict | None = None) -> dict:
    """Counts per body by disposition, edges by vote, new Decisions per body, new Persons — and, given the
    expected-disposition manifest, whether the build equals it exactly."""
    by_body = defaultdict(Counter)
    for d in bundle["dispositions"]:
        by_body[d["body"]][d["reason"]] += 1
    out = {
        "events": len(bundle["dispositions"]),
        "by_body": {b: dict(sorted(c.items())) for b, c in sorted(by_body.items())},
        "edges_by_vote": dict(sorted(Counter(e["properties"]["vote"] for e in bundle["edges"]
                                             if e["type"] == "CAST_VOTE").items())),
        "new_decisions": dict(sorted(Counter(n["properties"]["source_id"] for n in bundle["nodes"]
                                             if "Decision" in n["labels"]).items())),
        "new_persons": sum(1 for n in bundle["nodes"] if "Person" in n["labels"]),
    }
    if expected is not None:
        keys = ("events", "by_body", "edges_by_vote", "new_decisions", "new_persons")
        out["matches_expected"] = all(out[k] == expected.get(k) for k in keys if k in expected) and \
            set(keys) <= set(expected)
    return out


SAMPLE_N = 20
NOTABLE_N = 30
NOTABLE_VOTES = ("no", "abstain", "recused")


def select_samples(bundle: dict, *, seed: int, n: int = SAMPLE_N, notable: int = NOTABLE_N) -> dict:
    """Per body: n seeded random attached events, then every other attached event with a no / abstain / recused
    edge, up to `notable`."""
    flagged = {e["properties"]["ledger_event_id"] for e in bundle["edges"]
               if e["type"] == "CAST_VOTE" and e["properties"]["vote"] in NOTABLE_VOTES}
    out = {}
    for body in sorted({d["body"] for d in bundle["dispositions"]}):
        attached = sorted(d["event_id"] for d in bundle["dispositions"]
                          if d["body"] == body and d["reason"] == "attached")
        rng = random.Random(f"{seed}:{body}")
        picked = sorted(rng.sample(attached, min(n, len(attached))))
        out[body] = {"random": picked,
                     "notable": [e for e in attached if e in flagged and e not in picked][:notable]}
    return out


def _excerpt(text: str, span: list[int] | dict, pad: int = 0) -> str:
    start, end = (span["start"], span["end"]) if isinstance(span, dict) else span
    return " ".join(text[max(0, start - pad):end + pad].split())


def render_samples(selection: dict, bundle: dict, events: dict[str, dict], texts: dict[str, str],
                   names: dict[str, str], *, seed: int, sources: dict[str, str] | None = None,
                   bundle_fp: dict[str, str] | None = None) -> str:
    """The spot-check sheet: each sampled event's motion, block and every edge with its evidence excerpt and the
    resolved Person; one agree/disagree line per item for the independent reviewer."""
    by_event = defaultdict(list)
    for e in bundle["edges"]:
        if e["type"] == "CAST_VOTE":
            by_event[e["properties"]["ledger_event_id"]].append(e)
    disp = {d["event_id"]: d for d in bundle["dispositions"]}
    lines = [f"# Votes B2 spot check (seed {seed})", "",
             "For each item, read the excerpts against the source minutes and record `S<n> agree` or "
             "`S<n> disagree: <why>` — is every member's vote right, and is each member the right Person?", ""]
    if bundle_fp:
        lines += [f"Bundle: nodes {bundle_fp['nodes.jsonl']} edges {bundle_fp['edges.jsonl']}", ""]
    k = 0
    for body, picks in selection.items():
        for label, ids in (("random attached", picks["random"]), ("no / abstain / recused", picks["notable"])):
            lines += [f"## {body}: {label} ({len(ids)})", ""]
            for eid in ids:
                k += 1
                ev, d = events[eid], disp[eid]
                text = texts.get(ev["doc_sha256"], "")
                motion = (ev.get("motion") or {}).get("text") or ""
                target = d["target"] if d["target_kind"] == "matched" else f"new Decision {eid}"
                lines += [f"### S{k}. {eid}", f"- {ev['date']} · item {item_number(ev.get('item') or {}) or '—'} · "
                          f"outcome {ev['outcome']} · target {target}",
                          f"- motion: {motion[:300]}"]
                if sources and ev["doc_sha256"] in sources:
                    lines.append(f"- source: {sources[ev['doc_sha256']]}")
                if ev.get("block"):
                    lines.append(f"- block: “{_excerpt(text, ev['block'])[:400]}”")
                for e in sorted(by_event[eid], key=lambda e: (VOTES.index(e["properties"]["vote"]), e["start_id"])):
                    p = e["properties"]
                    evidence = json.loads(p["evidence"])
                    if evidence["kind"] == "named":
                        quote = f"“{_excerpt(text, evidence['span'])}”"
                    else:
                        quote = (f"sentinel “{_excerpt(text, evidence['sentinel'])}”; attendance "
                                 + " | ".join(f"“{_excerpt(text, s)[:160]}”" for s in evidence["trace"]))
                    lines.append(f"- {e['start_id']} ({names.get(e['start_id'], '?')}): **{p['vote']}** "
                                 f"({p['disposition']}) — {quote}")
                lines += ["", f"Reviewer: `S{k} agree` / `S{k} disagree: …`", ""]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Files and CLI
# ---------------------------------------------------------------------------

STAGING_ROOT = Path.home() / "open-marin-staging" / "votes-b"
MAPPING_BATCH = "map-001"


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(x) for x in Path(path).read_text(encoding="utf-8").splitlines() if x.strip()]


def _write_jsonl(path: Path, rows) -> None:
    path.write_text("".join(_canonical(r) + "\n" for r in rows), encoding="utf-8")


def _write_json(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def input_paths(ledger: Path, roster: Path, mapping: Path, baseline: Path, expected: Path | None,
                holds: Path | None = None) -> dict[str, Path]:
    paths = {
        "ledger/events.jsonl": ledger / "events.jsonl",
        "ledger/reconciliation.jsonl": ledger / "reconciliation.jsonl",
        "ledger/build.json": ledger / "build.json",
        "roster/drafts.json": roster / "drafts.json",
        "roster/batch-001.json": roster / "batch-001.json",
        "roster/answers-001.txt": roster / "answers-001.txt",
        "mapping/mapping.json": mapping / "mapping.json",
        f"mapping/batch-{MAPPING_BATCH}.json": mapping / f"batch-{MAPPING_BATCH}.json",
        f"mapping/answers-{MAPPING_BATCH}.txt": mapping / f"answers-{MAPPING_BATCH}.txt",
        "baseline/nodes.jsonl": baseline / "nodes.jsonl",
        "baseline/edges.jsonl": baseline / "edges.jsonl",
    }
    if expected is not None:
        paths["expected-dispositions.json"] = expected
    if holds is not None:
        paths["reviewer-holds.json"] = holds
    return {k: Path(v).expanduser().resolve() for k, v in paths.items()}


def _binding_hashes(paths: dict[str, Path]) -> dict[str, str]:
    """The files a mapping batch is bound to (votes_persons.BINDING_INPUTS)."""
    return {"mapping.json": _sha(paths["mapping/mapping.json"]), "drafts.json": _sha(paths["roster/drafts.json"]),
            "batch-001.json": _sha(paths["roster/batch-001.json"]),
            "answers-001.txt": _sha(paths["roster/answers-001.txt"])}


def _roster(paths):
    drafts = json.loads(paths["roster/drafts.json"].read_text())
    items = json.loads(paths["roster/batch-001.json"].read_text())["items"]
    answers = parse_answers(paths["roster/answers-001.txt"].read_text(), "roster-001", items)
    return drafts, items, answers


def render_batch_files(paths: dict[str, Path], out_dir: Path) -> list[str]:
    """Validate the mapping table and write mapping/batch-map-001.{md,json}; returns the validation problems."""
    drafts, items, answers = _roster(paths)
    rows = json.loads(paths["mapping/mapping.json"].read_text())["rows"]
    nodes, edges = _jsonl(paths["baseline/nodes.jsonl"]), _jsonl(paths["baseline/edges.jsonl"])
    problems = validate_mapping(rows, drafts, items, answers, nodes, edges, body_org=BODY_ORG, body_filing=BODY_FILING)
    if problems:
        return problems
    md, batch = render_mapping_batch(MAPPING_BATCH, rows, nodes, edges, drafts=drafts, body_org=BODY_ORG,
                                     body_filing=BODY_FILING, input_hashes=_binding_hashes(paths))
    (out_dir / f"batch-{MAPPING_BATCH}.md").write_text(md + "\n", encoding="utf-8")
    _write_json(out_dir / f"batch-{MAPPING_BATCH}.json", batch)
    return []


def build_files(paths: dict[str, Path], out: Path, *, provisional: bool = False) -> dict:
    """Build the bundle into `out` (an empty or previous bundle dir under the staging root). With `provisional`,
    every mapping row counts as confirmed — a pre-review preview, marked so in inputs.json, never applied."""
    drafts, items, answers = _roster(paths)
    rows = json.loads(paths["mapping/mapping.json"].read_text())["rows"]
    nodes, edges = _jsonl(paths["baseline/nodes.jsonl"]), _jsonl(paths["baseline/edges.jsonl"])
    problems = validate_mapping(rows, drafts, items, answers, nodes, edges, body_org=BODY_ORG, body_filing=BODY_FILING)
    if problems:
        raise BundleError("mapping table: " + "; ".join(problems))
    batch = json.loads(paths[f"mapping/batch-{MAPPING_BATCH}.json"].read_text())
    if provisional:
        mapping_answers = [{"item": r["item"], "option": "confirm", "note": None} for r in rows]
        load_mapping_answers(f"batch {MAPPING_BATCH}\n", batch, _binding_hashes(paths))  # still bound
    else:
        mapping_answers = load_mapping_answers(paths[f"mapping/answers-{MAPPING_BATCH}.txt"].read_text(), batch,
                                               _binding_hashes(paths))
    as_of = json.loads(paths["ledger/build.json"].read_text())["as_of"]
    resolver = Resolver(drafts, items, answers, rows, mapping_answers, as_of=as_of)
    holds = json.loads(paths["reviewer-holds.json"].read_text())["holds"]
    bundle = build_bundle(_jsonl(paths["ledger/events.jsonl"]), _jsonl(paths["ledger/reconciliation.jsonl"]),
                          resolver, rows, nodes, edges, holds=holds)
    expected = json.loads(paths["expected-dispositions.json"].read_text()) \
        if "expected-dispositions.json" in paths else None
    acc = accounting(bundle, expected)

    _prepare_out(out)
    write_export(out, bundle["nodes"], bundle["edges"])
    _write_jsonl(out / "dispositions.jsonl", bundle["dispositions"])
    _write_jsonl(out / "status-report.jsonl", bundle["status_report"])
    _write_jsonl(out / "repair.jsonl", bundle["repair"])
    _write_json(out / "accounting.json", acc)
    (out / "accounting.md").write_text(_accounting_md(acc), encoding="utf-8")
    (out / "repair.md").write_text(_repair_md(bundle["repair"]), encoding="utf-8")
    _write_json(out / "inputs.json", {
        "provisional": provisional,
        "as_of": as_of,
        "inputs": {name: {"path": str(p), "sha256": _sha(p)} for name, p in sorted(paths.items())
                   if not (provisional and name == f"mapping/answers-{MAPPING_BATCH}.txt")},
    })
    return acc


def _prepare_out(out: Path) -> None:
    out, root = Path(out).expanduser().resolve(), STAGING_ROOT.expanduser().resolve()
    if out == root or not out.is_relative_to(root):
        raise BundleError(f"--out {out} must be a directory inside {root}")
    if out.exists():
        if any(out.iterdir()) and not (out / "inputs.json").exists():
            raise BundleError(f"{out} is neither empty nor a previous bundle")
        shutil.rmtree(out)
    out.mkdir(parents=True)


def _accounting_md(acc: dict) -> str:
    lines = ["# Votes B2 bundle accounting", "", f"Accepted Part A events: {acc['events']}", ""]
    for body, reasons in acc["by_body"].items():
        lines.append(f"- **{body}**: " + ", ".join(f"{k} {v}" for k, v in reasons.items()))
    lines += ["", "CAST_VOTE edges by vote: " + ", ".join(f"{k} {v}" for k, v in acc["edges_by_vote"].items()),
              "New Decisions: " + ", ".join(f"{k} {v}" for k, v in acc["new_decisions"].items()),
              f"New Persons: {acc['new_persons']}"]
    if "matches_expected" in acc:
        lines.append(f"Matches the expected-disposition manifest: **{acc['matches_expected']}**")
    return "\n".join(lines) + "\n"


def _repair_md(repair: list[dict]) -> str:
    lines = ["# Votes B2 repair list", ""]
    for kind, title in (("decision", "Existing Decisions not matched (nothing attached)"),
                        ("event", "Held accepted events"), ("voter", "Voters that did not resolve"),
                        ("status", "Status reports (not changed)")):
        rows = [r for r in repair if r["kind"] == kind]
        lines += [f"## {title} ({len(rows)})", ""]
        for r in rows:
            lines.append("- " + _canonical({k: v for k, v in r.items() if k != "kind"}))
        lines.append("")
    return "\n".join(lines)


def write_samples(bundle_dir: Path, ledger: Path, inventory: Path, baseline: Path, seed: int, out: Path) -> int:
    """Render the spot-check sheet from a built bundle; the excerpts come from the inventoried documents."""
    from votes_inventory import iter_documents, load_inventory, resolve_path
    from votes_text import canonical_text

    bundle = {"edges": _jsonl(bundle_dir / "edges.jsonl"), "nodes": _jsonl(bundle_dir / "nodes.jsonl"),
              "dispositions": _jsonl(bundle_dir / "dispositions.jsonl")}
    selection = select_samples(bundle, seed=seed)
    wanted = {eid for picks in selection.values() for ids in picks.values() for eid in ids}
    events = {e["event_id"]: e for e in _jsonl(ledger / "events.jsonl") if e["event_id"] in wanted}
    shas = {e["doc_sha256"] for e in events.values()}
    inv = load_inventory(inventory)
    texts, sources = {}, {}
    for _body, _row, doc in iter_documents(inv):
        if doc["sha256"] in shas and doc["sha256"] not in texts:
            path = resolve_path(inv, doc["paths"][0])
            texts[doc["sha256"]] = canonical_text(path, doc["format"]).text
            sources[doc["sha256"]] = str(path)
    names = {n["id"]: n["properties"].get("name") for n in _jsonl(baseline / "nodes.jsonl") if "Person" in n["labels"]}
    names.update({n["id"]: n["properties"]["name"] for n in bundle["nodes"] if "Person" in n["labels"]})
    out = Path(out).expanduser().resolve()
    if not out.is_relative_to(STAGING_ROOT.expanduser().resolve()):
        raise BundleError(f"--out {out} must be inside {STAGING_ROOT}")
    out.write_text(render_samples(selection, bundle, events, texts, names, seed=seed, sources=sources,
                                  bundle_fp=fingerprint(bundle_dir)), encoding="utf-8")
    return len(wanted)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("samples")
    for flag in ("--bundle", "--ledger", "--inventory", "--baseline", "--out"):
        sp.add_argument(flag, type=Path, required=True)
    sp.add_argument("--seed", type=int, required=True)
    for name in ("mapping-batch", "build", "check"):
        p = sub.add_parser(name)
        p.add_argument("--ledger", type=Path, required=True)
        p.add_argument("--roster", type=Path, required=True)
        p.add_argument("--mapping", type=Path, required=True)
        p.add_argument("--baseline", type=Path, required=True)
        if name != "mapping-batch":
            p.add_argument("--expected", type=Path, required=True)
            p.add_argument("--holds", type=Path, required=True, help="reviewer-holds.json ({holds: [...]})")
            p.add_argument("--out", type=Path, required=True)
            p.add_argument("--provisional", action="store_true")
    args = parser.parse_args(argv)
    if args.cmd == "samples":
        try:
            n = write_samples(args.bundle, args.ledger, args.inventory, args.baseline, args.seed, args.out)
        except (BundleError, OSError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        print(f"spot check: {n} events → {args.out}")
        return 0
    expected = getattr(args, "expected", None)
    paths = input_paths(args.ledger, args.roster, args.mapping, args.baseline, expected, getattr(args, "holds", None))
    try:
        if args.cmd == "mapping-batch":
            problems = render_batch_files(paths, Path(args.mapping))
            for p in problems:
                print(f"ERROR: {p}", file=sys.stderr)
            print(f"mapping batch: {len(problems)} problem(s)")
            return 1 if problems else 0
        if args.cmd == "build":
            acc = build_files(paths, args.out, provisional=args.provisional)
            print(_accounting_md(acc))
            return 0 if acc.get("matches_expected") else 1
        # check: rebuild twice into the staging root and require byte identity with --out
        problems = []
        with tempfile.TemporaryDirectory(dir=STAGING_ROOT, prefix=".check-") as tmp:
            again = Path(tmp) / "bundle"
            acc = build_files(paths, again, provisional=args.provisional)
            if not acc.get("matches_expected"):
                problems.append("the rebuild does not match the expected-disposition manifest")
            mine = sorted(p.relative_to(args.out) for p in Path(args.out).rglob("*") if p.is_file())
            theirs = sorted(p.relative_to(again) for p in again.rglob("*") if p.is_file())
            if mine != theirs:
                problems.append("file lists differ")
            problems += [f"{rel} differs" for rel in sorted(set(mine) & set(theirs))
                         if (Path(args.out) / rel).read_bytes() != (again / rel).read_bytes()]
        for p in problems:
            print(f"ERROR: {p}", file=sys.stderr)
        print(f"determinism check: {len(problems)} problem(s)")
        return 1 if problems else 0
    except (BundleError, MappingError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
