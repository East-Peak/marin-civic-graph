// Every campaign surface shows the campaign freshness the bake published, per source, and an artifact
// baked without it (the current published one) renders safely with the plain "not available" line.
import { render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { EntityPayload } from "@/lib/server/entity-loader";
import { CAMPAIGN_FRESHNESS, makeContributionFixtureDb } from "../lib/server/contribution-fixtures";

vi.mock("@/lib/neo4j", () => ({ runQuery: vi.fn() }));
vi.mock("@/lib/server/homepage-data", () => ({
  loadStatus: vi.fn(async () => ({
    connected: true, node_count: 1, edge_count: 1, jurisdiction_count: 1, ingest_at: null, subgraphs_built_at: null,
  })),
}));
vi.mock("next/navigation", () => ({ notFound: () => { throw new Error("NEXT_NOT_FOUND"); } }));
vi.mock("@/lib/server/entity-evidence", () => ({ loadEvidence: vi.fn(async () => []) }));
for (const [path, name] of [
  ["@/components/layout/status-bar", "StatusBar"], ["@/components/layout/nav-header", "NavHeader"],
  ["@/components/entity/hero-title", "HeroTitle"], ["@/components/entity/hero-stats", "HeroStats"],
  ["@/components/entity/radial-hero", "RadialHero"], ["@/components/entity/facts-panel", "FactsPanel"],
  ["@/components/entity/connections", "Connections"], ["@/components/entity/timeline-ribbon", "TimelineRibbon"],
  ["@/components/entity/editorial-callout", "EditorialCallout"], ["@/components/entity/evidence-drawer", "EvidenceDrawer"],
  ["@/components/shortcuts/recent-entity-tracker", "RecentEntityTracker"],
] as const) {
  vi.doMock(path, () => ({ [name]: () => null }));
}

const MARIN = "Marin County: latest report date observed: 2026-09-30";
const MARIN_EXPORTS = "Marin County exports: 2019–2024 downloaded 2026-04-14; 2025–2026 downloaded 2026-10-01";
const NOVATO_GAPS = "Novato: 2019–2021, 2025–2026 not available";
const NONE = "Campaign data coverage dates are not available for this build.";

afterEach(async () => {
  (await import("@/lib/server/substrate")).closeSubstrateDb();
  delete process.env.SUBSTRATE_DB_PATH;
  vi.resetModules();
});

async function withDb(published: boolean) {
  vi.resetModules();
  process.env.SUBSTRATE_DB_PATH = makeContributionFixtureDb(published ? { freshness: CAMPAIGN_FRESHNESS } : {});
}

function entity(id: string, type: EntityPayload["type"]): EntityPayload {
  return { id, type, properties: { id }, label: id, neighbors: [], edges: [], neighbor_total: 0,
           focus_event_date: null } as EntityPayload;
}

const surfaces: Record<string, () => Promise<React.ReactNode>> = {
  "/contributions": async () =>
    (await import("@/app/contributions/page")).default({ searchParams: Promise.resolve({}) }),
  "name view": async () =>
    (await import("@/app/contributions/by-name/[type]/[slug]/page")).default({
      params: Promise.resolve({ type: "person", slug: "able-sample" }),
    }),
};

describe("campaign freshness on every surface", () => {
  it.each(Object.keys(surfaces))("%s shows every source's freshness", async (name) => {
    await withDb(true);
    const { container } = render(await surfaces[name]());
    const text = container.textContent!;
    expect(text).toContain(MARIN);
    expect(text).toContain(MARIN_EXPORTS);
    expect(text).toContain(NOVATO_GAPS);
    expect(text).not.toMatch(/filings through/i);
  });

  it.each(Object.keys(surfaces))("%s renders safely without it (the current published artifact)", async (name) => {
    await withDb(false);
    const { container } = render(await surfaces[name]());
    expect(container.textContent).toContain(NONE);
  });

  it("a committee's ranking shows its own source's freshness", async () => {
    await withDb(true);
    const { CommitteeTopContributors } = await import("@/components/contributions/committee-top-contributors");
    const section = render(<>{CommitteeTopContributors({ committeeId: "committee-beta", committeePath: "/committee/beta", after: null })}</>);
    expect(section.container.textContent).toContain(NOVATO_GAPS);
    expect(section.container.textContent).not.toContain(MARIN);
  });

  it.each([
    ["committee-alpha", "Committee", MARIN],
    ["moneyflow-tie-a", "MoneyFlow", NOVATO_GAPS],
    ["moneyflow-expenditure", "MoneyFlow", MARIN],
  ] as const)("the %s page (%s facts) shows its source's freshness", async (id, type, expected) => {
    await withDb(true);
    const { EntityPage } = await import("@/components/entity/entity-page");
    const { container } = render(await EntityPage({ entity: entity(id, type) }));
    expect(container.textContent).toContain(expected);
    expect(container.querySelectorAll("[data-testid='campaign-freshness']")).toHaveLength(1); // once per page
  });

  it.each([
    ["committee-gamma", "Committee"], // outside every NetFile jurisdiction
    ["moneyflow-ocr", "MoneyFlow"], // a San Rafael OCR flow
    ["moneyflow-contract", "MoneyFlow"],
    ["person-able-sample", "Person"],
  ] as const)("the %s page shows none", async (id, type) => {
    await withDb(true);
    const { EntityPage } = await import("@/components/entity/entity-page");
    const { container } = render(await EntityPage({ entity: entity(id, type) }));
    expect(container.querySelector("[data-testid='campaign-freshness']")).toBeNull();
    expect(container.textContent).not.toContain("latest report date observed");
  });

  it("a NetFile committee page renders safely without it", async () => {
    await withDb(false);
    const { EntityPage } = await import("@/components/entity/entity-page");
    const { container } = render(await EntityPage({ entity: entity("committee-alpha", "Committee") }));
    expect(container.textContent).toContain(NONE);
  });
});
