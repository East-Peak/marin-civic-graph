// @vitest-environment jsdom
// Operator-only actor pages (/actors, /actors/[slug], /cases/[docket]) and their reader, against a fixture index of
// invented actors. The schema is read from scripts/actor_index.py itself, so the reader cannot drift from the builder.
import Database from "better-sqlite3";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { actorsDbPath, loadActorList, loadActorPage, loadCasePage } from "../../../operator-workbench-src/_lib/actors";
import ActorsPage from "../../../operator-workbench-src/actors/page";
import ActorPage from "../../../operator-workbench-src/actors/[slug]/page";
import CasePage from "../../../operator-workbench-src/cases/[docket]/page";

const PY = readFileSync(path.join(process.cwd(), "..", "scripts", "actor_index.py"), "utf-8");
const SCHEMA = PY.match(/^SCHEMA = """([\s\S]*?)"""/m)![1];

let dir: string;
let dbPath: string;

type FactIn = Partial<Record<string, string | number | null>> & { fact_key: string; kind: string };

function fact(f: FactIn) {
  return {
    actor_slug: null, actor_name: "", counterparty_name: null, counterparty_slug: null, metric: null, amount: null,
    direction: null, date: null, date_kind: "none", source_ref: "src", source_url: null, quote: null, label: "label",
    identity_basis: "pattern_reviewed", counterparty_basis: null, assertion_status: "source_record", repeat_of: null,
    detail: "{}", ...f,
  };
}

function buildFixture(file: string) {
  const db = new Database(file);
  db.exec(SCHEMA);
  db.prepare("INSERT INTO meta VALUES ('substrate_as_of_date', '2031-07-01'), ('connections_searched', ?)").run(
    JSON.stringify({ forms: ["commitment_grant", "commitment_grant_litigation", "shared_officer"], reviewed_cases: 1,
      commitments: 2, reported_grants: 3, officer_rows: 4 }));
  const actor = db.prepare("INSERT INTO actors VALUES (?, ?, ?, ?, ?, 1, ?, '[]', '[]', ?, '[]', ?)");
  actor.run("harbor-shelter", "Harbor Shelter", "nonprofit", 1, 0, null, JSON.stringify(["harbor-annex"]), null);
  actor.run("harbor-annex", "Harbor Annex", "nonprofit", 1, 0, null, JSON.stringify(["harbor-shelter"]), null);
  actor.run("quill-law", "Law Offices of Oda Quill", "law_firm", 1, 0, null, "[]", null);
  actor.run("oda-quill", "Oda Quill", "person", 1, 0, "attorney of record", "[]", null);
  actor.run("tidepool-union", "Tidepool Tenants Union", "association", 1, 0, null, "[]", null);
  actor.run("county-of-fernwood", "County of Fernwood", "public_body", 1, 1, null, "[]", null);
  actor.run("officer-harbor-shelter-ash-wilder", "Ash Wilder", "person", 0, 0, "officer listed on Form 990", "[]",
    "harbor-shelter");
  const cols = ["fact_key", "actor_slug", "actor_name", "kind", "counterparty_name", "counterparty_slug", "metric",
    "amount", "direction", "date", "date_kind", "source_ref", "source_url", "quote", "label", "identity_basis",
    "counterparty_basis", "assertion_status", "repeat_of", "detail"];
  const ins = db.prepare(`INSERT INTO facts VALUES (${cols.map((c) => `@${c}`).join(", ")})`);
  const add = (f: FactIn) => ins.run(fact(f));
  add({ fact_key: "board_item:x:2", kind: "board_item", actor_slug: "harbor-shelter", actor_name: "Harbor Shelter",
    counterparty_name: "County of Fernwood", counterparty_slug: "county-of-fernwood", counterparty_basis: "ledger_body",
    metric: "stated_in_item", amount: 3000, direction: "county_pays", date: "2029-03-03", date_kind: "meeting_date",
    source_ref: "meeting-1 item CA-2", label: "committed (stated in a board item)", quote: "agreement with Harbor Shelter",
    assertion_status: "extracted_unsampled" });
  add({ fact_key: "board_item:x:3", kind: "board_item", actor_slug: "harbor-shelter", actor_name: "Harbor Shelter",
    counterparty_name: "County of Fernwood", counterparty_slug: "county-of-fernwood", counterparty_basis: "ledger_body",
    metric: "stated_in_item", amount: 3000, direction: "county_pays", date: "2029-03-03", date_kind: "meeting_date",
    source_ref: "meeting-1 item CA-2", label: "committed (stated in a board item)", repeat_of: "board_item:x:2",
    assertion_status: "extracted_unsampled" });
  add({ fact_key: "reported_grant:o:1:cash_grant", kind: "reported_grant", actor_slug: null, actor_name: "Lantern Fund",
    counterparty_name: "Harbor Shelter Inc", counterparty_slug: "harbor-shelter", counterparty_basis: "ein",
    metric: "cash_grant", amount: 600, direction: "grantor_reports", date: "2029", date_kind: "tax_year",
    identity_basis: "ein", source_ref: "990 o Schedule I row 1", label: "reported grant" });
  add({ fact_key: "reported_grant:o:2:cash_grant", kind: "reported_grant", actor_name: "Lantern Fund",
    counterparty_name: "Harbor Shelter", counterparty_slug: "harbor-shelter", counterparty_basis: "pattern_ein_not_in_registry",
    metric: "cash_grant", amount: 90, date: "2029", date_kind: "tax_year", identity_basis: "ein",
    source_ref: "990 o Schedule I row 2", label: "reported grant", detail: JSON.stringify({ recipient_ein: "009990009" }) });
  add({ fact_key: "officer:o:0", kind: "officer", actor_slug: "harbor-shelter", actor_name: "Harbor Shelter",
    counterparty_name: "Ash Wilder", counterparty_slug: "officer-harbor-shelter-ash-wilder",
    counterparty_basis: "stated_name", date: "2029", date_kind: "tax_year", identity_basis: "ein",
    label: "officer listed on the return: President", source_ref: "990 o" });
  add({ fact_key: "case_role:9:30-cv-00001:plaintiff:tidepool-union", kind: "case_role", actor_slug: "tidepool-union",
    actor_name: "Tidepool Tenants Union", counterparty_name: "County of Fernwood", counterparty_slug: "county-of-fernwood",
    counterparty_basis: "reviewed_role", date: "2030-05-05", date_kind: "filed", identity_basis: "reviewed_role",
    assertion_status: "reviewed_role", source_ref: "docket 9:30-cv-00001", label: "plaintiff in 9:30-cv-00001",
    detail: JSON.stringify({ docket: "9:30-cv-00001", outcome_date: "2031-02-02", outcome_evidence: "entries 40, 41",
      outcome_kind: "stipulated_dismissal", role: "plaintiff" }, null, 0).replaceAll('":', '": ').replaceAll(',"', ', "') });
  add({ fact_key: "docket_appearance:9:30-cv-00001:firm:Law Offices of Oda Quill:quill-law", kind: "docket_appearance",
    actor_slug: "quill-law", actor_name: "Law Offices of Oda Quill", date: "2030-05-05", date_kind: "filed",
    quote: "Law Offices of Oda Quill", assertion_status: "side_unknown", source_ref: "docket 9:30-cv-00001",
    label: "named on the docket as a firm; side not established",
    detail: JSON.stringify({ docket: "9:30-cv-00001", field: "firm" }).replaceAll('":', '": ').replaceAll(',"', ', "') });
  add({ fact_key: "minutes_mentions:harbor-shelter:Fernwood Council", kind: "minutes_mentions",
    actor_slug: "harbor-shelter", actor_name: "Harbor Shelter", counterparty_name: "Fernwood Council",
    metric: "page_count", amount: 2, assertion_status: "count_only", label: "minutes pages naming the actor",
    source_ref: "minutes text index: Fernwood Council" });
  const tot = db.prepare("INSERT INTO totals VALUES (?, ?, ?, ?, ?, ?, ?, ?)");
  tot.run("harbor-shelter", "subject", "board_item", "stated_in_item", "county_pays", 1, 3000,
    "amendments restate agreement ceilings; this sum overcounts");
  tot.run("harbor-shelter", "counterparty", "reported_grant", "cash_grant", "grantor_reports", 1, 600, null);
  db.prepare("INSERT INTO by_year VALUES ('harbor-shelter', 'subject', '2029', 'board_item', 'stated_in_item', " +
    "'county_pays', 1, 3000)").run();
  db.prepare("INSERT INTO cases VALUES (?, 'District Court, Fernwood', ?, '2030-05-05', '2031-02-02', 'Civil rights', " +
    "'https://courts.example/70000001/', '70000001', ?, ?, ?, NULL, 1, 'stipulated_dismissal', '2031-02-02', " +
    "'entries 40, 41')").run("9:30-cv-00001", "Tidepool Tenants Union v. County of Fernwood",
    JSON.stringify(["Tidepool Tenants Union", "County of Fernwood"]), JSON.stringify(["Oda Quill"]),
    JSON.stringify(["Law Offices of Oda Quill"]));
  db.prepare("INSERT INTO cases VALUES ('9:31-cv-00002', 'District Court, Fernwood', 'Resident v. Town', '2031-06-01', " +
    "NULL, 'Civil rights', NULL, '70000002', '[\"Uma Resident\"]', '[]', '[]', 'no attorney listed in the source', 0, " +
    "NULL, NULL, NULL)").run();
  db.prepare("INSERT INTO connections VALUES ('connection-1', 'shared_officer', 'shared officer name Ash Wilder: same " +
    "name, not confirmed the same person', ?, ?, 'unconfirmed')").run(JSON.stringify(["harbor-annex", "harbor-shelter"]),
    JSON.stringify([{ kind: "officer", metric: null, from: "harbor-annex", to: "harbor-shelter",
      label: "officer name on harbor-annex's return", sources: [{ fact_key: "officer:o:0", label: "officer",
        source_ref: "990 o", date: "2029", date_kind: "tax_year", amount: null, metric: null }] }]));
  const cov = db.prepare("INSERT INTO coverage VALUES (?, ?, ?, ?)");
  cov.run("board_ledger", "rows", "covered", JSON.stringify({ rows: 9, body: "County of Fernwood" }));
  cov.run("city_contracts", "all cities", "absent", JSON.stringify({ note: "No city-level contract source" }));
  cov.run("form_990", "001110001", "held", JSON.stringify({ tax_years: ["2029"] }));
  cov.run("form_990_registry", "harbor-shelter", "returns held", JSON.stringify({ tax_years: ["2029"] }));
  cov.run("form_990_registry", "tidepool-union", "no EIN in the registry", "{}");
  cov.run("minutes", "Fernwood Council", "covered", JSON.stringify({ states: { indexed: 1 } }));
  db.close();
}

beforeEach(() => {
  dir = mkdtempSync(path.join(os.tmpdir(), "open-marin-actors-"));
  dbPath = path.join(dir, "actors.sqlite");
  buildFixture(dbPath);
  vi.stubEnv("ACTORS_DB_PATH", dbPath);
  vi.stubEnv("OPERATOR_WORKBENCH", "1");
  vi.stubEnv("VERCEL", "");
  vi.stubEnv("VERCEL_ENV", "");
});

afterEach(() => {
  vi.unstubAllEnvs();
  rmSync(dir, { recursive: true, force: true });
});

describe("actor index path", () => {
  it("comes from ACTORS_DB_PATH and defaults outside every repo", () => {
    expect(actorsDbPath()).toBe(dbPath);
    vi.stubEnv("ACTORS_DB_PATH", "");
    expect(actorsDbPath()).toBe(path.join(os.homedir(), "open-marin-research", "actors.sqlite"));
  });
});

describe("a missing index", () => {
  it("is stated plainly on every page", async () => {
    vi.stubEnv("ACTORS_DB_PATH", path.join(dir, "missing.sqlite"));
    expect(loadActorList()).toEqual({ status: "absent", path: path.join(dir, "missing.sqlite") });
    expect(loadCasePage("x").status).toBe("absent");
    render(ActorsPage());
    expect(screen.getByText(/actor index is not built/i)).toBeInTheDocument();
  });
});

describe("loadActorList", () => {
  it("lists registry actors by kind with confirmed counts, possible matches apart, never unregistered officers", () => {
    const data = loadActorList();
    if (data.status !== "ok") throw new Error("absent");
    const all = data.groups.flatMap((g) => g.actors);
    expect(all.map((a) => a.slug)).not.toContain("officer-harbor-shelter-ash-wilder");
    const harbor = all.find((a) => a.slug === "harbor-shelter")!;
    expect(harbor.counts).toEqual({ board_item: 2, reported_grant: 1, officer: 1, minutes_mentions: 1 });
    expect(harbor.possible).toBe(1);
    // A body named as the counterparty (the ledger's own body, a defendant) counts those rows too.
    expect(all.find((a) => a.slug === "county-of-fernwood")!.counts).toEqual({ board_item: 2, case_role: 1 });
    expect(data.groups.map((g) => g.kind)).toEqual(["association", "law_firm", "nonprofit", "person", "public_body"]);
  });
});

describe("/actors/[slug]", () => {
  async function renderActor(slug: string) {
    return render(await ActorPage({ params: Promise.resolve({ slug }) }));
  }

  it("shows each kind's rows, labels, sources, totals with the overcount note, and that kind's coverage", async () => {
    await renderActor("harbor-shelter");
    const board = within(screen.getByRole("region", { name: /Board of Supervisors items/ }));
    expect(board.getAllByText("committed (stated in a board item)")).toHaveLength(2);
    expect(board.getByText(/repeats an earlier row; kept, excluded from totals/)).toBeInTheDocument();
    expect(board.getByText(/this sum overcounts/)).toBeInTheDocument();
    expect(board.getByText(/board ledger \/ rows/)).toBeInTheDocument();
    const contracts = within(screen.getByRole("region", { name: /Delegated contracts/ }));
    expect(contracts.getByText("None found in the covered sources.")).toBeInTheDocument();
    expect(contracts.getByText(/city contracts \/ all cities/)).toBeInTheDocument();
    expect(contracts.getByText("absent")).toBeInTheDocument();
    const grants = within(screen.getByRole("region", { name: /Reported grants/ }));
    expect(grants.getByText("990 o Schedule I row 1")).toBeInTheDocument();
    expect(grants.queryByText("990 o Schedule I row 2")).not.toBeInTheDocument();
    expect(grants.getByText(/Total received/)).toBeInTheDocument();
  });

  it("keeps possible matches in their own section with the reason and the EIN", async () => {
    await renderActor("harbor-shelter");
    const possible = within(screen.getByRole("region", { name: "Possible matches" }));
    expect(possible.getByText(/on an EIN the registry does not list/)).toBeInTheDocument();
    expect(possible.getByText(/recipient EIN 009990009/)).toBeInTheDocument();
  });

  it("shows affiliations without merging, people on returns, connections and the by-year summary", async () => {
    await renderActor("harbor-shelter");
    expect(within(screen.getByRole("region", { name: /Affiliations/ })).getByRole("link", { name: "Harbor Annex" }))
      .toHaveAttribute("href", "/actors/harbor-annex");
    expect(within(screen.getByRole("region", { name: /People listed/ })).getByRole("link", { name: "Ash Wilder" }))
      .toHaveAttribute("href", "/actors/officer-harbor-shelter-ash-wilder");
    const conn = within(screen.getByRole("region", { name: "Connections" }));
    expect(conn.getByText(/same name, not confirmed the same person/)).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "By year" })).getByText("2029")).toBeInTheDocument();
  });

  it("says when no connection exists and lists what was searched", async () => {
    await renderActor("tidepool-union");
    const conn = within(screen.getByRole("region", { name: "Connections" }));
    expect(conn.getByText(/No connection found\. Searched: forms commitment grant/)).toBeInTheDocument();
    expect(conn.getByText(/1 cases with reviewed roles/)).toBeInTheDocument();
  });

  it("shows reviewed case roles with outcomes and links to the case", async () => {
    await renderActor("tidepool-union");
    const roles = within(screen.getByRole("region", { name: "Case roles" }));
    expect(roles.getByRole("link", { name: "9:30-cv-00001" })).toHaveAttribute("href", "/cases/9%3A30-cv-00001");
    expect(roles.getByText(/plaintiff/)).toHaveTextContent(/against County of Fernwood/);
    expect(roles.getByText(/stipulated dismissal \(2031-02-02; evidence: entries 40, 41\)/)).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: /Own returns/ })).getByText(/no EIN in the registry/))
      .toBeInTheDocument();
  });

  it("gives a registered person and an officer entry the same page", async () => {
    await renderActor("oda-quill");
    expect(screen.getByText(/public role: attorney of record/)).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Connections" })).toBeInTheDocument();
    await renderActor("officer-harbor-shelter-ash-wilder");
    expect(screen.getByText(/not a confirmed identity/)).toBeInTheDocument();
    expect(within(screen.getAllByRole("region", { name: /Officers listed/ }).at(-1)!).getByText(/President/))
      .toBeInTheDocument();
  });

  it("says an unknown slug is not in the index", async () => {
    expect(loadActorPage("nobody").status).toBe("not_found");
    await renderActor("nobody");
    expect(screen.getByText(/No actor “nobody”/)).toBeInTheDocument();
  });
});

describe("/cases/[docket]", () => {
  async function renderCase(docket: string) {
    return render(await CasePage({ params: Promise.resolve({ docket }) }));
  }

  it("shows the case row, its reviewed roles and outcome, and lists attorneys and firms without sides", async () => {
    await renderCase("9%3A30-cv-00001");
    expect(screen.getByRole("heading", { name: "Tidepool Tenants Union v. County of Fernwood" })).toBeInTheDocument();
    const roles = within(screen.getByRole("region", { name: "Reviewed roles" }));
    expect(roles.getByRole("link", { name: "Tidepool Tenants Union" })).toHaveAttribute("href", "/actors/tidepool-union");
    expect(roles.getByText(/stipulated dismissal/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Attorneys \(side not established\)/ })).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "Registry actors on this docket" }))
      .getByRole("link", { name: "Law Offices of Oda Quill" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "CourtListener docket" })).toHaveAttribute(
      "href", "https://courts.example/70000001/");
  });

  it("says 'no attorney listed in the source', never self-represented", async () => {
    await renderCase("9:31-cv-00002");
    expect(screen.getByText("no attorney listed in the source")).toBeInTheDocument();
    expect(screen.getByText(/No reviewed roles for this docket/)).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/self[- ]represented|pro se/i);
  });
});
