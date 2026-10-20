#!/usr/bin/env python3
"""Attribute each combined-capture Meeting to the body that actually held it.

The April CivicPlus captures filed every category under one institution (registry/body-attribution.yaml names
each such source institution and its bodies). This module draws the attribution from evidence only:

    body_attribution.py map --export <export dir> --out <staging dir>

reads an export (`export_live_graph.py --backup`), and for every Meeting of a source institution decides, in order:

  * a missing or unknown category                    -> held (never guessed);
  * a title naming a joint meeting                   -> held;
  * the source's own category (e.g. "Town Council"), its title silent or naming that body too -> stays;
  * a title naming another known body                -> held (the category and the title disagree);
  * otherwise                                        -> moved to its category's body.

A held meeting keeps its current attribution. The output (map.jsonl, held.jsonl, summary.json, report.md) is
deterministic and records the sha256 of the export, the bodies file and the map itself, for review.

    body_attribution.py plan --baseline <export dir> --map <map dir> --out <staging dir>

turns the reviewed map into the migration: new institutions (and their IN_JURISDICTION) are created; each moved
Meeting's institution_id and its one AT_INSTITUTION are re-pointed; nothing else changes. It writes ops.json, the
candidate export, inverse.json and inverse-identity.json (forward then inverse on the baseline, byte for byte).
`statements` / `inverse_statements` are the same operations in Cypher, each with its exact expected count, for
one transaction; the inverse first proves the migration's creations hold nothing else, or changes nothing.

    body_attribution.py guard --map <map dir>

writes registry/body-attribution-guard.yaml: every moved meeting id and its body. normalize_meetings drops a
meeting its source lists again whose guarded body is another institution (a re-categorized agenda keeps its id;
the identity map can canonicalize a new id onto a moved one), and the loaders refuse, before any write, a batch
whose Meeting or AT_INSTITUTION contradicts the guard. So no weekly run, nor a reload of an old bundle, undoes it.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BODIES_PATH = REPO / "registry" / "body-attribution.yaml"
GUARD_PATH = REPO / "registry" / "body-attribution-guard.yaml"
MEETING_ID = re.compile(r"^meeting-(?P<source>[a-z0-9-]+)-(?P<n>[0-9]+)$")
STAGING_ROOT = Path.home() / "open-marin-staging" / "body-attribution"
EXPORT_FILES = ("nodes.jsonl", "edges.jsonl")
INSTITUTION_ID = re.compile(r"^org-[a-z0-9]+(-[a-z0-9]+)*$")
PLACE_ID = re.compile(r"^place-[a-z0-9]+(-[a-z0-9]+)*$")
JOINT = re.compile(r"\bjoint\b")
BODY_KEYS = ("category", "institution_id", "name", "jurisdiction_id", "aliases", "source")


class AttributionError(Exception):
    """The bodies file or an input is not one this module can attribute from; nothing was written."""


class StatementCountError(Exception):
    """A statement touched a different number of rows than planned; the caller rolls the transaction back."""


@dataclass(frozen=True)
class Verdict:
    rule: str  # "move" | "stays" | "held"
    to: str
    reason: str


def _words(text: str | None) -> str:
    """Lowercase words for alias matching: '&' is 'and', periods vanish, any other punctuation separates."""
    text = (text or "").lower().replace("&", " and ").replace(".", "")
    return " " + " ".join(re.sub(r"[^a-z0-9]+", " ", text).split()) + " "


def _squash(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", _words(text))


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def stable_line(row: dict) -> str:
    """export_live_graph's serialization, byte for byte."""
    return json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


_line = stable_line


def edge_key(e: dict) -> tuple[str, str, str]:
    """export_live_graph's edge order (ORDER BY s.id, type(r), t.id)."""
    return e["start_id"], e["type"], e["end_id"]


class Bodies:
    """The reviewed bodies file: per source institution, its own category and each other category's body."""

    def __init__(self, sources: dict[str, dict]):
        self.sources = sources

    @classmethod
    def load(cls, path: Path) -> "Bodies":
        import yaml

        return cls.from_dict(yaml.safe_load(Path(path).read_text()))

    @classmethod
    def from_dict(cls, data: dict) -> "Bodies":
        sources = (data or {}).get("sources") or {}
        if not sources:
            raise AttributionError("the bodies file names no source institution")
        for inst, source in sources.items():
            if not INSTITUTION_ID.match(inst):
                raise AttributionError(f"source institution {inst!r} is not an org-<place>-<body> id")
            for body in source.get("bodies") or []:
                where = f"{inst} / {body.get('category')!r}"
                missing = [k for k in BODY_KEYS if not body.get(k)]
                if missing:
                    raise AttributionError(f"{where}: missing {', '.join(missing)}")
                if not INSTITUTION_ID.match(body["institution_id"]):
                    raise AttributionError(f"{where}: institution_id {body['institution_id']!r} is not org-<place>-<body>")
                if not PLACE_ID.match(body["jurisdiction_id"]):
                    raise AttributionError(f"{where}: jurisdiction_id {body['jurisdiction_id']!r} is not a place- id")
            cats = [b["category"] for b in source.get("bodies") or []]
            if len(cats) != len(set(cats)) or source.get("own_category") in cats:
                raise AttributionError(f"{inst}: a category is named twice")
        return cls(sources)

    def _mentioned(self, source: dict, inst: str, title: str) -> dict[str, str]:
        """Every known body the title names: {institution id or name: the alias found}."""
        words = _words(title)
        named = {}
        candidates = [(b["institution_id"], b["aliases"]) for b in source.get("bodies") or []]
        candidates.append((inst, source.get("own_aliases") or []))
        candidates += list((source.get("other_aliases") or {}).items())
        for body, aliases in candidates:
            for alias in aliases:
                if _words(alias) in words:
                    named[body] = alias
                    break
        return named

    def classify(self, props: dict) -> Verdict:
        inst = props.get("institution_id")
        source = self.sources.get(inst)
        if source is None:
            raise AttributionError(f"{props.get('id')}: {inst} is not a source institution")
        category, title = props.get("category"), props.get("title") or ""
        if not category:
            return Verdict("held", inst, "missing category")
        body = next((b for b in source.get("bodies") or [] if b["category"] == category), None)
        if body is None and category != source.get("own_category"):
            return Verdict("held", inst, f"unknown category {category!r}")
        if JOINT.search(title.lower()):
            return Verdict("held", inst, "joint meeting (title)")
        named = self._mentioned(source, inst, title)
        if body is None and (inst in named or not named):  # e.g. the Town Council's own interviews for a commission
            return Verdict("stays", inst, f"category {category} (the source's own body)")
        others = {k: v for k, v in named.items() if k != (body or {}).get("institution_id", inst)}
        if others:
            return Verdict("held", inst, "title names another body: " + ", ".join(
                f"{k} ({v!r})" for k, v in sorted(others.items())))
        return Verdict("move", body["institution_id"], f"category {category}")

    def all_bodies(self) -> list[dict]:
        return sorted((b for s in self.sources.values() for b in s.get("bodies") or []),
                      key=lambda b: b["institution_id"])

    def new_institutions(self, existing: dict[str, str]) -> list[str]:
        """The bodies' institution ids not already in the graph (`existing`: Organization id -> name). An id or
        name that is a near-duplicate of an existing Organization's is refused: reuse it or rename, never both."""
        new = []
        for body in self.all_bodies():
            bid = body["institution_id"]
            if bid in existing:
                continue
            for oid, name in sorted(existing.items()):
                a, b = bid.split("-"), oid.split("-")
                short = min(len(a), len(b))
                if (_squash(oid) == _squash(bid) or (short >= 4 and a[:short] == b[:short])
                        or (name and _words(name) == _words(body["name"]))):
                    raise AttributionError(f"{bid} is a near-duplicate of the existing {oid} ({name!r})")
            new.append(bid)
        return sorted(set(new))


@dataclass
class MapResult:
    rows: list[dict]
    counts: dict
    new_institutions: list[str]
    reused_institutions: list[str]


def build_map(nodes, bodies: Bodies) -> MapResult:
    """One row per Meeting of a source institution (sorted by id), the counts, and which bodies are new."""
    rows, existing = [], {}
    for node in nodes:
        props = node.get("properties") or {}
        if "Organization" in node.get("labels", []):
            existing[node["id"]] = props.get("name") or ""
        if "Meeting" in node.get("labels", []) and props.get("institution_id") in bodies.sources:
            verdict = bodies.classify({**props, "id": node["id"]})
            rows.append({"id": node["id"], "category": props.get("category"), "title": props.get("title"),
                         "meeting_date": props.get("meeting_date"), "from": props["institution_id"],
                         "to": verdict.to, "rule": verdict.rule, "reason": verdict.reason})
    rows.sort(key=lambda r: r["id"])
    counts = {"before": dict(sorted(Counter(r["from"] for r in rows).items())),
              "after": dict(sorted(Counter(r["to"] for r in rows).items())),
              "rules": dict(sorted(Counter(r["rule"] for r in rows).items())),
              "total": len(rows)}
    new = bodies.new_institutions(existing)
    reused = sorted(b["institution_id"] for b in bodies.all_bodies() if b["institution_id"] in existing)
    return MapResult(rows, counts, new, reused)


def read_jsonl(path: Path):
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


def staging_out(path: Path, root: Path) -> Path:
    out, root = Path(path).expanduser().resolve(), Path(root).expanduser().resolve()
    if not (out == root or root in out.parents):
        raise AttributionError(f"refusing to write outside {root}")
    if out.exists() and any(out.iterdir()):
        raise AttributionError(f"output dir {out} is not empty")
    return out


def _render_map(summary: dict, rows: list[dict], bodies: Bodies) -> str:
    by_id = {b["institution_id"]: b for b in bodies.all_bodies()}
    c = summary["counts"]
    lines = ["# Body attribution — map for review", "",
             f"Export: `{summary['export']['dir']}` — nodes `{summary['export']['sha256']['nodes.jsonl']}`, "
             f"edges `{summary['export']['sha256']['edges.jsonl']}`  ",
             f"Predicate: {summary['predicate']}  ",
             f"Bodies file sha256 `{summary['bodies_sha256']}`; map.jsonl sha256 `{summary['map_sha256']}`", "",
             f"## Counts ({c['total']} meetings: " + ", ".join(f"{k} {v}" for k, v in c["rules"].items()) + ")", "",
             "| Institution | Before | After |", "|---|---:|---:|"]
    for inst in sorted(set(c["before"]) | set(c["after"])):
        lines.append(f"| {inst} | {c['before'].get(inst, 0)} | {c['after'].get(inst, 0)} |")
    lines += ["", "## Institutions", "", "| Institution | Name | Jurisdiction | New? | Source |", "|---|---|---|---|---|"]
    for inst in sorted(by_id):
        b = by_id[inst]
        state = "new" if inst in summary["new_institutions"] else "existing (reused)"
        lines.append(f"| {inst} | {b['name']} | {b['jurisdiction_id']} | {state} | {b['source']} |")
    held = [r for r in rows if r["rule"] == "held"]
    lines += ["", f"## Held ({len(held)}) — keep their current attribution; Stuart decides", "",
              "| Meeting | Date | Category | Title | Reason |", "|---|---|---|---|---|"]
    for r in held:
        title = (r["title"] or "").replace("|", "/")
        lines.append(f"| {r['id']} | {r['meeting_date']} | {r['category']} | {title} | {r['reason']} |")
    return "\n".join(lines) + "\n"


def write_map(export: Path, bodies_path: Path, out: Path, *, staging_root: Path | None = None) -> dict:
    out = staging_out(out, staging_root or STAGING_ROOT)
    export = Path(export).resolve()
    bodies = Bodies.load(bodies_path)
    result = build_map(read_jsonl(export / "nodes.jsonl"), bodies)
    out.mkdir(parents=True, exist_ok=True)
    (out / "map.jsonl").write_text("".join(_line(r) + "\n" for r in result.rows), encoding="utf-8")
    (out / "held.jsonl").write_text("".join(_line(r) + "\n" for r in result.rows if r["rule"] == "held"),
                                    encoding="utf-8")
    by_id = {b["institution_id"]: b for b in bodies.all_bodies()}
    summary = {
        "export": {"dir": str(export), "sha256": {n: _sha(export / n) for n in EXPORT_FILES}},
        "predicate": "Meeting nodes whose institution_id is one of " + ", ".join(sorted(bodies.sources)),
        "bodies_sha256": _sha(bodies_path),
        "map_sha256": _sha(out / "map.jsonl"),
        "held_sha256": _sha(out / "held.jsonl"),
        "counts": result.counts,
        "new_institutions": result.new_institutions,
        "reused_institutions": result.reused_institutions,
        "institutions": {i: {k: by_id[i][k] for k in ("name", "jurisdiction_id", "source")} for i in sorted(by_id)},
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    (out / "report.md").write_text(_render_map(summary, result.rows, bodies), encoding="utf-8")
    return summary


# --- the migration --------------------------------------------------------------------------------------------

GOVERNMENT = ["Government", "Organization"]  # the normalize stub's labels (export order: sorted)


def read_export(export: Path) -> tuple[list[dict], list[dict]]:
    return list(read_jsonl(Path(export) / "nodes.jsonl")), list(read_jsonl(Path(export) / "edges.jsonl"))


def write_export(out: Path, nodes, edges) -> dict:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "nodes.jsonl").write_text("".join(stable_line(n) + "\n" for n in sorted(nodes, key=lambda n: n["id"])),
                                     encoding="utf-8")
    (out / "edges.jsonl").write_text("".join(stable_line(e) + "\n" for e in sorted(edges, key=edge_key)),
                                     encoding="utf-8")
    return fingerprint(out)


def fingerprint(export: Path) -> dict:
    return {n: _sha(Path(export) / n) for n in EXPORT_FILES}


def _institution_node(body: dict) -> dict:
    """Exactly the shape normalize_meetings' institution stub takes once loaded."""
    return {"id": body["institution_id"], "labels": list(GOVERNMENT), "properties": {
        "id": body["institution_id"], "name": body["name"], "display_label": body["name"], "subtype": "government",
        "jurisdiction_id": body["jurisdiction_id"], "promotion_state": "promoted"}}


def plan_migration(nodes: list[dict], edges: list[dict], rows: list[dict], bodies: Bodies) -> dict:
    """The operations for the map's moved rows, against exactly this baseline; refuses anything it cannot re-point
    exactly (a meeting not at its `from`, not exactly one plain AT_INSTITUTION, a missing Place or institution)."""
    by_id = {n["id"]: n for n in nodes}
    existing = {i: (n["properties"].get("name") or "") for i, n in by_id.items() if "Organization" in n["labels"]}
    new = bodies.new_institutions(existing)
    body_of = {b["institution_id"]: b for b in bodies.all_bodies()}
    moved = [r for r in rows if r["rule"] == "move"]
    targets = {r["to"] for r in moved}
    unknown = sorted(targets - set(body_of))
    if unknown:
        raise AttributionError(f"the map moves meetings to institutions the bodies file does not name: {unknown}")
    at: dict[str, list[dict]] = {}
    for e in edges:
        if e["type"] == "AT_INSTITUTION":
            at.setdefault(e["start_id"], []).append(e)
    repoint = []
    for r in moved:
        n = by_id.get(r["id"])
        if n is None or "Meeting" not in n["labels"] or n["properties"].get("institution_id") != r["from"]:
            raise AttributionError(f"{r['id']}: not a Meeting at {r['from']} in this baseline")
        outs = at.get(r["id"], [])
        if len(outs) != 1 or outs[0]["end_id"] != r["from"]:
            raise AttributionError(f"{r['id']}: has {len(outs)} AT_INSTITUTION, not exactly one AT_INSTITUTION to "
                                   f"{r['from']}")
        if outs[0]["properties"]:
            raise AttributionError(f"{r['id']}: its AT_INSTITUTION carries properties {sorted(outs[0]['properties'])}")
        repoint.append({"id": r["id"], "from": r["from"], "to": r["to"], "props": {}})
    create = [_institution_node(body_of[i]) for i in new]
    for c in create:
        place = c["properties"]["jurisdiction_id"]
        if "Place" not in by_id.get(place, {}).get("labels", []):
            raise AttributionError(f"{c['id']}: its jurisdiction {place} is not a Place in this baseline")
    reused = sorted(targets - set(new))
    for i in reused:
        if "Organization" not in by_id[i]["labels"]:
            raise AttributionError(f"{i}: reused, but not an Organization")
    dependents = _dependents(nodes, edges, {r["id"] for r in repoint}, set(bodies.sources))
    if dependents["institution_fields"] or "DECIDED_BY" in dependents["decision_edges"]:
        raise AttributionError("what hangs off the moved meetings names an institution (fields "
                               f"{dependents['institution_fields']}, decision edges {dependents['decision_edges']}); "
                               "re-pointing it is not part of this migration")
    return {"repoint": sorted(repoint, key=lambda r: r["id"]), "create_nodes": create,
            "create_edges": [{"start_id": c["id"], "type": "IN_JURISDICTION",
                              "end_id": c["properties"]["jurisdiction_id"], "properties": {}} for c in create],
            "reused": reused, "dependents": dependents}


def _dependents(nodes, edges, moved: set[str], sources: set[str]) -> dict:
    """What hangs off the moved meetings, and whether any of it names an institution (it must not need re-pointing)."""
    touching = Counter(e["type"] for e in edges if e["start_id"] in moved or e["end_id"] in moved)
    hanging = {e["start_id"] for e in edges if e["end_id"] in moved and e["type"] in ("DECIDED_AT", "PART_OF_MEETING")}
    decisions = {n["id"] for n in nodes if n["id"] in hanging and "Decision" in n["labels"]}
    fields = Counter()
    for n in nodes:
        if n["id"] in hanging:
            for k, v in n["properties"].items():
                if "institution" in k or (isinstance(v, str) and v in sources):
                    fields[f"{'/'.join(n['labels'])}.{k}"] += 1
    return {"edges_touching_moved": dict(sorted(touching.items())),
            "decision_edges": dict(sorted(Counter(e["type"] for e in edges
                                                  if e["start_id"] in decisions or e["end_id"] in decisions).items())),
            "decisions": len(decisions), "agenda_items_and_others": len(hanging) - len(decisions),
            "institution_fields": dict(sorted(fields.items()))}


def apply_ops(nodes, edges, ops) -> tuple[list[dict], list[dict]]:
    """The candidate: the baseline with the planned rows changed, nothing else (pure; the Cypher's twin)."""
    moved = {r["id"]: r for r in ops["repoint"]}
    out = {n["id"]: n for n in nodes}
    for r in ops["repoint"]:
        n = copy.deepcopy(out[r["id"]])
        n["properties"]["institution_id"] = r["to"]
        out[r["id"]] = n
    for c in ops["create_nodes"]:
        out[c["id"]] = copy.deepcopy(c)
    kept = [e for e in edges if not (e["type"] == "AT_INSTITUTION" and e["start_id"] in moved
                                     and e["end_id"] == moved[e["start_id"]]["from"])]
    kept += [{"start_id": r["id"], "type": "AT_INSTITUTION", "end_id": r["to"], "properties": {}}
             for r in ops["repoint"]]
    kept += copy.deepcopy(ops["create_edges"])
    return sorted(out.values(), key=lambda n: n["id"]), sorted(kept, key=edge_key)


def _expected_creations(ops) -> list[str]:
    created = {c["id"] for c in ops["create_nodes"]}
    rels = [stable_line(e) for e in ops["create_edges"]]
    rels += [stable_line({"start_id": r["id"], "type": "AT_INSTITUTION", "end_id": r["to"], "properties": {}})
             for r in ops["repoint"] if r["to"] in created]
    return sorted(rels)


def inverse_problems(nodes, edges, ops) -> list[str]:
    """Why the inverse may not run: anything about the migration's creations or moved meetings that differs from
    exactly what it made (empty: the inverse can restore the pre-state)."""
    by_id = {n["id"]: n for n in nodes}
    created = {c["id"]: c for c in ops["create_nodes"]}
    problems = []
    for cid, c in sorted(created.items()):
        have = by_id.get(cid)
        if have is None:
            problems.append(f"{cid}: missing")
        elif sorted(have["labels"]) != sorted(c["labels"]):
            problems.append(f"{cid}: labels {have['labels']} are not the created {c['labels']}")
        elif have["properties"] != c["properties"]:
            problems.append(f"{cid}: properties changed since the migration created it")
    for oid in sorted({r["from"] for r in ops["repoint"]}):
        if "Organization" not in by_id.get(oid, {}).get("labels", []):
            problems.append(f"{oid}: the institution to restore is not an Organization in this graph")
    for place in sorted({e["end_id"] for e in ops["create_edges"]}):
        if "Place" not in by_id.get(place, {}).get("labels", []):
            problems.append(f"{place}: not a Place in this graph")
    touching = sorted(stable_line(e) for e in edges if e["start_id"] in created or e["end_id"] in created)
    if touching != _expected_creations(ops):
        problems.append(f"{len(touching)} relationships touch the created institutions, not exactly the "
                        f"{len(_expected_creations(ops))} the migration created")
    at: dict[str, list[dict]] = {}
    for e in edges:
        if e["type"] == "AT_INSTITUTION" and e["start_id"] in {r["id"] for r in ops["repoint"]}:
            at.setdefault(e["start_id"], []).append(e)
    for r in ops["repoint"]:
        n = by_id.get(r["id"])
        if n is None or "Meeting" not in n["labels"]:
            problems.append(f"{r['id']}: no longer a Meeting")
        elif n["properties"].get("institution_id") != r["to"]:
            problems.append(f"{r['id']}: institution_id is not {r['to']}")
        if [(e["end_id"], e["properties"]) for e in at.get(r["id"], [])] != [(r["to"], {})]:
            problems.append(f"{r['id']}: its AT_INSTITUTION is not exactly the one to {r['to']}")
    return problems


def apply_inverse(nodes, edges, ops) -> tuple[list[dict], list[dict]]:
    """The pre-state, restored exactly (pure); refuses on any inverse problem."""
    problems = inverse_problems(nodes, edges, ops)
    if problems:
        raise AttributionError(f"the inverse refuses: {problems[:5]}")
    moved = {r["id"]: r for r in ops["repoint"]}
    created = {c["id"] for c in ops["create_nodes"]}
    out = {i: n for i, n in ((n["id"], n) for n in nodes) if i not in created}
    for r in ops["repoint"]:
        n = copy.deepcopy(out[r["id"]])
        n["properties"]["institution_id"] = r["from"]
        out[r["id"]] = n
    kept = [e for e in edges if e["start_id"] not in created and e["end_id"] not in created
            and not (e["type"] == "AT_INSTITUTION" and e["start_id"] in moved and e["end_id"] == moved[e["start_id"]]["to"])]
    kept += [{"start_id": r["id"], "type": "AT_INSTITUTION", "end_id": r["from"], "properties": dict(r["props"])}
             for r in ops["repoint"]]
    return sorted(out.values(), key=lambda n: n["id"]), sorted(kept, key=edge_key)


def _stmt(step, query, params, expect) -> dict:
    return {"step": step, "query": query + " RETURN count(*) AS n", "params": params, "expect": expect}


def _rows(ops, old: str, new: str) -> list[dict]:
    return [{"id": r["id"], "old": r[old], "new": r[new], "props": r["props"]} for r in ops["repoint"]]


def statements(ops: dict) -> list[dict]:
    """Prechecks, then creates, then the re-point; each counts exactly its planned rows (prechecks: 0 or all)."""
    new = [c["id"] for c in ops["create_nodes"]]
    places = sorted({c["properties"]["jurisdiction_id"] for c in ops["create_nodes"]})
    rows = _rows(ops, "from", "to")
    at = ("UNWIND $rows AS r MATCH (m:Meeting {id: r.id}) WHERE m.institution_id = r.FIELD "
          "OPTIONAL MATCH (m)-[a:AT_INSTITUTION]->(o) WITH r, m, collect([o.id, properties(a)]) AS outs "
          "WHERE outs = [[r.FIELD, r.props]] WITH m")
    return [
        _stmt("precheck:new_institutions_absent", "UNWIND $ids AS id MATCH (n {id: id}) WITH n", {"ids": new}, 0),
        _stmt("precheck:reused_institutions_present", "UNWIND $ids AS id MATCH (n:Organization {id: id}) WITH n",
              {"ids": ops["reused"]}, len(ops["reused"])),
        _stmt("precheck:places_present", "UNWIND $ids AS id MATCH (p:Place {id: id}) WITH p", {"ids": places},
              len(places)),
        _stmt("precheck:meetings_at_from", at.replace("FIELD", "old"), {"rows": rows}, len(rows)),
        _stmt("create:institutions", "UNWIND $rows AS row CREATE (n:Government:Organization) SET n = row.props WITH n",
              {"rows": [{"props": c["properties"]} for c in ops["create_nodes"]]}, len(new)),
        _stmt("create:institution_jurisdictions", "UNWIND $rows AS e MATCH (o:Organization {id: e.start_id}) "
              "MATCH (p:Place {id: e.end_id}) CREATE (o)-[r:IN_JURISDICTION]->(p) SET r = e.properties WITH r",
              {"rows": ops["create_edges"]}, len(ops["create_edges"])),
        _stmt("repoint:set_institution_id", "UNWIND $rows AS r MATCH (m:Meeting {id: r.id}) "
              "WHERE m.institution_id = r.old SET m.institution_id = r.new WITH m", {"rows": rows}, len(rows)),
        _stmt("repoint:delete_old_edge", "UNWIND $rows AS r MATCH (m:Meeting {id: r.id})-[a:AT_INSTITUTION]->"
              "(o:Organization {id: r.old}) DELETE a WITH r", {"rows": rows}, len(rows)),
        _stmt("repoint:create_new_edge", "UNWIND $rows AS r MATCH (m:Meeting {id: r.id}) "
              "MATCH (o:Organization {id: r.new}) CREATE (m)-[a:AT_INSTITUTION]->(o) WITH a", {"rows": rows},
              len(rows)),
    ]


def inverse_statements(ops: dict) -> list[dict]:
    """Guards first — the created institutions exactly as created, each touched by exactly as many relationships as
    the migration made and each of those present exactly once, unchanged; each moved meeting exactly at its `to` —
    then the restore. Institutions are deleted without DETACH, so one
    that gained a relationship meanwhile fails the transaction rather than losing it."""
    created = [c["id"] for c in ops["create_nodes"]]
    juris = list(ops["create_edges"])
    attrib = [{"start_id": r["id"], "end_id": r["to"]} for r in ops["repoint"] if r["to"] in set(created)]
    rows = _rows(ops, "to", "from")
    back = _rows(ops, "from", "to")
    per_institution = Counter(e["start_id"] for e in juris) + Counter(e["end_id"] for e in attrib)
    exact = ("UNWIND $rows AS e MATCH (s:{s} {{id: e.start_id}}) OPTIONAL MATCH (s)-[r:{rel}]->(t:{t} {{id: e.end_id}}) "
             "WITH e, collect(properties(r)) AS ps WHERE ps = [{{}}] WITH e")
    return [
        _stmt("guard:institutions_as_created", "UNWIND $rows AS c MATCH (n:Organization {id: c.id}) "
              "WHERE size(labels(n)) = 2 AND n:Government AND properties(n) = c.props WITH n",
              {"rows": [{"id": c["id"], "props": c["properties"]} for c in ops["create_nodes"]]}, len(created)),
        _stmt("guard:institution_incident_counts", "UNWIND $rows AS c MATCH (n:Organization {id: c.id}) "
              "OPTIONAL MATCH (n)-[r]-() WITH c, count(r) AS k WHERE k = c.n WITH c",
              {"rows": [{"id": i, "n": per_institution[i]} for i in created]}, len(created)),
        _stmt("guard:created_jurisdictions_exact", exact.format(s="Organization", rel="IN_JURISDICTION", t="Place"),
              {"rows": juris}, len(juris)),
        _stmt("guard:created_attributions_exact", exact.format(s="Meeting", rel="AT_INSTITUTION", t="Organization"),
              {"rows": attrib}, len(attrib)),
        _stmt("guard:old_institutions_present", "UNWIND $ids AS id MATCH (o:Organization {id: id}) WITH o",
              {"ids": sorted({r["from"] for r in ops["repoint"]})}, len({r["from"] for r in ops["repoint"]})),
        _stmt("guard:meetings_at_to", "UNWIND $rows AS r MATCH (m:Meeting {id: r.id}) WHERE m.institution_id = r.old "
              "OPTIONAL MATCH (m)-[a:AT_INSTITUTION]->(o) WITH r, m, collect([o.id, properties(a)]) AS outs "
              "WHERE outs = [[r.old, {}]] WITH m", {"rows": rows}, len(rows)),
        _stmt("restore:delete_new_edge", "UNWIND $rows AS r MATCH (m:Meeting {id: r.id})-[a:AT_INSTITUTION]->"
              "(o:Organization {id: r.old}) DELETE a WITH r", {"rows": rows}, len(rows)),
        _stmt("restore:create_old_edge", "UNWIND $rows AS r MATCH (m:Meeting {id: r.id}) "
              "MATCH (o:Organization {id: r.old}) CREATE (m)-[a:AT_INSTITUTION]->(o) SET a = r.props WITH a",
              {"rows": back}, len(back)),
        _stmt("restore:set_institution_id", "UNWIND $rows AS r MATCH (m:Meeting {id: r.id}) "
              "WHERE m.institution_id = r.old SET m.institution_id = r.new WITH m", {"rows": rows}, len(rows)),
        _stmt("restore:delete_institution_jurisdictions", "UNWIND $rows AS e MATCH (o:Organization {id: e.start_id})"
              "-[r:IN_JURISDICTION]->(p:Place {id: e.end_id}) DELETE r WITH e", {"rows": juris}, len(juris)),
        _stmt("restore:delete_institutions", "UNWIND $ids AS id MATCH (n:Organization {id: id}) DELETE n WITH id",
              {"ids": created}, len(created)),
    ]


def run_statements(tx, stmts: list[dict]) -> dict:
    """Run each on the caller's one transaction; a count off plan raises before the next statement."""
    counts = {}
    for st in stmts:
        n = tx.run(st["query"], **st["params"]).single()["n"]
        if n != st["expect"]:
            raise StatementCountError(f"{st['step']}: touched {n}, planned {st['expect']}")
        counts[st["step"]] = n
    return counts


def apply_in_transaction(tx, ops: dict) -> dict:
    return run_statements(tx, statements(ops))


def inverse_in_transaction(tx, ops: dict) -> dict:
    return run_statements(tx, inverse_statements(ops))


def write_plan(baseline: Path, map_dir: Path, bodies_path: Path, out: Path) -> dict:
    """The migration bundle for exactly this baseline and this reviewed map (staging only)."""
    out = staging_out(out, STAGING_ROOT)
    baseline, map_dir = Path(baseline).resolve(), Path(map_dir)
    summary = json.loads((map_dir / "summary.json").read_text())
    base_sha = fingerprint(baseline)
    if summary["export"]["sha256"] != base_sha:
        raise AttributionError("the map was drawn from another baseline export")
    if _sha(map_dir / "map.jsonl") != summary["map_sha256"] or _sha(bodies_path) != summary["bodies_sha256"]:
        raise AttributionError("the map (or its bodies file) changed since it was written")
    nodes, edges = read_export(baseline)
    bodies = Bodies.load(bodies_path)
    rows = build_map(nodes, bodies).rows
    if "".join(stable_line(r) + "\n" for r in rows) != (map_dir / "map.jsonl").read_text(encoding="utf-8"):
        raise AttributionError("the reviewed map is not the map this code draws from this baseline")
    ops = plan_migration(nodes, edges, rows, bodies)
    out.mkdir(parents=True, exist_ok=True)
    if write_export(out / "baseline-rewritten", nodes, edges) != base_sha:
        raise AttributionError("the baseline does not re-serialize byte for byte; its rows cannot be planned on")
    candidate = apply_ops(nodes, edges, ops)
    cand_sha = write_export(out / "candidate", *candidate)
    restored_sha = write_export(out / "restored", *apply_inverse(*candidate, ops))
    (out / "ops.json").write_text(json.dumps(ops, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    (out / "inverse.json").write_text(json.dumps(inverse_statements(ops), indent=1, sort_keys=True) + "\n",
                                      encoding="utf-8")
    proof = {"baseline_sha256": base_sha, "candidate_sha256": cand_sha, "restored_sha256": restored_sha,
             "identical": restored_sha == base_sha}
    (out / "inverse-identity.json").write_text(json.dumps(proof, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    for d in ("baseline-rewritten", "restored"):
        for n in EXPORT_FILES:
            (out / d / n).unlink()
        (out / d).rmdir()
    report = {"baseline": {"dir": str(baseline), "sha256": base_sha}, "candidate_sha256": cand_sha,
              "map": {"dir": str(Path(map_dir).resolve()), "sha256": summary["map_sha256"]},
              "bodies_sha256": summary["bodies_sha256"], "ops_sha256": _sha(out / "ops.json"),
              "inverse_sha256": _sha(out / "inverse.json"),
              "counts": {"repoint": len(ops["repoint"]), "create_nodes": len(ops["create_nodes"]),
                         "create_edges": len(ops["create_edges"]), "reused": ops["reused"],
                         "repoint_by_target": dict(sorted(Counter(r["to"] for r in ops["repoint"]).items()))},
              "dependents": ops["dependents"],
              "verification": [] if proof["identical"] else ["forward then inverse does not restore the baseline"]}
    (out / "plan-report.json").write_text(json.dumps(report, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return report


# --- the guard ----------------------------------------------------------------------------------------------------

def write_guard_file(rows: list[dict], map_sha256: str, path: Path = None) -> Path:
    """The moved meetings, compactly: per old source, per body, the agenda-id suffixes of `meeting-<source>-<n>`."""
    path = Path(path or GUARD_PATH)
    sources: dict[str, dict] = {}
    for r in rows:
        if r["rule"] != "move":
            continue
        m = MEETING_ID.match(r["id"])
        if not m:
            raise AttributionError(f"{r['id']}: not meeting-<source>-<agenda id>; the guard cannot name it compactly")
        entry = sources.setdefault(m["source"], {"institution_id": r["from"], "moved": {}})
        if entry["institution_id"] != r["from"]:
            raise AttributionError(f"{m['source']}: meetings from two institutions")
        entry["moved"].setdefault(r["to"], []).append(int(m["n"]))
    for entry in sources.values():
        entry["moved"] = {k: sorted(v) for k, v in sorted(entry["moved"].items())}
    import yaml

    header = ("# Generated by scripts/body_attribution.py guard from the reviewed map; do not edit by hand.\n"
              "# Each moved meeting is meeting-<source>-<n>; normalize_meetings drops it from any other institution's\n"
              "# capture and the loaders refuse a contradicting row (see the module docstring).\n")
    body = yaml.safe_dump({"map_sha256": map_sha256, "sources": dict(sorted(sources.items()))}, sort_keys=False,
                          default_flow_style=None, width=118)
    path.write_text(header + body, encoding="utf-8")
    return path


def load_guard(path: Path | None = None) -> dict[str, str]:
    """Moved meeting id -> its body ({} when there is no guard file)."""
    import yaml

    path = Path(path or GUARD_PATH)
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text()) or {}
    return {f"meeting-{source}-{n}": body for source, entry in (data.get("sources") or {}).items()
            for body, ns in entry["moved"].items() for n in ns}


def without_guarded(capture: dict) -> tuple[dict, list[str]]:
    """The capture minus the meetings the guard assigns to an institution other than the capture's."""
    guard = load_guard()
    inst = capture.get("institution_id")
    drop = [m["meeting_id"] for m in capture.get("meetings") or []
            if m.get("meeting_id") in guard and guard[m["meeting_id"]] != inst]
    if not drop:
        return capture, []
    kept = [m for m in capture["meetings"] if m.get("meeting_id") not in set(drop)]
    return {**capture, "meetings": kept, "meeting_count": len(kept)}, drop


def preflight(nodes: list[dict], edges: list[dict]) -> None:
    """Refuse a load (normalized rows: node `properties`, edge `source_id`/`target_id`/`relationship_type`) holding a
    guarded Meeting at another institution, or an AT_INSTITUTION from one to another — before anything is written."""
    guard = load_guard()
    if not guard:
        return
    bad = [f"{n['id']} institution_id {n['properties']['institution_id']}" for n in nodes
           if n.get("id") in guard and (n.get("properties") or {}).get("institution_id") not in (None, guard[n["id"]])]
    bad += [f"{e['source_id']} AT_INSTITUTION {e['target_id']}" for e in edges
            if e.get("relationship_type") == "AT_INSTITUTION" and e.get("source_id") in guard
            and e.get("target_id") != guard[e["source_id"]]]
    if bad:
        raise AttributionError(f"refusing to load {len(bad)} rows that undo the body attribution "
                               f"(registry/body-attribution-guard.yaml): {bad[:5]}")


def identity_problems(cache: dict, guard: dict[str, str], own_categories: dict[str, list[str]]) -> list[str]:
    """How the identity cache (data/ingest-runs/meeting-identity.json) could hand a moved meeting's id to its old
    source's capture: a different id mapped onto it, or a key in that source's own categories linking to it."""
    from adapters.meeting_ids import normalize_title

    problems = []
    for id_key, canonical in sorted((cache.get("by_id") or {}).items()):
        source, _, incoming = id_key.partition("|")
        if canonical in guard and incoming != canonical:
            problems.append(f"by_id {id_key} maps {incoming} onto the moved {canonical}")
    for key, canonical in sorted((cache.get("by_key") or {}).items()):
        parts = key.split("|")
        own = {normalize_title(c) for c in own_categories.get(parts[0], [])}
        if canonical in guard and len(parts) == 4 and parts[2] in own:
            problems.append(f"by_key {key}: a {parts[2]} key links to the moved {canonical}")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("map", help="Write the attribution map for review from an export")
    m.add_argument("--export", type=Path, required=True)
    m.add_argument("--bodies", type=Path, default=BODIES_PATH)
    m.add_argument("--out", type=Path, required=True, help=f"A new directory under {STAGING_ROOT}")
    p = sub.add_parser("plan", help="Write the migration bundle for a baseline and its reviewed map")
    p.add_argument("--baseline", type=Path, required=True)
    p.add_argument("--map", type=Path, required=True)
    p.add_argument("--bodies", type=Path, default=BODIES_PATH)
    p.add_argument("--out", type=Path, required=True, help=f"A new directory under {STAGING_ROOT}")
    g = sub.add_parser("guard", help="Write registry/body-attribution-guard.yaml from the reviewed map")
    g.add_argument("--map", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.cmd == "guard":
            summary = json.loads((args.map / "summary.json").read_text())
            if _sha(args.map / "map.jsonl") != summary["map_sha256"]:
                raise AttributionError("the map changed since it was written")
            print(write_guard_file(list(read_jsonl(args.map / "map.jsonl")), summary["map_sha256"]))
        elif args.cmd == "map":
            print(json.dumps(write_map(args.export, args.bodies, args.out, staging_root=STAGING_ROOT)["counts"],
                             indent=1))
        else:
            print(json.dumps(write_plan(args.baseline, args.map, args.bodies, args.out)["counts"], indent=1))
    except AttributionError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
