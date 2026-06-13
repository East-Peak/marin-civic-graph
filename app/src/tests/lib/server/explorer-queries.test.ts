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
    // Find the MoneyFlow sub-query and verify its LIMIT. The event_date
    // column widened the sub-query body so the old 400-char slice is no
    // longer enough — widen to 500.
    const mfBlock = cypher.slice(cypher.indexOf("(c:MoneyFlow)"));
    expect(mfBlock.slice(0, 500)).toMatch(/LIMIT 8/);

    const amendBlock = cypher.slice(cypher.indexOf("(c:Amendment)"));
    expect(amendBlock.slice(0, 500)).toMatch(/LIMIT 2/);
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

  it("orders candidates by (ring, type_priority, rank_value DESC, id) at the outer level", () => {
    const { cypher } = buildExpandQuery(base);
    // Fix 3: the outer ORDER BY preserves rank_value so the aggregate cap
    // drops low-priority types first and keeps the highest-ranked members
    // per type within the cap.
    expect(cypher).toContain(
      "ORDER BY ring ASC, type_priority ASC, rank_value DESC, id ASC",
    );
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

  // -------------------------------------------------------------------------
  // Fix 1: edge-class toggles + includeUniversals
  // -------------------------------------------------------------------------

  it("fix 1: includeUniversals adds EVIDENCED_BY/IN_JURISDICTION/RELATES_TO_ISSUE to the relationship pattern", () => {
    const withoutUniversals = buildExpandQuery(base);
    const withUniversals = buildExpandQuery({ ...base, includeUniversals: true });

    const rels = (s: string) =>
      s.match(/\[:([A-Z_|]+)\*1\.\.2\]/)![1].split("|");

    const baseRels = rels(withoutUniversals.cypher);
    const universalRels = rels(withUniversals.cypher);

    // Default traversal excludes the three universals.
    expect(baseRels).not.toContain("EVIDENCED_BY");
    expect(baseRels).not.toContain("IN_JURISDICTION");
    expect(baseRels).not.toContain("RELATES_TO_ISSUE");

    // Flipped on, they appear — while PHASE2_WHITELIST_LIVE members stay.
    expect(universalRels).toContain("EVIDENCED_BY");
    expect(universalRels).toContain("IN_JURISDICTION");
    expect(universalRels).toContain("RELATES_TO_ISSUE");
    expect(universalRels).toContain("AT_MEETING");
    expect(universalRels).toContain("CAST_VOTE");
  });

  it("fix 1: excludedEdgeTypes governance subset + includeUniversals = only money + legal + universals", () => {
    // Simulate toggling governance OFF while keeping money/legal on and
    // enabling universals. The effective query should traverse money edges
    // + legal edges + universals, no governance edges.
    const { cypher } = buildExpandQuery({
      ...base,
      excludedEdgeTypes: ["AT_MEETING", "CAST_VOTE", "DECIDED_BY", "DECIDED_AT", "AT_INSTITUTION"],
      includeUniversals: true,
    });
    const rels = cypher.match(/\[:([A-Z_|]+)\*1\.\.2\]/)![1].split("|");
    expect(rels).not.toContain("AT_MEETING");
    expect(rels).not.toContain("CAST_VOTE");
    expect(rels).not.toContain("DECIDED_BY");
    expect(rels).toContain("FROM_SOURCE");    // money
    expect(rels).toContain("TO_TARGET");      // money
    expect(rels).toContain("EVIDENCED_BY");   // universal
  });

  // -------------------------------------------------------------------------
  // Fix 3: §6.3 Tier-2 priority table (not Plan 2 Phase-2 table)
  // -------------------------------------------------------------------------

  it("fix 3: §6.3 Tier-2 priority table includes all 23 types", () => {
    const { cypher } = buildExpandQuery(base);
    const expectedTypes = [
      "MoneyFlow", "Decision", "Case", "Project", "Program",
      "Agreement", "Amendment", "Filing", "Committee", "Election",
      "Candidacy", "Meeting", "Proceeding", "Person", "Organization",
      "Seat", "SeatService", "AgendaItem", "Record", "Place", "Issue",
      "Membership", "EconomicInterest",
    ];
    for (const t of expectedTypes) {
      expect(cypher, `missing sub-query for ${t}`).toContain(`(c:${t})`);
    }
  });

  it("fix 3 + 10: Proceeding sub-query ranks by occurred_at DESC (live property)", () => {
    const { cypher } = buildExpandQuery(base);
    const block = cypher.slice(cypher.indexOf("(c:Proceeding)"));
    expect(block.slice(0, 600)).toMatch(/ORDER BY hop_distance ASC, c\.occurred_at DESC/);
    // Pre-fix 10 this ranked on c.date / c.proceeding_date which are empty
    // on the live graph.
    expect(block.slice(0, 600)).not.toMatch(/c\.proceeding_date DESC/);
  });

  it("fix 3: Tier-2 type priorities differ from the Plan 2 Phase-2 table (Case < Filing)", () => {
    // Plan 2 Phase-2 has Filing at priority 3 before Case. Spec §6.3 Tier-2
    // ranks Case=3 above Filing=6 (lower number = higher priority).
    const { cypher } = buildExpandQuery(base);
    // Find the Case sub-query and read its type_priority constant.
    const caseBlock = cypher.slice(cypher.indexOf("(c:Case)"));
    const filingBlock = cypher.slice(cypher.indexOf("(c:Filing)"));
    expect(caseBlock.slice(0, 600)).toMatch(/3 AS type_priority/);
    expect(filingBlock.slice(0, 600)).toMatch(/6 AS type_priority/);
  });

  // -------------------------------------------------------------------------
  // Fix 4: event_date projection per sub-query
  // -------------------------------------------------------------------------

  it("fix 4: every sub-query projects event_date so client can plumb it into the time slider", () => {
    const { cypher } = buildExpandQuery(base);
    // Each sub-query must emit `AS event_date`. Count occurrences ≥ active
    // type count.
    const matches = cypher.match(/AS event_date/g) ?? [];
    expect(matches.length).toBeGreaterThanOrEqual(23);
  });

  it("fix 4: outer SELECT carries event_date forward", () => {
    const { cypher } = buildExpandQuery(base);
    expect(cypher).toMatch(/RETURN id, labels, label, type, ring, rank_value, type_priority, event_date/);
  });

  it("fix 4: durable types (Person, Organization, Place, Issue, Seat, Project, Program, Committee, Candidacy) project null event_date", () => {
    const { cypher } = buildExpandQuery(base);
    for (const t of ["Person", "Organization", "Place", "Issue", "Seat", "Project", "Program", "Committee", "Candidacy"]) {
      const block = cypher.slice(cypher.indexOf(`(c:${t})`));
      expect(block.slice(0, 600), `${t} should have null event_date`).toMatch(/null AS event_date/);
    }
  });
});
