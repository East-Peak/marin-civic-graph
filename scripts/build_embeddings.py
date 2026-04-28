"""Build embeddings for all eligible Open Marin entities.

Pipeline order: this is the FIRST data-touching step in v2.0+. Reads the
graph, synthesizes per-node text, computes synthesis hash, and embeds via
OpenAI text-embedding-3-small. Writes embedding/_hash/_version/embedded_at
directly to canonical properties (embeddings are not staged through
*_pending — only UMAP and cluster fields are).

CLI:
  python scripts/build_embeddings.py [--full] [--dry-run]

  --full    : re-embed every eligible node regardless of hash (rare).
  --dry-run : compute hashes + count work, do not call OpenAI or write.

Requires NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD / OPENAI_API_KEY in env.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
from pathlib import Path

# Allow `import openai` here — this module is in the outbound-policy ALLOWED list.
import openai  # noqa: F401  (used inside main(); kept top-level so lint sees it)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from outbound_policy import is_eligible, synthesize_outbound_text, audit_log  # noqa: F401

EMBEDDING_VERSION = 1
EMBEDDING_MODEL = "text-embedding-3-small"
EMBED_DIM = 1536
BATCH_SIZE = 100


def synth_text_for_node(node: dict, neighbors: list[dict]) -> str:
    """Wrap outbound_policy.synthesize_outbound_text for the embedding context."""
    return synthesize_outbound_text(node, neighbors)


def synthesis_hash(text: str, neighbor_ids: list[str]) -> str:
    """sha256 over the exact synthesis text plus sorted neighbor IDs.

    Same hash → same outbound payload → no re-embed needed. Different
    neighbor IDs (edge changes) → different hash → re-embed.
    """
    payload = text + "\n" + "|".join(sorted(neighbor_ids))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def needs_embed(node: dict, current_hash: str) -> bool:
    """True iff this node requires re-embedding."""
    if not node.get("embedding_hash"):
        return True
    if "embedding_version" in node and node["embedding_version"] != EMBEDDING_VERSION:
        return True
    return node["embedding_hash"] != current_hash


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", action="store_true",
                        help="Re-embed every eligible node regardless of hash")
    parser.add_argument("--dry-run", action="store_true",
                        help="Compute hashes only; no OpenAI calls or writes")
    args = parser.parse_args()

    if not args.dry_run and not os.environ.get("OPENAI_API_KEY"):
        print("error: OPENAI_API_KEY required (use --dry-run to skip)", file=sys.stderr)
        return 2

    # Body filled in during Task 16 rehearsal so we don't burn paid embeddings
    # before the surrounding pipeline (UMAP, clusters, naming, publish) is in
    # place. The unit-tested surface (synth_text, synthesis_hash, needs_embed)
    # is complete.
    print("build_embeddings.main() is a stub at this commit (Task 16 fills it in)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
