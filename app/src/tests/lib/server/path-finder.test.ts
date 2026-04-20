import { describe, it, expect, vi, beforeEach } from "vitest";

vi.mock("@/lib/neo4j", () => ({
  runQuery: vi.fn(),
}));

import { runQuery } from "@/lib/neo4j";
import {
  findPath,
  scorePath,
  EDGE_WEIGHTS,
  LOOSE_ONLY_EDGES,
  EXCLUDED_INTERMEDIATE_TYPES,
} from "@/lib/server/path-finder";

const runQueryMock = runQuery as unknown as ReturnType<typeof vi.fn>;

/** Build a mock Neo4j record that exposes `.get(col)`.
 * Defaults `node_event_dates` to all-null so legacy tests don't need to supply
 * dates (they're exercising weight math, not the timeline fix). */
function fakeRecord(row: {
  node_ids: string[];
  node_types: string[];
  node_labels: string[];
  edge_types: string[];
  node_event_dates?: Array<string | null>;
}) {
  const withDates = {
    ...row,
    node_event_dates:
      row.node_event_dates ?? row.node_ids.map(() => null),
  };
  return {
    get: (k: string) => (withDates as Record<string, unknown>)[k],
  };
}

describe("EDGE_WEIGHTS table", () => {
  it("maps weight-1 edges to 1", () => {
    expect(EDGE_WEIGHTS.CAST_VOTE).toBe(1);
    expect(EDGE_WEIGHTS.DECIDED_BY).toBe(1);
    expect(EDGE_WEIGHTS.PARTY_TO).toBe(1);
  });

  it("maps weight-2 money + amends edges", () => {
    expect(EDGE_WEIGHTS.FROM_SOURCE).toBe(2);
    expect(EDGE_WEIGHTS.TO_TARGET).toBe(2);
    // DISCLOSED_IN → DISCLOSED_IN_FILING (live).
    expect(EDGE_WEIGHTS.DISCLOSED_IN_FILING).toBe(2);
    // UNDER_AGREEMENT → RELATES_TO_AGREEMENT (live).
    expect(EDGE_WEIGHTS.RELATES_TO_AGREEMENT).toBe(2);
    // AMENDS → AMENDS_AGREEMENT (live).
    expect(EDGE_WEIGHTS.AMENDS_AGREEMENT).toBe(2);
  });

  it("maps weight-3 governance-structure edges", () => {
    expect(EDGE_WEIGHTS.HELD_BY).toBe(3);
    expect(EDGE_WEIGHTS.CONTROLLED_BY).toBe(3);
    expect(EDGE_WEIGHTS.CANDIDATE_ACTOR).toBe(3); // BY_PERSON live
    expect(EDGE_WEIGHTS.RESULT_OF_ELECTION).toBe(3);
  });

  it("maps weight-5 AT_MEETING / FILED_BY / PART_OF", () => {
    expect(EDGE_WEIGHTS.AT_MEETING).toBe(5);
    expect(EDGE_WEIGHTS.FILED_BY).toBe(5);
    expect(EDGE_WEIGHTS.PART_OF_MEETING).toBe(5);
    expect(EDGE_WEIGHTS.PART_OF_CASE).toBe(5);
  });

  it("omits universal edges from the weight table", () => {
    expect(EDGE_WEIGHTS.EVIDENCED_BY).toBeUndefined();
    expect(EDGE_WEIGHTS.IN_JURISDICTION).toBeUndefined();
    expect(EDGE_WEIGHTS.RELATES_TO_ISSUE).toBeUndefined();
  });

  it("tracks loose-only edges and excluded intermediate types", () => {
    expect(LOOSE_ONLY_EDGES.has("EVIDENCED_BY")).toBe(true);
    expect(LOOSE_ONLY_EDGES.has("IN_JURISDICTION")).toBe(true);
    expect(LOOSE_ONLY_EDGES.has("RELATES_TO_ISSUE")).toBe(true);

    expect(EXCLUDED_INTERMEDIATE_TYPES.has("Record")).toBe(true);
    expect(EXCLUDED_INTERMEDIATE_TYPES.has("Issue")).toBe(true);
    expect(EXCLUDED_INTERMEDIATE_TYPES.has("Place")).toBe(true);
    expect(EXCLUDED_INTERMEDIATE_TYPES.has("AgendaItem")).toBe(true);
    expect(EXCLUDED_INTERMEDIATE_TYPES.has("Decision")).toBe(false);
  });
});

describe("scorePath", () => {
  it("sums per-edge weights for a straight path and returns loose_match=false", () => {
    const scored = scorePath(
      {
        node_ids: ["person-a", "decision-b", "meeting-c"],
        node_types: ["Person", "Decision", "Meeting"],
        node_labels: ["Person A", "Decision B", "Meeting C"],
        edge_types: ["CAST_VOTE", "AT_MEETING"],
      },
      false,
    );
    expect(scored).not.toBeNull();
    // CAST_VOTE (1) + AT_MEETING (5) = 6.
    expect(scored!.weight).toBe(6);
    expect(scored!.loose_match).toBe(false);
    expect(scored!.path.nodes).toHaveLength(3);
    expect(scored!.path.edges).toHaveLength(2);
    expect(scored!.path.edges[0]).toMatchObject({
      source: "person-a",
      target: "decision-b",
      type: "CAST_VOTE",
      weight: 1,
    });
  });

  it("rejects paths with an excluded intermediate type in default mode", () => {
    const scored = scorePath(
      {
        node_ids: ["person-a", "record-b", "decision-c"],
        node_types: ["Person", "Record", "Decision"],
        node_labels: ["A", "B", "C"],
        edge_types: ["PARTY_TO", "DECIDED_BY"],
      },
      false,
    );
    expect(scored).toBeNull();
  });

  it("admits an excluded intermediate under loose mode with loose_match=true", () => {
    const scored = scorePath(
      {
        node_ids: ["person-a", "record-b", "decision-c"],
        node_types: ["Person", "Record", "Decision"],
        node_labels: ["A", "B", "C"],
        edge_types: ["PARTY_TO", "DECIDED_BY"],
      },
      true,
    );
    expect(scored).not.toBeNull();
    expect(scored!.loose_match).toBe(true);
  });

  it("allows an excluded type at the endpoint (last node)", () => {
    const scored = scorePath(
      {
        node_ids: ["person-a", "decision-b", "record-c"],
        node_types: ["Person", "Decision", "Record"],
        node_labels: ["A", "B", "C"],
        // The last edge happens to be DECIDED_BY (weight 1) — endpoints may
        // be any type, including excluded types.
        edge_types: ["CAST_VOTE", "DECIDED_BY"],
      },
      false,
    );
    expect(scored).not.toBeNull();
    expect(scored!.loose_match).toBe(false);
  });

  it("rejects EVIDENCED_BY in default mode and admits it at weight 10 under loose", () => {
    const row = {
      node_ids: ["a", "b"],
      node_types: ["Person", "Decision"],
      node_labels: ["A", "B"],
      edge_types: ["EVIDENCED_BY"],
    };
    expect(scorePath(row, false)).toBeNull();
    const loose = scorePath(row, true);
    expect(loose).not.toBeNull();
    expect(loose!.weight).toBe(10);
    expect(loose!.loose_match).toBe(true);
  });

  it("rejects an unknown edge in default mode", () => {
    const row = {
      node_ids: ["a", "b"],
      node_types: ["Person", "Decision"],
      node_labels: ["A", "B"],
      edge_types: ["NEVER_HEARD_OF"],
    };
    expect(scorePath(row, false)).toBeNull();
  });

  it("admits an unknown edge under loose at weight 10", () => {
    const row = {
      node_ids: ["a", "b"],
      node_types: ["Person", "Decision"],
      node_labels: ["A", "B"],
      edge_types: ["NEVER_HEARD_OF"],
    };
    const loose = scorePath(row, true);
    expect(loose).not.toBeNull();
    expect(loose!.weight).toBe(10);
    expect(loose!.loose_match).toBe(true);
  });
});

describe("findPath", () => {
  beforeEach(() => {
    runQueryMock.mockReset();
  });

  it("returns {found: false} when the driver returns no paths", async () => {
    runQueryMock.mockResolvedValueOnce([]);
    const result = await findPath("a", "b");
    expect(result).toEqual({ found: false });
  });

  it("returns {found: false} when fromId === toId (short-circuit, no query)", async () => {
    const result = await findPath("a", "a");
    expect(result).toEqual({ found: false });
    expect(runQueryMock).not.toHaveBeenCalled();
  });

  it("returns the minimum-weight path across multiple candidates", async () => {
    // Two candidate paths:
    //   A: Person → Decision via CAST_VOTE + DECIDED_BY = 2
    //   B: Person → Decision via PARTY_TO + DECIDED_BY = 2
    //   C: Person → Decision via HELD_BY + DECIDED_BY = 4
    // The minimum-weight winner is A (tie broken by driver-record order; our
    // implementation picks the first minimum encountered). The test just
    // asserts the minimum was chosen.
    runQueryMock.mockResolvedValueOnce([
      fakeRecord({
        node_ids: ["p", "s", "d"],
        node_types: ["Person", "SeatService", "Decision"],
        node_labels: ["P", "S", "D"],
        edge_types: ["HELD_BY", "DECIDED_BY"], // 3 + 1 = 4
      }),
      fakeRecord({
        node_ids: ["p", "d"],
        node_types: ["Person", "Decision"],
        node_labels: ["P", "D"],
        edge_types: ["CAST_VOTE"], // weight 1
      }),
    ]);

    const result = await findPath("p", "d");
    expect(result.found).toBe(true);
    if (result.found) {
      expect(result.path.weight).toBe(1);
      expect(result.loose_match).toBe(false);
      expect(result.path.edges[0].type).toBe("CAST_VOTE");
    }
  });

  it("loose toggle re-admits paths through excluded intermediate types", async () => {
    const recordPath = {
      node_ids: ["p", "r", "d"],
      node_types: ["Person", "Record", "Decision"],
      node_labels: ["P", "R", "D"],
      edge_types: ["PARTY_TO", "DECIDED_BY"],
    };
    runQueryMock.mockResolvedValueOnce([fakeRecord(recordPath)]);
    const defaultResult = await findPath("p", "d", { loose: false });
    expect(defaultResult).toEqual({ found: false });

    runQueryMock.mockResolvedValueOnce([fakeRecord(recordPath)]);
    const looseResult = await findPath("p", "d", { loose: true });
    expect(looseResult.found).toBe(true);
    if (looseResult.found) {
      expect(looseResult.loose_match).toBe(true);
      // Fix 5: loose admits excluded intermediate types at a LOOSE_WEIGHT
      // penalty. So PARTY_TO(1) + 10 (Record intermediate penalty) + DECIDED_BY(1) = 12.
      expect(looseResult.path.weight).toBe(12);
    }
  });

  it("passes loose-only edges into the rel filter under loose mode", async () => {
    runQueryMock.mockResolvedValueOnce([]);
    await findPath("a", "b", { loose: true });
    const [, params] = runQueryMock.mock.calls[0];
    expect(typeof params.relFilter).toBe("string");
    expect(String(params.relFilter).split("|")).toContain("EVIDENCED_BY");
    expect(String(params.relFilter).split("|")).toContain("CAST_VOTE");
  });

  it("omits loose-only edges from the rel filter in default mode", async () => {
    runQueryMock.mockResolvedValueOnce([]);
    await findPath("a", "b", { loose: false });
    const [, params] = runQueryMock.mock.calls[0];
    const rels = String(params.relFilter).split("|");
    expect(rels).not.toContain("EVIDENCED_BY");
    expect(rels).not.toContain("IN_JURISDICTION");
    expect(rels).toContain("CAST_VOTE");
  });

  // -------------------------------------------------------------------------
  // Fix 5: loose-mode intermediate-type penalty
  // -------------------------------------------------------------------------

  it("fix 5: loose applies LOOSE_WEIGHT penalty per excluded-intermediate hop", () => {
    // Path: Person → Record → Decision → Place (two excluded-intermediate
    // hops: Record, Decision is fine, Place at the endpoint is OK).
    const scored = scorePath(
      {
        node_ids: ["p", "r1", "d", "pl"],
        node_types: ["Person", "Record", "Decision", "Place"],
        node_labels: ["P", "R", "D", "PL"],
        // CAST_VOTE(1) + CAST_VOTE(1) + CAST_VOTE(1) = 3 edge weights
        edge_types: ["CAST_VOTE", "CAST_VOTE", "CAST_VOTE"],
      },
      true,
    );
    expect(scored).not.toBeNull();
    expect(scored!.loose_match).toBe(true);
    // One excluded intermediate (Record) → +10 penalty. Place at the endpoint
    // does NOT trigger the penalty. Total = 3 (edges) + 10 = 13.
    expect(scored!.weight).toBe(13);
  });

  it("fix 5: strict paths are lighter than loose-equivalent via intermediate penalty", () => {
    const strict = scorePath(
      {
        node_ids: ["p", "d"],
        node_types: ["Person", "Decision"],
        node_labels: ["P", "D"],
        edge_types: ["CAST_VOTE"],
      },
      false,
    );
    const loose = scorePath(
      {
        node_ids: ["p", "r", "d"],
        node_types: ["Person", "Record", "Decision"],
        node_labels: ["P", "R", "D"],
        edge_types: ["CAST_VOTE", "CAST_VOTE"],
      },
      true,
    );
    expect(strict!.weight).toBeLessThan(loose!.weight);
  });

  // -------------------------------------------------------------------------
  // Fix 6: no pre-truncation by hop count
  // -------------------------------------------------------------------------

  it("fix 6: Cypher does not contain a pre-score LIMIT / ORDER BY size()", async () => {
    runQueryMock.mockResolvedValueOnce([]);
    await findPath("a", "b");
    const [cypher] = runQueryMock.mock.calls[0];
    // Pre-fix cypher was "ORDER BY size(node_ids) ASC LIMIT 200". Fix 6
    // removes both so the scorer sees every candidate path.
    expect(cypher as string).not.toMatch(/LIMIT 200/);
    expect(cypher as string).not.toMatch(/ORDER BY size\(node_ids\)/);
  });

  it("fix 6: picks the min-weight path even when it has more hops than another candidate", async () => {
    // Short path: Person → Decision via AT_MEETING (weight 5)
    // Long path:  Person → Decision → Meeting (via CAST_VOTE x2 = 2)
    // Pre-fix, the short path could win at the LIMIT 200 / ORDER BY size
    // stage. Post-fix, weight decides.
    runQueryMock.mockResolvedValueOnce([
      fakeRecord({
        node_ids: ["p", "d"],
        node_types: ["Person", "Decision"],
        node_labels: ["P", "D"],
        edge_types: ["AT_MEETING"], // weight 5
      }),
      fakeRecord({
        node_ids: ["p", "d2", "d"],
        node_types: ["Person", "Decision", "Decision"],
        node_labels: ["P", "D2", "D"],
        // CAST_VOTE (1) + DECIDED_BY (1) = 2, longer but lighter
        edge_types: ["CAST_VOTE", "DECIDED_BY"],
      }),
    ]);
    const result = await findPath("p", "d");
    expect(result.found).toBe(true);
    if (result.found) {
      expect(result.path.weight).toBe(2);
      expect(result.path.edges).toHaveLength(2);
    }
  });

  it("fix 6: transaction-timeout returns {found:false} instead of 500ing", async () => {
    // Shape a real Neo4jError-style object with .code — the path-finder
    // classifier distinguishes timeouts (handled gracefully) from other
    // failures (rethrown so /api/path returns 5xx). Round-2 fix.
    const timeoutErr = Object.assign(
      new Error("transaction timed out"),
      { code: "Neo.ClientError.Transaction.TransactionTimedOut" },
    );
    runQueryMock.mockRejectedValueOnce(timeoutErr);
    const consoleWarn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const result = await findPath("a", "b");
    expect(result).toEqual({ found: false });
    consoleWarn.mockRestore();
  });

  it("round 2: non-timeout Cypher failures are rethrown (not silently no-path)", async () => {
    // A real regression (wrong Cypher, auth, network) must surface as an
    // error, not a silent empty result. Round-2 fix.
    const genericErr = Object.assign(
      new Error("syntax error"),
      { code: "Neo.ClientError.Statement.SyntaxError" },
    );
    runQueryMock.mockRejectedValueOnce(genericErr);
    await expect(findPath("a", "b")).rejects.toThrow("syntax error");
  });

  it("passes maxHops to the Cypher call", async () => {
    runQueryMock.mockResolvedValueOnce([]);
    await findPath("a", "b", { maxHops: 4 });
    const [, params] = runQueryMock.mock.calls[0];
    expect(params.maxHops).toBe(4);

    runQueryMock.mockResolvedValueOnce([]);
    await findPath("a", "b");
    const [, defaultParams] = runQueryMock.mock.calls[1];
    // Fix 6: DEFAULT_MAX_HOPS lowered 6→4 to keep enumeration tractable.
    expect(defaultParams.maxHops).toBe(4);
  });
});
