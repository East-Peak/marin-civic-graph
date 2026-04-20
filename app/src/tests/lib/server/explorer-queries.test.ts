import { describe, it, expect } from "vitest";
import { buildExpandQuery } from "@/lib/server/explorer-queries";
import {
  EXPAND_QUOTAS,
  AGGREGATE_CAPS,
  quotaFor,
  aggregateCapFor,
} from "@/lib/explorer/expand-quotas";
import { ALL_TYPES } from "@/lib/type-display";

describe("expand-quotas", () => {
  it("EXPAND_QUOTAS covers every NodeType", () => {
    for (const t of ALL_TYPES) {
      expect(EXPAND_QUOTAS[t]).toBeDefined();
      // Every type has quotas > 0 for every hop.
      expect(EXPAND_QUOTAS[t].hop1).toBeGreaterThan(0);
      expect(EXPAND_QUOTAS[t].hop4).toBeGreaterThanOrEqual(EXPAND_QUOTAS[t].hop1);
    }
  });

  it("AGGREGATE_CAPS matches spec §6.3 (20/80/160/240)", () => {
    expect(AGGREGATE_CAPS[1]).toBe(20);
    expect(AGGREGATE_CAPS[2]).toBe(80);
    expect(AGGREGATE_CAPS[3]).toBe(160);
    expect(AGGREGATE_CAPS[4]).toBe(240);
  });

  it("quotaFor reflects the per-type-per-hop table", () => {
    // Spot-check the table rows from the plan.
    expect(quotaFor("MoneyFlow", 1)).toBe(4);
    expect(quotaFor("MoneyFlow", 4)).toBe(24);
    expect(quotaFor("Amendment", 1)).toBe(1);
    expect(quotaFor("Amendment", 4)).toBe(6);
    expect(quotaFor("Person", 2)).toBe(6);
    expect(quotaFor("Meeting", 3)).toBe(12);
    expect(quotaFor("Place", 1)).toBe(1);
  });

  it("aggregateCapFor mirrors AGGREGATE_CAPS", () => {
    expect(aggregateCapFor(1)).toBe(20);
    expect(aggregateCapFor(3)).toBe(160);
  });
});

describe("buildExpandQuery", () => {
  const base = {
    focusId: "person-kate-colin",
    hopLimit: 2 as const,
    excludedNodeTypes: [],
    excludedEdgeTypes: [],
    alreadyLoadedIds: [],
  };

  it("returns the correct cap for each hopLimit", () => {
    expect(buildExpandQuery({ ...base, hopLimit: 1 }).cap).toBe(20);
    expect(buildExpandQuery({ ...base, hopLimit: 2 }).cap).toBe(80);
    expect(buildExpandQuery({ ...base, hopLimit: 3 }).cap).toBe(160);
    expect(buildExpandQuery({ ...base, hopLimit: 4 }).cap).toBe(240);
  });

  it("parameterizes focus_id and already_loaded_ids", () => {
    const { params } = buildExpandQuery({
      ...base,
      focusId: "person-kate-colin",
      alreadyLoadedIds: ["a", "b"],
    });
    expect(params.focus_id).toBe("person-kate-colin");
    expect(params.already_loaded_ids).toEqual(["a", "b"]);
  });

  it("filters candidates by already_loaded_ids and excludes focus_id", () => {
    const { cypher } = buildExpandQuery(base);
    expect(cypher).toContain("c.id <> $focus_id");
    expect(cypher).toContain("NOT c.id IN $already_loaded_ids");
  });

  it("embeds the hopLimit in the variable-length relationship pattern", () => {
    const { cypher: c1 } = buildExpandQuery({ ...base, hopLimit: 1 });
    const { cypher: c3 } = buildExpandQuery({ ...base, hopLimit: 3 });
    expect(c1).toContain("*1..1");
    expect(c3).toContain("*1..3");
  });

  it("per-type LIMITs match quotaFor(type, hopLimit)", () => {
    // Hop 2 quotas: MoneyFlow=8, Person=6, Organization=4, Amendment=2
    const { cypher } = buildExpandQuery({ ...base, hopLimit: 2 });
    expect(cypher).toContain("(c:MoneyFlow)");
    // Find the MoneyFlow sub-query and verify its LIMIT.
    const mfBlock = cypher.slice(cypher.indexOf("(c:MoneyFlow)"));
    expect(mfBlock.slice(0, 400)).toMatch(/LIMIT 8/);

    const amendBlock = cypher.slice(cypher.indexOf("(c:Amendment)"));
    expect(amendBlock.slice(0, 400)).toMatch(/LIMIT 2/);
  });

  it("excludes edges from excludedEdgeTypes from the relationship list", () => {
    const { cypher } = buildExpandQuery({
      ...base,
      excludedEdgeTypes: ["CAST_VOTE", "DECIDED_BY"],
    });
    // The relationship-type list appears in every sub-query; check that
    // neither excluded edge is in any of them.
    // Pattern: [:REL1|REL2|...*1..N]
    const relListMatch = cypher.match(/\[:([A-Z_|]+)\*1\.\.2\]/);
    expect(relListMatch).not.toBeNull();
    const rels = relListMatch![1].split("|");
    expect(rels).not.toContain("CAST_VOTE");
    expect(rels).not.toContain("DECIDED_BY");
    // Non-excluded edges still present.
    expect(rels).toContain("AT_MEETING");
  });

  it("skips sub-queries for excludedNodeTypes", () => {
    const { cypher } = buildExpandQuery({
      ...base,
      excludedNodeTypes: ["MoneyFlow", "Decision"],
    });
    expect(cypher).not.toContain("(c:MoneyFlow)");
    expect(cypher).not.toContain("(c:Decision)");
    // Other types still appear.
    expect(cypher).toContain("(c:Person)");
    expect(cypher).toContain("(c:Meeting)");
  });

  it("returns a degenerate parsed-but-empty query when every type is excluded", () => {
    const { cypher, cap } = buildExpandQuery({
      ...base,
      excludedNodeTypes: [...ALL_TYPES],
    });
    // No per-type UNION sub-queries.
    expect(cypher).not.toContain("UNION ALL");
    expect(cypher).toContain("LIMIT 0");
    // cap still reflects the hop-level aggregate.
    expect(cap).toBe(80);
  });

  it("orders candidates by (hop_distance, type_priority, id) at the outer level", () => {
    const { cypher } = buildExpandQuery(base);
    expect(cypher).toContain("ORDER BY ring ASC, type_priority ASC, id ASC");
    expect(cypher).toContain("LIMIT $cap");
  });

  it("orders each sub-query by hop_distance ASC first, then type ranking, then c.id", () => {
    const { cypher } = buildExpandQuery(base);
    // Every sub-query should order by hop_distance ASC as the leading key.
    expect(cypher).toMatch(/ORDER BY hop_distance ASC, c\.amount DESC/);
    expect(cypher).toMatch(/ORDER BY hop_distance ASC, c\.decided_at DESC/);
    // Final tie-break.
    expect(cypher).toMatch(/, c\.id ASC\n  LIMIT/);
  });

  it("computes hop_distance via WITH min(length(p)) so multi-path dupes resolve to shortest hop", () => {
    const { cypher } = buildExpandQuery(base);
    expect(cypher).toContain("WITH c, min(length(p)) AS hop_distance");
  });

  it("uses the PHASE2 live edge whitelist by default", () => {
    const { cypher } = buildExpandQuery(base);
    // A handful of whitelist members should appear.
    expect(cypher).toContain("AT_MEETING");
    expect(cypher).toContain("FILED_BY");
    expect(cypher).toContain("CAST_VOTE");
    // Universals should NOT be in the default pattern.
    expect(cypher).not.toMatch(/EVIDENCED_BY/);
  });

  it("falls back to __NO_LIVE_EDGE__ when every whitelist edge is excluded", () => {
    // Exclude the entire whitelist via the full edge-vocabulary set.
    const whitelistDump = buildExpandQuery(base).cypher;
    const rels = whitelistDump
      .match(/\[:([A-Z_|]+)\*1\.\.2\]/)![1]
      .split("|");
    const { cypher } = buildExpandQuery({
      ...base,
      excludedEdgeTypes: rels,
    });
    expect(cypher).toContain("__NO_LIVE_EDGE__");
  });
});
