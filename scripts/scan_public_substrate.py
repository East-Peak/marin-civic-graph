#!/usr/bin/env python3
"""Artifact-wide privacy scan of a baked public SQLite for campaign-contributor details (operator tool).

Three independent gates, each of which must hold:
  A. prohibited values: zero contributor values the policy keeps private. Needles come from the bundle's ledger
     and the graph export, never from the artifact: every contact-, street- or ZIP+4-shaped part of any reported
     source cell, and each employer/occupation value withheld for such a shape (global: they may appear nowhere);
     every other withheld value, conflicting reports included (per flow: ordinary words elsewhere, so they may
     not appear on their own flow); and the street, PO box and ZIP+4 parts of OCR flows' address_raw (global).
     A hit on a non-MoneyFlow node that the baseline bake has identically is pre-existing public text (Project
     exposure is authoritative): listed separately, never counted as a contributor leak.
  B. new findings: detector findings (phone, email, url, street, zip4) whose count the baseline bake of the
     unmigrated graph does not already have for the same surface, row and span, plus any changed FTS token
     stream, unless --explain names the exact finding with a reason. Baseline findings are reported separately.
  C. reconciliation: every eligible flow's reported_* props equal what the ledger yields under the exposure
     level, no other node carries any, and per source and field published + source_missing + withheld = eligible.

Surfaces: every table's text cells, JSON cells walked to every key and leaf, and the contentless FTS index
rebuilt per row and column from fts5vocab (FTS drops punctuation: there needles match as token phrases, the
phone/street/zip4 detectors run on the token stream, and any change to a stream is a finding). A fixed matrix of
synthetic leaks, independent of the real data, is planted in a scratch copy on every run; each must be reported
exactly where it was planted (and a negative control must not be), or the scan fails.

Usage:
  python scripts/scan_public_substrate.py --sqlite cand.sqlite --baseline base.sqlite --bundle <CF2 bundle> \
      --export <candidate export dir> --out report.json [--explain explain.json]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from contributor_detail import (  # noqa: E402
    CONTACT_DETECTORS, FIELDS, LEDGER_KEYS, PROPS, display, flow_props, load_reviewed, transaction_details,
)
from public_exposure import ADDRESS_EXPOSURE, CONTRIBUTOR_LEVELS  # noqa: E402

_ZIP4 = re.compile(r"(?<![0-9])[0-9]{5}-[0-9]{4}(?![0-9])")
_STATE_ZIP_TAIL = re.compile(r"[A-Z]{2}\.?\s+[0-9]{5}(?:-[0-9]{4})?", re.I)
# House number + the first word: the start of any street, however the rest of the address runs on.
_HOUSE_NUMBER_STREET = re.compile(r"(?<!\w)[0-9]+[A-Z]?\s+[^\W\d_][\w'.-]*", re.I)
DETECTORS = (*CONTACT_DETECTORS, ("zip4", _ZIP4))
FTS_DETECTORS = (*((n, p) for n, p in CONTACT_DETECTORS if n in ("phone", "street")),
                 ("zip4", re.compile(r"(?<!\w)[0-9]{5} [0-9]{4}(?!\w)")))  # "94999-0001" tokenizes to "94999 0001"
CONTACT_RULES = ("phone", "email", "url", "street")
OCR_FLOW_TYPES = ("campaign_contribution", "campaign_expenditure")
MIN_GLOBAL_NEEDLE = 6
ROW_KEYS = {"nodes": ("id",), "browse_rows": ("id",), "meta": ("key",), "edges": ("source", "rel", "target"),
            "identity_links": ("source", "target", "assertion_id"), "money_rollups": ("org_id",)}


def _norm(text: str) -> str:
    return " ".join(str(text).split()).casefold()


def _leaves(value, path: str):
    """Every key and every scalar leaf of a JSON value, as (path, text)."""
    if isinstance(value, dict):
        for key, item in value.items():
            yield f"{path}.{{key}}", str(key)
            yield from _leaves(item, f"{path}.{key}")
    elif isinstance(value, list):
        for i, item in enumerate(value):
            yield from _leaves(item, f"{path}[{i}]")
    elif value is not None and not isinstance(value, bool):
        yield path, str(value)


def fts_streams(conn: sqlite3.Connection) -> dict[tuple[int, str], str]:
    """The contentless FTS index, rebuilt as one token stream per row and column."""
    conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS temp.fts_vocab USING fts5vocab(main, search_fts, 'instance')")
    tokens = defaultdict(list)
    for term, doc, col, offset in conn.execute("SELECT term, doc, col, offset FROM temp.fts_vocab"):
        tokens[(doc, col)].append((offset, term))
    return {key: " ".join(t for _, t in sorted(terms)) for key, terms in sorted(tokens.items())}


def text_surfaces(conn: sqlite3.Connection):
    """(table, path, row identity, node id or None, text) for every text in every table and the FTS index."""
    rowid_to_id = dict(conn.execute("SELECT rowid, id FROM nodes"))
    tables = [t for (t,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")
              if not t.startswith(("search_fts", "sqlite_"))]
    for table in tables:
        cursor = conn.execute(f'SELECT rowid, * FROM "{table}"')
        columns = [c[0] for c in cursor.description][1:]
        for rowid, *row in cursor:
            values = dict(zip(columns, row))
            keys = ROW_KEYS.get(table)
            identity = "|".join(str(values[k]) for k in keys) if keys else f"rowid:{rowid}"
            node_id = values.get("id") if table in ("nodes", "browse_rows") else None
            for column, cell in values.items():
                if not isinstance(cell, str):
                    continue
                parsed = None
                if cell[:1] in "{[":
                    try:
                        parsed = json.loads(cell)
                    except ValueError:
                        pass
                if parsed is None:
                    yield table, column, identity, node_id, cell
                else:
                    for path, text in _leaves(parsed, column):
                        yield table, path, identity, node_id, text
    for (doc, col), text in fts_streams(conn).items():
        node_id = rowid_to_id.get(doc)
        yield "search_fts", col, node_id or f"rowid:{doc}", node_id, text


def _span(text: str, match: re.Match) -> str:
    """The match widened to the whitespace-delimited run around it, so "https://" names its whole URL."""
    start, end = match.start(), match.end()
    while start > 0 and not text[start - 1].isspace():
        start -= 1
    while end < len(text) and not text[end].isspace():
        end += 1
    return _norm(text[start:end])


def detector_findings(conn: sqlite3.Connection) -> Counter:
    findings: Counter = Counter()
    for table, path, identity, _, text in text_surfaces(conn):
        for name, pattern in (FTS_DETECTORS if table == "search_fts" else DETECTORS):
            for match in pattern.finditer(text):
                findings[(table, path, identity, name, _span(text, match))] += 1
    return findings


# ---------------------------------------------------------------------------
# What the ledger and the export say must never show
# ---------------------------------------------------------------------------

_PO_BOX = re.compile(r"\bP\.?\s*O\.?\s*BOX\s*#?\s*[0-9]+|\bPOST\s+OFFICE\s+BOX\s*#?\s*[0-9]+", re.I)


def shaped_parts(text: str) -> set[str]:
    """Every contact, street, PO box or ZIP+4 part of a text, as a needle.

    A bare "ST 99999" tail is no part (city + ZIP are public), and a street-, phone- or ZIP-shaped part without a
    digit (a lone "PO BOX") names nothing; a PO box needle keeps its number."""
    parts = {_norm(m.group(0)) for m in _PO_BOX.finditer(text)}
    for name, pattern in DETECTORS:
        for match in pattern.finditer(text):
            part = match.group(0).strip()
            if _STATE_ZIP_TAIL.fullmatch(part) or (name not in ("email", "url") and not re.search(r"[0-9]", part)):
                continue
            parts.add(_norm(part))
    return {p for p in parts if len(p) >= MIN_GLOBAL_NEEDLE}


def ledger_expectations(bundle: Path, reviewed: frozenset, level: str) -> dict:
    """Expected public props per eligible flow, and the needles: global and per flow."""
    expected, per_flow, global_needles, coverage = {}, defaultdict(set), {}, {}
    shown = {PROPS[f] for f in CONTRIBUTOR_LEVELS[level]}
    for source in sorted(p for p in bundle.iterdir() if (p / "ledger.jsonl").is_file()):
        members = defaultdict(list)
        with open(source / "ledger.jsonl") as f:
            for line in f:
                row = json.loads(line)
                for key, cell in (row.get("reported") or {}).items():  # every source cell, whatever its outcome
                    if isinstance(cell, str):
                        for part in shaped_parts(cell):
                            global_needles.setdefault(part, "raw_zip4" if _ZIP4.fullmatch(part) else f"shaped_{key}")
                if row.get("counted") and row.get("schedule") == "A":
                    members[row["moneyflow_id"]].append(row)
        fields = {f: Counter() for f in FIELDS}
        eligible = 0
        for flow_id, rows in members.items():
            reason, details = transaction_details("A", rows, reviewed)
            if reason:
                continue
            eligible += 1
            expected[flow_id] = {k: v for k, v in flow_props(details).items() if k in shown}
            for field, outcome in details.items():
                if outcome.value is not None:
                    fields[field]["published" if PROPS[field] in shown else "withheld:exposure_level"] += 1
                    continue
                fields[field]["source_missing" if outcome.rule == "source_missing" else f"withheld:{outcome.rule}"] += 1
                for row in rows if outcome.rule != "source_missing" else ():
                    cell = row["reported"].get(LEDGER_KEYS[field])
                    for text in {display(cell), cell.strip() if isinstance(cell, str) else None} - {None, ""}:
                        per_flow[flow_id].add(_norm(text))
                        if field in ("employer", "occupation") and outcome.rule in CONTACT_RULES:
                            global_needles[_norm(text)] = f"withheld_{outcome.rule}"
        coverage[source.name] = {"eligible": eligible, "fields": {f: dict(sorted(c.items())) for f, c in fields.items()}}
    return {"expected": expected, "per_flow": per_flow, "global": global_needles, "coverage": coverage}


def ocr_needles(export_dir: Path) -> dict[str, str]:
    """The street, PO box, unit and ZIP+4 parts of OCR flows' address_raw, wherever in the value they sit."""
    needles = {}
    with open(export_dir / "nodes.jsonl") as f:
        for line in f:
            node = json.loads(line)
            props = node.get("properties", {})
            if "MoneyFlow" in node.get("labels", []) and props.get("flow_type") in OCR_FLOW_TYPES:
                address = display(props.get("address_raw")) or ""
                for part in shaped_parts(address):
                    needles[part] = "raw_zip4" if _ZIP4.fullmatch(part) else "ocr_address_raw"
                for segment in address.split(","):
                    match = _HOUSE_NUMBER_STREET.search(segment)
                    if match and len(match.group(0)) >= MIN_GLOBAL_NEEDLE:
                        needles[_norm(match.group(0))] = "ocr_address_raw"
    return needles


def _fts_phrase(needle: str) -> str | None:
    tokens = re.findall(r"\w+", needle)
    return '"' + " ".join(tokens) + '"' if tokens else None


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def prohibited_hits(conn: sqlite3.Connection, global_needles: dict, per_flow: dict) -> list[dict]:
    """Each hit records the hash of the whole text it sits in: a baseline exemption holds only for unchanged text."""
    hits = []
    ordered = sorted(global_needles, key=len, reverse=True)
    pattern = re.compile("|".join(re.escape(n) for n in ordered)) if ordered else None
    rowid_to_id = dict(conn.execute("SELECT rowid, id FROM nodes"))
    types = dict(conn.execute("SELECT id, type FROM nodes"))
    for table, path, identity, node_id, text in text_surfaces(conn):
        if table == "search_fts":
            continue  # phrase queries below
        norm = _norm(text)
        where = {"surface": table, "path": path, "row": identity, "node_type": types.get(node_id), "text": _sha(text)}
        for match in pattern.finditer(norm) if pattern else ():
            hits.append({**where, "kind": global_needles[match.group(0)], "needle": match.group(0)})
        for needle in per_flow.get(node_id, ()):
            if re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", norm):
                hits.append({**where, "kind": "withheld_on_its_flow", "needle": needle})
    streams = defaultdict(list)
    for (doc, col), text in fts_streams(conn).items():
        streams[doc].append(f"{col}:{text}")
    phrases = {*global_needles.items(), *((n, "withheld_on_its_flow") for ns in per_flow.values() for n in ns)}
    for needle, kind in sorted(phrases):
        phrase = _fts_phrase(needle)
        if not phrase:
            continue
        for (rowid,) in conn.execute("SELECT rowid FROM search_fts WHERE search_fts MATCH ?", (phrase,)):
            node_id = rowid_to_id.get(rowid)
            if kind != "withheld_on_its_flow" or needle in per_flow.get(node_id, ()):
                hits.append({"surface": "search_fts", "path": "*", "row": node_id or f"rowid:{rowid}",
                             "node_type": types.get(node_id), "text": _sha("\n".join(streams[rowid])),
                             "kind": kind, "needle": needle})
    return hits


def reconciliation_problems(conn: sqlite3.Connection, expected: dict) -> list[str]:
    problems, present = [], set()
    keys = set(PROPS.values())
    for node_id, props_json in conn.execute("SELECT id, props FROM nodes"):
        present.add(node_id)
        have = {k: v for k, v in json.loads(props_json).items() if k in keys}
        want = expected.get(node_id, {})
        if have != want:
            problems.append(f"{node_id}: artifact {have} vs ledger {want}")
    problems += [f"{i}: eligible flow missing from the artifact" for i in sorted(set(expected) - present)]
    return problems


# ---------------------------------------------------------------------------
# The scan
# ---------------------------------------------------------------------------

FINDING_FIELDS = ("surface", "path", "row", "detector", "span")
HIT_FIELDS = ("surface", "path", "row", "text", "kind", "needle")


def _explained(explain: list[dict]) -> dict[tuple, str]:
    table = {}
    for entry in explain:
        missing = [k for k in (*FINDING_FIELDS, "reason") if not str(entry.get(k) or "").strip()]
        if missing:
            raise ValueError(f"an explanation needs {missing}: {entry!r}")
        table[tuple(entry[k] for k in FINDING_FIELDS)] = entry["reason"]
    return table


def scan(sqlite_path: Path, baseline_path: Path, bundle: Path, export_dir: Path, explain: list[dict],
         level: str = ADDRESS_EXPOSURE["campaign_contributor"], extra_needles: dict | None = None,
         extra_per_flow: dict | None = None) -> dict:
    expectations = ledger_expectations(bundle, load_reviewed(), level)
    needles = {**expectations["global"], **ocr_needles(export_dir), **(extra_needles or {})}
    per_flow = defaultdict(set, expectations["per_flow"])
    for flow, values in (extra_per_flow or {}).items():
        per_flow[flow] |= set(values)
    explained = _explained(explain)
    with sqlite3.connect(baseline_path) as conn:
        baseline = detector_findings(conn)
        baseline_streams = fts_streams(conn)
        baseline_hits = {tuple(h[k] for k in HIT_FIELDS) for h in prohibited_hits(conn, needles, {})}
    with sqlite3.connect(sqlite_path) as conn:
        candidate = detector_findings(conn)
        streams = fts_streams(conn)
        hits = prohibited_hits(conn, needles, per_flow)
        recon = reconciliation_problems(conn, expectations["expected"])
    new = [dict(zip(FINDING_FIELDS, key), count=n - baseline.get(key, 0))
           for key, n in sorted(candidate.items(), key=str) if n > baseline.get(key, 0)]
    new += [{"surface": "search_fts", "path": col, "row": f"rowid:{doc}", "detector": "fts_stream_changed",
             "span": _sha(text), "count": 1}
            for (doc, col), text in sorted(streams.items()) if baseline_streams.get((doc, col)) != text]
    for finding in new:
        finding["reason"] = explained.get(tuple(finding[k] for k in FINDING_FIELDS))
    preexisting = [h for h in hits if h["node_type"] != "MoneyFlow" and h["kind"] != "withheld_on_its_flow"
                   and tuple(h[k] for k in HIT_FIELDS) in baseline_hits]
    leaks = [h for h in hits if h not in preexisting]
    return {
        "level": level,
        "needles": dict(sorted(Counter(needles.values()).items())),
        "per_flow_needle_flows": len(per_flow),
        "gate_a_prohibited_hits": leaks,
        "gate_a_preexisting_public_text": preexisting,
        "gate_b_new_findings": new,
        "gate_b_unexplained": sum(1 for f in new if f["reason"] is None),
        "gate_c_reconciliation_problems": recon,
        "coverage": expectations["coverage"],
        "baseline_findings": dict(sorted(Counter(f"{k[0]}:{k[3]}" for k in baseline.elements()).items())),
        "candidate_findings": dict(sorted(Counter(f"{k[0]}:{k[3]}" for k in candidate.elements()).items())),
        "passed": not leaks and not any(f["reason"] is None for f in new) and not recon,
    }


# ---------------------------------------------------------------------------
# Controls: a fixed matrix of synthetic leaks (fictional values), independent of the real data
# ---------------------------------------------------------------------------

CONTROL_NEEDLE = "8 controlwood ln"
CONTROL_FLOW = "moneyflow-9999999-control"
REQUIRED_CONTROLS = 17
CONTROL_FLOW_VALUE = "controlco widgets"
CONTROL_DETECTORS = {"phone": "415-555-0142", "email": "control@example.org", "url": "https://control.example.org/x",
                     "street": "9 controlwood ct", "zip4": "94999-0142"}


def inject_controls(sqlite_path: Path) -> list[dict]:
    """Plant the matrix, with its own synthetic flow; return what the scan must report for each control."""
    c = []
    flow = CONTROL_FLOW
    with sqlite3.connect(sqlite_path) as conn:
        project = conn.execute("SELECT id FROM nodes WHERE type != 'MoneyFlow' ORDER BY id LIMIT 1").fetchone()[0]
        conn.execute("INSERT INTO nodes(id, type, search_label, props) VALUES (?, 'MoneyFlow', '', '{}')", (flow,))
        browse = conn.execute("SELECT id FROM browse_rows ORDER BY id LIMIT 1").fetchone()[0]
        # Gate A: the global needle on every surface kind, once transformed (case, spacing, embedded).
        conn.execute("UPDATE nodes SET props = json_set(props, '$.control_value', ?) WHERE id = ?",
                     ("near   8  CONTROLWOOD Ln  today", project))
        c.append({"gate": "a", "surface": "nodes", "path": "props.control_value", "row": project})
        conn.execute("UPDATE nodes SET props = json_set(props, '$.\"8 Controlwood Ln\"', 1) WHERE id = ?", (project,))
        c.append({"gate": "a", "surface": "nodes", "path": "props.{key}", "row": project})
        conn.execute("UPDATE browse_rows SET col1_value = ? WHERE id = ?", (json.dumps("8 Controlwood Ln"), browse))
        c.append({"gate": "a", "surface": "browse_rows", "path": "col1_value", "row": browse})
        conn.execute("UPDATE nodes SET search_label = ? WHERE id = ?", ("at 8 Controlwood Ln", project))
        c.append({"gate": "a", "surface": "nodes", "path": "search_label", "row": project})
        conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('control_a', '8 Controlwood Ln')")
        c.append({"gate": "a", "surface": "meta", "path": "value", "row": "control_a"})
        conn.execute("INSERT INTO search_fts(rowid, search_label, search_terms) VALUES (30000001, ?, '')",
                     ("8 Controlwood Ln",))
        c.append({"gate": "a", "surface": "search_fts", "path": "*", "row": "rowid:30000001"})
        # Gate A per flow: the flow's own withheld value is caught on it and nowhere else (negative control).
        conn.execute("UPDATE nodes SET search_label = ? WHERE id = ?", ("from Controlco Widgets", flow))
        c.append({"gate": "a", "surface": "nodes", "path": "search_label", "row": flow})
        conn.execute("UPDATE nodes SET props = json_set(props, '$.control_other', 'Controlco Widgets') "
                     "WHERE id = ?", (project,))
        c.append({"gate": "a", "surface": "nodes", "path": "props.control_other", "row": project, "absent": True})
        # Gate C: a published value the ledger does not yield.
        conn.execute("UPDATE nodes SET props = json_set(props, '$.reported_employer', 'Control Co') WHERE id = ?",
                     (flow,))
        c.append({"gate": "c", "row": flow})
        # Gate B: every detector class in plain text and JSON, one on the FTS token stream, and a changed stream.
        for detector, value in CONTROL_DETECTORS.items():
            conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)", (f"control_{detector}", value))
            c.append({"gate": "b", "surface": "meta", "path": "value", "row": f"control_{detector}",
                      "detector": detector})
        conn.execute("UPDATE nodes SET props = json_set(props, '$.control_contact', ?) WHERE id = ?",
                     (CONTROL_DETECTORS["email"], project))
        c.append({"gate": "b", "surface": "nodes", "path": "props.control_contact", "row": project, "detector": "email"})
        conn.execute("INSERT INTO search_fts(rowid, search_label, search_terms) VALUES (30000002, ?, '')",
                     ("call 415-555-0143",))
        c.append({"gate": "b", "surface": "search_fts", "path": "search_label", "row": "rowid:30000002",
                  "detector": "phone"})
        c.append({"gate": "b", "surface": "search_fts", "path": "search_label", "row": "rowid:30000002",
                  "detector": "fts_stream_changed"})
    return c


def controls_caught(report: dict, controls: list[dict]) -> list[dict]:
    for control in controls:
        if control["gate"] == "a":
            found = any(all(h[k] == control[k] for k in ("surface", "path", "row"))
                        for h in report["gate_a_prohibited_hits"])
            control["caught"] = found != control.get("absent", False)
        elif control["gate"] == "b":
            control["caught"] = any(all(f[k] == control[k] for k in ("surface", "path", "row", "detector"))
                                    and f["reason"] is None for f in report["gate_b_new_findings"])
        else:
            control["caught"] = any(p.startswith(f"{control['row']}:") for p in report["gate_c_reconciliation_problems"])
    return controls


def run_controls(sqlite_path: Path, baseline: Path, bundle: Path, export_dir: Path, scratch: Path) -> list[dict]:
    shutil.copyfile(sqlite_path, scratch)
    try:
        controls = inject_controls(scratch)
        planted = scan(scratch, baseline, bundle, export_dir, [], extra_needles={CONTROL_NEEDLE: "control"},
                       extra_per_flow={CONTROL_FLOW: {CONTROL_FLOW_VALUE}})
    finally:
        scratch.unlink()
    if len(controls) != REQUIRED_CONTROLS:
        raise ValueError(f"the control matrix planted {len(controls)} of {REQUIRED_CONTROLS} controls")
    return controls_caught(planted, controls)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--sqlite", type=Path, required=True, help="candidate public SQLite")
    parser.add_argument("--baseline", type=Path, required=True, help="baseline bake of the unmigrated graph")
    parser.add_argument("--bundle", type=Path, required=True, help="CF2 normalizer bundle (ledger format 2)")
    parser.add_argument("--export", type=Path, required=True, help="the graph export the candidate was baked from")
    parser.add_argument("--out", type=Path, required=True, help="report JSON (staging only)")
    parser.add_argument("--explain", type=Path, help="JSON list of {surface, path, row, detector, span, reason}")
    args = parser.parse_args(argv)
    try:
        explain = json.loads(args.explain.read_text()) if args.explain else []
        report = scan(args.sqlite, args.baseline, args.bundle, args.export, explain)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    report["controls"] = run_controls(args.sqlite, args.baseline, args.bundle, args.export,
                                      args.out.parent / f"{args.out.stem}-controls.sqlite")
    report["passed"] = report["passed"] and all(c["caught"] for c in report["controls"])
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n")
    print(f"gate A prohibited hits: {len(report['gate_a_prohibited_hits'])} "
          f"(pre-existing public text: {len(report['gate_a_preexisting_public_text'])})")
    print(f"gate B new findings: {len(report['gate_b_new_findings'])} ({report['gate_b_unexplained']} unexplained)")
    print(f"gate C reconciliation problems: {len(report['gate_c_reconciliation_problems'])}")
    print(f"controls caught: {sum(c['caught'] for c in report['controls'])}/{len(report['controls'])}")
    print("PASS" if report["passed"] else "FAIL")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
