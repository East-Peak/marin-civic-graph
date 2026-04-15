#!/usr/bin/env python3
"""Normalize adapter meeting output into settled-ontology JSONL for Neo4j loading.

Reads extracted JSON from Granicus/CivicPlus adapters and produces:
  - nodes.jsonl (Meeting, Record, Organization, Place nodes)
  - edges.jsonl (AT_INSTITUTION, IN_JURISDICTION, EVIDENCED_BY)
  - normalization-report.json
"""

from __future__ import annotations

import argparse
import json
import glob
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

ROOT = Path(__file__).resolve().parent.parent

# Maps source_id patterns to human-readable institution display names
INSTITUTION_DISPLAY = {
    "org-marin-county-board-of-supervisors": "Marin County Board of Supervisors",
    "org-novato-city-council": "Novato City Council",
    "org-sausalito-city-council": "Sausalito City Council",
    "org-corte-madera-town-council": "Corte Madera Town Council",
    "org-mill-valley-committees": "Mill Valley Committees",
}

PLACE_DISPLAY = {
    "place-marin-county": ("Marin County", "county"),
    "place-novato": ("Novato", "city"),
    "place-sausalito": ("Sausalito", "city"),
    "place-corte-madera": ("Corte Madera", "city"),
    "place-mill-valley": ("Mill Valley", "city"),
}

ARTIFACT_RECORD_TYPES = {
    "agenda": "meeting_agenda",
    "minutes": "meeting_minutes",
    "video": "meeting_video",
    "packet": "meeting_packet",
    "captions": "meeting_captions",
    "mp3": "meeting_audio",
    "mp4": "meeting_video_file",
}


def _node(id: str, node_type: str, labels: list[str], display_label: str,
          properties: dict, capture: dict, section: str = "meeting_candidates",
          status: str | None = None) -> dict:
    return {
        "id": id,
        "node_type": node_type,
        "labels": labels,
        "display_label": display_label,
        "promotion_state": "promoted",
        "source_bundle_ids": [capture["capture_id"]],
        "source_sections": [section],
        "source_status": status,
        "properties": properties,
        "qa_lane": False,
    }


def _edge(source_id: str, source_type: str, target_id: str, target_type: str,
          rel_type: str, capture: dict, properties: dict | None = None) -> dict:
    return {
        "source_id": source_id,
        "source_node_type": source_type,
        "target_id": target_id,
        "target_node_type": target_type,
        "relationship_type": rel_type,
        "source_bundle_ids": [capture["capture_id"]],
        "source_fields": ["normalize_meetings"],
        "properties": properties or {},
    }


def build_meeting_node(meeting: dict, capture: dict) -> dict:
    source_id = capture["source_id"]
    title = meeting.get("title") or "Meeting"
    date = meeting.get("date") or ""
    display = f"{title} — {date}" if date else title

    props = {
        "meeting_date": date,
        "meeting_type": meeting.get("meeting_type", "other"),
        "title": title,
        "institution_id": capture["institution_id"],
        "jurisdiction_id": capture["jurisdiction_id"],
    }
    if meeting.get("clip_id"):
        props["clip_id"] = meeting["clip_id"]
    if meeting.get("agenda_id"):
        props["agenda_id"] = meeting["agenda_id"]
    if meeting.get("category"):
        props["category"] = meeting["category"]

    return _node(
        id=meeting["meeting_id"],
        node_type="Meeting",
        labels=["Meeting"],
        display_label=display,
        properties=props,
        capture=capture,
        status=f"captured_from_{capture.get('adapter', 'unknown')}",
    )


def build_record_node(ref: dict, capture: dict) -> dict:
    props = {
        "record_type": ref.get("record_type", "unknown"),
        "source_id": ref.get("source_id", capture["source_id"]),
    }
    if ref.get("artifact_path"):
        props["artifact_path"] = ref["artifact_path"]
    if ref.get("source_url"):
        props["source_url"] = ref["source_url"]
    if ref.get("captured_at"):
        props["captured_at"] = ref["captured_at"]
    if ref.get("year"):
        props["year"] = ref["year"]

    return _node(
        id=ref["id"],
        node_type="Record",
        labels=["Record"],
        display_label=ref.get("record_type", ref["id"]),
        properties=props,
        capture=capture,
        section="record_refs",
        status="captured",
    )


def build_institution_stub(capture: dict) -> dict:
    inst_id = capture["institution_id"]
    display = INSTITUTION_DISPLAY.get(inst_id, inst_id.replace("org-", "").replace("-", " ").title())
    return _node(
        id=inst_id,
        node_type="Organization",
        labels=["Organization", "Government"],
        display_label=display,
        properties={
            "name": display,
            "subtype": "government",
            "jurisdiction_id": capture["jurisdiction_id"],
        },
        capture=capture,
        section="institution_stubs",
        status="stub_from_adapter_config",
    )


def build_place_stub(capture: dict) -> dict:
    place_id = capture["jurisdiction_id"]
    display, place_type = PLACE_DISPLAY.get(
        place_id,
        (place_id.replace("place-", "").replace("-", " ").title(), "city"),
    )
    return _node(
        id=place_id,
        node_type="Place",
        labels=["Place"],
        display_label=display,
        properties={"name": display, "place_type": place_type},
        capture=capture,
        section="place_stubs",
        status="stub_from_adapter_config",
    )


def build_edges(meeting: dict, capture: dict) -> list[dict]:
    edges = []
    mid = meeting["meeting_id"]

    # Meeting → Organization
    edges.append(_edge(mid, "Meeting", capture["institution_id"], "Organization",
                       "AT_INSTITUTION", capture))

    # Meeting → Place
    edges.append(_edge(mid, "Meeting", capture["jurisdiction_id"], "Place",
                       "IN_JURISDICTION", capture))

    # Meeting → Record (evidence for each available artifact)
    for art_type, art in meeting.get("artifacts", {}).items():
        if art.get("available") and art.get("url"):
            record_id = f"record-{capture['source_id']}-{meeting['meeting_id'].split('meeting-')[-1]}-{art_type}"
            edges.append(_edge(mid, "Meeting", record_id, "Record",
                               "EVIDENCED_BY", capture))

    return edges


def normalize_source(capture: dict, output_dir: Path) -> tuple[list[dict], list[dict], dict]:
    output_dir.mkdir(parents=True, exist_ok=True)

    nodes: list[dict] = []
    edges: list[dict] = []

    # Institution and Place stubs
    nodes.append(build_institution_stub(capture))
    nodes.append(build_place_stub(capture))

    # Organization → Place edge
    edges.append(_edge(capture["institution_id"], "Organization",
                       capture["jurisdiction_id"], "Place",
                       "IN_JURISDICTION", capture))

    # Archive page record
    for ref in capture.get("record_refs", []):
        nodes.append(build_record_node(ref, capture))

    # Meetings + per-meeting artifact records + edges
    for meeting in capture.get("meetings", []):
        nodes.append(build_meeting_node(meeting, capture))
        meeting_edges = build_edges(meeting, capture)
        edges.extend(meeting_edges)

        # Create Record nodes for available artifacts
        for art_type, art in meeting.get("artifacts", {}).items():
            if art.get("available") and art.get("url"):
                mid_suffix = meeting["meeting_id"].split("meeting-")[-1]
                record_id = f"record-{capture['source_id']}-{mid_suffix}-{art_type}"
                record_type = ARTIFACT_RECORD_TYPES.get(art_type, f"meeting_{art_type}")
                nodes.append(build_record_node(
                    {"id": record_id, "record_type": record_type,
                     "source_id": capture["source_id"],
                     "source_url": art["url"],
                     "captured_at": capture["captured_at"]},
                    capture,
                ))

    # Write JSONL
    with open(output_dir / "nodes.jsonl", "w") as f:
        for node in nodes:
            f.write(json.dumps(node, sort_keys=True) + "\n")
    with open(output_dir / "edges.jsonl", "w") as f:
        for edge in edges:
            f.write(json.dumps(edge, sort_keys=True) + "\n")

    report = {
        "source_id": capture["source_id"],
        "capture_id": capture["capture_id"],
        "normalized_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "node_count": len(nodes),
        "edge_count": len(edges),
        "meeting_count": len(capture.get("meetings", [])),
        "record_count": len([n for n in nodes if n["node_type"] == "Record"]),
    }
    with open(output_dir / "normalization-report.json", "w") as f:
        json.dump(report, indent=2, fp=f)
        f.write("\n")

    return nodes, edges, report


def find_latest_capture(source_id: str) -> Path | None:
    pattern = str(ROOT / "data" / "extracted" / source_id / "*.json")
    files = sorted(glob.glob(pattern))
    return Path(files[-1]) if files else None


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize adapter meeting output to settled-ontology JSONL")
    parser.add_argument("--source", help="Source ID to normalize")
    parser.add_argument("--all", dest="all_sources", action="store_true", help="Normalize all available sources")
    parser.add_argument("--load", action="store_true", help="Load into Neo4j after normalization")
    args = parser.parse_args()

    import yaml
    sources = []
    for registry_file in (ROOT / "registry").glob("*-sources.yaml"):
        with open(registry_file) as f:
            data = yaml.safe_load(f)
        sources.extend(data.get("sources", []))

    if args.source:
        targets = [s for s in sources if s["id"] == args.source]
        if not targets:
            print(f"Unknown source: {args.source}", file=sys.stderr)
            sys.exit(1)
    elif args.all_sources:
        targets = sources
    else:
        print("Specify --source <id> or --all", file=sys.stderr)
        sys.exit(1)

    for source_config in targets:
        source_id = source_config["id"]
        capture_path = find_latest_capture(source_id)
        if not capture_path:
            print(f"  No captures found for {source_id}, skipping")
            continue

        print(f"\nNormalizing: {source_id}")
        print(f"  Capture: {capture_path}")

        capture = json.loads(capture_path.read_text())
        if capture.get("meeting_count", 0) == 0:
            print(f"  No meetings in capture, skipping")
            continue

        output_dir = ROOT / "data" / "normalized" / f"{source_id}-meetings"
        nodes, edges, report = normalize_source(capture, output_dir)

        print(f"  Nodes: {report['node_count']}")
        print(f"  Edges: {report['edge_count']}")
        print(f"  Meetings: {report['meeting_count']}")
        print(f"  Records: {report['record_count']}")
        print(f"  Output: {output_dir}")

        if args.load:
            from load_neo4j_v2 import load_nodes as neo4j_load_nodes, load_edges as neo4j_load_edges, apply_schema
            from neo4j import GraphDatabase

            uri = os.getenv("NEO4J_URI")
            user = os.getenv("NEO4J_USER")
            password = os.getenv("NEO4J_PASSWORD")
            if not all([uri, user, password]):
                print("  NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD required for --load", file=sys.stderr)
                continue

            driver = GraphDatabase.driver(uri, auth=(user, password))
            try:
                print(f"  Loading into Neo4j...")
                neo4j_load_nodes(driver, nodes)
                neo4j_load_edges(driver, edges)
                print(f"  Loaded.")
            finally:
                driver.close()


if __name__ == "__main__":
    main()
