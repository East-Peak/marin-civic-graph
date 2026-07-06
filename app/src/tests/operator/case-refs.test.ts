import { describe, expect, it } from "vitest";
import { caseRefs } from "../../../operator-workbench-src/_lib/case-refs";
import { proposedKey, vendorId } from "../../../operator-workbench-src/_lib/bench-logic";
import type { Case } from "../../../operator-workbench-src/_lib/bench-types";

function mkCase(source: string, anchorId: string, vendorIdValue: string, publicFields: Record<string, unknown>): Case {
  return {
    case_id: `attach|${anchorId}|${vendorIdValue}`,
    candidate_joins: [
      {
        left_ref: {
          source_id: source,
          local_id: vendorIdValue,
          display_label: "County Vendor",
          public_fields: {},
        },
        right_ref: {
          source_id: source,
          local_id: anchorId,
          display_label: "Registry Anchor",
          public_fields: publicFields,
        },
        signals: [],
        signal_strength: 0.9,
      },
    ],
    ai_reviews: [],
    current_ledger_status: "none",
    bulk_eligible: false,
    review_flags: {},
  };
}

describe("caseRefs", () => {
  it("names the left ref as vendor and the right ref as anchor", () => {
    const refs = caseRefs(mkCase("ein", "org-bmf-ein-111111111", "org-vendor-alpha", { registry_ein: "111111111" }));

    expect(refs).toEqual({
      vendorId: "org-vendor-alpha",
      anchorId: "org-bmf-ein-111111111",
      proposedKey: "111111111",
      source: "ein",
    });
  });

  it("reads each lane's public proposed-key field", () => {
    expect(caseRefs(mkCase("ein", "org-bmf-ein-111111111", "v1", { registry_ein: "111111111" })).proposedKey).toBe("111111111");
    expect(caseRefs(mkCase("sos_id", "org-casos-0222222", "v2", { sos_id: "0222222" })).proposedKey).toBe("0222222");
    expect(caseRefs(mkCase("committee_id", "org-fppc-3333333", "v3", { committee_id: "3333333" })).proposedKey).toBe("3333333");
  });

  it("uses the bench's existing em-dash fallback for missing proposed keys", () => {
    expect(caseRefs(mkCase("ein", "org-bmf-ein-111111111", "v1", {})).proposedKey).toBe("—");
  });

  it("fails loud when the case does not carry exactly one join", () => {
    const c = mkCase("ein", "org-bmf-ein-111111111", "v1", { registry_ein: "111111111" });
    c.candidate_joins = [];
    expect(() => caseRefs(c)).toThrow(/exactly one candidate_join/);
  });

  it("bench vendorId and proposedKey delegate to the shared caseRefs result", () => {
    const c = mkCase("sos_id", "org-casos-0222222", "org-vendor-beta", { sos_id: "0222222" });

    expect(vendorId(c)).toBe(caseRefs(c).vendorId);
    expect(proposedKey(c)).toBe(caseRefs(c).proposedKey);
  });
});
