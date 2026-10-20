#!/usr/bin/env python3
"""Votes Part B2, increment d: apply the approved additive plan to the operator graph — only on Stuart's "apply".

    python scripts/votes_apply.py apply --state-dir ~/open-marin-staging/votes-b --approve <sha256> \\
        --canonical-root ~/projects/marin-civic-graph

1. Before any driver opens: the state is AWAITING_APPLY, `--approve` equals the sha256 of
   plan/approval-inputs.json, every file it lists still has its recorded sha256, and NEO4J_URI is exactly
   bolt://localhost:7688. The ops executed are parsed from the verified ops.json bytes.
2. The weekly run's lock in the canonical checkout (scripts/run_lock.py) is held through every later step.
3. A fresh full-fidelity export (`--backup`) to apply/pre-apply-backup must equal the plan's baseline (else DRIFT,
   nothing written).
4. One transaction: case_additive_plan.apply_in_transaction (prechecks 0, exact counts), then the whole graph is
   re-read inside the same transaction and must equal the planned candidate byte for byte; otherwise it is left
   uncommitted (ROLLED_BACK). A commit that raises may still have committed: APPLY_UNVERIFIED (commit_uncertain).
5. A post-commit export to apply/post-apply-export must equal the candidate → APPLIED; anything else is
   APPLY_UNVERIFIED with apply/RECOVERY.md. Nothing is ever retried automatically; the backup is never touched.

`check-published` verifies a published artifact against plan/expected-edges.jsonl (and two real pages).
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

from case_additive_plan import apply_in_transaction, fingerprint
from export_live_graph import _iter_edge_page_rows, _iter_node_page_rows, _stable_line, export_live_graph
from run_lock import RunLockHeld, run_lock

OPERATOR_URI = "bolt://localhost:7688"
STATES = ("AWAITING_MAPPING_REVIEW", "AWAITING_APPLY", "APPLIED", "ROLLED_BACK", "APPLY_UNVERIFIED",
          "PUBLISHED_VERIFIED",
          # the votes refresh's revisions (scripts/votes_refresh.py)
          "AWAITING_REVIEW", "ALL_HELD", "AWAITING_ROSTER_REVIEW",
          # published durably just before the transaction opens; a crash leaves it, never AWAITING_APPLY
          "APPLY_IN_PROGRESS", "PREPARING")
SCOPE = ("decision-novato-city-council-", "decision-marin-county-bos-", "vev-novato-city-council-",
         "vev-marin-county-bos-")
APPROVAL = Path("plan/approval-inputs.json")
__all__ = ["RunLockHeld"]


class ApplyRefused(Exception):
    """Nothing was opened or written."""


def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def get_state(state_dir: Path) -> str | None:
    path = Path(state_dir) / "state.json"
    return json.loads(path.read_text())["state"] if path.exists() else None


def set_state(state_dir: Path, state: str, **detail) -> None:
    if state not in STATES:
        raise ValueError(state)
    path = Path(state_dir) / "state.json"
    try:
        history = json.loads(path.read_text()).get("history", []) if path.exists() else []
        if not isinstance(history, list) or not all(isinstance(h, dict) for h in history):
            raise ValueError("history is not a list of entries")
    except (OSError, ValueError, AttributeError):  # an unreadable state is kept beside, never parsed into history
        raw = path.read_bytes()
        keep = path.with_name(f"state.json.unreadable-{_sha_bytes(raw)[:8]}")
        keep.write_bytes(raw)
        history = [{"state": "UNREADABLE", "kept": keep.name}]
    data = json.dumps({"state": state, **detail, "history": history + [{"state": state, **detail}]},
                      indent=1, sort_keys=True) + "\n"
    tmp = path.with_name(".state.json.tmp")  # the old or the new file, never a torn one
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def refresh_batch(state_dir: Path):
    """For a votes-refresh revision dir, its refresh root (else None). A dir under the refresh batches root without
    its marker is refused: it must never be applied as if it were an ordinary state dir."""
    import votes_refresh

    d = Path(state_dir).resolve()
    root = votes_refresh.REFRESH_ROOT.resolve() / "batches"
    marked = (d / votes_refresh.MARKER).is_file()
    if d.is_relative_to(root) and not marked:
        raise ApplyRefused(f"{d} is under the votes refresh but has no {votes_refresh.MARKER}")
    return d.parents[2] if marked else None


def expected_edges(ops: dict) -> list[dict]:
    """The publication oracle: every planned CAST_VOTE as (start, end, vote), sorted."""
    return sorted(({"start_id": e["start_id"], "end_id": e["end_id"], "vote": e["properties"]["vote"]}
                   for e in ops["add_edges"] if e["type"] == "CAST_VOTE"),
                  key=lambda r: (r["start_id"], r["end_id"]))


def write_approval(state_dir: Path, files: dict[str, Path]) -> str:
    """Record path + sha256 of every file the approval covers; the state becomes AWAITING_APPLY. Returns the
    approval sha256 Stuart's "apply" is bound to."""
    state_dir = Path(state_dir)
    report_path = files.get("plan/plan-report.json")
    if report_path is None:
        raise ApplyRefused("the approval must cover plan/plan-report.json")
    report = json.loads(Path(report_path).read_text())
    if report.get("verification"):
        raise ApplyRefused(f"the plan has verification problems: {report['verification'][:3]}")
    manifest = {name: {"path": str(Path(p).resolve()), "sha256": _sha_bytes(Path(p).read_bytes())}
                for name, p in sorted(files.items())}
    path = state_dir / APPROVAL
    path.write_text(json.dumps({"files": manifest}, indent=1, sort_keys=True) + "\n")
    sha = _sha_bytes(path.read_bytes())
    set_state(state_dir, "AWAITING_APPLY", approval_sha256=sha)
    return sha


def prepare(state_dir: Path, *, bundle: Path, plan: Path, sheet: Path, review: Path, bake_check: Path) -> str:
    """AWAITING_APPLY, only for a final bundle that equals its manifest, a clean votes-b plan of exactly that
    bundle on exactly the bundle's baseline, a fully answered spot check whose doubts are all held, and a clean
    staging bake. Writes plan/expected-edges.jsonl and the approval manifest; returns the approval sha256."""
    state_dir, bundle, plan = Path(state_dir), Path(bundle), Path(plan)
    inputs = json.loads((bundle / "inputs.json").read_text())
    if inputs.get("provisional") is not False:
        raise ApplyRefused("the bundle is provisional (built before the mapping review was answered)")
    if json.loads((bundle / "accounting.json").read_text()).get("matches_expected") is not True:
        raise ApplyRefused("the bundle does not match the expected-disposition manifest")
    report = json.loads((plan / "plan-report.json").read_text())
    if report.get("profile") != "votes-b" or report.get("verification") or not report.get("baseline_reexport_identical"):
        raise ApplyRefused("the plan is not a clean votes-b plan")
    if report["case"]["sha256"] != fingerprint(bundle):
        raise ApplyRefused("the plan was made from another bundle")
    pinned = {name.split("/")[1]: inputs["inputs"][name]["sha256"]
              for name in ("baseline/nodes.jsonl", "baseline/edges.jsonl")}
    if report["baseline"]["sha256"] != pinned:
        raise ApplyRefused("the plan's baseline is not the bundle's baseline")
    fp = fingerprint(bundle)
    sheet_text = Path(sheet).read_text()
    if f"Bundle: nodes {fp['nodes.jsonl']} edges {fp['edges.jsonl']}" not in sheet_text:
        raise ApplyRefused("the spot-check sheet was drawn from another bundle")
    first = (Path(review).read_text().splitlines() or [""])[0]
    if first != f"Sheet sha256: {_sha_bytes(sheet_text.encode())}":
        raise ApplyRefused("the spot-check review is not of this sheet (first line `Sheet sha256: <sha>`)")
    bake = json.loads(Path(bake_check).read_text())
    if bake.get("candidate_sha256") != report["candidate_sha256"] or bake.get("bundle_sha256") != fp:
        raise ApplyRefused("the staging bake check was not made from this plan's candidate and bundle")
    attached = {json.loads(x)["event_id"] for x in (bundle / "dispositions.jsonl").read_text().splitlines()
                if x.strip() and json.loads(x)["reason"] == "attached"}
    problems = review_problems(Path(sheet).read_text(), Path(review).read_text(), attached=attached)
    if problems or not re.search(r"^### S\d+\.", Path(sheet).read_text(), re.M):
        raise ApplyRefused(f"spot check: {problems[:5] or ['the sheet has no items']}")
    if json.loads(Path(bake_check).read_text()).get("problems") != []:
        raise ApplyRefused("the staging bake check has problems")
    ops = json.loads((plan / "ops.json").read_text())
    (plan / "expected-edges.jsonl").write_text("".join(_stable_line(r) + "\n" for r in expected_edges(ops)))
    files = {f"plan/{rel}": plan / rel for rel in ("ops.json", "plan-report.json", "inverse.json",
                                                    "expected-edges.jsonl", "candidate/nodes.jsonl",
                                                    "candidate/edges.jsonl")}
    files.update({f"bundle/{p.name}": p for p in sorted(bundle.iterdir()) if p.is_file()})
    files.update({f"input/{name}": Path(entry["path"]) for name, entry in inputs["inputs"].items()})
    files.update({"spot-check.md": Path(sheet), "spot-check-review.md": Path(review), "bake-check.json": Path(bake_check)})
    for name, entry in inputs["inputs"].items():
        if _sha_bytes(Path(entry["path"]).read_bytes()) != entry["sha256"]:
            raise ApplyRefused(f"bundle input {name} changed since the bundle was built")
    return write_approval(state_dir, files)


def approval_sha(state_dir: Path) -> str:
    return _sha_bytes((Path(state_dir) / APPROVAL).read_bytes())


def _verify_approval(state_dir: Path, approve: str) -> dict:
    if get_state(state_dir) != "AWAITING_APPLY":
        raise ApplyRefused(f"state is {get_state(state_dir)}, not AWAITING_APPLY")
    raw = (state_dir / APPROVAL).read_bytes()
    if _sha_bytes(raw) != approve:
        raise ApplyRefused("--approve does not match plan/approval-inputs.json")
    verified = {}
    for name, entry in sorted(json.loads(raw)["files"].items()):
        path = Path(entry["path"])
        data = path.read_bytes() if path.is_file() else None
        if data is None or _sha_bytes(data) != entry["sha256"]:
            raise ApplyRefused(f"{name} changed since the approval was recorded")
        verified[name] = data
    return verified  # name → the exact bytes that were hashed; callers parse these, never the files again


def _tx_fingerprint(tx) -> dict:
    """The whole graph as this transaction sees it, in export_live_graph --backup's exact bytes."""
    out = {}
    for name, rows in (("nodes.jsonl", _iter_node_page_rows(tx, batch_size=10_000, progress=lambda _: None,
                                                             keep_all=True)),
                       ("edges.jsonl", _iter_edge_page_rows(tx, batch_size=10_000, progress=lambda _: None,
                                                            keep_all=True))):
        h = hashlib.sha256()
        for row in rows:
            h.update((_stable_line(row) + "\n").encode("utf-8"))
        out[name] = h.hexdigest()
    return out


def _recovery(state_dir: Path, reason: str, detail: str, inverse: str | None = None) -> None:
    (state_dir / "apply" / "RECOVERY.md").write_text("\n".join([
        f"# APPLY_UNVERIFIED — {reason}", "", detail, "",
        "Nothing is retried automatically. To recover:",
        f"1. The untouched pre-apply backup: `{state_dir / 'apply' / 'pre-apply-backup'}` (equals the plan baseline).",
        inverse or (f"2. Additions only: run `{state_dir / 'plan' / 'inverse.json'}`'s statements in ONE transaction, "
                    "each counting exactly its rows; or restore the whole graph from the backup with "
                    "`restore_neo4j_local.py`."),
        "3. Re-export (`export_live_graph.py --backup`) and compare with the backup / candidate before any next step.",
        ""]) + "\n")


def run_apply(state_dir: Path, *, approve: str, canonical_root: Path, uri: str | None, driver_factory,
               database: str, exporter=export_live_graph, apply_ops=None, precheck=None, inverse: str | None = None) -> str:
    """For a votes-refresh revision the refresh lock is taken FIRST (then the weekly lock) and held throughout: the
    refresh guard (current revision, not released, no covering roster hold) is checked under it, and the journal is
    written before it is released."""
    state_dir = Path(state_dir)
    root = refresh_batch(state_dir)
    if root is None:
        return _run_apply(state_dir, approve=approve, canonical_root=canonical_root, uri=uri,
                          driver_factory=driver_factory, database=database, exporter=exporter, apply_ops=apply_ops,
                          precheck=precheck, inverse=inverse)
    import votes_refresh
    reg = votes_refresh.Registry(root)
    with reg.locked():
        try:
            votes_refresh.apply_guard(state_dir, reg)
        except votes_refresh.RefreshError as exc:
            raise ApplyRefused(str(exc)) from None
        result = _run_apply(state_dir, approve=approve, canonical_root=canonical_root, uri=uri,
                            driver_factory=driver_factory, database=database, exporter=exporter)
        votes_refresh.sync_journal(root, reg)
        return result


def _run_apply(state_dir: Path, *, approve: str, canonical_root: Path, uri: str | None, driver_factory,
               database: str, exporter=export_live_graph, apply_ops=None, precheck=None, inverse=None) -> str:
    """`apply_ops(tx, ops)` runs the plan's statements (default: the additive plan's); `precheck()`, under the lock
    before any driver opens, may refuse (ApplyRefused); `inverse` is RECOVERY.md's undo step."""
    apply_ops = apply_ops or apply_in_transaction
    verified = _verify_approval(state_dir, approve)
    if uri != OPERATOR_URI:
        raise ApplyRefused(f"NEO4J_URI must be {OPERATOR_URI} (got {uri!r})")
    ops = json.loads(verified["plan/ops.json"])
    report = json.loads(verified["plan/plan-report.json"])
    apply_dir = state_dir / "apply"
    with run_lock(Path(canonical_root)):
        if precheck is not None:
            precheck()
        apply_dir.mkdir(exist_ok=True)
        driver = driver_factory()
        try:
            backup = apply_dir / "pre-apply-backup"
            exporter(driver, database=database, out_dir=backup, backup=True, progress=None)
            if fingerprint(backup) != report["baseline"]["sha256"]:
                return "DRIFT"  # state stays AWAITING_APPLY; re-plan
            set_state(state_dir, "APPLY_IN_PROGRESS", approval_sha256=approve)
            # No `with` around the transaction: neo4j 5's Transaction COMMITS when such a block exits normally.
            with driver.session(database=database) as session:
                tx = session.begin_transaction()
                try:
                    apply_ops(tx, ops)
                    verified = _tx_fingerprint(tx) == report["candidate_sha256"]
                except Exception as exc:  # nothing committed yet: roll back and say so
                    tx.rollback()
                    set_state(state_dir, "ROLLED_BACK", reason=f"before commit: {exc!r}")
                    return "ROLLED_BACK"
                if not verified:
                    tx.rollback()
                    set_state(state_dir, "ROLLED_BACK", reason="in_transaction_mismatch")
                    return "ROLLED_BACK"
                try:
                    tx.commit()
                    committed = True
                except Exception as exc:  # the server may have committed before the error reached us
                    committed = repr(exc)
            post, err = apply_dir / "post-apply-export", None
            try:
                exporter(driver, database=database, out_dir=post, backup=True, progress=None)
                matches = fingerprint(post) == report["candidate_sha256"]
            except Exception as exc:
                matches, err = None, repr(exc)
            if committed is not True:
                seen = ("the post-apply export MATCHES the candidate" if matches is True else
                        "the post-apply export does NOT match the candidate" if matches is False else
                        f"the post-apply export failed: {err}")
                _recovery(state_dir, "commit_uncertain", f"tx.commit() raised {committed}; {seen}.", inverse)
                set_state(state_dir, "APPLY_UNVERIFIED", reason="commit_uncertain")
                return "APPLY_UNVERIFIED"
            if matches is True:
                set_state(state_dir, "APPLIED", approval_sha256=approve)
                return "APPLIED"
            reason = "post_export_mismatch" if matches is False else "post_export_failed"
            _recovery(state_dir, reason, "Committed, but the post-apply export does not equal the candidate."
                      if matches is False else f"Committed, but the post-apply export failed: {err}", inverse)
            set_state(state_dir, "APPLY_UNVERIFIED", reason=reason)
            return "APPLY_UNVERIFIED"
        finally:
            driver.close()


def check_published_edges(sqlite_path: Path, expected: list[dict], *, scope: tuple[str, ...]) -> list[str]:
    """Problems: the artifact's CAST_VOTE edges into Decisions whose id starts with a `scope` prefix must equal the
    expected (start, end, vote) set exactly."""
    con = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)
    try:
        have = {(s, t, (json.loads(p) or {}).get("vote") if p else None)
                for s, t, p in con.execute("SELECT source, target, props FROM edges WHERE rel = 'CAST_VOTE'")
                if t.startswith(scope)}
    finally:
        con.close()
    want = {(e["start_id"], e["end_id"], e["vote"]) for e in expected}
    problems = [f"missing {x}" for x in sorted(want - have)[:20]] + [f"unexpected {x}" for x in sorted(have - want)[:20]]
    if want != have:
        problems.append(f"{len(want - have)} missing, {len(have - want)} unexpected of {len(want)} expected")
    return problems


VOTE_LABEL = {"aye": "voted aye", "no": "voted no", "abstain": "abstained", "absent": "absent", "recused": "recused"}
FORBIDDEN_DECISION_KEYS = frozenset({"motion_text", "ayes", "noes", "recused", "absent", "abstain", "mover",
                                     "seconder", "tally", "embedding", "excerpt", "evidence", "motion"})


def bake_problems(sqlite_path: Path, new_nodes: list[dict], expected: list[dict], *,
                  scope: tuple[str, ...], check_edges: bool = True) -> list[str]:
    """A staging bake of the candidate: every new Decision has its planned label as nodes.search_label and in
    the FTS index, public props that are a subset of what was planned and carry nothing forbidden; the scoped
    CAST_VOTE edges equal the expected set."""
    con = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)
    problems = []
    try:
        for n in new_nodes:
            if "Decision" not in n["labels"]:
                continue
            row = con.execute("SELECT rowid, type, search_label, props FROM nodes WHERE id = ?", (n["id"],)).fetchone()
            if row is None:
                problems.append(f"{n['id']}: not in the bake")
                continue
            rowid, typ, label, props = row
            want = n["properties"]["search_label"]
            if typ != "Decision" or label != want:
                problems.append(f"{n['id']}: search_label {label!r} is not the planned {want!r}")
            for column, value in (("search_label", want), ("search_terms", n["properties"].get("search_terms", ""))):
                phrase = '"' + value.replace('"', " ") + '"'
                hits = {r for (r,) in con.execute("SELECT rowid FROM search_fts WHERE search_fts MATCH ?",
                                                  (f"{column} : {phrase}",))} if value.strip() else set()
                if rowid not in hits:
                    what = "label is" if column == "search_label" else "search_terms are"
                    problems.append(f"{n['id']}: its {what} not in the FTS index")
            baked = json.loads(props)
            allowed = _public_decision_keys()
            extra = sorted(set(baked) - set(n["properties"]))
            hidden = sorted(set(baked) - allowed)
            bad = sorted(set(baked) & FORBIDDEN_DECISION_KEYS)
            if extra or bad:
                problems.append(f"{n['id']}: public props {extra + bad} were not planned or are forbidden")
            if hidden:
                problems.append(f"{n['id']}: props {hidden} are not public Decision properties")
            for key, value in sorted(baked.items()):
                if not isinstance(value, (str, int, float, bool)):
                    problems.append(f"{n['id']}: public prop {key} is not a scalar")
    finally:
        con.close()
    return problems + (check_published_edges(sqlite_path, expected, scope=scope) if check_edges else [])


# --- the votes refresh: verification scoped to one batch's target Decisions --------------------------------------

def _cast_votes(sqlite_path: Path) -> dict[tuple[str, str], dict | None]:
    con = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)
    try:
        return {(s, t): (json.loads(p) if p else None)
                for s, t, p in con.execute("SELECT source, target, props FROM edges WHERE rel = 'CAST_VOTE'")}
    finally:
        con.close()


def check_target_edges(sqlite_path: Path, expected: list[dict], targets: list[str]) -> list[str]:
    """The CAST_VOTE edges into exactly the batch's target Decisions equal the expected (start, end, vote) set."""
    scope = set(targets)
    have = {(s, t, (p or {}).get("vote")) for (s, t), p in _cast_votes(sqlite_path).items() if t in scope}
    want = {(e["start_id"], e["end_id"], e["vote"]) for e in expected}
    problems = [f"missing {x}" for x in sorted(want - have)[:20]] + [f"unexpected {x}" for x in sorted(have - want)[:20]]
    if want != have:
        problems.append(f"{len(want - have)} missing, {len(have - want)} unexpected of {len(want)} expected on "
                        f"{len(scope)} target Decisions")
    return problems


def baseline_votes_preserved(sqlite_path: Path, baseline_edges: list[dict]) -> list[str]:
    """Every baseline CAST_VOTE is in the artifact with its public properties unchanged (the bake's own projection,
    registry/edge-properties.json)."""
    from public_edge_props import EdgePropStats, load_edge_allowlist, public_edge_props

    allow, stats = load_edge_allowlist(), EdgePropStats()
    have = _cast_votes(sqlite_path)
    problems = []
    for e in sorted((e for e in baseline_edges if e["type"] == "CAST_VOTE"), key=lambda e: (e["start_id"], e["end_id"])):
        key = (e["start_id"], e["end_id"])
        want = public_edge_props("CAST_VOTE", e["properties"], allow, stats)
        if key not in have:
            problems.append(f"baseline vote {key} is missing")
        elif have[key] != want:
            problems.append(f"baseline vote {key} changed: {want} → {have[key]}")
    return problems


def unplanned_votes(sqlite_path: Path, baseline_edges: list[dict], expected: list[dict]) -> list[str]:
    """Staging only: the candidate's bake holds no CAST_VOTE beyond the baseline's and this batch's."""
    known = {(e["start_id"], e["end_id"]) for e in baseline_edges if e["type"] == "CAST_VOTE"} | \
        {(e["start_id"], e["end_id"]) for e in expected}
    return [f"unplanned vote {k}" for k in sorted(set(_cast_votes(sqlite_path)) - known)]


def refresh_publication_problems(sqlite_path: Path, expected: list[dict], targets: list[str],
                                 baseline_edges: list[dict]) -> list[str]:
    """A published artifact: this batch's targets exact and every baseline vote unchanged. Votes elsewhere (later
    batches) are allowed."""
    return check_target_edges(sqlite_path, expected, targets) + baseline_votes_preserved(sqlite_path, baseline_edges)


def refresh_page_targets(expected: list[dict], *, new_ids: set[str]) -> dict[str, str]:
    """Per body present in the batch: its first new-Decision target, else its first existing-Decision target."""
    out: dict[str, str] = {}
    for body in ("marin-county-bos", "novato-city-council"):
        mine = sorted({e["end_id"] for e in expected if e["end_id"].startswith((f"vev-{body}-", f"decision-{body}-"))})
        if mine:
            out[body] = next((t for t in mine if t in new_ids), mine[0])
    return out


def existing_target_problems(sqlite_path: Path, baseline_nodes: list[dict], targets: list[str]) -> list[str]:
    """An existing target Decision keeps exactly the public projection of its baseline properties."""
    allowed = _public_decision_keys()
    base = {n["id"]: n for n in baseline_nodes}
    con = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)
    problems = []
    try:
        for t in sorted(set(targets) & set(base)):
            row = con.execute("SELECT props FROM nodes WHERE id = ?", (t,)).fetchone()
            if row is None:
                problems.append(f"{t}: not in the bake")
                continue
            baked = json.loads(row[0] or "{}")
            want = {k: v for k, v in base[t]["properties"].items() if k in allowed}
            bad = sorted((set(baked) - allowed) | (set(baked) & FORBIDDEN_DECISION_KEYS))
            if bad:
                problems.append(f"{t}: public props {bad} are not public Decision properties")
            if baked != want:
                problems.append(f"{t}: public props {baked} are not the baseline's public projection {want}")
    finally:
        con.close()
    return problems


def refresh_bake_problems(sqlite_path: Path, new_nodes: list[dict], expected: list[dict], targets: list[str],
                          baseline_nodes: list[dict], baseline_edges: list[dict]) -> list[str]:
    """A staging bake of a refresh batch's candidate: the new Decisions as B2 checks them, the existing targets'
    public props unchanged, exact edges on the batch's targets, every baseline vote preserved, nothing unplanned."""
    return (bake_problems(sqlite_path, new_nodes, expected, scope=(), check_edges=False)
            + existing_target_problems(sqlite_path, baseline_nodes, targets)
            + check_target_edges(sqlite_path, expected, targets)
            + baseline_votes_preserved(sqlite_path, baseline_edges)
            + unplanned_votes(sqlite_path, baseline_edges, expected))


def _approved_file(state_dir: Path, name: str) -> bytes:
    """A file's bytes, only if the applied approval recorded exactly these bytes for it."""
    state = json.loads((Path(state_dir) / "state.json").read_text())
    raw = (Path(state_dir) / APPROVAL).read_bytes()
    if not state.get("approval_sha256") or _sha_bytes(raw) != state["approval_sha256"]:
        raise ApplyRefused("the approval manifest is not the one that was applied")
    entry = json.loads(raw)["files"].get(name)
    data = Path(entry["path"]).read_bytes() if entry and Path(entry["path"]).is_file() else None
    if data is None or _sha_bytes(data) != entry["sha256"]:
        raise ApplyRefused(f"{name} is not the approved file")
    return data


def _public_decision_keys() -> frozenset[str]:
    from public_props import _ALLOWED
    return _ALLOWED["Decision"]


def review_problems(sheet: str, review: str, *, attached: set[str]) -> list[str]:
    """Every spot-check item answered; any disagree or unsure item's event must not be attached."""
    items = dict(re.findall(r"^### (S\d+)\. (\S+)", sheet, re.M))
    answers = {m.group(1): m.group(2) for m in re.finditer(r"^(S\d+)\s+(agree|disagree|unsure)\b", review, re.M)}
    problems = [f"{k} is not answered" for k in items if k not in answers]
    problems += [f"{k} is not in the sheet" for k in answers if k not in items]
    problems += [f"{k} ({items[k]}) is {v} but still attached" for k, v in answers.items()
                 if v != "agree" and k in items and items[k] in attached]
    return problems


def page_problems(page_html: str, votes: list[tuple[str, str]]) -> list[str]:
    """A Decision page shows every planned member with that member's own vote label: the first label after the
    member's name, before the next member's, must be the planned one."""
    text = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", page_html)).split())
    labels = "|".join(re.escape(x) for x in VOTE_LABEL.values())
    others = sorted({n for n, _ in votes}, key=len, reverse=True)
    stop = re.compile("|".join([r"\bPerson\b", *(re.escape(n) for n in others)]))
    problems = []
    for name, vote in votes:
        if name not in text:
            problems.append(f"{name} is not on the page")
            continue
        shown = []
        for m in re.finditer(re.escape(name), text):
            tail = text[m.end():m.end() + 60]
            cut = stop.search(tail)
            label = re.search(rf"\b({labels})\b", tail[:cut.start()] if cut else tail)
            if label:
                shown.append(label.group(1))
        if VOTE_LABEL[vote] not in shown:
            problems.append(f"{name} is not shown as {VOTE_LABEL[vote]!r}")
    return problems


def _fetch(url: str) -> str:
    from urllib.request import urlopen
    with urlopen(url, timeout=60) as resp:  # noqa: S310 — our own site, http(s) only
        return resp.read().decode("utf-8", errors="replace")


def page_checks(sqlite_path: Path, expected: list[dict], base_url: str, targets: dict[str, str] | None = None) -> dict:
    """One Novato and one Board Decision page (the first new Decision of each body in expected order) must show
    each planned member with their vote label. `targets` (a refresh batch): {body: the Decision page to check}."""
    con = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)
    try:
        names = dict(con.execute("SELECT id, search_label FROM nodes WHERE type = 'Person'"))
    finally:
        con.close()
    out = {}
    picks = targets if targets is not None else {
        prefix: next((e["end_id"] for e in expected if e["end_id"].startswith(prefix)), None)
        for prefix in ("vev-novato-city-council-", "vev-marin-county-bos-")}
    for prefix, target in picks.items():
        if target is None:
            out[prefix] = {"problems": [f"no new {prefix} Decision in the expected set"]}
            continue
        url = f"{base_url.rstrip('/')}/decision/{target}"
        votes = [(names.get(e["start_id"], e["start_id"]), e["vote"]) for e in expected if e["end_id"] == target]
        try:
            problems = page_problems(_fetch(url), votes)
        except Exception as exc:
            problems = [f"fetching {url} failed: {exc!r}"]
        out[prefix] = {"url": url, "votes": len(votes), "problems": problems}
    return out


def _authenticate_oracle(state_dir: Path) -> bytes:
    """The expected-edge file's bytes, only if they are byte-for-byte the ones the applied approval recorded."""
    state = json.loads((Path(state_dir) / "state.json").read_text())
    raw = (Path(state_dir) / APPROVAL).read_bytes()
    if not state.get("approval_sha256") or _sha_bytes(raw) != state["approval_sha256"]:
        raise ApplyRefused("the approval manifest is not the one that was applied")
    entry = json.loads(raw)["files"].get("plan/expected-edges.jsonl")
    data = (Path(state_dir) / "plan" / "expected-edges.jsonl").read_bytes()
    if entry is None or _sha_bytes(data) != entry["sha256"]:
        raise ApplyRefused("plan/expected-edges.jsonl is not the approved oracle")
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    ap = sub.add_parser("apply")
    ap.add_argument("--state-dir", type=Path, required=True)
    ap.add_argument("--approve", required=True)
    ap.add_argument("--canonical-root", type=Path, required=True)
    mm = sub.add_parser("mark-mapping-review", help="state AWAITING_MAPPING_REVIEW (the batch is out)")
    mm.add_argument("--state-dir", type=Path, required=True)
    pp = sub.add_parser("prepare")
    for flag in ("--state-dir", "--bundle", "--plan", "--sheet", "--review", "--bake-check"):
        pp.add_argument(flag, type=Path, required=True)
    bc = sub.add_parser("bake-check", help="check a staging bake of the candidate (+ pages from a local server)")
    for flag in ("--sqlite", "--bundle", "--plan", "--out"):
        bc.add_argument(flag, type=Path, required=True)
    bc.add_argument("--base-url", required=True)
    bc.add_argument("--targets", type=Path, help="a refresh batch's plan/targets.json: batch-scoped checks")
    bc.add_argument("--baseline", type=Path, help="with --targets: the batch's baseline export")
    cp = sub.add_parser("check-published")
    cp.add_argument("--state-dir", type=Path, required=True)
    cp.add_argument("--sqlite", type=Path, required=True)
    cp.add_argument("--base-url", required=True)
    args = parser.parse_args(argv)
    if args.cmd == "mark-mapping-review":
        set_state(args.state_dir, "AWAITING_MAPPING_REVIEW")
        return 0
    if args.cmd == "prepare":
        try:
            sha = prepare(args.state_dir, bundle=args.bundle, plan=args.plan, sheet=args.sheet, review=args.review,
                          bake_check=args.bake_check)
        except ApplyRefused as exc:
            print(f"REFUSED: {exc}", file=sys.stderr)
            return 1
        print(f"AWAITING_APPLY — approval sha256 {sha}")
        return 0
    if args.cmd == "bake-check":
        ops = json.loads((args.plan / "ops.json").read_text())
        expected = expected_edges(ops)
        new = [json.loads(x) for x in (args.bundle / "nodes.jsonl").read_text().splitlines() if x.strip()]
        if args.targets:
            targets = json.loads(args.targets.read_text())["targets"]
            base_nodes = [json.loads(x) for x in (args.baseline / "nodes.jsonl").read_text().splitlines() if x.strip()]
            base_edges = [json.loads(x) for x in (args.baseline / "edges.jsonl").read_text().splitlines() if x.strip()]
            problems = refresh_bake_problems(args.sqlite, new, expected, targets, base_nodes, base_edges)
            pages = page_checks(args.sqlite, expected, args.base_url,
                                targets=refresh_page_targets(expected, new_ids={n["id"] for n in new}))
        else:
            problems = bake_problems(args.sqlite, new, expected, scope=SCOPE)
            pages = page_checks(args.sqlite, expected, args.base_url)
        result = {"problems": problems, "pages": pages,
                  **({"targets_sha256": _sha_bytes(args.targets.read_bytes()), "baseline_sha256": fingerprint(args.baseline)}
                     if args.targets else {}),
                  "candidate_sha256": json.loads((args.plan / "plan-report.json").read_text())["candidate_sha256"],
                  "bundle_sha256": fingerprint(args.bundle),
                  "sqlite_sha256": _sha_bytes(Path(args.sqlite).read_bytes())}
        result["problems"] += [f"{k}: {p}" for k, v in result["pages"].items() for p in v["problems"]]
        args.out.write_text(json.dumps(result, indent=1, sort_keys=True) + "\n")
        print(f"bake check: {len(result['problems'])} problem(s)")
        return 0 if not result["problems"] else 1
    if args.cmd == "check-published":
        if get_state(args.state_dir) not in ("APPLIED", "PUBLISHED_VERIFIED"):
            print(f"REFUSED: state is {get_state(args.state_dir)}, not APPLIED", file=sys.stderr)
            return 1
        try:
            oracle = _authenticate_oracle(args.state_dir)
        except ApplyRefused as exc:
            print(f"REFUSED: {exc}", file=sys.stderr)
            return 1
        expected = [json.loads(x) for x in oracle.decode("utf-8").splitlines() if x.strip()]  # the verified bytes
        if (args.state_dir / "refresh-batch.json").is_file():  # a refresh batch: its own targets + the baseline
            try:
                targets = json.loads(_approved_file(args.state_dir, "plan/targets.json"))["targets"]
                base_edges = [json.loads(x) for x in _approved_file(args.state_dir, "baseline/edges.jsonl")
                              .decode("utf-8").splitlines() if x.strip()]
            except ApplyRefused as exc:
                print(f"REFUSED: {exc}", file=sys.stderr)
                return 1
            problems = refresh_publication_problems(args.sqlite, expected, targets, base_edges)
            pages = page_checks(args.sqlite, expected, args.base_url,
                                targets=refresh_page_targets(expected, new_ids={t for t in targets
                                                                                if t.startswith("vev-")}))
        else:
            problems = check_published_edges(args.sqlite, expected, scope=SCOPE)
            pages = page_checks(args.sqlite, expected, args.base_url)
        problems += [f"{k}: {p}" for k, v in pages.items() for p in v["problems"]]
        for p in problems:
            print(f"PROBLEM: {p}", file=sys.stderr)
        if problems:
            return 1
        set_state(args.state_dir, "PUBLISHED_VERIFIED", approval_sha256=json.loads(
            (args.state_dir / "state.json").read_text())["approval_sha256"], sqlite_sha256=_sha_bytes(Path(args.sqlite).read_bytes()),
                  pages={k: v["url"] for k, v in pages.items()})
        print(f"PUBLISHED_VERIFIED — {len(expected)} edges, pages {[v['url'] for v in pages.values()]}")
        return 0
    try:
        from neo4j_target import open_driver
        uri = os.environ.get("NEO4J_URI")
        result = run_apply(args.state_dir, approve=args.approve, canonical_root=args.canonical_root, uri=uri,
                           database=os.environ.get("NEO4J_DATABASE", "neo4j"),
                           driver_factory=lambda: open_driver(uri, auth=(os.environ["NEO4J_USER"],
                                                                         os.environ["NEO4J_PASSWORD"])))
    except (ApplyRefused, RunLockHeld) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1
    print(result)
    return 0 if result == "APPLIED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
