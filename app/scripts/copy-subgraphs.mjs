// app/scripts/copy-subgraphs.mjs
// Copies data/projected/graph-v1/signature-subgraphs/* into app/public/subgraphs/
// so Next.js serves them as static assets. Runs automatically via prebuild.

import { cp, mkdir, rm } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.resolve(__dirname, "..", "..", "data", "projected", "graph-v1", "signature-subgraphs");
const DEST = path.resolve(__dirname, "..", "public", "subgraphs");

async function main() {
  await rm(DEST, { recursive: true, force: true });
  await mkdir(DEST, { recursive: true });
  await cp(SRC, DEST, { recursive: true });
  console.log(`copied subgraph bundles → ${DEST}`);

  // Also copy currently-tracking.yaml for static serving.
  const REGISTRY_YAML = path.resolve(__dirname, "..", "..", "registry", "currently-tracking.yaml");
  const REGISTRY_DEST = path.resolve(__dirname, "..", "public", "currently-tracking.yaml");
  await cp(REGISTRY_YAML, REGISTRY_DEST);
  console.log(`copied threads registry → ${REGISTRY_DEST}`);

  // Catalog counts — baked bundle per spec §3.7 (not a live query per request).
  const CATALOG_SRC = path.resolve(__dirname, "..", "..", "data", "projected", "graph-v1", "catalog.json");
  const CATALOG_DEST = path.resolve(__dirname, "..", "public", "catalog.json");
  await cp(CATALOG_SRC, CATALOG_DEST);
  console.log(`copied catalog → ${CATALOG_DEST}`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
