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

  it("unwraps Neo4j Integer wrapper for umap_version", async () => {
    // Neo4j JS driver returns Integer instances with toNumber(); they
    // serialize to JSON as {low, high} if not unwrapped first. The
    // rehearsal report (2026-04-29) caught this shape leaking to clients.
    const neo4jInt = { low: 14, high: 0, toNumber: () => 14 };
    (runQuery as ReturnType<typeof vi.fn>).mockResolvedValueOnce([
      {
        get: (k: string) => ({
          version_id: "2026-04-29-2014-rehearsal-001",
          umap_version: neo4jInt,
          blob_url: "constellation-2026-04-29-2014-rehearsal-001.json.gz",
          built_at: "2026-04-29T20:14:00Z",
        })[k],
      },
    ]);
    const req = new Request("http://localhost/api/constellation-manifest", {
      headers: { "x-forwarded-for": "127.0.0.1" },
    });
    const res = await GET(req);
    const body = await res.json();
    expect(body.umap_version).toBe(14);
  });

  it("sources built_at from s.updated_at (publish writes updated_at)", async () => {
    // Rehearsal 2026-04-29 returned built_at=null because PROMOTE_CYPHER
    // step 4 sets s.updated_at, never s.built_at. Manifest must read the
    // column publish actually writes.
    (runQuery as ReturnType<typeof vi.fn>).mockResolvedValueOnce([
      {
        get: (k: string) => ({
          version_id: "v",
          umap_version: 1,
          blob_url: "b",
          built_at: "2026-04-29T20:14:00Z",
        })[k],
      },
    ]);
    const req = new Request("http://localhost/api/constellation-manifest", {
      headers: { "x-forwarded-for": "127.0.0.1" },
    });
    await GET(req);
    const cypher = (runQuery as ReturnType<typeof vi.fn>).mock.calls[0][0] as string;
    expect(cypher).toContain("toString(s.updated_at) AS built_at");
    expect(cypher).not.toContain("s.built_at");
  });

  it("returns size_gz from _SyncState (Neo4j Integer unwrapped)", async () => {
    // Rehearsal 2026-04-29 finding #4: size_gz was hardcoded to 0.
    // Now publish writes s.size_gz; route must select and unwrap it.
    const sizeGz = { low: 8456789, high: 0, toNumber: () => 8456789 };
    (runQuery as ReturnType<typeof vi.fn>).mockResolvedValueOnce([
      {
        get: (k: string) => ({
          version_id: "v",
          umap_version: 1,
          blob_url: "b",
          built_at: "2026-04-29T20:14:00Z",
          size_gz: sizeGz,
        })[k],
      },
    ]);
    const req = new Request("http://localhost/api/constellation-manifest", {
      headers: { "x-forwarded-for": "127.0.0.1" },
    });
    const res = await GET(req);
    const body = await res.json();
    expect(body.size_gz).toBe(8456789);
    const cypher = (runQuery as ReturnType<typeof vi.fn>).mock.calls[0][0] as string;
    expect(cypher).toContain("s.size_gz AS size_gz");
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
