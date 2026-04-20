// app/src/tests/api/data.test.ts
import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("@/lib/neo4j", () => ({
  runQuery: vi.fn(),
}));

import { runQuery } from "@/lib/neo4j";
import { GET } from "@/app/api/data/[query]/route";

const runQueryMock = runQuery as unknown as ReturnType<typeof vi.fn>;

function fakeRecord(row: Record<string, unknown>) {
  return { get: (k: string) => row[k] };
}

function fakeNeo4jInteger(n: number) {
  return {
    toNumber: () => n,
    low: n,
    high: 0,
  };
}

function makeReq(slug: string, qs = "") {
  return new Request(`http://localhost/api/data/${slug}${qs ? `?${qs}` : ""}`);
}

function makeParams(slug: string) {
  return { params: Promise.resolve({ query: slug }) };
}

describe("GET /api/data/[query]", () => {
  beforeEach(() => {
    runQueryMock.mockReset();
  });

  it("404 for unknown slug", async () => {
    const res = await GET(makeReq("no-such-query"), makeParams("no-such-query"));
    expect(res.status).toBe(404);
  });

  it("400 when an unknown filter key is supplied", async () => {
    const res = await GET(
      makeReq("san-rafael-decisions-since-2019", "bogus_filter=1"),
      makeParams("san-rafael-decisions-since-2019"),
    );
    expect(res.status).toBe(400);
    const body = await res.json();
    expect(body.error).toMatch(/unknown filter/);
  });

  it("400 when a required filter is missing (evidence-records needs target_id)", async () => {
    const res = await GET(
      makeReq("evidence-records-supporting"),
      makeParams("evidence-records-supporting"),
    );
    expect(res.status).toBe(400);
    const body = await res.json();
    expect(body.error).toMatch(/filter required/);
  });

  it("runs the Cypher and projects rows using column keys", async () => {
    runQueryMock.mockResolvedValueOnce([
      fakeRecord({
        decided_at: "2024-03-14",
        title: "Resolution Approving Budget FY 2024-25",
        institution_name: "San Rafael City Council",
        id: "decision-sr-budget-fy2425",
      }),
    ]);
    const res = await GET(
      makeReq("san-rafael-decisions-since-2019", "from_date=2024-01-01&to_date=2024-12-31"),
      makeParams("san-rafael-decisions-since-2019"),
    );
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.slug).toBe("san-rafael-decisions-since-2019");
    expect(body.columns.length).toBeGreaterThan(0);
    expect(body.rows).toHaveLength(1);
    expect(body.rows[0].title).toBe("Resolution Approving Budget FY 2024-25");
    expect(body.rows[0].id).toBe("decision-sr-budget-fy2425");
  });

  it("coerces Neo4j Integer values in the row projection", async () => {
    runQueryMock.mockResolvedValueOnce([
      fakeRecord({
        person_name: "Kate Colin",
        seat_display: "San Rafael Mayor",
        form_700_count: fakeNeo4jInteger(4),
        form_803_count: fakeNeo4jInteger(0),
        id: "person-kate-colin",
      }),
    ]);
    const res = await GET(
      makeReq("current-officeholders-form-coverage"),
      makeParams("current-officeholders-form-coverage"),
    );
    const body = await res.json();
    expect(body.rows[0].form_700_count).toBe(4);
    expect(body.rows[0].form_803_count).toBe(0);
  });

  it("500 when the Cypher throws", async () => {
    runQueryMock.mockRejectedValueOnce(new Error("boom"));
    const consoleErr = vi.spyOn(console, "error").mockImplementation(() => {});
    const res = await GET(
      makeReq("san-rafael-decisions-since-2019"),
      makeParams("san-rafael-decisions-since-2019"),
    );
    expect(res.status).toBe(500);
    consoleErr.mockRestore();
  });

  it("applies filter defaults when the caller omits them", async () => {
    runQueryMock.mockResolvedValueOnce([]);
    await GET(
      makeReq("san-rafael-decisions-since-2019"),
      makeParams("san-rafael-decisions-since-2019"),
    );
    const call = runQueryMock.mock.calls.at(-1);
    expect(call?.[1].from_date).toBe("2019-01-01");
  });

  it("passes caller-supplied filter values through to the Cypher builder", async () => {
    runQueryMock.mockResolvedValueOnce([]);
    await GET(
      makeReq(
        "san-rafael-decisions-since-2019",
        "from_date=2024-06-01&to_date=2024-07-01&institution_id=org-san-rafael-city-council",
      ),
      makeParams("san-rafael-decisions-since-2019"),
    );
    const call = runQueryMock.mock.calls.at(-1);
    expect(call?.[1].from_date).toBe("2024-06-01");
    expect(call?.[1].to_date).toBe("2024-07-01");
    expect(call?.[1].institution_id).toBe("org-san-rafael-city-council");
  });

  it("400 when a filter value exceeds the length cap", async () => {
    const tooLong = "a".repeat(501);
    const res = await GET(
      makeReq("san-rafael-decisions-since-2019", `institution_id=${tooLong}`),
      makeParams("san-rafael-decisions-since-2019"),
    );
    expect(res.status).toBe(400);
  });

  // -------------------------------------------------------------------------
  // Fix 13: apply defaults BEFORE enforcing required filters
  // -------------------------------------------------------------------------

  it("fix 13: a required filter with a declared default is satisfied via the default (no 400)", async () => {
    // agreements-and-amendments-for-project has `project_id` required AND
    // declares a default of "project-san-rafael-350-merrydale-interim-shelter".
    // Pre-fix, omitting project_id returned 400 because required was checked
    // before defaults were applied. The page works because it applies
    // defaults client-side — this test pins parity.
    runQueryMock.mockResolvedValueOnce([]);
    const res = await GET(
      makeReq("agreements-and-amendments-for-project"),
      makeParams("agreements-and-amendments-for-project"),
    );
    expect(res.status).toBe(200);
    const call = runQueryMock.mock.calls.at(-1);
    expect(call?.[1].project_id).toBe(
      "project-san-rafael-350-merrydale-interim-shelter",
    );
  });
});
