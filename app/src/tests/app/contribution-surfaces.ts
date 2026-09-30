// Shared assertions for the contribution surfaces' rendered output.
import { expect } from "vitest";
import { NODE_PROP_VALUES, WITHHELD_VALUES } from "../lib/server/contribution-fixtures";

export const COVERAGE_NOTE = "NetFile filings for Marin County and Novato; San Rafael not yet included";
export const DETAILS_DISCLAIMER =
  "As reported on each filing. Reports under this name vary; differences do not establish whether contributors are the same or different.";
export const COMMITTEE_CAPTION =
  "Totals group contributions reported under the same name to this committee; a name may represent multiple people.";

/** Pages a name group must never lead to: identities and government business. */
const FORBIDDEN_ROUTE = /^\/(person|organization|agreement|amendment|contract|decision|agenda-item|meeting|vote|seat|seat-service|filing|project)\//;
const ALLOWED_ROUTE = /^\/(committee\/|money-flow\/|contributions(\/|\?|#|$))|^\/(graph|data|about)?$/;

export function hrefsIn(container: HTMLElement): string[] {
  return [...container.querySelectorAll("a[href]")].map((a) => a.getAttribute("href")!);
}

/** Every link on the rendered surface, site navigation included. */
export function assertOnlyContributionLinks(container: HTMLElement) {
  const hrefs = hrefsIn(container);
  for (const href of hrefs) {
    expect(href, href).not.toMatch(FORBIDDEN_ROUTE);
    expect(href, href).toMatch(ALLOWED_ROUTE);
  }
}

export function assertNoWithheldOrNodeValues(container: HTMLElement) {
  const html = container.innerHTML;
  for (const needle of [...WITHHELD_VALUES, ...NODE_PROP_VALUES]) {
    expect(html).not.toContain(needle);
  }
}

/** Government-business, rollup and identity wording that never belongs beside a name group. */
export const FORBIDDEN_WORDING = /contract|verified money|verifies|verified by|rollup|same as|controlled|controls|self-contribution|\bvote|decision|agenda|payee|expenditure/i;
