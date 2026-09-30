import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { makeContributionFixtureDb } from "../lib/server/contribution-fixtures";

vi.mock("@/lib/neo4j", () => ({ runQuery: vi.fn() }));

type PageModule = typeof import("@/app/[type]/[slug]/page");
let page: PageModule;

beforeEach(async () => {
  vi.resetModules();
  process.env.SUBSTRATE_DB_PATH = makeContributionFixtureDb();
  page = await import("@/app/[type]/[slug]/page");
});

afterEach(async () => {
  (await import("@/lib/server/substrate")).closeSubstrateDb();
  delete process.env.SUBSTRATE_DB_PATH;
});

const params = (type: string, slug: string) => ({ params: Promise.resolve({ type, slug }) });

describe("entity page metadata", () => {
  it.each([
    ["person", "many-small", "MANY SMALL", "people"],
    ["person", "evidenced", "EVIDENCED GIVER", "people"],
    ["person", "ocr-only", "OCR ONLY", "people"],
  ])("keeps the contributor-only page /%s/%s out of search indexes", async (type, slug, name, kind) => {
    const metadata = await page.generateMetadata(params(type, slug));
    expect(metadata.title).toBe(`Contributions reported under ${name}`);
    expect(metadata.description).toMatch(new RegExp(`^Contributions reported under ${name}.*may represent multiple ${kind}`));
    expect(metadata.robots).toEqual({ index: false, follow: true });
  });

  it.each([
    ["person", "able-sample"], // also a payee
    ["person", "candidate"], // controls a committee
    ["organization", "one-large"], // contract recipient
    ["person", "official-only"],
    ["committee", "alpha"],
    ["money-flow", "able-1"],
    ["person", "nobody"],
  ])("leaves /%s/%s with the site's default metadata", async (type, slug) => {
    expect(await page.generateMetadata(params(type, slug))).toEqual({});
  });
});
