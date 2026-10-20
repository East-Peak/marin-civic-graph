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
rows; each source institution's page previews exactly the first expected meetings (the page caps its list at 40);
one moved meeting per body links exactly that body and its page names it. Staging only.
"""
from __future__ import annotations

import argparse
import html
import json
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
    """`planned`: nodes_added [id], at_institution [(meeting, old, new)], in_jurisdiction_added [(org, place)]."""
    out: list[dict] = []
    a, b = _ro(after), _ro(before)
    try:
        tables = {t for (t,) in a.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        nodes = (_table(b, "SELECT * FROM nodes"), _table(a, "SELECT * FROM nodes"))
        edges = (_table(b, "SELECT source, rel, target, props FROM edges"),
                 _table(a, "SELECT source, rel, target, props FROM edges"))
        browse = (_table(b, "SELECT * FROM browse_rows"), _table(a, "SELECT * FROM browse_rows")) \
            if "browse_rows" in tables else (Counter(), Counter())
        others = {t: (_table(b, f"SELECT * FROM {t}"), _table(a, f"SELECT * FROM {t}"))
                  for t in ("money_rollups", "identity_links", "meta") if t in tables}
    finally:
        a.close()
        b.close()
    added = sorted(r[0] for r in (nodes[1] - nodes[0]).elements())
    removed = sorted(r[0] for r in (nodes[0] - nodes[1]).elements())
    want_add = Counter([(m, "AT_INSTITUTION", new) for m, _, new in planned["at_institution"]] +
                       [(o, "IN_JURISDICTION", p) for o, p in planned["in_jurisdiction_added"]])
    want_del = Counter((m, "AT_INSTITUTION", old) for m, old, _ in planned["at_institution"])
    got_add = Counter(r[:3] for r in (edges[1] - edges[0]).elements())
    got_del = Counter(r[:3] for r in (edges[0] - edges[1]).elements())
    browse_added = sorted(r[0] for r in (browse[1] - browse[0]).elements())
    ok = (added == sorted(planned["nodes_added"]) and not removed and got_add == want_add and got_del == want_del
          and browse_added == (sorted(planned["nodes_added"]) if "browse_rows" in tables else [])
          and not (browse[0] - browse[1])
          and all(x == y for x, y in others.values()))
    _check(out, "the bake differs from the baseline's only by the planned rows", ok, {
        "nodes_added": len(added), "nodes_removed_or_changed": removed[:5], "edges_added": sum(got_add.values()),
        "edges_removed": sum(got_del.values()), "unplanned_edges": [list(k) for k in (got_add - want_add)][:5],
        "missing_edges": [list(k) for k in (want_add - got_add)][:5], "browse_added": len(browse_added),
        "other_tables_changed": sorted(t for t, (x, y) in others.items() if x != y)})
    return out


def preview_checks(inst: str, payload: dict, expected: set[str]) -> list[dict]:
    """The page's neighbor list is capped; its meetings must be exactly the first expected ones in its order (id)."""
    out: list[dict] = []
    neighbors = payload.get("neighbors") or []
    meetings = [n["id"] for n in neighbors if n["type"] == "Meeting"]
    room = PREVIEW_CAP - sum(1 for n in neighbors if n["type"] != "Meeting")
    n = min(len(expected), room)
    _check(out, f"{inst}'s page previews the first {n} expected meetings", meetings == sorted(expected)[:n],
           {"shown": len(meetings), "first_shown": meetings[:3]})
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
    ops = json.loads((plan / "ops.json").read_text())
    rows = list(ba.read_jsonl(Path(map_dir) / "map.jsonl"))
    names = {c["id"]: c["properties"]["name"] for c in ops["create_nodes"]}
    candidate = bake / "candidate" / "public-substrate.sqlite"
    checks = sqlite_checks(candidate, rows, names)
    checks += diff_checks(bake / "baseline" / "public-substrate.sqlite", candidate, {
        "nodes_added": list(names), "at_institution": [(r["id"], r["from"], r["to"]) for r in ops["repoint"]],
        "in_jurisdiction_added": [(e["start_id"], e["end_id"]) for e in ops["create_edges"]]})
    con = _ro(candidate)
    labels = dict(con.execute("SELECT id, search_label FROM nodes"))
    con.close()
    for inst in sorted({r["from"] for r in rows}):
        payload = json.loads(_get(f"{base_url}/api/parity-entity/organization/{inst}"))
        checks += preview_checks(inst, payload, {r["id"] for r in rows if r["from"] == inst and r["to"] == inst})
    for body in sorted({r["to"] for r in ops["repoint"]}):
        mid = min(r["id"] for r in ops["repoint"] if r["to"] == body)
        payload = json.loads(_get(f"{base_url}/api/parity-entity/meeting/{mid}"))
        checks += meeting_checks(mid, payload, _get(f"{base_url}/meeting/{mid}"), body, labels[body])
    result = {"plan": str(plan.resolve()), "candidate_sha256": report["candidate_sha256"],
              "candidate_bake_sha256": ba._sha(candidate),
              "baseline_bake_sha256": ba._sha(bake / "baseline" / "public-substrate.sqlite"),
              "guard_sha256": ba._sha(ba.GUARD_PATH),
              "code_revision": subprocess.run(["git", "-C", str(SCRIPTS.parent), "rev-parse", "HEAD"],
                                              capture_output=True, text=True).stdout.strip(),
              "checks": checks, "all_pass": all(c["ok"] for c in checks)}
    (bake / "checks.json").write_text(json.dumps(result, indent=1, sort_keys=True) + "\n")
    return result


def run_bakes(plan: Path, attach: Path, out: Path) -> None:
    report = json.loads((Path(plan) / "plan-report.json").read_text())
    out = ba.staging_out(out, ba.STAGING_ROOT)
    for name, export in (("baseline", Path(report["baseline"]["dir"])), ("candidate", Path(plan) / "candidate")):
        (out / name).mkdir(parents=True)
        subprocess.run([sys.executable, str(SCRIPTS / "bake_public_substrate.py"), "--source", "live-export",
                        "--live-export-dir", str(export), "--attach-overlay-dir", str(attach),
                        "--sqlite", str(out / name / "public-substrate.sqlite"),
                        "--report", str(out / name / "report.json")], check=True)


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
