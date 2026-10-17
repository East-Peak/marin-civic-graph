#!/usr/bin/env python3
"""Votes Part A, increment g: build the audited vote-evidence ledger from the frozen inventory.

    python scripts/votes_ledger.py build --inventory ~/open-marin-staging/votes/inventory \\
        --out ~/open-marin-staging/votes/ledger --roster-drafts ~/open-marin-staging/votes/roster/drafts.json \\
        --seed 20261014 --as-of 2026-10-14
    python scripts/votes_ledger.py check --out ~/open-marin-staging/votes/ledger

`build` verifies every inventoried document's sha256, then per document: canonical text → vote
events (parser) → events holding an unconsumed vote label are held → attendance and ALL expansion →
the independent candidate scan and its dispositions → partition and evidence validation and the
printed-tally check. Then the reconciliation with the existing Decisions and the roster evidence.
Everything it writes is sorted and timestamp-free. `check` rebuilds into a temporary directory and
requires every file to be byte-identical (integrity and determinism in one), and requires the
recorded checks to be empty. Nothing here touches the graph.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import random
import shutil
import sys
import tempfile
from pathlib import Path

from votes_attendance import resolve
from votes_blocks import is_transcript, parse_document
from votes_candidates import check_partition, dispose, document_disposition, events_to_hold, scan
from votes_inventory import iter_documents, load_inventory, resolve_path, verify_documents
from votes_reconcile import check_reconciliation, reconcile
from votes_roster import coverage as roster_coverage
from votes_roster import render_batch, validate_seatservices, verify_drafts
from votes_text import canonical_text
from votes_validate import validate_document

BODY_ORG = {"org-novato-city-council": "novato-city-council",
            "org-marin-county-board-of-supervisors": "marin-county-bos"}
SEATS = [f"District {i}" for i in range(1, 6)]
SAMPLE_N = 20
NOTABLE_N = 30
STAGING_ROOT = Path.home() / "open-marin-staging" / "votes"


class LedgerError(Exception):
    pass


def _guard_out(out: Path, staging_root: Path, inputs: list[Path]) -> Path:
    """The output directory is deleted and rewritten, so it must lie strictly inside the staging
    root and never be, contain or sit inside an input."""
    out, root = Path(out).resolve(), Path(staging_root).resolve()
    if out == root or not out.is_relative_to(root):
        raise ValueError(f"--out {out} must be a directory inside {root}")
    for inp in inputs:
        inp = Path(inp).resolve()
        if out == inp or out.is_relative_to(inp) or inp.is_relative_to(out):
            raise ValueError(f"--out {out} overlaps the input {inp}")
    return out


def _dumps(obj) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False)


def _write_jsonl(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(_dumps(r) + "\n" for r in rows), encoding="utf-8")


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, sort_keys=True, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def _export_rows(inv: dict):
    export = Path(inv["export"]["path"])
    for name in ("nodes", "edges"):
        got = hashlib.sha256((export / f"{name}.jsonl").read_bytes()).hexdigest()
        if got != inv["export"][f"{name}_sha256"]:
            raise LedgerError(f"the frozen export's {name}.jsonl no longer matches the inventory's sha256")
    nodes = [json.loads(x) for x in (export / "nodes.jsonl").read_text().splitlines() if x.strip()]
    edges = [json.loads(x) for x in (export / "edges.jsonl").read_text().splitlines() if x.strip()]
    return nodes, edges


def _decisions_and_services(inv: dict):
    nodes, edges = _export_rows(inv)
    by_id = {n["id"]: n for n in nodes}
    decisions = [n["properties"] for n in nodes if "Decision" in n["labels"]
                 and n["properties"].get("source_id") in inv["bodies"]]
    out = collections.defaultdict(list)
    seat_of, holder, inst = {}, {}, {}
    for e in edges:
        if e["type"] == "FOR_SEAT":
            seat_of[e["start_id"]] = e["end_id"]
        elif e["type"] == "HELD_BY":
            holder[e["start_id"]] = e["end_id"]
        elif e["type"] == "AT_INSTITUTION":
            inst[e["start_id"]] = e["end_id"]
    for n in nodes:
        if "SeatService" not in n["labels"]:
            continue
        seat = by_id.get(seat_of.get(n["id"], ""), {}).get("properties", {})
        body = BODY_ORG.get(inst.get(seat_of.get(n["id"], ""), ""))
        person = by_id.get(holder.get(n["id"], ""), {}).get("properties", {})
        if body and person.get("name"):
            p = n["properties"]
            out[body].append({"id": n["id"], "key": person["name"].split()[-1].upper(), "seat": seat.get("name"),
                              "started_at": p.get("started_at"), "ended_at": p.get("ended_at")})
    return decisions, out


def _excerpt(text: str, loc: dict | None, pad: int = 0) -> str:
    if not loc:
        return ""
    return " ".join(text[max(0, loc["start"] - pad):loc["end"] + pad].split())


def _roster_source(ref: str, inv: dict, rows_by_id: dict, texts: dict, web_root: Path) -> dict | None:
    """A cited roster source: `minutes:<meeting>` (its inventoried document), `agenda:<meeting>` (the
    cached agenda under the raw root), or `web:<path>` (a page captured into the roster's sources)."""
    from votes_inventory import sniff_format

    kind, _, ident = ref.partition(":")
    if kind == "minutes":
        row = rows_by_id.get(ident)
        if not row or not row["documents"]:
            return None
        doc = row["documents"][0]
        text = texts.get(f"{ident}.{doc['sha256'][:8]}") or \
            canonical_text(resolve_path(inv, doc["paths"][0]), doc["format"]).text
        return {"text": text, "sha256": doc["sha256"], "url": row["minutes_url"], "date": row["date"]}
    if kind == "agenda":
        body = next((b for b in inv["bodies"] if ident.startswith(f"meeting-{b}-")), None)
        folder = Path(inv["roots"]["raw"]) / (body or "") / "agendas"
        path = next((p for p in sorted(folder.glob(f"{ident}.*"))), None) if body else None
    elif kind == "web":
        path = (web_root / ident).resolve()
        if not path.is_relative_to(web_root.resolve()):
            return None
    else:
        return None
    if path is None or not path.is_file():
        return None
    data = path.read_bytes()
    fmt = sniff_format(data)
    if fmt is None:
        return None
    return {"text": canonical_text(path, fmt).text, "sha256": hashlib.sha256(data).hexdigest(), "url": ref,
            "date": None}


def ledger_documents(inv: dict, base: Path | None = None):
    """Part A's per-document pipeline over every inventoried document (canonical text → events → held labels →
    attendance and ALL expansion → candidate scan and dispositions → partition, evidence and tally checks).
    Returns (events, candidates, dispositions, documents, problems, texts, traces, gaps by meeting); the votes
    refresh runs it unchanged over the meetings it selects."""
    events_all, cands_all, disp_all, docs_all, problems = [], [], [], [], []
    texts: dict[str, str] = {}
    traces: dict[str, list] = {}
    gaps_by_meeting: dict[str, str] = {}
    for body, b in sorted(inv["bodies"].items()):
        for row in b["meetings"]:
            if row["gap"]:
                gaps_by_meeting[row["meeting_id"]] = row["gap"]
                docs_all.append({"body": body, "meeting_id": row["meeting_id"], "date": row["date"], "class": "gap",
                                 "gap": row["gap"], "doc_sha256": None})
    for body, row, doc in iter_documents(inv):
        if row["gap"]:
            continue
        ct = canonical_text(resolve_path(inv, doc["paths"][0], base), doc["format"])
        key = f"{row['meeting_id']}.{doc['sha256'][:8]}"
        texts[key] = ct.text
        transcript = is_transcript(ct)
        events = parse_document(ct, body=body, meeting_id=row["meeting_id"], doc_sha256=doc["sha256"])
        cands = scan(ct, doc_sha256=doc["sha256"])
        for eid, reason in events_to_hold(cands, events).items():
            ev = next(e for e in events if e["event_id"] == eid)
            ev["status"] = "held"
            ev["hold_reasons"] = sorted(set(ev["hold_reasons"]) | {reason})
        resolved, trace = resolve(ct, body=body, events=events)
        att = [t["span"] for t in trace]
        disp = dispose(ct, cands, resolved, attendance_spans=att, transcript=transcript)
        problems += [f"{key}: {p}" for p in check_partition(cands, disp, resolved, ct=ct, attendance_spans=att,
                                                            transcript=transcript)]
        problems += [f"{key}: {p}" for p in validate_document(ct, body, resolved)]
        for ev in resolved:
            t = ev.get("tally")
            if ev["status"] in ("named", "expanded") and t and not t.get("unrecognized") and \
                    (t["a"] != len(ev["categories"]["aye"]) or t["n"] != len(ev["categories"]["no"])):
                problems.append(f"{ev['event_id']}: accepted with counts that differ from its printed tally")
            ev["doc_key"] = key
            ev["date"] = row["date"]
        traces[key] = trace
        dd = document_disposition(ct, cands, doc_sha256=doc["sha256"])
        if transcript:
            dd["class"] = "transcript"
        docs_all.append({"body": body, "meeting_id": row["meeting_id"], "date": row["date"], "events": len(resolved),
                         **dd})
        events_all += resolved
        cands_all += [{**c, "body": body, "meeting_id": row["meeting_id"]} for c in cands]
        disp_all += [{**d, "body": body, "meeting_id": row["meeting_id"]} for d in disp]

    return events_all, cands_all, disp_all, docs_all, problems, texts, traces, gaps_by_meeting


def build(inventory_dir: Path, out: Path, *, roster_drafts: Path, seed: int, as_of: str,
          staging_root: Path = STAGING_ROOT) -> dict:
    inventory_dir = Path(inventory_dir)
    inv = load_inventory(inventory_dir)
    out = _guard_out(out, staging_root, [inventory_dir, Path(inv["export"]["path"]), Path(roster_drafts).parent
                                         if Path(roster_drafts).parent.resolve() != Path(staging_root).resolve()
                                         else Path(roster_drafts)] + [Path(p) for p in inv["roots"].values()])
    verify_documents(inv)
    _export_rows(inv)  # the frozen export must still be the one inventoried
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    events_all, cands_all, disp_all, docs_all, problems, texts, traces, gaps_by_meeting = ledger_documents(inv)

    decisions, services = _decisions_and_services(inv)
    in_inventory = {r["meeting_id"] for b in inv["bodies"].values() for r in b["meetings"]}
    recon_gaps = {d["meeting_id"]: gaps_by_meeting.get(d["meeting_id"], "out_of_window")
                  for d in decisions if d["meeting_id"] not in in_inventory or d["meeting_id"] in gaps_by_meeting}
    recon = reconcile(decisions, events_all, recon_gaps)
    problems += check_reconciliation(decisions, events_all, recon)

    # roster
    drafts_by_body = json.loads(Path(roster_drafts).read_text())
    sources = {}
    rows_by_id = {r["meeting_id"]: r for b in inv["bodies"].values() for r in b["meetings"]}
    roster_out = {"verification": {}, "seatservices": {}, "coverage": {}}
    for body, drafts in sorted(drafts_by_body.items()):
        src = {}
        for t in drafts["terms"]:
            for e in t.get("evidence", []):
                loaded = _roster_source(e["source"], inv, rows_by_id, texts, Path(roster_drafts).parent / "sources")
                if loaded:
                    src[e["source"]] = loaded
        sources.update(src)
        roster_out["verification"][body] = verify_drafts(drafts, src)
        problems += [f"roster {body}: {p}" for p in roster_out["verification"][body]]
        roster_out["seatservices"][body] = validate_seatservices(drafts, services.get(body, []))
        window = inv["windows"].get(body, ["2019-01-01", as_of])[0]
        roster_out["coverage"][body] = roster_coverage(drafts, SEATS, window, as_of)
    md, items = render_batch("roster-001", drafts_by_body, roster_out["seatservices"], roster_out["coverage"],
                             sources=sources, as_of=as_of)

    # outputs
    events_all.sort(key=lambda e: e["event_id"])
    _write_jsonl(out / "events.jsonl", events_all)
    _write_jsonl(out / "candidates.jsonl", sorted(cands_all, key=lambda c: c["cand_id"]))
    _write_jsonl(out / "dispositions.jsonl", sorted(disp_all, key=lambda d: d["cand_id"]))
    _write_jsonl(out / "documents.jsonl", sorted(docs_all, key=lambda d: (d["meeting_id"], d.get("doc_sha256") or "")))
    _write_jsonl(out / "reconciliation.jsonl", recon)
    for key, trace in sorted(traces.items()):
        _write_jsonl(out / "attendance" / f"{key}.jsonl", trace)
    _write_json(out / "roster" / "drafts.json", drafts_by_body)
    _write_json(out / "roster" / "verification.json", roster_out["verification"])
    _write_json(out / "roster" / "seatservices.json", roster_out["seatservices"])
    _write_json(out / "roster" / "coverage.json", roster_out["coverage"])
    (out / "roster" / "batch-001.md").write_text(md, encoding="utf-8")
    _write_json(out / "roster" / "batch-001.json", {"batch": "roster-001", "items": items})

    cov = _coverage(inv, docs_all, events_all, disp_all, recon)
    _write_json(out / "coverage.json", cov)
    (out / "coverage.md").write_text(_coverage_md(cov), encoding="utf-8")
    (out / "samples.md").write_text(_samples(events_all, traces, texts, seed), encoding="utf-8")
    _write_json(out / "check.json", {"problems": sorted(problems)})
    _write_json(out / "build.json", {"inventory": str(inventory_dir), "inventory_sha256": hashlib.sha256(
        (inventory_dir / "inventory.json").read_bytes()).hexdigest(), "roster_drafts": str(roster_drafts),
        "roster_drafts_sha256": hashlib.sha256(Path(roster_drafts).read_bytes()).hexdigest(),
        "seed": seed, "as_of": as_of, "staging_root": str(Path(staging_root))})
    return {"problems": len(problems), "events": len(events_all), "candidates": len(cands_all)}


def _coverage(inv, docs, events, disp, recon) -> dict:
    out = {}
    for body in sorted(inv["bodies"]):
        rows = inv["bodies"][body]["meetings"]
        meetings = [r for r in rows if r["gap"] != "not_in_scope_body"]
        d_rows = [r for r in recon if r["kind"] == "decision" and r["meeting_id"].startswith(f"meeting-{body}-")]
        new = [r for r in recon if r["kind"] == "event" and r["meeting_id"].startswith(f"meeting-{body}-")]
        cand = collections.defaultdict(collections.Counter)
        for d in disp:
            if d["body"] == body:
                cand[d["class"]][d["reason"]] += 1
        evs = [e for e in events if e["body"] == body]
        decisions = dict(collections.Counter(r["status"] for r in d_rows))
        out[body] = {
            "inventory_rows": len(rows),
            "out_of_scope": len(rows) - len(meetings),
            "out_of_scope_classes": dict(collections.Counter(r["body_class"] for r in rows
                                                             if r["gap"] == "not_in_scope_body")),
            "meetings": len(meetings),
            "documents": sum(1 for d in docs if d["body"] == body and d["class"] != "gap"),
            "gaps": dict(collections.Counter(r["gap"] for r in meetings if r["gap"])),
            "documents_without_candidates": sum(1 for d in docs if d["body"] == body and d["class"] == "no_candidates"),
            "transcripts": sum(1 for d in docs if d["body"] == body and d["class"] == "transcript"),
            "events": dict(collections.Counter(e["status"] for e in evs)),
            "held_reasons": dict(collections.Counter(r for e in evs for r in e["hold_reasons"])),
            "candidates": {k: dict(v) for k, v in sorted(cand.items())},
            "existing_decisions": {**decisions, "total": len(d_rows),
                                   "unmatched_reasons": dict(collections.Counter(
                                       r["reason"] for r in d_rows if r["status"] == "unmatched"))},
            "held_for_repair": sum(decisions.get(k, 0) for k in ("conflicting", "ambiguous", "unmatched")),
            "new_events": {"accepted": sum(1 for r in new if r["event_status"] != "held"),
                           "held": sum(1 for r in new if r["event_status"] == "held")},
        }
    return out


def _coverage_md(cov: dict) -> str:
    def kv(d):
        return ", ".join(f"{k} {v}" for k, v in sorted(d.items()) if not isinstance(v, dict)) or "none"
    lines = ["# Vote ledger coverage", ""]
    for body, c in cov.items():
        ed = c["existing_decisions"]
        lines += [f"## {body}", "",
                  f"- inventory rows {c['inventory_rows']}; out of scope {c['out_of_scope']} ({kv(c['out_of_scope_classes'])})",
                  f"- meetings in scope: {c['meetings']}; documents parsed: {c['documents']} "
                  f"(without vote candidates: {c['documents_without_candidates']}; caption transcripts: {c['transcripts']})",
                  f"- gaps (in scope): {kv(c['gaps'])}",
                  f"- events: {kv(c['events'])}",
                  f"- held reasons: {kv(c['held_reasons'])}",
                  "- candidates: " + "; ".join(f"{cls}: {kv(r)}" for cls, r in sorted(c["candidates"].items())),
                  f"- existing Decisions ({ed['total']}): {kv(ed)}; unmatched reasons: {kv(ed['unmatched_reasons'])}",
                  f"- held for repair (conflicting + ambiguous + unmatched): {c['held_for_repair']}",
                  f"- new events (no Decision): accepted {c['new_events']['accepted']}, held {c['new_events']['held']}",
                  ""]
    return "\n".join(lines) + "\n"


def _event_md(ev: dict, text: str) -> list[str]:
    cats = "; ".join(f"{c}: {', '.join(n['name'] for n in v)}" for c, v in ev["categories"].items() if v)
    status = ev["status"] + (f": {', '.join(ev['hold_reasons'])}" if ev["status"] == "held" else "")
    lines = [f"### {ev['event_id']} ({ev['date']}, {status})",
             f"- motion: {(ev['motion'] or {}).get('text', '')[:300]}",
             f"- mover/seconder: {(ev['motion'] or {}).get('mover')} / {(ev['motion'] or {}).get('seconder')}",
             f"- outcome {ev['outcome']}; tally {(ev.get('tally') or {}).get('printed')}; {cats}"]
    if ev.get("item_exceptions"):
        lines.append("- prose exceptions: " + "; ".join(f"{x['name']} {x['kind']}: “{_excerpt(text, x['span'])}”"
                                                        for x in ev["item_exceptions"]))
    lines.append(f"- block (lines {ev['block']['line_start']}–{ev['block']['line_end']}): “{_excerpt(text, ev['block'])}”"
                 if ev.get("block") else "- no block")
    if ev["status"] == "expanded":
        lines.append("- attendance evidence: " + " | ".join(f"“{_excerpt(text, s)[:200]}”"
                                                            for s in ev["attendance"]["evidence"]))
    return lines + [""]


def _samples(events, traces, texts, seed) -> str:
    lines = [f"# Vote ledger samples (seed {seed})", "",
             "Random named and expanded events per body (seeded), then every dissent, recusal, abstention and "
             "attendance change up to 30 per body, each with its excerpt.", ""]
    for body in sorted({e["body"] for e in events}):
        evs = sorted((e for e in events if e["body"] == body), key=lambda e: e["event_id"])
        rng = random.Random(f"{seed}:{body}")
        lines += [f"## {body}", ""]
        for status in ("named", "expanded"):
            pool = [e for e in evs if e["status"] == status]
            pick = sorted(rng.sample(pool, min(SAMPLE_N, len(pool))), key=lambda e: e["event_id"])
            lines += [f"## {body}: {len(pick)} random {status} of {len(pool)}", ""]
            for e in pick:
                lines += _event_md(e, texts[e["doc_key"]])
        for label, test in (("dissents", lambda e: bool(e["categories"]["no"])),
                            ("recusals", lambda e: bool(e["categories"]["recused"])
                             or any(x["kind"] == "recused" for x in e.get("item_exceptions", []))),
                            ("abstentions", lambda e: bool(e["categories"]["abstain"])
                             or any(x["kind"] == "abstain" for x in e.get("item_exceptions", [])))):
            found = [e for e in evs if test(e)]  # held ones too: they are the hard cases
            lines += [f"## {body}: {label} ({min(len(found), NOTABLE_N)} of {len(found)})", ""]
            for e in found[:NOTABLE_N]:
                lines += _event_md(e, texts[e["doc_key"]])
        changes = [(k, t) for k, tr in sorted(traces.items()) if k.startswith(f"meeting-{body}-")
                   for t in tr if t["kind"] in ("arrive", "depart", "absent_statement", "uncertain", "recess",
                                                "reconvene", "all_present")]
        lines += [f"## {body}: attendance changes ({min(len(changes), NOTABLE_N)} of {len(changes)})", ""]
        for k, t in changes[:NOTABLE_N]:
            lines.append(f"- {k} line {t['span']['line_start']}: {t['kind']} {t['member']} — "
                         f"“{_excerpt(texts[k], t['span'])[:240]}”")
        lines.append("")
    return "\n".join(lines) + "\n"


def check(out: Path) -> list[str]:
    out = Path(out)
    params = json.loads((out / "build.json").read_text())
    problems = list(json.loads((out / "check.json").read_text())["problems"])
    root = Path(params["staging_root"])
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root, prefix=".check-") as tmp:
        again = Path(tmp) / "ledger"
        build(Path(params["inventory"]), again, roster_drafts=Path(params["roster_drafts"]), seed=params["seed"],
              as_of=params["as_of"], staging_root=Path(params["staging_root"]))
        mine = sorted(p.relative_to(out) for p in out.rglob("*") if p.is_file())
        theirs = sorted(p.relative_to(again) for p in again.rglob("*") if p.is_file())
        if mine != theirs:
            problems.append("the output's file list differs from a rebuild")
        for rel in sorted(set(mine) & set(theirs)):
            if (out / rel).read_bytes() != (again / rel).read_bytes():
                problems.append(f"{rel}: differs from a rebuild")
    return problems


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--inventory", required=True, type=Path)
    b.add_argument("--out", required=True, type=Path)
    b.add_argument("--roster-drafts", required=True, type=Path)
    b.add_argument("--seed", type=int, required=True)
    b.add_argument("--as-of", required=True)
    b.add_argument("--staging-root", type=Path, default=STAGING_ROOT)
    c = sub.add_parser("check")
    c.add_argument("--out", required=True, type=Path)
    args = ap.parse_args(argv)
    if args.cmd == "build":
        summary = build(args.inventory, args.out, roster_drafts=args.roster_drafts, seed=args.seed, as_of=args.as_of,
                        staging_root=args.staging_root)
        print(json.dumps(summary, sort_keys=True))
        return 0 if summary["problems"] == 0 else 1
    problems = check(args.out)
    for p in problems[:50]:
        print(p)
    print(f"{len(problems)} problems")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
