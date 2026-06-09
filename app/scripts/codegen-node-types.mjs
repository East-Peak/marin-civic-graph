// app/scripts/codegen-node-types.mjs
// Codegen the TS mirror of the node-type contract from registry/node-types.json
// (the single source of truth). Emits app/src/lib/node-types.generated.ts with
// ALL_TYPES `as const` + the NodeType union. A direct JSON import would infer a
// broad `string[]` and weaken Record<NodeType, ...> exhaustiveness — the
// `as const` literal tuple is what makes the union sound.
//
// Regenerate: node app/scripts/codegen-node-types.mjs
// A vitest parity test (node-types-registry.test.ts) fails if the committed
// generated file drifts from the registry.

import { readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REGISTRY_PATH = path.resolve(__dirname, "..", "..", "registry", "node-types.json");
const OUT_PATH = path.resolve(__dirname, "..", "src", "lib", "node-types.generated.ts");

/** Render node-types.generated.ts from the parsed registry. Pure — no I/O. */
export function renderNodeTypes(registry) {
  const types = Object.keys(registry.graph_node_types);
  const tuple = types.map((t) => `  "${t}",`).join("\n");
  return `// AUTO-GENERATED from registry/node-types.json — DO NOT EDIT BY HAND.
// Regenerate: node app/scripts/codegen-node-types.mjs
// The registry is the single source of truth for the node-type contract.

export const ALL_TYPES = [
${tuple}
] as const;

export type NodeType = (typeof ALL_TYPES)[number];
`;
}

function main() {
  const registry = JSON.parse(readFileSync(REGISTRY_PATH, "utf-8"));
  writeFileSync(OUT_PATH, renderNodeTypes(registry));
  console.log(`generated ${path.relative(process.cwd(), OUT_PATH)}`);
}

// Run main() only when invoked directly (node app/scripts/codegen-node-types.mjs),
// not when imported by the parity test.
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main();
}
