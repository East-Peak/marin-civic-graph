// Mirror of scripts/citations.py. Keep both in lockstep.

const ARRAY_FIELDS = ["evidence_record_ids", "record_ids"] as const;

const SINGLE_FIELDS = [
  "filing_id", "fppc_report_id", "form_700_line",
  "minutes_url", "agenda_url", "meeting_url",
  "docket_number", "permit_id",
  "source_filing_id", "fppc_id",
] as const;

const PAIR_REQUIRED: ReadonlyArray<readonly string[]> = [["source_url", "source_id"]];

function isSet(value: unknown): boolean {
  if (value == null) return false;
  if (typeof value === "string") return value.trim() !== "";
  if (Array.isArray(value)) return value.length > 0;
  return Boolean(value);
}

export function hasPrimarySourceCitation(node: Record<string, unknown>): boolean {
  for (const f of ARRAY_FIELDS) if (isSet(node[f])) return true;
  for (const f of SINGLE_FIELDS) if (isSet(node[f])) return true;
  for (const fields of PAIR_REQUIRED) {
    if (fields.every((f) => isSet(node[f]))) return true;
  }
  return false;
}
