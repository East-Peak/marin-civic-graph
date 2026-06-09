// app/src/tests/lib/node-type-parity.test.ts
//
// M1b — exhaustive node-type SURFACE parity (TS surfaces). The gate that proves
// every *active* TS surface covers every graph node type, so adding a type
// (EconomicInterest / Membership next) is a proven-complete change, not a
// 15-surface guessing game. The expected set is the GENERATED ALL_TYPES (the
// registry mirror); production modules keep their own imports.
//
// Surface-class-aware (M1b decision doc) — each surface tested by the contract
// matching its ACTUAL shape; we do NOT reshape product code to fit a uniform test:
//   EXHAUSTIVE_MAP      Record<NodeType,…> — compile-time `Record<NodeType>` in
//                       the product PLUS a runtime "every type is a key, no extras".
//   EXHAUSTIVE_GROUPING union of groups == ALL_TYPES, each exactly once.
//   per-type switch     invoked for every type; the switch carries a `never`
//                       exhaustiveness guard (a missing case is a tsc error).
//   PREFIX_RESOLUTION   feed a REAL id for every registry prefix → RESOLVES
//                       (the M1a lesson: resolution, not list-membership).
//   SEARCHABLE_SUBSET   INDEXED_TYPES == registry searchable=true (14); Record is
//                       searchable=false BY DESIGN (the documented exception).
//   sidecar-negative    no sidecar_artifact name leaks into any exhaustive surface.
//
// CURATED_SUBSET / GENERIC_EXCLUDED surfaces are intentionally NOT forced
// exhaustive (that would create dead per-type entries) — justified one-liners:
//   * entity-facts.heroStatsForEntity (+ hero-stats.tsx): Tier-1 types only;
//     `default: return []` → Tier-2 types render no hero strip. No type breaks.
//   * entity-page.isTier1 / TIER_1_FOCUS_TYPES: curated Tier-1 set; isTier1
//     returns false (generic) for the rest.
//   * explorer-state.buildDefaultNodeFilters / DEFAULT_OFF_TYPES: every type gets
//     a flag via the ALL_TYPES loop; DEFAULT_OFF_TYPES is a curated off-by-default
//     subset, not an exhaustive map.
//   * generic slug-strip route builders (entity-loader/entity-page/api-expand/
//     search-backend/browse-queries.runBrowseQuery): build /urlSegment/{slug}
//     from a KNOWN type — no prefix→type resolution to get wrong.
//   * homepage-data.CatalogPayload.counts: Partial<Record<NodeType,number>> by
//     design (reads the baked catalog.json).

import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, it, expect } from "vitest";

import {
  ALL_TYPES,
  TYPE_BY_ID_PREFIX,
  resolveTypeFromId,
} from "@/lib/node-types.generated";
import {
  INDEXED_TYPES,
  displayNameForType,
  urlSegmentForType,
} from "@/lib/type-display";
import { EXPAND_QUOTAS } from "@/lib/explorer/expand-quotas";
import { TYPE_COLORS, TYPE_ABBREV } from "@/components/constellation/sprite-atlas";
import { columnsForType, nodeTypeForUrlSegment } from "@/lib/server/browse-queries";
import { effectiveEventDate } from "@/lib/server/entity-temporal";
import { factsForEntity, heroStatsForEntity } from "@/lib/server/entity-facts";
import { GROUPS } from "@/components/home/catalog-list";
import { FILTER_GROUPS } from "@/components/explorer/explorer-toolbar";
import { SUB_SPECS } from "@/lib/server/explorer-queries";
import { canonicalType } from "@/lib/canonical-type";
import { resolveIdAlias } from "@/lib/id-aliases";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, "..", "..", "..", "..");
const registry = JSON.parse(
  readFileSync(path.join(REPO_ROOT, "registry", "node-types.json"), "utf-8"),
);

const SORTED_TYPES = [...ALL_TYPES].sort();
const SEARCHABLE: string[] = Object.entries(registry.graph_node_types)
  .filter(([, spec]) => (spec as { searchable: boolean }).searchable)
  .map(([t]) => t);
const SIDECAR: string[] = registry.sidecar_artifacts;
const ID_PREFIXES: Record<string, string> = registry.id_prefixes;

function realIdFor(prefix: string): string {
  // A representative real id; agenda-item uses the real dated shape.
  return prefix === "agenda-item-"
    ? "agenda-item-2024-08-19-5a"
    : `${prefix}2024-sample-001`;
}

// ---------------------------------------------------------------------------
// EXHAUSTIVE_MAP — keyed Record<NodeType,…>; exactly the 22 keys, no extras.
// ---------------------------------------------------------------------------
describe("EXHAUSTIVE_MAP surfaces key every NodeType (and no extras)", () => {
  it.each([
    ["sprite-atlas TYPE_COLORS", TYPE_COLORS as Record<string, unknown>],
    ["sprite-atlas TYPE_ABBREV", TYPE_ABBREV as Record<string, unknown>],
    ["expand-quotas EXPAND_QUOTAS", EXPAND_QUOTAS as Record<string, unknown>],
  ])("%s", (_label, map) => {
    expect(Object.keys(map).sort()).toEqual(SORTED_TYPES);
  });

  it("type-display DISPLAY_NAMES (via displayNameForType) is total + non-empty", () => {
    for (const t of ALL_TYPES) expect(displayNameForType(t)).toBeTruthy();
  });

  it("browse-queries propKeyForFactLabel MAP (via columnsForType) resolves every type", () => {
    // columnsForType() indexes MAP[type] internally — an absent key would throw.
    for (const t of ALL_TYPES) expect(() => columnsForType(t)).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// per-type switch — `never`-guarded; invoke for every type.
// ---------------------------------------------------------------------------
describe("per-type switches handle every NodeType (never-guarded)", () => {
  it("entity-temporal effectiveEventDate handles every type (no default/throw)", () => {
    for (const t of ALL_TYPES) {
      const v = effectiveEventDate(t, {});
      expect(v === null || typeof v === "string").toBe(true);
    }
  });

  it("entity-facts factsForEntity returns per-type rows (not the [] default) for every type", () => {
    for (const t of ALL_TYPES) {
      const rows = factsForEntity(t, { id: `${t.toLowerCase()}-x` });
      // ≥1 per-type case row + the always-appended ID row → length > 1. The
      // never-default returns just [ID] (length 1), so this catches a fall-through.
      expect(rows.length).toBeGreaterThan(1);
      expect(rows[rows.length - 1].key).toBe("ID");
    }
  });
});

// ---------------------------------------------------------------------------
// EXHAUSTIVE_GROUPING — union == ALL_TYPES, each exactly once.
// ---------------------------------------------------------------------------
describe("EXHAUSTIVE_GROUPING surfaces cover every NodeType exactly once", () => {
  it("explorer-toolbar FILTER_GROUPS: union == ALL_TYPES, each once", () => {
    expect(FILTER_GROUPS.flatMap((g) => g.types).sort()).toEqual(SORTED_TYPES);
  });

  it("explorer-queries SUB_SPECS: exactly one expand spec per type", () => {
    expect(SUB_SPECS.map((s) => s.typeLabel).sort()).toEqual(SORTED_TYPES);
  });

  it("catalog-list GROUPS cover every type except Record (rendered in its own footer section)", () => {
    const grouped = GROUPS.flatMap((g) => g.types);
    // No duplicates among the grouped types.
    expect(grouped.length).toBe(new Set(grouped).size);
    // The ONLY type intentionally outside GROUPS is Record (documented exception).
    const missing = ALL_TYPES.filter((t) => !grouped.includes(t));
    expect(missing).toEqual(["Record"]);
  });
});

// ---------------------------------------------------------------------------
// PREFIX_RESOLUTION — real-id-per-type RESOLUTION (resolution, not membership).
// ---------------------------------------------------------------------------
describe("PREFIX_RESOLUTION surfaces resolve a real id for every registry prefix", () => {
  it("generated TYPE_BY_ID_PREFIX equals the registry id_prefixes (single source)", () => {
    expect(TYPE_BY_ID_PREFIX).toEqual(ID_PREFIXES);
  });

  it("resolveTypeFromId resolves every registry prefix (incl. agenda-item- + legacy)", () => {
    for (const [prefix, type] of Object.entries(ID_PREFIXES)) {
      expect(resolveTypeFromId(realIdFor(prefix))).toBe(type);
    }
  });

  it("canonical-type canonicalType resolves every registry prefix", () => {
    for (const [prefix, type] of Object.entries(ID_PREFIXES)) {
      expect(canonicalType([], realIdFor(prefix))).toBe(type);
    }
  });

  it("id-aliases resolveIdAlias resolves the real agenda-item- id (was stale agendaitem-)", () => {
    expect(resolveIdAlias("agenda-item-2024-08-19-5a")).toEqual({
      id: "agenda-item-2024-08-19-5a",
      type: "AgendaItem",
    });
  });

  it("browse-queries nodeTypeForUrlSegment round-trips every type's url segment", () => {
    for (const t of ALL_TYPES) {
      expect(nodeTypeForUrlSegment(urlSegmentForType(t))).toBe(t);
    }
  });
});

// ---------------------------------------------------------------------------
// SEARCHABLE_SUBSET — INDEXED_TYPES == registry searchable=true (14), Record excepted.
// ---------------------------------------------------------------------------
describe("SEARCHABLE_SUBSET == registry searchable=true set, Record exception documented", () => {
  it("INDEXED_TYPES equals the registry searchable=true set (the 14)", () => {
    expect(new Set(INDEXED_TYPES)).toEqual(new Set(SEARCHABLE));
    expect(INDEXED_TYPES).toHaveLength(14);
  });

  it("Record is searchable=false in the registry BY DESIGN (do not flip to pass)", () => {
    expect(registry.graph_node_types.Record.searchable).toBe(false);
    expect(INDEXED_TYPES).not.toContain("Record");
  });
});

// ---------------------------------------------------------------------------
// Sidecar negative — no sidecar artifact name appears as a type or surface key.
// ---------------------------------------------------------------------------
describe("sidecar artifacts never appear as a NodeType or in any exhaustive surface", () => {
  it.each(SIDECAR)("%s is absent from ALL_TYPES + every exhaustive surface", (name) => {
    expect(ALL_TYPES as readonly string[]).not.toContain(name);
    expect(Object.keys(TYPE_COLORS)).not.toContain(name);
    expect(Object.keys(TYPE_ABBREV)).not.toContain(name);
    expect(Object.keys(EXPAND_QUOTAS)).not.toContain(name);
    expect(INDEXED_TYPES as string[]).not.toContain(name);
    expect(FILTER_GROUPS.flatMap((g) => g.types) as string[]).not.toContain(name);
    expect(SUB_SPECS.map((s) => s.typeLabel) as string[]).not.toContain(name);
    expect(GROUPS.flatMap((g) => g.types) as string[]).not.toContain(name);
    expect(Object.values(TYPE_BY_ID_PREFIX) as string[]).not.toContain(name);
  });
});

// ---------------------------------------------------------------------------
// CURATED_SUBSET — every type has a tested generic/default path (no type breaks).
// ---------------------------------------------------------------------------
describe("CURATED_SUBSET surfaces keep a generic/default path for every type", () => {
  it("heroStatsForEntity returns [] for a non-Tier-1 type (the generic default)", () => {
    expect(heroStatsForEntity("Issue", {})).toEqual([]);
  });

  it("heroStatsForEntity never throws for any type (Tier-1 cases + default)", () => {
    for (const t of ALL_TYPES) expect(() => heroStatsForEntity(t, {})).not.toThrow();
  });
});
