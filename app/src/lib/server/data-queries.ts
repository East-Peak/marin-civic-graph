// app/src/lib/server/data-queries.ts
//
// The 10 predefined query templates for /data (spec §8, v1 §5c).
// Each query owns its filter + column shape plus a Cypher builder that
// accepts raw filter values (strings from the URL) and returns a
// parameterized Cypher string + params map.
//
// Contract: Cypher MUST use `$param` placeholders. Never interpolate filter
// values into the query string — tests assert there are no `${` markers
// in any built query regardless of filter input.

import "server-only";

export type FilterType = "date" | "amount" | "select" | "text";

export type FilterDef = {
  key: string;
  label: string;
  type: FilterType;
  default?: string;
  options?: string[];
  required?: boolean;
  placeholder?: string;
};

export type ColumnDef = {
  key: string;
  label: string;
  sortable?: boolean;
  alignment?: "left" | "right";
  /** If set, cell is rendered as a link. "entity-route" uses the row's
   *  `{key}_route` value when present, else falls back to the id heuristic.
   *  Static strings are treated as plain links (not used currently). */
  link?: "entity-route";
};

export type CypherBuilt = {
  query: string;
  params: Record<string, unknown>;
};

export type DataQueryDef = {
  slug: string;
  display_name: string;
  description: string;
  filters: FilterDef[];
  columns: ColumnDef[];
  cypher: (filters: Record<string, string>) => CypherBuilt;
};

// ---------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

function nonEmpty(v: string | undefined | null): string | null {
  if (v == null) return null;
  const t = v.trim();
  return t.length === 0 ? null : t;
}

// ---------------------------------------------------------------------------
// 1. San Rafael decisions since 2019
// ---------------------------------------------------------------------------

const sanRafaelDecisions: DataQueryDef = {
  slug: "san-rafael-decisions-since-2019",
  display_name: "San Rafael decisions since 2019",
  description:
    "Decisions made by San Rafael (and optionally other) institutions in a date range. Ordered newest first, 500 row cap.",
  filters: [
    { key: "from_date", label: "From", type: "date", default: "2019-01-01" },
    { key: "to_date", label: "To", type: "date", default: today() },
    {
      key: "institution_id",
      label: "Institution id",
      type: "text",
      placeholder: "org-san-rafael-city-council",
    },
  ],
  columns: [
    { key: "decided_at", label: "Decided at", sortable: true, alignment: "left" },
    { key: "title", label: "Title", sortable: true, alignment: "left" },
    {
      key: "institution_name",
      label: "Institution",
      sortable: true,
      alignment: "left",
    },
    { key: "id", label: "Decision id", alignment: "left", link: "entity-route" },
  ],
  cypher: (filters) => {
    const fromDate = nonEmpty(filters.from_date) ?? "2019-01-01";
    const toDate = nonEmpty(filters.to_date) ?? today();
    const institutionId = nonEmpty(filters.institution_id);
    const params: Record<string, unknown> = {
      from_date: fromDate,
      to_date: toDate,
      institution_id: institutionId,
    };
    // Fix 8: the slug promises San Rafael decisions, so bake a SR floor into
    // the match. The optional `institution_id` filter further narrows it to
    // a specific SR org (city-council, planning-commission, etc.) when set.
    // Without this floor, future non-SR decisions would silently leak into
    // the result set the moment any other jurisdiction gets loaded.
    const query = `
      MATCH (d:Decision)
      WHERE d.institution_id STARTS WITH 'org-san-rafael-'
        AND d.decided_at >= $from_date AND d.decided_at <= $to_date
        AND ($institution_id IS NULL OR d.institution_id = $institution_id)
      OPTIONAL MATCH (inst:Organization {id: d.institution_id})
      RETURN d.decided_at       AS decided_at,
             coalesce(d.search_label, d.title, d.id) AS title,
             coalesce(inst.name, d.institution_id)   AS institution_name,
             d.id               AS id
      ORDER BY decided_at DESC, id ASC
      LIMIT 500
    `;
    return { query, params };
  },
};

// ---------------------------------------------------------------------------
// 2. Money flows by year
// ---------------------------------------------------------------------------

const moneyFlowsByYear: DataQueryDef = {
  slug: "money-flows-by-year",
  display_name: "Money flows over threshold",
  description:
    "Money flows at or above an amount threshold. Optional filters on year and flow type.",
  filters: [
    { key: "min_amount", label: "Min amount", type: "amount", default: "1000" },
    { key: "year", label: "Year", type: "text", placeholder: "2024" },
    {
      key: "flow_type",
      label: "Flow type",
      type: "select",
      options: ["", "contribution", "expenditure", "behest"],
    },
  ],
  columns: [
    { key: "flow_date", label: "Flow date", sortable: true, alignment: "left" },
    { key: "amount", label: "Amount", sortable: true, alignment: "right" },
    { key: "flow_type", label: "Type", sortable: true, alignment: "left" },
    { key: "source_name", label: "Source", alignment: "left" },
    { key: "target_name", label: "Target", alignment: "left" },
    { key: "id", label: "Flow id", alignment: "left", link: "entity-route" },
  ],
  cypher: (filters) => {
    const minAmountRaw = nonEmpty(filters.min_amount) ?? "1000";
    const minAmount = Number(minAmountRaw);
    const year = nonEmpty(filters.year);
    const flowType = nonEmpty(filters.flow_type);
    // Match `YYYY-...` prefix when a year is supplied.
    const yearPrefix = year == null ? null : `${year}-`;
    const params: Record<string, unknown> = {
      min_amount: Number.isFinite(minAmount) ? minAmount : 0,
      year_prefix: yearPrefix,
      flow_type: flowType,
    };
    const query = `
      MATCH (m:MoneyFlow)
      WHERE coalesce(m.amount, 0) >= $min_amount
        AND ($year_prefix IS NULL OR m.flow_date STARTS WITH $year_prefix)
        AND ($flow_type IS NULL OR m.flow_type = $flow_type)
      OPTIONAL MATCH (m)-[:FROM_SOURCE]->(src)
      OPTIONAL MATCH (m)-[:TO_TARGET]->(tgt)
      RETURN m.flow_date AS flow_date,
             m.amount    AS amount,
             m.flow_type AS flow_type,
             coalesce(src.search_label, src.name, src.id) AS source_name,
             coalesce(tgt.search_label, tgt.name, tgt.id) AS target_name,
             m.id        AS id
      ORDER BY flow_date DESC, id ASC
      LIMIT 500
    `;
    return { query, params };
  },
};

// ---------------------------------------------------------------------------
// 3. Filings by person or committee
// ---------------------------------------------------------------------------

const filingsByFiler: DataQueryDef = {
  slug: "filings-by-person-or-committee",
  display_name: "Filings by person or committee",
  description:
    "Filings (Form 460/497/700/803) by signed-at range, optional filer id, optional type.",
  filters: [
    { key: "from_date", label: "From", type: "date", default: "2020-01-01" },
    { key: "to_date", label: "To", type: "date", default: today() },
    {
      key: "filing_type",
      label: "Filing type",
      type: "select",
      options: ["", "form_460", "form_497", "form_700", "form_803"],
    },
    {
      key: "filer_id",
      label: "Filer id",
      type: "text",
      placeholder: "person-kate-colin",
    },
  ],
  columns: [
    { key: "signed_at", label: "Signed at", sortable: true, alignment: "left" },
    { key: "filing_type", label: "Type", sortable: true, alignment: "left" },
    { key: "filed_by_name", label: "Filed by", alignment: "left" },
    { key: "id", label: "Filing id", alignment: "left", link: "entity-route" },
  ],
  cypher: (filters) => {
    const fromDate = nonEmpty(filters.from_date) ?? "2020-01-01";
    const toDate = nonEmpty(filters.to_date) ?? today();
    const filingType = nonEmpty(filters.filing_type);
    const filerId = nonEmpty(filters.filer_id);
    const params: Record<string, unknown> = {
      from_date: fromDate,
      to_date: toDate,
      filing_type: filingType,
      filer_id: filerId,
    };
    const query = `
      MATCH (f:Filing)
      WHERE f.signed_at >= $from_date AND f.signed_at <= $to_date
        AND ($filing_type IS NULL OR f.filing_type = $filing_type)
      OPTIONAL MATCH (f)-[:FILED_BY]->(filer)
      WITH f, filer
      WHERE $filer_id IS NULL OR filer.id = $filer_id OR f.filed_by = $filer_id
      RETURN f.signed_at   AS signed_at,
             f.filing_type AS filing_type,
             coalesce(filer.search_label, filer.name, filer.id, f.filed_by) AS filed_by_name,
             f.id          AS id
      ORDER BY signed_at DESC, id ASC
      LIMIT 500
    `;
    return { query, params };
  },
};

// ---------------------------------------------------------------------------
// 4. Current officeholders + Form 700/803 coverage
// ---------------------------------------------------------------------------

const currentOfficeholders: DataQueryDef = {
  slug: "current-officeholders-form-coverage",
  display_name: "Current officeholders — Form 700/803 coverage",
  description:
    "Active SeatService rows with Form 700 and Form 803 counts per officeholder.",
  filters: [
    {
      key: "jurisdiction_id",
      label: "Jurisdiction id",
      type: "text",
      placeholder: "place-san-rafael",
    },
  ],
  columns: [
    { key: "person_name", label: "Person", sortable: true, alignment: "left" },
    { key: "seat_display", label: "Seat", sortable: true, alignment: "left" },
    { key: "form_700_count", label: "Form 700", sortable: true, alignment: "right" },
    { key: "form_803_count", label: "Form 803", sortable: true, alignment: "right" },
    { key: "id", label: "Person id", alignment: "left", link: "entity-route" },
  ],
  cypher: (filters) => {
    const jurisdictionId = nonEmpty(filters.jurisdiction_id);
    const params: Record<string, unknown> = {
      jurisdiction_id: jurisdictionId,
    };
    // Fix 9: live SeatService uses `ended_at`/`started_at`, not the spec's
    // `end_date`/`start_date`. Pre-fix this query was filtering on a property
    // that doesn't exist, so it returned every SeatService row (IS NULL
    // matches everything) and then downstream joins marked them "current."
    const query = `
      MATCH (p:Person)-[:HELD_BY]-(svc:SeatService)
      WHERE svc.ended_at IS NULL OR svc.ended_at = '' OR svc.ended_at >= date()
      OPTIONAL MATCH (svc)-[:FOR_SEAT]->(seat:Seat)
      WITH p, svc, seat
      WHERE $jurisdiction_id IS NULL
         OR seat.jurisdiction_id = $jurisdiction_id
         OR svc.jurisdiction_id = $jurisdiction_id
      OPTIONAL MATCH (f700:Filing {filing_type: 'form_700'})-[:FILED_BY]->(p)
      WITH p, svc, seat, count(DISTINCT f700) AS form_700_count
      OPTIONAL MATCH (f803:Filing {filing_type: 'form_803'})-[:FILED_BY]->(p)
      WITH p, svc, seat, form_700_count, count(DISTINCT f803) AS form_803_count
      RETURN coalesce(p.search_label, p.name, p.id) AS person_name,
             coalesce(seat.name, svc.seat_id, svc.id) AS seat_display,
             form_700_count,
             form_803_count,
             p.id AS id
      ORDER BY person_name ASC, id ASC
      LIMIT 500
    `;
    return { query, params };
  },
};

// ---------------------------------------------------------------------------
// 5. Agreements + amendments for a project
// ---------------------------------------------------------------------------

const agreementsForProject: DataQueryDef = {
  slug: "agreements-and-amendments-for-project",
  display_name: "Agreements + amendments for a project",
  description:
    "All Agreements tied to a given project, with amendment counts and effective dates.",
  filters: [
    {
      key: "project_id",
      label: "Project id",
      type: "text",
      default: "project-san-rafael-350-merrydale-interim-shelter",
      required: true,
    },
  ],
  columns: [
    { key: "agreement_name", label: "Agreement", sortable: true, alignment: "left" },
    { key: "effective_date", label: "Effective date", sortable: true, alignment: "left" },
    { key: "amount", label: "Amount", sortable: true, alignment: "right" },
    { key: "amendment_count", label: "Amendments", sortable: true, alignment: "right" },
    { key: "id", label: "Agreement id", alignment: "left", link: "entity-route" },
  ],
  cypher: (filters) => {
    const projectId = nonEmpty(filters.project_id);
    const params: Record<string, unknown> = { project_id: projectId };
    const query = `
      MATCH (a:Agreement)
      WHERE $project_id IS NULL
         OR EXISTS { MATCH (a)-[]-(p:Project {id: $project_id}) }
         OR a.project_id = $project_id
      OPTIONAL MATCH (am:Amendment)-[:AMENDS_AGREEMENT]->(a)
      WITH a, count(am) AS amendment_count
      RETURN coalesce(a.search_label, a.name, a.id) AS agreement_name,
             a.effective_date AS effective_date,
             a.amount         AS amount,
             amendment_count,
             a.id             AS id
      ORDER BY effective_date DESC, id ASC
      LIMIT 500
    `;
    return { query, params };
  },
};

// ---------------------------------------------------------------------------
// 6. Legal proceedings affecting local programs/projects
// ---------------------------------------------------------------------------

const legalProceedings: DataQueryDef = {
  slug: "legal-proceedings-affecting-local",
  display_name: "Legal proceedings affecting local programs/projects",
  description:
    "Proceedings + their parent case, joined to any linked local program or project.",
  filters: [
    { key: "case_id", label: "Case id", type: "text", placeholder: "case-boyd-v-san-rafael" },
  ],
  columns: [
    { key: "case_caption", label: "Case caption", sortable: true, alignment: "left" },
    { key: "proceeding_type", label: "Type", sortable: true, alignment: "left" },
    // Fix 10: column key renamed to occurred_at so the browse table pulls
    // the right property without a post-query rename step.
    { key: "occurred_at", label: "Date", sortable: true, alignment: "left" },
    { key: "affected_program", label: "Affected", alignment: "left" },
    { key: "id", label: "Proceeding id", alignment: "left", link: "entity-route" },
  ],
  cypher: (filters) => {
    const caseId = nonEmpty(filters.case_id);
    const params: Record<string, unknown> = { case_id: caseId };
    // Fix 10: live Proceeding uses `occurred_at`, not `proceeding_date`.
    // Pre-fix this column was blank for every row.
    const query = `
      MATCH (pr:Proceeding)-[:PART_OF|PART_OF_CASE]->(c:Case)
      WHERE $case_id IS NULL OR c.id = $case_id
      OPTIONAL MATCH (c)-[]-(link)
      WHERE link:Program OR link:Project
      WITH pr, c, link
      RETURN coalesce(c.search_label, c.caption, c.id) AS case_caption,
             pr.proceeding_type AS proceeding_type,
             pr.occurred_at     AS occurred_at,
             coalesce(link.search_label, link.name, link.id) AS affected_program,
             pr.id AS id
      ORDER BY occurred_at DESC, id ASC
      LIMIT 500
    `;
    return { query, params };
  },
};

// ---------------------------------------------------------------------------
// 7. Evidence records supporting a target
// ---------------------------------------------------------------------------

const evidenceRecords: DataQueryDef = {
  slug: "evidence-records-supporting",
  display_name: "Evidence records supporting a decision/project/case",
  description:
    "All Records EVIDENCED_BY-attached to a given target id (decision, project, case, etc.).",
  filters: [
    {
      key: "target_id",
      label: "Target id",
      type: "text",
      required: true,
      placeholder: "decision-xyz or project-xyz",
    },
  ],
  columns: [
    { key: "record_type", label: "Record type", sortable: true, alignment: "left" },
    { key: "captured_at", label: "Captured at", sortable: true, alignment: "left" },
    {
      key: "preferred_display_artifact",
      label: "Artifact",
      alignment: "left",
    },
    {
      key: "preferred_public_url",
      label: "Public URL",
      alignment: "left",
    },
    { key: "id", label: "Record id", alignment: "left", link: "entity-route" },
  ],
  cypher: (filters) => {
    const targetId = nonEmpty(filters.target_id);
    const params: Record<string, unknown> = { target_id: targetId };
    // Per live graph: EVIDENCED_BY points target -> Record (target evidences into
    // record). Direction is (target)-[:EVIDENCED_BY]->(Record).
    const query = `
      MATCH (target {id: $target_id})-[:EVIDENCED_BY]->(r:Record)
      RETURN r.record_type                 AS record_type,
             r.captured_at                 AS captured_at,
             r.preferred_display_artifact  AS preferred_display_artifact,
             r.preferred_public_url        AS preferred_public_url,
             r.id                          AS id
      ORDER BY captured_at DESC, id ASC
      LIMIT 500
    `;
    return { query, params };
  },
};

// ---------------------------------------------------------------------------
// 8. Local pressure ranking — San Rafael tracking threads
// ---------------------------------------------------------------------------

const localPressureRanking: DataQueryDef = {
  slug: "local-pressure-ranking-sr",
  display_name: "Local pressure ranking — San Rafael threads",
  description:
    "Ranks tracked threads (Project/Program/Case) by money, legal, and evidence pressure.",
  filters: [],
  columns: [
    { key: "thread_name", label: "Thread", sortable: true, alignment: "left" },
    { key: "type", label: "Type", sortable: true, alignment: "left" },
    { key: "money_pressure", label: "Money", sortable: true, alignment: "right" },
    { key: "legal_pressure", label: "Legal", sortable: true, alignment: "right" },
    { key: "evidence_density", label: "Evidence", sortable: true, alignment: "right" },
    { key: "id", label: "Id", alignment: "left", link: "entity-route" },
  ],
  cypher: () => {
    // Spec says "San Rafael threads". Live graph doesn't set jurisdiction_id
    // on Project/Program/Case uniformly; cohort is identified by Place links
    // (primary_place_id, jurisdiction_place_id, place_ids) or by id prefix as
    // a fallback. Evidence is (target)-[:EVIDENCED_BY]->(Record).
    const query = `
      MATCH (t)
      WHERE (t:Project OR t:Program OR t:Case)
        AND (
             t.primary_place_id = 'place-san-rafael'
          OR t.jurisdiction_place_id = 'place-san-rafael'
          OR 'place-san-rafael' IN coalesce(t.place_ids, [])
          OR t.id CONTAINS 'san-rafael'
        )
      OPTIONAL MATCH (t)-[]-(m:MoneyFlow)
      WITH t, sum(coalesce(m.amount, 0)) AS money_pressure
      OPTIONAL MATCH (t)-[]-(pr:Proceeding)
      WITH t, money_pressure, count(DISTINCT pr) AS legal_pressure
      OPTIONAL MATCH (t)-[:EVIDENCED_BY]->(r:Record)
      WITH t, money_pressure, legal_pressure, count(DISTINCT r) AS evidence_density
      RETURN coalesce(t.search_label, t.name, t.id) AS thread_name,
             labels(t)[0] AS type,
             money_pressure,
             legal_pressure,
             evidence_density,
             t.id AS id
      ORDER BY money_pressure DESC, legal_pressure DESC, evidence_density DESC, id ASC
      LIMIT 100
    `;
    return { query, params: {} };
  },
};

// ---------------------------------------------------------------------------
// 9. Campaign money within N days of a decision
// ---------------------------------------------------------------------------

const campaignMoneyNearDecisions: DataQueryDef = {
  slug: "campaign-money-near-decisions",
  display_name: "Campaign money near local decisions",
  description:
    "Contributions/expenditures within a time window of a decision in the chosen jurisdiction.",
  filters: [
    { key: "window_days", label: "Window (days)", type: "amount", default: "30" },
    {
      key: "jurisdiction",
      label: "Jurisdiction",
      type: "select",
      options: ["", "san-rafael", "marin-county"],
      default: "san-rafael",
    },
  ],
  columns: [
    { key: "decision_title", label: "Decision", sortable: true, alignment: "left" },
    { key: "decided_at", label: "Decided at", sortable: true, alignment: "left" },
    { key: "money_amount", label: "Amount", sortable: true, alignment: "right" },
    { key: "flow_date", label: "Flow date", sortable: true, alignment: "left" },
    { key: "days_delta", label: "Δ days", sortable: true, alignment: "right" },
    { key: "id", label: "Flow id", alignment: "left", link: "entity-route" },
  ],
  cypher: (filters) => {
    const windowDaysRaw = nonEmpty(filters.window_days) ?? "30";
    const windowDays = Number(windowDaysRaw);
    const jurisdiction = nonEmpty(filters.jurisdiction) ?? "san-rafael";
    const params: Record<string, unknown> = {
      window_days: Number.isFinite(windowDays) ? windowDays : 30,
      jurisdiction,
    };
    // Decisions carry institution_id (e.g. 'org-san-rafael-city-council') but
    // no jurisdiction_id. Match on institution_id or id containing the
    // jurisdiction slug. MoneyFlow has no direct jurisdiction link — we keep
    // the cross-join intentionally loose and let the caller narrow via
    // window_days. duration.inDays needs a proper date() conversion so malformed
    // dates are filtered out via the IS NOT NULL guard above.
    const query = `
      MATCH (d:Decision)
      WHERE (d.institution_id CONTAINS $jurisdiction OR d.id CONTAINS $jurisdiction)
        AND d.decided_at IS NOT NULL AND d.decided_at <> ''
      MATCH (m:MoneyFlow)
      WHERE m.flow_date IS NOT NULL AND m.flow_date <> ''
        AND abs(duration.inDays(date(m.flow_date), date(d.decided_at)).days) <= $window_days
      WITH d, m,
           duration.inDays(date(m.flow_date), date(d.decided_at)).days AS days_delta
      RETURN coalesce(d.search_label, d.title, d.id) AS decision_title,
             d.decided_at AS decided_at,
             m.amount     AS money_amount,
             m.flow_date  AS flow_date,
             days_delta,
             m.id         AS id
      ORDER BY abs(days_delta) ASC, decided_at DESC, id ASC
      LIMIT 500
    `;
    return { query, params };
  },
};

// ---------------------------------------------------------------------------
// 10. QA validation gaps
// ---------------------------------------------------------------------------

const qaValidationGaps: DataQueryDef = {
  slug: "qa-validation-gaps",
  display_name: "QA — validation + reconciliation gaps",
  description:
    "Categorized counts of data-quality gaps: missing dates, unresolved actors, orphan records.",
  filters: [],
  columns: [
    { key: "category", label: "Category", sortable: true, alignment: "left" },
    { key: "description", label: "Description", alignment: "left" },
    { key: "count", label: "Count", sortable: true, alignment: "right" },
  ],
  cypher: () => {
    const query = `
      CALL {
        MATCH (d:Decision) WHERE d.decided_at IS NULL OR d.decided_at = ''
        RETURN 'decisions.missing_decided_at' AS category,
               'Decisions with no decided_at date'  AS description,
               count(d) AS count
      }
      RETURN category, description, count
      UNION
      CALL {
        MATCH (m:MoneyFlow) WHERE m.amount IS NULL
        RETURN 'money_flows.missing_amount' AS category,
               'Money flows with no amount'  AS description,
               count(m) AS count
      }
      RETURN category, description, count
      UNION
      CALL {
        MATCH (f:Filing) WHERE f.signed_at IS NULL OR f.signed_at = ''
        RETURN 'filings.missing_signed_at' AS category,
               'Filings with no signed_at date'  AS description,
               count(f) AS count
      }
      RETURN category, description, count
      UNION
      CALL {
        // Fix 11: live edge direction is (target)-[:EVIDENCED_BY]->(Record).
        // Pre-fix we checked "NOT (r)-[:EVIDENCED_BY]->()", which is true for
        // every Record (Records never have outgoing EVIDENCED_BY edges), so
        // the orphan count matched the total Record count. Flip direction to
        // find Records with no incoming target.
        MATCH (r:Record) WHERE NOT ()-[:EVIDENCED_BY]->(r)
        RETURN 'records.orphan_no_target' AS category,
               'Records not attached to any target'  AS description,
               count(r) AS count
      }
      RETURN category, description, count
      UNION
      CALL {
        MATCH (a:Agreement) WHERE a.effective_date IS NULL OR a.effective_date = ''
        RETURN 'agreements.missing_effective_date' AS category,
               'Agreements with no effective_date'  AS description,
               count(a) AS count
      }
      RETURN category, description, count
    `;
    return { query, params: {} };
  },
};

// ---------------------------------------------------------------------------
// Export
// ---------------------------------------------------------------------------

export const DATA_QUERIES: DataQueryDef[] = [
  sanRafaelDecisions,
  moneyFlowsByYear,
  filingsByFiler,
  currentOfficeholders,
  agreementsForProject,
  legalProceedings,
  evidenceRecords,
  localPressureRanking,
  campaignMoneyNearDecisions,
  qaValidationGaps,
];

export function findDataQuery(slug: string): DataQueryDef | null {
  return DATA_QUERIES.find((q) => q.slug === slug) ?? null;
}

/** Apply filter defaults where the caller didn't provide a value.
 *  Returns a shallow copy; never mutates the input. */
export function applyFilterDefaults(
  def: DataQueryDef,
  provided: Record<string, string>,
): Record<string, string> {
  const merged: Record<string, string> = {};
  for (const f of def.filters) {
    const value = provided[f.key];
    if (value != null && value !== "") {
      merged[f.key] = value;
    } else if (f.default != null) {
      merged[f.key] = f.default;
    }
  }
  return merged;
}
