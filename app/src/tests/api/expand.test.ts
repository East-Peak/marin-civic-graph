import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("@/lib/neo4j", () => ({
  runQuery: vi.fn(),
}));

import { runQuery } from "@/lib/neo4j";
import { GET } from "@/app/api/expand/route";

const runQueryMock = runQuery as unknown as ReturnType<typeof vi.fn>;

function fakeRecord(row: Record<string, unknown>) {
  return { get: (k: string) => row[k] };
}

describe("GET /api/expand", () => {
  beforeEach(() => {
    runQueryMock.mockReset();
  });

  it("400 when focus is missing", async () => {
    const req = new Request("http://localhost/api/expand?hop=1");
    const res = await GET(req);
    expect(res.status).toBe(400);
  });

  it("defaults hop to 1 when missing", async () => {
    runQueryMock.mockResolvedValue([]);
    const req = new Request("http://localhost/api/expand?focus=x");
    const res = await GET(req);
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.cap).toBe(20); // hop=1
  });

  it("400 when hop is out of range", async () => {
    for (const hop of ["0", "5", "-1", "abc", "1.5"]) {
      const req = new Request(`http://localhost/api/expand?focus=x&hop=${hop}`);
      const res = await GET(req);
      expect(res.status, `hop=${hop}`).toBe(400);
    }
  });

  it("accepts hop=1, hop=2, hop=3, hop=4", async () => {
    runQueryMock.mockResolvedValue([]);
    for (const hop of [1, 2, 3, 4]) {
      const req = new Request(`http://localhost/api/expand?focus=x&hop=${hop}`);
      const res = await GET(req);
      expect(res.status, `hop=${hop}`).toBe(200);
    }
  });

  it("projects query rows into {id, type, label, route, ring}", async () => {
    // First runQuery call = expand nodes; second call = edges-among-selected.
    runQueryMock
      .mockResolvedValueOnce([
        fakeRecord({
          id: "person-kate-colin",
          labels: ["Person"],
          label: "Kate Colin",
          ring: 1,
        }),
        fakeRecord({
          id: "decision-a",
          labels: ["Decision"],
          label: "Decision A",
          ring: 2,
        }),
      ])
      .mockResolvedValueOnce([]);

    const req = new Request("http://localhost/api/expand?focus=x&hop=2");
    const res = await GET(req);
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.nodes).toHaveLength(2);
    expect(body.nodes[0]).toMatchObject({
      id: "person-kate-colin",
      type: "Person",
      label: "Kate Colin",
      route: "/person/kate-colin",
      ring: 1,
    });
    expect(body.new_count).toBe(2);
    expect(body.cap).toBe(80); // hop=2
  });

  it("returns cap matching aggregate-caps table", async () => {
    runQueryMock.mockResolvedValue([]);
    const caps: Record<string, number> = {};
    for (const hop of [1, 2, 3, 4]) {
      const req = new Request(`http://localhost/api/expand?focus=x&hop=${hop}`);
      const res = await GET(req);
      const body = await res.json();
      caps[String(hop)] = body.cap;
    }
    expect(caps).toEqual({ "1": 20, "2": 80, "3": 160, "4": 240 });
  });

  it("fetches edges among focus + already_loaded + new nodes", async () => {
    runQueryMock
      .mockResolvedValueOnce([
        fakeRecord({
          id: "person-a",
          labels: ["Person"],
          label: "A",
          ring: 1,
        }),
      ])
      .mockResolvedValueOnce([
        fakeRecord({
          source: "person-a",
          target: "focus-x",
          rel_type: "CAST_VOTE",
          start_id: "person-a",
          end_id: "focus-x",
        }),
      ]);

    const req = new Request(
      "http://localhost/api/expand?focus=focus-x&hop=1&already_loaded=decision-b",
    );
    const res = await GET(req);
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.edges).toHaveLength(1);
    expect(body.edges[0]).toMatchObject({
      source: "person-a",
      target: "focus-x",
      type: "CAST_VOTE",
      style: "governance",
    });

    // Second call = edges-among-selected — its params.ids is the union.
    const [, edgeParams] = runQueryMock.mock.calls[1];
    expect(new Set(edgeParams.ids as string[])).toEqual(
      new Set(["focus-x", "decision-b", "person-a"]),
    );
  });

  it("skips edge query when the union has < 2 ids", async () => {
    runQueryMock.mockResolvedValueOnce([]); // nodes query returns nothing
    const req = new Request("http://localhost/api/expand?focus=focus-x&hop=1");
    const res = await GET(req);
    expect(res.status).toBe(200);
    expect(runQueryMock).toHaveBeenCalledTimes(1);
  });

  it("filters the edges-among-selected whitelist by excluded_edge_types", async () => {
    runQueryMock
      .mockResolvedValueOnce([
        fakeRecord({ id: "a", labels: ["Person"], label: "A", ring: 1 }),
      ])
      .mockResolvedValueOnce([]);

    const req = new Request(
      "http://localhost/api/expand?focus=f&hop=1&excluded_edge_types=CAST_VOTE,DECIDED_BY",
    );
    await GET(req);

    const [, edgeParams] = runQueryMock.mock.calls[1];
    const whitelist = edgeParams.whitelist as string[];
    expect(whitelist).not.toContain("CAST_VOTE");
    expect(whitelist).not.toContain("DECIDED_BY");
    expect(whitelist).toContain("AT_MEETING");
  });

  it("drops unknown node types from excluded_node_types", async () => {
    runQueryMock.mockResolvedValue([]);
    const req = new Request(
      "http://localhost/api/expand?focus=f&hop=1&excluded_node_types=Person,NotAType",
    );
    const res = await GET(req);
    expect(res.status).toBe(200); // doesn't throw on bogus type
    // Sub-query for Person is skipped but NotAType doesn't blow anything up.
    const [cypher] = runQueryMock.mock.calls[0];
    expect(cypher).not.toContain("(c:Person)");
    expect(cypher).toContain("(c:Decision)");
  });

  it("500 when the expand query throws", async () => {
    runQueryMock.mockRejectedValueOnce(new Error("neo4j down"));
    const req = new Request("http://localhost/api/expand?focus=f&hop=1");
    const res = await GET(req);
    expect(res.status).toBe(500);
  });
});
