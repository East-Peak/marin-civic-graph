#!/usr/bin/env python3
"""Rehearse a guarded (crosswalk-required or native-only) source's weekly path end to end; check a real run after.

    crosswalk_rehearsal.py rehearse --source <id> --export <dir> --work <staging dir> [--identity-cache <json>]
                                    [--responses <dir>] [--expected <json>]
    crosswalk_rehearsal.py check-loaded <run-id> --source <id> --post-export <dir> [--root <repo>] [--out <dir>]

`rehearse` (staging only; no graph writes) runs the real weekly chain: refresh_weekly.stage ->
ingest.py -> the adapter -> the robots gate, then refresh_weekly.load, whose meeting step is the real
`normalize_meetings.py --load` subprocess against a fake graph seeded from `--export`. Only backup,
reconciliation, export and bake are stand-ins. The first run fetches live (politely, through the
robots gate) and records every response; the others replay them with the clock frozen, so a populated
identity cache, a second identical run and a later week (+7 days) see byte-identical inputs. It then
checks what the goal requires: new Meetings == the listing-only set, new Records == an independent
classification, nothing existing touched, no duplicate Meeting, cache-independence, replay no-op, a
later week adds exactly its listing snapshot. A native-only source has no crosswalk to derive its
expectations from: `--expected` names its Meetings, artifact Records and stubs to create (from the
reviewed listing inventory), and the source's own registry file is the one staged.

`check-loaded` (read only) repeats the checks after a real Monday run: from that run's pinned backup,
capture, crosswalk and load report, plus a full-property export taken after it
(`export_live_graph.py --backup --out-dir <dir>`).

`ingest-shim` is the rehearsal's own: the runner wraps ingest.py in it to record or replay responses
and freeze the clock. Nothing in the production path knows it exists. A replay serves each URL's final
body after the gate admits that URL; redirect hops and failed fetches are not re-enacted (the live run's
request log is the robots evidence, and the rehearsal requires its capture to have no fetch errors).
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import shutil
import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

SCRIPTS = Path(__file__).resolve().parent
REPO = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))

import crosswalk  # noqa: E402
import guarded_load  # noqa: E402

LINK_TYPES = ("EVIDENCED_BY", "RELATES_TO_MEETING")
LISTING_RECORD = {"proudcity": "meetings-page", "civicplus_archive": "archive-page"}  # record-<sid>-<this>-<day>
STUB_PROPERTIES = ("name", "subtype", "jurisdiction_id", "place_type", "display_label", "promotion_state")
VARIANTS = ("empty-cache", "populated-cache", "replay", "later-week")


# --- the ingest shim: record / replay responses, freeze the clock ------------------------------------------


class ResponseStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)

    def _file(self, url: str, data: bytes | None = None) -> Path:
        key = url.encode() if data is None else url.encode() + b"\n" + data  # a POST is its url and its body
        return self.path / f"{hashlib.sha256(key).hexdigest()}.json"

    def has(self, url: str, data: bytes | None = None) -> bool:
        return self._file(url, data).is_file()

    def put(self, url: str, data: bytes | None = None, **reply) -> None:
        body = reply.pop("body")
        self._file(url, data).write_text(json.dumps({"url": url, **reply, "body": base64.b64encode(body).decode()}))

    def get(self, url: str, data: bytes | None = None) -> dict:
        path = self._file(url, data)
        if not path.is_file():
            raise RuntimeError(f"replay has no recorded response for {url}")
        reply = json.loads(path.read_text())
        return {**reply, "body": base64.b64decode(reply["body"])}

    def __len__(self) -> int:
        return len(list(self.path.glob("*.json")))


class _Body(io.BytesIO):
    """A recorded response body, readable as the adapters read a reply (headers give its charset)."""

    headers = SimpleNamespace(get_content_charset=lambda default=None: default)


def install_shim(store: ResponseStore, mode: str, frozen: datetime, override: ResponseStore | None = None) -> None:
    """record: fetch live (through the gate) and keep every response; replay: serve only kept responses, send
    nothing; fill: serve what is kept, fetch-and-keep what is not. `override` answers first (a week's listing)."""
    import adapters.base as base
    import adapters.proudcity as proudcity
    import ingest
    import robots_gate

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return frozen if tz else frozen.replace(tzinfo=None)

    class FrozenDate(date):
        @classmethod
        def today(cls):
            return frozen.date()

    base.datetime = FrozenDatetime  # raw_dir, extracted_path, capture_id, utc_now_iso
    ingest.date = FrozenDate
    ingest._now = lambda: frozen.isoformat(timespec="seconds")
    gate_open = robots_gate.RobotsGate.open
    real_get = robots_gate.http_get

    def kept(url, data=None):
        for s in (override, store):
            if s is not None and s.has(url, data):
                return s.get(url, data)
        return None

    def robots_transport(url, timeout):
        r = kept(url) if mode != "record" else None
        if r is not None or mode == "replay":
            r = r or store.get(url)
            return robots_gate.Reply(r["status"], r["headers"], r["body"], r["error"])
        reply = real_get(url, timeout)
        store.put(url, status=reply.status, headers=reply.headers, body=reply.body, error=reply.error)
        return reply

    def open_(self, request, *, timeout, handlers=(), hosts=None):
        data = request.data
        r = kept(request.full_url, data) if mode != "record" else None
        if r is not None or mode == "replay":
            r = r or store.get(request.full_url, data)
            pace = self._pace
            self._pace = lambda url: 0.0  # a kept response is not sent: nothing to pace
            try:
                self.admit(request.full_url, method=request.get_method(), hosts=hosts)  # robots.txt still decides
            finally:
                self._pace = pace
            return _Body(r["body"])
        with gate_open(self, request, timeout=timeout, handlers=handlers, hosts=hosts) as resp:
            body = resp.read()
        store.put(request.full_url, data, status=200, headers={}, body=body, error=None)
        return _Body(body)

    robots_gate.RobotsGate.__init__.__kwdefaults__["robots_transport"] = robots_transport
    robots_gate.RobotsGate.open = open_
    if mode == "replay":  # nothing is sent, so nothing is paced, and nothing may be
        import time
        import urllib.request

        def no_network(*_, **__):
            raise RuntimeError("a replay sent a request")

        urllib.request.OpenerDirector.open = no_network
        robots_gate.RobotsGate._pace = lambda self, url: 0.0
        proudcity.time = ingest.time = SimpleNamespace(sleep=lambda seconds: None)
        time.sleep = lambda seconds: None  # the agenda stage's own spacing (agenda_items resolves it at call time)


def _shim_main(args) -> int:
    override = ResponseStore(args.override) if getattr(args, "override", None) else None
    install_shim(ResponseStore(args.responses), args.mode, datetime.fromisoformat(args.frozen), override)
    if getattr(args, "program", "ingest") == "agenda":
        import agenda_items

        return agenda_items.main(args.ingest_args)
    import ingest

    return ingest.main(args.ingest_args)


# --- the rehearsal --------------------------------------------------------------------------------------


def _read_export(path: Path) -> tuple[dict[str, dict], list[dict]]:
    with open(Path(path) / "nodes.jsonl", encoding="utf-8") as fh:
        nodes = {n["id"]: n for n in map(json.loads, filter(str.strip, fh))}
    with open(Path(path) / "edges.jsonl", encoding="utf-8") as fh:
        edges = [json.loads(line) for line in fh if line.strip()]
    return nodes, edges


class RehearsalRunner:
    """refresh_weekly's runner for a rehearsal: real ingest (shimmed) and real meeting loads; stand-ins for the rest."""

    def __init__(self, *, store: ResponseStore, mode: str, frozen: datetime, graph_uri: str, seed: Path):
        self.store, self.mode, self.frozen, self.graph_uri, self.seed = store, mode, frozen, graph_uri, seed
        self.calls: list[list[str]] = []

    def __call__(self, cmd, cwd, env, timeout):
        import refresh_weekly as rw

        self.calls.append(list(cmd))
        script = Path(cmd[1]).name if len(cmd) > 1 else cmd[0]
        if script == "ingest.py":
            shim = [cmd[0], str(Path(__file__).resolve()), "ingest-shim", "--responses", str(self.store.path),
                    "--mode", self.mode, "--frozen", self.frozen.isoformat(), "--", *cmd[2:]]
            return rw.subprocess_runner(shim, cwd, env, timeout)
        if script == "normalize_meetings.py":
            return rw.subprocess_runner(cmd, cwd, {**env, "NEO4J_URI": self.graph_uri}, timeout)
        if script == "export_live_graph.py" and "--backup" in cmd:
            out = Path(cmd[cmd.index("--out-dir") + 1])
            out.mkdir(parents=True)
            for name in ("nodes.jsonl", "edges.jsonl"):
                (out / name).symlink_to(self.seed / name)
            return rw.Result(0, "rehearsal: the backup is the seed export\n")
        if script in ("export_live_graph.py", "refresh_reconciliation.sh"):
            return rw.Result(0, f"rehearsal: {script} not run\n")
        if script == "bake_public_substrate.py":
            sqlite = Path(cmd[cmd.index("--sqlite") + 1])
            sqlite.parent.mkdir(parents=True, exist_ok=True)
            sqlite.write_bytes(b"rehearsal: no bake")
            for name in ("status_manifest.json", "catalog.json"):
                (sqlite.parent / name).write_text("{}")
            Path(cmd[cmd.index("--report") + 1]).write_text(json.dumps(
                {"totals": {}, "sqlite": {"size_bytes": 0, "budget_bytes": 1, "within_budget": True}}))
            return rw.Result(0, "rehearsal: bake not run\n")
        raise RuntimeError(f"the rehearsal does not run {cmd}")


def source_registry(repo: Path, source_id: str) -> tuple[str, dict]:
    """(registry name, config) of the meeting registry (registry/<name>-sources.yaml) that holds `source_id`."""
    import yaml

    for path in sorted((Path(repo) / "registry").glob("*-sources.yaml")):
        for config in yaml.safe_load(path.read_text()).get("sources") or []:
            if config.get("id") == source_id:
                return path.name.removesuffix("-sources.yaml"), config
    raise ValueError(f"no registry holds {source_id}")


def _make_root(root: Path, repo: Path, source_id: str, registry_name: str, identity_cache: dict | None) -> None:
    """A weekly root: the source's registry with only `source_id` weekly, crosswalks, the scripts, an empty data/."""
    import yaml

    (root / "registry").mkdir(parents=True)
    name = f"{registry_name}-sources.yaml"
    registry = yaml.safe_load((repo / "registry" / name).read_text())
    for source in registry["sources"]:
        source["schedule"] = "weekly" if source["id"] == source_id else "manual"
    (root / "registry" / name).write_text(yaml.safe_dump(registry, sort_keys=False))
    if (repo / "registry" / "crosswalks").is_dir():
        shutil.copytree(repo / "registry" / "crosswalks", root / "registry" / "crosswalks")
    (root / "scripts").symlink_to(repo / "scripts", target_is_directory=True)
    (root / "data" / "ingest-runs").mkdir(parents=True)
    if identity_cache is not None:
        (root / "data" / "ingest-runs" / "meeting-identity.json").write_text(json.dumps(identity_cache))


def _context(root: Path, runner, now: datetime, work: Path, registry_name: str):
    import refresh_weekly as rw

    env = {"NEO4J_URI": "bolt://localhost:7688", "NEO4J_USER": "neo4j", "NEO4J_PASSWORD": "rehearsal-unused",
           "NEO4J_DATABASE": "neo4j", "PATH": "/usr/bin:/bin",
           rw.CF_STAGING_ENV: str(work / "cf-staging"), rw.VOTES_REFRESH_ENV: str(work / "votes-refresh")}

    def refuse(*_):
        raise RuntimeError("the rehearsal reaches for no network outside the robots-gated adapter")

    return rw.Context(root=root, runner=runner, env=env, python=sys.executable, now=lambda: now,
                      meeting_registries=(registry_name,), staged_sources={}, ping=refuse, netfile_fetch=refuse,
                      prepare_campaign_exports=False)


def run_variant(name: str, work: Path, repo: Path, source_id: str, *, store: ResponseStore, mode: str,
                frozen: datetime, graph: Path, seed: Path, identity_cache: dict | None,
                registry_name: str = "proudcity") -> dict:
    import refresh_weekly as rw

    root = work / name
    _make_root(root, repo, source_id, registry_name, identity_cache)
    runner = RehearsalRunner(store=store, mode=mode, frozen=frozen, graph_uri=f"fakegraph://{graph}", seed=seed)
    ctx = _context(root, runner, frozen, work, registry_name)
    staged = rw.stage(ctx)
    loaded = rw.load(ctx, staged["run_id"]) if staged["status"] == "awaiting_load_approval" else staged
    source = loaded["sources"].get(source_id, {})
    capture = root / source["capture"]["path"] if source.get("capture") else None
    report_name = (source.get("load_report") or {}).get("path")
    report = json.loads((rw.run_dir(root, staged["run_id"]) / "load-reports" / report_name).read_text()) \
        if report_name else None
    return {"name": name, "root": root, "status": loaded["status"], "error": loaded.get("error"),
            "state": loaded, "source": source, "capture": capture, "report": report, "mode": mode,
            "frozen": frozen.isoformat()}


def expected_records(capture: dict, nodes: dict[str, dict], edges: list[dict], source_id: str,
                     institution_id: str) -> dict:
    """An independent classification of every artifact Record a first load makes (not guarded_load's code)."""
    meetings = {i for i, n in nodes.items() if "Meeting" in n["labels"]
                and n["properties"].get("institution_id") == institution_id}
    linked: dict[str, set[str]] = {}
    for e in edges:
        if e["type"] == "EVIDENCED_BY" and e["start_id"] in meetings:
            linked.setdefault(e["start_id"], set()).add(e["end_id"])
        elif e["type"] == "RELATES_TO_MEETING" and e["end_id"] in meetings:
            linked.setdefault(e["end_id"], set()).add(e["start_id"])
    is_record = lambda r: "Record" in nodes.get(r, {}).get("labels", [])  # noqa: E731
    by_url: dict[str, set[str]] = {}
    for rs in linked.values():
        for r in filter(is_record, rs):
            if nodes[r]["properties"].get("source_url"):
                by_url.setdefault(nodes[r]["properties"]["source_url"], set()).add(r)
    kinds = guarded_load.ARTIFACT_KINDS
    classes: Counter = Counter()
    created: set[str] = {ref["id"] for ref in capture.get("record_refs", [])}
    classes["listing_snapshot"] = len(created)
    fresh: dict[str, list[tuple[str, str]]] = {}
    problems = []
    for m in capture["meetings"]:
        mid, new = m["meeting_id"], m["meeting_id"] not in meetings
        urls = [a["url"] for a in (m.get("artifacts") or {}).values() if a.get("available") and a.get("url")]
        if len(set(urls)) != len(urls):
            classes["HOLD"] += 1
            problems.append((mid, "*", "one url on two artifacts"))
            continue
        for art, a in sorted((m.get("artifacts") or {}).items()):
            if not (a.get("available") and a.get("url")):
                continue
            url = a["url"]
            template = f"record-{source_id}-{mid.split('meeting-', 1)[-1]}-{art}"
            established = {r for r in linked.get(mid, ()) if is_record(r)
                           and nodes[r]["properties"].get("record_type") in kinds.get(art, ())}
            established |= {template} if template in nodes else set()
            if established:
                one = next(iter(established))
                ok = len(established) == 1 and nodes[one]["properties"].get("source_url") == url
                classes["existing_exact_match" if ok else "HOLD"] += 1
                problems += [] if ok else [(mid, art, url)]
            elif by_url.get(url):
                ok = new and len(by_url[url]) == 1 and \
                    nodes[next(iter(by_url[url]))]["properties"].get("record_type") in kinds.get(art, ())
                classes["existing_reused_by_new_meeting" if ok else "HOLD"] += 1
                problems += [] if ok else [(mid, art, url)]
            else:
                fresh.setdefault(url, []).append((mid, art, new))
    for url, users in fresh.items():
        if len({art for _, art, _ in users}) > 1:
            classes["HOLD"] += len(users)
            problems.append((url, "*", "one new url across kinds"))
            continue
        owner = min(users)
        created.add(f"record-{source_id}-{owner[0].split('meeting-', 1)[-1]}-{owner[1]}")
        for user in users:
            classes[("artifact_on_new_meeting" if user[2] else "new_artifact_on_existing_meeting")
                    if user == owner else "shares_a_new_record"] += 1
    return {"created": sorted(created), "classes": dict(classes), "holds": problems}


def _check(results: dict, name: str, ok: bool, detail) -> None:
    results["checks"].append({"check": name, "ok": bool(ok), "detail": detail})


def rehearse(source_id: str, export: Path, work: Path, *, repo: Path = REPO, identity_cache: Path | None = None,
             responses: Path | None = None, now: datetime | None = None, expected: Path | None = None) -> dict:
    work, export = Path(work).resolve(), Path(export).resolve()
    if work.is_relative_to(REPO) or work.is_relative_to(Path(repo).resolve()):
        raise ValueError(f"the rehearsal works in staging, never inside the repo ({work})")
    registry_name, config = source_registry(repo, source_id)
    if crosswalk.required(config):
        xw, expect = crosswalk.load(repo / config["crosswalk"], source_id), None
    elif config.get("identity") == crosswalk.NATIVE:
        if expected is None:
            raise ValueError(f"{source_id} is native-only: its rehearsal needs --expected (the reviewed inventory)")
        xw, expect = None, json.loads(Path(expected).read_text())
    else:
        raise ValueError(f"{source_id} is not a guarded source (identity crosswalk-required or native-only)")
    work.mkdir(parents=True, exist_ok=False)
    frozen = (now or datetime.now(timezone.utc)).replace(microsecond=0)
    store = ResponseStore(responses or work / "responses")
    first_mode = "replay" if len(store) else "record"
    graphs = {v: guarded_load.FakeGraphPort.create(work / f"graph-{v}", seed=export)
              for v in ("empty-cache", "populated-cache")}
    real_cache = json.loads(Path(identity_cache).read_text()) if identity_cache else {"by_id": {}, "by_key": {}}
    ids = [crosswalk.adapter_id(source_id, slug) for slug in list(xw.entries)[:5]] if xw else expect["meetings"][:5]
    wrong = {f"{source_id}|{mid}": "meeting-wrong-from-cache" for mid in ids}
    populated = {**real_cache, "by_id": {**real_cache.get("by_id", {}), **wrong}}
    plan = [("empty-cache", first_mode, frozen, graphs["empty-cache"], None),
            ("populated-cache", "replay", frozen, graphs["populated-cache"], populated),
            ("replay", "replay", frozen, graphs["empty-cache"], None),
            ("later-week", "replay", frozen + timedelta(days=7), graphs["empty-cache"], None)]
    runs, overlays = {}, {}
    for name, mode, at, graph, cache in plan:
        runs[name] = run_variant(name, work, repo, source_id, store=store, mode=mode, frozen=at, graph=graph,
                                 seed=export, identity_cache=cache, registry_name=registry_name)
        overlays[name] = guarded_load.FakeGraphPort(graph).overlay()
    return _rehearsal_checks(source_id, config, xw, export, work, runs, overlays, store, expect)


def _rehearsal_checks(source_id, config, xw, export, work, runs, overlays, store, expect=None) -> dict:
    results = {"source_id": source_id, "export": str(export), "crosswalk_sha256": xw.sha256 if xw else None,
               "identity": config.get("identity"), "work": str(work), "responses": len(store), "runs": {},
               "checks": []}
    for name, run in runs.items():
        results["runs"][name] = {"mode": run["mode"], "frozen": run["frozen"], "status": run["status"],
                                 "error": run["error"], "outcome": (run["report"] or {}).get("outcome"),
                                 "created": (run["report"] or {}).get("created"),
                                 "holds": (run["report"] or {}).get("holds")}
        _check(results, f"{name}: the run reached awaiting_publish_approval with the source loaded",
               run["status"] == "awaiting_publish_approval" and source_id in run["state"].get("loaded", [])
               and (run["report"] or {}).get("outcome") == "loaded", run["error"] or run["source"].get("reasons"))
        if xw:
            _check(results, f"{name}: the stage pinned the crosswalk version",
                   run["source"].get("crosswalk_sha256") == xw.sha256, run["source"].get("crosswalk_sha256"))
        else:
            _check(results, f"{name}: the stage pinned the native-only identity",
                   run["source"].get("identity") == crosswalk.NATIVE, run["source"].get("identity"))
    if not all(c["ok"] for c in results["checks"]):
        return results
    first = runs["empty-cache"]
    capture = json.loads(first["capture"].read_text())
    _check(results, "the first capture has no fetch errors (replays cannot hide a failed fetch)",
           not capture.get("errors"), capture.get("errors", [])[:5])
    nodes, edges = _read_export(export)
    _coherent_clock(results, runs, source_id, LISTING_RECORD[config["adapter"]])
    if xw is None:
        return _native_checks(results, source_id, config, nodes, runs, overlays, expect)

    # new Meetings == the listing-only set, by the generator's own report on this run's listing
    listing = (first["root"] / "data" / "raw" / source_id / first["frozen"][:10] / "source.html").read_text()
    base = "/".join(config["url"].split("/", 3)[:3])
    _, xreport = crosswalk.generate(source_id, config["institution_id"], export, listing, base_url=base,
                                    backfill_from=str(config.get("backfill_from", "")), previous=xw.entries)
    expected_meetings = sorted(crosswalk.adapter_id(source_id, s) for s in xreport["listing_only"])
    created = first["report"]["created"]
    results["crosswalk_report"] = {k: xreport[k] for k in ("counts", "listing_only", "kept", "graph_only", "conflicts")}
    _check(results, "new Meetings == the listing-only (adapter-only) set",
           sorted(created["nodes"].get("Meeting", [])) == expected_meetings,
           {"created": len(created["nodes"].get("Meeting", [])), "expected": len(expected_meetings)})
    expected = expected_records(capture, nodes, edges, source_id, config["institution_id"])
    results["expected_records"] = expected["classes"]
    _check(results, "new Records == the independently classified set",
           sorted(created["nodes"].get("Record", [])) == expected["created"] and not expected["holds"],
           {"created": len(created["nodes"].get("Record", [])), "expected": len(expected["created"]),
            "classes": expected["classes"], "holds": expected["holds"]})

    o_nodes, o_edges = overlays["empty-cache"]
    touched = [n["id"] for n in o_nodes if n["id"] in nodes]
    created_ids = {n["id"] for n in o_nodes}
    between_existing = [e for e in o_edges if e["start_id"] not in created_ids and e["end_id"] not in created_ids]
    _check(results, "0 changes to existing nodes, labels or relationships (the overlay holds only creates)",
           not touched and not between_existing, {"overwritten": touched, "edges_between_existing": between_existing})
    sr_meetings = {i: n["properties"] for i, n in nodes.items() if "Meeting" in n["labels"]
                   and n["properties"].get("institution_id") == config["institution_id"]}
    sr_meetings.update({n["id"]: n["properties"] for n in o_nodes if "Meeting" in n["labels"]})
    slugs = Counter(crosswalk.page_slug(p.get("meeting_page_url")) for p in sr_meetings.values()
                    if p.get("meeting_page_url"))
    dupes = sorted(s for s, c in slugs.items() if c > 1)
    _check(results, "0 duplicate Meetings (one Meeting per page slug; no new Meeting is a crosswalk target)",
           not dupes and not (set(created["nodes"].get("Meeting", [])) & set(xw.entries.values())), dupes)
    results["counts"] = {"new_meetings": len(created["nodes"].get("Meeting", [])),
                         "new_records": len(created["nodes"].get("Record", [])), "new_edges": len(created["edges"]),
                         "skipped_edges": first["report"]["skipped_edges"],
                         "protected_differences": first["report"]["protected_differences"]}

    _replays(results, source_id, config, runs, overlays)
    return results


def _replays(results: dict, source_id: str, config: dict, runs: dict, overlays: dict) -> None:
    first, populated, replay, later = (runs[v] for v in VARIANTS)
    _check(results, "empty and populated identity cache: identical capture and identical writes",
           first["capture"].read_bytes() == populated["capture"].read_bytes()
           and overlays["populated-cache"] == overlays["empty-cache"], None)
    _check(results, "a second identical run is a no-op",
           replay["capture"].read_bytes() == first["capture"].read_bytes()
           and replay["report"]["created"] == {"nodes": {}, "edges": []}
           and overlays["replay"] == overlays["empty-cache"], replay["report"]["created"])
    listing_id = f"record-{source_id}-{LISTING_RECORD[config['adapter']]}-{later['frozen'][:10]}"
    _check(results, "a later-week capture adds exactly its dated listing Record",
           later["report"]["created"] == {"nodes": {"Record": [listing_id]}, "edges": []}, later["report"]["created"])


def _native_checks(results, source_id, config, nodes, runs, overlays, expect) -> dict:
    """A native-only source: its first load against the caller's expectation (the reviewed inventory)."""
    first = runs["empty-cache"]
    capture = json.loads(first["capture"].read_text())
    created = first["report"]["created"]
    _check(results, "new Meetings == the expected set (the reviewed inventory)",
           sorted(created["nodes"].get("Meeting", [])) == sorted(expect["meetings"]),
           {"created": len(created["nodes"].get("Meeting", [])), "expected": len(expect["meetings"]),
            "unexpected": sorted(set(created["nodes"].get("Meeting", [])) - set(expect["meetings"]))[:10],
            "missing": sorted(set(expect["meetings"]) - set(created["nodes"].get("Meeting", [])))[:10]})
    records = sorted(expect["records"] + [r["id"] for r in capture.get("record_refs", [])])
    results["expected_records"] = {"meetings": len(expect["meetings"]), "artifact_records": len(expect["records"]),
                                   "listing_snapshot": len(capture.get("record_refs", [])),
                                   "stubs": sorted(expect.get("stubs", []))}
    _check(results, "new Records == the expected artifact Records + this run's listing snapshot",
           sorted(created["nodes"].get("Record", [])) == records,
           {"created": len(created["nodes"].get("Record", [])), "expected": len(records)})
    stubs = sorted(created["nodes"].get("Organization", []) + created["nodes"].get("Place", []))
    _check(results, "stubs created == the expected (absent) stubs, nothing else",
           stubs == sorted(expect.get("stubs", [])), stubs)
    o_nodes, o_edges = overlays["empty-cache"]
    touched = [n["id"] for n in o_nodes if n["id"] in nodes]
    created_ids = {n["id"] for n in o_nodes}
    between_existing = [e for e in o_edges if e["start_id"] not in created_ids and e["end_id"] not in created_ids]
    _check(results, "0 changes to existing nodes, labels or relationships (the overlay holds only creates)",
           not touched and not between_existing, {"overwritten": touched, "edges_between_existing": between_existing})
    keys = Counter(n["properties"].get("listing_key") for n in o_nodes if "Meeting" in n["labels"])
    keys.update(n["properties"].get("listing_key") for n in nodes.values() if "Meeting" in n["labels"]
                and n["properties"].get("institution_id") == config["institution_id"])
    dupes = sorted(k for k, c in keys.items() if c > 1)
    _check(results, "0 duplicate Meetings (one Meeting per listing key)", not dupes, dupes)
    results["counts"] = {"new_meetings": len(created["nodes"].get("Meeting", [])),
                         "new_records": len(created["nodes"].get("Record", [])), "new_stubs": stubs,
                         "new_edges": len(created["edges"]), "skipped_edges": first["report"]["skipped_edges"],
                         "protected_differences": first["report"]["protected_differences"]}
    _replays(results, source_id, config, runs, overlays)
    return results


def _coherent_clock(results: dict, runs: dict, source_id: str, page: str = "meetings-page") -> None:
    problems = []
    for name, run in runs.items():
        day = run["frozen"][:10]
        capture = json.loads(run["capture"].read_text())
        listing = [r["id"] for r in capture.get("record_refs", [])]
        expect = {"capture file": f"{day}.json", "capture_id": f"{source_id}__{day}", "captured_at": day,
                  "listing record": f"record-{source_id}-{page}-{day}",
                  "raw path": f"data/raw/{source_id}/{day}/source.html"}
        got = {"capture file": run["capture"].name, "capture_id": capture.get("capture_id"),
               "captured_at": (capture.get("captured_at") or "")[:10], "listing record": (listing or [None])[0],
               "raw path": capture.get("raw_artifact")}
        if got != expect or not (run["root"] / expect["raw path"]).is_file():
            problems.append({name: {"expected": expect, "got": got}})
    _check(results, "each capture is coherent with its frozen clock (ids, timestamps, paths)", not problems, problems)


def render_rehearsal(results: dict) -> str:
    lines = [f"# Rehearsal: {results['source_id']}", "",
             f"- export `{results['export']}`; crosswalk `{results['crosswalk_sha256']}`; "
             f"{results['responses']} recorded responses; work `{results['work']}`", ""]
    lines += ["| Run | Mode | Clock | Status | Outcome |", "|---|---|---|---|---|"]
    lines += [f"| {n} | {r['mode']} | {r['frozen']} | {r['status']} | {r['outcome']} |"
              for n, r in results["runs"].items()]
    lines += ["", "| Check | Result |", "|---|---|"]
    lines += [f"| {c['check']} | {'PASS' if c['ok'] else 'FAIL: ' + json.dumps(c['detail'])[:300]} |"
              for c in results["checks"]]
    if results.get("counts"):
        lines += ["", "## First load", "", "```", json.dumps(results["counts"], indent=1, sort_keys=True), "```",
                  "", "## Expected Records (independent classification)", "", "```",
                  json.dumps(results["expected_records"], indent=1, sort_keys=True), "```"]
    verdict = "PASS" if results["checks"] and all(c["ok"] for c in results["checks"]) else "FAIL"
    return "\n".join(lines + ["", f"**Rehearsal: {verdict}**", ""])


# --- check-loaded ------------------------------------------------------------------------------------------


class CheckRefused(RuntimeError):
    """check-loaded cannot bind its inputs to the named run; nothing was judged."""


def _edge_key(e: dict) -> tuple:
    return (e["start_id"], e["type"], e["end_id"], json.dumps(e.get("properties") or {}, sort_keys=True))


def _owned(nodes: dict[str, dict], edges: list[dict], source_id: str, institution_id: str, extra=frozenset()):
    """(owned node ids, every relationship touching one, as a multiset of (start, type, end, properties)).

    Owned: the source's Meetings (by institution), Records with its source_id, and Records on those
    Meetings' EVIDENCED_BY / RELATES_TO_MEETING edges. The shared stubs are not owned (other loaders
    write them); they are compared separately.
    """
    meetings = {i for i, n in nodes.items() if "Meeting" in n["labels"]
                and n["properties"].get("institution_id") == institution_id}
    owned = meetings | {i for i, n in nodes.items() if "Record" in n["labels"]
                        and n["properties"].get("source_id") == source_id} | (set(extra) & set(nodes))
    for e in edges:
        if e["type"] in LINK_TYPES and (e["start_id"] in meetings or e["end_id"] in meetings):
            other = e["end_id"] if e["start_id"] in meetings else e["start_id"]
            if "Record" in nodes.get(other, {}).get("labels", []):
                owned.add(other)
    return owned, Counter(_edge_key(e) for e in edges if e["start_id"] in owned or e["end_id"] in owned)


def check_loaded(root: Path, run_id: str, source_id: str, post_export: Path, out: Path) -> dict:
    import refresh_weekly as rw
    import yaml

    root, post_export = Path(root).resolve(), Path(post_export).resolve()
    state = rw.read_state(root, run_id)
    if "loaded" not in {h["status"] for h in state["history"]}:
        raise CheckRefused(f"run {run_id} never reached `loaded`")
    for path in sorted((root / rw.RUNS_DIR).glob("*/state.json")):
        later = json.loads(path.read_text())
        if path.parent.name > run_id and ("backup" in later or
                                          {h["status"] for h in later["history"]} & {"loaded", "load_failed"}):
            raise CheckRefused(f"run {path.parent.name} attempted a load after {run_id}; the graph is not that run's")
    source = state["sources"].get(source_id) or {}
    if not ({"crosswalk_sha256", "identity"} & set(source)) or not source.get("load_report"):
        raise CheckRefused(f"{source_id} was not a guarded (crosswalk-required or native-only) load in run {run_id}")
    backup = root / state["backup"]
    pinned = state.get("backup_sha256") or {}
    if not pinned or any(rw._sha256(backup / f) != h for f, h in pinned.items()):
        raise CheckRefused(f"the backup {state['backup']} does not match the hashes the run pinned")
    capture_path = root / source["capture"]["path"]
    if rw._sha256(capture_path) != source["capture"]["sha256"]:
        raise CheckRefused(f"the capture {source['capture']['path']} changed since the run")
    configs = yaml.safe_load((root / f"registry/{source['registry']}-sources.yaml").read_text())["sources"]
    config = next(s for s in configs if s["id"] == source_id)
    capture = json.loads(capture_path.read_text())
    if "crosswalk_sha256" in source:
        if crosswalk.sha256_file(root / config["crosswalk"]) != source["crosswalk_sha256"]:
            raise CheckRefused("the crosswalk changed since the run; check out the pinned version first")
    elif capture.get("load_policy") != crosswalk.load_policy(config):
        raise CheckRefused("the registry's load policy changed since the run; check out the run's version first")
    loaded_at = next(h["at"] for h in state["history"] if h["status"] == "loaded")
    post_files = {f: post_export / f for f in ("nodes.jsonl", "edges.jsonl")}
    if not all(p.is_file() for p in post_files.values()):
        raise CheckRefused(f"{post_export} is not an export (nodes.jsonl, edges.jsonl)")
    taken = min(datetime.fromtimestamp(p.stat().st_mtime, timezone.utc) for p in post_files.values())
    if taken < datetime.fromisoformat(loaded_at):
        raise CheckRefused(f"the post-export ({taken.isoformat()}) predates the run's load ({loaded_at})")
    reports = sorted((rw.run_dir(root, run_id) / "load-reports").glob(f"{source_id}.*.json"),
                     key=lambda p: int(p.name.rsplit(".", 2)[-2]))
    attempts = [json.loads(p.read_text()) for p in reports]
    final = json.loads((rw.run_dir(root, run_id) / "load-reports" / source["load_report"]["path"]).read_text())

    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    graph_dir = out / f"expected-graph-{run_id}"
    if graph_dir.exists():
        shutil.rmtree(graph_dir)
    graph = guarded_load.FakeGraphPort.create(graph_dir, seed=backup)
    with guarded_load.open_port(f"fakegraph://{graph}") as port:
        expected = guarded_load.load_capture(port, capture, config, root=root)
    expected.pop("normalized", None)

    results = {"run_id": run_id, "source_id": source_id, "checks": [],
               "inputs": {"backup": state["backup"], "backup_sha256": pinned, "capture": source["capture"],
                          "crosswalk_sha256": source.get("crosswalk_sha256"), "identity": source.get("identity"),
                          "post_export": str(post_export),
                          "post_export_sha256": {f: rw._sha256(p) for f, p in post_files.items()},
                          "post_export_taken": taken.isoformat(), "loaded_at": loaded_at}}
    if source.get("held") or source_id not in state.get("loaded", []) or final["outcome"] != "loaded":
        results.update(verdict="HELD", counts={"outcome": final["outcome"], "holds": final.get("holds")})
        return results
    done_nodes = sorted(i for a in attempts if a["outcome"] == "loaded" for ids in a["created"]["nodes"].values()
                        for i in ids)
    done_edges = sorted(tuple(e) for a in attempts if a["outcome"] == "loaded" for e in a["created"]["edges"])
    planned_ids = sorted(i for ids in expected["created"]["nodes"].values() for i in ids)
    _check(results, "the planner on the backup reproduces what the run's attempts created",
           expected["outcome"] == "loaded" and planned_ids == done_nodes
           and sorted(tuple(e) for e in expected["created"]["edges"]) == done_edges,
           {"expected": expected["outcome"], "attempts": [a["outcome"] for a in attempts]})
    planned_nodes, planned_rows = guarded_load.FakeGraphPort(graph).overlay()
    planned_nodes = {n["id"]: n for n in planned_nodes}
    planned_edges = Counter(_edge_key(e) for e in planned_rows)

    before_nodes, before_edges = _read_export(backup)
    after_nodes, after_edges = _read_export(post_export)
    stubs = [config["institution_id"], config["jurisdiction_id"]]
    # A stub absent before the run is this source's own once it exists (only its load may create it).
    new_stubs = {s for s in stubs if s not in before_nodes and (s in after_nodes or s in planned_nodes)}
    owned_before, edges_before = _owned(before_nodes, before_edges, source_id, config["institution_id"])
    owned_after, edges_after = _owned(after_nodes, after_edges, source_id, config["institution_id"], new_stubs)
    new_nodes = owned_after - owned_before
    _check(results, "new owned nodes == the planned creates", new_nodes == set(planned_nodes),
           {"unexpected": sorted(new_nodes - set(planned_nodes))[:20],
            "missing": sorted(set(planned_nodes) - new_nodes)[:20]})
    wrong_props = sorted(i for i in new_nodes & set(planned_nodes) if i in after_nodes
                         if after_nodes[i]["properties"] != planned_nodes[i]["properties"]
                         or sorted(after_nodes[i]["labels"]) != sorted(planned_nodes[i]["labels"]))
    _check(results, "created nodes carry exactly the planned labels and properties", not wrong_props, wrong_props[:20])
    changed = sorted(i for i in owned_before if i not in after_nodes
                     or after_nodes[i]["properties"] != before_nodes[i]["properties"]
                     or sorted(after_nodes[i]["labels"]) != sorted(before_nodes[i]["labels"]))
    _check(results, "0 changes to pre-existing owned nodes (labels, every property)", not changed,
           {"changed": len(changed), "first": changed[:20]})
    new_edges = edges_after - edges_before
    _check(results, "new relationships on owned nodes == the planned creates (with their properties, counted)",
           new_edges == planned_edges, {"unexpected": sorted(new_edges - planned_edges)[:20],
                                        "missing": sorted(planned_edges - new_edges)[:20]})
    lost = edges_before - edges_after
    _check(results, "0 pre-existing relationships on owned nodes removed or changed", not lost, sorted(lost)[:20])
    stub_changes = {s: {k: (before_nodes[s]["properties"].get(k), after_nodes.get(s, {}).get("properties", {}).get(k))
                        for k in STUB_PROPERTIES
                        if before_nodes[s]["properties"].get(k) != after_nodes.get(s, {}).get("properties", {}).get(k)}
                    for s in stubs if s in before_nodes}
    stub_labels = {s: sorted(before_nodes[s]["labels"]) == sorted(after_nodes.get(s, {}).get("labels", []))
                   for s in stubs if s in before_nodes}
    _check(results, "shared stubs: labels and the properties this source's normalizer writes unchanged",
           not any(stub_changes.values()) and all(stub_labels.values()), stub_changes)
    results["counts"] = {"new_nodes": Counter(after_nodes[i]["labels"][0] for i in new_nodes),
                         "new_edges": Counter({k[1]: 0 for k in new_edges}) + Counter(
                             k[1] for k in new_edges.elements()), "outcome": final["outcome"]}
    results["verdict"] = "PASS" if all(c["ok"] for c in results["checks"]) else "FAIL"
    return results


def render_check(results: dict) -> str:
    lines = [f"# check-loaded {results['run_id']}: {results['source_id']} — **{results['verdict']}**", "",
             "```", json.dumps(results["inputs"], indent=1, sort_keys=True), "```", "",
             "| Check | Result |", "|---|---|"]
    lines += [f"| {c['check']} | {'PASS' if c['ok'] else 'FAIL: ' + json.dumps(c['detail'], default=str)[:300]} |"
              for c in results["checks"]]
    lines += ["", "```", json.dumps(results["counts"], indent=1, sort_keys=True, default=dict), "```", ""]
    return "\n".join(lines)


# --- CLI ------------------------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    rh = sub.add_parser("rehearse", help="the weekly chain on a fake graph (staging only)")
    rh.add_argument("--source", required=True)
    rh.add_argument("--export", type=Path, required=True)
    rh.add_argument("--work", type=Path, required=True, help="a new staging directory")
    rh.add_argument("--identity-cache", type=Path, help="a meeting-identity.json to copy for the populated run")
    rh.add_argument("--responses", type=Path, help="recorded responses to replay instead of fetching")
    rh.add_argument("--expected", type=Path,
                    help="a native-only source's expected {meetings, records, stubs} (the reviewed inventory)")
    ck = sub.add_parser("check-loaded", help="after a real run: what it wrote vs what it should have (read only)")
    ck.add_argument("run_id")
    ck.add_argument("--source", help="the guarded meeting source to check (or --agenda-items)")
    ck.add_argument("--agenda-items", action="store_true", help="check the run's agenda-items stage instead")
    ck.add_argument("--post-export", type=Path,
                    help="export_live_graph.py --backup --out-dir <dir>, taken after the run")
    ck.add_argument("--root", type=Path, default=REPO)
    ck.add_argument("--out", type=Path, help="where results go (default: <post-export>/check-loaded)")
    sh = sub.add_parser("ingest-shim", help=argparse.SUPPRESS)
    sh.add_argument("--responses", type=Path, required=True)
    sh.add_argument("--mode", choices=("record", "replay", "fill"), required=True)
    sh.add_argument("--frozen", required=True)
    sh.add_argument("--override", type=Path, help="responses that answer first (a week's listing)")
    sh.add_argument("--program", choices=("ingest", "agenda"), default="ingest")
    sh.add_argument("ingest_args", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)

    if args.cmd == "ingest-shim":
        args.ingest_args = [a for a in args.ingest_args if a != "--"] if args.ingest_args[:1] == ["--"] \
            else args.ingest_args
        return _shim_main(args)
    if args.cmd == "rehearse":
        results = rehearse(args.source, args.export, args.work, identity_cache=args.identity_cache,
                           responses=args.responses, expected=args.expected)
        text = render_rehearsal(results)
        (Path(args.work) / "rehearsal.json").write_text(json.dumps(results, indent=1, default=str) + "\n")
        (Path(args.work) / "rehearsal.md").write_text(text)
        print(text)
        return 0 if results["checks"] and all(c["ok"] for c in results["checks"]) else 1
    if args.agenda_items:  # the stage pins its own before/after exports: no --post-export needed
        import agenda_rehearsal

        return agenda_rehearsal.main(["check-loaded", args.run_id, "--root", str(args.root)])
    if not args.source or not args.post_export:
        parser.error("check-loaded needs --source and --post-export (or --agenda-items)")
    out = args.out or args.post_export / "check-loaded"
    try:
        results = check_loaded(args.root, args.run_id, args.source, args.post_export, out)
    except CheckRefused as exc:
        print(f"Refused: {exc}", file=sys.stderr)
        return 2
    text = render_check(results)
    (out / "check-loaded.json").write_text(json.dumps(results, indent=1, default=dict) + "\n")
    (out / "check-loaded.md").write_text(text)
    print(text)
    return 0 if results["verdict"] == "PASS" else 1  # HELD: nothing of the source loaded; not a pass


if __name__ == "__main__":
    sys.exit(main())
