// app/scripts/codegen-edge-properties.mjs
// Codegen the TS mirror of the relationship-property allowlist from registry/edge-properties.json (shared with the
// bake: scripts/public_edge_props.py). `as const` keeps the vote vocabulary a literal union. The live loader builds
// Cypher from these names, so they are held to identifier shapes here (and again in Python).
//
// Regenerate: node app/scripts/codegen-edge-properties.mjs
// edge-props.test.ts fails if the committed generated file drifts from the registry.

import { readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REGISTRY_PATH = path.resolve(__dirname, "..", "..", "registry", "edge-properties.json");
const OUT_PATH = path.resolve(__dirname, "..", "src", "lib", "edge-properties.generated.ts");

const REL_NAME = /^[A-Z][A-Z_]*$/;
const PROP_NAME = /^[a-z][a-z_]*$/;
const VALUE = /^[a-z][a-z_-]*$/;

/** Render edge-properties.generated.ts from the parsed registry. Pure — no I/O. Throws on a malformed registry. */
export function renderEdgeProperties(registry) {
  const lines = [];
  for (const [rel, props] of Object.entries(registry.relationships)) {
    if (!REL_NAME.test(rel)) throw new Error(`edge-properties: bad relationship name ${JSON.stringify(rel)}`);
    lines.push(`  ${rel}: {`);
    for (const [prop, values] of Object.entries(props)) {
      if (!PROP_NAME.test(prop)) throw new Error(`edge-properties: bad property name ${JSON.stringify(prop)}`);
      if (
        !Array.isArray(values) ||
        values.length === 0 ||
        !values.every((value) => typeof value === "string" && VALUE.test(value)) ||
        new Set(values).size !== values.length
      ) {
        throw new Error(`edge-properties: ${rel}.${prop} needs a list of distinct lowercase words`);
      }
      lines.push(`    ${prop}: [${values.map((value) => `"${value}"`).join(", ")}],`);
    }
    lines.push("  },");
  }
  return `// AUTO-GENERATED from registry/edge-properties.json — DO NOT EDIT BY HAND.
// Regenerate: node app/scripts/codegen-edge-properties.mjs
// The registry is the single source of truth for which relationship properties are public.

export const EDGE_PROPERTY_ALLOWLIST = {
${lines.join("\n")}
} as const;
`;
}

function main() {
  const registry = JSON.parse(readFileSync(REGISTRY_PATH, "utf-8"));
  writeFileSync(OUT_PATH, renderEdgeProperties(registry));
  console.log(`generated ${path.relative(process.cwd(), OUT_PATH)}`);
}

// Run main() only when invoked directly, not when imported by the parity test.
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main();
}
