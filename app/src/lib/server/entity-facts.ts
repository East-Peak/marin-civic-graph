// Per-type fact-field definitions for the entity-page facts panel.
// Spec §7.1 item 6 (Tier 1) + §7.2 (Tier 2). Extracted as a pure module so
// tests can exercise per-type rows without rendering React.
//
// Also hosts heroStatsForEntity (Tier 1 big-numeral strip, spec §7.1 item 4).

import type { NodeType } from "@/lib/type-display";

export type FactRow = { key: string; value: string | null };
export type HeroStat = { label: string; value: string };

function s(v: unknown): string | null {
  if (typeof v === "string") return v.length > 0 ? v : null;
  if (typeof v === "number") return Number.isFinite(v) ? String(v) : null;
  if (typeof v === "boolean") return v ? "true" : "false";
  return null;
}

function asList(v: unknown): string | null {
  return Array.isArray(v) && v.length > 0 ? v.join(", ") : null;
}

function period(start: unknown, end: unknown): string | null {
  const a = s(start);
  const b = s(end);
  if (a && b) return `${a} – ${b}`;
  return a ?? b;
}

/**
 * Return the ordered list of scalar fact rows to display in the right-rail
 * facts panel for the given entity. The final row is always the canonical
 * entity id so Stuart can copy it for citation.
 */
export function factsForEntity(
  type: NodeType,
  props: Record<string, unknown>,
): FactRow[] {
  const rows: FactRow[] = (() => {
    switch (type) {
      case "Person":
        return [
          { key: "Name", value: s(props.name) },
          { key: "Current seat", value: s(props.current_seat_display) },
          { key: "Jurisdiction", value: s(props.jurisdiction_name) },
          { key: "Aliases", value: asList(props.aliases) },
        ];
      case "Decision":
        return [
          { key: "Decided", value: s(props.decided_at) },
          { key: "Institution", value: s(props.institution_name) },
          { key: "Vote", value: s(props.vote_summary) },
          { key: "Status", value: s(props.status) },
        ];
      case "Project":
        return [
          { key: "Name", value: s(props.name) },
          { key: "Status", value: s(props.status) },
          { key: "Address", value: s(props.address) },
          { key: "Jurisdiction", value: s(props.jurisdiction_name) },
        ];
      case "Program":
        return [
          { key: "Name", value: s(props.name) },
          { key: "Status", value: s(props.status) },
          { key: "Type", value: s(props.program_type) },
          { key: "Jurisdiction", value: s(props.jurisdiction_name) },
        ];
      case "Case":
        return [
          { key: "Caption", value: s(props.caption) ?? s(props.name) },
          { key: "Docket", value: s(props.docket_number) },
          { key: "Filed", value: s(props.filed_at) },
          { key: "Closed", value: s(props.closed_at) },
          { key: "Status", value: s(props.status) },
        ];
      case "Meeting":
        return [
          { key: "Title", value: s(props.title) },
          { key: "Date", value: s(props.meeting_date) },
          { key: "Institution", value: s(props.institution_name) },
          { key: "Type", value: s(props.meeting_type) },
        ];
      case "Filing":
        return [
          { key: "Type", value: s(props.filing_type) },
          { key: "Signed", value: s(props.signed_at) },
          { key: "Period", value: period(props.period_start, props.period_end) },
          { key: "Filer", value: s(props.filed_by_name) ?? s(props.filer_name) },
        ];
      case "Committee":
        return [
          { key: "Name", value: s(props.name) },
          { key: "FPPC ID", value: s(props.fppc_id) },
          { key: "Treasurer", value: s(props.treasurer) },
          { key: "Candidate", value: s(props.candidate_name) },
        ];
      case "Organization":
        return [
          { key: "Name", value: s(props.name) },
          { key: "Subtype", value: s(props.subtype) ?? asList(props.labels) },
          { key: "Jurisdiction", value: s(props.jurisdiction_name) },
          { key: "Website", value: s(props.website) },
        ];
      case "MoneyFlow":
        return [
          { key: "Amount", value: s(props.amount) },
          { key: "Date", value: s(props.flow_date) },
          { key: "Type", value: s(props.flow_type) },
          { key: "Schedule", value: s(props.source_schedule) },
        ];
      case "Seat":
        return [
          { key: "Title", value: s(props.title) ?? s(props.name) },
          { key: "Institution", value: s(props.institution_name) },
          { key: "Jurisdiction", value: s(props.jurisdiction_name) },
        ];
      case "SeatService":
        return [
          { key: "Seat", value: s(props.seat_title) },
          { key: "Person", value: s(props.person_name) },
          { key: "Start", value: s(props.start_date) },
          { key: "End", value: s(props.end_date) },
        ];
      case "Election":
        return [
          { key: "Title", value: s(props.name) ?? s(props.title) },
          { key: "Date", value: s(props.election_date) },
          { key: "Type", value: s(props.election_type) },
          { key: "Jurisdiction", value: s(props.jurisdiction_name) },
        ];
      case "Candidacy":
        return [
          { key: "Candidate", value: s(props.person_name) ?? s(props.name) },
          { key: "Seat", value: s(props.seat_title) },
          { key: "Election", value: s(props.election_name) },
          { key: "Outcome", value: s(props.outcome) },
        ];
      case "AgendaItem":
        return [
          { key: "Heading", value: s(props.heading) ?? s(props.title) },
          { key: "Meeting", value: s(props.meeting_title) },
          { key: "Date", value: s(props.meeting_date) },
          { key: "Item", value: s(props.item_number) },
        ];
      case "Proceeding":
        return [
          { key: "Title", value: s(props.title) ?? s(props.name) },
          { key: "Date", value: s(props.proceeding_date) ?? s(props.date) },
          { key: "Case", value: s(props.case_caption) },
          { key: "Type", value: s(props.proceeding_type) },
        ];
      case "Agreement":
        return [
          { key: "Title", value: s(props.title) ?? s(props.name) },
          { key: "Type", value: s(props.agreement_type) },
          { key: "Effective", value: s(props.effective_date) },
          { key: "Parties", value: asList(props.parties) },
        ];
      case "Amendment":
        return [
          { key: "Title", value: s(props.title) ?? s(props.name) },
          { key: "Parent", value: s(props.parent_title) ?? s(props.parent_id) },
          { key: "Effective", value: s(props.effective_date) },
        ];
      case "Record":
        return [
          { key: "Record type", value: s(props.record_type) },
          { key: "Captured", value: s(props.captured_at) },
          { key: "Artifact", value: s(props.preferred_display_artifact) },
          { key: "Public URL", value: s(props.preferred_public_url) },
        ];
      case "Place":
        return [
          { key: "Name", value: s(props.name) },
          { key: "Type", value: s(props.place_type) },
          { key: "Parent", value: s(props.parent_name) },
        ];
      case "Issue":
        return [
          { key: "Name", value: s(props.name) },
          { key: "Description", value: s(props.description) },
        ];
      default: {
        const _exhaustive: never = type;
        void _exhaustive;
        return [];
      }
    }
  })();

  // Every type gets the canonical id as the final row for citation.
  rows.push({ key: "ID", value: s(props.id) });
  return rows;
}

// ---------------------------------------------------------------------------
// Tier 1 hero stats (big-numeral strip, spec §7.1 item 4).
// ---------------------------------------------------------------------------

function formatMoney(v: unknown): string {
  const n =
    typeof v === "number"
      ? v
      : typeof v === "string"
        ? Number(v)
        : NaN;
  if (!Number.isFinite(n) || n === 0) return "—";
  return `$${Math.round(n).toLocaleString()}`;
}

function sv(v: unknown): string {
  if (v == null) return "—";
  if (typeof v === "string") return v.length > 0 ? v : "—";
  if (typeof v === "number") return Number.isFinite(v) ? String(v) : "—";
  return String(v);
}

/**
 * Return the ordered big-numeral stats to render in the Tier 1 hero strip.
 *
 * Tier 2 types return an empty array — hero-stats.tsx renders nothing in that
 * case so the layout collapses cleanly.
 *
 * Per spec §7.1 item 4 — each Tier 1 type has an authoritative stat list
 * with every field represented. Missing props em-dash ("—") gracefully;
 * the shape stays identical page-to-page so the layout doesn't reflow
 * as the graph is enriched.
 *
 * Several derived counts (`decisions_count`, `records_count`, `total_money`,
 * …) are not yet projected onto live AuraDB nodes — those will fall back to
 * "—" until the Plan 3 ingestion work lands. The em-dashed slots remain
 * structural placeholders so nothing moves when the counts arrive.
 */
export function heroStatsForEntity(
  type: NodeType,
  props: Record<string, unknown>,
): HeroStat[] {
  switch (type) {
    case "Project":
    case "Program":
      // Spec: total money, linked decisions, counterparties, evidence count.
      return [
        { label: "money", value: formatMoney(props.total_money) },
        { label: "decisions", value: sv(props.decisions_count) },
        { label: "counterparties", value: sv(props.counterparties_count) },
        { label: "evidence", value: sv(props.records_count ?? props.evidence_count) },
      ];
    case "Person":
      // Spec: current seat, SeatService window, filings count.
      return [
        { label: "current seat", value: sv(props.current_seat_display) },
        {
          label: "service",
          value: period(
            props.current_seat_started_at ?? props.service_start_date,
            props.current_seat_ended_at ?? props.service_end_date,
          ) ?? "—",
        },
        { label: "filings", value: sv(props.filings_count) },
      ];
    case "Decision":
      // Spec: decided-at date, vote summary, linked agenda item.
      return [
        { label: "decided", value: sv(props.decided_at) },
        { label: "vote", value: sv(props.vote_summary) },
        { label: "agenda item", value: sv(props.agenda_item_number ?? props.item_number) },
      ];
    case "Case":
      // Spec: filed-at, court, status, constrains count.
      return [
        { label: "filed", value: sv(props.filed_at) },
        { label: "court", value: sv(props.court_name ?? props.court) },
        { label: "status", value: sv(props.status) },
        { label: "constrains", value: sv(props.constrains_count) },
      ];
    case "Meeting":
      // Spec: date, institution, agenda-items count, decisions count.
      return [
        { label: "date", value: sv(props.meeting_date) },
        { label: "institution", value: sv(props.institution_name) },
        { label: "agenda items", value: sv(props.agenda_items_count) },
        { label: "decisions", value: sv(props.decisions_count) },
      ];
    case "Filing":
      // Spec: filing type, signed-at, period, actor.
      return [
        { label: "type", value: sv(props.filing_type) },
        { label: "signed", value: sv(props.signed_at) },
        { label: "period", value: period(props.period_start, props.period_end) ?? "—" },
        {
          label: "actor",
          value: sv(
            props.filed_by_name ?? props.filer_name ?? props.candidate_name,
          ),
        },
      ];
    case "Committee":
      // Spec: fppc_id, candidate, elections, money totals.
      return [
        { label: "fppc id", value: sv(props.fppc_id) },
        { label: "candidate", value: sv(props.candidate_name) },
        { label: "elections", value: sv(props.elections_count) },
        { label: "money in", value: formatMoney(props.total_money_in) },
      ];
    default:
      return [];
  }
}
