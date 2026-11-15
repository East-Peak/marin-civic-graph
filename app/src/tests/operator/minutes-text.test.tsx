// @vitest-environment jsdom
// Operator-only minutes text search (/minutes): the server module and the page, against a fixture index with
// invented text. The index file is built by scripts/minutes_text_index.py; this mirrors its schema.
import Database from "better-sqlite3";
import { mkdtempSync, rmSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  coverageByBody,
  ftsQuery,
  loadMinutesPage,
  minutesTextDbPath,
  searchMinutes,
} from "../../../operator-workbench-src/_lib/minutes-text";
import MinutesPage from "../../../operator-workbench-src/minutes/page";

const SCHEMA = `
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE pages (id INTEGER PRIMARY KEY, meeting_id TEXT NOT NULL, source TEXT NOT NULL, body TEXT NOT NULL,
    meeting_date TEXT NOT NULL, page INTEGER NOT NULL, text TEXT NOT NULL, official_url TEXT,
    source_sha256 TEXT NOT NULL, UNIQUE (meeting_id, page));
CREATE VIRTUAL TABLE pages_fts USING fts5(text, content='pages', content_rowid='id',
    tokenize='unicode61 remove_diacritics 2');
CREATE TABLE coverage (meeting_id TEXT PRIMARY KEY, source TEXT NOT NULL, body TEXT NOT NULL,
    meeting_date TEXT NOT NULL, minutes_url TEXT, state TEXT NOT NULL);
CREATE TABLE dispositions (path TEXT PRIMARY KEY, source TEXT NOT NULL, meeting_id TEXT, sha256 TEXT,
    disposition TEXT NOT NULL, reason TEXT);`;

let dir: string;
let dbPath: string;

function buildFixture(file: string) {
  const db = new Database(file);
  db.exec(SCHEMA);
  db.prepare("INSERT INTO meta VALUES ('schema', 'minutes-text-v1'), ('substrate_as_of_date', '2030-01-09')").run();
  const page = db.prepare(
    "INSERT INTO pages (meeting_id, source, body, meeting_date, page, text, official_url, source_sha256) " +
      "VALUES (?, 'sa', ?, ?, ?, ?, ?, 'abc')",
  );
  page.run("m-old", "Fernwood Town Council", "2028-02-01", 3,
    "Council discussed the Willow Glade picnic lot layout.\nThe vote was 4-1.", "https://town.example/old");
  page.run("m-new", "Fernwood Town Council", "2029-05-05", 1,
    "Opening remarks about the library roof.", "https://town.example/new");
  page.run("m-new", "Fernwood Town Council", "2029-05-05", 7,
    "Staff presented a revised Willow Glade picnic lot with fewer spaces.", "https://town.example/new");
  page.run("m-parks", "Fernwood Parks Commission", "2029-01-10", 2,
    "The commission toured the Willow Glade picnic lot.", "https://town.example/parks");
  db.exec("INSERT INTO pages_fts (pages_fts) VALUES ('rebuild')");
  const cov = db.prepare("INSERT INTO coverage VALUES (?, 'sa', ?, ?, ?, ?)");
  cov.run("m-old", "Fernwood Town Council", "2028-02-01", "https://town.example/old", "indexed");
  cov.run("m-new", "Fernwood Town Council", "2029-05-05", "https://town.example/new", "indexed");
  cov.run("m-gap", "Fernwood Town Council", "2027-11-11", "https://town.example/gap", "not cached");
  cov.run("m-scan", "Fernwood Town Council", "2027-12-12", "https://town.example/scan", "no-text");
  cov.run("m-parks", "Fernwood Parks Commission", "2029-01-10", "https://town.example/parks", "indexed");
  db.close();
}

function openFixture() {
  return new Database(dbPath, { readonly: true, fileMustExist: true });
}

beforeEach(() => {
  dir = mkdtempSync(path.join(os.tmpdir(), "open-marin-minutes-text-"));
  dbPath = path.join(dir, "minutes-text.sqlite");
  buildFixture(dbPath);
  vi.stubEnv("MINUTES_TEXT_DB_PATH", dbPath);
  vi.stubEnv("OPERATOR_WORKBENCH", "1");
  vi.stubEnv("VERCEL", "");
  vi.stubEnv("VERCEL_ENV", "");
});

afterEach(() => {
  vi.unstubAllEnvs();
  rmSync(dir, { recursive: true, force: true });
});

describe("minutes text index path", () => {
  it("comes from MINUTES_TEXT_DB_PATH", () => {
    expect(minutesTextDbPath()).toBe(dbPath);
  });

  it("defaults to the research location outside every repo", () => {
    vi.stubEnv("MINUTES_TEXT_DB_PATH", "");
    expect(minutesTextDbPath()).toBe(path.join(os.homedir(), "open-marin-research", "minutes-text.sqlite"));
  });
});

describe("ftsQuery", () => {
  it("requires every word and keeps quoted phrases, never interpreting FTS syntax", () => {
    expect(ftsQuery('Willow Glade "picnic lot"')).toBe('"Willow" AND "Glade" AND "picnic lot"');
    expect(ftsQuery("NEAR( a* OR b")).toBe('"NEAR" AND "a" AND "OR" AND "b"');
    expect(ftsQuery("   ")).toBeNull();
  });
});

describe("searchMinutes", () => {
  it("groups page hits by meeting, newest meeting first, pages in order", () => {
    const db = openFixture();
    try {
      const { results, truncated } = searchMinutes(db, "Willow Glade picnic lot");
      expect(truncated).toBe(false);
      expect(results.map((r) => r.meetingId)).toEqual(["m-new", "m-parks", "m-old"]);
      expect(results[0]).toMatchObject({
        body: "Fernwood Town Council",
        meetingDate: "2029-05-05",
        officialUrl: "https://town.example/new",
      });
      expect(results[0].hits.map((h) => h.page)).toEqual([7]);
      expect(results[2].hits[0].snippet).toContain("\u0002Willow\u0003");
    } finally {
      db.close();
    }
  });

  it("returns nothing for an empty query or no match", () => {
    const db = openFixture();
    try {
      expect(searchMinutes(db, "  ")).toEqual({ results: [], truncated: false });
      expect(searchMinutes(db, "zeppelin")).toEqual({ results: [], truncated: false });
    } finally {
      db.close();
    }
  });
});

describe("searchMinutes truncation", () => {
  it("says when more pages matched than it returns, so counts never look exhaustive", () => {
    const db = openFixture();
    try {
      const { results, truncated } = searchMinutes(db, "Willow", 2);
      expect(truncated).toBe(true);
      expect(results.flatMap((r) => r.hits)).toHaveLength(2);
      expect(searchMinutes(db, "Willow", 3).truncated).toBe(false);
    } finally {
      db.close();
    }
  });
});

describe("coverageByBody", () => {
  it("gives each body's date range and its count in every state", () => {
    const db = openFixture();
    try {
      expect(coverageByBody(db)).toEqual([
        { body: "Fernwood Parks Commission", first: "2029-01-10", last: "2029-01-10",
          counts: { indexed: 1, "not cached": 0, "no-text": 0, quarantined: 0, unmapped: 0 } },
        { body: "Fernwood Town Council", first: "2027-11-11", last: "2029-05-05",
          counts: { indexed: 2, "not cached": 1, "no-text": 1, quarantined: 0, unmapped: 0 } },
      ]);
    } finally {
      db.close();
    }
  });
});

describe("loadMinutesPage", () => {
  it("says the index is absent rather than failing", () => {
    vi.stubEnv("MINUTES_TEXT_DB_PATH", path.join(dir, "missing.sqlite"));
    expect(loadMinutesPage("anything")).toEqual({ status: "absent", path: path.join(dir, "missing.sqlite") });
  });

  it("returns results and coverage when the index exists", () => {
    const page = loadMinutesPage("library roof");
    expect(page.status).toBe("ok");
    if (page.status !== "ok") return;
    expect(page.asOf).toBe("2030-01-09");
    expect(page.results.map((r) => r.meetingId)).toEqual(["m-new"]);
    expect(page.coverage).toHaveLength(2);
  });
});

describe("/minutes page", () => {
  async function renderPage(q?: string) {
    const ui = await MinutesPage({ searchParams: Promise.resolve(q === undefined ? {} : { q }) });
    return render(ui);
  }

  it("shows each meeting's body, date, passage with the match, page number and official link", async () => {
    await renderPage("Willow Glade picnic lot");
    const items = screen.getAllByRole("article");
    expect(items).toHaveLength(3);
    const first = within(items[0]);
    expect(first.getByText("Fernwood Town Council")).toBeInTheDocument();
    expect(first.getByText("2029-05-05")).toBeInTheDocument();
    expect(first.getByText(/page 7/)).toBeInTheDocument();
    expect(first.getAllByText("Willow")[0].tagName).toBe("MARK");
    expect(first.getByRole("link", { name: /official document/i })).toHaveAttribute(
      "href", "https://town.example/new");
    expect(screen.getByText(/3 meetings/)).toBeInTheDocument();
    expect(screen.queryByText(/only the first/i)).not.toBeInTheDocument();
  });

  it("states coverage per body so no results is distinguishable from not covered", async () => {
    await renderPage("zeppelin");
    expect(screen.getByText(/no matches/i)).toBeInTheDocument();
    const table = screen.getByRole("table");
    const row = within(table).getByText("Fernwood Town Council").closest("tr")!;
    expect(within(row).getByText("2027-11-11 – 2029-05-05")).toBeInTheDocument();
    expect(row.textContent).toContain("2");
  });

  it("says plainly when the index file is absent", async () => {
    vi.stubEnv("MINUTES_TEXT_DB_PATH", path.join(dir, "missing.sqlite"));
    await renderPage("anything");
    expect(screen.getByText(/minutes text index is not built/i)).toBeInTheDocument();
  });
});
