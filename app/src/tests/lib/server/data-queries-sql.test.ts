import Database from "better-sqlite3";
import { mkdtempSync } from "node:fs";
import path from "node:path";
import { tmpdir } from "node:os";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DATA_QUERIES, applyFilterDefaults } from "@/lib/server/data-queries";

type NodeFixture = {
  id: string;
  type: string;
  search_label: string;
  props: Record<string, unknown>;
};

type EdgeFixture = {
  source: string;
  rel: string;
  target: string;
};

function insertNode(db: Database.Database, node: NodeFixture) {
  db.prepare("INSERT INTO nodes(id, type, search_label, props) VALUES (?, ?, ?, ?)").run(
    node.id,
    node.type,
    node.search_label,
    JSON.stringify(node.props),
  );
}

function insertEdge(db: Database.Database, edge: EdgeFixture) {
  db.prepare("INSERT INTO edges(source, rel, target) VALUES (?, ?, ?)").run(
    edge.source,
    edge.rel,
    edge.target,
  );
}

function makeFixtureDb(): string {
  const dir = mkdtempSync(path.join(tmpdir(), "open-marin-data-sql-"));
  const dbPath = path.join(dir, "public-substrate.sqlite");
  const db = new Database(dbPath);
  db.exec(`
    CREATE TABLE nodes (
      id TEXT PRIMARY KEY,
      type TEXT NOT NULL,
      search_label TEXT NOT NULL,
      props TEXT NOT NULL CHECK (json_valid(props))
    );
    CREATE TABLE edges (
      source TEXT NOT NULL,
      rel TEXT NOT NULL,
      target TEXT NOT NULL
    );
    CREATE TABLE browse_rows (
      id TEXT PRIMARY KEY,
      type TEXT NOT NULL,
      search_label TEXT NOT NULL,
      label_lower TEXT NOT NULL,
      col1_key TEXT,
      col1_value TEXT,
      col2_key TEXT,
      col2_value TEXT
    );
    CREATE TABLE meta (
      key TEXT PRIMARY KEY,
      value TEXT NOT NULL
    );
  `);
  db.prepare("INSERT INTO meta(key, value) VALUES ('as_of_date', '2026-07-07')").run();

  [
    {
      id: "decision-shelter-approval",
      type: "Decision",
      search_label: "Shelter approval",
      props: {
        decided_at: "2024-03-15",
        institution_id: "org-san-rafael-city-council",
        title: "Resolution approving shelter",
      },
    },
    {
      id: "moneyflow-campaign-1500",
      type: "MoneyFlow",
      search_label: "$1,500 campaign contribution",
      props: {
        amount: 1500,
        flow_date: "2024-03-10",
        flow_type: "contribution",
      },
    },
    {
      id: "moneyflow-campaign-undated",
      type: "MoneyFlow",
      search_label: "Undated campaign contribution",
      props: {
        amount: 2000,
        flow_date: null,
        flow_type: "contribution",
      },
    },
    {
      id: "filing-alice-700",
      type: "Filing",
      search_label: "Alice Form 700",
      props: {
        filed_by: "person-alice-council",
        filing_type: "form_700",
        signed_at: "2024-03-20",
      },
    },
    {
      id: "filing-alice-803",
      type: "Filing",
      search_label: "Alice Form 803",
      props: {
        filed_by: "person-alice-council",
        filing_type: "form_803",
        signed_at: "2024-04-20",
      },
    },
    {
      id: "filing-alice-700-older",
      type: "Filing",
      search_label: "Alice older Form 700",
      props: {
        filed_by: "person-alice-council",
        filing_type: "form_700",
        signed_at: "2023-03-20",
      },
    },
    {
      id: "person-alice-council",
      type: "Person",
      search_label: "Alice Council",
      props: { name: "Alice Council" },
    },
    {
      id: "seatservice-alice-current",
      type: "SeatService",
      search_label: "Alice Council service",
      props: {
        ended_at: null,
        jurisdiction_id: "place-san-rafael",
        seat_id: "seat-san-rafael-council",
        started_at: "2020-01-01",
      },
    },
    {
      id: "person-bob-ended-future",
      type: "Person",
      search_label: "Bob Future Ended",
      props: { name: "Bob Future Ended" },
    },
    {
      id: "seatservice-bob-ended-future",
      type: "SeatService",
      search_label: "Bob Future service",
      props: {
        ended_at: "2029-01-01",
        jurisdiction_id: "place-san-rafael",
        seat_id: "seat-san-rafael-council",
        started_at: "2020-01-01",
      },
    },
    {
      id: "project-san-rafael-350-merrydale-interim-shelter",
      type: "Project",
      search_label: "Merrydale shelter",
      props: { name: "Merrydale shelter" },
    },
    {
      id: "agreement-null-date",
      type: "Agreement",
      search_label: "Agreement without date",
      props: {
        amount: 100,
        effective_date: null,
        project_id: "project-san-rafael-350-merrydale-interim-shelter",
      },
    },
    {
      id: "agreement-2024",
      type: "Agreement",
      search_label: "Agreement 2024",
      props: {
        amount: 200,
        effective_date: "2024-01-01",
        project_id: "project-san-rafael-350-merrydale-interim-shelter",
      },
    },
    {
      id: "record-null-captured",
      type: "Record",
      search_label: "Undated record",
      props: {
        captured_at: null,
        preferred_display_artifact: "undated.txt",
        preferred_public_url: "https://example.test/undated",
        record_type: "staff_report",
      },
    },
    {
      id: "record-2024-captured",
      type: "Record",
      search_label: "Dated record",
      props: {
        captured_at: "2024-02-01",
        preferred_display_artifact: "dated.txt",
        preferred_public_url: "https://example.test/dated",
        record_type: "staff_report",
      },
    },
    {
      id: "case-boyd-v-city-of-san-rafael",
      type: "Case",
      search_label: "Boyd v. San Rafael",
      props: { caption: "Boyd v. San Rafael" },
    },
    {
      id: "case-no-local-link",
      type: "Case",
      search_label: "No local link case",
      props: { caption: "No local link case" },
    },
    {
      id: "proceeding-null-date",
      type: "Proceeding",
      search_label: "Undated proceeding",
      props: { occurred_at: null, proceeding_type: "order" },
    },
    {
      id: "proceeding-2024",
      type: "Proceeding",
      search_label: "Dated proceeding",
      props: { occurred_at: "2024-05-01", proceeding_type: "hearing" },
    },
    {
      id: "proceeding-no-local-link",
      type: "Proceeding",
      search_label: "Proceeding without local link",
      props: { occurred_at: "2024-06-01", proceeding_type: "order" },
    },
    {
      id: "program-local",
      type: "Program",
      search_label: "Local program",
      props: { name: "Local program" },
    },
    {
      id: "project-local",
      type: "Project",
      search_label: "Local project",
      props: { name: "Local project" },
    },
  ].forEach((node) => insertNode(db, node));

  [
    { source: "moneyflow-campaign-1500", rel: "FROM_SOURCE", target: "person-alice-council" },
    { source: "moneyflow-campaign-1500", rel: "TO_TARGET", target: "decision-shelter-approval" },
    { source: "filing-alice-700", rel: "FILED_BY", target: "person-alice-council" },
    { source: "filing-alice-803", rel: "FILED_BY", target: "person-alice-council" },
    { source: "filing-alice-803", rel: "FILED_BY", target: "person-alice-council" },
    { source: "filing-alice-700-older", rel: "FILED_BY", target: "person-alice-council" },
    { source: "filing-alice-700-older", rel: "FILED_BY", target: "person-alice-council" },
    { source: "person-alice-council", rel: "HELD_BY", target: "seatservice-alice-current" },
    { source: "person-bob-ended-future", rel: "HELD_BY", target: "seatservice-bob-ended-future" },
    { source: "decision-shelter-approval", rel: "EVIDENCED_BY", target: "record-null-captured" },
    { source: "decision-shelter-approval", rel: "EVIDENCED_BY", target: "record-2024-captured" },
    { source: "proceeding-null-date", rel: "PART_OF", target: "case-boyd-v-city-of-san-rafael" },
    { source: "proceeding-2024", rel: "PART_OF", target: "case-boyd-v-city-of-san-rafael" },
    { source: "proceeding-no-local-link", rel: "PART_OF", target: "case-no-local-link" },
    { source: "case-boyd-v-city-of-san-rafael", rel: "AFFECTS", target: "program-local" },
    { source: "project-local", rel: "AFFECTED_BY", target: "case-boyd-v-city-of-san-rafael" },
  ].forEach((edge) => insertEdge(db, edge));

  db.close();
  return dbPath;
}

async function runSql(slug: string, provided: Record<string, string> = {}) {
  const def = DATA_QUERIES.find((query) => query.slug === slug);
  if (!def) throw new Error(`missing query def: ${slug}`);
  const { runDataQuerySql } = await import("@/lib/server/data-queries-sql");
  return runDataQuerySql(def, applyFilterDefaults(def, provided));
}

describe("SQL data query translations", () => {
  beforeEach(() => {
    vi.resetModules();
    process.env.SERVING_BACKEND = "substrate";
    process.env.SUBSTRATE_DB_PATH = makeFixtureDb();
  });

  afterEach(async () => {
    const mod = await import("@/lib/server/substrate");
    mod.closeSubstrateDb();
    delete process.env.SERVING_BACKEND;
    delete process.env.SUBSTRATE_DB_PATH;
  });

  it("has a SQL builder for every /data query slug", async () => {
    const { DATA_QUERY_SQL_BUILDERS } = await import("@/lib/server/data-queries-sql");
    expect(Object.keys(DATA_QUERY_SQL_BUILDERS).sort()).toEqual(
      DATA_QUERIES.map((query) => query.slug).sort(),
    );
  });

  it("returns the Decision row shape for San Rafael decisions", async () => {
    const result = await runSql("san-rafael-decisions-since-2019", {
      from_date: "2024-01-01",
      to_date: "2024-12-31",
    });

    expect(result.rows).toEqual([
      {
        decided_at: "2024-03-15",
        title: "Shelter approval",
        institution_name: "org-san-rafael-city-council",
        id: "decision-shelter-approval",
      },
    ]);
  });

  it("returns the MoneyFlow row shape with source and target labels", async () => {
    const result = await runSql("money-flows-by-year", {
      min_amount: "1000",
      year: "2024",
      flow_type: "contribution",
    });

    expect(result.rows).toEqual([
      {
        flow_date: "2024-03-10",
        amount: 1500,
        flow_type: "contribution",
        source_name: "Alice Council",
        target_name: "Shelter approval",
        id: "moneyflow-campaign-1500",
      },
    ]);
  });

  it("returns the Filing row shape with filer label", async () => {
    const result = await runSql("filings-by-person-or-committee", {
      filer_id: "person-alice-council",
      filing_type: "form_700",
      from_date: "2024-01-01",
      to_date: "2024-12-31",
    });

    expect(result.rows).toEqual([
      {
        signed_at: "2024-03-20",
        filing_type: "form_700",
        filed_by_name: "Alice Council",
        id: "filing-alice-700",
      },
    ]);
  });

  it("mimics live current-officeholder date coercion and counts distinct person filings", async () => {
    const result = await runSql("current-officeholders-form-coverage", {
      jurisdiction_id: "place-san-rafael",
    });

    expect(result.as_of_date).toBeUndefined();
    expect(result.rows).toEqual([
      {
        person_name: "Alice Council",
        seat_display: "seat-san-rafael-council",
        form_700_count: 2,
        form_803_count: 1,
        id: "person-alice-council",
      },
    ]);
  });

  it("emits Cypher-compatible null-first DESC order clauses for nullable date sorts", async () => {
    const { DATA_QUERY_SQL_BUILDERS } = await import("@/lib/server/data-queries-sql");

    const nullableDescSorts = [
      ["san-rafael-decisions-since-2019", "decided_at"],
      ["money-flows-by-year", "flow_date"],
      ["filings-by-person-or-committee", "signed_at"],
      ["agreements-and-amendments-for-project", "effective_date"],
      ["legal-proceedings-affecting-local", "occurred_at"],
      ["evidence-records-supporting", "captured_at"],
    ] as const;

    for (const [slug, column] of nullableDescSorts) {
      const built = DATA_QUERY_SQL_BUILDERS[slug]({});
      expect(built.sql.replace(/\s+/g, " "), slug).toContain(
        `ORDER BY (${column} IS NULL) DESC, ${column} DESC, id ASC`,
      );
    }
  });

  it("orders undated nullable DESC query rows before dated rows like Cypher", async () => {
    const money = await runSql("money-flows-by-year", {
      min_amount: "1000",
      flow_type: "contribution",
    });
    expect(money.rows.map((row) => row.id)).toEqual([
      "moneyflow-campaign-undated",
      "moneyflow-campaign-1500",
    ]);

    const agreements = await runSql("agreements-and-amendments-for-project");
    expect(agreements.rows.map((row) => row.id)).toEqual([
      "agreement-null-date",
      "agreement-2024",
    ]);

    const evidence = await runSql("evidence-records-supporting", {
      target_id: "decision-shelter-approval",
    });
    expect(evidence.rows.map((row) => row.id)).toEqual([
      "record-null-captured",
      "record-2024-captured",
    ]);
  });

  it("multiplies legal proceedings by parent case links and preserves null affected rows", async () => {
    const linked = await runSql("legal-proceedings-affecting-local", {
      case_id: "case-boyd-v-city-of-san-rafael",
    });
    expect(linked.rows.map((row) => row.id)).toEqual([
      "proceeding-null-date",
      "proceeding-null-date",
      "proceeding-2024",
      "proceeding-2024",
    ]);
    expect(
      linked.rows
        .filter((row) => row.id === "proceeding-null-date")
        .map((row) => row.affected_program)
        .sort(),
    ).toEqual(["Local program", "Local project"]);

    const unlinked = await runSql("legal-proceedings-affecting-local", {
      case_id: "case-no-local-link",
    });
    expect(unlinked.rows).toEqual([
      {
        case_caption: "No local link case",
        proceeding_type: "order",
        occurred_at: "2024-06-01",
        affected_program: null,
        id: "proceeding-no-local-link",
      },
    ]);
  });

  it("uses julianday window math for campaign money near decisions", async () => {
    const result = await runSql("campaign-money-near-decisions", {
      jurisdiction: "san-rafael",
      window_days: "7",
    });

    expect(result.rows).toEqual([
      {
        decision_title: "Shelter approval",
        decided_at: "2024-03-15",
        money_amount: 1500,
        flow_date: "2024-03-10",
        days_delta: 5,
        id: "moneyflow-campaign-1500",
      },
    ]);
  });

  it("executes every SQL query and projects only declared columns", async () => {
    for (const def of DATA_QUERIES) {
      const provided: Record<string, string> =
        def.slug === "evidence-records-supporting"
          ? { target_id: "decision-shelter-approval" }
          : {};
      const result = await runSql(def.slug, provided);

      for (const row of result.rows) {
        expect(Object.keys(row).sort(), def.slug).toEqual(
          def.columns.map((column) => column.key).sort(),
        );
      }
    }
  });
});
