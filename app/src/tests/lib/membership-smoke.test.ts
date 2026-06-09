// app/src/tests/lib/membership-smoke.test.ts
//
// M2a smoke (TS) — the Membership branches EXECUTE. node-type-parity proves
// every surface has a Membership key; these prove the wired entries behave
// against a sample node (zero live instances is the expected state until
// M2b's 990 ingestor runs). No DB — pure functions + query builders only.

import { describe, it, expect } from "vitest";
import { factsForEntity } from "@/lib/server/entity-facts";
import { effectiveEventDate } from "@/lib/server/entity-temporal";
import {
  buildBrowseQuery,
  columnsForType,
  nodeTypeForUrlSegment,
} from "@/lib/server/browse-queries";
import { SUB_SPECS } from "@/lib/server/explorer-queries";
import { EXPAND_QUOTAS } from "@/lib/explorer/expand-quotas";
import {
  displayNameForType,
  urlSegmentForType,
  INDEXED_TYPES,
} from "@/lib/type-display";
import {
  TYPE_COLORS,
  TYPE_ABBREV,
  buildTierAAtlas,
  buildTierBAtlas,
  TIER_A_DOT_SIZES,
} from "@/components/constellation/sprite-atlas";

// Mirrors what scripts/membership_builders.build_membership_node emits
// (person_name/organization_name denormalized for facts/browse).
const SAMPLE = {
  id: "membership-jane-doe-marin-community-foundation-board-chair-2023-07-01",
  person_id: "person-jane-doe",
  organization_id: "organization-marin-community-foundation",
  person_name: "Jane Doe",
  organization_name: "Marin Community Foundation",
  role: "Board Chair",
  started_at: "2023-07-01",
  ended_at: "2025-06-30",
  confidence: 0.95,
  source_basis: "irs_990_2023",
};

describe("Membership facts rows (entity-facts)", () => {
  it("renders the predeclared fields from a sample node", () => {
    const rows = factsForEntity("Membership", SAMPLE);
    const map = Object.fromEntries(rows.map((r) => [r.key, r.value]));
    expect(map["Person"]).toBe("Jane Doe");
    expect(map["Organization"]).toBe("Marin Community Foundation");
    expect(map["Role"]).toBe("Board Chair");
    expect(map["Period"]).toBe("2023-07-01 – 2025-06-30");
    expect(map["Source"]).toBe("irs_990_2023");
    expect(rows[rows.length - 1].key).toBe("ID");
  });

  it("renders an open-ended tenure as the start date alone", () => {
    const { ended_at: _omitted, ...openEnded } = SAMPLE;
    const rows = factsForEntity("Membership", openEnded);
    const period = rows.find((r) => r.key === "Period")?.value;
    expect(period).toBe("2023-07-01");
  });
});

describe("Membership temporal (entity-temporal)", () => {
  it("returns started_at as the effective event date", () => {
    expect(effectiveEventDate("Membership", SAMPLE)).toBe("2023-07-01");
  });

  it("returns null for a node with no dates (no throw)", () => {
    expect(effectiveEventDate("Membership", {})).toBeNull();
  });
});

describe("Membership browse (browse-queries)", () => {
  it("columnsForType yields Name + Person + Organization", () => {
    expect(columnsForType("Membership")).toEqual([
      { key: "search_label", label: "Name" },
      { key: "person_name", label: "Person" },
      { key: "organization_name", label: "Organization" },
    ]);
  });

  it("buildBrowseQuery emits valid Membership cypher", () => {
    const { cypher, params } = buildBrowseQuery({ type: "Membership", limit: 10 });
    expect(cypher).toContain("(n:Membership)");
    expect(params.limit).toBeDefined(); // neo4j Integer — value checked by shared tests
  });

  it("the membership url segment round-trips", () => {
    expect(nodeTypeForUrlSegment("membership")).toBe("Membership");
  });
});

describe("Membership explorer spec + quota", () => {
  it("SUB_SPEC is well-formed and started_at-anchored", () => {
    const spec = SUB_SPECS.find((s) => s.typeLabel === "Membership");
    expect(spec).toBeDefined();
    expect(spec?.rankingKey).toBe("c.started_at DESC");
    expect(spec?.rankValueExpr).toBe("c.started_at");
    expect(spec?.eventDateExpr).toBe("c.started_at");
    expect(spec?.typePriority).toBeTypeOf("number");
  });

  it("expand quota resolves and matches SeatService (the structural analog)", () => {
    expect(EXPAND_QUOTAS.Membership).toEqual({ hop1: 2, hop2: 4, hop3: 8, hop4: 12 });
    expect(EXPAND_QUOTAS.Membership).toEqual(EXPAND_QUOTAS.SeatService);
  });
});

describe("Membership display + sprite", () => {
  it("display name, url segment, color, abbreviation are all defined", () => {
    expect(displayNameForType("Membership")).toBe("Memberships");
    expect(urlSegmentForType("Membership")).toBe("membership");
    expect(TYPE_COLORS.Membership).toMatch(/^#[0-9a-f]{6}$/i);
    expect(TYPE_ABBREV.Membership).toBe("MBR");
  });

  it("both sprite atlases build Membership sprites", () => {
    const tierA = buildTierAAtlas();
    for (const size of TIER_A_DOT_SIZES) {
      expect(tierA.spriteIndex[`Membership:${size}`]).toBeTypeOf("number");
    }
    expect(buildTierBAtlas().spriteIndex.Membership).toBeTypeOf("number");
  });
});

describe("Membership search exclusion", () => {
  it("is absent from INDEXED_TYPES (searchable=false; count stays 14)", () => {
    expect(INDEXED_TYPES).not.toContain("Membership");
    expect(INDEXED_TYPES).toHaveLength(14);
  });
});
