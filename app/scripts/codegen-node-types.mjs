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
  // Registry id_prefixes — incl. the real multi-hyphen `agenda-item-` and the
  // legacy aliases (actor-/inst-/eid-). This is the ONE prefix→type map for TS;
  // id-aliases.ts + data-table.tsx route through resolveTypeFromId rather than
  // hand-rolling their own (which is how the `agendaitem-` / first-hyphen-split
  // bugs crept in).
  const prefixEntries = Object.entries(registry.id_prefixes)
    .map(([prefix, type]) => `  "${prefix}": "${type}",`)
    .join("\n");
  return `// AUTO-GENERATED from registry/node-types.json — DO NOT EDIT BY HAND.
// Regenerate: node app/scripts/codegen-node-types.mjs
// The registry is the single source of truth for the node-type contract.

export const ALL_TYPES = [
${tuple}
] as const;

export type NodeType = (typeof ALL_TYPES)[number];

// Canonical id-prefix → NodeType, derived from registry id_prefixes. Includes
// the real \`agenda-item-\` prefix and the legacy aliases (actor-/inst-/eid-).
export const TYPE_BY_ID_PREFIX: Record<string, NodeType> = {
${prefixEntries}
};

// Longest-prefix-first so a strict-prefix pair (e.g. a hypothetical \`agenda-\`
// vs \`agenda-item-\`) can never mis-resolve. Today's registry has no such pair,
// but sorting makes the resolver robust to future additions regardless of map
// key order.
const _PREFIXES_LONGEST_FIRST = Object.keys(TYPE_BY_ID_PREFIX).sort(
  (a, b) => b.length - a.length,
);

/**
 * Resolve a node's canonical NodeType from its id prefix. The single shared
 * id-prefix resolver for the app — returns null for an id with no known prefix.
 */
export function resolveTypeFromId(id: string): NodeType | null {
  for (const prefix of _PREFIXES_LONGEST_FIRST) {
    if (id.startsWith(prefix)) return TYPE_BY_ID_PREFIX[prefix];
  }
  return null;
}
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
