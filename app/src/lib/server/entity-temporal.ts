// Per-type effective event date projection per spec §5.4.
//
// Durable entities (Person / Organization / Committee / Project / Program /
// Place / Issue / Seat) intentionally return null — these are always visible
// regardless of a time slider, and do not earn a mark on the ribbon.
//
// Range-valued types (Case, SeatService) return the range start only; the
// full range treatment (§5.4) is deferred to Plan 3 — Batch F's timeline is
// a single-point-per-event read-only ribbon.

import "server-only";
import type { NodeType } from "@/lib/type-display";

export function effectiveEventDate(
  type: NodeType,
  props: Record<string, unknown>,
): string | null {
  const s = (v: unknown): string | null =>
    typeof v === "string" && v.length > 0 ? v : null;

  switch (type) {
    case "Meeting":
      return s(props.meeting_date);
    case "Decision":
      return s(props.decided_at);
    case "MoneyFlow":
      return s(props.flow_date);
    case "Filing":
      return s(props.signed_at);
    case "Election":
      return s(props.election_date);
    case "Proceeding":
      // Live graph uses `occurred_at` (per Codex round-1 fix 10). Fall back
      // to `proceeding_date` / `date` to keep older callers / test fixtures
      // working.
      return s(props.occurred_at) ?? s(props.proceeding_date) ?? s(props.date);
    case "Agreement":
    case "Amendment":
      return s(props.effective_date);
    case "Case":
      // Range treatment (filed_at → closed_at) deferred to Plan 3.
      return s(props.filed_at);
    case "AgendaItem":
      // Parent meeting date — may be null until ingestion wires it through.
      return s(props.parent_meeting_date) ?? s(props.meeting_date);
    case "Record":
      return s(props.published_at) ?? s(props.captured_at);
    case "Candidacy":
      // Spec §5.4 says "via linked Election.election_date"; we don't have
      // that join on the neighbor shape today, so return null.
      return null;
    case "SeatService":
      return s(props.started_at) ?? s(props.start_date);
    case "Membership":
      // Range treatment (started_at → ended_at) deferred, same as SeatService.
      return s(props.started_at);
    // Durable types — always visible, no ribbon mark.
    case "Person":
    case "Organization":
    case "Committee":
    case "Project":
    case "Program":
    case "Place":
    case "Issue":
    case "Seat":
      return null;
    default: {
      const _exhaustive: never = type;
      void _exhaustive;
      return null;
    }
  }
}
