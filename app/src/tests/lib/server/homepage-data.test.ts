// app/src/tests/lib/server/homepage-data.test.ts
//
// Regression for the /about vs status-bar jurisdiction-count drift:
// homepage-data.loadStatus() must use the same place_type predicate that
// about-data.loadJurisdictions() uses, otherwise the status bar will
// report a different number than the /about list shows.
import { describe, it, expect, vi } from "vitest";

vi.mock("@/lib/neo4j", () => ({
  runQuery: vi.fn(),
}));

// readFile is used for the subgraphs manifest — mock to return a stable
// error path so readManifestBuiltAt resolves to null.
vi.mock("node:fs/promises", async (importOriginal) => {
  const actual = await importOriginal<typeof import("node:fs/promises")>();
  return {
    ...actual,
    readFile: vi.fn().mockRejectedValue(new Error("no manifest")),
  };
});

import { runQuery } from "@/lib/neo4j";
import { loadStatus } from "@/lib/server/homepage-data";

const mockRunQuery = runQuery as unknown as ReturnType<typeof vi.fn>;

describe("loadStatus", () => {
  it("uses JURISDICTION_PLACE_TYPES (city, town, county) — matches /about list", async () => {
    mockRunQuery.mockResolvedValueOnce([
      {
        get: (k: string) => ({
          node_count: { toNumber: () => 100 },
          edge_count: { toNumber: () => 200 },
          jurisdiction_count: { toNumber: () => 12 },
          ingest_at: "2026-04-14T00:00:00Z",
        })[k],
      },
    ]);
    await loadStatus();
    const [cypher, params] = mockRunQuery.mock.calls[0];
    expect(cypher).toContain("place_type IN $place_types");
    expect(params).toEqual({
      place_types: ["city", "town", "county"],
    });
  });

  it("returns connected=false on query error", async () => {
    mockRunQuery.mockRejectedValueOnce(new Error("boom"));
    const status = await loadStatus();
    expect(status.connected).toBe(false);
    expect(status.jurisdiction_count).toBe(0);
  });
});
