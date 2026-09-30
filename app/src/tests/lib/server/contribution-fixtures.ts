// A small public substrate whose contribution totals are calculated by hand.
// Every name, place and value is fictional. Amounts in the comments are cents.
//
//   committee-alpha  35 rows  286,510  many-small 30×5,000 = 150,000 > one-large 100,000
//                                      > able-sample 25,000 + 10,010 − 2,500 = 32,510
//                                      > dup-path 4,000 (its edges are stored twice)
//   committee-beta    8 rows   74,765  tie-a 30,000 = tie-b 30,000 (id order) > pat-example 7,500
//                                      > able-sample 6,000 (who also gives to alpha)
//                                      > float-noise 10 + 20 + 1,235 = 1,265 > zero 0
//   committee-gamma   4 rows   52,200  candidate 50,000 (the committee is CONTROLLED_BY them)
//                                      > evidenced 2,000 (its only other edge is EVIDENCED_BY)
//                                      > alias-giver 100 = same-as-giver 100 (SAME_AS-linked)
//   all              47 rows  413,475
//
// Flows that are not reconciled contributions touch the same nodes and must never count:
// an expenditure paying able-sample, a San Rafael OCR campaign_contribution from able-sample,
// and a delegated contract paying one-large (which also has a money_rollups row and a SAME_AS link).
import Database from "better-sqlite3";
import { mkdtempSync } from "node:fs";
import path from "node:path";
import { tmpdir } from "node:os";

type NodeRow = { id: string; type: string; label: string; props?: Record<string, unknown> };
type EdgeRow = [source: string, rel: string, target: string];

/** Goal 2's withheld synthetic values: stored on flows under keys no surface may read. */
export const WITHHELD_VALUES = [
  "415-555-0199",
  "12 Sample Loop, apt 4Sampleton, CA 94999",
  "Exampleco.com",
] as const;

/** Values a contributor node's own props carry; reported details must never be backfilled from them. */
export const NODE_PROP_VALUES = ["Backfill Occupation", "Backfill City", "Backfill Employer"] as const;

export const DETAIL_ABLE_SAMPLETON = {
  reported_occupation: "Teacher",
  reported_employer: "Sampleton Unified",
  reported_city: "Sampleton",
  reported_state: "CA",
  reported_zip5: "94999",
};

export const DETAIL_ABLE_DEMOTOWN = {
  reported_occupation: "Principal",
  reported_employer: "Demotown Academy",
  reported_city: "Demotown",
  reported_state: "CA",
  reported_zip5: "94997",
};

export const DETAIL_ABLE_EXAMPLEVILLE = {
  reported_occupation: "Teacher",
  reported_employer: "Exampleville Schools",
  reported_city: "Exampleville",
  reported_state: "CA",
  reported_zip5: "94998",
};

const WITHHELD_PROPS = {
  reported_street: WITHHELD_VALUES[1],
  contributor_phone: WITHHELD_VALUES[0],
  reported_employer_raw: WITHHELD_VALUES[2],
  reported_entity_cd: "IND",
};

function flow(
  id: string,
  amount: number,
  date: string,
  props: Record<string, unknown> = {},
  flowType = "contribution",
): NodeRow {
  return {
    id,
    type: "MoneyFlow",
    label: `${flowType} ${id}`,
    props: { amount, flow_date: date, flow_type: flowType, source_schedule: "A", ...props },
  };
}

export const CONTRIBUTION_COUNT = 47;
export const CONTRIBUTION_TOTAL_CENTS = 413_475;

export function buildContributionFixture(): { nodes: NodeRow[]; edges: EdgeRow[] } {
  const nodes: NodeRow[] = [
    { id: "committee-alpha", type: "Committee", label: "Committee for Measure Alpha" },
    { id: "committee-beta", type: "Committee", label: "Friends of Beta" },
    { id: "committee-gamma", type: "Committee", label: "Candidate Gamma for Council" },
    { id: "committee-empty", type: "Committee", label: "Committee With No Contributions" },
    {
      id: "person-able-sample",
      type: "Person",
      label: "ABLE SAMPLE",
      props: {
        occupation: NODE_PROP_VALUES[0],
        city: NODE_PROP_VALUES[1],
        employer: NODE_PROP_VALUES[2],
      },
    },
    { id: "person-many-small", type: "Person", label: "MANY SMALL" },
    { id: "org-one-large", type: "Organization", label: "ONE LARGE HOLDINGS LLC" },
    { id: "org-one-large-canonical", type: "Organization", label: "One Large Holdings" },
    { id: "person-dup-path", type: "Person", label: "DUP PATH" },
    { id: "person-tie-a", type: "Person", label: "TIE ALPHA" },
    { id: "person-tie-b", type: "Person", label: "TIE BETA" },
    { id: "person-pat-example-2", type: "Person", label: "PAT EXAMPLE" },
    { id: "person-float-noise", type: "Person", label: "FLOAT NOISE" },
    { id: "person-zero", type: "Person", label: "ZERO AMOUNT" },
    { id: "person-candidate", type: "Person", label: "CANDIDATE GAMMA" },
    { id: "person-pat-example", type: "Person", label: "PAT EXAMPLE" },
    { id: "person-official-only", type: "Person", label: "OFFICIAL ONLY" },
    { id: "person-ocr-only", type: "Person", label: "OCR ONLY" },
    { id: "person-evidenced", type: "Person", label: "EVIDENCED GIVER" },
    { id: "record-sample", type: "Record", label: "Sample filing record" },
    { id: "org-same-as-giver", type: "Organization", label: "LINKED GIVER INC" },
    { id: "org-same-as-peer", type: "Organization", label: "Linked Giver" },
    { id: "person-alias-giver", type: "Person", label: "ALIAS GIVER" },
    { id: "decision-vote", type: "Decision", label: "Approve the sample contract" },
    { id: "agreement-sample", type: "Agreement", label: "Sample services agreement" },
    { id: "agendaitem-sample", type: "AgendaItem", label: "Sample agenda item" },

    flow("moneyflow-able-1", 250, "2024-03-01", { ...DETAIL_ABLE_SAMPLETON, ...WITHHELD_PROPS }),
    flow("moneyflow-able-2", 100.1, "2024-04-01", DETAIL_ABLE_EXAMPLEVILLE),
    flow("moneyflow-able-refund", -25, "2024-05-01"),
    flow("moneyflow-able-beta", 60, "2023-09-09", DETAIL_ABLE_DEMOTOWN),
    ...Array.from({ length: 30 }, (_, i) =>
      flow(`moneyflow-small-${String(i).padStart(2, "0")}`, 50, `2024-02-${String((i % 28) + 1).padStart(2, "0")}`),
    ),
    flow("moneyflow-large", 1000, "2024-01-15"),
    flow("moneyflow-dup", 40, "2024-06-01"),
    flow("moneyflow-tie-a", 300, "2023-10-01"),
    flow("moneyflow-tie-b", 300, "2023-10-01"),
    flow("moneyflow-pat", 75, "2023-11-11"),
    flow("moneyflow-float-1", 0.1, "2023-12-01"),
    flow("moneyflow-float-2", 0.2, "2023-12-02"),
    flow("moneyflow-float-3", 12.35, "2023-12-03"),
    flow("moneyflow-zero", 0, "2023-12-04"),
    flow("moneyflow-candidate", 500, "2024-07-01"),
    flow("moneyflow-evidenced", 20, "2024-07-02"),
    flow("moneyflow-same-as", 1, "2024-07-03"),
    flow("moneyflow-alias", 1, "2024-07-04"),

    flow("moneyflow-expenditure", 900, "2024-08-01", {}, "expenditure"),
    flow("moneyflow-ocr", 5000, "2024-08-02", {}, "campaign_contribution"),
    flow("moneyflow-ocr-only", 700, "2024-08-03", {}, "campaign_contribution"),
    flow("moneyflow-contract", 250000, "2024-08-03", {}, "delegated_contract"),
  ];

  const give = (contributor: string, flowId: string, committee: string): EdgeRow[] => [
    [contributor, "FROM_SOURCE", flowId],
    [flowId, "TO_TARGET", committee],
  ];

  const edges: EdgeRow[] = [
    ...give("person-able-sample", "moneyflow-able-1", "committee-alpha"),
    ...give("person-able-sample", "moneyflow-able-2", "committee-alpha"),
    ...give("person-able-sample", "moneyflow-able-refund", "committee-alpha"),
    ...give("person-able-sample", "moneyflow-able-beta", "committee-beta"),
    ...Array.from({ length: 30 }, (_, i) =>
      give("person-many-small", `moneyflow-small-${String(i).padStart(2, "0")}`, "committee-alpha"),
    ).flat(),
    ...give("org-one-large", "moneyflow-large", "committee-alpha"),
    // The duplicate join path: both edges stored twice.
    ...give("person-dup-path", "moneyflow-dup", "committee-alpha"),
    ...give("person-dup-path", "moneyflow-dup", "committee-alpha"),
    ...give("person-tie-b", "moneyflow-tie-b", "committee-beta"),
    ...give("person-tie-a", "moneyflow-tie-a", "committee-beta"),
    ...give("person-pat-example-2", "moneyflow-pat", "committee-beta"),
    ...give("person-float-noise", "moneyflow-float-1", "committee-beta"),
    ...give("person-float-noise", "moneyflow-float-2", "committee-beta"),
    ...give("person-float-noise", "moneyflow-float-3", "committee-beta"),
    ...give("person-zero", "moneyflow-zero", "committee-beta"),
    ...give("person-candidate", "moneyflow-candidate", "committee-gamma"),
    ["committee-gamma", "CONTROLLED_BY", "person-candidate"],
    ...give("person-evidenced", "moneyflow-evidenced", "committee-gamma"),
    ["person-evidenced", "EVIDENCED_BY", "record-sample"],
    // Identity links are not roles: a contributor linked to a peer with no role of its own stays
    // contributor-only; one linked to an official does not.
    ...give("org-same-as-giver", "moneyflow-same-as", "committee-gamma"),
    ["org-same-as-peer", "SAME_AS", "org-same-as-giver"],
    ...give("person-alias-giver", "moneyflow-alias", "committee-gamma"),
    ["person-official-only", "SAME_AS", "person-alias-giver"],

    // Not reconciled contributions.
    ["committee-alpha", "FROM_SOURCE", "moneyflow-expenditure"],
    ["moneyflow-expenditure", "TO_TARGET", "person-able-sample"],
    ...give("person-able-sample", "moneyflow-ocr", "committee-alpha"),
    ...give("person-ocr-only", "moneyflow-ocr-only", "committee-alpha"),
    ["org-county", "FROM_SOURCE", "moneyflow-contract"],
    ["moneyflow-contract", "TO_TARGET", "org-one-large"],
    ["agreement-sample", "PARTY", "org-one-large"],

    // An official who shares a name with a contributor on another node.
    ["person-pat-example", "CAST_VOTE", "decision-vote"],
    ["person-official-only", "CAST_VOTE", "decision-vote"],
    ["decision-vote", "ON_AGENDA_ITEM", "agendaitem-sample"],
  ];

  nodes.push({ id: "org-county", type: "Organization", label: "Sample County" });
  return { nodes, edges };
}

export function makeContributionFixtureDb(): string {
  const dir = mkdtempSync(path.join(tmpdir(), "open-marin-contributions-"));
  const dbPath = path.join(dir, "public-substrate.sqlite");
  const db = new Database(dbPath);
  db.exec(`
    CREATE TABLE nodes (
      id TEXT PRIMARY KEY,
      type TEXT NOT NULL,
      search_label TEXT NOT NULL,
      props TEXT NOT NULL CHECK (json_valid(props))
    );
    CREATE TABLE edges (source TEXT NOT NULL, rel TEXT NOT NULL, target TEXT NOT NULL);
    CREATE INDEX idx_edges_source_rel_target ON edges(source, rel, target);
    CREATE INDEX idx_edges_target_rel_source ON edges(target, rel, source);
    CREATE TABLE identity_links (
      source TEXT NOT NULL,
      target TEXT NOT NULL,
      assertion_id TEXT NOT NULL,
      basis TEXT,
      decided_at TEXT,
      reviewer TEXT,
      PRIMARY KEY (source, target, assertion_id)
    );
    CREATE TABLE money_rollups (
      org_id TEXT PRIMARY KEY,
      flows_in_count INTEGER NOT NULL,
      money_in_total REAL NOT NULL,
      flows_out_count INTEGER NOT NULL,
      money_out_total REAL NOT NULL,
      top_counterparties TEXT NOT NULL CHECK (json_valid(top_counterparties))
    );
    CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
  `);
  const { nodes, edges } = buildContributionFixture();
  const insertNode = db.prepare("INSERT INTO nodes(id, type, search_label, props) VALUES (?, ?, ?, ?)");
  for (const node of nodes) {
    insertNode.run(node.id, node.type, node.label, JSON.stringify(node.props ?? {}));
  }
  const insertEdge = db.prepare("INSERT INTO edges(source, rel, target) VALUES (?, ?, ?)");
  for (const edge of edges) insertEdge.run(...edge);
  db.prepare(
    "INSERT INTO identity_links(source, target, assertion_id, basis) VALUES (?, ?, ?, ?)",
  ).run("org-one-large", "org-one-large-canonical", "assert-sample", "verified sample basis");
  db.prepare(
    "INSERT INTO identity_links(source, target, assertion_id, basis) VALUES (?, ?, ?, ?)",
  ).run("org-same-as-peer", "org-same-as-giver", "assert-peer", "sample basis");
  db.prepare(
    `INSERT INTO money_rollups VALUES ('org-one-large', 2, 251000, 1, 1000, ?)`,
  ).run(JSON.stringify([{ id: "org-county", label: "Sample County", total: 250000 }]));
  db.prepare("INSERT INTO meta(key, value) VALUES ('as_of_date', '2024-09-01')").run();
  db.close();
  return dbPath;
}
