"""Automatic preparation of landed campaign exports, driven through the weekly runner.

Every preparation step (export, normalize, check-live, plan, bakes, scan) is faked by CfWorld, which models the
live graph as the set of export files it was built from. Synthetic captures in tmp_path; no network, no Neo4j,
nothing outside tmp_path.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import refresh_weekly as rw  # noqa: E402
from tests.netfile_workbooks import filing, summary, write_export  # noqa: E402
from tests.test_cf_export_due import FakeApi  # noqa: E402
from tests.test_refresh_weekly import (  # noqa: E402, F401 (fixtures)
    DUE_FAIL, FAIL, HEARTBEAT, RUN, _sha, _state, alarm_pings, ctx, pings, root, world,
)

COUNTY = {"id": "county-cf", "name": "Example County", "agency_code": "EXC", "backfill_from": "2025-01-01",
          "portal_url": "https://netfile.example/public/EXC/campaign", "jurisdiction_id": "place-example",
          "institution_id": "org-example", "adapter": "netfile"}
TOWN = {**COUNTY, "id": "town-cf", "name": "Sampleton", "agency_code": "SMP",
        "portal_url": "https://netfile.example/public/SMP/campaign", "jurisdiction_id": "place-sampleton"}
HTML_PAGE = b"<!DOCTYPE html><html></html>"


class CfWorld:
    """The live graph is the set of (source, year, sha256) export files it was built from."""

    def __init__(self, base, root: Path):
        self.base, self.root = base, root
        self.graph: frozenset = frozenset()
        self.version = 0  # bumped by a weekly load that changes other data
        self.bad = {"normalize": set(), "reconcile": set(), "plan": set(), "scan": set()}  # sha256s failing a gate
        self.hang: set[str] = set()  # step scripts that time out
        self.crash: dict[str, tuple[int, str]] = {}  # step scripts that die: (returncode, output)
        self.flows: dict[str, str] = {}  # campaign MoneyFlow id -> flow_date, as the live export holds them
        self.retire: set[str] = set()  # flows the plan retires
        self.calls: list[list[str]] = []

    def __call__(self, cmd, cwd, env, timeout):
        self.calls.append(list(cmd))
        if cmd[0] == "git":
            return self.base(cmd, cwd, env, timeout)
        script = Path(cmd[1]).name
        if script in self.hang:
            return rw.Result(-9, f"{script}: working\n", timed_out_after=timeout)
        if script in self.crash:
            return rw.Result(*self.crash[script])
        arg = lambda flag: cmd[cmd.index(flag) + 1]  # noqa: E731
        if script == "export_live_graph.py" and "--backup" in cmd:
            out = Path(arg("--out-dir"))
            out.mkdir(parents=True)
            (out / "nodes.jsonl").write_text("".join(json.dumps(line) + "\n" for line in [
                {"graph": sorted(self.graph), "v": self.version},
                *({"id": fid, "labels": ["MoneyFlow"], "properties": {"flow_date": day, "flow_type": "contribution"}}
                  for fid, day in sorted(self.flows.items()))]))
            (out / "edges.jsonl").write_text("")
            return rw.Result(0, "exported\n")
        if script == "normalize_campaign_finance.py":
            return self._normalize(Path(arg("--registry")), Path(arg("--input-root")), Path(arg("--output-root")))
        if script == "cf_migration_plan.py" and "--check-live" in cmd:
            holds = self._held_by(Path(arg("--check-live")))
            return rw.Result(0 if self._files(Path(arg("--bundle"))) == holds else 1, "check-live\n")
        if script == "cf_migration_plan.py":
            return self._plan(Path(arg("--bundle")), Path(arg("--out")))
        if script == "bake_public_substrate.py":
            return self._bake(cmd, arg)
        if script == "scan_public_substrate.py":
            ok = not (self._files(Path(arg("--bundle"))) & self._bad("scan"))
            Path(arg("--out")).write_text(json.dumps({
                "passed": ok, "gate_a_prohibited_hits": [], "gate_b_unexplained": 0 if ok else 3,
                "gate_c_reconciliation_problems": [], "gate_b_added_records": ["x"], "gate_b_removed_records": []}))
            return rw.Result(0 if ok else 1, "PASS\n" if ok else "FAIL\n")
        return self.base(cmd, cwd, env, timeout)

    def _bad(self, gate: str) -> set:
        return {f for f in self._all_files() if f[2] in self.bad[gate]}

    def _all_files(self) -> set:
        found = set()
        for path in (self.root / "data/raw").rglob("*.zip"):
            found.add((path.parts[-3], path.stem, _sha(path)))
        return found

    @staticmethod
    def _files(bundle: Path) -> frozenset:
        selection = bundle / "selection.json"
        if not selection.is_file():
            return frozenset({("no", "selection", "")})
        sources = json.loads(selection.read_text())["sources"]
        return frozenset((sid, y, e["sha256"]) for sid, s in sources.items() for y, e in s["years"].items()
                         if e["status"] == "export")

    def _held_by(self, export: Path) -> frozenset:
        nodes = json.loads((export / "nodes.jsonl").read_text().splitlines()[0])
        if "candidate_of" in nodes:
            return self._files(Path(nodes["candidate_of"]))
        return frozenset(tuple(f) for f in nodes["graph"])

    def _normalize(self, registry: Path, raw: Path, out: Path):
        sources = yaml.safe_load(registry.read_text())["sources"]
        shas = {(p.parts[-3], p.stem, _sha(p)) for p in raw.rglob("*.zip")}
        if {s for _, _, s in shas} & self.bad["normalize"]:
            return rw.Result(1, "ERROR: county-cf/2026-09-28/2026.zip: not what the registry says\n")
        for source in sources:
            sid = source["id"]
            d = out / sid
            d.mkdir(parents=True)
            bad = any(s in self.bad["reconcile"] for x, _, s in shas if x == sid)
            (d / "reconciliation.json").write_text(json.dumps(
                {"errors": 0, "groups": [{"filing_id": "f1", "status": "mismatched" if bad else "matched"}]}))
            filer = "1400001" if sid == "county-cf" else "1400002"
            (d / "filings.jsonl").write_text(json.dumps({"rpt_date": "2026-09-20", "filer_id": filer}) + "\n")
            for name in ("nodes.jsonl", "edges.jsonl"):
                (d / name).write_text("")
        (out / "run-manifest.json").write_text("{}")
        return rw.Result(0, "Normalizing\n")

    def _plan(self, bundle: Path, out: Path):
        (out / "candidate").mkdir(parents=True)
        if self._files(bundle) & self._bad("plan"):  # like the real one: the report says what failed
            (out / "migration-report.json").write_text(json.dumps({"verification": ["missing node x"]}))
            return rw.Result(1, "ERROR: missing node x\nplan: 1 verification problem(s)\n")
        (out / "candidate" / "nodes.jsonl").write_text(json.dumps({"candidate_of": str(bundle)}) + "\n")
        (out / "candidate" / "edges.jsonl").write_text("")
        (out / "migration-plan.md").write_text("# plan\n")
        (out / "ops.json").write_text(json.dumps({"retire_nodes": sorted(self.retire)}))
        (out / "migration-report.json").write_text(json.dumps({
            "summary": {"added_nodes": {"MoneyFlow": 3, "Person": 1}, "retired_nodes": 0, "changed_nodes": 1,
                        "added_edges": 6, "retired_edges": 0},
            "amounts": {"contribution": {"baseline": "10.00", "candidate": "40.00", "delta": "30.00"}}}))
        return rw.Result(0, "plan ok\n")

    def _bake(self, cmd, arg):
        sqlite = Path(arg("--sqlite"))
        sqlite.parent.mkdir(parents=True, exist_ok=True)
        export = Path(arg("--live-export-dir")) if "--live-export-dir" in cmd else None
        bundles = [cmd[i + 1] for i, c in enumerate(cmd) if c == "--campaign-bundle"]
        holds = self._held_by(export) if export else frozenset(tuple(f) for f in self.graph)
        verified = next((b for b in bundles if self._files(Path(b)) == holds), None)
        sqlite.unlink(missing_ok=True)
        with sqlite3.connect(sqlite) as conn:
            conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
            if verified:
                bid = json.loads((Path(verified) / "selection.json").read_text())["bundle_id"]
                conn.execute("INSERT INTO meta VALUES ('campaign_freshness', ?)", (json.dumps({"bundle_id": bid}),))
        (sqlite.parent / "status_manifest.json").write_text("{}")
        (sqlite.parent / "catalog.json").write_text("{}")
        Path(arg("--report")).write_text(json.dumps({
            "totals": {"nodes": 2, "edges": 1}, "sqlite": {"size_bytes": 26, "budget_bytes": 100, "within_budget": True},
            **({"campaign_freshness": {"verified_bundle": verified}} if bundles else {})}))
        return rw.Result(0, "baked\n")

    def scripts(self) -> list[str]:
        return [Path(c[1]).name for c in self.calls if c[0] != "git"]


@pytest.fixture
def cf(ctx, world, root):
    fake = CfWorld(world, root)
    ctx.runner = fake
    ctx.netfile_fetch = FakeApi()
    ctx.env[rw.HEARTBEAT_ENV] = HEARTBEAT
    (root / "registry/node-types.json").write_text("{}")
    (root / "registry/contributor-detail-reviewed.json").write_text('{"reviewed": []}')
    _registry(root, COUNTY)
    return fake


def _registry(root: Path, *sources: dict) -> None:
    (root / "registry/netfile-sources.yaml").write_text(yaml.safe_dump({"sources": list(sources)}))


def _land(root: Path, sid: str, capture: str, year: str, rpt: str = "2026-09-20", amount: int = 0) -> tuple:
    path = write_export(root / f"data/raw/{sid}/{capture}/{year}.zip",
                        {"Summary": [summary(filing(rpt=rpt), "A", "1", amount)]})
    return (sid, year, _sha(path))


def _both_years(root: Path, sid: str = "county-cf", capture: str = "2026-09-12", amount: int = 0) -> set:
    return {_land(root, sid, capture, "2025", "2026-01-31", amount), _land(root, sid, capture, "2026", amount=amount)}


def _week(ctx, cf, day: int, hour: int = 5) -> int:
    """A weekly run at 2026-09-<day> (a fresh run id each time)."""
    from datetime import datetime, timezone
    ctx.now = lambda: datetime(2026, 9, day, hour, 0, 0, tzinfo=timezone.utc)
    ctx.runner.base.git["added"] = False  # each week starts with a clean private-repo index
    return rw.main(["weekly"], ctx)


def _cf_state(root: Path) -> dict:
    return json.loads((root / "data/ingest-runs/campaign-finance.json").read_text())


def _alarm_body(alarm_pings) -> str:
    return alarm_pings[-1][1]


# --- valid, invalid --------------------------------------------------------------------------------------


def test_a_valid_capture_is_prepared_with_a_plan_and_a_passing_scan_and_the_main_run_is_clean(
        ctx, cf, root, pings, alarm_pings):
    files = _both_years(root)

    assert _week(ctx, cf, 28) == 0

    prepared = _cf_state(root)["prepared"]
    assert prepared["outcome"] == "prepared" and Path(prepared["plan"]).is_file()
    assert json.loads((Path(prepared["dir"]) / "scan.json").read_text())["passed"]
    summary_md = Path(prepared["summary"]).read_text()
    assert "MoneyFlows: 3 added, 0 retired, 1 changed" in summary_md and "Privacy scan: PASS" in summary_md
    assert cf._files(Path(prepared["bundle"])) == files
    assert [u for u, _ in pings] == [HEARTBEAT]
    assert "tell Claude 'apply'" in _alarm_body(alarm_pings) and alarm_pings[-1][0] == DUE_FAIL
    assert str(ctx.env[rw.CF_STAGING_ENV]) in prepared["dir"]
    assert _state(root)["campaign_preparation"]["status"] == "prepared"


def test_the_bakes_share_one_export_and_a_frozen_configuration(ctx, cf, root):
    _both_years(root)
    _week(ctx, cf, 28)
    bakes = [c for c in cf.calls if Path(c[1]).name == "bake_public_substrate.py" and "--attach-overlay-dir" in c]
    run = Path(_cf_state(root)["prepared"]["dir"]).parent
    assert len(bakes) == 2
    assert {c[c.index("--registry") + 1] for c in bakes} == {str(run / "config/node-types.json")}
    assert {c[c.index("--attach-overlay-dir") + 1] for c in bakes} == {str(run / "config/attach")}
    assert bakes[0][bakes[0].index("--live-export-dir") + 1] == str(run / "export")


def test_an_invalid_newest_file_is_held_and_alarmed_and_nothing_is_prepared(ctx, cf, root, alarm_pings):
    _both_years(root)
    bad = root / "data/raw/county-cf/2026-09-27/2026.zip"
    bad.parent.mkdir(parents=True)
    bad.write_bytes(HTML_PAGE)

    assert _week(ctx, cf, 28) == 0  # a data hold is the alarm's business, not a monitoring failure

    state = _cf_state(root)
    assert state["prepared"]["outcome"] == "held" and state["prepared"]["gate"] == "fallback"
    assert "normalize_campaign_finance.py" not in cf.scripts()
    body = _alarm_body(alarm_pings)
    assert "data/raw/county-cf/2026-09-27/2026.zip was not used: an HTML page" in body
    assert "no applied preparation to keep" in body


@pytest.mark.parametrize("gate,says", [("normalize", "held at normalize"), ("reconcile", "held at reconcile"),
                                       ("plan", "held at plan"), ("scan", "held at scan")])
def test_a_failing_gate_holds_that_source_named_and_the_other_source_still_prepares(
        ctx, cf, root, alarm_pings, gate, says):
    _registry(root, COUNTY, TOWN)
    applied = _both_years(root, "county-cf") | _both_years(root, "town-cf")
    cf.graph = frozenset(applied)
    assert _week(ctx, cf, 21) == 0  # bootstrap: the graph already holds these
    assert _cf_state(root)["applied"]

    county = _land(root, "county-cf", "2026-09-27", "2026", amount=5)
    town = _land(root, "town-cf", "2026-09-27", "2026", amount=7)
    cf.bad[gate].add(town[2])

    assert _week(ctx, cf, 28) == 0

    prepared = _cf_state(root)["prepared"]
    assert prepared["outcome"] == "prepared"
    files = cf._files(Path(prepared["bundle"]))
    assert county in files and town not in files  # the town keeps its applied 2026
    assert {f for f in applied if f[0] == "town-cf"} <= files
    body = _alarm_body(alarm_pings)
    assert says in body and "Recovery:" in body and "tell Claude 'apply'" in body


def test_a_single_source_gate_failure_holds_the_preparation_with_the_gate_named(ctx, cf, root, alarm_pings):
    files = _both_years(root)
    cf.bad["scan"] |= {sha for _, _, sha in files}

    assert _week(ctx, cf, 28) == 0

    prepared = _cf_state(root)["prepared"]
    assert prepared["outcome"] == "held" and prepared["gate"] == "scan"
    assert "held at scan" in _alarm_body(alarm_pings) and "scan.json" in _alarm_body(alarm_pings)


# --- selection --------------------------------------------------------------------------------------------


def test_a_newer_capture_holding_only_some_years_is_combined_with_the_older_ones(ctx, cf, root):
    old2025 = next(f for f in _both_years(root, capture="2026-09-20") if f[1] == "2025")
    new2026 = _land(root, "county-cf", "2026-09-27", "2026", amount=9)

    _week(ctx, cf, 28)

    prepared = _cf_state(root)["prepared"]
    assert cf._files(Path(prepared["bundle"])) == {old2025, new2026}
    years = json.loads((Path(prepared["bundle"]) / "selection.json").read_text())["sources"]["county-cf"]["years"]
    assert years["2025"]["capture"] == "2026-09-20" and years["2026"]["capture"] == "2026-09-27"  # some years
    assert years["2026"]["path"] == "county-cf/2026-09-27/2026.zip"


def test_a_year_that_vanishes_from_data_raw_keeps_its_applied_file(ctx, cf, root):
    files = _both_years(root)
    cf.graph = frozenset(files)
    _week(ctx, cf, 21)
    (root / "data/raw/county-cf/2026-09-12/2025.zip").unlink()  # the operator tidied up
    _land(root, "county-cf", "2026-09-27", "2026", amount=3)

    _week(ctx, cf, 28)

    bundle = cf._files(Path(_cf_state(root)["prepared"]["bundle"]))
    assert next(f for f in files if f[1] == "2025") in bundle  # absence never means retirement


# --- re-runs: no-op only while still valid -------------------------------------------------------------------


def test_an_unchanged_rerun_is_a_noop_while_the_preparation_is_still_valid(ctx, cf, root, alarm_pings):
    _both_years(root)
    _week(ctx, cf, 21)
    normalizes = cf.scripts().count("normalize_campaign_finance.py")

    assert _week(ctx, cf, 28) == 0

    assert cf.scripts().count("normalize_campaign_finance.py") == normalizes
    assert _cf_state(root)["last_preparation"]["status"] == "noop"
    assert "tell Claude 'apply'" in _alarm_body(alarm_pings)  # still awaiting approval


def test_graph_baseline_drift_regenerates_the_plan_without_a_new_download(ctx, cf, root):
    _both_years(root)
    _week(ctx, cf, 21)
    first = _cf_state(root)["prepared"]
    cf.version += 1  # the week's loads changed other data: the plan's baseline is stale

    _week(ctx, cf, 28)

    second = _cf_state(root)["prepared"]
    assert second["outcome"] == "prepared" and second["dir"] != first["dir"]
    assert second["bundle_id"] == first["bundle_id"] and second["key"][2] != first["key"][2]


def test_a_configuration_change_regenerates(ctx, cf, root):
    _both_years(root)
    _week(ctx, cf, 21)
    (root / "registry/contributor-detail-reviewed.json").write_text('{"reviewed": [], "note": "changed"}')
    _week(ctx, cf, 28)
    assert _cf_state(root)["prepared"]["key"][1] != _cf_state(root)["prepared"]["key"][0]
    assert _cf_state(root)["last_preparation"]["status"] == "prepared"


def test_a_transient_failure_fails_the_main_run_and_the_next_run_recovers_from_the_same_files(
        ctx, cf, root, pings, alarm_pings):
    _both_years(root)
    cf.hang.add("scan_public_substrate.py")

    assert _week(ctx, cf, 21) == 1

    assert pings[-1][0] == FAIL and "campaign preparation" in pings[-1][1] and "timed out" in pings[-1][1]
    assert "retried next weekly run" in _alarm_body(alarm_pings)
    cf.hang.clear()

    assert _week(ctx, cf, 28) == 0
    assert _cf_state(root)["prepared"]["outcome"] == "prepared"


def test_a_held_preparation_is_retried_every_run(ctx, cf, root):
    files = _both_years(root)
    cf.bad["scan"] |= {sha for _, _, sha in files}
    _week(ctx, cf, 21)
    scans = cf.scripts().count("scan_public_substrate.py")
    _week(ctx, cf, 28)
    assert cf.scripts().count("scan_public_substrate.py") == scans + 1


# --- applied, published, bootstrap --------------------------------------------------------------------------


def test_applying_then_publishing_clears_the_alarm(ctx, cf, root, alarm_pings):
    files = _both_years(root, capture="2026-09-13")  # still fresh by the calendar on Sunday 09-20
    _week(ctx, cf, 14)
    prepared = _cf_state(root)["prepared"]
    cf.graph = frozenset(files)  # Stuart said "apply"

    _week(ctx, cf, 21)  # the weekly bake verifies the applied bundle and publishes its freshness

    state = _cf_state(root)
    assert state["applied"]["bundle_id"] == prepared["bundle_id"]
    assert state["published"]["bundle_id"] == prepared["bundle_id"]
    assert state["last_preparation"]["status"] == "noop"
    main_bake = next(c for c in reversed(cf.calls) if Path(c[1]).name == "bake_public_substrate.py"
                     and "--attach-overlay-dir" not in c)
    assert prepared["bundle"] in main_bake
    assert alarm_pings[-1][0].endswith("?rid=qv-secret-4242&k=alpha%2Fbeta-77")  # plain: nothing due
    assert "tell Claude" not in _alarm_body(alarm_pings)


def test_bootstrap_an_already_applied_selection_publishes_on_the_next_run(ctx, cf, root, alarm_pings):
    cf.graph = frozenset(_both_years(root))

    _week(ctx, cf, 21)

    state = _cf_state(root)
    assert state["applied"] and state["prepared"]["outcome"] == "applied"
    assert "cf_migration_plan.py" in cf.scripts() and not any("--baseline" in c for c in cf.calls)  # no plan
    assert "the next weekly run publishes it" in _alarm_body(alarm_pings)

    _week(ctx, cf, 28)

    assert _cf_state(root)["published"]["bundle_id"] == state["applied"]["bundle_id"]
    assert "publishes it" not in _alarm_body(alarm_pings)


def test_a_graph_restore_invalidates_the_applied_record(ctx, cf, root):
    files = _both_years(root)
    cf.graph = frozenset(files)
    _week(ctx, cf, 21)
    cf.graph = frozenset()  # the graph was restored from an older backup

    _week(ctx, cf, 28)

    state = _cf_state(root)
    assert state["applied"] is None and state["applied_unverified"]
    assert state["prepared"]["outcome"] == "prepared"


def test_preparation_never_runs_after_a_load_that_stopped_partway(ctx, cf, root):
    _both_years(root)
    cf.base.exit_codes["normalize_meetings.py"] = 1  # a load step fails: load_failed

    _week(ctx, cf, 28)

    assert _state(root)["status"] == "load_failed" and "campaign_preparation" not in _state(root)
    assert "normalize_campaign_finance.py" not in cf.scripts()


def test_nothing_writes_the_live_graph(ctx, cf, root):
    _both_years(root)
    _week(ctx, cf, 28)
    prep = [c for c in cf.calls if c[0] != "git" and "cf-staging" in " ".join(c)]
    assert prep and not any("--load" in c or "--load-from" in c for c in prep)
    assert {Path(c[1]).name for c in prep} <= {"export_live_graph.py", "normalize_campaign_finance.py",
                                                 "cf_migration_plan.py", "bake_public_substrate.py",
                                                 "scan_public_substrate.py"}
    assert all("--backup" in c for c in prep if Path(c[1]).name == "export_live_graph.py")


# --- Codex round 2: coverage, staging guard, artifacts, crash vs hold ----------------------------------------


def test_years_the_applied_bundle_has_survive_a_narrower_backfill(ctx, cf, root):
    files = _both_years(root)
    cf.graph = frozenset(files)
    _week(ctx, cf, 21)
    _registry(root, {**COUNTY, "backfill_from": "2026-01-01"})
    _land(root, "county-cf", "2026-09-27", "2026", amount=4)

    _week(ctx, cf, 28)

    assert next(f for f in files if f[1] == "2025") in cf._files(Path(_cf_state(root)["prepared"]["bundle"]))


def test_a_misconfigured_source_stops_preparation_instead_of_retiring_its_flows(ctx, cf, root, pings):
    _registry(root, COUNTY, {k: v for k, v in TOWN.items() if k != "agency_code"})
    _both_years(root)

    assert _week(ctx, cf, 28) == 1  # the alarm's config problem fails the main run

    assert "normalize_campaign_finance.py" not in cf.scripts() and "lacks agency_code" in pings[-1][1]


def test_retiring_flows_in_years_no_export_covers_holds_the_plan(ctx, cf, root, alarm_pings):
    cf.graph = frozenset(_both_years(root))  # 2025 and 2026 only
    _week(ctx, cf, 21)  # bootstrap: applied
    _land(root, "county-cf", "2026-09-27", "2026", amount=8)
    cf.flows = {"moneyflow-1400001-OLD1": "2024-03-01", "moneyflow-1400001-NEW1": "2026-02-01"}
    cf.retire = {"moneyflow-1400001-OLD1"}  # 2024: no export in this bundle explains its retirement

    _week(ctx, cf, 28)

    prepared = _cf_state(root)["prepared"]
    assert prepared["outcome"] == "held" and prepared["gate"] == "coverage"
    assert "moneyflow-1400001-OLD1" in _alarm_body(alarm_pings)


def test_retiring_a_flow_in_a_covered_year_is_an_ordinary_amendment(ctx, cf, root):
    cf.graph = frozenset(_both_years(root))
    _week(ctx, cf, 21)  # bootstrap: applied
    _land(root, "county-cf", "2026-09-27", "2026", amount=8)
    cf.flows = {"moneyflow-1400001-AMEND": "2026-02-01"}
    cf.retire = {"moneyflow-1400001-AMEND"}

    _week(ctx, cf, 28)

    assert _cf_state(root)["prepared"]["outcome"] == "prepared"


def test_without_an_applied_preparation_a_plan_that_retires_flows_holds_for_review(ctx, cf, root, alarm_pings):
    """The live graph was changed outside the preparations (say, a hand-built bundle applied) and data/raw lacks
    those exports: a plan from what data/raw offers would roll it back."""
    _both_years(root)
    cf.graph = frozenset({("county-cf", "2026", "f" * 64)})  # holds something data/raw does not offer
    cf.flows = {"moneyflow-1400001-NEWER": "2026-08-01"}
    cf.retire = {"moneyflow-1400001-NEWER"}

    _week(ctx, cf, 28)

    prepared = _cf_state(root)["prepared"]
    assert prepared["outcome"] == "held" and prepared["gate"] == "baseline"
    assert "land in data/raw the exports the live graph was built from" in _alarm_body(alarm_pings)


@pytest.mark.parametrize("where", ["root", "data/raw", "data"])
def test_a_staging_root_inside_the_repo_is_refused_before_anything_is_written(ctx, cf, root, pings, where):
    _both_years(root)
    staging = root / where / "cf-staging-here"
    ctx.env[rw.CF_STAGING_ENV] = str(staging)

    assert _week(ctx, cf, 28) == 1

    assert not staging.exists() and "staging" in pings[-1][1]


def test_a_noop_requires_every_artifact_unchanged(ctx, cf, root):
    _both_years(root)
    _week(ctx, cf, 21)
    first = _cf_state(root)["prepared"]
    (Path(first["dir"]) / "plan" / "ops.json").write_text('{"tampered": true}')

    _week(ctx, cf, 28)

    second = _cf_state(root)["prepared"]
    assert second["dir"] != first["dir"] and _cf_state(root)["last_preparation"]["status"] == "prepared"


@pytest.mark.parametrize("script,result", [
    ("scan_public_substrate.py", (-9, "")),
    ("cf_migration_plan.py", (1, "Traceback (most recent call last):\n  ...\nMemoryError\n")),
    ("normalize_campaign_finance.py", (1, "Traceback (most recent call last):\nOSError: disk\n")),
])
def test_a_crash_is_transient_never_a_data_hold(ctx, cf, root, pings, script, result):
    _both_years(root)
    if script == "cf_migration_plan.py":  # check-live must still answer; only the plan run crashes
        cf._plan = lambda bundle, out: rw.Result(*result)
    else:
        cf.crash[script] = result

    assert _week(ctx, cf, 28) == 1

    assert _cf_state(root)["prepared"].get("outcome") != "held"
    assert "campaign preparation" in pings[-1][1]


def test_retiring_a_flow_whose_filer_no_bundle_filing_names_holds_the_plan(ctx, cf, root):
    cf.graph = frozenset(_both_years(root))
    _week(ctx, cf, 21)
    _land(root, "county-cf", "2026-09-27", "2026", amount=8)
    cf.flows = {"moneyflow-1499999-GONE": "2026-02-01"}  # a covered year, but no export names this filer
    cf.retire = {"moneyflow-1499999-GONE"}

    _week(ctx, cf, 28)

    assert _cf_state(root)["prepared"]["gate"] == "coverage"


def test_a_source_dropped_from_the_registry_keeps_its_applied_files(ctx, cf, root):
    _registry(root, COUNTY, TOWN)
    town = _both_years(root, "town-cf")
    cf.graph = frozenset(_both_years(root) | town)
    _week(ctx, cf, 21)
    _registry(root, COUNTY)
    _land(root, "county-cf", "2026-09-27", "2026", amount=6)

    _week(ctx, cf, 28)

    prepared = _cf_state(root)["prepared"]
    assert prepared["outcome"] == "prepared" and town <= cf._files(Path(prepared["bundle"]))
