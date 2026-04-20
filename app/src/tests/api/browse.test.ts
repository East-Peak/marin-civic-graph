// app/src/tests/api/browse.test.ts
import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("@/lib/neo4j", () => ({
  runQuery: vi.fn(),
}));

import { runQuery } from "@/lib/neo4j";
import { GET } from "@/app/api/browse/[type]/route";

const mockRunQuery = runQuery as unknown as ReturnType<typeof vi.fn>;

function fakeRecord(data: Record<string, unknown>) {
  return {
    get: (k: string) => data[k],
    keys: Object.keys(data),
    length: Object.keys(data).length,
    has: (k: string) => k in data,
    toObject: () => ({ ...data }),
  };
}

function invoke(url: string, type: string) {
  return GET(new Request(url), { params: Promise.resolve({ type }) });
}

describe("GET /api/browse/[type]", () => {
  beforeEach(() => {
    mockRunQuery.mockReset();
  });

  it("400 when the type is unknown", async () => {
    const res = await invoke("http://localhost/api/browse/unknown", "unknown");
    expect(res.status).toBe(400);
  });

  it("rejects limit > 200", async () => {
    const res = await invoke("http://localhost/api/browse/person?limit=500", "person");
    expect(res.status).toBe(400);
  });

  it("rejects negative / NaN limit", async () => {
    const negRes = await invoke("http://localhost/api/browse/person?limit=-1", "person");
    expect(negRes.status).toBe(400);
    const nanRes = await invoke("http://localhost/api/browse/person?limit=abc", "person");
    expect(nanRes.status).toBe(400);
  });

  it("returns rows + next_cursor for a full page", async () => {
    mockRunQuery.mockResolvedValueOnce([
      fakeRecord({
        id: "person-a",
        type: "Person",
        search_label: "Alice",
        current_seat_display: "Mayor",
        jurisdiction_name: "Ross",
      }),
      fakeRecord({
        id: "person-b",
        type: "Person",
        search_label: "Bob",
        current_seat_display: null,
        jurisdiction_name: "Ross",
      }),
    ]);
    const res = await invoke("http://localhost/api/browse/person?limit=2", "person");
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.type).toBe("Person");
    expect(body.rows).toHaveLength(2);
    expect(body.next_cursor).toBe("person-b");
    expect(body.columns[0]).toEqual({ key: "search_label", label: "Name" });
  });

  it("returns next_cursor=null when the page is not full", async () => {
    mockRunQuery.mockResolvedValueOnce([
      fakeRecord({
        id: "decision-x",
        type: "Decision",
        search_label: "X",
        decided_at: "2024-01-01",
        institution_name: "SR",
      }),
    ]);
    const res = await invoke(
      "http://localhost/api/browse/decision?limit=50",
      "decision",
    );
    const body = await res.json();
    expect(body.next_cursor).toBeNull();
  });

  it("passes cursor through to the query runner", async () => {
    mockRunQuery.mockResolvedValueOnce([]);
    await invoke(
      "http://localhost/api/browse/person?cursor=person-abc&limit=10",
      "person",
    );
    const lastCall = mockRunQuery.mock.calls.at(-1);
    expect(lastCall?.[1].cursor).toBe("person-abc");
  });

  it("supports URL-segment aliases like money-flow -> MoneyFlow", async () => {
    mockRunQuery.mockResolvedValueOnce([]);
    const res = await invoke(
      "http://localhost/api/browse/money-flow?limit=5",
      "money-flow",
    );
    const body = await res.json();
    expect(body.type).toBe("MoneyFlow");
  });
});
