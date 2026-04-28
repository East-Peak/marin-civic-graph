"""Build embeddings for all eligible Open Marin entities.

Pipeline order: this is the FIRST data-touching step in v2.0+. Reads the
graph, synthesizes per-node text, computes synthesis hash, and embeds via
Voyage AI voyage-4 (Anthropic's official embeddings partner). Writes
embedding/_hash/_version/embedded_at directly to canonical properties
(embeddings are not staged through *_pending — only UMAP and cluster
fields are).

CLI:
  python scripts/build_embeddings.py [--full] [--dry-run]

  --full    : re-embed every eligible node regardless of hash (rare).
  --dry-run : compute hashes + count work, do not call Voyage AI or write.

Requires NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD / VOYAGE_API_KEY in env.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
from pathlib import Path

# Allow `import voyageai` here — this module is in the outbound-policy ALLOWED list.
import voyageai  # noqa: F401  (used inside main(); kept top-level so lint sees it)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from outbound_policy import is_eligible, synthesize_outbound_text, audit_log  # noqa: F401

EMBEDDING_VERSION = 1
EMBEDDING_MODEL = "voyage-4"
EMBED_DIM = 1024
BATCH_SIZE = 128


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
                        help="Compute hashes only; no Voyage AI calls or writes")
    args = parser.parse_args()

    if not args.dry_run and not os.environ.get("VOYAGE_API_KEY"):
        print("error: VOYAGE_API_KEY required (use --dry-run to skip)", file=sys.stderr)
        return 2

    from neo4j import GraphDatabase
    from canonical_type import canonical_type

    uri = os.environ["NEO4J_URI"]
    user = os.environ["NEO4J_USER"]
    password = os.environ["NEO4J_PASSWORD"]
    database = os.environ.get("NEO4J_DATABASE", "neo4j")

    driver = GraphDatabase.driver(uri, auth=(user, password))
    with driver.session(database=database) as session:
        # 1. Pull every node.
        all_rows = list(session.run(
            "MATCH (n) RETURN n.id AS id, labels(n) AS labels, properties(n) AS props"
        ))
        all_nodes = []
        for row in all_rows:
            node_id = row["id"]
            labels = row["labels"]
            props = row["props"] or {}
            t = canonical_type(labels, node_id)
            if t is None or not is_eligible(t):
                continue
            n = dict(props)
            n["id"] = node_id
            n["labels"] = labels
            n["type"] = t
            all_nodes.append(n)

        # 2. Build neighbor map (cap at top-5 eligible neighbors per node).
        neighbor_map: dict[str, list[dict]] = {n["id"]: [] for n in all_nodes}
        edge_rows = list(session.run(
            "MATCH (a)-[r]-(b) "
            "WHERE a.id IS NOT NULL AND b.id IS NOT NULL "
            "RETURN a.id AS a_id, b.id AS b_id, labels(b) AS b_labels, "
            "       b.label AS b_label, type(r) AS rel_type "
            "LIMIT 5000000"
        ))
        for row in edge_rows:
            a_id = row["a_id"]
            if a_id not in neighbor_map:
                continue
            if len(neighbor_map[a_id]) >= 5:
                continue
            b_id = row["b_id"]
            b_labels = row["b_labels"]
            b_type = canonical_type(b_labels, b_id)
            if b_type is None or not is_eligible(b_type):
                continue
            neighbor_map[a_id].append({
                "id": b_id,
                "type": b_type,
                "label": row["b_label"] or b_id,
            })

        # 3. Determine which nodes need embedding.
        work: list[tuple[dict, str, str]] = []
        for n in all_nodes:
            text = synth_text_for_node(n, neighbor_map[n["id"]])
            h = synthesis_hash(text, sorted(x["id"] for x in neighbor_map[n["id"]]))
            if args.full or needs_embed(n, current_hash=h):
                work.append((n, text, h))

        print(f"need to embed {len(work)} of {len(all_nodes)}")
        if args.dry_run:
            driver.close()
            return 0

        # 4. Batch through Voyage AI.
        client = voyageai.Client()
        for i in range(0, len(work), BATCH_SIZE):
            batch = work[i:i + BATCH_SIZE]
            texts = [t for (_, t, _) in batch]
            result = client.embed(texts, model=EMBEDDING_MODEL, input_type="document")
            embeddings = result.embeddings

            rows = [
                {"id": n["id"], "embedding": emb, "hash": h}
                for (n, _, h), emb in zip(batch, embeddings)
            ]
            session.run(
                "UNWIND $rows AS row "
                "MATCH (n {id: row.id}) "
                "SET n.embedding = row.embedding, "
                "    n.embedding_hash = row.hash, "
                "    n.embedding_version = $version, "
                "    n.embedded_at = datetime()",
                rows=rows,
                version=EMBEDDING_VERSION,
            )

            for (n, _, h) in batch:
                audit_log(
                    vendor="voyage",
                    node_id=n["id"],
                    node_type=n["type"],
                    neighbor_ids_included=[x["id"] for x in neighbor_map[n["id"]]],
                    neighbor_ids_dropped=[],
                    prompt_hash=h,
                )

            print(f"  embedded {min(i + BATCH_SIZE, len(work))}/{len(work)}")

    driver.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
