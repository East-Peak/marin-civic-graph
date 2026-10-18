#!/usr/bin/env python3
"""The agenda-items stage's complete delta: what two full exports, taken immediately before and after the stage,
say it wrote.

    agenda_delta.py --pre <export> --post <export> --bundle <run>/agenda-items/bundle \\
                    --stage-report <run>/agenda-items/report.json --out <json>

Exactly the committed meetings' bundle items may appear (labels and properties as the bundle has them), with exactly
their PART_OF_MEETING and EVIDENCED_BY each; every other node keeps its labels and properties, no node or
relationship disappears, and no other relationship appears (relationships compared as a multiset, properties
included). Anything else is a problem the weekly run reports. Read only.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path


def _read(path: Path, name: str) -> list[dict]:
    with open(Path(path) / name, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _edge(e: dict) -> tuple:
    return e["start_id"], e["type"], e["end_id"], json.dumps(e.get("properties") or {}, sort_keys=True)


def compare(pre: Path, post: Path, bundle: Path, *, committed: list[str]) -> dict:
    before = {n["id"]: n for n in _read(pre, "nodes.jsonl")}
    after = {n["id"]: n for n in _read(post, "nodes.jsonl")}
    planned = {n["id"]: n for n in _read(bundle, "nodes.jsonl") if n["properties"].get("meeting_id") in set(committed)}
    problems = []
    for nid in sorted(set(before) - set(after)):
        problems.append(f"removed node {nid}")
    for nid in sorted(set(before) & set(after)):
        if (before[nid]["labels"], before[nid]["properties"]) != (after[nid]["labels"], after[nid]["properties"]):
            problems.append(f"changed node {nid}")
    for nid in sorted(set(after) - set(before)):
        if nid not in planned:
            problems.append(f"unexpected node {nid}")
        elif (after[nid]["labels"], after[nid]["properties"]) != (planned[nid]["labels"], planned[nid]["properties"]):
            problems.append(f"new node {nid} differs from the bundle")
    for nid in sorted(set(planned) - set(after)):
        problems.append(f"committed item missing: {nid}")
    edges_before = Counter(_edge(e) for e in _read(pre, "edges.jsonl"))
    edges_after = Counter(_edge(e) for e in _read(post, "edges.jsonl"))
    expected = Counter(_edge(e) for e in _read(bundle, "edges.jsonl") if e["start_id"] in planned)
    for edge, n in sorted((edges_before - edges_after).items()):
        problems.append(f"removed edge {edge[:3]} x{n}")
    added = edges_after - edges_before
    for edge, n in sorted((added - expected).items()):
        problems.append(f"unexpected edge {edge[:3]} x{n}")
    for edge, n in sorted((expected - added).items()):
        problems.append(f"committed edge missing {edge[:3]} x{n}")
    return {"ok": not problems, "problems": problems[:200], "problem_count": len(problems),
            "added_nodes": len(set(after) - set(before)), "added_edges": sum(added.values()),
            "committed_meetings": sorted(committed)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    for flag in ("--pre", "--post", "--bundle", "--stage-report", "--out"):
        parser.add_argument(flag, type=Path, required=True)
    args = parser.parse_args(argv)
    report = json.loads(args.stage_report.read_text(encoding="utf-8"))
    result = compare(args.pre, args.post, args.bundle, committed=list(report["load"]["created"]["meetings"]))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    print(f"agenda delta: {'ok' if result['ok'] else 'PROBLEMS'} ({result['added_nodes']} nodes, "
          f"{result['added_edges']} edges added; {result['problem_count']} problems)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
