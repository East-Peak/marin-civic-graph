import { describe, it, expect } from "vitest";
import {
  buildMustShowQuery,
  buildPhase2FillQuery,
  buildEdgesAmongSelectedQuery,
  buildTier2NeighborhoodQuery,
} from "@/lib/server/entity-queries";

describe("entity-queries", () => {
  it("buildMustShowQuery(Person) includes all required traversals", () => {
    const q = buildMustShowQuery("Person");
    expect(q).toContain("HELD_BY");
    expect(q).toContain("FOR_SEAT");
    expect(q).toContain("CONTROLLED_BY");
    expect(q).toContain("PARTY_TO");
    expect(q).toContain("AT_INSTITUTION"); // 3-hop
    expect(q).toContain("ring");
    // All 6 Person must-show rows should be present (SeatService, Seat,
    // Committee, Candidacy, Case, Organization).
    expect(q).toContain("CANDIDATE_ACTOR"); // BY_PERSON → CANDIDATE_ACTOR
  });

  it("buildMustShowQuery(Decision) includes AT_MEETING + DECIDED_BY + CAST_VOTE", () => {
    const q = buildMustShowQuery("Decision");
    expect(q).toContain("AT_MEETING");
    expect(q).toContain("DECIDED_BY");
    expect(q).toContain("CAST_VOTE");
    // ABOUT_PROJECT collapses to RELATES_TO_PROJECT per Batch A.
    expect(q).toContain("RELATES_TO_PROJECT");
    expect(q).toContain("RELATES_TO_PROGRAM");
  });

  it("buildMustShowQuery(Project) uses 2-hop for Amendment + Program", () => {
    const q = buildMustShowQuery("Project");
    // Amendment admitted 2-hop via Agreement:
    //   (Project)<-[FOR_PROJECT→RELATES_TO_PROJECT]-(:Agreement)<-[AMENDS→AMENDS_AGREEMENT]-(Amendment)
    expect(q).toContain("AMENDS_AGREEMENT");
    expect(q).toMatch(/RELATES_TO_PROJECT\]-\(:Agreement\)<-\[:AMENDS_AGREEMENT\]-\(n:Amendment\)/);
    // Program admitted 2-hop via Decision:
    //   (Project)<-[ABOUT_PROJECT→RELATES_TO_PROJECT]-(:Decision)-[ABOUT_PROGRAM→RELATES_TO_PROGRAM]->(Program)
    expect(q).toMatch(/RELATES_TO_PROJECT\]-\(:Decision\)-\[:RELATES_TO_PROGRAM\]->\(n:Program\)/);
  });

  it("buildMustShowQuery(Meeting) wires AT_INSTITUTION, PART_OF_MEETING, AT_MEETING", () => {
    const q = buildMustShowQuery("Meeting");
    expect(q).toContain("AT_INSTITUTION");
    expect(q).toContain("PART_OF_MEETING");
    expect(q).toContain("AT_MEETING");
  });

  it("buildMustShowQuery(Filing) resolves FILED_BY to its 4 live variants", () => {
    const q = buildMustShowQuery("Filing");
    expect(q).toContain("FILED_BY");
    expect(q).toContain("FILED_BY_COMMITTEE");
    expect(q).toContain("OFFICIAL_FILER");
    expect(q).toContain("FILED_BY_ORG"); // M2b: 990 Filing → filing Organization
    expect(q).toContain("FOR_ELECTION");
    expect(q).toContain("DISCLOSED_IN_FILING");
    // The org filer must survive the must-show target-label filter.
    expect(q).toContain("n:Organization");
  });

  it("buildMustShowQuery(Committee) wires CONTROLLED_BY + FILED_BY", () => {
    const q = buildMustShowQuery("Committee");
    expect(q).toContain("CONTROLLED_BY");
    expect(q).toContain("FILED_BY");
  });

  it("buildMustShowQuery(Case) wires PART_OF_CASE + HEARD_IN + PARTY_TO", () => {
    const q = buildMustShowQuery("Case");
    expect(q).toContain("PART_OF_CASE");
    expect(q).toContain("HEARD_IN");
    expect(q).toContain("PARTY_TO");
  });

  it("buildMustShowQuery(Program) uses 2-hop via Decision", () => {
    const q = buildMustShowQuery("Program");
    expect(q).toContain("RELATES_TO_PROGRAM");
    expect(q).toContain("RELATES_TO_PROJECT"); // 2-hop to Project
  });

  it("buildMustShowQuery throws for unsupported Tier 2 types", () => {
    expect(() => buildMustShowQuery("Organization")).toThrow(/Unsupported Tier 1/);
    expect(() => buildMustShowQuery("Record")).toThrow(/Unsupported Tier 1/);
  });

  it("buildPhase2FillQuery has per-type LIMITs matching spec quotas", () => {
    const q = buildPhase2FillQuery("Person");
    expect(q).toMatch(/LIMIT 8/); // MoneyFlow and Decision both 8
    expect(q).toMatch(/LIMIT 6/); // Filing, Meeting, Person all 6
    expect(q).toMatch(/LIMIT 4/); // Organization, AgendaItem, Proceeding
    expect(q).toMatch(/LIMIT 2/); // Amendment, Election, Candidacy
  });

  it("buildPhase2FillQuery excludes focus_id and must_show_ids", () => {
    const q = buildPhase2FillQuery("Person");
    expect(q).toContain("c.id <> $focus_id");
    expect(q).toContain("NOT c.id IN $must_show_ids");
  });

  it("buildPhase2FillQuery uses PHASE2_WHITELIST_LIVE relationship names", () => {
    const q = buildPhase2FillQuery("Project");
    // Must include actual live names (not spec names) in the relationship-type list
    expect(q).toContain("PART_OF_MEETING");
    expect(q).not.toContain(":PART_OF|"); // bare spec name shouldn't be in the pattern
    expect(q).toContain("ABOUT_AGENDA_ITEM");
  });

  it("buildPhase2FillQuery includes 11 UNION ALL sub-queries", () => {
    const q = buildPhase2FillQuery("Person");
    const unionCount = (q.match(/UNION ALL/g) ?? []).length;
    expect(unionCount).toBe(10); // 11 sub-queries = 10 UNION ALL delimiters
  });

  it("buildPhase2FillQuery orders sub-queries by type_priority ASC", () => {
    const q = buildPhase2FillQuery("Decision");
    expect(q).toContain("ORDER BY type_priority ASC");
    // MoneyFlow (priority 1) must come before Decision (priority 2) must come
    // before Candidacy (priority 11) in the source text.
    const moneyIdx = q.indexOf("'MoneyFlow'");
    const decisionIdx = q.indexOf("'Decision'");
    const candidacyIdx = q.indexOf("'Candidacy'");
    expect(moneyIdx).toBeLessThan(decisionIdx);
    expect(decisionIdx).toBeLessThan(candidacyIdx);
  });

  it("buildPhase2FillQuery wires edges_to_must_show for Person + Organization", () => {
    const q = buildPhase2FillQuery("Person");
    // Both Person and Organization sub-queries need the OPTIONAL MATCH count.
    expect(q).toContain("edges_to_must_show");
    expect(q).toContain("OPTIONAL MATCH (c)-[r]-(m)");
    expect(q).toContain("m.id IN must_show_ids");
  });

  it("buildPhase2FillQuery dedupes candidates with WITH DISTINCT c + count(DISTINCT r)", () => {
    // Fix 5 — a candidate reachable by multiple paths was previously counted
    // per-path in edges_to_must_show, inflating Person/Organization
    // centrality scores. Dedup via DISTINCT on both c and r.
    const q = buildPhase2FillQuery("Person");
    expect(q).toContain("WITH DISTINCT c, focus_id, must_show_ids");
    expect(q).toContain("count(DISTINCT r) AS edges_to_must_show");
  });

  it("buildEdgesAmongSelectedQuery filters to whitelist and selected nodes", () => {
    const q = buildEdgesAmongSelectedQuery();
    expect(q).toContain("a.id IN $ids");
    expect(q).toContain("b.id IN $ids");
    expect(q).toContain("type(r) IN $whitelist");
  });

  it("buildEdgesAmongSelectedQuery has deterministic ORDER BY (round 3 fix)", () => {
    // Without ORDER BY the Connections UI rendered groups in AuraDB-plan-dependent
    // order, which violated the "same entity → same layout every reload" contract.
    const q = buildEdgesAmongSelectedQuery();
    expect(q).toContain("ORDER BY rel_type ASC, start_id ASC, end_id ASC");
  });

  it("buildTier2NeighborhoodQuery (generic) caps at 40, excludes Place/Issue, stable order", () => {
    const q = buildTier2NeighborhoodQuery();
    expect(q).toContain("LIMIT 40");
    expect(q).toContain("NOT n:Place");
    expect(q).toContain("NOT n:Issue");
    // Fix 3 — stable ORDER BY so the 40-cap doesn't produce flicker between reloads.
    expect(q).toContain("ORDER BY labels(n)[0] ASC, n.id ASC");
  });

  it("buildTier2NeighborhoodQuery(Record) uses EVIDENCED_BY waiver", () => {
    // Fix 4 — Records reach entities via EVIDENCED_BY (excluded from the
    // Phase-2 whitelist), so a /record/{id} page needs a per-focus waiver.
    const q = buildTier2NeighborhoodQuery("Record");
    expect(q).toContain("EVIDENCED_BY");
    expect(q).toContain("LIMIT 40");
    expect(q).toContain("ORDER BY labels(n)[0] ASC, n.id ASC");
  });

  it("buildTier2NeighborhoodQuery(Place) includes IN_JURISDICTION waiver", () => {
    const q = buildTier2NeighborhoodQuery("Place");
    expect(q).toContain("IN_JURISDICTION");
    // Still exclude Issue to keep the two structural hubs separate.
    expect(q).toContain("NOT n:Issue");
    expect(q).toContain("LIMIT 40");
  });

  it("buildTier2NeighborhoodQuery(Issue) includes RELATES_TO_ISSUE waiver", () => {
    const q = buildTier2NeighborhoodQuery("Issue");
    expect(q).toContain("RELATES_TO_ISSUE");
    expect(q).toContain("NOT n:Place");
    expect(q).toContain("LIMIT 40");
  });
});
