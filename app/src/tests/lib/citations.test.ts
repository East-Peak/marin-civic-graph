import { describe, it, expect } from "vitest";
import { hasPrimarySourceCitation } from "@/lib/citations";

describe("hasPrimarySourceCitation", () => {
  it("evidence_record_ids non-empty → true", () => {
    expect(hasPrimarySourceCitation({ evidence_record_ids: ["r-1"] })).toBe(true);
  });

  it("evidence_record_ids empty → false", () => {
    expect(hasPrimarySourceCitation({ evidence_record_ids: [] })).toBe(false);
  });

  it("record_ids alternative", () => {
    expect(hasPrimarySourceCitation({ record_ids: ["r-2"] })).toBe(true);
  });

  it("filing_id alone", () => {
    expect(hasPrimarySourceCitation({ filing_id: "F-1" })).toBe(true);
  });

  it("source_url + source_id required as a pair", () => {
    expect(hasPrimarySourceCitation({ source_url: "u" })).toBe(false);
    expect(hasPrimarySourceCitation({ source_url: "u", source_id: "s" })).toBe(true);
  });

  it("blank strings don't count", () => {
    expect(hasPrimarySourceCitation({ filing_id: "" })).toBe(false);
    expect(hasPrimarySourceCitation({ minutes_url: "   " })).toBe(false);
  });

  it("empty node → false", () => {
    expect(hasPrimarySourceCitation({})).toBe(false);
  });

  it("MoneyFlow source_filing_id satisfies", () => {
    expect(hasPrimarySourceCitation({ source_filing_id: "sched-A-1" })).toBe(true);
  });

  it("Committee fppc_id satisfies", () => {
    expect(hasPrimarySourceCitation({ fppc_id: "1234567" })).toBe(true);
  });
});
