import { describe, it, expect } from "vitest";
import {
  specToLive,
  PHASE2_WHITELIST_LIVE,
  UNIVERSAL_EDGES_LIVE,
  SPEC_TO_LIVE,
  MONEY_EDGES_LIVE,
  LEGAL_EDGES_LIVE,
} from "@/lib/edge-vocabulary";

describe("edge-vocabulary", () => {
  it("PART_OF resolves to both PART_OF_MEETING and PART_OF_CASE", () => {
    expect(specToLive("PART_OF")).toEqual(
      expect.arrayContaining(["PART_OF_MEETING", "PART_OF_CASE"]),
    );
  });

  it("ABOUT_ITEM resolves to ABOUT_AGENDA_ITEM", () => {
    expect(specToLive("ABOUT_ITEM")).toContain("ABOUT_AGENDA_ITEM");
  });

  it("PHASE2_WHITELIST_LIVE excludes core universal edges", () => {
    for (const u of ["EVIDENCED_BY", "IN_JURISDICTION", "RELATES_TO_ISSUE"]) {
      expect(PHASE2_WHITELIST_LIVE).not.toContain(u);
    }
  });

  it("PHASE2_WHITELIST_LIVE has no spec-only names", () => {
    for (const specName of ["ABOUT_ITEM", "DISCLOSED_IN", "PART_OF", "AMENDS", "RESULT_OF"]) {
      expect(PHASE2_WHITELIST_LIVE).not.toContain(specName);
    }
  });

  it("SPEC_TO_LIVE contains all 30 spec relationship names (26 §3 + 2 COI §4.1 + 2 COI §4.2)", () => {
    const specNames = [
      "CAST_VOTE",
      "AT_MEETING",
      "ABOUT_ITEM",
      "DECIDED_BY",
      "PART_OF",
      "HELD_BY",
      "FOR_SEAT",
      "RESULT_OF",
      "AT_INSTITUTION",
      "FROM_SOURCE",
      "TO_TARGET",
      "DISCLOSED_IN",
      "UNDER_AGREEMENT",
      "AMENDS",
      "CONTROLLED_BY",
      "FILED_BY",
      "BY_PERSON",
      "IN_ELECTION",
      "FOR_ELECTION",
      "FOR_PROJECT",
      "ABOUT_PROJECT",
      "ABOUT_PROGRAM",
      "PARTY_TO",
      "CONSTRAINS",
      "BETWEEN",
      "HEARD_IN",
      // COI spec §4.1 (M2a) — Membership edges.
      "MEMBER",
      "MEMBER_OF_ORG",
      // COI spec §4.2 (M4) — Form 700 disclosure edges.
      "DISCLOSED_AS",
      "INTEREST_IN",
    ];
    for (const name of specNames) {
      expect(SPEC_TO_LIVE[name]).toBeDefined();
    }
    expect(specNames).toHaveLength(30);
  });

  it("Membership edges are traversable (whitelisted, not universal-excluded)", () => {
    expect(specToLive("MEMBER")).toEqual(["MEMBER"]);
    expect(specToLive("MEMBER_OF_ORG")).toEqual(["MEMBER_OF_ORG"]);
    for (const e of ["MEMBER", "MEMBER_OF_ORG"]) {
      expect(PHASE2_WHITELIST_LIVE).toContain(e);
      expect(UNIVERSAL_EDGES_LIVE).not.toContain(e);
    }
  });

  it("Form 700 disclosure edges traversable, non-money (COI spec §4.2, M4)", () => {
    expect(specToLive("DISCLOSED_AS")).toEqual(["DISCLOSED_AS"]);
    expect(specToLive("INTEREST_IN")).toEqual(["INTEREST_IN"]);
    for (const e of ["DISCLOSED_AS", "INTEREST_IN"]) {
      expect(PHASE2_WHITELIST_LIVE).toContain(e);
      expect(UNIVERSAL_EDGES_LIVE).not.toContain(e);
      // Disclosure relations, not transactional money flows (Predeclared 2).
      expect(MONEY_EDGES_LIVE).not.toContain(e);
    }
  });

  it("CONSTRAINS has no live edge — not yet materialized", () => {
    expect(specToLive("CONSTRAINS")).toEqual([]);
  });

  it("specToLive returns empty array for unknown spec name", () => {
    expect(specToLive("TOTALLY_MADE_UP_EDGE")).toEqual([]);
  });

  it("FILED_BY resolves to 4 live edges", () => {
    // FILED_BY_ORG (M2b): Form 990 Filing → filing Organization.
    expect(specToLive("FILED_BY")).toEqual([
      "FILED_BY",
      "FILED_BY_COMMITTEE",
      "OFFICIAL_FILER",
      "FILED_BY_ORG",
    ]);
  });

  it("FILED_BY_ORG is Phase-2 traversable", () => {
    expect(PHASE2_WHITELIST_LIVE).toContain("FILED_BY_ORG");
    expect(UNIVERSAL_EDGES_LIVE).not.toContain("FILED_BY_ORG");
  });

  it("UNIVERSAL_EDGES_LIVE carries core structural edges", () => {
    for (const u of ["EVIDENCED_BY", "IN_JURISDICTION", "RELATES_TO_ISSUE", "SAME_AS"]) {
      expect(UNIVERSAL_EDGES_LIVE).toContain(u);
    }
  });

  it("MONEY_EDGES_LIVE covers money-family live edges", () => {
    for (const e of ["FROM_SOURCE", "TO_TARGET", "DISCLOSED_IN_FILING", "RELATES_TO_AGREEMENT"]) {
      expect(MONEY_EDGES_LIVE).toContain(e);
    }
  });

  it("LEGAL_EDGES_LIVE is empty until CONSTRAINS materializes", () => {
    expect(LEGAL_EDGES_LIVE).toEqual([]);
  });
});
