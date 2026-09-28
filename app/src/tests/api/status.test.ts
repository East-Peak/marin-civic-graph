import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("@/lib/neo4j", () => ({
  runQuery: vi.fn(),
}));

import { runQuery } from "@/lib/neo4j";
import { GET } from "@/app/api/status/route";


// These tests exercise the legacy live-Cypher branch (mocked runQuery), which
// must be opted into explicitly now that the substrate is the default. They
// go away with the live branches in tranche T2.
beforeEach(() => {
  process.env.SERVING_BACKEND = "live";
});

describe("GET /api/status", () => {
  it("returns node/edge/jurisdiction counts and ingest_at from live query", async () => {
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
    expect(body).toMatchObject({
      connected: true,
      node_count: 112431,
      edge_count: 141207,
      jurisdiction_count: 11,
      ingest_at: "2026-04-14T09:12:00Z",
    });
  });

  it("returns connected=false when query errors", async () => {
    (runQuery as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error("conn refused"));

    const res = await GET();
    const body = await res.json();
    expect(body.connected).toBe(false);
  });
});
