#!/usr/bin/env python3
"""Votes refresh: the expected disposition of every accepted event, derived independently of the bundle builder.

A separate derivation (it imports neither votes_bundle nor votes_persons nor the refresh adapter): from the ledger
events, the scoped reconciliation, the confirmed roster terms, the reviewed mapping, the baseline and the batch's
holds, the reason each accepted event is held, or `attached`. The bundle must equal it event for event.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, timedelta

ORG = {"novato-city-council": "org-novato-city-council", "marin-county-bos": "org-marin-county-board-of-supervisors"}
CATEGORIES = ("aye", "no", "abstain", "absent", "recused")
VOTER_ORDER = ("out_of_term", "unknown_key", "missing_mapping", "ambiguous_person")


def _last_day(term: dict, as_of: str) -> str:
    if term.get("end") is None:
        return as_of
    if term.get("end_kind") == "bound":
        return (date.fromisoformat(term["end"]) - timedelta(days=1)).isoformat()
    return term["end"]


def derive(*, events, recon, drafts, items, answers, rows, mapping_answers, nodes, edges, holds, as_of) -> dict:
    confirmed_items = {a["item"] for a in answers if a["option"] == "confirm"}
    confirmed_drafts = {i["draft_id"] for i in items if i["item"] in confirmed_items}
    terms = [(b, t) for b in drafts for t in drafts[b]["terms"] if t["draft_id"] in confirmed_drafts]
    mapped_items = {a["item"] for a in mapping_answers if a["option"] == "confirm"}
    person_of = {r["draft_id"]: r["person_id"] for r in rows if r["item"] in mapped_items
                 and r.get("status") in ("mapped", "verified_no_person") and r.get("person_id")}

    def person(body, key, day):
        mine = [t for b, t in terms if b == body and t["key"] == key]
        if not mine:
            return None, "unknown_key"
        cover = [t for t in mine if t["start"] <= day <= _last_day(t, as_of)]
        if not cover:
            return None, "out_of_term"
        if any(t["draft_id"] not in person_of for t in cover):
            return None, "missing_mapping"
        found = {person_of[t["draft_id"]] for t in cover}
        return (found.pop(), None) if len(found) == 1 else (None, "ambiguous_person")

    by_id = {n["id"]: n for n in nodes}
    decided_at, votes_in = defaultdict(list), Counter()
    for e in edges:
        if e["type"] == "DECIDED_AT":
            decided_at[e["start_id"]].append(e["end_id"])
        elif e["type"] == "CAST_VOTE":
            votes_in[e["end_id"]] += 1
    targets = defaultdict(list)
    for r in recon:
        if r["kind"] == "decision" and r["status"] == "matched":
            targets[r["event_id"]].append(("matched", r["decision_id"]))
        elif r["kind"] == "event" and r["status"] == "new":
            targets[r["event_id"]].append(("new", r["event_id"]))
    held = {h["event_id"]: h.get("rule", "reviewer_hold") for h in holds}
    actors = defaultdict(set)
    for e in events:
        for role in ("mover", "seconder"):
            if (e.get("motion") or {}).get(role):
                actors[e["meeting_id"]].add(e["motion"][role])
    accepted = [e for e in events if e["status"] in ("named", "expanded")]
    aimed = Counter(targets[e["event_id"]][0][1] for e in accepted if len(targets.get(e["event_id"], [])) == 1)

    per_event, votes, new_decisions = {}, Counter(), Counter()
    for e in sorted(accepted, key=lambda e: e["event_id"]):
        eid, body = e["event_id"], e["body"]
        t = targets.get(eid, [])
        kind, target = t[0] if len(t) == 1 else (None, None)
        meeting = by_id.get(e["meeting_id"], {"labels": [], "properties": {}})
        decision = by_id.get(target, {"labels": [], "properties": {}})
        keys = [m["name"] for c in CATEGORIES for m in e["categories"].get(c, [])]
        if eid in held:
            reason = held[eid]
        elif not t:
            reason = "decision_not_matched"
        elif len(t) > 1:
            reason = "assignment_conflict"
        elif "Meeting" not in meeting["labels"] or meeting["properties"].get("meeting_date") != e["date"] \
                or meeting["properties"].get("institution_id") != ORG.get(body):
            reason = "meeting_mismatch"
        elif kind == "matched" and ("Decision" not in decision["labels"]
                                    or decision["properties"].get("source_id") != body
                                    or decision["properties"].get("meeting_id") != e["meeting_id"]
                                    or decided_at.get(target) != [e["meeting_id"]]):
            reason = "decision_shape"
        elif kind == "new" and eid in by_id:
            reason = "new_id_taken"
        elif votes_in[target]:
            reason = "existing_votes"
        elif aimed[target] > 1:
            reason = "target_collision"
        elif kind == "matched" and decision["properties"].get("status") in ("carried", "failed") \
                and e["outcome"] in ("carried", "failed") and decision["properties"]["status"] != e["outcome"]:
            reason = "status_contradiction"
        elif e["status"] == "expanded" and \
                (actors[e["meeting_id"]] & set(e["attendance"].get("roster") or [])) - set(keys):
            reason = "attendance_doubt"
        else:
            resolved = {k: person(body, k, e["date"]) for k in set(keys)}
            fails = sorted({why for _, why in resolved.values() if why}, key=VOTER_ORDER.index)
            if len(keys) != len(set(keys)):
                reason = "duplicate_member"
            elif fails:
                reason = "voter_" + fails[0]
            elif len({p for p, _ in resolved.values()}) != len(resolved):
                reason = "person_collision"
            else:
                reason = "attached"
                for c in CATEGORIES:
                    votes[c] += len(e["categories"].get(c, []))
                if kind == "new":
                    new_decisions[body] += 1
        per_event[eid] = reason
    by_body = defaultdict(Counter)
    for e in accepted:
        by_body[e["body"]][per_event[e["event_id"]]] += 1
    return {"per_event": per_event,
            "counts": {"events": len(accepted), "by_body": {b: dict(sorted(c.items())) for b, c in sorted(by_body.items())},
                       "edges_by_vote": dict(sorted((k, v) for k, v in votes.items() if v)),
                       "new_decisions": dict(sorted(new_decisions.items()))}}
