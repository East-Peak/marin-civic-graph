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
  it("returns name+type rows in query order", async () => {
    mockRunQuery.mockResolvedValueOnce([
      fakeRecord({ name: "Belvedere", type: "city" }),
      fakeRecord({ name: "Fairfax", type: "town" }),
      fakeRecord({ name: "Marin County", type: "county" }),
    ]);
    const rows = await loadJurisdictions();
    expect(rows).toEqual([
      { name: "Belvedere", type: "city" },
      { name: "Fairfax", type: "town" },
      { name: "Marin County", type: "county" },
    ]);
  });

  it("filters to Place nodes where place_type is city/town/county", async () => {
    mockRunQuery.mockResolvedValueOnce([]);
    await loadJurisdictions();
    const [cypher] = mockRunQuery.mock.calls[0];
    expect(cypher).toContain(":Place");
    expect(cypher).toContain("place_type IN ['city', 'town', 'county']");
    expect(cypher).toContain("ORDER BY p.name ASC");
  });

  it("returns [] when the query throws (graceful fallback)", async () => {
    mockRunQuery.mockRejectedValueOnce(new Error("boom"));
    const rows = await loadJurisdictions();
    expect(rows).toEqual([]);
  });

  it("coerces missing type to empty string", async () => {
    mockRunQuery.mockResolvedValueOnce([fakeRecord({ name: "Ross", type: null })]);
    const rows = await loadJurisdictions();
    expect(rows[0]).toEqual({ name: "Ross", type: "" });
  });
});
