import { render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { makeContributionFixtureDb } from "../lib/server/contribution-fixtures";
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
vi.mock("next/navigation", () => ({
  notFound: () => {
    throw new Error("NEXT_NOT_FOUND");
  },
}));

type PageModule = typeof import("@/app/contributions/by-name/[type]/[slug]/page");
let page: PageModule;

beforeEach(async () => {
  vi.resetModules();
  process.env.SUBSTRATE_DB_PATH = makeContributionFixtureDb();
  page = await import("@/app/contributions/by-name/[type]/[slug]/page");
});

afterEach(async () => {
  (await import("@/lib/server/substrate")).closeSubstrateDb();
  delete process.env.SUBSTRATE_DB_PATH;
});

const params = (type: string, slug: string) => ({ params: Promise.resolve({ type, slug }) });

async function renderView(type: string, slug: string) {
  const ui = await page.default(params(type, slug));
  return render(ui);
}

function rowFor(container: HTMLElement, flowSlug: string): HTMLElement {
  const link = container.querySelector(`a[href="/money-flow/${flowSlug}"]`);
  expect(link, flowSlug).not.toBeNull();
  return link!.closest("tr")!;
}

describe("/contributions/by-name/[type]/[slug]", () => {
  it("shows only contributions under the exact labels, each row with its own reported details", async () => {
    const { container } = await renderView("person", "able-sample");

    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Contributions reported under ABLE SAMPLE");
    expect(container.textContent).toContain(COVERAGE_NOTE);
    expect(container.textContent).toContain(DETAILS_DISCLAIMER);

    // Every total carries the label: the overall total and the two committee subtotals.
    const totals = container.querySelectorAll("[data-testid='contribution-total']");
    expect(totals).toHaveLength(3);
    for (const total of totals) expect(total.textContent).toContain("May represent multiple people");
    expect(totals[0].textContent).toContain("$385.10");

    // Two conflicting localities stay on their own rows.
    const sampleton = rowFor(container, "able-1");
    const exampleville = rowFor(container, "able-2");
    expect(sampleton.textContent).toContain("Sampleton, CA 94999");
    expect(sampleton.textContent).not.toContain("Exampleville");
    expect(exampleville.textContent).toContain("Exampleville, CA 94998");
    expect(exampleville.textContent).not.toContain("Sampleton");

    const refund = rowFor(container, "able-refund");
    expect(refund.textContent).toContain("−$25.00");
    expect(refund.textContent).toContain("Not available in this dataset");
    expect(within(refund).getByRole("link", { name: "Committee for Measure Alpha" }).getAttribute("href")).toBe(
      "/committee/alpha",
    );

    // Only the four reconciled contributions: the payment to this name and the OCR flow are absent.
    expect(container.querySelectorAll("tbody[data-testid='contribution-rows'] tr")).toHaveLength(4);
    expect(container.textContent).not.toContain("$900.00");
    expect(container.textContent).not.toContain("$5,000.00");
    expect(container.textContent).not.toMatch(FORBIDDEN_WORDING);
    assertOnlyContributionLinks(container);
    assertNoWithheldOrNodeValues(container);
  });

  it("says a name with no reported details has none in this dataset", async () => {
    const { container } = await renderView("person", "zero");
    expect(rowFor(container, "zero").textContent).toContain("Not available in this dataset");
    expect(container.textContent).toContain("$0.00");
  });

  it("never implies a self-contribution when the name also controls the recipient committee", async () => {
    const { container } = await renderView("person", "candidate");
    expect(container.textContent).toContain("Candidate Gamma for Council");
    expect(container.textContent).not.toMatch(FORBIDDEN_WORDING);
    expect(container.textContent).not.toMatch(/\bself\b|own committee|candidate's/i);
    assertOnlyContributionLinks(container);
  });

  it("shows an organization sharing a node with a contract recipient only its contributions", async () => {
    const { container } = await renderView("organization", "one-large");
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe(
      "Contributions reported under ONE LARGE HOLDINGS LLC",
    );
    for (const total of container.querySelectorAll("[data-testid='contribution-total']")) {
      expect(total.textContent).toContain("May represent multiple organizations");
    }
    expect(rowFor(container, "large").textContent).toContain("Not available in this dataset");
    expect(container.textContent).not.toMatch(FORBIDDEN_WORDING);
    expect(container.textContent).not.toMatch(/2,500|2,510|One Large Holdings\b(?! LLC)|Sample County/);
    assertOnlyContributionLinks(container);
  });

  it("never links a contributor to an official who shares the name", async () => {
    const { container } = await renderView("person", "pat-example-2");
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Contributions reported under PAT EXAMPLE");
    expect(container.querySelector("a[href^='/person/']")).toBeNull();
    expect(container.textContent).not.toMatch(FORBIDDEN_WORDING);
    assertOnlyContributionLinks(container);
  });

  it("keeps a contribution with no recipient committee, saying so", async () => {
    const { container } = await renderView("person", "orphan-giver");
    const row = rowFor(container, "orphan-giver");
    expect(row.querySelectorAll("td")[2].textContent).toBe("Not available in this dataset");
    expect(container.querySelectorAll("[data-testid='contribution-total']")).toHaveLength(1);
  });

  it("describes the node type as a recorded classification, not an identity", async () => {
    const person = await renderView("person", "many-small");
    expect(person.container.textContent).toContain("Recorded on the filings as an individual");
    expect(person.container.textContent).toContain("not a verified identity");
  });

  it.each([
    ["person", "ocr-only"], // only San Rafael OCR flows
    ["person", "official-only"],
    ["committee", "alpha"],
    ["money-flow", "able-1"],
    ["person", "nobody"],
  ])("404s for /%s/%s", async (type, slug) => {
    await expect(page.default(params(type, slug))).rejects.toThrow("NEXT_NOT_FOUND");
  });

  it("keeps the view out of search indexes with the exact title and description", async () => {
    const metadata = await page.generateMetadata(params("person", "able-sample"));
    expect(metadata.title).toBe("Contributions reported under ABLE SAMPLE");
    expect(metadata.description).toMatch(/^Contributions reported under ABLE SAMPLE/);
    expect(metadata.description).toContain("may represent multiple people");
    expect(metadata.robots).toEqual({ index: false, follow: true });
    expect(metadata).not.toHaveProperty("other");
  });

  it("gives an unknown name view noindex metadata too", async () => {
    const metadata = await page.generateMetadata(params("person", "nobody"));
    expect(metadata.robots).toEqual({ index: false, follow: true });
  });
});
