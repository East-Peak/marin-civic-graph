// app/src/tests/api/status.test.ts
import { describe, it, expect, vi } from "vitest";

vi.mock("@/lib/neo4j", () => ({
  runQuery: vi.fn(),
}));

import { runQuery } from "@/lib/neo4j";
import { GET } from "@/app/api/status/route";

describe("GET /api/status", () => {
  it("returns node_count, edge_count, jurisdiction_count, ingest_at", async () => {
    (runQuery as ReturnType<typeof vi.fn>).mockResolvedValueOnce([
      {
        get: (k: string) => ({
          node_count: { toNumber: () => 112431 } as unknown as number,
          edge_count: { toNumber: () => 141207 } as unknown as number,
          jurisdiction_count: { toNumber: () => 11 } as unknown as number,
          ingest_at: "2026-04-14T09:12:00Z",
        })[k],
      },
    ]);

    const res = await GET();
    const body = await res.json();
    expect(body).toEqual({
      connected: true,
      node_count: 112431,
      edge_count: 141207,
      jurisdiction_count: 11,
      ingest_at: "2026-04-14T09:12:00Z",
      subgraphs_built_at: expect.any(String),
    });
  });

  it("returns connected=false when query errors", async () => {
    (runQuery as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error("conn refused"));

    const res = await GET();
    const body = await res.json();
    expect(body.connected).toBe(false);
  });
});
