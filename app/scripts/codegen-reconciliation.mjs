// app/scripts/codegen-reconciliation.mjs
// Codegen the TS mirror of registry/reconciliation.json (the single source of
// truth for reconciliation status buckets and key-source fields).
//
// Regenerate: node app/scripts/codegen-reconciliation.mjs
// A vitest parity test fails if the committed generated file drifts.

import { readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REGISTRY_PATH = path.resolve(__dirname, "..", "..", "registry", "reconciliation.json");
const OUT_PATH = path.resolve(
  __dirname,
  "..",
  "operator-workbench-src",
  "_lib",
  "reconciliation.generated.ts",
);

function renderObjectEntries(obj, renderValue) {
  return Object.entries(obj)
    .map(([key, value]) => `  "${key}": ${renderValue(value)},`)
    .join("\n");
}

function renderStringTuple(values) {
  return values.map((value) => `  "${value}",`).join("\n");
}

function renderStringMap(obj, indent = "    ") {
  return Object.entries(obj)
    .map(([key, value]) => `${indent}"${key}": "${value}",`)
    .join("\n");
}

/** Render reconciliation.generated.ts from the parsed registry. Pure - no I/O. */
export function renderReconciliationRegistry(registry) {
  const actionabilityEntries = renderObjectEntries(
    registry.ledger_statuses,
    (spec) => `"${spec.actionability}"`,
  );
  const rejectedTuple = renderStringTuple(registry.bench_display_buckets.rejected);
  const doneTuple = renderStringTuple(registry.bench_display_buckets.done);
  const knownTuple = renderStringTuple(registry.bench_display_buckets.known_statuses);
  const keySourceEntries = renderObjectEntries(
    registry.key_sources,
    (spec) => `{
    source_id: "${spec.source_id}",
    public_key_field: "${spec.public_key_field}",
    anchor_prefix: "${spec.anchor_prefix}",
    anchor_source: "${spec.anchor_source}",
    attach_basis: "${spec.attach_basis}",
    anchor_subject_fields: {
${renderStringMap(spec.anchor_subject_fields, "      ")}
    },
  }`,
  );
  const keyFieldEntries = Object.values(registry.key_sources)
    .map((spec) => `  "${spec.source_id}": "${spec.public_key_field}",`)
    .join("\n");

  return `// AUTO-GENERATED from registry/reconciliation.json - DO NOT EDIT BY HAND.
// Regenerate: node app/scripts/codegen-reconciliation.mjs
// The registry is the single source of truth for reconciliation status/key-source mechanics.

export const LEDGER_ACTIONABILITY = {
${actionabilityEntries}
} as const;

export type LedgerStatus = keyof typeof LEDGER_ACTIONABILITY;
export type LedgerActionability = (typeof LEDGER_ACTIONABILITY)[LedgerStatus];

export const BENCH_REJECTED_STATUSES = [
${rejectedTuple}
] as const;

export const BENCH_DONE_STATUSES = [
${doneTuple}
] as const;

export const BENCH_KNOWN_STATUSES = [
${knownTuple}
] as const;

export const KEY_SOURCE_SPECS = {
${keySourceEntries}
} as const;

export const KEY_FIELD_BY_SOURCE: Record<string, string> = {
${keyFieldEntries}
};
`;
}

function main() {
  const registry = JSON.parse(readFileSync(REGISTRY_PATH, "utf-8"));
  writeFileSync(OUT_PATH, renderReconciliationRegistry(registry));
  console.log(`generated ${path.relative(process.cwd(), OUT_PATH)}`);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main();
}
