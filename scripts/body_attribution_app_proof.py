#!/usr/bin/env python3
"""Prove the public site follows the body attribution: bake the candidate as production does, then check the
serving data and the app's own entity payloads.

    body_attribution_app_proof.py bake  --plan <plan dir> --attach <staged copy of data/review/attach> --out <dir>
    body_attribution_app_proof.py prove --plan <plan dir> --map <map dir> --bake <dir> --base-url http://127.0.0.1:<port>

`bake` runs bake_public_substrate.py --source live-export on the baseline and on the candidate (into <out>/baseline,
<out>/candidate). `prove` needs the app served from the candidate bake (`SUBSTRATE_DB_PATH=<out>/candidate/
public-substrate.sqlite PARITY_DEBUG=1 next dev`) and checks: each source institution lists exactly its own and its
held meetings; each moved meeting has exactly one AT_INSTITUTION, to its body; each new body is baked under its
name; no meeting carries an institution_name; the candidate bake differs from the baseline bake only by the planned
rows (full rows, the search index, the sidecars); each source institution's page previews exactly the first expected
peers (the page caps its list at 40; the expectation is computed from the map and the baseline bake) and links
exactly those meetings; one moved meeting per body links exactly that body and its page names it; a decision of a
moved meeting shows its body, not the old institution. `prove` refuses bakes not made from this plan. Staging only.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import sqlite3
import subprocess
import sys
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

import body_attribution as ba  # noqa: E402

PREVIEW_CAP = 40  # app/src/lib/server/graph-engine.ts tier2Neighborhood
BAKE_FILES = ("public-substrate.sqlite", "status_manifest.json", "catalog.json", "report.json")
SERVING_TABLES = ("nodes", "edges", "browse_rows", "search_fts", "money_rollups", "identity_links", "meta")


def _check(out, name, ok, detail=None):
    out.append({"name": name, "ok": bool(ok), "detail": detail})


def _ro(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def sqlite_checks(sqlite: Path, rows: list[dict], names: dict[str, str]) -> list[dict]:
    """`rows`: the reviewed map; `names`: each new body's name."""
    out: list[dict] = []
    con = _ro(sqlite)
    try:
        types = dict(con.execute("SELECT id, type FROM nodes"))
        labels = dict(con.execute("SELECT id, search_label FROM nodes"))
        props = {i: json.loads(p or "{}") for i, p in con.execute("SELECT id, props FROM nodes")}
        at = defaultdict(list)
        for s, t in con.execute("SELECT source, target FROM edges WHERE rel = 'AT_INSTITUTION'"):
            at[s].append(t)
    finally:
        con.close()
    for inst in sorted({r["from"] for r in rows}):
        want = {r["id"] for r in rows if r["from"] == inst and r["to"] == inst}
        have = {s for s, ts in at.items() if inst in ts and types.get(s) == "Meeting"}
        _check(out, f"{inst} lists exactly its own and its held meetings", have == want,
               {"expected": len(want), "baked": len(have), "missing": sorted(want - have)[:5],
                "unexpected": sorted(have - want)[:5]})
    moved = [r for r in rows if r["rule"] == "move"]
    wrong = [r["id"] for r in moved if at.get(r["id"]) != [r["to"]]]
    _check(out, "every moved meeting has exactly one AT_INSTITUTION, to its body", not wrong,
           {"moved": len(moved), "wrong": wrong[:5]})
    for body in sorted({r["to"] for r in moved}):
        if body in names:
            _check(out, f"{body} is baked under its name {names[body]!r}",
                   types.get(body) == "Organization" and labels.get(body) == names[body], labels.get(body))
        else:
            _check(out, f"{body} (reused) is baked", types.get(body) == "Organization", labels.get(body))
    named = sorted(r["id"] for r in rows if "institution_name" in props.get(r["id"], {}))
    _check(out, "no moved or held meeting carries an institution_name", not named, named[:5])
    return out


def _table(con, sql) -> Counter:
    return Counter(con.execute(sql))


def diff_checks(before: Path, after: Path, planned: dict) -> list[dict]:
    """The candidate bake against the baseline bake: every table row, the search index and both sidecars differ by
    exactly the planned rows. `planned`: nodes_added {id: name}, at_institution [(meeting, old, new)],
    in_jurisdiction_added [(org, place)], template (an existing government stub's id: the shape new rows take)."""
    out: list[dict] = []
    a, b = _ro(after), _ro(before)
    try:
        tables = {t for (t,) in a.execute("SELECT name FROM sqlite_master WHERE type = 'table'")} & \
            {t for (t,) in b.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        missing_tables = sorted(set(SERVING_TABLES) - tables)
        rows = {t: (_table(b, f"SELECT * FROM {t}"), _table(a, f"SELECT * FROM {t}"))
                for t in ("nodes", "edges", "browse_rows", "money_rollups", "identity_links", "meta") if t in tables}
        search = tuple(_search_index(con) if "search_fts" in tables else {} for con in (b, a))
        tpl = planned["template"]
        tpl_node = b.execute("SELECT type, props FROM nodes WHERE id = ?", (tpl,)).fetchone()
        tpl_browse = b.execute("SELECT * FROM browse_rows WHERE id = ?", (tpl,)).fetchone() \
            if "browse_rows" in tables else None
        at_props = {p for (p,) in b.execute("SELECT props FROM edges WHERE rel = 'AT_INSTITUTION' AND target = ?",
                                              (planned["at_institution"][0][1],))} if planned["at_institution"] else set()
        juris_props = {p for (p,) in b.execute("SELECT props FROM edges WHERE rel = 'IN_JURISDICTION' AND source = ?",
                                                 (tpl,))}
        fts = {}
        for oid, name in planned["nodes_added"].items():
            rowid = a.execute("SELECT rowid FROM nodes WHERE id = ?", (oid,)).fetchone()
            hits = {r for (r,) in a.execute("SELECT rowid FROM search_fts WHERE search_fts MATCH ?",
                                             ('search_label : "' + name.replace('"', " ") + '"',))}
            fts[oid] = bool(rowid) and rowid[0] in hits
    finally:
        a.close()
        b.close()
    tpl_props = {k: v for k, v in json.loads(tpl_node[1]).items() if k != "name"}
    want_nodes = Counter((oid, tpl_node[0], name, json.dumps({"name": name, **tpl_props}, sort_keys=True))
                         for oid, name in planned["nodes_added"].items())
    got_nodes = Counter((i, t, label, json.dumps(json.loads(p), sort_keys=True))
                        for i, t, label, p in (rows["nodes"][1] - rows["nodes"][0]).elements())
    want_browse = Counter((oid, tpl_browse[1], name, name.lower(), *tpl_browse[4:])
                          for oid, name in planned["nodes_added"].items()) if tpl_browse else Counter()
    got_browse = rows["browse_rows"][1] - rows["browse_rows"][0] if "browse_rows" in rows else Counter()
    (at_prop,), (j_prop,) = (at_props or {None}), (juris_props or {None})
    want_add = Counter([(m, "AT_INSTITUTION", new, at_prop) for m, _, new in planned["at_institution"]] +
                       [(o, "IN_JURISDICTION", pl, j_prop) for o, pl in planned["in_jurisdiction_added"]])
    want_del = Counter((m, "AT_INSTITUTION", old, at_prop) for m, old, _ in planned["at_institution"])
    got_add, got_del = rows["edges"][1] - rows["edges"][0], rows["edges"][0] - rows["edges"][1]
    unchanged = sorted(t for t in ("money_rollups", "identity_links", "meta") if t in rows and rows[t][0] != rows[t][1])
    ok = (got_nodes == want_nodes and not (rows["nodes"][0] - rows["nodes"][1]) and got_add == want_add
          and got_del == want_del and got_browse == want_browse
          and not (rows.get("browse_rows", (Counter(), Counter()))[0] - rows.get("browse_rows", (Counter(), Counter()))[1])
          and not unchanged and len(at_props) <= 1 and len(juris_props) <= 1)
    _check(out, "the bake differs from the baseline's only by the planned rows (full rows)", ok, {
        "nodes_added": sum(got_nodes.values()), "unexpected_nodes": [list(k) for k in (got_nodes - want_nodes)][:3],
        "edges_added": sum(got_add.values()), "edges_removed": sum(got_del.values()),
        "unplanned_edges": [list(k) for k in (got_add - want_add)][:3], "missing_edges": [list(k) for k in (want_add - got_add)][:3],
        "browse_added": sum(got_browse.values()), "other_tables_changed": unchanged})
    _check(out, "the bake has the production serving tables", not missing_tables, missing_tables)
    _check(out, "every new institution is in the search index under its name", all(fts.values()),
           sorted(k for k, v in fts.items() if not v))
    changed = sorted(i for i in set(search[0]) | set(search[1]) if search[0].get(i) != search[1].get(i))
    _check(out, "the search index differs only by the new institutions",
           "search_fts" in tables and changed == sorted(planned["nodes_added"]), changed[:5])
    side = {}
    for name in ("status_manifest.json", "catalog.json"):
        x, y = (_json_file(Path(d).parent / name) for d in (before, after))
        side[name] = None if x is None or y is None else _flat_diff(x, y)
    n, e = len(planned["nodes_added"]), len(planned["in_jurisdiction_added"])
    want_side = {"status_manifest.json": {"per_type_counts.Organization": n, "node_count": n, "edge_count": e},
                 "catalog.json": {"counts.Organization": n, "per_type_counts.Organization": n, "node_count": n,
                                  "edge_count": e}}
    _check(out, "the bake's sidecars change only by the planned counts",
           all(side[k] == want for k, want in want_side.items()), side)
    return out


def _search_index(con: sqlite3.Connection) -> dict[str, tuple]:
    """What the (contentless, production) search index holds for each node: its indexed tokens with column and
    position, read through fts5vocab (the text columns of a contentless table read back as NULL)."""
    con.execute("CREATE VIRTUAL TABLE IF NOT EXISTS temp.search_vocab USING fts5vocab(main, search_fts, instance)")
    ids = dict(con.execute("SELECT rowid, id FROM nodes"))
    docs: dict[str, list] = defaultdict(list)
    for doc, term, col, offset in con.execute("SELECT doc, term, col, offset FROM temp.search_vocab"):
        docs[ids.get(doc, f"rowid:{doc}")].append((term, col, offset))
    return {i: tuple(sorted(v)) for i, v in docs.items()}


def _json_file(path: Path):
    return json.loads(path.read_text()) if path.is_file() else None


def _flat_diff(x: dict, y: dict) -> dict:
    """{dotted key: y - x} for every numeric value that differs (any other difference: the pair)."""
    def flat(d, p=""):
        o = {}
        for k, v in d.items():
            o.update(flat(v, f"{p}{k}.") if isinstance(v, dict) else {f"{p}{k}": v})
        return o
    fx, fy = flat(x), flat(y)
    diff = {}
    for k in sorted(set(fx) | set(fy)):
        if fx.get(k) != fy.get(k):
            both = isinstance(fx.get(k), int) and isinstance(fy.get(k), int)
            diff[k] = fy[k] - fx[k] if both else [fx.get(k), fy.get(k)]
    return diff


def expected_neighborhood(baseline: Path, inst: str, meetings: set[str]) -> list[tuple[str, str]]:
    """The institution page's eligible peers after the migration, as (type, id) in the page's order: its expected
    meetings (from the reviewed map) and every other eligible peer from the BASELINE bake (the migration changes no
    non-Meeting edge; diff_checks proves it). Eligible: a PHASE2 relationship, a peer that is not a Place or Issue
    (graph-engine.ts isAllowedTier2Edge; the whitelist's canonical source is edge_vocabulary.py)."""
    from edge_vocabulary import PHASE2_WHITELIST_LIVE

    rels = set(PHASE2_WHITELIST_LIVE)
    con = _ro(baseline)
    try:
        types = dict(con.execute("SELECT id, type FROM nodes"))
        peers = {t if s == inst else s for s, rel, t in con.execute(
            "SELECT source, rel, target FROM edges WHERE source = ? OR target = ?", (inst, inst)) if rel in rels}
    finally:
        con.close()
    others = {(types[p], p) for p in peers if p != inst and p in types and types[p] not in ("Place", "Issue", "Meeting")}
    return sorted(others | {("Meeting", m) for m in meetings})


def preview_checks(inst: str, payload: dict, expected: list[tuple[str, str]], page: str) -> list[dict]:
    """The page's neighbor list (capped) must be exactly the first expected peers, and the rendered page must link
    exactly its meetings."""
    out: list[dict] = []
    shown = [(n["type"], n["id"]) for n in payload.get("neighbors") or []]
    want = sorted(expected)[:PREVIEW_CAP]
    _check(out, f"{inst}'s page previews exactly the first {len(want)} expected peers", shown == want,
           {"shown": len(shown), "first_shown": shown[:3], "first_expected": want[:3]})
    linked = set(re.findall(r'href="/meeting/([^"]+)"', page))
    want_links = {i.removeprefix("meeting-") for t, i in want if t == "Meeting"}
    _check(out, f"{inst}'s rendered page links exactly the previewed meetings", linked == want_links,
           {"linked": len(linked), "expected": len(want_links), "unexpected": sorted(linked - want_links)[:5]})
    return out


def decision_checks(did: str, payload: dict, body: str, old: str) -> list[dict]:
    out: list[dict] = []
    orgs = [n["id"] for n in payload.get("neighbors") or [] if n["type"] == "Organization"]
    _check(out, f"{did} (a decision of a moved meeting) shows {body}, not {old}", body in orgs and old not in orgs, orgs)
    return out


def meeting_checks(mid: str, payload: dict, page: str, body: str, label: str) -> list[dict]:
    out: list[dict] = []
    orgs = [n for n in payload.get("neighbors") or [] if n["type"] == "Organization"]
    _check(out, f"{mid}'s page links exactly its body {body}", [o["id"] for o in orgs] == [body]
           and orgs[0].get("label") == label, [(o["id"], o.get("label")) for o in orgs])
    _check(out, f"{mid}'s rendered page names {label!r}", html.escape(label) in page or label in page)
    return out


def _get(url: str) -> str:
    with urllib.request.urlopen(url, timeout=120) as r:  # the operator's own local dev server only
        return r.read().decode("utf-8")


def prove(plan: Path, map_dir: Path, bake: Path, base_url: str) -> dict:
    if not base_url.startswith(("http://127.0.0.1:", "http://localhost:")):
        raise ba.AttributionError("the app proof reads only a local dev server")
    plan, bake = Path(plan), Path(bake)
    report = json.loads((plan / "plan-report.json").read_text())
    inputs = json.loads((bake / "bake-inputs.json").read_text())
    if inputs["candidate"] != ba.fingerprint(plan / "candidate") or inputs["candidate"] != report["candidate_sha256"] \
            or inputs["baseline"] != report["baseline"]["sha256"]:
        raise ba.AttributionError("the bakes were not made from this plan's baseline and candidate")
    attach = Path(inputs["attach_dir"])
    if {n: ba._sha(attach / n) for n in inputs["attach"]} != inputs["attach"]:
        raise ba.AttributionError("the attach overlay changed since the bakes")
    if _outputs(bake) != inputs.get("outputs"):
        raise ba.AttributionError("the baked files are not the ones the bakes wrote")
    impl = ba.implementation()
    if not impl["clean"] or inputs.get("implementation") != impl:
        raise ba.AttributionError("the bakes were made by other code than this clean checkout's")
    ops = json.loads((plan / "ops.json").read_text())
    rows = list(ba.read_jsonl(Path(map_dir) / "map.jsonl"))
    if ba._sha(Path(map_dir) / "map.jsonl") != report["map"]["sha256"]:
        raise ba.AttributionError("the map is not the plan's")
    names = {c["id"]: c["properties"]["name"] for c in ops["create_nodes"]}
    candidate, baseline = bake / "candidate" / "public-substrate.sqlite", bake / "baseline" / "public-substrate.sqlite"
    checks = sqlite_checks(candidate, rows, names)
    checks += diff_checks(baseline, candidate, {
        "nodes_added": names, "at_institution": [(r["id"], r["from"], r["to"]) for r in ops["repoint"]],
        "in_jurisdiction_added": [(e["start_id"], e["end_id"]) for e in ops["create_edges"]],
        "template": sorted({r["from"] for r in rows})[0]})
    con = _ro(candidate)
    labels = dict(con.execute("SELECT id, search_label FROM nodes"))
    decided = defaultdict(list)
    for d, m in con.execute("SELECT source, target FROM edges WHERE rel = 'DECIDED_AT'"):
        decided[m].append(d)
    con.close()
    for inst in sorted({r["from"] for r in rows}):
        payload = json.loads(_get(f"{base_url}/api/parity-entity/organization/{inst}"))
        own = {r["id"] for r in rows if r["from"] == inst and r["to"] == inst}
        checks += preview_checks(inst, payload, expected_neighborhood(baseline, inst, own),
                                 _get(f"{base_url}/organization/{inst}"))
    for body in sorted({r["to"] for r in ops["repoint"]}):
        moved = sorted(r["id"] for r in ops["repoint"] if r["to"] == body)
        mid = moved[0]
        payload = json.loads(_get(f"{base_url}/api/parity-entity/meeting/{mid}"))
        checks += meeting_checks(mid, payload, _get(f"{base_url}/meeting/{mid}"), body, labels[body])
        with_decision = [m for m in moved if decided.get(m)]
        if with_decision:
            did = sorted(decided[with_decision[0]])[0]
            old = next(r["from"] for r in ops["repoint"] if r["id"] == with_decision[0])
            checks += decision_checks(did, json.loads(_get(f"{base_url}/api/parity-entity/decision/{did}")), body, old)
    result = {"plan": str(plan.resolve()), "candidate_sha256": report["candidate_sha256"],
              "baseline_sha256": report["baseline"]["sha256"], "map_sha256": report["map"]["sha256"],
              "bake_inputs": inputs, "candidate_bake_sha256": ba._sha(candidate),
              "baseline_bake_sha256": ba._sha(baseline), "guard_sha256": ba._sha(ba.GUARD_PATH),
              "implementation": ba.implementation(), "checks": checks, "all_pass": all(c["ok"] for c in checks)}
    (bake / "checks.json").write_text(json.dumps(result, indent=1, sort_keys=True) + "\n")
    return result


def run_bakes(plan: Path, attach: Path, out: Path) -> None:
    """Both bakes, from a read-only staged copy of the attach overlay; bake-inputs.json records what they were made
    from, for `prove` to verify."""
    report = json.loads((Path(plan) / "plan-report.json").read_text())
    out = ba.staging_out(out, ba.STAGING_ROOT)
    attach = Path(attach).resolve()
    impl = ba.implementation()
    if not impl["clean"]:
        raise ba.AttributionError("the tree has uncommitted changes or untracked files; commit before baking")
    files = sorted(p.name for p in attach.iterdir() if p.is_file())
    if not files or any(os.stat(attach / n).st_mode & 0o222 for n in files):
        raise ba.AttributionError(f"{attach}: the attach overlay copy must exist and be read-only")
    exports = {"baseline": Path(report["baseline"]["dir"]), "candidate": Path(plan) / "candidate"}
    before = {**{name: ba.fingerprint(export) for name, export in exports.items()},
              "attach": {n: ba._sha(attach / n) for n in files}}
    for name, export in exports.items():
        (out / name).mkdir(parents=True)
        subprocess.run([sys.executable, str(SCRIPTS / "bake_public_substrate.py"), "--source", "live-export",
                        "--live-export-dir", str(export), "--attach-overlay-dir", str(attach),
                        "--sqlite", str(out / name / "public-substrate.sqlite"),
                        "--report", str(out / name / "report.json")], check=True)
    after = {**{name: ba.fingerprint(export) for name, export in exports.items()},
             "attach": {n: ba._sha(attach / n) for n in files}}
    if after != before or ba.implementation() != impl:
        raise ba.AttributionError("a bake input or the code changed while baking")
    (out / "bake-inputs.json").write_text(json.dumps({
        **before, "attach_dir": str(attach), "outputs": _outputs(out), "implementation": impl},
        indent=1, sort_keys=True) + "\n")


def _outputs(out: Path) -> dict:
    return {name: {f: ba._sha(Path(out) / name / f) for f in BAKE_FILES} for name in ("baseline", "candidate")}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("bake")
    b.add_argument("--plan", type=Path, required=True)
    b.add_argument("--attach", type=Path, required=True)
    b.add_argument("--out", type=Path, required=True)
    p = sub.add_parser("prove")
    p.add_argument("--plan", type=Path, required=True)
    p.add_argument("--map", type=Path, required=True)
    p.add_argument("--bake", type=Path, required=True)
    p.add_argument("--base-url", required=True)
    args = parser.parse_args(argv)
    if args.cmd == "bake":
        run_bakes(args.plan, args.attach, args.out)
        return 0
    result = prove(args.plan, args.map, args.bake, args.base_url)
    for c in result["checks"]:
        print(f"{'PASS' if c['ok'] else 'FAIL'} {c['name']}" + ("" if c["ok"] else f" — {c['detail']}"))
    print("ALL PASS" if result["all_pass"] else "FAILED")
    return 0 if result["all_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
