// app/src/tests/lib/server/about-data.test.ts
import { describe, it, expect, vi } from "vitest";

vi.mock("@/lib/neo4j", () => ({
  runQuery: vi.fn(),
}));

import { runQuery } from "@/lib/neo4j";
import { loadJurisdictions } from "@/lib/server/about-data";

const mockRunQuery = runQuery as unknown as ReturnType<typeof vi.fn>;

function fakeRecord(row: Record<string, unknown>) {
  return { get: (k: string) => row[k] };
}

describe("loadJurisdictions", () => {
  it("returns { ok: true, jurisdictions } with name+type rows in query order", async () => {
    mockRunQuery.mockResolvedValueOnce([
      fakeRecord({ name: "Belvedere", type: "city" }),
      fakeRecord({ name: "Fairfax", type: "town" }),
      fakeRecord({ name: "Marin County", type: "county" }),
    ]);
    const result = await loadJurisdictions();
    expect(result).toEqual({
      ok: true,
      jurisdictions: [
        { name: "Belvedere", type: "city" },
        { name: "Fairfax", type: "town" },
        { name: "Marin County", type: "county" },
      ],
    });
  });

  it("filters to Place nodes via shared JURISDICTION_PLACE_TYPES param", async () => {
    mockRunQuery.mockResolvedValueOnce([]);
    await loadJurisdictions();
    const [cypher, params] = mockRunQuery.mock.calls[0];
    expect(cypher).toContain(":Place");
    expect(cypher).toContain("place_type IN $place_types");
    expect(cypher).toContain("ORDER BY p.name ASC");
    // Single source of truth — must agree with /about list predicate.
    expect(params).toEqual({
      place_types: ["city", "town", "county"],
    });
  });

  it("returns { ok: true, jurisdictions: [] } on a legitimately-empty result", async () => {
    mockRunQuery.mockResolvedValueOnce([]);
    const result = await loadJurisdictions();
    expect(result).toEqual({ ok: true, jurisdictions: [] });
  });

  it("returns { ok: false } on loader error — distinguishes empty from broken", async () => {
    mockRunQuery.mockRejectedValueOnce(new Error("boom"));
    const result = await loadJurisdictions();
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error).toBe("unknown");
    }
  });

  it("coerces missing type to empty string", async () => {
    mockRunQuery.mockResolvedValueOnce([fakeRecord({ name: "Ross", type: null })]);
    const result = await loadJurisdictions();
    expect(result.ok).toBe(true);
    if (result.ok) {
      expect(result.jurisdictions[0]).toEqual({ name: "Ross", type: "" });
    }
  });
});
