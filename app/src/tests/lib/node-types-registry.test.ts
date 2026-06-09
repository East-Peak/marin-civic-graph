// app/src/tests/lib/node-types-registry.test.ts
// M1a — the TS mirror of registry/node-types.json is codegen'd (as const) and
// parity-checked against the registry + the hand-maintained type surfaces.
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, it, expect } from "vitest";
import { ALL_TYPES as GENERATED_ALL_TYPES } from "@/lib/node-types.generated";
import { ALL_TYPES as DISPLAY_ALL_TYPES } from "@/lib/type-display";
import { canonicalType } from "@/lib/canonical-type";
import { renderNodeTypes } from "../../../scripts/codegen-node-types.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, "..", "..", "..", "..");
const REGISTRY_PATH = path.join(REPO_ROOT, "registry", "node-types.json");
const GENERATED_PATH = path.join(REPO_ROOT, "app", "src", "lib", "node-types.generated.ts");

const registry = JSON.parse(readFileSync(REGISTRY_PATH, "utf-8"));
const registryTypes = Object.keys(registry.graph_node_types);

describe("node-types codegen mirror", () => {
  it("generated ALL_TYPES equals the registry graph node types (order + membership)", () => {
    expect([...GENERATED_ALL_TYPES]).toEqual(registryTypes);
    expect(GENERATED_ALL_TYPES).toHaveLength(22);
  });

  it("the committed generated file is up to date (not stale vs registry)", () => {
    const onDisk = readFileSync(GENERATED_PATH, "utf-8");
    expect(onDisk).toBe(renderNodeTypes(registry));
  });

  it("type-display ALL_TYPES is in parity with the generated set", () => {
    expect([...DISPLAY_ALL_TYPES]).toEqual([...GENERATED_ALL_TYPES]);
  });
});

describe("canonicalType prefix resolution (registry parity)", () => {
  it("resolves the real agenda-item- prefix to AgendaItem (the latent bug)", () => {
    expect(canonicalType([], "agenda-item-2024-08-19-5a")).toBe("AgendaItem");
  });

  it("resolves every registry id prefix to its mapped type", () => {
    for (const [prefix, type] of Object.entries(registry.id_prefixes)) {
      expect(canonicalType([], `${prefix}sample-001`)).toBe(type);
    }
  });

  it("still resolves the legacy aliases", () => {
    expect(canonicalType([], "actor-kate-colin")).toBe("Person");
    expect(canonicalType([], "inst-san-rafael")).toBe("Organization");
    expect(canonicalType([], "eid-12345")).toBe("Filing");
  });
});
