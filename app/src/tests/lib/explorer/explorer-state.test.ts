import { describe, it, expect } from "vitest";
import {
  parseUrlToState,
  stateToUrl,
  mergeExpansion,
  defaultTimeRange,
  autoEnableFiltersForFocus,
  edgeKey,
  edgeClassificationExcludes,
  widenTimeRangeForLoadedSubgraph,
  GOVERNANCE_EDGES_LIVE,
  type ExplorerState,
} from "@/lib/explorer/explorer-state";
import { ALL_TYPES } from "@/lib/type-display";
import { MONEY_EDGES_LIVE, LEGAL_EDGES_LIVE } from "@/lib/edge-vocabulary";

const INGEST = "2026-04-14T09:00:00Z";

function emptyState(overrides: Partial<ExplorerState> = {}): ExplorerState {
  return parseUrlToState(new URLSearchParams(), INGEST) ?? (overrides as ExplorerState);
}

describe("defaultTimeRange", () => {
  it("returns 5-year window ending at ingestAt", () => {
    const { from, to } = defaultTimeRange("2026-04-14T09:00:00Z");
    expect(to).toBe("2026-04-14");
    // 5 years * 365 days = 1825 days; ISO subtraction rounds to 2021-04-15
    // (5 years = 1825 days, leap-year aware is not done here — that's fine
    // for a default that the user can adjust).
    expect(from.startsWith("2021-")).toBe(true);
  });

  it("accepts a plain YYYY-MM-DD ingest date", () => {
    const { from, to } = defaultTimeRange("2026-01-01");
    expect(to).toBe("2026-01-01");
    expect(from.startsWith("2021-")).toBe(true);
  });
});

describe("parseUrlToState", () => {
  it("returns defaults when URL is empty", () => {
    const s = parseUrlToState(new URLSearchParams(), INGEST);
    expect(s.focus).toBeNull();
    expect(s.hop).toBe(2);
    expect(s.nodeFilters.Person).toBe(true);
    expect(s.nodeFilters.Record).toBe(false);
    expect(s.nodeFilters.Place).toBe(false);
    expect(s.nodeFilters.Issue).toBe(false);
    expect(s.nodeFilters.AgendaItem).toBe(false);
    expect(s.edgeFilters).toEqual({
      governance: true,
      money: true,
      legalConstrains: true,
      universal: false,
    });
    expect(s.timeTo).toBe("2026-04-14");
    expect(s.loadedNodeIds.size).toBe(0);
    expect(s.loadedEdgeKeys.size).toBe(0);
  });

  it("parses focus and seeds loadedNodeIds with it", () => {
    const s = parseUrlToState(
      new URLSearchParams("?focus=person-kate-colin"),
      INGEST,
    );
    expect(s.focus).toBe("person-kate-colin");
    expect(s.loadedNodeIds.has("person-kate-colin")).toBe(true);
  });

  it("clamps hop to 1..4", () => {
    for (const [input, expected] of [
      ["1", 1],
      ["2", 2],
      ["3", 3],
      ["4", 4],
      ["0", 2], // out-of-range → default
      ["5", 2],
      ["abc", 2],
      ["2.5", 2],
    ] as const) {
      const s = parseUrlToState(new URLSearchParams(`?hop=${input}`), INGEST);
      expect(s.hop, `hop=${input}`).toBe(expected);
    }
  });

  it("parses an enabled-only node list", () => {
    const s = parseUrlToState(
      new URLSearchParams("?nodes=Person,Decision,Record"),
      INGEST,
    );
    expect(s.nodeFilters.Person).toBe(true);
    expect(s.nodeFilters.Decision).toBe(true);
    expect(s.nodeFilters.Record).toBe(true);
    expect(s.nodeFilters.Meeting).toBe(false);
    expect(s.nodeFilters.Organization).toBe(false);
  });

  it("ignores unknown node types in the URL", () => {
    const s = parseUrlToState(
      new URLSearchParams("?nodes=Person,NotAType,Decision"),
      INGEST,
    );
    expect(s.nodeFilters.Person).toBe(true);
    expect(s.nodeFilters.Decision).toBe(true);
    // No crash for NotAType.
  });

  it("treats nodes= (empty) as all-off", () => {
    const s = parseUrlToState(new URLSearchParams("?nodes="), INGEST);
    for (const t of ALL_TYPES) {
      expect(s.nodeFilters[t], t).toBe(false);
    }
  });

  it("parses edge filters as enabled-only list", () => {
    const s = parseUrlToState(
      new URLSearchParams("?edges=money,universal"),
      INGEST,
    );
    expect(s.edgeFilters).toEqual({
      governance: false,
      money: true,
      legalConstrains: false,
      universal: true,
    });
  });

  it("parses explicit from/to", () => {
    const s = parseUrlToState(
      new URLSearchParams("?from=2024-01-01&to=2024-12-31"),
      INGEST,
    );
    expect(s.timeFrom).toBe("2024-01-01");
    expect(s.timeTo).toBe("2024-12-31");
  });
});

describe("stateToUrl", () => {
  it("round-trips with parseUrlToState on defaults", () => {
    const s = parseUrlToState(new URLSearchParams(), INGEST);
    const url = stateToUrl(s);
    const parsed = parseUrlToState(url, INGEST);
    expect(parsed.hop).toBe(s.hop);
    expect(parsed.nodeFilters).toEqual(s.nodeFilters);
    expect(parsed.edgeFilters).toEqual(s.edgeFilters);
    expect(parsed.timeFrom).toBe(s.timeFrom);
    expect(parsed.timeTo).toBe(s.timeTo);
  });

  it("omits hop when default (2)", () => {
    const s = parseUrlToState(new URLSearchParams(), INGEST);
    const url = stateToUrl(s);
    expect(url.has("hop")).toBe(false);
  });

  it("emits hop when non-default", () => {
    const base = parseUrlToState(new URLSearchParams(), INGEST);
    const url = stateToUrl({ ...base, hop: 4 });
    expect(url.get("hop")).toBe("4");
  });

  it("omits node filter param when defaults", () => {
    const s = parseUrlToState(new URLSearchParams(), INGEST);
    const url = stateToUrl(s);
    expect(url.has("nodes")).toBe(false);
  });

  it("emits node filter param when non-default", () => {
    const base = parseUrlToState(new URLSearchParams(), INGEST);
    const state = {
      ...base,
      nodeFilters: { ...base.nodeFilters, Record: true }, // default Record=false
    };
    const url = stateToUrl(state);
    expect(url.get("nodes")?.split(",")).toContain("Record");
  });

  it("emits focus and time when set", () => {
    const base = parseUrlToState(
      new URLSearchParams("?focus=person-kate-colin"),
      INGEST,
    );
    const url = stateToUrl(base);
    expect(url.get("focus")).toBe("person-kate-colin");
    expect(url.get("from")).toBe(base.timeFrom);
    expect(url.get("to")).toBe(base.timeTo);
  });

  it("round-trips edge filter changes", () => {
    const base = parseUrlToState(new URLSearchParams(), INGEST);
    const state = {
      ...base,
      edgeFilters: { ...base.edgeFilters, universal: true, money: false },
    };
    const url = stateToUrl(state);
    const parsed = parseUrlToState(url, INGEST);
    expect(parsed.edgeFilters).toEqual(state.edgeFilters);
  });
});

describe("mergeExpansion", () => {
  it("adds new node ids to loadedNodeIds", () => {
    const base = parseUrlToState(new URLSearchParams("?focus=a"), INGEST);
    const merged = mergeExpansion(base, [{ id: "b" }, { id: "c" }], []);
    expect([...merged.loadedNodeIds].sort()).toEqual(["a", "b", "c"]);
  });

  it("dedupes when a node reappears", () => {
    const base = parseUrlToState(new URLSearchParams("?focus=a"), INGEST);
    const merged = mergeExpansion(base, [{ id: "a" }, { id: "b" }], []);
    expect(merged.loadedNodeIds.size).toBe(2);
  });

  it("preserves other state fields (immutable update)", () => {
    const base = parseUrlToState(
      new URLSearchParams("?focus=a&hop=3"),
      INGEST,
    );
    const merged = mergeExpansion(base, [{ id: "b" }], []);
    expect(merged.hop).toBe(3);
    expect(merged.nodeFilters).toEqual(base.nodeFilters);
    expect(merged.loadedNodeIds).not.toBe(base.loadedNodeIds); // new Set instance
  });

  it("dedupes edges regardless of direction via edgeKey", () => {
    const base = parseUrlToState(new URLSearchParams("?focus=a"), INGEST);
    const merged = mergeExpansion(
      base,
      [],
      [
        { source: "a", target: "b", type: "CAST_VOTE" },
        { source: "b", target: "a", type: "CAST_VOTE" }, // reversed
      ],
    );
    expect(merged.loadedEdgeKeys.size).toBe(1);
  });

  it("edgeKey is direction-independent", () => {
    expect(edgeKey({ source: "a", target: "b", type: "X" })).toBe(
      edgeKey({ source: "b", target: "a", type: "X" }),
    );
    // But different rel types are different keys.
    expect(edgeKey({ source: "a", target: "b", type: "X" })).not.toBe(
      edgeKey({ source: "a", target: "b", type: "Y" }),
    );
  });
});

describe("autoEnableFiltersForFocus", () => {
  it("enables the Record filter + universal edges for Record focus", () => {
    const base = parseUrlToState(new URLSearchParams(), INGEST);
    expect(base.nodeFilters.Record).toBe(false);
    expect(base.edgeFilters.universal).toBe(false);
    const after = autoEnableFiltersForFocus(base, "Record");
    expect(after.nodeFilters.Record).toBe(true);
    expect(after.edgeFilters.universal).toBe(true);
  });

  it("enables Place + universal edges for Place focus", () => {
    const base = parseUrlToState(new URLSearchParams(), INGEST);
    const after = autoEnableFiltersForFocus(base, "Place");
    expect(after.nodeFilters.Place).toBe(true);
    expect(after.edgeFilters.universal).toBe(true);
  });

  it("enables Issue + universal edges for Issue focus", () => {
    const base = parseUrlToState(new URLSearchParams(), INGEST);
    const after = autoEnableFiltersForFocus(base, "Issue");
    expect(after.nodeFilters.Issue).toBe(true);
    expect(after.edgeFilters.universal).toBe(true);
  });

  it("enables AgendaItem filter but NOT universal edges for AgendaItem focus", () => {
    const base = parseUrlToState(new URLSearchParams(), INGEST);
    const after = autoEnableFiltersForFocus(base, "AgendaItem");
    expect(after.nodeFilters.AgendaItem).toBe(true);
    // AgendaItem uses PART_OF which is in the Phase-2 whitelist — no need
    // for universal edges.
    expect(after.edgeFilters.universal).toBe(false);
  });

  it("is a no-op for focus types that are already on by default", () => {
    const base = parseUrlToState(new URLSearchParams(), INGEST);
    const after = autoEnableFiltersForFocus(base, "Person");
    expect(after.nodeFilters).toEqual(base.nodeFilters);
    expect(after.edgeFilters).toEqual(base.edgeFilters);
  });

  it("does not mutate the input state", () => {
    const base = parseUrlToState(new URLSearchParams(), INGEST);
    const snapshot = JSON.stringify({
      nodeFilters: base.nodeFilters,
      edgeFilters: base.edgeFilters,
    });
    autoEnableFiltersForFocus(base, "Record");
    expect(
      JSON.stringify({
        nodeFilters: base.nodeFilters,
        edgeFilters: base.edgeFilters,
      }),
    ).toBe(snapshot);
  });
});

// -------------------------------------------------------------------------
// Fix 1: edgeClassificationExcludes
// -------------------------------------------------------------------------

describe("edgeClassificationExcludes", () => {
  it("returns an empty list when every edge class is on", () => {
    const base = parseUrlToState(new URLSearchParams(), INGEST);
    const excludes = edgeClassificationExcludes(base);
    expect(excludes).toEqual([]);
  });

  it("excludes the money edges when money is off", () => {
    const base = parseUrlToState(new URLSearchParams(), INGEST);
    const state: ExplorerState = {
      ...base,
      edgeFilters: { ...base.edgeFilters, money: false },
    };
    const excludes = edgeClassificationExcludes(state);
    for (const e of MONEY_EDGES_LIVE) expect(excludes).toContain(e);
  });

  it("excludes governance-classified edges (non-money, non-legal) when governance is off", () => {
    const base = parseUrlToState(new URLSearchParams(), INGEST);
    const state: ExplorerState = {
      ...base,
      edgeFilters: { ...base.edgeFilters, governance: false },
    };
    const excludes = edgeClassificationExcludes(state);
    for (const e of GOVERNANCE_EDGES_LIVE) expect(excludes).toContain(e);
    // Money + legal should NOT be excluded since those chips are still on.
    for (const e of MONEY_EDGES_LIVE) expect(excludes).not.toContain(e);
  });

  it("excludes legal-constrains edges when legalConstrains is off", () => {
    const base = parseUrlToState(new URLSearchParams(), INGEST);
    const state: ExplorerState = {
      ...base,
      edgeFilters: { ...base.edgeFilters, legalConstrains: false },
    };
    const excludes = edgeClassificationExcludes(state);
    for (const e of LEGAL_EDGES_LIVE) expect(excludes).toContain(e);
  });

  it("combines multiple off-classes without double-counting", () => {
    const base = parseUrlToState(new URLSearchParams(), INGEST);
    const state: ExplorerState = {
      ...base,
      edgeFilters: {
        governance: false,
        money: false,
        legalConstrains: true,
        universal: true,
      },
    };
    const excludes = edgeClassificationExcludes(state);
    // Union of governance + money, no duplicates.
    const set = new Set(excludes);
    expect(set.size).toBe(excludes.length);
    for (const e of GOVERNANCE_EDGES_LIVE) expect(set.has(e)).toBe(true);
    for (const e of MONEY_EDGES_LIVE) expect(set.has(e)).toBe(true);
  });
});

// -------------------------------------------------------------------------
// Fix 4: widenTimeRangeForLoadedSubgraph
// -------------------------------------------------------------------------

describe("widenTimeRangeForLoadedSubgraph", () => {
  it("widens timeFrom to cover an earlier event_date", () => {
    const base = parseUrlToState(new URLSearchParams(), INGEST);
    expect(base.timeFrom.startsWith("2021-")).toBe(true);
    const widened = widenTimeRangeForLoadedSubgraph(base, ["2015-06-01"]);
    expect(widened.timeFrom).toBe("2015-06-01");
    // timeTo is never touched.
    expect(widened.timeTo).toBe(base.timeTo);
  });

  it("does not mutate when every event_date is inside the window", () => {
    const base = parseUrlToState(new URLSearchParams(), INGEST);
    const widened = widenTimeRangeForLoadedSubgraph(base, ["2023-01-01", "2024-12-31"]);
    expect(widened.timeFrom).toBe(base.timeFrom);
  });

  it("ignores null / undefined / malformed dates", () => {
    const base = parseUrlToState(new URLSearchParams(), INGEST);
    const widened = widenTimeRangeForLoadedSubgraph(base, [null, undefined, "", "not-a-date"]);
    expect(widened.timeFrom).toBe(base.timeFrom);
  });

  it("uses the earliest of multiple dates", () => {
    const base = parseUrlToState(new URLSearchParams(), INGEST);
    const widened = widenTimeRangeForLoadedSubgraph(base, ["2015-06-01", "2010-01-01", "2017-09-09"]);
    expect(widened.timeFrom).toBe("2010-01-01");
  });

  it("uses the first 10 chars of a longer ISO datetime", () => {
    const base = parseUrlToState(new URLSearchParams(), INGEST);
    const widened = widenTimeRangeForLoadedSubgraph(base, ["2015-06-01T12:34:56Z"]);
    expect(widened.timeFrom).toBe("2015-06-01");
  });
});

// Reference emptyState to avoid unused-import lint noise (kept in scope for
// future tests; harmless at runtime).
void emptyState;
