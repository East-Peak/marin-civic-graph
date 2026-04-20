// app/src/tests/lib/server/browse-queries.test.ts
import { describe, it, expect, vi } from "vitest";

vi.mock("@/lib/neo4j", () => ({
  runQuery: vi.fn(),
}));

import { runQuery } from "@/lib/neo4j";
import {
  buildBrowseQuery,
  columnsForType,
  clampLimit,
  nodeTypeForUrlSegment,
  runBrowseQuery,
  DEFAULT_LIMIT,
  MAX_LIMIT,
} from "@/lib/server/browse-queries";

const mockRunQuery = runQuery as unknown as ReturnType<typeof vi.fn>;

describe("buildBrowseQuery", () => {
  it("binds cursor as $cursor parameter, not string interpolation", () => {
    const { cypher, params } = buildBrowseQuery({
      type: "Person",
      cursor: "person-kate-colin",
      limit: 10,
    });
    expect(cypher).toContain("$cursor");
    expect(params.cursor).toBe("person-kate-colin");
    // Must not contain the literal id inline — that's a SQLi-adjacent smell.
    expect(cypher).not.toContain("person-kate-colin");
  });

  it("coerces undefined cursor to null so the Cypher guard lets every row through", () => {
    const { params } = buildBrowseQuery({ type: "Person", limit: 10 });
    expect(params.cursor).toBeNull();
  });

  it("applies search as a $search parameter; empty strings are treated as null", () => {
    const withSearch = buildBrowseQuery({
      type: "Person",
      search: "colin",
    });
    expect(withSearch.params.search).toBe("colin");
    expect(withSearch.cypher).toContain("toLower($search)");

    const emptySearch = buildBrowseQuery({ type: "Person", search: "   " });
    expect(emptySearch.params.search).toBeNull();
  });

  it("orders by id ASC for stable cursor pagination", () => {
    const { cypher } = buildBrowseQuery({ type: "Person", limit: 10 });
    expect(cypher).toMatch(/ORDER BY n\.id ASC/);
  });

  it("clamps limit to [1, MAX_LIMIT] with sensible defaults", () => {
    expect(clampLimit(0)).toBe(DEFAULT_LIMIT);
    expect(clampLimit(-5)).toBe(DEFAULT_LIMIT);
    expect(clampLimit(undefined)).toBe(DEFAULT_LIMIT);
    expect(clampLimit(10_000)).toBe(MAX_LIMIT);
    expect(clampLimit("25")).toBe(25);
    expect(clampLimit("not-a-number")).toBe(DEFAULT_LIMIT);
  });
});

describe("columnsForType", () => {
  it("Person: Name, then extras (Current seat, Jurisdiction) — not ID", () => {
    const cols = columnsForType("Person");
    expect(cols[0]).toEqual({ key: "search_label", label: "Name" });
    expect(cols.length).toBe(3);
    expect(cols.some((c) => c.label === "ID")).toBe(false);
    expect(cols.find((c) => c.label === "Current seat")?.key).toBe(
      "current_seat_display",
    );
    expect(cols.find((c) => c.label === "Jurisdiction")?.key).toBe(
      "jurisdiction_name",
    );
  });

  it("Decision: Name, then Decided + Institution", () => {
    const cols = columnsForType("Decision");
    expect(cols.map((c) => c.label)).toEqual([
      "Name",
      "Decided",
      "Institution",
    ]);
    expect(cols.find((c) => c.label === "Decided")?.key).toBe("decided_at");
    expect(cols.find((c) => c.label === "Institution")?.key).toBe(
      "institution_name",
    );
  });

  it("Record: falls back to first-two fact keys (Record type, Captured)", () => {
    const cols = columnsForType("Record");
    expect(cols.map((c) => c.label)).toEqual([
      "Name",
      "Record type",
      "Captured",
    ]);
  });
});

describe("nodeTypeForUrlSegment", () => {
  it("maps known URL segments to canonical NodeType", () => {
    expect(nodeTypeForUrlSegment("person")).toBe("Person");
    expect(nodeTypeForUrlSegment("money-flow")).toBe("MoneyFlow");
    expect(nodeTypeForUrlSegment("seat-service")).toBe("SeatService");
    expect(nodeTypeForUrlSegment("agenda-item")).toBe("AgendaItem");
  });

  it("returns null for unknown segments", () => {
    expect(nodeTypeForUrlSegment("unknown")).toBeNull();
    expect(nodeTypeForUrlSegment("")).toBeNull();
  });
});

describe("runBrowseQuery", () => {
  it("derives next_cursor from the last row's id when the page is full", async () => {
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
    const result = await runBrowseQuery({ type: "Person", limit: 2 });
    expect(result.rows).toHaveLength(2);
    expect(result.next_cursor).toBe("person-b");
  });

  it("returns next_cursor=null when fewer rows returned than limit", async () => {
    mockRunQuery.mockResolvedValueOnce([
      fakeRecord({
        id: "person-a",
        type: "Person",
        search_label: "Alice",
        current_seat_display: null,
        jurisdiction_name: null,
      }),
    ]);
    const result = await runBrowseQuery({ type: "Person", limit: 50 });
    expect(result.next_cursor).toBeNull();
  });

  it("computes a per-row route via urlSegmentForType + slug-suffix", async () => {
    mockRunQuery.mockResolvedValueOnce([
      fakeRecord({
        id: "person-kate-colin",
        type: "Person",
        search_label: "Kate Colin",
        current_seat_display: "Mayor",
        jurisdiction_name: "San Rafael",
      }),
    ]);
    const result = await runBrowseQuery({ type: "Person", limit: 50 });
    expect(result.rows[0].route).toBe("/person/kate-colin");
  });
});

function fakeRecord(data: Record<string, unknown>) {
  return {
    get: (k: string) => data[k],
    keys: Object.keys(data),
    length: Object.keys(data).length,
    has: (k: string) => k in data,
    toObject: () => ({ ...data }),
  };
}
