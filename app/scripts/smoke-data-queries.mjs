#!/usr/bin/env node
// Smoke-test the 10 predefined data queries against the live AuraDB.
// Run: NEO4J_URI=... NEO4J_USER=... NEO4J_PASSWORD=... node scripts/smoke-data-queries.mjs
//
// Not part of the build/test pipeline — ad-hoc diagnostic.

import neo4j from "neo4j-driver";

// Inline copies of the 10 queries (small duplicate so we don't pull in
// the TS source-only module). Keep synchronized with src/lib/server/data-queries.ts.

function today() {
  return new Date().toISOString().slice(0, 10);
}

const QUERIES = [
  {
    slug: "san-rafael-decisions-since-2019",
    params: { from_date: "2024-01-01", to_date: "2024-12-31", institution_id: null },
    cypher: `
      MATCH (d:Decision)
      WHERE d.decided_at >= $from_date AND d.decided_at <= $to_date
        AND ($institution_id IS NULL OR d.institution_id = $institution_id)
      OPTIONAL MATCH (inst:Organization {id: d.institution_id})
      RETURN d.decided_at AS decided_at,
             coalesce(d.search_label, d.subject, d.id) AS title,
             coalesce(inst.name, d.institution_id) AS institution_name,
             d.id AS id
      ORDER BY decided_at DESC, id ASC
      LIMIT 5
    `,
  },
  {
    slug: "money-flows-by-year",
    params: { min_amount: 10000, year_prefix: "2024-", flow_type: null },
    cypher: `
      MATCH (m:MoneyFlow)
      WHERE coalesce(m.amount, 0) >= $min_amount
        AND ($year_prefix IS NULL OR m.flow_date STARTS WITH $year_prefix)
        AND ($flow_type IS NULL OR m.flow_type = $flow_type)
      OPTIONAL MATCH (m)-[:FROM_SOURCE]->(src)
      OPTIONAL MATCH (m)-[:TO_TARGET]->(tgt)
      RETURN m.flow_date AS flow_date,
             m.amount AS amount,
             m.flow_type AS flow_type,
             coalesce(src.search_label, src.name, src.id) AS source_name,
             coalesce(tgt.search_label, tgt.name, tgt.id) AS target_name,
             m.id AS id
      ORDER BY flow_date DESC, id ASC
      LIMIT 5
    `,
  },
  {
    slug: "filings-by-person-or-committee",
    params: { from_date: "2020-01-01", to_date: today(), filing_type: null, filer_id: null },
    cypher: `
      MATCH (f:Filing)
      WHERE f.signed_at >= $from_date AND f.signed_at <= $to_date
        AND ($filing_type IS NULL OR f.filing_type = $filing_type)
      OPTIONAL MATCH (f)-[:FILED_BY]->(filer)
      WITH f, filer
      WHERE $filer_id IS NULL OR filer.id = $filer_id OR f.filed_by = $filer_id
      RETURN f.signed_at AS signed_at,
             f.filing_type AS filing_type,
             coalesce(filer.search_label, filer.name, filer.id, f.filed_by) AS filed_by_name,
             f.id AS id
      ORDER BY signed_at DESC, id ASC
      LIMIT 5
    `,
  },
  {
    slug: "current-officeholders-form-coverage",
    params: { jurisdiction_id: null },
    cypher: `
      MATCH (p:Person)-[:HELD_BY]-(svc:SeatService)
      WHERE svc.end_date IS NULL OR svc.end_date = '' OR svc.end_date >= date()
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
      LIMIT 5
    `,
  },
  {
    slug: "agreements-and-amendments-for-project",
    params: { project_id: "project-san-rafael-350-merrydale-interim-shelter" },
    cypher: `
      MATCH (a:Agreement)
      WHERE $project_id IS NULL
         OR EXISTS { MATCH (a)-[]-(p:Project {id: $project_id}) }
         OR a.project_id = $project_id
      OPTIONAL MATCH (am:Amendment)-[:AMENDS_AGREEMENT]->(a)
      WITH a, count(am) AS amendment_count
      RETURN coalesce(a.search_label, a.name, a.id) AS agreement_name,
             a.effective_date AS effective_date,
             a.amount AS amount,
             amendment_count,
             a.id AS id
      ORDER BY effective_date DESC, id ASC
      LIMIT 5
    `,
  },
  {
    slug: "legal-proceedings-affecting-local",
    params: { case_id: null },
    cypher: `
      MATCH (pr:Proceeding)-[:PART_OF|PART_OF_CASE]->(c:Case)
      WHERE $case_id IS NULL OR c.id = $case_id
      OPTIONAL MATCH (c)-[]-(link)
      WHERE link:Program OR link:Project
      WITH pr, c, link
      RETURN coalesce(c.search_label, c.caption, c.id) AS case_caption,
             pr.proceeding_type AS proceeding_type,
             pr.proceeding_date AS proceeding_date,
             coalesce(link.search_label, link.name, link.id) AS affected_program,
             pr.id AS id
      ORDER BY proceeding_date DESC, id ASC
      LIMIT 5
    `,
  },
  {
    slug: "evidence-records-supporting",
    params: { target_id: "project-san-rafael-350-merrydale-interim-shelter" },
    cypher: `
      MATCH (target {id: $target_id})-[:EVIDENCED_BY]->(r:Record)
      RETURN r.record_type AS record_type,
             r.captured_at AS captured_at,
             r.preferred_display_artifact AS preferred_display_artifact,
             r.preferred_public_url AS preferred_public_url,
             r.id AS id
      ORDER BY captured_at DESC, id ASC
      LIMIT 5
    `,
  },
  {
    slug: "local-pressure-ranking-sr",
    params: {},
    cypher: `
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
      LIMIT 5
    `,
  },
  {
    slug: "campaign-money-near-decisions",
    params: { window_days: 30, jurisdiction: "san-rafael" },
    cypher: `
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
             m.amount AS money_amount,
             m.flow_date AS flow_date,
             days_delta,
             m.id AS id
      ORDER BY abs(days_delta) ASC, decided_at DESC, id ASC
      LIMIT 5
    `,
  },
  {
    slug: "qa-validation-gaps",
    params: {},
    cypher: `
      CALL {
        MATCH (d:Decision) WHERE d.decided_at IS NULL OR d.decided_at = ''
        RETURN 'decisions.missing_decided_at' AS category,
               'Decisions with no decided_at date' AS description,
               count(d) AS count
      }
      RETURN category, description, count
      UNION
      CALL {
        MATCH (m:MoneyFlow) WHERE m.amount IS NULL
        RETURN 'money_flows.missing_amount' AS category,
               'Money flows with no amount' AS description,
               count(m) AS count
      }
      RETURN category, description, count
      UNION
      CALL {
        MATCH (f:Filing) WHERE f.signed_at IS NULL OR f.signed_at = ''
        RETURN 'filings.missing_signed_at' AS category,
               'Filings with no signed_at date' AS description,
               count(f) AS count
      }
      RETURN category, description, count
      UNION
      CALL {
        MATCH (r:Record) WHERE NOT (r)-[:EVIDENCED_BY]->()
        RETURN 'records.orphan_no_target' AS category,
               'Records not attached to any target' AS description,
               count(r) AS count
      }
      RETURN category, description, count
      UNION
      CALL {
        MATCH (a:Agreement) WHERE a.effective_date IS NULL OR a.effective_date = ''
        RETURN 'agreements.missing_effective_date' AS category,
               'Agreements with no effective_date' AS description,
               count(a) AS count
      }
      RETURN category, description, count
    `,
  },
];

function toJs(v) {
  if (v == null) return null;
  if (typeof v === "object" && "toNumber" in v) {
    try { return v.toNumber(); } catch { return Number(v); }
  }
  return v;
}

async function main() {
  const driver = neo4j.driver(
    process.env.NEO4J_URI,
    neo4j.auth.basic(process.env.NEO4J_USER, process.env.NEO4J_PASSWORD),
  );
  for (const q of QUERIES) {
    const session = driver.session({ database: process.env.NEO4J_DATABASE || "neo4j" });
    try {
      const res = await session.run(q.cypher, q.params);
      const rows = res.records.map((r) => {
        const row = {};
        for (const k of r.keys) row[k] = toJs(r.get(k));
        return row;
      });
      console.log(`\n[${q.slug}] rows=${rows.length}`);
      if (rows[0]) console.log("  first:", JSON.stringify(rows[0]).slice(0, 240));
    } catch (err) {
      console.log(`\n[${q.slug}] ERROR: ${err.message}`);
    } finally {
      await session.close();
    }
  }
  await driver.close();
}

main().catch((e) => { console.error(e); process.exit(1); });
