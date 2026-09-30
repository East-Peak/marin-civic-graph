// app/src/lib/server/contributions-sql.ts
//
// The one reader of reconciled campaign contributions (MoneyFlow flow_type = 'contribution':
// NetFile filings for Marin County and Novato). A contributor node is a name group — every
// contribution filed under one name slug — so everything here is "reported under this name",
// never an identity. Rules every query keeps:
//   - Only the flow's own reported_* props are read; the contributor node's props never are.
//   - Counts and totals aggregate DISTINCT flow ids in integer cents, never money_rollups
//     (which mixes flow types and SAME_AS-linked organizations).
//   - Lists page by keyset cursors "<cents>:<id>" so a traversal never skips or repeats a row.
// Public-artifact surfaces: this reads the substrate in either serving mode.
import "server-only";

import { canonicalType } from "@/lib/canonical-type";
import {
  contributionNameRoute,
  entityRoute,
  isContributorType,
  resolveContributorId,
  resolveEntityId,
  type ContributorType,
} from "@/lib/entity-route";
import { getSubstrateDb } from "@/lib/server/substrate";

export type ReportedDetails = {
  occupation: string | null;
  employer: string | null;
  city: string | null;
  state: string | null;
  zip5: string | null;
};

export type ContributorRef = { id: string; type: ContributorType; label: string; name_route: string };
export type RecipientRef = { id: string; label: string; route: string };

export type ContributionRow = {
  flow_id: string;
  flow_route: string;
  date: string | null;
  amount_cents: number;
  details: ReportedDetails;
};

export type NameViewRow = ContributionRow & { recipient: RecipientRef | null };

export type ContributionsByName = {
  contributor: { id: string; type: ContributorType; label: string };
  rows: NameViewRow[];
  totals: { count: number; total_cents: number };
  by_committee: { recipient: RecipientRef; count: number; total_cents: number }[];
};

export type CommitteeContributor = {
  /** 1-based position in this committee's ranking by total, then id. */
  rank: number;
  contributor: ContributorRef;
  count: number;
  total_cents: number;
  rows: ContributionRow[];
};

export type CommitteeTopContributors = {
  summary: { names: number; count: number; total_cents: number };
  rows: CommitteeContributor[];
  next_cursor: string | null;
};

export type LargestContributionRow = ContributionRow & {
  contributor: ContributorRef | null;
  recipient: RecipientRef | null;
};

export type LargestContributions = { rows: LargestContributionRow[]; next_cursor: string | null };

export class InvalidCursorError extends Error {}

type PageOptions = { limit: number; after?: string | null };

const text = (alias: string, key: string) => `NULLIF(TRIM(json_extract(${alias}.props, '$.${key}')), '')`;

/** One row per stored contribution flow with its own reported details. */
const FLOW_COLUMNS = `
  m.id AS flow_id,
  ${text("m", "flow_date")} AS date,
  CAST(ROUND(CAST(json_extract(m.props, '$.amount') AS REAL) * 100) AS INTEGER) AS amount_cents,
  ${text("m", "reported_occupation")} AS occupation,
  ${text("m", "reported_employer")} AS employer,
  ${text("m", "reported_city")} AS city,
  ${text("m", "reported_state")} AS state,
  ${text("m", "reported_zip5")} AS zip5`;

const IS_CONTRIBUTION = `m.type = 'MoneyFlow' AND json_extract(m.props, '$.flow_type') = 'contribution'`;

/**
 * Distinct (flow, contributor, recipient) triples: a duplicated edge row joins twice
 * but DISTINCT collapses it. Contributors are Person/Organization; recipients Committees.
 * `recipient: "optional"` keeps a flow that reaches no committee (recipient null), for a
 * name's own list; a committee's ranking joins it as required so its filter uses the index.
 */
function contributionTriples(recipient: "required" | "optional"): string {
  const join = recipient === "required" ? "JOIN" : "LEFT JOIN";
  return `
  SELECT DISTINCT
    ${FLOW_COLUMNS},
    c.id AS contributor_id,
    c.type AS contributor_type,
    c.search_label AS contributor_label,
    r.id AS recipient_id,
    r.search_label AS recipient_label
  FROM nodes m
  JOIN edges fe ON fe.target = m.id AND fe.rel = 'FROM_SOURCE'
  JOIN nodes c ON c.id = fe.source AND c.type IN ('Person', 'Organization')
  ${join} edges te ON te.source = m.id AND te.rel = 'TO_TARGET'
    AND EXISTS (SELECT 1 FROM nodes rc WHERE rc.id = te.target AND rc.type = 'Committee')
  ${join} nodes r ON r.id = te.target
  WHERE ${IS_CONTRIBUTION}`;
}

const NAME_TRIPLES = contributionTriples("optional");
const COMMITTEE_TRIPLES = contributionTriples("required");

type FlowSql = {
  flow_id: string;
  date: string | null;
  amount_cents: number;
  occupation: string | null;
  employer: string | null;
  city: string | null;
  state: string | null;
  zip5: string | null;
};

function toContributionRow(row: FlowSql): ContributionRow {
  return {
    flow_id: row.flow_id,
    flow_route: entityRoute(row.flow_id, "MoneyFlow"),
    date: row.date,
    amount_cents: Number(row.amount_cents),
    details: {
      occupation: row.occupation,
      employer: row.employer,
      city: row.city,
      state: row.state,
      zip5: row.zip5,
    },
  };
}

function recipientRef(id: string, label: string): RecipientRef {
  return { id, label, route: entityRoute(id, "Committee") };
}

function contributorRef(id: string, type: string, label: string): ContributorRef | null {
  if (!isContributorType(type as ContributorType)) return null;
  const contributorType = type as ContributorType;
  return { id, type: contributorType, label, name_route: contributionNameRoute(id, contributorType) };
}

function clampLimit(limit: number): number {
  return Math.max(1, Math.min(100, Math.floor(limit)));
}

function parseCursor(after: string | null | undefined): { cents: number; id: string } | null {
  if (after == null || after === "") return null;
  const match = /^(-?\d+):(.+)$/.exec(after);
  const cents = match ? Number(match[1]) : NaN;
  if (!match || !Number.isSafeInteger(cents)) throw new InvalidCursorError(`malformed cursor: ${after}`);
  return { cents, id: match[2] };
}

const cursorFor = (cents: number, id: string) => `${cents}:${id}`;

// ---------------------------------------------------------------------------
// Name view
// ---------------------------------------------------------------------------

export type ContributorNode = { id: string; type: ContributorType; label: string };

type RouteResolver = typeof resolveEntityId;

function resolveNode(resolve: RouteResolver, segment: string, slug: string): ContributorNode | null {
  const lookup = getSubstrateDb().prepare("SELECT type, search_label FROM nodes WHERE id = ?");
  const stored = (id: string) => lookup.get(id) as { type: string; search_label: string } | undefined;
  const id = resolve(segment, slug, (candidate) => {
    const row = stored(candidate);
    return row ? canonicalType([row.type], candidate) : null;
  });
  const row = id ? stored(id) : undefined;
  const type = id && row ? canonicalType([row.type], id) : null;
  return id && row && isContributorType(type) ? { id, type, label: row.search_label } : null;
}

/** The Person/Organization node a `/contributions/by-name/<segment>/<slug>` route names. */
export function resolveContributorNode(segment: string, slug: string): ContributorNode | null {
  return resolveNode(resolveContributorId, segment, slug);
}

/** The Person/Organization node an entity route (legacy /actor/, /inst/ included) renders. */
export function resolveEntityContributorNode(segment: string, slug: string): ContributorNode | null {
  return resolveNode(resolveEntityId, segment, slug);
}

type TripleSql = FlowSql & {
  contributor_id: string;
  contributor_type: string;
  contributor_label: string;
  recipient_id: string | null;
  recipient_label: string | null;
};

export function loadContributionsByName(nodeId: string): ContributionsByName | null {
  const db = getSubstrateDb();
  const rows = db
    .prepare(
      `SELECT * FROM (${NAME_TRIPLES}) WHERE contributor_id = ?
       ORDER BY date IS NULL, date DESC, flow_id ASC, recipient_id ASC`,
    )
    .all(nodeId) as TripleSql[];
  if (rows.length === 0) return null;

  const first = rows[0];
  const type = first.contributor_type as ContributorType;

  const totals = db
    .prepare(
      `SELECT COUNT(*) AS count, COALESCE(SUM(amount_cents), 0) AS total_cents
       FROM (SELECT DISTINCT flow_id, amount_cents FROM (${NAME_TRIPLES}) WHERE contributor_id = ?)`,
    )
    .get(nodeId) as { count: number; total_cents: number };

  const byCommittee = new Map<string, { recipient: RecipientRef; count: number; total_cents: number }>();
  for (const row of rows) {
    if (row.recipient_id === null || row.recipient_label === null) continue;
    const entry = byCommittee.get(row.recipient_id) ?? {
      recipient: recipientRef(row.recipient_id, row.recipient_label),
      count: 0,
      total_cents: 0,
    };
    entry.count += 1;
    entry.total_cents += Number(row.amount_cents);
    byCommittee.set(row.recipient_id, entry);
  }

  return {
    contributor: { id: first.contributor_id, type, label: first.contributor_label },
    rows: rows.map((row) => ({
      ...toContributionRow(row),
      recipient:
        row.recipient_id !== null && row.recipient_label !== null
          ? recipientRef(row.recipient_id, row.recipient_label)
          : null,
    })),
    totals: { count: Number(totals.count), total_cents: Number(totals.total_cents) },
    by_committee: [...byCommittee.values()].sort(
      (a, b) => b.total_cents - a.total_cents || a.recipient.id.localeCompare(b.recipient.id),
    ),
  };
}

// ---------------------------------------------------------------------------
// Top contributors to one committee
// ---------------------------------------------------------------------------

type NameTotalSql = {
  rank: number;
  contributor_id: string;
  contributor_type: string;
  contributor_label: string;
  count: number;
  total_cents: number;
};

export function loadCommitteeTopContributors(
  committeeId: string,
  { limit, after }: PageOptions,
): CommitteeTopContributors {
  const db = getSubstrateDb();
  const cursor = parseCursor(after);
  const pageSize = clampLimit(limit);
  const committeeRows = `SELECT * FROM (${COMMITTEE_TRIPLES}) WHERE recipient_id = @committeeId`;
  const nameTotals = `
    SELECT ROW_NUMBER() OVER (ORDER BY SUM(amount_cents) DESC, contributor_id ASC) AS rank,
           contributor_id, contributor_type, contributor_label,
           COUNT(*) AS count, SUM(amount_cents) AS total_cents
    FROM (SELECT DISTINCT flow_id, amount_cents, contributor_id, contributor_type, contributor_label
          FROM (${committeeRows}))
    GROUP BY contributor_id`;

  const summary = db
    .prepare(
      `SELECT COUNT(DISTINCT contributor_id) AS names, COUNT(DISTINCT flow_id) AS count,
              COALESCE((SELECT SUM(amount_cents) FROM (SELECT DISTINCT flow_id, amount_cents FROM (${committeeRows}))), 0)
                AS total_cents
       FROM (${committeeRows})`,
    )
    .get({ committeeId }) as { names: number; count: number; total_cents: number };

  const names = db
    .prepare(
      `SELECT * FROM (${nameTotals})
       WHERE @afterCents IS NULL
          OR total_cents < @afterCents
          OR (total_cents = @afterCents AND contributor_id > @afterId)
       ORDER BY total_cents DESC, contributor_id ASC
       LIMIT @take`,
    )
    .all({
      committeeId,
      afterCents: cursor?.cents ?? null,
      afterId: cursor?.id ?? null,
      take: pageSize + 1,
    }) as NameTotalSql[];

  const page = names.slice(0, pageSize);
  const rowsFor = db.prepare(
    `SELECT DISTINCT flow_id, date, amount_cents, occupation, employer, city, state, zip5
     FROM (${committeeRows}) WHERE contributor_id = @contributorId
     ORDER BY date IS NULL, date DESC, flow_id ASC`,
  );

  const rows = page.flatMap((name): CommitteeContributor[] => {
    const contributor = contributorRef(name.contributor_id, name.contributor_type, name.contributor_label);
    if (!contributor) return [];
    const flows = rowsFor.all({ committeeId, contributorId: name.contributor_id }) as FlowSql[];
    return [
      {
        rank: Number(name.rank),
        contributor,
        count: Number(name.count),
        total_cents: Number(name.total_cents),
        rows: flows.map(toContributionRow),
      },
    ];
  });

  const last = page.at(-1);
  return {
    summary: {
      names: Number(summary.names),
      count: Number(summary.count),
      total_cents: Number(summary.total_cents),
    },
    rows,
    next_cursor: names.length > pageSize && last ? cursorFor(Number(last.total_cents), last.contributor_id) : null,
  };
}

// ---------------------------------------------------------------------------
// Largest contributions
// ---------------------------------------------------------------------------

/** Direct count of reconciled contribution MoneyFlows. */
export function countContributions(): number {
  const row = getSubstrateDb()
    .prepare(`SELECT COUNT(DISTINCT m.id) AS n FROM nodes m WHERE ${IS_CONTRIBUTION}`)
    .get() as { n: number };
  return Number(row.n);
}

type LargestSql = FlowSql & {
  contributor_id: string | null;
  contributor_type: string | null;
  contributor_label: string | null;
  recipient_id: string | null;
  recipient_label: string | null;
};

/**
 * One row per contribution flow — including any whose contributor or recipient is missing
 * or of another type, so the list always reconciles to countContributions(). A flow stored
 * with several contributors or recipients shows the first by id.
 */
export function loadLargestContributions({ limit, after }: PageOptions): LargestContributions {
  const cursor = parseCursor(after);
  const pageSize = clampLimit(limit);
  const rows = getSubstrateDb()
    .prepare(
      `WITH flows AS (
         SELECT ${FLOW_COLUMNS},
           (SELECT c.id FROM edges fe JOIN nodes c ON c.id = fe.source
             WHERE fe.target = m.id AND fe.rel = 'FROM_SOURCE' ORDER BY c.id LIMIT 1) AS contributor_id,
           (SELECT r.id FROM edges te JOIN nodes r ON r.id = te.target AND r.type = 'Committee'
             WHERE te.source = m.id AND te.rel = 'TO_TARGET' ORDER BY r.id LIMIT 1) AS recipient_id
         FROM nodes m
         WHERE ${IS_CONTRIBUTION}
       )
       SELECT flows.*,
              c.type AS contributor_type, c.search_label AS contributor_label,
              r.search_label AS recipient_label
       FROM flows
       LEFT JOIN nodes c ON c.id = flows.contributor_id
       LEFT JOIN nodes r ON r.id = flows.recipient_id
       WHERE @afterCents IS NULL
          OR amount_cents < @afterCents
          OR (amount_cents = @afterCents AND flow_id > @afterId)
       ORDER BY amount_cents DESC, flow_id ASC
       LIMIT @take`,
    )
    .all({ afterCents: cursor?.cents ?? null, afterId: cursor?.id ?? null, take: pageSize + 1 }) as LargestSql[];

  const page = rows.slice(0, pageSize);
  const last = page.at(-1);
  return {
    rows: page.map((row) => ({
      ...toContributionRow(row),
      contributor:
        row.contributor_id && row.contributor_type && row.contributor_label != null
          ? contributorRef(row.contributor_id, row.contributor_type, row.contributor_label)
          : null,
      recipient:
        row.recipient_id && row.recipient_label != null ? recipientRef(row.recipient_id, row.recipient_label) : null,
    })),
    next_cursor: rows.length > pageSize && last ? cursorFor(Number(last.amount_cents), last.flow_id) : null,
  };
}

// ---------------------------------------------------------------------------
// Contributor-only nodes (noindex on their entity pages)
// ---------------------------------------------------------------------------

/**
 * True when a Person/Organization's only public role is contributing: it gives to at least
 * one contribution-type MoneyFlow (reconciled or San Rafael OCR), and neither it nor any node
 * it is identity-linked to (SAME_AS edge or identity_links row) has an edge other than such
 * gifts, EVIDENCED_BY (provenance) or SAME_AS. Identity links are not roles; a linked peer's
 * roles are, because its page and this one describe the same linked identity.
 */
export function isContributorOnly(nodeId: string): boolean {
  const row = getSubstrateDb()
    .prepare(
      `WITH linked(id) AS (
         SELECT @id
         UNION SELECT CASE WHEN source = @id THEN target ELSE source END
           FROM edges WHERE rel = 'SAME_AS' AND (source = @id OR target = @id)
         UNION SELECT CASE WHEN source = @id THEN target ELSE source END
           FROM identity_links WHERE source = @id OR target = @id
       ),
       touching AS (
         SELECT l.id AS node, e.rel, e.source,
                COALESCE(e.rel = 'FROM_SOURCE' AND e.source = l.id AND m.type = 'MoneyFlow'
                  AND json_extract(m.props, '$.flow_type') IN ('contribution', 'campaign_contribution'), 0) AS gives
         FROM linked l
         JOIN edges e ON e.source = l.id OR e.target = l.id
         LEFT JOIN nodes m ON m.id = e.target
       )
       SELECT
         (SELECT COUNT(*) FROM nodes WHERE id = @id AND type IN ('Person', 'Organization')) AS present,
         (SELECT COUNT(*) FROM touching WHERE node = @id AND gives) AS gifts,
         (SELECT COUNT(*) FROM touching
           WHERE NOT gives AND rel <> 'SAME_AS' AND NOT (rel = 'EVIDENCED_BY' AND source = node)) AS other_roles`,
    )
    .get({ id: nodeId }) as { present: number; gifts: number; other_roles: number };
  return row.present > 0 && row.gifts > 0 && row.other_roles === 0;
}
