#!/usr/bin/env python3
"""Votes refresh, increment c: carry Part A + B2 forward over only the meetings a batch selects.

The parser, attendance, dispositions, attachment and hold rules are Part A's and B2's, unchanged
(votes_ledger.ledger_documents, votes_bundle.build_bundle). This module adds only what a repeatable refresh needs:

- roster-change evidence → persistent roster holds (a roll-call name with no confirmed term; contextual oath,
  appointment, resignation, vacancy or election evidence for the body) and the review packet;
- enforcement of every unresolved hold over every later batch (all votes of that body on/after its from-date);
- roster hints (a confirmed member absent from every usable roll call; no roll calls = insufficient evidence);
- candidate accounting (every selected document → candidates → events, none lost before the bundle).
"""
from __future__ import annotations

import hashlib
import re

# --- roster-change signals --------------------------------------------------------------------------------------

_SIGNALS = (
    ("oath", re.compile(r"\boath\s+of\s+office\b|\bsworn\s+in\b|\bswore\s+in\b|\bswearing[\s-]in\b|\bseated\b", re.I)),
    ("resignation", re.compile(r"\bresign(?:ed|s|ing|ation)?\b", re.I)),
    ("vacancy", re.compile(r"\bvacan(?:cy|cies|t)\b", re.I)),
    ("appointment", re.compile(r"\bappoint(?:ed|s|ing|ment)?\b", re.I)),
    ("election", re.compile(r"\b(?:newly\s+)?elected\b|\bcanvass\w*|\bdeclar\w*\s+the\s+results?\b", re.I)),
)
# the body as an institution (it acts, or its seat is the office) …
_BODY_INSTITUTION = {
    "novato-city-council": re.compile(r"\b(?:city\s+)?council\b(?!\s*(?:member|woman|man))|"
                                      r"\bcouncil(?:member|woman|man)s?\b(?=\s*(?:for|representing|of|,|\.|$))", re.I),
    "marin-county-bos": re.compile(r"\bboard\s+of\s+supervisors\b|\bthe\s+board\b(?!\s+of\b)|"
                                   r"\bsupervisors?\b(?=\s*(?:for|representing|of\s+district|,|\.|$))", re.I),
}
# … or a member by title (the member is sworn in, or resigns)
_MEMBER_TITLE = {
    "novato-city-council": re.compile(r"\bcouncil\s*(?:member|woman|man)s?\b|\bmayor\b", re.I),
    "marin-county-bos": re.compile(r"\bsupervisors?\b", re.I),
}
_BODY_OFFICE = {b: re.compile(f"{_BODY_INSTITUTION[b].pattern}|{_MEMBER_TITLE[b].pattern}", re.I)
                for b in _BODY_INSTITUTION}
_ROLE = re.compile(r"\b(?:vice\s+mayor|mayor\s+pro\s+tem\w*|mayor|vice\s+president|president|vice\s+chair|chair)\b",
                   re.I)
_OTHER_BODY = re.compile(r"\b(?:commissions?|committees?|authority|advisory|jpa|joint\s+powers|task\s+force|"
                         r"(?:sanitary|water|fire|school|hospital|transit|open\s+space)\s+district|"
                         r"board\s+of\s+(?:directors|trustees|education)|library|parks|council\s+of\b|"
                         r"(?:disaster|youth|citizens?|county|regional)\s+(?:and\s+\w+\s+)?(?:corps\s+)?council|"
                         r"\b(?!the\b|county\b|marin\b)\w+\s+board\b(?!\s+of\s+supervisors)|association|conservancy|oversight|service\s+area|csa\b|flood\s+control|"
                         r"zone\b|vector|pest\s+management|\w+\s+district\b(?<!\bdistrict\b)|"
                         # employment: an appointment of staff is not a seat on the body
                         r"public\s+employ\w*|city\s+(?:manager|attorney|clerk)|county\s+(?:administrator|counsel)|"
                         r"director|interim|staff|positions?|fte|personnel|representative|member\s+vacancy)\b", re.I)
_SEAT = re.compile(r"\bseat\b|\bdistrict\s*\d\b", re.I)
_CORRESPONDENCE = re.compile(r"\b(?:letter|e-?mail|correspondence|wrote|public\s+comment|speaker)\b", re.I)
_MINUTES = re.compile(r"\bminutes\b", re.I)
_SENTENCE_END = re.compile(r"(?<=[.!?])[”\"]?\s+(?=[“\"A-Z])")
_OFFICE_WINDOW = 90
CONTEXT_PARAGRAPHS = 3
# Calibrated on Part A's 593 documents: an unresolved appointment / vacancy / election mention is nearly always a
# commission, district or staff appointment, so it is a packet hint; an unresolved oath or resignation is a hold.
UNCERTAIN_HOLD_KINDS = ("oath", "resignation")


def _office_class(text: str, body: str) -> str | None:
    """The first office named in `text`: body | seat | role | other | None."""
    found = []
    for rank, (cls, rx) in enumerate((("other", _OTHER_BODY), ("role", _ROLE), ("body", _BODY_OFFICE[body]),
                                       ("seat", _SEAT))):
        m = rx.search(text)
        if m:
            found.append((m.start(), rank, cls))  # at the same position another body wins ("Council of Mayors")
    return min(found)[2] if found else None


def _quoted(paragraph: str) -> list[tuple[int, int]]:
    spans, open_at = [], None
    for i, ch in enumerate(paragraph):
        if ch == "“" or (ch == '"' and open_at is None):
            open_at = i
        elif (ch == "”" or ch == '"') and open_at is not None:
            spans.append((open_at, i))
            open_at = None
    if open_at is not None:
        spans.append((open_at, len(paragraph)))
    return spans


def _sentences(paragraph: str) -> list[tuple[int, str]]:
    out, start = [], 0
    for m in _SENTENCE_END.finditer(paragraph):
        out.append((start, paragraph[start:m.start()].strip()))
        start = m.end()
    out.append((start, paragraph[start:].strip()))
    return [(s, t) for s, t in out if t]


def _paragraphs(text: str, fmt: str):
    """(offset, paragraph): blank-line blocks in a PDF's layout text; every line of HTML/DOCX is a paragraph."""
    rx = r"[^\n]+" if fmt in ("html", "docx") else r"(?:[^\n]+\n?)+"
    return [(m.start(), m.group(0)) for m in re.finditer(rx, text)]


def roster_signals(ct, body: str, fmt: str = "pdf") -> list[dict]:
    """Roster-change evidence for `body` in one document: {kind, certainty, excerpt, span}. Certain when the
    office the verb acts on (or, failing that, the sentence's subject, or the previous sentence) is this body or
    its seat; no signal when it is another body or a role within the body (a mayoral rotation); uncertain when
    nothing resolves it — a review hold, never a silent pass. Quoted text, correspondence and public comment,
    and approval of minutes are never evidence."""
    text, out = ct.text, []
    paragraphs = _paragraphs(text, fmt)
    for pi, (p_off, para) in enumerate(paragraphs):
        if _CORRESPONDENCE.search(para):
            continue
        context = " ".join(p for _, p in paragraphs[max(0, pi - CONTEXT_PARAGRAPHS):pi])
        quotes = _quoted(para)
        sentences = _sentences(para)
        for i, (s_off, sent) in enumerate(sentences):
            if _MINUTES.search(sent):
                continue
            base = p_off + para.index(sent, s_off)
            seen_kinds = set()
            for kind, rx in _SIGNALS:
                for m in rx.finditer(sent):
                    at = base - p_off + m.start()
                    if any(a <= at <= b for a, b in quotes) or kind in seen_kinds:
                        continue
                    certainty = _certainty(sent, m, kind, body, sentences[i - 1][1] if i else "")
                    if certainty == "uncertain" and _OTHER_BODY.search(context):
                        certainty = None  # the section this sits in is another body's (its appointments)
                    if certainty is None:
                        continue
                    seen_kinds.add(kind)
                    out.append({"kind": kind, "certainty": certainty, "excerpt": " ".join(sent.split()),
                                "span": ct.locate(base, base + len(sent))})
    return sorted(out, key=lambda s: (s["span"]["start"], s["kind"]))


_OFFICE_PREP = re.compile(r"\b(?:to|as|from|on|in|for)\b", re.I)


def _certainty(sent: str, m, kind: str, body: str, previous: str) -> str | None:
    """The office: what follows the first preposition after the verb ("appoint X *to the council*", "resigned *from
    the Parks Commission*") — never the appointee's own title. Then the subject: the body as an institution for any
    signal; a member's title only for an oath or a resignation (the member is the one sworn in or leaving)."""
    after = sent[m.end():m.end() + _OFFICE_WINDOW]
    prep = _OFFICE_PREP.search(after)
    office = _office_class(after[prep.end():], body) if prep else None
    if office is None:
        office = {"other": "other", "role": "role"}.get(_office_class(after, body))
    if office in ("other", "role"):
        return None
    if office == "body":
        return "certain"
    before = sent[:m.start()]
    subject = _office_class(before, body)
    if subject == "other":
        return None
    member_subject = bool(_MEMBER_TITLE[body].search(before)) and kind in ("oath", "resignation")
    acting_body = bool(_BODY_INSTITUTION[body].search(before))
    if office == "seat":
        if _OTHER_BODY.search(sent):
            return None
        return "certain" if acting_body or member_subject or _BODY_INSTITUTION[body].search(previous) else "uncertain"
    if acting_body or member_subject:
        return "certain"
    if previous and _OTHER_BODY.search(previous):
        return None
    if previous and _BODY_INSTITUTION[body].search(previous):
        return "certain"
    return "uncertain"


# --- holds ------------------------------------------------------------------------------------------------------

def hold_id(*parts) -> str:
    return "hold-" + hashlib.sha256("\x1f".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:8]


def signal_holds(signals: list[dict], body: str, date: str, doc_sha256: str, meeting_id: str, path: str) -> list[dict]:
    """Certain signals and uncertain oaths/resignations hold; the other uncertain signals are hints (packet only)."""
    return [{"hold_id": hold_id(body, date, "roster_event", doc_sha256, s["span"]["start"], s["span"]["end"]),
             "kind": "roster_event" if s["certainty"] == "certain" else "roster_event_uncertain",
             "signal": s["kind"], "body": body, "from_date": date, "meeting_id": meeting_id,
             "doc_sha256": doc_sha256, "path": path, "excerpt": s["excerpt"], "span": s["span"]} for s in signals
            if s["certainty"] == "certain" or s["kind"] in UNCERTAIN_HOLD_KINDS]


def signal_hints(signals: list[dict]) -> list[dict]:
    return [s for s in signals if s["certainty"] == "uncertain" and s["kind"] not in UNCERTAIN_HOLD_KINDS]


def name_holds(events: list[dict], resolver, body: str) -> list[dict]:
    """A member key in any event of this body (any status: votes or the roll call behind them) with no confirmed
    term covering that meeting → one hold per key, from its earliest such meeting."""
    first: dict[str, tuple] = {}
    for ev in sorted((e for e in events if e["body"] == body), key=lambda e: (e["date"], e["event_id"])):
        keys = {m["name"] for cat in ev["categories"].values() for m in cat} | \
            set((ev.get("attendance") or {}).get("roster") or [])
        for key in sorted(keys):
            got = resolver.resolve(body, key, ev["date"])
            if got[0] != "ok" and got[1] in ("unknown_key", "out_of_term") and key not in first:
                first[key] = (ev, got[1])
    return [{"hold_id": hold_id(body, ev["date"], "name_without_term", key), "kind": "name_without_term",
             "body": body, "from_date": ev["date"], "key": key, "reason": reason, "meeting_id": ev["meeting_id"],
             "event_id": ev["event_id"], "doc_sha256": ev["doc_sha256"]}
            for key, (ev, reason) in sorted(first.items())]


def enforce_holds(events: list[dict], holds: list[dict]) -> list[dict]:
    """Every accepted event of a held body dated on/after an unresolved hold's from-date is held (rule
    `roster_hold`, reason = the earliest such hold), whatever batch or document order brought it."""
    live = sorted((h for h in holds if not h.get("resolved")), key=lambda h: (h["from_date"], h["hold_id"]))
    out = []
    for ev in sorted(events, key=lambda e: e["event_id"]):
        if ev["status"] not in ("named", "expanded"):
            continue
        h = next((h for h in live if h["body"] == ev["body"] and ev["date"] >= h["from_date"]), None)
        if h:
            out.append({"event_id": ev["event_id"], "reason": h["hold_id"], "rule": "roster_hold"})
    return out


def roster_hints(body: str, traces: dict[str, list], open_keys: list[str]) -> dict:
    """Hints only, never a term change: confirmed open-term members seen in no usable roll call of the batch."""
    rolls = [t for k, tr in sorted(traces.items()) for t in tr if t["kind"] == "roll_call" and t.get("certain_after")]
    if not rolls:
        return {"roll_calls": 0, "absent_from_all": [], "evidence": "insufficient evidence"}
    seen = {m for t in rolls for m in t.get("present_after") or []} | \
        {t.get("member") for tr in traces.values() for t in tr if t["kind"] == "absent_statement"}
    return {"roll_calls": len(rolls), "absent_from_all": sorted(set(open_keys) - seen), "evidence": "ok"}


# --- the batch adapter ------------------------------------------------------------------------------------------

class AdapterError(Exception):
    pass


def sha256_file(path) -> str:
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def as_of_for(docs: list[dict]) -> str:
    """Open confirmed terms run through the newest selected meeting (deterministic; no wall clock)."""
    return max(d["date"] for d in docs)


def refresh_inventory(docs: list[dict], repo) -> dict:
    """A votes-inventory-v1 view of only the selected documents, rooted at the repo (Stuart's saved files are read
    in place). Every document is re-hashed before it is parsed."""
    from pathlib import Path

    bodies: dict[str, dict] = {}
    for d in sorted(docs, key=lambda d: (d["body"], d["date"], d["meeting_id"])):
        path = Path(repo) / d["path"]
        if not path.is_file() or sha256_file(path) != d["sha256"]:
            raise AdapterError(f"{d['meeting_id']}: {d['path']} does not match its recorded sha256")
        bodies.setdefault(d["body"], {"meetings": [], "unplaced_documents": []})["meetings"].append({
            "meeting_id": d["meeting_id"], "date": d["date"], "title": d.get("title", ""), "body_class": "refresh",
            "minutes_record_id": d.get("record_id"), "minutes_url": d.get("url"), "gap": None,
            "documents": [{"paths": [f"repo/{d['path']}"], "sha256": d["sha256"], "bytes": path.stat().st_size,
                           "format": d["format"], "origin": "manual"}]})
    return {"schema": "votes-inventory-v1", "roots": {"repo": str(repo)}, "bodies": bodies}


def _effective_rows(rows: list[dict], applied_persons) -> list[dict]:
    """A verified_no_person row whose Person an authenticated earlier apply created is an ordinary mapped row now
    (no new Person is emitted again); the reviewed files themselves are unchanged."""
    return [dict(r, status="mapped") if r.get("status") == "verified_no_person" and r.get("person_id") in applied_persons
            else r for r in rows]


def build_batch(docs: list[dict], repo, nodes: list[dict], edges: list[dict], cfg: dict, *,
                holds: list[dict], reviewer_holds: list[dict]) -> dict:
    """Part A's parser and B2's bundle rules over only `docs` (accepted saved files), against `nodes`/`edges` (the
    batch's frozen baseline). `holds`: the registry's roster holds so far (resolved ones flagged); `cfg`: the pinned,
    already verified roster + mapping (votes_refresh_ledger.load_config)."""
    import votes_bundle
    import votes_refresh_expected
    from votes_ledger import ledger_documents
    from votes_persons import Resolver, validate_mapping
    from votes_reconcile import reconcile

    inv = refresh_inventory(docs, repo)
    events, cands, disp, ledger_docs, problems, texts, traces, _gaps = ledger_documents(inv)
    mids = {d["meeting_id"] for d in docs}
    decisions = [n["properties"] for n in nodes if "Decision" in n["labels"]
                 and n["properties"].get("meeting_id") in mids]
    recon = reconcile(decisions, events, {})

    applied = frozenset(cfg.get("applied_persons", []))
    mapping_problems = validate_mapping(cfg["rows"], cfg["drafts"], cfg["items"], cfg["answers"], nodes, edges,
                                        body_org=votes_bundle.BODY_ORG, body_filing=votes_bundle.BODY_FILING,
                                        applied_persons=applied)
    if mapping_problems:
        raise AdapterError("mapping table against this baseline: " + "; ".join(mapping_problems[:5]))
    rows = _effective_rows(cfg["rows"], applied)
    as_of = as_of_for(docs)
    resolver = Resolver(cfg["drafts"], cfg["items"], cfg["answers"], rows, cfg["mapping_answers"], as_of=as_of)

    from votes_text import CanonicalText
    known = {h["hold_id"] for h in holds}
    new_holds, hints, signals = [], {}, {}
    for d in sorted(docs, key=lambda d: (d["date"], d["meeting_id"])):
        key = f"{d['meeting_id']}.{d['sha256'][:8]}"
        ct = CanonicalText.from_lines(texts[key].split("\n"))
        sig = roster_signals(ct, d["body"], d["format"])
        signals[key] = sig
        new_holds += signal_holds(sig, d["body"], d["date"], d["sha256"], d["meeting_id"], d["path"])
    for body in sorted({d["body"] for d in docs}):
        new_holds += name_holds(events, resolver, body)
        open_keys = sorted({t["key"] for t in cfg["drafts"].get(body, {}).get("terms", []) if t.get("end") is None})
        hints[body] = {**roster_hints(body, {k: v for k, v in traces.items() if k.startswith(f"meeting-{body}-")},
                                      open_keys),
                       "uncertain_signals": [{"doc_key": k, **s} for k, sig in sorted(signals.items())
                                             if k.startswith(f"meeting-{body}-") for s in signal_hints(sig)]}
    dedup = {}
    for h in new_holds:
        if h["hold_id"] not in known:
            dedup.setdefault(h["hold_id"], h)
    new_holds = sorted(dedup.values(), key=lambda h: (h["body"], h["from_date"], h["hold_id"]))
    effective = list(holds) + new_holds
    event_holds = enforce_holds(events, effective)
    roster_held = {h["event_id"] for h in event_holds}
    review = [dict(h, rule="reviewer_hold") for h in reviewer_holds if h["event_id"] not in roster_held]
    bundle = votes_bundle.build_bundle(events, recon, resolver, rows, nodes, edges, holds=event_holds + review,
                                       scope_meetings=mids)
    expected = votes_refresh_expected.derive(
        events=events, recon=recon, drafts=cfg["drafts"], items=cfg["items"], answers=cfg["answers"], rows=rows,
        mapping_answers=cfg["mapping_answers"], nodes=nodes, edges=edges, holds=event_holds + review, as_of=as_of)
    ledger = {"events": events, "candidates": cands, "dispositions": disp, "documents": ledger_docs,
              "problems": problems, "traces": traces}
    accounting = candidate_accounting(docs, ledger, bundle)
    per_event = {d["event_id"]: d["reason"] for d in bundle["dispositions"]}
    accounting["matches_expected"] = per_event == expected["per_event"]
    if not accounting["matches_expected"]:
        accounting["problems"].append("per-event dispositions differ from the expected manifest: " + ", ".join(
            sorted(e for e in set(per_event) | set(expected["per_event"])
                   if per_event.get(e) != expected["per_event"].get(e))[:5]))
    return {"as_of": as_of, "documents_selected": docs, "ledger": ledger, "texts": texts, "reconciliation": recon,
            "signals": signals, "new_holds": new_holds, "effective_holds": effective, "event_holds": event_holds,
            "reviewer_holds": review, "hints": hints, "bundle": bundle,
            "bundle_accounting": votes_bundle.accounting(bundle), "expected": expected, "accounting": accounting,
            "attached": sum(1 for d in bundle["dispositions"] if d["reason"] == "attached")}


def candidate_accounting(docs: list[dict], ledger: dict, bundle: dict) -> dict:
    """Every selected document reaches the ledger; every candidate has exactly one disposition; every accepted
    event is in the bundle exactly once; every held ledger event is listed (none is lost before the bundle)."""
    problems = []
    seen_docs = {(d["meeting_id"], d.get("doc_sha256")) for d in ledger["documents"]}
    for d in docs:
        if (d["meeting_id"], d["sha256"]) not in seen_docs:
            problems.append(f"{d['meeting_id']}: document {d['sha256'][:8]} is not in the ledger")
    cand_ids = [c["cand_id"] for c in ledger["candidates"]]
    disp_ids = [x["cand_id"] for x in ledger["dispositions"]]
    if sorted(cand_ids) != sorted(set(cand_ids)) or sorted(disp_ids) != sorted(cand_ids):
        problems.append("candidates and their dispositions are not one-to-one")
    accepted = [e["event_id"] for e in ledger["events"] if e["status"] in ("named", "expanded")]
    held = [e["event_id"] for e in ledger["events"] if e["status"] == "held"]
    in_bundle = [x["event_id"] for x in bundle["dispositions"]]
    for eid in sorted(set(accepted) - set(in_bundle)):
        problems.append(f"{eid}: accepted but not in the bundle")
    for eid in sorted({e for e in in_bundle if in_bundle.count(e) > 1}):
        problems.append(f"{eid}: in the bundle more than once")
    for eid in sorted(set(in_bundle) - set(accepted)):
        problems.append(f"{eid}: in the bundle but not an accepted ledger event")
    problems += [f"ledger: {p}" for p in ledger["problems"]]
    return {"documents": len(docs), "candidates": len(cand_ids), "accepted_events": len(accepted),
            "ledger_held_events": sorted(held), "problems": problems}


def render_packet(hold: dict) -> str:
    """The review packet for one roster hold: what was seen, where, and how to answer."""
    what = {"name_without_term": f"`{hold.get('key')}` appears in a roll call or vote with no confirmed roster term "
                                 f"covering {hold['from_date']} ({hold.get('reason')}) — a new member, a returning "
                                 "one, or a misprint",
            "roster_event": f"roster-change wording ({hold.get('signal')}) for this body",
            "roster_event_uncertain": f"{hold.get('signal')} wording whose office could not be resolved"}[hold["kind"]]
    lines = [f"# Roster hold {hold['hold_id']} — {hold['body']}", "",
             f"- What: {what}.",
             f"- Meeting: `{hold['meeting_id']}` ({hold['from_date']}); document sha256 `{hold['doc_sha256']}`"]
    if hold.get("path"):
        lines.append(f"- Source: `{hold['path']}`" + (f", lines {hold['span']['line_start']}–{hold['span']['line_end']}"
                                                       if hold.get("span") else ""))
    if hold.get("excerpt"):
        lines.append(f"- Excerpt: “{hold['excerpt']}”")
    lines += ["", f"Every vote of {hold['body']} dated on or after {hold['from_date']} is held, in every batch, "
              "until this is answered.", "",
              "To answer, add one line to `roster-holds/resolutions.txt`:", "",
              f"    {hold['hold_id']} dismiss: <why there is no roster change>", "",
              "A real roster change (a new term, an end date) is not answered here: it needs a reviewed roster "
              "batch (a follow-up goal), and the hold stays until then.", ""]
    return "\n".join(lines)


# --- the pinned roster + mapping (verified once) ----------------------------------------------------------------

CONFIG = "config.json"
BODIES = ("marin-county-bos", "novato-city-council")


def _write_atomic(path, data: bytes) -> None:
    import os
    from pathlib import Path

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    with open(tmp, "wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _b2_applied_persons(votes_b) -> list[str]:
    """Person ids the authenticated B2 apply created: its state is APPLIED/PUBLISHED_VERIFIED under exactly the
    approval manifest on disk, and ops.json is byte-for-byte the approved one."""
    import json
    from pathlib import Path

    vb = Path(votes_b)
    state = json.loads((vb / "state.json").read_text())
    if state.get("state") not in ("APPLIED", "PUBLISHED_VERIFIED"):
        raise AdapterError(f"the B2 apply record is {state.get('state')}, not APPLIED")
    approval = (vb / "plan" / "approval-inputs.json").read_bytes()
    if hashlib.sha256(approval).hexdigest() != state.get("approval_sha256"):
        raise AdapterError("the B2 approval manifest is not the one that was applied")
    entry = json.loads(approval)["files"].get("plan/ops.json")
    ops = (vb / "plan" / "ops.json").read_bytes()
    if entry is None or hashlib.sha256(ops).hexdigest() != entry["sha256"]:
        raise AdapterError("B2 plan/ops.json is not the approved one")
    return sorted(n["id"] for n in json.loads(ops)["add_nodes"] if "Person" in n["labels"])


def init_config(refresh, *, part_a, votes_b) -> dict:
    """Verify the reviewed roster ONCE, offline, exactly as votes_ledger.build verified it (every cited source loaded
    and hashed, every quote found, both bodies clean), authenticate the B2 apply record, and pin every input."""
    import json
    from pathlib import Path

    from votes_inventory import load_inventory, resolve_path
    from votes_ledger import _roster_source
    from votes_roster import verify_drafts

    part_a, vb = Path(part_a), Path(votes_b)
    roster = part_a / "roster"
    files = {"roster/drafts.json": roster / "drafts.json", "roster/batch-001.json": roster / "batch-001.json",
             "roster/answers-001.txt": roster / "answers-001.txt", "ledger/build.json": part_a / "ledger" / "build.json",
             "inventory/inventory.json": part_a / "inventory" / "inventory.json",
             "mapping/mapping.json": vb / "mapping" / "mapping.json",
             "mapping/batch-map-001.json": vb / "mapping" / "batch-map-001.json",
             "mapping/answers-map-001.txt": vb / "mapping" / "answers-map-001.txt",
             "b2/state.json": vb / "state.json", "b2/approval-inputs.json": vb / "plan" / "approval-inputs.json",
             "b2/ops.json": vb / "plan" / "ops.json"}
    drafts = json.loads(files["roster/drafts.json"].read_text())
    if sorted(drafts) != list(BODIES):
        raise AdapterError(f"the roster drafts must cover exactly {BODIES}, not {sorted(drafts)}")
    built = json.loads(files["ledger/build.json"].read_text())
    if built.get("roster_drafts_sha256") != sha256_file(files["roster/drafts.json"]):
        raise AdapterError("Part A's ledger/build.json was built from other roster drafts")
    inv = load_inventory(part_a / "inventory")
    rows_by_id = {r["meeting_id"]: r for b in inv["bodies"].values() for r in b["meetings"]}
    sources, verification = {}, {}
    for body in BODIES:
        loaded = {}
        for t in drafts[body]["terms"]:
            for ev in t.get("evidence", []):
                ref = ev["source"]
                src = _roster_source(ref, inv, rows_by_id, {}, roster / "sources")
                if src is None:
                    raise AdapterError(f"{body}: evidence source {ref} does not resolve")
                if ref.startswith("minutes:"):
                    doc = rows_by_id[ref.partition(":")[2]]["documents"][0]
                    path = resolve_path(inv, doc["paths"][0])
                    if sha256_file(path) != doc["sha256"]:
                        raise AdapterError(f"{body}: {ref} no longer matches its inventoried sha256")
                    files[f"source/{ref}"] = path
                loaded[ref] = src
                sources[ref] = src["sha256"]
        verification[body] = verify_drafts(drafts[body], loaded)
        if verification[body]:
            raise AdapterError(f"{body}: roster verification: {verification[body][:3]} (a quote or support failed)")
    applied = _b2_applied_persons(vb)
    load_mapping(files)  # the review answers are still bound to the files they were drawn from
    cfg = {"schema": "votes-refresh-config-v1", "verification": verification, "roster_sources": dict(sorted(sources.items())),
           "applied_persons": applied,
           "files": {name: {"path": str(Path(p).resolve()), "sha256": sha256_file(p)} for name, p in sorted(files.items())}}
    _write_atomic(Path(refresh) / CONFIG, (json.dumps(cfg, indent=1, sort_keys=True) + "\n").encode())
    return cfg


def load_mapping(files: dict) -> tuple:
    import json

    from votes_persons import MappingError, load_mapping_answers
    from votes_roster import parse_answers

    items = json.loads(open(files["roster/batch-001.json"]).read())["items"]
    answers = parse_answers(open(files["roster/answers-001.txt"]).read(), "roster-001", items)
    rows = json.loads(open(files["mapping/mapping.json"]).read())["rows"]
    batch = json.loads(open(files["mapping/batch-map-001.json"]).read())
    binding = {"mapping.json": sha256_file(files["mapping/mapping.json"]),
               "drafts.json": sha256_file(files["roster/drafts.json"]),
               "batch-001.json": sha256_file(files["roster/batch-001.json"]),
               "answers-001.txt": sha256_file(files["roster/answers-001.txt"])}
    try:
        mapping_answers = load_mapping_answers(open(files["mapping/answers-map-001.txt"]).read(), batch, binding)
    except MappingError as exc:
        raise AdapterError(f"mapping answers: {exc}") from None
    return items, answers, rows, mapping_answers


def load_config(refresh) -> dict:
    """The pinned inputs, only if every pinned file is byte-for-byte what init verified."""
    import json
    from pathlib import Path

    raw = (Path(refresh) / CONFIG).read_bytes()
    cfg = json.loads(raw)
    for name, entry in sorted(cfg["files"].items()):
        p = Path(entry["path"])
        if not p.is_file() or sha256_file(p) != entry["sha256"]:
            raise AdapterError(f"pinned input {name} changed since init ({p}); re-run init after review")
    files = {name: Path(e["path"]) for name, e in cfg["files"].items()}
    items, answers, rows, mapping_answers = load_mapping(files)
    return {"drafts": json.loads(files["roster/drafts.json"].read_text()), "items": items, "answers": answers,
            "rows": rows, "mapping_answers": mapping_answers, "applied_persons": cfg["applied_persons"],
            "config_sha256": hashlib.sha256(raw).hexdigest()}
