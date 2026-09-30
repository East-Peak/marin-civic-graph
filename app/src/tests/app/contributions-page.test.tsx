import { render, screen, type RenderResult } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CONTRIBUTION_COUNT, CONTRIBUTION_TOTAL_CENTS, makeContributionFixtureDb } from "../lib/server/contribution-fixtures";
import {
  COVERAGE_NOTE,
  DETAILS_DISCLAIMER,
  FORBIDDEN_WORDING,
  assertNoWithheldOrNodeValues,
  assertOnlyContributionLinks,
} from "./contribution-surfaces";

vi.mock("@/lib/neo4j", () => ({ runQuery: vi.fn() }));
vi.mock("@/lib/server/homepage-data", () => ({
  loadStatus: vi.fn(async () => ({
    connected: true,
    node_count: 1,
    edge_count: 1,
    jurisdiction_count: 1,
    ingest_at: null,
    subgraphs_built_at: null,
  })),
}));

type PageModule = typeof import("@/app/contributions/page");
type TableModule = typeof import("@/components/contributions/largest-contributions");
let page: PageModule;
let table: TableModule;

beforeEach(async () => {
  vi.resetModules();
  process.env.SUBSTRATE_DB_PATH = makeContributionFixtureDb();
  page = await import("@/app/contributions/page");
  table = await import("@/components/contributions/largest-contributions");
});

afterEach(async () => {
  (await import("@/lib/server/substrate")).closeSubstrateDb();
  delete process.env.SUBSTRATE_DB_PATH;
});

const search = (params: Record<string, string> = {}) => ({ searchParams: Promise.resolve(params) });

function dollars(text: string): number {
  const negative = text.startsWith("−");
  const cents = Math.round(Number(text.replace(/[−$,]/g, "")) * 100);
  return negative ? -cents : cents;
}

describe("/contributions", () => {
  it("lists the largest contributions under the coverage note and details disclaimer", async () => {
    const { container } = render(await page.default(search()));
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Largest contributions");
    expect(container.textContent).toContain(`${CONTRIBUTION_COUNT} contributions`);
    expect(container.textContent).toContain(COVERAGE_NOTE);
    expect(container.textContent).toContain(DETAILS_DISCLAIMER);

    const rows = [...container.querySelectorAll("tr[data-testid='contribution-row']")];
    expect(rows).toHaveLength(CONTRIBUTION_COUNT);
    const first = rows[0];
    expect(first.querySelector("a[href='/contributions/by-name/organization/one-large']")!.textContent).toBe(
      "ONE LARGE HOLDINGS LLC",
    );
    expect(first.textContent).toContain("Recorded as an organization");
    expect(first.querySelector("a[href='/committee/alpha']")!.textContent).toBe("Committee for Measure Alpha");
    expect(first.querySelector("a[href='/money-flow/large']")).not.toBeNull();
    expect(first.textContent).toContain("2024-01-15");
    expect(first.textContent).toContain("$1,000.00");
    expect(first.textContent).toContain("Not available in this dataset");

    const able = rows.find((tr) => tr.querySelector("a[href='/money-flow/able-2']"))!;
    expect(able.textContent).toContain("Exampleville, CA 94998");
    expect(able.textContent).not.toContain("Sampleton");
    expect(rows.at(-1)!.textContent).toContain("−$25.00");

    for (const row of rows) {
      expect(row.querySelector("a[href^='/contributions/by-name/']")).not.toBeNull();
      expect(row.querySelector("a[href^='/committee/']")).not.toBeNull();
      expect(row.querySelector("a[href^='/money-flow/']")).not.toBeNull();
      expect(row.querySelector("[data-testid='row-date']")!.textContent).toMatch(/^\d{4}-\d{2}-\d{2}$/);
      expect(row.querySelector("[data-testid='row-amount']")!.textContent).toMatch(/^−?\$[\d,]+\.\d{2}$/);
    }
    expect(container.textContent).not.toMatch(FORBIDDEN_WORDING);
    assertOnlyContributionLinks(container);
    assertNoWithheldOrNodeValues(container);
  });

  it("pages by amount then id through every contribution exactly once", async () => {
    const seen: string[] = [];
    let cents = 0;
    let after: string | null = null;
    let pages = 0;
    do {
      const { container, unmount }: RenderResult = render(table.LargestContributions({ after, pageSize: 10 }));
      pages += 1;
      for (const row of container.querySelectorAll("tr[data-testid='contribution-row']")) {
        seen.push(row.querySelector("a[href^='/money-flow/']")!.getAttribute("href")!);
        cents += dollars(row.querySelector("[data-testid='row-amount']")!.textContent!);
      }
      const next: Element | null = container.querySelector("a[data-testid='next-contributions']");
      after = next ? new URL(next.getAttribute("href")!, "http://x").searchParams.get("after") : null;
      if (pages > 1) expect(container.querySelector("a[data-testid='first-contributions']")).not.toBeNull();
      unmount();
    } while (after);
    expect(pages).toBe(5);
    expect(seen).toHaveLength(CONTRIBUTION_COUNT);
    expect(new Set(seen).size).toBe(CONTRIBUTION_COUNT);
    expect(cents).toBe(CONTRIBUTION_TOTAL_CENTS);
  });

  it("starts from the top when the cursor is malformed", async () => {
    const { container } = render(await page.default(search({ after: "junk" })));
    expect(container.querySelector("tr[data-testid='contribution-row'] a[href='/money-flow/large']")).not.toBeNull();
  });

  it("stays indexable, with a plain title and description", async () => {
    const metadata = page.metadata;
    expect(metadata.title).toBe("Largest contributions");
    expect(metadata.description).toContain("Marin County and Novato");
    expect(metadata).not.toHaveProperty("robots");
  });
});
