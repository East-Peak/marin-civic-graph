// app/src/tests/api/catalog.test.ts
import { describe, it, expect, vi } from "vitest";

vi.mock("@/lib/neo4j", () => ({
  runQuery: vi.fn(),
}));

import { runQuery } from "@/lib/neo4j";
import { GET } from "@/app/api/catalog/route";

describe("GET /api/catalog", () => {
  it("returns counts keyed by NodeType", async () => {
    (runQuery as ReturnType<typeof vi.fn>).mockResolvedValueOnce([
      {
        get: (k: string) =>
          ({
            label: "Person",
            count: { toNumber: () => 2184 } as unknown as number,
          })[k],
      },
      {
        get: (k: string) =>
          ({
            label: "Decision",
            count: { toNumber: () => 1453 } as unknown as number,
          })[k],
      },
    ]);

    const res = await GET();
    const body = await res.json();
    expect(body.counts.Person).toBe(2184);
    expect(body.counts.Decision).toBe(1453);
  });
});
