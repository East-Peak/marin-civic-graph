import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("@/lib/neo4j", () => ({
  runQuery: vi.fn(),
}));

vi.mock("@/lib/blob", () => ({
  signBlobUrl: vi.fn(async (path: string, _ttl: number) =>
    `https://blob.vercel-storage.com/${path}?sig=fake&exp=1234`),
}));

import { runQuery } from "@/lib/neo4j";
import { GET } from "@/app/api/constellation-manifest/route";

describe("GET /api/constellation-manifest", () => {
  beforeEach(() => {
    (runQuery as ReturnType<typeof vi.fn>).mockReset();
  });

  it("returns 401 if request fails IP allowlist", async () => {
    const req = new Request("http://localhost/api/constellation-manifest", {
      headers: { "x-forwarded-for": "8.8.8.8" },
    });
    const res = await GET(req);
    expect(res.status).toBe(401);
  });

  it("returns the active manifest with signed URL when allowed", async () => {
    (runQuery as ReturnType<typeof vi.fn>).mockResolvedValueOnce([
      {
        get: (k: string) => ({
          version_id: "2026-04-27-rehearsal-001",
          umap_version: 14,
          blob_url: "constellation-2026-04-27-rehearsal-001.json.gz",
          built_at: "2026-04-27T08:00:00Z",
        })[k],
      },
    ]);
    const req = new Request("http://localhost/api/constellation-manifest", {
      headers: { "x-forwarded-for": "127.0.0.1" },
    });
    const res = await GET(req);
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.schema_version).toBe(1);
    expect(body.current_version).toBe("2026-04-27-rehearsal-001");
    expect(body.umap_version).toBe(14);
    expect(body.signed_url).toContain("constellation-2026-04-27-rehearsal-001.json.gz");
    expect(typeof body.expires_at).toBe("string");
  });

  it("returns 503 when no manifest exists yet (pre-first-publish)", async () => {
    (runQuery as ReturnType<typeof vi.fn>).mockResolvedValueOnce([]);
    const req = new Request("http://localhost/api/constellation-manifest", {
      headers: { "x-forwarded-for": "127.0.0.1" },
    });
    const res = await GET(req);
    expect(res.status).toBe(503);
  });
});
