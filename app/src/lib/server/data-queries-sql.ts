import "server-only";

import type { ColumnDef, DataQueryDef } from "@/lib/server/data-queries";
import { DATA_QUERIES } from "@/lib/server/data-queries";
import { getSubstrateDb } from "@/lib/server/substrate";

type SqlParam = string | number | null;

type SqlBuilt = {
  sql: string;
  params: Record<string, SqlParam>;
  includeAsOfDate?: boolean;
};

type SqlBuilder = (filters: Record<string, string>) => SqlBuilt;

export type DataQuerySqlResult = {
  rows: Record<string, unknown>[];
  as_of_date?: string;
};

function nonEmpty(v: string | undefined | null): string | null {
  if (v == null) return null;
  const t = v.trim();
  return t.length === 0 ? null : t;
}

function finiteNumber(raw: string | undefined, fallback: number): number {
  const parsed = Number(raw);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function prop(alias: string, key: string): string {
  return `json_extract(${alias}.props, '$.${key}')`;
}

function label(alias: string): string {
  return `coalesce(nullif(${alias}.search_label, ''), nullif(${prop(alias, "name")}, ''), ${alias}.id)`;
}

function titleLabel(alias: string): string {
  return `coalesce(nullif(${alias}.search_label, ''), nullif(${prop(alias, "title")}, ''), ${alias}.id)`;
}

function captionLabel(alias: string): string {
  return `coalesce(nullif(${alias}.search_label, ''), nullif(${prop(alias, "caption")}, ''), ${alias}.id)`;
}

function amountExpr(alias: string): string {
  return `CAST(${prop(alias, "amount")} AS REAL)`;
}

function datePresent(alias: string, key: string): string {
  return `NULLIF(${prop(alias, key)}, '') IS NOT NULL`;
}

function missingProp(alias: string, key: string): string {
  return `(json_type(${alias}.props, '$.${key}') IS NULL OR json_type(${alias}.props, '$.${key}') = 'null' OR ${prop(alias, key)} = '')`;
}

function readAsOfDate(): string | undefined {
  const row = getSubstrateDb()
    .prepare("SELECT value FROM meta WHERE key = 'as_of_date'")
    .get() as { value: string } | undefined;
  return row?.value;
}

function projectRows(rows: Record<string, unknown>[], columns: ColumnDef[]) {
  return rows.map((row) => {
    const projected: Record<string, unknown> = {};
    for (const col of columns) {
      projected[col.key] = row[col.key] ?? null;
    }
    return projected;
  });
}

const sanRafaelDecisions: SqlBuilder = (filters) => {
  const fromDate = nonEmpty(filters.from_date) ?? "2019-01-01";
  const toDate = nonEmpty(filters.to_date) ?? new Date().toISOString().slice(0, 10);
  const institutionId = nonEmpty(filters.institution_id);
  return {
    sql: `
      SELECT
        ${prop("d", "decided_at")} AS decided_at,
        ${titleLabel("d")} AS title,
        coalesce(${label("inst")}, ${prop("d", "institution_id")}) AS institution_name,
        d.id AS id
      FROM nodes d
      LEFT JOIN nodes inst
        ON inst.id = ${prop("d", "institution_id")}
       AND inst.type = 'Organization'
      WHERE d.type = 'Decision'
        AND ${prop("d", "institution_id")} LIKE 'org-san-rafael-%'
        AND ${prop("d", "decided_at")} >= @from_date
        AND ${prop("d", "decided_at")} <= @to_date
        AND (@institution_id IS NULL OR ${prop("d", "institution_id")} = @institution_id)
      ORDER BY decided_at DESC, id ASC
      LIMIT 500
    `,
    params: {
      from_date: fromDate,
      to_date: toDate,
      institution_id: institutionId,
    },
  };
};

const moneyFlowsByYear: SqlBuilder = (filters) => {
  const minAmount = finiteNumber(nonEmpty(filters.min_amount) ?? "1000", 0);
  const year = nonEmpty(filters.year);
  const flowType = nonEmpty(filters.flow_type);
  return {
    sql: `
      SELECT
        ${prop("m", "flow_date")} AS flow_date,
        ${amountExpr("m")} AS amount,
        ${prop("m", "flow_type")} AS flow_type,
        ${label("src")} AS source_name,
        ${label("tgt")} AS target_name,
        m.id AS id
      FROM nodes m
      LEFT JOIN edges src_edge
        ON src_edge.source = m.id
       AND src_edge.rel = 'FROM_SOURCE'
      LEFT JOIN nodes src
        ON src.id = src_edge.target
      LEFT JOIN edges tgt_edge
        ON tgt_edge.source = m.id
       AND tgt_edge.rel = 'TO_TARGET'
      LEFT JOIN nodes tgt
        ON tgt.id = tgt_edge.target
      WHERE m.type = 'MoneyFlow'
        AND coalesce(${amountExpr("m")}, 0) >= @min_amount
        AND (@year_prefix IS NULL OR ${prop("m", "flow_date")} LIKE @year_prefix || '%')
        AND (@flow_type IS NULL OR ${prop("m", "flow_type")} = @flow_type)
      ORDER BY flow_date DESC, id ASC
      LIMIT 500
    `,
    params: {
      min_amount: minAmount,
      year_prefix: year == null ? null : `${year}-`,
      flow_type: flowType,
    },
  };
};

const filingsByFiler: SqlBuilder = (filters) => {
  const fromDate = nonEmpty(filters.from_date) ?? "2020-01-01";
  const toDate = nonEmpty(filters.to_date) ?? new Date().toISOString().slice(0, 10);
  const filingType = nonEmpty(filters.filing_type);
  const filerId = nonEmpty(filters.filer_id);
  return {
    sql: `
      SELECT
        ${prop("f", "signed_at")} AS signed_at,
        ${prop("f", "filing_type")} AS filing_type,
        coalesce(${label("filer")}, ${prop("f", "filed_by")}) AS filed_by_name,
        f.id AS id
      FROM nodes f
      LEFT JOIN edges filed_by_edge
        ON filed_by_edge.source = f.id
       AND filed_by_edge.rel = 'FILED_BY'
      LEFT JOIN nodes filer
        ON filer.id = filed_by_edge.target
      WHERE f.type = 'Filing'
        AND ${prop("f", "signed_at")} >= @from_date
        AND ${prop("f", "signed_at")} <= @to_date
        AND (@filing_type IS NULL OR ${prop("f", "filing_type")} = @filing_type)
        AND (
          @filer_id IS NULL
          OR filer.id = @filer_id
          OR ${prop("f", "filed_by")} = @filer_id
        )
      ORDER BY signed_at DESC, id ASC
      LIMIT 500
    `,
    params: {
      from_date: fromDate,
      to_date: toDate,
      filing_type: filingType,
      filer_id: filerId,
    },
  };
};

const currentOfficeholders: SqlBuilder = (filters) => {
  const jurisdictionId = nonEmpty(filters.jurisdiction_id);
  return {
    sql: `
      WITH current(as_of_date) AS (
        SELECT value FROM meta WHERE key = 'as_of_date'
      ),
      services AS (
        SELECT DISTINCT
          p.id AS person_id,
          svc.id AS service_id
        FROM current, nodes p
        JOIN edges held_edge
          ON held_edge.rel = 'HELD_BY'
         AND (held_edge.source = p.id OR held_edge.target = p.id)
        JOIN nodes svc
          ON svc.type = 'SeatService'
         AND svc.id = CASE
           WHEN held_edge.source = p.id THEN held_edge.target
           ELSE held_edge.source
         END
        LEFT JOIN edges seat_edge
          ON seat_edge.source = svc.id
         AND seat_edge.rel = 'FOR_SEAT'
        LEFT JOIN nodes seat
          ON seat.id = seat_edge.target
         AND seat.type = 'Seat'
        WHERE p.type = 'Person'
          AND (${prop("svc", "ended_at")} IS NULL OR ${prop("svc", "ended_at")} = '' OR ${prop("svc", "ended_at")} >= current.as_of_date)
          AND (
            @jurisdiction_id IS NULL
            OR ${prop("seat", "jurisdiction_id")} = @jurisdiction_id
            OR ${prop("svc", "jurisdiction_id")} = @jurisdiction_id
          )
      )
      SELECT
        ${label("p")} AS person_name,
        coalesce(${prop("seat", "name")}, ${prop("svc", "seat_id")}, svc.id) AS seat_display,
        (
          SELECT count(DISTINCT f700.id)
          FROM nodes f700
          JOIN edges f700_edge
            ON f700_edge.source = f700.id
           AND f700_edge.rel = 'FILED_BY'
           AND f700_edge.target = p.id
          WHERE f700.type = 'Filing'
            AND ${prop("f700", "filing_type")} = 'form_700'
        ) AS form_700_count,
        (
          SELECT count(DISTINCT f803.id)
          FROM nodes f803
          JOIN edges f803_edge
            ON f803_edge.source = f803.id
           AND f803_edge.rel = 'FILED_BY'
           AND f803_edge.target = p.id
          WHERE f803.type = 'Filing'
            AND ${prop("f803", "filing_type")} = 'form_803'
        ) AS form_803_count,
        p.id AS id
      FROM services
      JOIN nodes p ON p.id = services.person_id
      JOIN nodes svc ON svc.id = services.service_id
      LEFT JOIN edges seat_edge
        ON seat_edge.source = svc.id
       AND seat_edge.rel = 'FOR_SEAT'
      LEFT JOIN nodes seat
        ON seat.id = seat_edge.target
       AND seat.type = 'Seat'
      ORDER BY person_name ASC, id ASC
      LIMIT 500
    `,
    params: { jurisdiction_id: jurisdictionId },
    includeAsOfDate: true,
  };
};

const agreementsForProject: SqlBuilder = (filters) => {
  const projectId = nonEmpty(filters.project_id);
  return {
    sql: `
      SELECT
        ${label("a")} AS agreement_name,
        ${prop("a", "effective_date")} AS effective_date,
        ${amountExpr("a")} AS amount,
        (
          SELECT count(*)
          FROM nodes am
          JOIN edges am_edge
            ON am_edge.source = am.id
           AND am_edge.rel = 'AMENDS_AGREEMENT'
           AND am_edge.target = a.id
          WHERE am.type = 'Amendment'
        ) AS amendment_count,
        a.id AS id
      FROM nodes a
      WHERE a.type = 'Agreement'
        AND (
          @project_id IS NULL
          OR ${prop("a", "project_id")} = @project_id
          OR EXISTS (
            SELECT 1
            FROM edges project_edge
            JOIN nodes p
              ON p.type = 'Project'
             AND p.id = @project_id
             AND (p.id = project_edge.source OR p.id = project_edge.target)
            WHERE project_edge.source = a.id OR project_edge.target = a.id
          )
        )
      ORDER BY effective_date DESC, id ASC
      LIMIT 500
    `,
    params: { project_id: projectId },
  };
};

const legalProceedings: SqlBuilder = (filters) => {
  const caseId = nonEmpty(filters.case_id);
  return {
    sql: `
      SELECT
        ${captionLabel("c")} AS case_caption,
        ${prop("pr", "proceeding_type")} AS proceeding_type,
        ${prop("pr", "occurred_at")} AS occurred_at,
        ${label("link")} AS affected_program,
        pr.id AS id
      FROM nodes pr
      JOIN edges case_edge
        ON case_edge.source = pr.id
       AND case_edge.rel IN ('PART_OF', 'PART_OF_CASE')
      JOIN nodes c
        ON c.id = case_edge.target
       AND c.type = 'Case'
      LEFT JOIN (
        SELECT edge.source AS case_id, linked.id AS link_id
        FROM edges edge
        JOIN nodes linked
          ON linked.id = edge.target
         AND linked.type IN ('Program', 'Project')
        UNION
        SELECT edge.target AS case_id, linked.id AS link_id
        FROM edges edge
        JOIN nodes linked
          ON linked.id = edge.source
         AND linked.type IN ('Program', 'Project')
      ) link_match
        ON link_match.case_id = c.id
      LEFT JOIN nodes link
        ON link.id = link_match.link_id
      WHERE pr.type = 'Proceeding'
        AND (@case_id IS NULL OR c.id = @case_id)
      ORDER BY occurred_at DESC, id ASC
      LIMIT 500
    `,
    params: { case_id: caseId },
  };
};

const evidenceRecords: SqlBuilder = (filters) => {
  const targetId = nonEmpty(filters.target_id);
  return {
    sql: `
      SELECT
        ${prop("r", "record_type")} AS record_type,
        ${prop("r", "captured_at")} AS captured_at,
        ${prop("r", "preferred_display_artifact")} AS preferred_display_artifact,
        ${prop("r", "preferred_public_url")} AS preferred_public_url,
        r.id AS id
      FROM nodes target
      JOIN edges evidence_edge
        ON evidence_edge.source = target.id
       AND evidence_edge.rel = 'EVIDENCED_BY'
      JOIN nodes r
        ON r.id = evidence_edge.target
       AND r.type = 'Record'
      WHERE target.id = @target_id
      ORDER BY captured_at DESC, id ASC
      LIMIT 500
    `,
    params: { target_id: targetId },
  };
};

const localPressureRanking: SqlBuilder = () => ({
  sql: `
    SELECT
      ${label("t")} AS thread_name,
      t.type AS type,
      coalesce((
        SELECT sum(coalesce(${amountExpr("m")}, 0))
        FROM edges money_edge
        JOIN nodes m
          ON m.type = 'MoneyFlow'
         AND m.id = CASE
           WHEN money_edge.source = t.id THEN money_edge.target
           ELSE money_edge.source
         END
        WHERE money_edge.source = t.id OR money_edge.target = t.id
      ), 0) AS money_pressure,
      (
        SELECT count(DISTINCT pr.id)
        FROM edges proceeding_edge
        JOIN nodes pr
          ON pr.type = 'Proceeding'
         AND pr.id = CASE
           WHEN proceeding_edge.source = t.id THEN proceeding_edge.target
           ELSE proceeding_edge.source
         END
        WHERE proceeding_edge.source = t.id OR proceeding_edge.target = t.id
      ) AS legal_pressure,
      (
        SELECT count(DISTINCT r.id)
        FROM edges evidence_edge
        JOIN nodes r
          ON r.type = 'Record'
         AND r.id = evidence_edge.target
        WHERE evidence_edge.source = t.id
          AND evidence_edge.rel = 'EVIDENCED_BY'
      ) AS evidence_density,
      t.id AS id
    FROM nodes t
    WHERE t.type IN ('Project', 'Program', 'Case')
      AND (
        ${prop("t", "primary_place_id")} = 'place-san-rafael'
        OR ${prop("t", "jurisdiction_place_id")} = 'place-san-rafael'
        OR EXISTS (
          SELECT 1
          FROM json_each(t.props, '$.place_ids') AS place
          WHERE place.value = 'place-san-rafael'
        )
        OR t.id LIKE '%san-rafael%'
      )
    ORDER BY money_pressure DESC, legal_pressure DESC, evidence_density DESC, id ASC
    LIMIT 100
  `,
  params: {},
});

const campaignMoneyNearDecisions: SqlBuilder = (filters) => {
  const windowDays = finiteNumber(nonEmpty(filters.window_days) ?? "30", 30);
  const jurisdiction = nonEmpty(filters.jurisdiction) ?? "san-rafael";
  return {
    sql: `
      SELECT
        ${titleLabel("d")} AS decision_title,
        ${prop("d", "decided_at")} AS decided_at,
        ${amountExpr("m")} AS money_amount,
        ${prop("m", "flow_date")} AS flow_date,
        CAST(julianday(${prop("d", "decided_at")}) - julianday(${prop("m", "flow_date")}) AS INTEGER) AS days_delta,
        m.id AS id
      FROM nodes d
      JOIN nodes m
        ON m.type = 'MoneyFlow'
      WHERE d.type = 'Decision'
        AND (${prop("d", "institution_id")} LIKE '%' || @jurisdiction || '%' OR d.id LIKE '%' || @jurisdiction || '%')
        AND ${datePresent("d", "decided_at")}
        AND ${datePresent("m", "flow_date")}
        AND julianday(${prop("d", "decided_at")}) IS NOT NULL
        AND julianday(${prop("m", "flow_date")}) IS NOT NULL
        AND abs(julianday(${prop("d", "decided_at")}) - julianday(${prop("m", "flow_date")})) <= @window_days
      ORDER BY abs(days_delta) ASC, decided_at DESC, id ASC
      LIMIT 500
    `,
    params: {
      window_days: windowDays,
      jurisdiction,
    },
  };
};

const qaValidationGaps: SqlBuilder = () => ({
  sql: `
    SELECT
      'decisions.missing_decided_at' AS category,
      'Decisions with no decided_at date' AS description,
      count(*) AS count
    FROM nodes d
    WHERE d.type = 'Decision' AND ${missingProp("d", "decided_at")}
    UNION ALL
    SELECT
      'money_flows.missing_amount' AS category,
      'Money flows with no amount' AS description,
      count(*) AS count
    FROM nodes m
    WHERE m.type = 'MoneyFlow'
      AND (json_type(m.props, '$.amount') IS NULL OR json_type(m.props, '$.amount') = 'null')
    UNION ALL
    SELECT
      'filings.missing_signed_at' AS category,
      'Filings with no signed_at date' AS description,
      count(*) AS count
    FROM nodes f
    WHERE f.type = 'Filing' AND ${missingProp("f", "signed_at")}
    UNION ALL
    SELECT
      'records.orphan_no_target' AS category,
      'Records not attached to any target' AS description,
      count(*) AS count
    FROM nodes r
    WHERE r.type = 'Record'
      AND NOT EXISTS (
        SELECT 1
        FROM edges evidence_edge
        WHERE evidence_edge.rel = 'EVIDENCED_BY'
          AND evidence_edge.target = r.id
      )
    UNION ALL
    SELECT
      'agreements.missing_effective_date' AS category,
      'Agreements with no effective_date' AS description,
      count(*) AS count
    FROM nodes a
    WHERE a.type = 'Agreement' AND ${missingProp("a", "effective_date")}
  `,
  params: {},
});

export const DATA_QUERY_SQL_BUILDERS: Record<string, SqlBuilder> = {
  "san-rafael-decisions-since-2019": sanRafaelDecisions,
  "money-flows-by-year": moneyFlowsByYear,
  "filings-by-person-or-committee": filingsByFiler,
  "current-officeholders-form-coverage": currentOfficeholders,
  "agreements-and-amendments-for-project": agreementsForProject,
  "legal-proceedings-affecting-local": legalProceedings,
  "evidence-records-supporting": evidenceRecords,
  "local-pressure-ranking-sr": localPressureRanking,
  "campaign-money-near-decisions": campaignMoneyNearDecisions,
  "qa-validation-gaps": qaValidationGaps,
};

const registeredSlugs = new Set(DATA_QUERIES.map((query) => query.slug));
const sqlSlugs = new Set(Object.keys(DATA_QUERY_SQL_BUILDERS));
for (const slug of registeredSlugs) {
  if (!sqlSlugs.has(slug)) {
    throw new Error(`missing SQL data query builder: ${slug}`);
  }
}

export function runDataQuerySql(
  def: DataQueryDef,
  filters: Record<string, string>,
): DataQuerySqlResult {
  const builder = DATA_QUERY_SQL_BUILDERS[def.slug];
  if (!builder) {
    throw new Error(`missing SQL data query builder: ${def.slug}`);
  }

  const built = builder(filters);
  const rows = getSubstrateDb().prepare(built.sql).all(built.params) as Record<
    string,
    unknown
  >[];
  const result: DataQuerySqlResult = {
    rows: projectRows(rows, def.columns),
  };
  if (built.includeAsOfDate) {
    result.as_of_date = readAsOfDate();
  }
  return result;
}
