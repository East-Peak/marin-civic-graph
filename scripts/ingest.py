#!/usr/bin/env python3
"""Ingestion runner — load source registry, dispatch adapters, write output."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

from adapters import get_adapter_class

ROOT = Path(__file__).resolve().parent.parent


def load_sources(registry_path: Path) -> list[dict]:
    with open(registry_path) as f:
        data = yaml.safe_load(f)
    return data.get("sources", [])


def resolve_sources(
    sources: list[dict],
    source: str | None = None,
    all_sources: bool = False,
) -> list[dict]:
    if all_sources:
        return list(sources)
    if source:
        matches = [s for s in sources if s["id"] == source]
        if not matches:
            available = [s["id"] for s in sources]
            raise ValueError(f"Unknown source: {source!r}. Available: {available}")
        return matches
    raise ValueError("Specify --source <id> or --all")


def run_source(source_config: dict, root: Path) -> dict:
    adapter_cls = get_adapter_class(source_config["adapter"])
    adapter = adapter_cls(source_config, root)
    result = adapter.capture()

    out_path = adapter.extracted_path()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2) + "\n")

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Run ingestion adapters")
    parser.add_argument("--source", help="Source ID to capture")
    parser.add_argument("--all", dest="all_sources", action="store_true", help="Capture all sources")
    parser.add_argument(
        "--registry",
        default="registry/granicus-sources.yaml",
        help="Path to source registry",
    )
    args = parser.parse_args()

    registry_path = ROOT / args.registry
    sources = load_sources(registry_path)

    try:
        targets = resolve_sources(sources, source=args.source, all_sources=args.all_sources)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    for i, source_config in enumerate(targets):
        if i > 0:
            print("  (waiting 2s between sources)")
            time.sleep(2)

        source_id = source_config["id"]
        print(f"\nCapturing: {source_id}")
        print(f"  Adapter: {source_config['adapter']}")
        print(f"  URL: {source_config['url']}")

        try:
            result = run_source(source_config, ROOT)
            print(f"  Variant: {result.get('variant', 'unknown')}")
            print(f"  Meetings: {result['meeting_count']}")
            for art, count in sorted(result.get("artifact_counts", {}).items()):
                print(f"    {art}: {count}")
            if result.get("errors"):
                print(f"  Errors: {len(result['errors'])}")
                for err in result["errors"]:
                    print(f"    - {err}")
        except Exception as e:
            print(f"  FAILED: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
