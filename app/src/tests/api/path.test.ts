import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("@/lib/server/path-finder", () => ({
  findPath: vi.fn(),
}));

import { findPath } from "@/lib/server/path-finder";
import { GET } from "@/app/api/path/route";

const findPathMock = findPath as unknown as ReturnType<typeof vi.fn>;

describe("GET /api/path", () => {
  beforeEach(() => {
    findPathMock.mockReset();
  });

  it("400 when from is missing", async () => {
    const req = new Request("http://localhost/api/path?to=x");
    const res = await GET(req);
    expect(res.status).toBe(400);
  });

  it("400 when to is missing", async () => {
    const req = new Request("http://localhost/api/path?from=x");
    const res = await GET(req);
    expect(res.status).toBe(400);
  });

  it("400 when id exceeds length cap", async () => {
    const long = "a".repeat(501);
    const req = new Request(`http://localhost/api/path?from=${long}&to=y`);
    const res = await GET(req);
    expect(res.status).toBe(400);
  });

  it("happy path — returns the findPath result", async () => {
    findPathMock.mockResolvedValueOnce({
      found: true,
      loose_match: false,
      path: {
        nodes: [
          { id: "a", type: "Person", label: "A" },
          { id: "b", type: "Decision", label: "B" },
        ],
        edges: [{ source: "a", target: "b", type: "CAST_VOTE", weight: 1 }],
        weight: 1,
      },
    });

    const req = new Request("http://localhost/api/path?from=a&to=b");
    const res = await GET(req);
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.found).toBe(true);
    expect(body.path.weight).toBe(1);
    expect(findPathMock).toHaveBeenCalledWith("a", "b", { loose: false });
  });

  it("threads the loose=true query param into findPath options", async () => {
    findPathMock.mockResolvedValueOnce({ found: false });
    const req = new Request("http://localhost/api/path?from=a&to=b&loose=true");
    const res = await GET(req);
    expect(res.status).toBe(200);
    expect(findPathMock).toHaveBeenCalledWith("a", "b", { loose: true });
  });

  it("surfaces found: false when findPath returns no path", async () => {
    findPathMock.mockResolvedValueOnce({ found: false });
    const req = new Request("http://localhost/api/path?from=a&to=b");
    const res = await GET(req);
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body).toEqual({ found: false });
  });

  it("500 when findPath throws", async () => {
    findPathMock.mockRejectedValueOnce(new Error("neo4j down"));
    const req = new Request("http://localhost/api/path?from=a&to=b");
    const res = await GET(req);
    expect(res.status).toBe(500);
  });
});
