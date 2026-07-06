import type { Case } from "./bench-types";

/** Registry key field by lane (which anchor public field holds the proposed identity key). */
export const KEY_FIELD: Record<string, string> = {
  ein: "registry_ein",
  sos_id: "sos_id",
  committee_id: "committee_id",
};

export type CaseRefs = {
  vendorId: string;
  anchorId: string;
  proposedKey: string;
  source: string;
};

function singleJoin(c: Case) {
  if (c.candidate_joins.length !== 1) {
    throw new Error(`case ${c.case_id} must contain exactly one candidate_join`);
  }
  return c.candidate_joins[0];
}

/** Single owner of the workbench's case endpoint convention: left = vendor, right = anchor. */
export function caseRefs(c: Case): CaseRefs {
  const join = singleJoin(c);
  const source = join.left_ref.source_id;
  const field = KEY_FIELD[source];
  const rawKey = field ? join.right_ref.public_fields[field] : undefined;
  return {
    vendorId: String(join.left_ref.local_id),
    anchorId: String(join.right_ref.local_id),
    proposedKey: rawKey == null || rawKey === "" ? "—" : String(rawKey),
    source,
  };
}
