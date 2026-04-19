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
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
