import { render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { makeContributionFixtureDb } from "../../lib/server/contribution-fixtures";
import {
  COMMITTEE_CAPTION,
  COVERAGE_NOTE,
  DETAILS_DISCLAIMER,
  FORBIDDEN_WORDING,
  assertNoWithheldOrNodeValues,
  assertOnlyContributionLinks,
} from "../../app/contribution-surfaces";

vi.mock("@/lib/neo4j", () => ({ runQuery: vi.fn() }));

type Mod = typeof import("@/components/contributions/committee-top-contributors");
let mod: Mod;

beforeEach(async () => {
  vi.resetModules();
  process.env.SUBSTRATE_DB_PATH = makeContributionFixtureDb();
  mod = await import("@/components/contributions/committee-top-contributors");
});

afterEach(async () => {
  (await import("@/lib/server/substrate")).closeSubstrateDb();
  delete process.env.SUBSTRATE_DB_PATH;
});

async function renderSection(committeeId: string, after: string | null = null, pageSize?: number) {
  const ui = await mod.CommitteeTopContributors({ committeeId, committeePath: "/committee/x", after, pageSize });
  return render(<>{ui}</>);
}

function entryFor(container: HTMLElement, nameRoute: string): HTMLElement {
  const link = container.querySelector(`a[href="${nameRoute}"]`);
  expect(link, nameRoute).not.toBeNull();
  return link!.closest("tr")!;
}

describe("CommitteeTopContributors", () => {
  it("ranks names by total to this committee under the exact caption and labels", async () => {
    const { container } = await renderSection("committee-alpha");
    const section = container.querySelector("section[data-testid='committee-top-contributors']")!;
    expect(section.querySelector("caption")!.textContent).toBe(COMMITTEE_CAPTION);
    expect(section.textContent).toContain(COVERAGE_NOTE);
    expect(section.textContent).toContain(DETAILS_DISCLAIMER);

    const names = [...section.querySelectorAll("tbody > tr[data-testid='ranked-name']")];
    expect(names.map((tr) => tr.querySelector("a")!.textContent)).toEqual([
      "MANY SMALL",
      "ONE LARGE HOLDINGS LLC",
      "ABLE SAMPLE",
      "DUP PATH",
    ]);
    const totals = section.querySelectorAll("tbody [data-testid='contribution-total']");
    expect(totals).toHaveLength(4);
    expect(totals[0].textContent).toBe("$1,500.00May represent multiple people");
    expect(totals[1].textContent).toBe("$1,000.00May represent multiple organizations");

    const org = entryFor(container, "/contributions/by-name/organization/one-large");
    expect(org.textContent).toContain("Organization");
    expect(org.textContent).toContain("Not available in this dataset");
    const many = entryFor(container, "/contributions/by-name/person/many-small");
    expect(many.textContent).toContain("Individual");
    expect(many.textContent).toContain("30");
  });

  it("shows each name's own rows at this committee with their own details", async () => {
    const { container } = await renderSection("committee-alpha");
    const able = entryFor(container, "/contributions/by-name/person/able-sample");
    expect(able.textContent).toContain("$325.10");
    const rows = [...able.querySelectorAll("li[data-testid='ranked-row']")];
    expect(rows.map((li) => li.querySelector("a")!.getAttribute("href"))).toEqual([
      "/money-flow/able-refund",
      "/money-flow/able-2",
      "/money-flow/able-1",
    ]);
    expect(rows[0].textContent).toContain("−$25.00");
    expect(rows[1].textContent).toContain("Exampleville, CA 94998");
    expect(rows[1].textContent).not.toContain("Sampleton");
    expect(rows[2].textContent).toContain("Sampleton, CA 94999");
    // able-sample's gift to beta never appears here.
    expect(container.textContent).not.toContain("Demotown");
    expect(container.textContent).not.toContain("$60.00");
  });

  it("links only to name views and filing records, never to profiles or government business", async () => {
    for (const committee of ["committee-alpha", "committee-beta", "committee-gamma"]) {
      const { container, unmount } = await renderSection(committee);
      assertOnlyContributionLinks(container);
      assertNoWithheldOrNodeValues(container);
      expect(container.textContent).not.toMatch(FORBIDDEN_WORDING);
      expect(container.querySelector("a[href^='/person/'], a[href^='/organization/']")).toBeNull();
      unmount();
    }
  });

  it("pages by cursor with a link that keeps the committee path", async () => {
    const first = await renderSection("committee-beta", null, 2);
    const next = first.container.querySelector("a[data-testid='next-names']")!;
    expect(next.getAttribute("href")).toBe("/committee/x?contributors_after=30000%3Aperson-tie-b#top-contributors");
    first.unmount();

    const second = await renderSection("committee-beta", "30000:person-tie-b", 2);
    const ranks = [...second.container.querySelectorAll("tr[data-testid='ranked-name'] td:first-child")].map(
      (td) => td.textContent,
    );
    expect(ranks).toEqual(["3", "4"]);
    expect(second.container.querySelector("a[data-testid='first-names']")!.getAttribute("href")).toBe(
      "/committee/x#top-contributors",
    );
  });

  it("starts from the top when the cursor is malformed", async () => {
    const { container } = await renderSection("committee-beta", "junk", 2);
    expect(container.querySelector("tr[data-testid='ranked-name'] a")!.textContent).toBe("TIE ALPHA");
  });

  it("renders nothing for a committee without contributions", async () => {
    const { container } = await renderSection("committee-empty");
    expect(container.innerHTML).toBe("");
  });
});
