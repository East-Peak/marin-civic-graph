"""Dry-run report: row-position meeting ids -> their stable ids (spec I2).

READ-ONLY and offline. Reads the meeting captures under
``<data-dir>/extracted/<source>/*.json`` and re-derives each meeting's id with
the adapters' stable rule (``adapters/meeting_ids.py``). Every capture id of the
old ``…-row-N`` form is mapped to the id the fixed adapter assigns that same
row, so an operator can later merge the orphaned Meeting nodes. Ross captures
that predate ``detail_url`` recover it from the raw page the capture recorded;
a row that cannot be recovered is listed as unresolved, never guessed.

It never connects to Neo4j and writes only ``--out``. The graph dedupe is a
separate, operator-gated step.

Usage:
    python scripts/report_orphan_meeting_ids.py --data-dir data --out /tmp/orphans.json
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict, deque
from pathlib import Path

from adapters import civicplus, drupal_ross, granicus
from adapters.meeting_ids import assign_meeting_ids

ROW_ID_RE = re.compile(r"-row-\d+$")


def _title(meeting: dict) -> str | None:
    return meeting.get("title")


# adapter name -> (native key, text hashed for the fallback), as each adapter stamps ids
RULES = {
    "granicus": (granicus.native_meeting_key, _title),
    "drupal_ross": (drupal_ross.native_meeting_key, _title),
    "civicplus": (civicplus.native_meeting_key, civicplus.meeting_name),
}


def _load_capture(path: Path) -> dict | None:
    try:
        capture = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(capture, dict) or capture.get("adapter") not in RULES:
        return None
    if not isinstance(capture.get("meetings"), list):
        return None
    return capture


def _raw_path(raw_artifact: str | None, data_dir: Path) -> Path | None:
    """Resolve a capture's repo-relative ``data/raw/…`` path against *data_dir*."""
    if not raw_artifact:
        return None
    parts = Path(raw_artifact).parts
    if parts and parts[0] == "data":
        return data_dir.joinpath(*parts[1:])
    return data_dir.parent / raw_artifact


def _recover_ross_detail_urls(capture: dict, meetings: list[dict], data_dir: Path) -> dict[int, str]:
    """Fill ``detail_url`` from the raw page, matching rows on (date, title).

    Returns ``{meeting index: reason}`` for rows that could not be recovered.
    """
    todo = [i for i, m in enumerate(meetings) if "detail_url" not in m]
    if not todo:
        return {}
    raw = _raw_path(capture.get("raw_artifact"), data_dir)
    if raw is None or not raw.is_file():
        return {i: "raw page missing; detail url unknown" for i in todo}

    base_url = (capture.get("url") or "").rstrip("/").rsplit("/meetings", 1)[0]
    pool: dict[tuple, deque] = defaultdict(deque)
    for row in drupal_ross.extract_ross_meetings(raw.read_text(errors="ignore"), base_url):
        pool[(row["date"], row["title"])].append(row["detail_url"])

    unresolved: dict[int, str] = {}
    for i in todo:
        urls = pool.get((meetings[i].get("date"), meetings[i].get("title")))
        if urls:
            meetings[i]["detail_url"] = urls.popleft()
        else:
            unresolved[i] = "row not found in raw page"
    return unresolved


def build_report(data_dir: Path) -> dict:
    """Map every row-position meeting id in the captures to its stable id."""
    sources: dict[str, dict] = {}
    mappings: list[dict] = []
    unresolved: list[dict] = []
    changed_native: list[dict] = []

    for path in sorted((data_dir / "extracted").glob("*/*.json")):
        capture = _load_capture(path)
        if capture is None:
            continue
        adapter = capture["adapter"]
        source_id = capture.get("source_id") or path.parent.name
        native_key, name = RULES[adapter]

        meetings = [dict(m) for m in capture["meetings"]]
        old_ids = [m.get("meeting_id") for m in meetings]
        missing = (
            _recover_ross_detail_urls(capture, meetings, data_dir) if adapter == "drupal_ross" else {}
        )
        assign_meeting_ids(meetings, source_id, native_key, name=name)

        stats = sources.setdefault(
            source_id,
            {"adapter": adapter, "captures": [], "row_position_ids": 0, "mapped": 0, "unresolved": 0},
        )
        stats["captures"].append(path.name)

        for i, (old_id, m) in enumerate(zip(old_ids, meetings)):
            entry = {
                "source_id": source_id,
                "capture": f"{path.parent.name}/{path.name}",
                "old_id": old_id,
                "date": m.get("date"),
                "title": m.get("title"),
            }
            if not old_id or not ROW_ID_RE.search(old_id):
                if old_id != m["meeting_id"]:
                    changed_native.append({**entry, "stable_id": m["meeting_id"]})
                continue
            stats["row_position_ids"] += 1
            if i in missing:
                stats["unresolved"] += 1
                unresolved.append({**entry, "reason": missing[i]})
                continue
            stats["mapped"] += 1
            mappings.append({
                **entry,
                "stable_id": m["meeting_id"],
                "key": "native" if native_key(m) else "title_hash",
            })

    return {
        "graph_mutation": "none",
        "note": "Dry run from offline captures. Merging orphaned Meeting nodes is operator-gated.",
        "data_dir": str(data_dir),
        "sources": sources,
        "mappings": mappings,
        "unresolved": unresolved,
        "changed_native_ids": changed_native,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--data-dir", required=True, type=Path, help="checkout's data/ directory")
    parser.add_argument("--out", required=True, type=Path, help="where to write the JSON report")
    args = parser.parse_args(argv)

    result = build_report(args.data_dir)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    for source_id, s in sorted(result["sources"].items()):
        print(
            f"{source_id}: {s['row_position_ids']} row-position ids, "
            f"{s['mapped']} mapped, {s['unresolved']} unresolved"
        )
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
