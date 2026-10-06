import { afterEach, describe, expect, it } from "vitest";
import { CAMPAIGN_FRESHNESS, makeContributionFixtureDb } from "./contribution-fixtures";

async function load(freshness?: unknown) {
  process.env.SUBSTRATE_DB_PATH = makeContributionFixtureDb(freshness === undefined ? {} : { freshness });
  return import("@/lib/server/campaign-freshness");
}

afterEach(async () => {
  (await import("@/lib/server/substrate")).closeSubstrateDb();
  delete process.env.SUBSTRATE_DB_PATH;
});

describe("campaign freshness from the bake", () => {
  it("reads the fields the bake published", async () => {
    const { loadCampaignFreshness } = await load(CAMPAIGN_FRESHNESS);
    expect(loadCampaignFreshness()).toEqual(CAMPAIGN_FRESHNESS);
  });

  it("is null for an artifact baked without it (the current published one)", async () => {
    const { loadCampaignFreshness } = await load();
    expect(loadCampaignFreshness()).toBeNull();
  });

  it.each([
    ["not JSON", "{oops"],
    ["no sources", { bundle_id: "x" }],
    ["a source without dates", { bundle_id: "x", sources: [{ name: "Example", jurisdiction_id: "place-x" }] }],
    ["a year that is not a year", { ...CAMPAIGN_FRESHNESS, sources: [{ ...CAMPAIGN_FRESHNESS.sources[1], unavailable_years: ["soon"] }] }],
  ])("is null, never a guess, for a malformed value (%s)", async (_, value) => {
    const { loadCampaignFreshness } = await load(value);
    expect(loadCampaignFreshness()).toBeNull();
  });

  it("finds the jurisdictions of a committee and of a NetFile money flow through its committee", async () => {
    const { campaignJurisdictions } = await load(CAMPAIGN_FRESHNESS);
    expect(campaignJurisdictions("committee-alpha")).toEqual(["place-marin-county"]);
    expect(campaignJurisdictions("moneyflow-able-1")).toEqual(["place-marin-county"]); // contribution: flow -> committee
    expect(campaignJurisdictions("moneyflow-expenditure")).toEqual(["place-marin-county"]); // committee -> flow
    expect(campaignJurisdictions("moneyflow-tie-a")).toEqual(["place-novato"]);
    expect(campaignJurisdictions("committee-gamma")).toEqual([]);
    expect(campaignJurisdictions("moneyflow-ocr")).toEqual([]); // San Rafael OCR flows are not NetFile exports
    expect(campaignJurisdictions("moneyflow-contract")).toEqual([]);
  });
});
