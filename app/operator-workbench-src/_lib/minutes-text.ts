// Operator-only server module: read-only full-text search over the minutes text index
// (scripts/minutes_text_index.py). Lives inside the build-excluded operator route group, so a public or
// CI build contains neither this reader nor any response carrying minutes text — minutes name private
// people (public commenters, applicants, litigants).
//
// The index lives outside every repo (MINUTES_TEXT_DB_PATH, default ~/open-marin-research/minutes-text.sqlite)
// and is opened per request, read-only (substrate.ts conventions): a rebuild atomically replaces the file,
// so a cached handle would keep reading the old one. A missing file is a state, never an error.
import "server-only";

import Database from "better-sqlite3";
import { existsSync } from "node:fs";
import os from "node:os";
import path from "node:path";

export const COVERAGE_STATES = ["indexed", "not cached", "no-text", "quarantined", "unmapped"] as const;
export type CoverageState = (typeof COVERAGE_STATES)[number];

/** Snippet match markers (control characters: they cannot occur in the extracted text). */
export const MARK_START = "\u0002";
export const MARK_END = "\u0003";

export type PageHit = { page: number; snippet: string };
export type MeetingResult = {
  meetingId: string;
  body: string;
  meetingDate: string;
  officialUrl: string | null;
  hits: PageHit[];
};
export type BodyCoverage = { body: string; first: string; last: string; counts: Record<CoverageState, number> };
export type MinutesPageData =
  | { status: "absent"; path: string }
  | { status: "ok"; asOf: string; query: string; results: MeetingResult[]; coverage: BodyCoverage[] };

const MAX_PAGE_HITS = 400;

export function minutesTextDbPath(): string {
  const configured = process.env.MINUTES_TEXT_DB_PATH;
  if (configured && configured.trim() !== "") return path.resolve(configured);
  return path.join(os.homedir(), "open-marin-research", "minutes-text.sqlite");
}

/** Every word (or "quoted phrase") must be on the page; FTS syntax in the input is never interpreted.
 * Mirrors minutes_text_index.fts_query. */
export function ftsQuery(q: string): string | null {
  const terms = [...q.matchAll(/"([^"]+)"|(\S+)/g)]
    .map((m) => (m[1] ?? m[2]).replace(/[^\p{L}\p{N}_\s'-]/gu, " ").trim())
    .filter((t) => t !== "");
  return terms.length ? terms.map((t) => `"${t}"`).join(" AND ") : null;
}

type HitRow = {
  meeting_id: string;
  body: string;
  meeting_date: string;
  official_url: string | null;
  page: number;
  snippet: string;
};

export function searchMinutes(db: Database.Database, q: string): MeetingResult[] {
  const match = ftsQuery(q);
  if (!match) return [];
  const rows = db
    .prepare(
      `SELECT p.meeting_id, p.body, p.meeting_date, p.official_url, p.page,
              snippet(pages_fts, 0, '${MARK_START}', '${MARK_END}', '…', 28) AS snippet
         FROM pages_fts JOIN pages p ON p.id = pages_fts.rowid
        WHERE pages_fts MATCH ?
        ORDER BY p.meeting_date DESC, p.meeting_id, p.page
        LIMIT ?`,
    )
    .all(match, MAX_PAGE_HITS) as HitRow[];
  const byMeeting = new Map<string, MeetingResult>();
  for (const r of rows) {
    let m = byMeeting.get(r.meeting_id);
    if (!m) {
      m = { meetingId: r.meeting_id, body: r.body, meetingDate: r.meeting_date, officialUrl: r.official_url, hits: [] };
      byMeeting.set(r.meeting_id, m);
    }
    m.hits.push({ page: r.page, snippet: r.snippet.replace(/\s+/g, " ").trim() });
  }
  return [...byMeeting.values()];
}

export function coverageByBody(db: Database.Database): BodyCoverage[] {
  const rows = db
    .prepare(
      `SELECT body, state, MIN(meeting_date) AS first, MAX(meeting_date) AS last, COUNT(*) AS n
         FROM coverage GROUP BY body, state ORDER BY body`,
    )
    .all() as { body: string; state: CoverageState; first: string; last: string; n: number }[];
  const out = new Map<string, BodyCoverage>();
  for (const r of rows) {
    let b = out.get(r.body);
    if (!b) {
      b = { body: r.body, first: r.first, last: r.last,
        counts: Object.fromEntries(COVERAGE_STATES.map((s) => [s, 0])) as Record<CoverageState, number> };
      out.set(r.body, b);
    }
    b.first = r.first < b.first ? r.first : b.first;
    b.last = r.last > b.last ? r.last : b.last;
    b.counts[r.state] = (b.counts[r.state] ?? 0) + r.n;
  }
  return [...out.values()];
}

export function loadMinutesPage(query: string): MinutesPageData {
  const file = minutesTextDbPath();
  if (!existsSync(file)) return { status: "absent", path: file };
  const db = new Database(file, { readonly: true, fileMustExist: true });
  try {
    const asOf = (db.prepare("SELECT value FROM meta WHERE key = 'substrate_as_of_date'").get() as
      | { value: string }
      | undefined)?.value ?? "";
    return { status: "ok", asOf, query, results: searchMinutes(db, query), coverage: coverageByBody(db) };
  } finally {
    db.close();
  }
}
