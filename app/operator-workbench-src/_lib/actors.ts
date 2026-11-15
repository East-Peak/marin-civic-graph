// Operator-only server module: read-only views over the actor index (scripts/actor_index.py). Lives inside the
// build-excluded operator route group, so a public or CI build contains neither this reader nor any page built
// from it: the index names people in public roles (officers, attorneys, parties) and is research, not publication.
//
// The index lives outside every repo (ACTORS_DB_PATH, default ~/open-marin-research/actors.sqlite) and is opened
// per request, read-only: a rebuild atomically replaces the file. A missing file is a state, never an error.
import "server-only";

import Database from "better-sqlite3";
import { existsSync } from "node:fs";
import os from "node:os";
import path from "node:path";

/** Attachments that count (id, EIN, reviewed pattern, reviewed role, the ledger's own body). Mirrors
 * actor_index.CONFIRMED; everything else is a possible match. */
export const CONFIRMED = ["substrate_id", "ein", "pattern_reviewed", "reviewed_role", "ledger_body"] as const;
export const SIDE_UNKNOWN = "side not established";
/** Rows shown per section; totals always cover every row. */
export const SECTION_ROW_LIMIT = 200;

export const KIND_ORDER = [
  "board_item", "delegated_contract", "reported_grant", "own_return", "officer", "political_gift", "agenda_item",
  "case_role", "docket_appearance", "minutes_mentions",
] as const;
export type FactKind = (typeof KIND_ORDER)[number];

export const KIND_TITLES: Record<FactKind, string> = {
  board_item: "Board of Supervisors items (amounts as stated in the item)",
  delegated_contract: "Delegated contracts (contract ceilings)",
  reported_grant: "Reported grants (Form 990 Schedule I)",
  own_return: "Own returns (Form 990)",
  officer: "Officers listed on Form 990",
  political_gift: "Political contributions (as reported)",
  agenda_item: "Agenda items naming the actor",
  case_role: "Case roles (reviewed)",
  docket_appearance: "Docket appearances (side not established)",
  minutes_mentions: "Minutes mentions (page counts)",
};

/** Which coverage inputs answer "is this kind covered at all?" for a section. */
export const KIND_COVERAGE: Record<FactKind, string[]> = {
  board_item: ["board_ledger"],
  delegated_contract: ["delegated_contracts", "city_contracts"],
  reported_grant: ["form_990"],
  own_return: ["form_990_registry"],
  officer: ["form_990_registry"],
  political_gift: ["political_gifts"],
  agenda_item: ["agenda_items"],
  case_role: ["dockets"],
  docket_appearance: ["dockets"],
  minutes_mentions: ["minutes"],
};

export type ActorRow = {
  slug: string; name: string; kind: string; registered: number; public_body: number; reviewed: number;
  public_role: string | null; substrate_ids: string; eins: string; affiliated_with: string; patterns: string;
  organization_slug: string | null;
};
export type Fact = {
  fact_key: string; actor_slug: string | null; actor_name: string; kind: FactKind; counterparty_name: string | null;
  counterparty_slug: string | null; metric: string | null; amount: number | null; direction: string | null;
  date: string | null; date_kind: string; source_ref: string; source_url: string | null; quote: string | null;
  label: string; identity_basis: string; counterparty_basis: string | null; assertion_status: string;
  repeat_of: string | null; detail: string;
};
export type Total = { side: string; kind: string; metric: string; direction: string; n: number; amount: number;
  note: string | null };
export type YearRow = { side: string; year: string; kind: string; metric: string; direction: string; n: number;
  amount: number | null };
export type CoverageRow = { input: string; item: string; state: string; detail: string };
export type Hop = { kind: string; metric: string | null; from: string; to: string; label: string;
  sources: { fact_key: string; label: string; source_ref: string; date: string | null; date_kind: string;
    amount: number | null; metric: string | null }[] };
export type Connection = { connection_id: string; form: string; label: string; actors: string[]; hops: Hop[];
  person_identity: string | null };
export type CaseRow = { docket: string; court: string | null; caption: string | null; filed: string | null;
  closed: string | null; cause: string | null; courtlistener_url: string | null; parties: string[];
  attorneys: string[]; firms: string[]; attorney_note: string | null; roles_reviewed: number;
  outcome_kind: string | null; outcome_date: string | null; outcome_evidence: string | null };
export type Searched = { forms: string[]; reviewed_cases: number; commitments: number; reported_grants: number;
  officer_rows: number };

export type Section = { kind: FactKind; title: string; rows: Fact[]; total: number; page: number; pageSize: number;
  totals: Total[]; coverage: CoverageRow[] };
/** Which section is paged (the others show their first page); "possible" pages the possible matches. */
export type PageOptions = { section?: string; page?: number; pageSize?: number };
export type ListEntry = { slug: string; name: string; kind: string; counts: Partial<Record<FactKind, number>>;
  possible: number };
export type Absent = { status: "absent"; path: string };
export type ActorListData = Absent | { status: "ok"; asOf: string; groups: { kind: string; actors: ListEntry[] }[] };
export type ActorPageData =
  | Absent
  | { status: "not_found"; slug: string }
  | { status: "ok"; asOf: string; actor: ActorRow; organization: ActorRow | null; affiliations: ActorRow[];
      people: ActorRow[]; byYear: YearRow[]; sections: Section[]; possible: Fact[]; possibleTotal: number;
      possiblePage: number; pageSize: number; caseRoles: Fact[];
      connections: Connection[]; searched: Searched | null; coverage: CoverageRow[]; names: Record<string, string> };
export type CasePageData =
  | Absent
  | { status: "not_found"; docket: string }
  | { status: "ok"; asOf: string; case: CaseRow; roles: Fact[]; appearances: Fact[]; names: Record<string, string> };

export function actorsDbPath(): string {
  const configured = process.env.ACTORS_DB_PATH;
  if (configured && configured.trim() !== "") return path.resolve(configured);
  return path.join(os.homedir(), "open-marin-research", "actors.sqlite");
}

const IN_CONFIRMED = `(${CONFIRMED.map((c) => `'${c}'`).join(", ")})`;

function withDb<T>(fn: (db: Database.Database, asOf: string) => T): T | Absent {
  const file = actorsDbPath();
  if (!existsSync(file)) return { status: "absent", path: file };
  const db = new Database(file, { readonly: true, fileMustExist: true });
  try {
    const asOf = (db.prepare("SELECT value FROM meta WHERE key = 'substrate_as_of_date'").get() as
      | { value: string } | undefined)?.value ?? "";
    return fn(db, asOf);
  } finally {
    db.close();
  }
}

export function isConfirmed(basis: string | null): boolean {
  return basis !== null && (CONFIRMED as readonly string[]).includes(basis);
}

export function loadActorList(): ActorListData {
  return withDb((db, asOf) => {
    const actors = db.prepare("SELECT * FROM actors WHERE registered = 1 ORDER BY kind, name").all() as ActorRow[];
    const counts = db.prepare(
      `SELECT slug, kind, COUNT(*) AS n FROM (
         SELECT actor_slug AS slug, kind FROM facts WHERE identity_basis IN ${IN_CONFIRMED}
         UNION ALL SELECT counterparty_slug, kind FROM facts
           WHERE counterparty_slug IS NOT actor_slug AND counterparty_basis IN ${IN_CONFIRMED})
       WHERE slug IS NOT NULL GROUP BY slug, kind`,
    ).all() as { slug: string; kind: FactKind; n: number }[];
    const possible = db.prepare(
      `SELECT slug, COUNT(*) AS n FROM (
         SELECT actor_slug AS slug FROM facts WHERE identity_basis NOT IN ${IN_CONFIRMED}
         UNION ALL SELECT counterparty_slug FROM facts
           WHERE counterparty_basis NOT IN ${IN_CONFIRMED} AND counterparty_basis <> 'stated_name')
       WHERE slug IS NOT NULL GROUP BY slug`,
    ).all() as { slug: string; n: number }[];
    const groups = new Map<string, ListEntry[]>();
    for (const a of actors) {
      const entry: ListEntry = { slug: a.slug, name: a.name, kind: a.kind, possible: 0,
        counts: Object.fromEntries(counts.filter((c) => c.slug === a.slug).map((c) => [c.kind, c.n])) };
      entry.possible = possible.find((p) => p.slug === a.slug)?.n ?? 0;
      groups.set(a.kind, [...(groups.get(a.kind) ?? []), entry]);
    }
    return { status: "ok" as const, asOf, groups: [...groups].map(([kind, list]) => ({ kind, actors: list })) };
  });
}

function parseConnection(r: { connection_id: string; form: string; label: string; actors: string; hops: string;
  person_identity: string | null }): Connection {
  return { ...r, actors: JSON.parse(r.actors) as string[], hops: JSON.parse(r.hops) as Hop[] };
}

function namesFor(db: Database.Database): Record<string, string> {
  const rows = db.prepare("SELECT slug, name FROM actors").all() as { slug: string; name: string }[];
  return Object.fromEntries(rows.map((r) => [r.slug, r.name]));
}

export function loadActorPage(slug: string, opts: PageOptions = {}): ActorPageData {
  const pageSize = opts.pageSize ?? SECTION_ROW_LIMIT;
  const pageOf = (name: string) => (opts.section === name && opts.page && opts.page > 1 ? Math.floor(opts.page) : 1);
  return withDb((db, asOf) => {
    const actor = db.prepare("SELECT * FROM actors WHERE slug = ?").get(slug) as ActorRow | undefined;
    if (!actor) return { status: "not_found" as const, slug };
    // An officer row is the officer entry's own record (the entry was made from that row's name), so it shows there.
    const byKind = db.prepare(
      `SELECT * FROM facts WHERE kind = ? AND (
         (actor_slug = @slug AND identity_basis IN ${IN_CONFIRMED})
         OR (counterparty_slug = @slug AND (counterparty_basis IN ${IN_CONFIRMED} OR kind = 'officer')))
       ORDER BY date DESC, fact_key LIMIT @limit OFFSET @offset`);
    const countKind = db.prepare(
      `SELECT COUNT(*) AS n FROM facts WHERE kind = ? AND (
         (actor_slug = @slug AND identity_basis IN ${IN_CONFIRMED})
         OR (counterparty_slug = @slug AND (counterparty_basis IN ${IN_CONFIRMED} OR kind = 'officer')))`);
    const totals = db.prepare("SELECT * FROM totals WHERE actor_slug = ? AND kind = ? ORDER BY side, metric, direction");
    const coverage = db.prepare("SELECT * FROM coverage WHERE input = ? ORDER BY item");
    const sections: Section[] = KIND_ORDER.map((kind) => {
      const cov = KIND_COVERAGE[kind].flatMap((input) =>
        (coverage.all(input) as CoverageRow[]).filter((c) => input !== "form_990_registry" || c.item === slug));
      const page = pageOf(kind);
      return {
        kind, title: KIND_TITLES[kind], page, pageSize,
        rows: byKind.all(kind, { slug, limit: pageSize, offset: (page - 1) * pageSize }) as Fact[],
        total: (countKind.get(kind, { slug }) as { n: number }).n,
        totals: totals.all(slug, kind) as Total[],
        coverage: cov, // for reported grants: every filer whose returns were searched, with years and gaps
      };
    });
    const possibleWhere = `(actor_slug = @slug AND identity_basis NOT IN ${IN_CONFIRMED})
         OR (counterparty_slug = @slug AND counterparty_basis NOT IN ${IN_CONFIRMED}
             AND counterparty_basis <> 'stated_name')`;
    const possiblePage = pageOf("possible");
    const possible = db.prepare(`SELECT * FROM facts WHERE ${possibleWhere}
       ORDER BY kind, date DESC, fact_key LIMIT @limit OFFSET @offset`)
      .all({ slug, limit: pageSize, offset: (possiblePage - 1) * pageSize }) as Fact[];
    const possibleTotal = (db.prepare(`SELECT COUNT(*) AS n FROM facts WHERE ${possibleWhere}`).get({ slug }) as
      { n: number }).n;
    const affiliated = JSON.parse(actor.affiliated_with) as string[];
    const affiliations = affiliated.length
      ? db.prepare(`SELECT * FROM actors WHERE slug IN (${affiliated.map(() => "?").join(", ")}) ORDER BY name`)
          .all(...affiliated) as ActorRow[]
      : [];
    const people = db.prepare("SELECT * FROM actors WHERE organization_slug = ? ORDER BY name").all(slug) as ActorRow[];
    const organization = actor.organization_slug
      ? (db.prepare("SELECT * FROM actors WHERE slug = ?").get(actor.organization_slug) as ActorRow) : null;
    const connections = (db.prepare("SELECT * FROM connections WHERE actors LIKE ? ORDER BY form, connection_id")
      .all(`%${JSON.stringify(slug)}%`) as Parameters<typeof parseConnection>[0][]).map(parseConnection)
      .filter((c) => c.actors.includes(slug));
    const searchedRaw = (db.prepare("SELECT value FROM meta WHERE key = 'connections_searched'").get() as
      | { value: string } | undefined)?.value;
    return {
      status: "ok" as const, asOf, actor, organization, affiliations, people,
      byYear: db.prepare("SELECT * FROM by_year WHERE actor_slug = ? ORDER BY year DESC, kind, metric, direction")
        .all(slug) as YearRow[],
      sections, possible, possibleTotal, possiblePage, pageSize,
      caseRoles: sections.find((s) => s.kind === "case_role")?.rows ?? [],
      connections, searched: searchedRaw ? (JSON.parse(searchedRaw) as Searched) : null,
      coverage: db.prepare("SELECT * FROM coverage ORDER BY input, item").all() as CoverageRow[],
      names: namesFor(db),
    };
  });
}

export function loadCasePage(docket: string): CasePageData {
  return withDb((db, asOf) => {
    const raw = db.prepare("SELECT * FROM cases WHERE docket = ?").get(docket) as
      | (Omit<CaseRow, "parties" | "attorneys" | "firms"> & { parties: string; attorneys: string; firms: string })
      | undefined;
    if (!raw) return { status: "not_found" as const, docket };
    const facts = db.prepare(
      "SELECT * FROM facts WHERE kind = ? AND json_extract(detail, '$.docket') = ? ORDER BY actor_slug, fact_key");
    return {
      status: "ok" as const, asOf,
      case: { ...raw, parties: JSON.parse(raw.parties) as string[], attorneys: JSON.parse(raw.attorneys) as string[],
        firms: JSON.parse(raw.firms) as string[] },
      roles: facts.all("case_role", docket) as Fact[],
      appearances: facts.all("docket_appearance", docket) as Fact[],
      names: namesFor(db),
    };
  });
}
