// app/src/lib/server/campaign-freshness.ts
//
// How fresh the campaign data in this artifact is, as the bake published it (meta campaign_freshness,
// scripts/cf_freshness.py) from the exact bundle the artifact holds. Never derived here: an artifact baked
// without it, or with a value that does not parse, has none, and the surfaces say so.
import "server-only";

import { getSubstrateDb } from "@/lib/server/substrate";

export type SourceFreshness = {
  source_id: string;
  name: string;
  jurisdiction_id: string;
  latest_report_date: string | null;
  exports: { year: string; export_date: string }[];
  unavailable_years: string[];
  held_years: string[];
};

export type CampaignFreshness = { bundle_id: string; sources: SourceFreshness[] };

const DATE = /^\d{4}-\d{2}-\d{2}$/;
const YEAR = /^\d{4}$/;

const isText = (v: unknown): v is string => typeof v === "string" && v.length > 0;
const isYears = (v: unknown): v is string[] => Array.isArray(v) && v.every((y) => typeof y === "string" && YEAR.test(y));

function isSource(v: unknown): v is SourceFreshness {
  if (typeof v !== "object" || v === null) return false;
  const s = v as Record<string, unknown>;
  return (
    isText(s.source_id) &&
    isText(s.name) &&
    isText(s.jurisdiction_id) &&
    (s.latest_report_date === null || (typeof s.latest_report_date === "string" && DATE.test(s.latest_report_date))) &&
    Array.isArray(s.exports) &&
    s.exports.every(
      (e) =>
        typeof e === "object" && e !== null &&
        typeof e.year === "string" && YEAR.test(e.year) &&
        typeof e.export_date === "string" && DATE.test(e.export_date),
    ) &&
    isYears(s.unavailable_years) &&
    isYears(s.held_years)
  );
}

export function loadCampaignFreshness(): CampaignFreshness | null {
  const row = getSubstrateDb().prepare("SELECT value FROM meta WHERE key = 'campaign_freshness'").get() as
    | { value: string }
    | undefined;
  if (!row) return null;
  try {
    const parsed: unknown = JSON.parse(row.value);
    const value = parsed as Record<string, unknown>;
    if (typeof parsed === "object" && parsed !== null && isText(value.bundle_id) &&
        Array.isArray(value.sources) && value.sources.every(isSource)) {
      return { bundle_id: value.bundle_id, sources: value.sources };
    }
  } catch {
    // fall through: a value that does not parse is no freshness at all
  }
  console.warn("[campaign-freshness] meta campaign_freshness is malformed; showing none");
  return null;
}

/** A page's freshness and the jurisdictions it applies to; on any substrate trouble, none (the page renders). */
export function campaignFreshnessFor(nodeId: string): { freshness: CampaignFreshness | null; jurisdictions: string[] } {
  try {
    return { freshness: loadCampaignFreshness(), jurisdictions: campaignJurisdictions(nodeId) };
  } catch (err) {
    console.warn(`[campaign-freshness] lookup failed for ${nodeId}:`, err);
    return { freshness: null, jurisdictions: [] };
  }
}

/**
 * The jurisdictions whose NetFile source a page's campaign data comes from: a committee's own, or, for a
 * NetFile contribution or expenditure, its committee's. San Rafael OCR flows and contracts have none.
 */
export function campaignJurisdictions(nodeId: string): string[] {
  const rows = getSubstrateDb()
    .prepare(
      `SELECT DISTINCT j.target AS jurisdiction
         FROM nodes n
         JOIN edges j ON j.rel = 'IN_JURISDICTION' AND j.source IN (
           SELECT n.id WHERE n.type = 'Committee'
           UNION SELECT e.target FROM edges e WHERE e.source = n.id AND e.rel = 'TO_TARGET'
           UNION SELECT e.source FROM edges e WHERE e.target = n.id AND e.rel = 'FROM_SOURCE'
         )
         JOIN nodes c ON c.id = j.source AND c.type = 'Committee'
        WHERE n.id = ?
          AND (n.type = 'Committee'
               OR (n.type = 'MoneyFlow'
                   AND json_extract(n.props, '$.flow_type') IN ('contribution', 'expenditure')))
        ORDER BY j.target`,
    )
    .all(nodeId) as { jurisdiction: string }[];
  return rows.map((r) => r.jurisdiction);
}
