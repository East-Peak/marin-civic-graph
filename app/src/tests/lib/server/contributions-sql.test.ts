import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  CONTRIBUTION_COUNT,
  CONTRIBUTION_TOTAL_CENTS,
  NODE_PROP_VALUES,
  WITHHELD_VALUES,
  makeContributionFixtureDb,
} from "./contribution-fixtures";

vi.mock("@/lib/neo4j", () => ({
  runQuery: vi.fn(async () => {
    throw new Error("contribution queries read only the public substrate");
  }),
}));

type Mod = typeof import("@/lib/server/contributions-sql");
let mod: Mod;

beforeEach(async () => {
  vi.resetModules();
  process.env.SUBSTRATE_DB_PATH = makeContributionFixtureDb();
  mod = await import("@/lib/server/contributions-sql");
});

afterEach(async () => {
  (await import("@/lib/server/substrate")).closeSubstrateDb();
  delete process.env.SUBSTRATE_DB_PATH;
});

const ALLOWED_ROW_KEYS = ["amount_cents", "date", "details", "flow_id", "flow_route", "recipient"];
const ALLOWED_DETAIL_KEYS = ["city", "employer", "occupation", "state", "zip5"];

function assertNoLeaks(value: unknown) {
  const text = JSON.stringify(value);
  for (const needle of [...WITHHELD_VALUES, ...NODE_PROP_VALUES]) {
    expect(text).not.toContain(needle);
  }
}

describe("loadContributionsByName", () => {
  it("lists only the node's reconciled contributions, newest first, with each row's own details", () => {
    const view = mod.loadContributionsByName("person-able-sample")!;
    expect(view.contributor).toEqual({ id: "person-able-sample", type: "Person", label: "ABLE SAMPLE" });
    expect(view.rows.map((r) => r.flow_id)).toEqual([
      "moneyflow-able-refund",
      "moneyflow-able-2",
      "moneyflow-able-1",
    ]);
    expect(view.rows.map((r) => r.amount_cents)).toEqual([-2_500, 10_010, 25_000]);
    expect(view.rows[2]).toEqual({
      flow_id: "moneyflow-able-1",
      flow_route: "/money-flow/able-1",
      date: "2024-03-01",
      amount_cents: 25_000,
      recipient: { id: "committee-alpha", label: "Committee for Measure Alpha", route: "/committee/alpha" },
      details: {
        occupation: "Teacher",
        employer: "Sampleton Unified",
        city: "Sampleton",
        state: "CA",
        zip5: "94999",
      },
    });
    expect(view.rows[1].details.city).toBe("Exampleville");
    expect(view.rows[0].details).toEqual({
      occupation: null,
      employer: null,
      city: null,
      state: null,
      zip5: null,
    });
    for (const row of view.rows) {
      expect(Object.keys(row).sort()).toEqual(ALLOWED_ROW_KEYS);
      expect(Object.keys(row.details).sort()).toEqual(ALLOWED_DETAIL_KEYS);
    }
    expect(view.totals).toEqual({ count: 3, total_cents: 32_510 });
    expect(view.by_committee).toEqual([
      {
        recipient: { id: "committee-alpha", label: "Committee for Measure Alpha", route: "/committee/alpha" },
        count: 3,
        total_cents: 32_510,
      },
    ]);
    assertNoLeaks(view);
  });

  it("counts a flow once when its join path is stored twice", () => {
    const view = mod.loadContributionsByName("person-dup-path")!;
    expect(view.rows).toHaveLength(1);
    expect(view.totals).toEqual({ count: 1, total_cents: 4_000 });
  });

  it("reconciles float amounts in whole cents", () => {
    expect(mod.loadContributionsByName("person-float-noise")!.totals).toEqual({
      count: 3,
      total_cents: 1_265,
    });
    expect(mod.loadContributionsByName("person-zero")!.totals).toEqual({ count: 1, total_cents: 0 });
  });

  it("returns null for nodes with no reconciled contribution and for non-contributor types", () => {
    expect(mod.loadContributionsByName("person-ocr-only")).toBeNull();
    expect(mod.loadContributionsByName("person-official-only")).toBeNull();
    expect(mod.loadContributionsByName("committee-alpha")).toBeNull();
    expect(mod.loadContributionsByName("moneyflow-able-1")).toBeNull();
    expect(mod.loadContributionsByName("person-missing")).toBeNull();
  });

  it("gives an organization only its contributions, never its contract or rollup money", () => {
    const view = mod.loadContributionsByName("org-one-large")!;
    expect(view.contributor.type).toBe("Organization");
    expect(view.rows.map((r) => r.flow_id)).toEqual(["moneyflow-large"]);
    expect(view.totals).toEqual({ count: 1, total_cents: 100_000 });
    expect(JSON.stringify(view)).not.toMatch(/contract|250000|251000|canonical/i);
  });
});

describe("loadCommitteeTopContributors", () => {
  it("ranks names by total to this committee, many small gifts above one large", () => {
    const page = mod.loadCommitteeTopContributors("committee-alpha", { limit: 10 });
    expect(page.summary).toEqual({ names: 4, count: 35, total_cents: 286_510 });
    expect(
      page.rows.map((r) => [r.contributor.id, r.count, r.total_cents]),
    ).toEqual([
      ["person-many-small", 30, 150_000],
      ["org-one-large", 1, 100_000],
      ["person-able-sample", 3, 32_510],
      ["person-dup-path", 1, 4_000],
    ]);
    expect(page.rows[1].contributor).toEqual({
      id: "org-one-large",
      type: "Organization",
      label: "ONE LARGE HOLDINGS LLC",
      name_route: "/contributions/by-name/organization/one-large",
    });
    expect(page.next_cursor).toBeNull();
  });

  it("ties each reported detail to its own row and lists only this committee's rows", () => {
    const page = mod.loadCommitteeTopContributors("committee-alpha", { limit: 10 });
    const able = page.rows.find((r) => r.contributor.id === "person-able-sample")!;
    expect(able.rows).toEqual([
      {
        flow_id: "moneyflow-able-refund",
        flow_route: "/money-flow/able-refund",
        date: "2024-05-01",
        amount_cents: -2_500,
        details: { occupation: null, employer: null, city: null, state: null, zip5: null },
      },
      {
        flow_id: "moneyflow-able-2",
        flow_route: "/money-flow/able-2",
        date: "2024-04-01",
        amount_cents: 10_010,
        details: {
          occupation: "Teacher",
          employer: "Exampleville Schools",
          city: "Exampleville",
          state: "CA",
          zip5: "94998",
        },
      },
      {
        flow_id: "moneyflow-able-1",
        flow_route: "/money-flow/able-1",
        date: "2024-03-01",
        amount_cents: 25_000,
        details: {
          occupation: "Teacher",
          employer: "Sampleton Unified",
          city: "Sampleton",
          state: "CA",
          zip5: "94999",
        },
      },
    ]);
    for (const entry of page.rows) {
      expect(entry.rows).toHaveLength(entry.count);
      expect(entry.rows.reduce((sum, r) => sum + r.amount_cents, 0)).toBe(entry.total_cents);
    }
    // The same people give to beta; none of those rows may enter alpha's ranking.
    const beta = mod.loadCommitteeTopContributors("committee-beta", { limit: 10 });
    const alphaFlows = new Set(page.rows.flatMap((e) => e.rows.map((r) => r.flow_id)));
    for (const entry of beta.rows) for (const r of entry.rows) expect(alphaFlows.has(r.flow_id)).toBe(false);
    assertNoLeaks(page);
  });

  it("orders tied totals by id and keeps refunds and zeros in the ranking", () => {
    const page = mod.loadCommitteeTopContributors("committee-beta", { limit: 10 });
    expect(page.rows.map((r) => [r.contributor.id, r.total_cents])).toEqual([
      ["person-tie-a", 30_000],
      ["person-tie-b", 30_000],
      ["person-pat-example-2", 7_500],
      ["person-float-noise", 1_265],
      ["person-zero", 0],
    ]);
    expect(page.summary).toEqual({ names: 5, count: 7, total_cents: 68_765 });
  });

  it("returns an empty page for a committee without contributions", () => {
    const page = mod.loadCommitteeTopContributors("committee-empty", { limit: 10 });
    expect(page).toEqual({ summary: { names: 0, count: 0, total_cents: 0 }, rows: [], next_cursor: null });
  });

  it.each([1, 2, 3])("traverses every name exactly once at page size %i", (limit) => {
    for (const committee of ["committee-alpha", "committee-beta"]) {
      const full = mod.loadCommitteeTopContributors(committee, { limit: 100 }).rows.map((r) => r.contributor.id);
      const seen: string[] = [];
      let after: string | null = null;
      do {
        const page = mod.loadCommitteeTopContributors(committee, { limit, after });
        expect(page.rows.length).toBeLessThanOrEqual(limit);
        seen.push(...page.rows.map((r) => r.contributor.id));
        after = page.next_cursor;
      } while (after);
      expect(seen).toEqual(full);
      expect(new Set(seen).size).toBe(seen.length);
    }
  });

  it("rejects a malformed cursor instead of guessing", () => {
    expect(() => mod.loadCommitteeTopContributors("committee-alpha", { limit: 2, after: "junk" })).toThrow(
      mod.InvalidCursorError,
    );
  });
});

describe("loadLargestContributions", () => {
  it("counts exactly the reconciled contribution MoneyFlows", () => {
    expect(mod.countContributions()).toBe(CONTRIBUTION_COUNT);
  });

  it("orders by signed amount, then flow id, one row per contribution", () => {
    const page = mod.loadLargestContributions({ limit: 6 });
    expect(page.rows.map((r) => [r.flow_id, r.amount_cents])).toEqual([
      ["moneyflow-large", 100_000],
      ["moneyflow-candidate", 50_000],
      ["moneyflow-tie-a", 30_000],
      ["moneyflow-tie-b", 30_000],
      ["moneyflow-able-1", 25_000],
      ["moneyflow-able-2", 10_010],
    ]);
    expect(page.rows[0]).toEqual({
      flow_id: "moneyflow-large",
      flow_route: "/money-flow/large",
      date: "2024-01-15",
      amount_cents: 100_000,
      contributor: {
        id: "org-one-large",
        type: "Organization",
        label: "ONE LARGE HOLDINGS LLC",
        name_route: "/contributions/by-name/organization/one-large",
      },
      recipient: { id: "committee-alpha", label: "Committee for Measure Alpha", route: "/committee/alpha" },
      details: { occupation: null, employer: null, city: null, state: null, zip5: null },
    });
  });

  it.each([1, 4, 7, 50])("traverses all contributions exactly once at page size %i", (limit) => {
    const seen: string[] = [];
    let cents = 0;
    let after: string | null = null;
    do {
      const page = mod.loadLargestContributions({ limit, after });
      seen.push(...page.rows.map((r) => r.flow_id));
      cents += page.rows.reduce((sum, r) => sum + r.amount_cents, 0);
      after = page.next_cursor;
    } while (after);
    expect(seen).toHaveLength(CONTRIBUTION_COUNT);
    expect(new Set(seen).size).toBe(CONTRIBUTION_COUNT);
    expect(cents).toBe(CONTRIBUTION_TOTAL_CENTS);
    expect(seen.at(-1)).toBe("moneyflow-able-refund");
  });

  it("never exposes withheld values or node props", () => {
    assertNoLeaks(mod.loadLargestContributions({ limit: 100 }));
  });
});

describe("isContributorOnly", () => {
  it.each([
    ["person-many-small", true],
    ["person-evidenced", true], // an EVIDENCED_BY edge is provenance, not a role
    ["person-ocr-only", true],
    ["person-able-sample", false], // also a payee
    ["person-candidate", false], // controls a committee
    ["org-one-large", false], // contract recipient with a SAME_AS link
    ["person-official-only", false],
    ["committee-alpha", false],
    ["person-missing", false],
  ])("%s → %s", (id, expected) => {
    expect(mod.isContributorOnly(id)).toBe(expected);
  });
});
