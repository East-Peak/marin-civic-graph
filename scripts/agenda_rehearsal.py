#!/usr/bin/env python3
"""Rehearse the weekly agenda-items stage on the real chain, on a fake graph; check a real run after.

    agenda_rehearsal.py prime    --work <dir>                                  # record the listings once
    agenda_rehearsal.py withhold --work <dir> --source <id> --agenda-ids 1690,1681  # week 1 without them
    agenda_rehearsal.py rehearse --work <dir> --export <fresh export> [--expected <json>] [--cap 4]
                                 [--weekly <ids>] [--acceptance --targets <ids>]
    agenda_rehearsal.py check-loaded <run-id> [--root <repo>]               # a real run's own stage delta

`rehearse` runs refresh_weekly.stage -> ingest.py -> the adapters -> the robots gate -> refresh_weekly.load
(every meeting loader on the fake graph) -> the agenda stage (agenda_items.py, bracketed by two exports and
agenda_delta.py) four times on ONE root and ONE graph seeded from the export: V1 week 1 (T), V2 the same frozen
run's agenda step again, V3 a fresh run (T + 1 h), V4 the next week (T + 7 d, the real listing). Responses come
from <work>/responses (filled once, then replayed) with <work>/week1 answering first for V1-V3; the seed drops the
withheld meetings so V4's real listing brings them in as new. Pass 1 may fetch what is missing (fill); pass 2
replays everything on a fresh graph and must write the same rows. With --expected (built from reviewer
annotations by a staging tool, never by this code), each variant's new AgendaItems must equal it. Staging only;
the real graph is never touched (every loader gets fakegraph:///, any other script is refused).
"""
from __future__ import annotations

import argparse
import base64
import difflib
import json
import re
import shutil
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
REPO = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))

import guarded_load  # noqa: E402
from crosswalk_rehearsal import RehearsalRunner, ResponseStore  # noqa: E402

AGENDA_STEP = "agenda_items.py"


class AgendaRunner(RehearsalRunner):
    """The weekly runner for an agenda rehearsal: shimmed ingest and agenda stage, real meeting loads and delta,
    fake-graph exports; every graph-touching step gets the fake URI; anything else is refused."""

    def __init__(self, *, store, mode, frozen, graph_uri, seed, override: Path | None, lock_dir: Path):
        super().__init__(store=store, mode=mode, frozen=frozen, graph_uri=graph_uri, seed=seed)
        self.override, self.lock_dir = override, lock_dir
        self.agenda_rows: list[tuple[int, int]] = []  # overlay lines before/after each agenda step

    def _shim(self, program, cmd):
        shim = [cmd[0], str(SCRIPTS / "crosswalk_rehearsal.py"), "ingest-shim", "--responses", str(self.store.path),
                "--mode", self.mode, "--frozen", self.frozen.isoformat(), "--program", program]
        return shim + (["--override", str(self.override)] if self.override else []) + ["--", *cmd[2:]]

    def __call__(self, cmd, cwd, env, timeout):
        import refresh_weekly as rw

        script = Path(cmd[1]).name if len(cmd) > 1 else cmd[0]
        fake = {**env, "NEO4J_URI": self.graph_uri, "OPEN_MARIN_LOCK_DIR": str(self.lock_dir)}
        if script == "ingest.py":
            self.calls.append(list(cmd))
            return rw.subprocess_runner(self._shim("ingest", cmd), cwd, env, timeout)
        if script == AGENDA_STEP:
            self.calls.append(list(cmd))
            before = _lines(self.graph_path)
            result = rw.subprocess_runner(self._shim("agenda", cmd), cwd, fake, timeout)
            self.agenda_rows.append((before, _lines(self.graph_path)))
            return result
        if script == "agenda_delta.py":
            self.calls.append(list(cmd))
            return rw.subprocess_runner(cmd, cwd, env, timeout)
        if script == "export_live_graph.py" and "--backup" in cmd and "agenda-items" in cmd[cmd.index("--out-dir") + 1]:
            self.calls.append(list(cmd))
            guarded_load.FakeGraphPort(self.graph_path).export(Path(cmd[cmd.index("--out-dir") + 1]))
            return rw.Result(0, "rehearsal: the fake graph exported\n")
        if script == "normalize_meetings.py":
            self.calls.append(list(cmd))
            return rw.subprocess_runner(cmd, cwd, fake, timeout)
        return super().__call__(cmd, cwd, env, timeout)

    @property
    def graph_path(self) -> Path:
        return Path(self.graph_uri.removeprefix("fakegraph://"))


def _lines(graph: Path) -> int:
    return len((graph / "overlay.jsonl").read_text().splitlines())


def _root(work: Path, cap: int, qualify: frozenset[str] = frozenset(), weekly: frozenset[str] = frozenset()) -> Path:
    """A weekly root: every meeting registry as in the repo, the configured sources capped for the rehearsal, the
    `qualify` ones qualified at their parser's current version and the `weekly` ones on the weekly schedule — in
    this staging copy only (the repo's registry qualifies a source only once its held-out evidence exists, and
    schedules it weekly only at its flip)."""
    import yaml

    from agenda_parsers import PARSERS

    root = work / "root"
    (root / "registry").mkdir(parents=True)
    for path in sorted((REPO / "registry").glob("*-sources.yaml")):
        doc = yaml.safe_load(path.read_text())
        for source in doc.get("sources") or []:
            if source["id"] in weekly:
                source["schedule"] = "weekly"
                source.pop("schedule_note", None)
            block = source.get("agenda_items")
            if isinstance(block, dict):
                block["cap"] = cap
                if source["id"] in qualify:
                    block["qualified"] = {"parser": block["parser"], "version": PARSERS[block["parser"]].version,
                                          "report": "rehearsal only"}
        (root / "registry" / path.name).write_text(yaml.safe_dump(doc, sort_keys=False))
    if (REPO / "registry" / "crosswalks").is_dir():
        shutil.copytree(REPO / "registry" / "crosswalks", root / "registry" / "crosswalks")
    (root / "scripts").symlink_to(SCRIPTS, target_is_directory=True)
    (root / "data" / "ingest-runs").mkdir(parents=True)
    return root


def _context(root: Path, runner, now: datetime, work: Path):
    import refresh_weekly as rw

    env = {"NEO4J_URI": "bolt://localhost:7688", "NEO4J_USER": "neo4j", "NEO4J_PASSWORD": "rehearsal-unused",
           "NEO4J_DATABASE": "neo4j", "PATH": "/usr/bin:/bin:/opt/homebrew/bin",
           rw.CF_STAGING_ENV: str(work / "cf-staging"), rw.VOTES_REFRESH_ENV: str(work / "votes-refresh")}

    def refuse(*_):
        raise RuntimeError("the rehearsal reaches for no network outside the robots-gated steps")

    return rw.Context(root=root, runner=runner, env=env, python=sys.executable, now=lambda: now,
                      staged_sources={}, ping=refuse, netfile_fetch=refuse, prepare_campaign_exports=False,
                      agenda_items=True)


def prune_seed(export: Path, out: Path, meeting_ids: set[str]) -> Path:
    """The export without these Meetings, the Records only they hold, and every edge touching either."""
    nodes = [json.loads(x) for x in (Path(export) / "nodes.jsonl").read_text().splitlines() if x.strip()]
    edges = [json.loads(x) for x in (Path(export) / "edges.jsonl").read_text().splitlines() if x.strip()]
    holders: dict[str, set[str]] = {}
    for e in edges:
        if e["type"] == "EVIDENCED_BY":
            holders.setdefault(e["end_id"], set()).add(e["start_id"])
    drop = set(meeting_ids) | {r for r, ms in holders.items() if ms and ms <= set(meeting_ids)}
    out.mkdir(parents=True)
    (out / "nodes.jsonl").write_text("".join(json.dumps(n) + "\n" for n in nodes if n["id"] not in drop))
    (out / "edges.jsonl").write_text("".join(json.dumps(e) + "\n" for e in edges
                                             if e["start_id"] not in drop and e["end_id"] not in drop))
    return out


def withhold(store: ResponseStore, week1: ResponseStore, agenda_ids: list[str]) -> list[str]:
    """Week 1's listing: every kept CivicPlus response with these agendas' rows taken out (nothing else changed)."""
    changed = []
    row = re.compile(r'<tr[^>]+class="catAgendaRow"[^>]*>.*?</tr>', re.S)
    withheld = lambda html: any(re.search(rf"_\d{{8}}-{a}\b", html) for a in agenda_ids)  # noqa: E731
    for path in sorted(store.path.glob("*.json")):
        reply = json.loads(path.read_text())
        body = base64.b64decode(reply["body"]).decode("utf-8", "replace")
        kept = row.sub(lambda m: "" if withheld(m.group(0)) else m.group(0), body)
        if kept != body:
            (week1.path / path.name).write_text(json.dumps({**reply, "body": base64.b64encode(kept.encode()).decode()}))
            changed.append(reply["url"])
    return changed


def _variant(name, root, work, store, mode, frozen, graph, seed, override):
    import refresh_weekly as rw

    runner = AgendaRunner(store=store, mode=mode, frozen=frozen, graph_uri=f"fakegraph://{graph}", seed=seed,
                          override=override, lock_dir=work / "locks")
    ctx = _context(root, runner, frozen, work)
    staged = rw.stage(ctx)
    loaded = rw.load(ctx, staged["run_id"]) if staged["status"] == "awaiting_load_approval" else staged
    return {"name": name, "run_id": staged["run_id"], "status": loaded["status"], "error": loaded.get("error"),
            "agenda": loaded.get("agenda_items"), "rows": runner.agenda_rows, "runner": runner, "ctx": ctx}


def _new_rows(graph: Path, span: tuple[int, int]) -> list[dict]:
    lines = (graph / "overlay.jsonl").read_text().splitlines()[span[0]:span[1]]
    return [json.loads(x) for x in lines]


def run_pass(work: Path, export: Path, *, label: str, mode: str, frozen: datetime, cap: int,
             qualify: frozenset[str] = frozenset(), weekly: frozenset[str] = frozenset()) -> dict:
    """One pass of the four variants on a new root and graph."""
    import refresh_weekly as rw

    out = work / label
    out.mkdir(parents=True, exist_ok=False)
    meta = json.loads((work / "withheld.json").read_text()) if (work / "withheld.json").is_file() else {"meetings": []}
    seed = prune_seed(export, out / "seed", set(meta["meetings"]))
    graph = guarded_load.FakeGraphPort.create(out / "graph", seed=seed)
    root = _root(out, cap, qualify, weekly)
    store = ResponseStore(work / "responses")
    week1 = work / "week1" if (work / "week1").is_dir() else None
    runs = {}
    for name, at, override in (("V1", frozen, week1), ("V3", frozen + timedelta(hours=1), week1),
                               ("V4", frozen + timedelta(days=7), None)):
        runs[name] = _variant(name, root, out, store, mode, at, graph, seed, override)
        if name == "V1":  # V2: the same frozen run's agenda step, again
            v1 = runs["V1"]
            report = (rw.run_dir(root, v1["run_id"]) / "agenda-items" / "report.json").read_bytes()
            log = rw.run_dir(root, v1["run_id"]) / "logs" / "requests-agenda-items.jsonl"
            requests_before = len(log.read_text().splitlines()) if log.is_file() else 0
            before = _lines(graph)
            result = v1["runner"]([sys.executable, str(SCRIPTS / AGENDA_STEP), "run", "--root", str(root),
                                   "--run-id", v1["run_id"]], root, v1["ctx"].env, 600)
            runs["V2"] = {"name": "V2", "run_id": v1["run_id"], "exit": result.returncode,
                          "rows_added": _lines(graph) - before,
                          "report_same": (rw.run_dir(root, v1["run_id"]) / "agenda-items" / "report.json").read_bytes()
                          == report,
                          "requests_added": (len(log.read_text().splitlines()) if log.is_file() else 0) - requests_before}
    return {"root": root, "graph": graph, "seed": seed, "runs": runs, "withheld": meta}


def _report(root: Path, run_id: str) -> dict:
    import refresh_weekly as rw

    return json.loads((rw.run_dir(root, run_id) / "agenda-items" / "report.json").read_text())


def _items_of(rows: list[dict]) -> dict[str, dict]:
    return {r["node"]["id"]: r["node"] for r in rows if "node" in r}


def _title_ok(a: str, b: str) -> bool:
    norm = lambda t: " ".join(re.sub(r"[^\w\s]", " ", (t or "").lower()).split())  # noqa: E731
    return norm(a) == norm(b) or difflib.SequenceMatcher(None, norm(a), norm(b)).ratio() >= 0.90


def target_checks(created_by: dict[str, dict], expected: dict, targets) -> list[dict]:
    """Per named target: it loaded items in some variant, exactly the expected ones (both nonempty), and its own
    titles/headings agree with the annotations on >= 95% of them (a target's few items are not lost in the pool)."""
    out = []
    for target in targets:
        have = {i: n["properties"] for items in created_by.values() for i, n in items.items()
                if n["properties"]["source_id"] == target}
        want = {i: p for v in expected.values() for i, p in v["items"].items() if p["source_id"] == target}
        out.append({"check": f"acceptance: {target} loaded a nonempty, independently expected set",
                    "ok": bool(have) and have.keys() == want.keys(),
                    "detail": {"created": len(have), "expected": len(want), "missing": sorted(want.keys() - have)[:5],
                               "extra": sorted(have.keys() - want)[:5]}})
        both = sorted(have.keys() & want.keys())
        titles = [i for i in both if not _title_ok(have[i]["title"], want[i]["title"])
                  or not _title_ok(have[i].get("heading", ""), want[i].get("heading", ""))]
        out.append({"check": f"acceptance: {target}: its titles/headings agree with the annotations on >= 95%",
                    "ok": bool(both) and 1 - len(titles) / len(both) >= 0.95,
                    "detail": {"disagree": titles[:10], "of": len(both)}})
    return out


def checks(p1: dict, p2: dict | None, expected: dict | None, acceptance: bool = False, targets=()) -> list[dict]:
    out = []

    def check(name, ok, detail=None):
        out.append({"check": name, "ok": bool(ok), "detail": detail})

    graph = p1["graph"]
    created_by = {}
    for name in ("V1", "V3", "V4"):
        run = p1["runs"][name]
        check(f"{name}: the run reaches publish approval", run["status"] == "awaiting_publish_approval",
              run.get("error"))
        check(f"{name}: agenda stage ok, its delta exact (full exports before/after)",
              (run["agenda"] or {}).get("ok") is True, (run["agenda"] or {}).get("error"))
        rows = [r for span in run["rows"] for r in _new_rows(graph, span)]
        bad = [r for r in rows if not ("node" in r and r["node"]["labels"] == ["AgendaItem"])
               and not ("edge" in r and r["edge"]["type"] in guarded_load.AGENDA_EDGES)]
        check(f"{name}: the agenda step wrote only AgendaItem creates and their two edges", not bad, bad[:3])
        created_by[name] = _items_of(rows)
    v2 = p1["runs"]["V2"]
    check("V2: the same frozen run again is a no-op (0 rows, 0 requests, same report)",
          v2["exit"] == 0 and v2["rows_added"] == 0 and v2["requests_added"] == 0 and v2["report_same"], v2)
    r1, r3, r4 = (_report(p1["root"], p1["runs"][n]["run_id"]) for n in ("V1", "V3", "V4"))
    for sid, s3 in r3["sources"].items():
        if not s3.get("eligible"):
            continue
        check(f"V3 {sid}: a fresh run advances the backlog by <= cap",
              s3["selected"] <= s3["cap"] and s3["backlog_after"] == max(0, r1["sources"][sid]["backlog_after"]
                                                                         - s3["selected"]),
              {"selected": s3["selected"], "cap": s3["cap"], "before": r1["sources"][sid]["backlog_after"],
               "after": s3["backlog_after"]})
    withheld = set(p1["withheld"]["meetings"])
    if withheld:
        v4_meetings = {n["properties"]["meeting_id"] for n in created_by["V4"].values()}
        v4_held = {m for s in r4["sources"].values() for m in (s.get("held") or {})}
        check("V4: the withheld meetings arrive through the real listing and are taken that week",
              withheld <= (v4_meetings | v4_held), sorted(withheld - v4_meetings - v4_held))
    if expected is not None:
        for name in ("V1", "V3", "V4"):
            run = p1["runs"][name]
            rows = [r for span in run["rows"] for r in _new_rows(graph, span)]
            have_edges = Counter((r["edge"]["start_id"], r["edge"]["type"], r["edge"]["end_id"]) for r in rows if "edge" in r)
            want_edges = Counter(tuple(e) for e in expected[name]["edges"])
            check(f"{name}: new relationships == the expected set (endpoints and multiplicity)", have_edges == want_edges,
                  {"missing": [list(e) for e in (want_edges - have_edges)][:5],
                   "extra": [list(e) for e in (have_edges - want_edges)][:5]})
            want = expected[name]["items"]
            have = created_by[name]
            missing, extra = sorted(set(want) - set(have)), sorted(set(have) - set(want))
            structural = sorted(i for i in set(want) & set(have) if
                                {k: v for k, v in have[i]["properties"].items() if k not in ("title", "display_label", "heading")}
                                != {k: v for k, v in want[i].items() if k not in ("title", "display_label", "heading")})
            titles = sorted(i for i in set(want) & set(have) if not _title_ok(have[i]["properties"]["title"], want[i]["title"])
                            or not _title_ok(have[i]["properties"].get("heading", ""), want[i].get("heading", "")))
            total = len(set(want) & set(have)) or 1
            check(f"{name}: new AgendaItems == the expected set (ids and properties)", not missing and not extra
                  and not structural, {"missing": missing[:10], "extra": extra[:10], "structural": structural[:10]})
            check(f"{name}: titles/headings agree with the annotations on >= 95% of items",
                  1 - len(titles) / total >= 0.95, {"disagree": titles[:10], "of": total})
    if p2 is not None:
        same = (p1["graph"] / "overlay.jsonl").read_text() == (p2["graph"] / "overlay.jsonl").read_text()
        check("pass 2 (pure replay, fresh graph) writes exactly pass 1's rows", same)
    if acceptance:
        check("acceptance: independent expectations and a pure replay were both run", expected is not None and p2 is not None)
        sources = {n["properties"]["source_id"] for items in created_by.values() for n in items.values()}
        check("acceptance: at least three sources loaded items", len(sources) >= 3, sorted(sources))
        v4 = {n["properties"]["meeting_id"] for n in created_by["V4"].values()}
        check("acceptance: the later week loaded a newly arrived meeting's items and the next backlog batch",
              bool(v4 & withheld) and bool(v4 - withheld), {"new": sorted(v4 & withheld), "backlog": len(v4 - withheld)})
        if targets:
            out += target_checks(created_by, expected or {}, targets)
    return out


# --- check-loaded: a real run's agenda stage, from its own pinned inputs (read only) ------------------------


def check_loaded(root: Path, run_id: str) -> dict:
    """After a real weekly run: bind to the run's pinned pre/post exports, bundle and report, and judge.

    The stage's delta is recomputed (exactly the committed meetings' bundle items and edges; nothing else
    changed, removed or added); every committed meeting's ledger entry is `loaded` with the bundle's url and
    sha256; every held meeting gained nothing; and, across the whole run (its pre-load backup vs the post
    export), no AgendaItem or Decision that existed before changed or vanished."""
    import agenda_delta
    import refresh_weekly as rw

    root = Path(root).resolve()
    state = rw.read_state(root, run_id)
    agenda = state.get("agenda_items")
    if not agenda or "exports_sha256" not in agenda:
        raise RuntimeError(f"run {run_id} has no completed agenda stage to check")
    work = rw.run_dir(root, run_id) / rw.AGENDA_DIR
    results = []

    def check(name, ok, detail=None):
        results.append({"check": name, "ok": bool(ok), "detail": detail})

    moved = {k: v for k, v in agenda["exports_sha256"].items() if rw._sha256(work / k) != v}
    check("the pre/post exports are the ones the run pinned", not moved, sorted(moved))
    manifest = json.loads((work / "bundle" / "manifest.json").read_text())
    stale = {f for f, sha in manifest["files"].items() if rw._sha256(work / "bundle" / f) != sha}
    check("the bundle is the one its manifest hashed", not stale, sorted(stale))
    report = json.loads((work / "report.json").read_text())
    committed = sorted(set(report["load"]["created"]["meetings"]) | set(report["load"].get("already_loaded") or []))
    delta = agenda_delta.compare(work / "pre", work / "post", work / "bundle", committed=committed)
    check("stage delta: exactly the committed items and their edges", delta["ok"], delta["problems"][:10])
    ledger = json.loads((root / "data/ingest-runs/agenda-items-ledger.json").read_text())["meetings"]
    by_mid = {m["meeting_id"]: m for m in manifest["meetings"]}
    wrong = [mid for mid in committed if (ledger.get(mid) or {}).get("state") not in ("loaded", "revised")
             or ledger[mid].get("sha256") != by_mid[mid]["sha256"] or ledger[mid].get("url") != by_mid[mid]["url"]]
    check("every committed meeting is in the ledger with the bundle's url and sha256", not wrong, wrong[:10])
    backup = root / state["backup"]
    moved = {f: sha for f, sha in (state.get("backup_sha256") or {}).items() if rw._sha256(backup / f) != sha}
    check("the pre-load backup is the one the run pinned", state.get("backup_sha256") and not moved, sorted(moved))
    protected = lambda n: {"AgendaItem", "Decision"} & set(n["labels"])  # noqa: E731
    before = {n["id"]: n for n in map(json.loads, (backup / "nodes.jsonl").read_text().splitlines()) if protected(n)}
    after = {n["id"]: n for n in map(json.loads, (work / "post" / "nodes.jsonl").read_text().splitlines())
             if n["id"] in before}
    changed = [i for i, n in before.items() if after.get(i) != n]

    def incident(path: Path) -> Counter:
        return Counter((e["start_id"], e["type"], e["end_id"], json.dumps(e.get("properties") or {}, sort_keys=True))
                       for e in map(json.loads, (path / "edges.jsonl").read_text().splitlines())
                       if e["start_id"] in before or e["end_id"] in before)

    lost = sorted((incident(backup) - incident(work / "post")).elements())
    check("no AgendaItem or Decision that existed before the run changed or vanished", not changed, changed[:10])
    check("none of their relationships changed or vanished", not lost, [list(x[:3]) for x in lost[:10]])
    return {"run_id": run_id, "checks": results, "verdict": "PASS" if all(c["ok"] for c in results) else "FAIL",
            "committed": committed, "added": {"nodes": delta["added_nodes"], "edges": delta["added_edges"]}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    pr = sub.add_parser("prime")
    pr.add_argument("--work", type=Path, required=True)
    pr.add_argument("--export", type=Path, required=True)
    wh = sub.add_parser("withhold")
    wh.add_argument("--work", type=Path, required=True)
    wh.add_argument("--agenda-ids", required=True)
    wh.add_argument("--meetings", required=True, help="the graph meeting ids of those agendas, comma separated")
    rh = sub.add_parser("rehearse")
    rh.add_argument("--work", type=Path, required=True)
    rh.add_argument("--export", type=Path, required=True)
    rh.add_argument("--expected", type=Path)
    rh.add_argument("--cap", type=int, default=4)
    rh.add_argument("--frozen", required=True, help="ISO time of week 1 (kept for every pass)")
    rh.add_argument("--replay", action="store_true", help="also run pass 2: pure replay on a fresh graph")
    rh.add_argument("--qualify", default="", help="sources qualified in the rehearsal's staging registry only")
    rh.add_argument("--weekly", default="", help="sources put on the weekly schedule in that staging registry only")
    rh.add_argument("--targets", default="", help="with --acceptance: sources that must each load their expected items")
    rh.add_argument("--acceptance", action="store_true",
                    help="the run that counts: requires --expected and --replay, three sources, a later-week arrival")
    ck = sub.add_parser("check-loaded", help="after a real run: its agenda stage, from its own pinned inputs")
    ck.add_argument("run_id")
    ck.add_argument("--root", type=Path, default=REPO)
    args = parser.parse_args(argv)
    if args.cmd == "check-loaded":
        result = check_loaded(args.root, args.run_id)
        for c in result["checks"]:
            print(("PASS " if c["ok"] else "FAIL ") + c["check"] + ("" if c["ok"] else f"  {c['detail']}"))
        print(f"check-loaded {args.run_id} (agenda items): {result['verdict']}")
        return 0 if result["verdict"] == "PASS" else 1
    work = args.work.resolve()
    if args.cmd == "prime":  # record the listings (and robots) once: a stage alone, nothing loaded
        import refresh_weekly as rw

        work.mkdir(parents=True, exist_ok=True)
        root = _root(work / "prime", 4)
        runner = AgendaRunner(store=ResponseStore(work / "responses"), mode="fill",
                              frozen=datetime.now(timezone.utc).replace(microsecond=0),
                              graph_uri=f"fakegraph://{work / 'prime-graph'}", seed=args.export, override=None,
                              lock_dir=work / "locks")
        state = rw.stage(_context(root, runner, runner.frozen, work / "prime"))
        print(json.dumps({sid: s["ok"] for sid, s in state["sources"].items()}, indent=1))
        return 0
    if args.cmd == "withhold":
        week1 = ResponseStore(work / "week1")
        changed = withhold(ResponseStore(work / "responses"), week1, args.agenda_ids.split(","))
        (work / "withheld.json").write_text(json.dumps({"agenda_ids": args.agenda_ids.split(","),
                                                        "meetings": args.meetings.split(","), "responses": changed},
                                                       indent=1))
        print(f"week 1: {len(changed)} responses with rows withheld")
        return 0
    frozen = datetime.fromisoformat(args.frozen)
    n = len(list(work.glob("pass-*")))
    qualify = frozenset(filter(None, args.qualify.split(",")))
    weekly = frozenset(filter(None, args.weekly.split(",")))
    p1 = run_pass(work, args.export, label=f"pass-{n + 1}", mode="fill", frozen=frozen, cap=args.cap, qualify=qualify,
                  weekly=weekly)
    p2 = run_pass(work, args.export, label=f"pass-{n + 2}", mode="replay", frozen=frozen, cap=args.cap,
                  qualify=qualify, weekly=weekly) if args.replay else None
    expected = json.loads(args.expected.read_text()) if args.expected else None
    results = checks(p1, p2, expected, acceptance=args.acceptance,
                     targets=[t for t in args.targets.split(",") if t])
    admitted = admitted_agendas(p1)
    (work / f"pass-{n + 1}" / "admitted.json").write_text(json.dumps(admitted, indent=1))
    (work / f"pass-{n + 1}" / "checks.json").write_text(json.dumps(results, indent=1, default=str))
    for c in results:
        print(("PASS " if c["ok"] else "FAIL ") + c["check"] + ("" if c["ok"] else f"  {json.dumps(c['detail'], default=str)[:400]}"))
    return 0 if all(c["ok"] for c in results) else 1


def admitted_agendas(p: dict) -> list[dict]:
    """Every agenda any variant fetched (for the reviewers): meeting, url, file, sha256, result."""
    import refresh_weekly as rw

    out = []
    for name in ("V1", "V3", "V4"):
        run_id = p["runs"][name]["run_id"]
        fetched = rw.run_dir(p["root"], run_id) / "agenda-items" / "fetched"
        for path in sorted(fetched.glob("*.json")) if fetched.is_dir() else []:
            r = json.loads(path.read_text())
            out.append({"variant": name, "run_id": run_id, "meeting_id": r["meeting_id"], "source_id": r["source_id"],
                        "meeting_date": r["meeting_date"], "title": r.get("title"), "url": r["url"],
                        "file": str(fetched.parent / "files" / r["file"]) if r.get("file") else None,
                        "sha256": r.get("sha256"), "hold": r.get("hold"),
                        "items": len((r.get("parsed") or {}).get("items") or [])})
    return out


if __name__ == "__main__":
    sys.exit(main())
