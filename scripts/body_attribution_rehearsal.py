#!/usr/bin/env python3
"""Prove the weekly run cannot undo the body attribution: the real chain, on a fake graph seeded with the candidate.

    body_attribution_rehearsal.py rehearse --plan <plan dir> --responses <recorded store> --frozen <iso>
        --ingest-runs <staged copy: ledger.jsonl, meeting-identity.json> --control <council meeting id> --out <dir>

For each variant (the agenda-items stage as on main, and switched on) it runs refresh_weekly.stage -> ingest.py ->
the civicplus adapter (replaying the recorded responses through the robots gate, the clock frozen) ->
refresh_weekly.load, whose meeting step is the real `normalize_meetings.py --load` into the fake graph. The root
holds copies of the run ledger (so the source's floors are the operator's own) and of the meeting identity cache.
Only the backup, reconciliation, export and bake are stand-ins (crosswalk_rehearsal.RehearsalRunner). A run that
is held or skips the source fails the proof. `checks` then requires: the control meeting loaded, no moved meeting
in the capture or in any MERGE row, and every moved meeting's node and relationships exactly the candidate's; and
the identity caches (staged copy, and as the run left it) hand no moved id to its old source; with the agenda
stage on, it ran and created AgendaItems. `--mode fill` fetches only what the store lacks (robots-gated); a second,
`replay` run on a fresh root then sends nothing. Staging only.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
REPO = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))

import body_attribution as ba  # noqa: E402
import guarded_load  # noqa: E402

SOURCE = "corte-madera-town-council"
REGISTRY = "civicplus"


def _relationships(edges, ids: set[str]) -> Counter:
    return Counter(ba.stable_line(e) for e in edges if e["start_id"] in ids or e["end_id"] in ids)


def checks(*, candidate: tuple[list, list], post: tuple[list, list], capture: dict | None, overlay: list[dict],
           source_state: dict, run_status: str, guard: dict[str, str], control: str,
           agenda: dict | None = None, agenda_required: bool = False) -> list[dict]:
    """`agenda_required`: the variant switches the agenda-items stage on, so `agenda` (its outcome) must be ok."""
    """The proof's checks for one variant, each {name, ok, detail}."""
    out = []

    def check(name, ok, detail=None):
        out.append({"name": name, "ok": bool(ok), "detail": detail})

    moved = set(guard)
    captured = {m.get("meeting_id") for m in (capture or {}).get("meetings") or []}
    check("the run loaded (not held, not failed)", run_status in ("awaiting_publish_approval", "published"),
          run_status)
    check("the source was accepted with a nonempty capture", source_state.get("ok") and captured,
          {k: source_state.get(k) for k in ("ok", "rows", "last_good_rows", "reasons")})
    check(f"the control council meeting {control} is in the capture", control in captured)
    merged = {r["merge_node"]["id"] for r in overlay if "merge_node" in r}
    check(f"the control council meeting {control} was loaded (a MERGE row)", control in merged)
    check("no moved meeting is in the capture", not (captured & moved), sorted(captured & moved)[:5])
    touched = merged | {r["merge_edge"][k] for r in overlay if "merge_edge" in r for k in ("start_id", "end_id")}
    check("no MERGE row touches a moved meeting", not (touched & moved), sorted(touched & moved)[:5])
    creates = {r["node"]["id"] for r in overlay if "node" in r} | \
        {r["edge"][k] for r in overlay if "edge" in r for k in ("start_id", "end_id")}
    check("no create touches a moved meeting", not (creates & moved), sorted(creates & moved)[:5])
    cand = {n["id"]: n for n in candidate[0] if n["id"] in moved}
    after = {n["id"]: n for n in post[0] if n["id"] in moved}
    differ = sorted(i for i in moved if cand.get(i) != after.get(i))
    check("every moved meeting's node is exactly the candidate's", not differ and len(cand) == len(moved), differ[:5])
    check("every relationship touching a moved meeting is exactly the candidate's",
          _relationships(candidate[1], moved) == _relationships(post[1], moved))
    at = Counter(e["start_id"] for e in post[1] if e["type"] == "AT_INSTITUTION" and e["start_id"] in moved
                 and e["end_id"] == guard[e["start_id"]])
    stray = [e for e in post[1] if e["type"] == "AT_INSTITUTION" and e["start_id"] in moved
             and e["end_id"] != guard[e["start_id"]]]
    check("every moved meeting has exactly one AT_INSTITUTION, to its body",
          not stray and all(at[i] == 1 for i in moved), len(stray))
    if agenda_required:
        items = [r["node"] for r in overlay if "node" in r and "AgendaItem" in r["node"]["labels"]]
        check("the agenda-items stage ran and created AgendaItems", (agenda or {}).get("ok") and items,
              {"stage": agenda, "created": len(items)})
    return out


def _make_root(out: Path, ingest_runs: Path) -> Path:
    """A weekly root: the civicplus registry with only the council source weekly, the scripts, staged copies of the
    run ledger and the identity cache (never the operator's files themselves)."""
    import yaml

    root = out / "root"
    (root / "registry").mkdir(parents=True)
    doc = yaml.safe_load((REPO / "registry" / f"{REGISTRY}-sources.yaml").read_text())
    for source in doc["sources"]:
        if source["id"] != SOURCE and source.get("schedule") == "weekly":
            source["schedule"] = "manual"
    (root / "registry" / f"{REGISTRY}-sources.yaml").write_text(yaml.safe_dump(doc, sort_keys=False))
    if (REPO / "registry" / "crosswalks").is_dir():
        shutil.copytree(REPO / "registry" / "crosswalks", root / "registry" / "crosswalks")
    (root / "scripts").symlink_to(SCRIPTS, target_is_directory=True)
    runs = root / "data" / "ingest-runs"
    runs.mkdir(parents=True)
    for name in ("ledger.jsonl", "meeting-identity.json"):
        shutil.copyfile(Path(ingest_runs) / name, runs / name)
    return root


def run_variant(name: str, out: Path, *, candidate: Path, responses: Path, frozen: datetime, ingest_runs: Path,
                agenda: bool, mode: str = "replay") -> dict:
    import refresh_weekly as rw
    from agenda_rehearsal import AgendaRunner
    from crosswalk_rehearsal import ResponseStore

    out = Path(out) / name
    out.mkdir(parents=True)
    graph = guarded_load.FakeGraphPort.create(out / "graph", seed=candidate)
    root = _make_root(out, ingest_runs)
    runner = AgendaRunner(store=ResponseStore(responses), mode=mode, frozen=frozen,
                          graph_uri=f"fakegraph://{graph}", seed=Path(candidate), override=None, lock_dir=out / "locks")
    env = {"NEO4J_URI": "bolt://localhost:7688", "NEO4J_USER": "neo4j", "NEO4J_PASSWORD": "rehearsal-unused",
           "NEO4J_DATABASE": "neo4j", "PATH": "/usr/bin:/bin:/opt/homebrew/bin",
           rw.CF_STAGING_ENV: str(out / "cf-staging"), rw.VOTES_REFRESH_ENV: str(out / "votes-refresh")}

    def refuse(*_):
        raise RuntimeError("the rehearsal reaches for no network outside the robots-gated steps")

    ctx = rw.Context(root=root, runner=runner, env=env, python=sys.executable, now=lambda: frozen,
                     meeting_registries=(REGISTRY,), staged_sources={}, ping=refuse, netfile_fetch=refuse,
                     prepare_campaign_exports=False, agenda_items=agenda)
    staged = rw.stage(ctx)
    loaded = rw.load(ctx, staged["run_id"]) if staged["status"] == "awaiting_load_approval" else staged
    source = loaded["sources"].get(SOURCE, {})
    capture = json.loads((root / source["capture"]["path"]).read_text()) if source.get("capture") else None
    guarded_load.FakeGraphPort(graph).export(out / "post")
    overlay = [json.loads(x) for x in (graph / "overlay.jsonl").read_text().splitlines() if x]
    return {"status": loaded["status"], "error": loaded.get("error"), "source": source, "capture": capture,
            "overlay": overlay, "post": out / "post", "root": root, "agenda": loaded.get("agenda_items")}


def rehearse(plan: Path, responses: Path, frozen: datetime, ingest_runs: Path, control: str, out: Path,
             mode: str = "replay") -> dict:
    """`mode` "fill" fetches (through the robots gate) only what the recorded store lacks; "replay" sends nothing."""
    import yaml

    out = ba.staging_out(out, ba.STAGING_ROOT)
    plan = Path(plan)
    report = json.loads((plan / "plan-report.json").read_text())
    if ba.fingerprint(plan / "candidate") != report["candidate_sha256"]:
        raise ba.AttributionError("the candidate is not the plan's")
    guard = ba.load_guard()
    ops = json.loads((plan / "ops.json").read_text())
    if guard != {r["id"]: r["to"] for r in ops["repoint"]}:
        raise ba.AttributionError("registry/body-attribution-guard.yaml does not name exactly the plan's moves")
    candidate = ba.read_export(plan / "candidate")
    categories = {s["id"]: s.get("categories") or [] for s in
                  yaml.safe_load((REPO / "registry" / f"{REGISTRY}-sources.yaml").read_text())["sources"]}
    staged_cache = json.loads((Path(ingest_runs) / "meeting-identity.json").read_text())
    result = {"plan": str(plan.resolve()), "candidate_sha256": report["candidate_sha256"],
              "guard_sha256": ba._sha(ba.GUARD_PATH), "code_revision": _revision(),
              "inputs": {"responses": str(Path(responses).resolve()), "frozen": frozen.isoformat(),
                         "ingest_runs": {n: ba._sha(Path(ingest_runs) / n)
                                         for n in ("ledger.jsonl", "meeting-identity.json")}},
              "control": control, "mode": mode, "variants": {},
              "identity": {"staged_cache": ba.identity_problems(staged_cache, guard, categories)}}
    for name, agenda in (("agenda-as-on-main", False), ("agenda-on", True)):
        run = run_variant(name, out, candidate=plan / "candidate", responses=responses, frozen=frozen,
                          ingest_runs=ingest_runs, agenda=agenda, mode=mode)
        after = json.loads((run["root"] / "data" / "ingest-runs" / "meeting-identity.json").read_text())
        result["identity"][f"after-{name}"] = ba.identity_problems(after, guard, categories)
        result["variants"][name] = {
            "status": run["status"], "error": run["error"], "agenda_items": run["agenda"],
            "capture_meetings": len((run["capture"] or {}).get("meetings") or []),
            "source": {k: run["source"].get(k) for k in ("ok", "rows", "last_good_rows", "reasons")},
            "overlay_rows": dict(Counter(next(iter(r)) for r in run["overlay"])),
            "checks": checks(candidate=candidate, post=ba.read_export(run["post"]), capture=run["capture"],
                             overlay=run["overlay"], source_state=run["source"], run_status=run["status"],
                             guard=guard, control=control, agenda=run["agenda"], agenda_required=agenda)}
    result["all_pass"] = all(c["ok"] for v in result["variants"].values() for c in v["checks"]) and \
        not any(result["identity"].values())
    (out / "checks.json").write_text(json.dumps(result, indent=1, sort_keys=True, default=str) + "\n")
    return result


def _revision() -> str:
    return subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("rehearse")
    r.add_argument("--plan", type=Path, required=True)
    r.add_argument("--responses", type=Path, required=True)
    r.add_argument("--frozen", required=True, help="the recorded run's time, e.g. 2026-10-18T12:00:00+00:00")
    r.add_argument("--ingest-runs", type=Path, required=True)
    r.add_argument("--control", required=True)
    r.add_argument("--out", type=Path, required=True)
    r.add_argument("--mode", choices=("replay", "fill"), default="replay")
    args = parser.parse_args(argv)
    result = rehearse(args.plan, args.responses, datetime.fromisoformat(args.frozen), args.ingest_runs, args.control,
                      args.out, mode=args.mode)
    for name, v in result["variants"].items():
        for c in v["checks"]:
            print(f"{'PASS' if c['ok'] else 'FAIL'} {name}: {c['name']}" + ("" if c["ok"] else f" — {c['detail']}"))
    print(f"identity: {result['identity']}")
    print("ALL PASS" if result["all_pass"] else "FAILED")
    return 0 if result["all_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
