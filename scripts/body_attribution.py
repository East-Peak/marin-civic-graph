#!/usr/bin/env python3
"""Attribute each combined-capture Meeting to the body that actually held it.

The April CivicPlus captures filed every category under one institution (registry/body-attribution.yaml names
each such source institution and its bodies). This module draws the attribution from evidence only:

    body_attribution.py map --export <export dir> --out <staging dir>

reads an export (`export_live_graph.py --backup`), and for every Meeting of a source institution decides, in order:

  * a missing or unknown category                    -> held (never guessed);
  * a title naming a joint meeting                   -> held;
  * the source's own category (e.g. "Town Council")  -> stays;
  * a title naming another known body                -> held (the category and the title disagree);
  * otherwise                                        -> moved to its category's body.

A held meeting keeps its current attribution. The output (map.jsonl, held.jsonl, summary.json, report.md) is
deterministic and records the sha256 of the export, the bodies file and the map itself, for review.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BODIES_PATH = REPO / "registry" / "body-attribution.yaml"
STAGING_ROOT = Path.home() / "open-marin-staging" / "body-attribution"
EXPORT_FILES = ("nodes.jsonl", "edges.jsonl")
INSTITUTION_ID = re.compile(r"^org-[a-z0-9]+(-[a-z0-9]+)*$")
PLACE_ID = re.compile(r"^place-[a-z0-9]+(-[a-z0-9]+)*$")
JOINT = re.compile(r"\bjoint\b")
BODY_KEYS = ("category", "institution_id", "name", "jurisdiction_id", "aliases", "source")


class AttributionError(Exception):
    """The bodies file or an input is not one this module can attribute from; nothing was written."""


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


def _line(row: dict) -> str:
    return json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


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
        if body is None:
            return Verdict("stays", inst, f"category {category} (the source's own body)")
        others = {k: v for k, v in self._mentioned(source, inst, title).items() if k != body["institution_id"]}
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


def write_map(export: Path, bodies_path: Path, out: Path, *, staging_root: Path = STAGING_ROOT) -> dict:
    out = staging_out(out, staging_root)
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("map", help="Write the attribution map for review from an export")
    m.add_argument("--export", type=Path, required=True)
    m.add_argument("--bodies", type=Path, default=BODIES_PATH)
    m.add_argument("--out", type=Path, required=True)
    m.add_argument("--staging-root", type=Path, default=STAGING_ROOT)
    args = parser.parse_args(argv)
    try:
        summary = write_map(args.export, args.bodies, args.out, staging_root=args.staging_root)
    except AttributionError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(summary["counts"], indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
