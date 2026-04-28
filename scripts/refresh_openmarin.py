#!/usr/bin/env python3
"""
Post-ingest refresh orchestrator for Open Marin.

Runs, in order:
  1. scripts/apply_search_index.py        (idempotent schema + index creation)
  2. scripts/build_search_properties.py   (denormalize search_label/terms/rank)
  3. scripts/build_record_preferred_urls.py  (normalize Record public URLs)
  4. scripts/build_catalog.py             (bake per-type counts to catalog.json)
  5. scripts/build_signature_subgraphs.py (build homepage bundle JSON)
  6. scripts/update_sync_state.py         (stamp :_SyncState for INGEST freshness)
  7. app/scripts/copy-subgraphs.mjs       (publish freshly-built bundles + catalog into app/public/)

Exits non-zero if any step fails. Call this after every ingestion run so the
frontend's baked artifacts and freshness timestamps stay correct.

Requires NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD / NEO4J_DATABASE in env.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

PYTHON_STEPS = [
    "scripts/apply_search_index.py",
    "scripts/build_search_properties.py",
    "scripts/build_record_preferred_urls.py",
    "scripts/build_catalog.py",
    "scripts/build_signature_subgraphs.py",
    # v2.0 pipeline additions (per spec §9.9):
    "scripts/build_embeddings.py",
    "scripts/build_umap.py",
    "scripts/build_clusters.py",
    "scripts/match_clusters.py",
    "scripts/name_clusters.py",
    "scripts/publish_constellation.py",
    "scripts/update_sync_state.py",
]

# Final step: copy the freshly-built JSON artifacts into app/public/ so the
# Next.js app actually serves the new catalog / subgraphs / threads registry.
# Without this, refresh updates data/ but app/public/ stays stale until
# npm run dev or npm run build triggers the prebuild copy.
NODE_STEP = "app/scripts/copy-subgraphs.mjs"


def main() -> int:
    missing = [v for v in ("NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD") if not os.environ.get(v)]
    if missing:
        print(f"error: missing env vars: {', '.join(missing)}", file=sys.stderr)
        return 2

    for step in PYTHON_STEPS:
        script = REPO_ROOT / step
        if not script.exists():
            print(f"error: {script} not found", file=sys.stderr)
            return 2
        print(f"\n▶ {step}", flush=True)
        result = subprocess.run([sys.executable, str(script)], cwd=REPO_ROOT)
        if result.returncode != 0:
            print(f"✗ {step} failed (exit {result.returncode})", file=sys.stderr)
            return result.returncode
        print(f"✓ {step}", flush=True)

    node_script = REPO_ROOT / NODE_STEP
    if not node_script.exists():
        print(f"error: {node_script} not found", file=sys.stderr)
        return 2
    print(f"\n▶ {NODE_STEP}", flush=True)
    result = subprocess.run(["node", str(node_script)], cwd=REPO_ROOT)
    if result.returncode != 0:
        print(f"✗ {NODE_STEP} failed (exit {result.returncode})", file=sys.stderr)
        return result.returncode
    print(f"✓ {NODE_STEP}", flush=True)

    print("\nAll refresh steps completed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
