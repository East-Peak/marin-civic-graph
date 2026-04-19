import { describe, it, expect } from "vitest";
import { effectiveEventDate } from "@/lib/server/entity-temporal";
import { ALL_TYPES, type NodeType } from "@/lib/type-display";

describe("effectiveEventDate", () => {
  it("returns meeting_date for Meeting", () => {
    expect(effectiveEventDate("Meeting", { meeting_date: "2024-08-19" })).toBe(
      "2024-08-19",
    );
  });

  it("returns decided_at for Decision", () => {
    expect(effectiveEventDate("Decision", { decided_at: "2024-08-19" })).toBe(
      "2024-08-19",
    );
  });

  it("returns flow_date for MoneyFlow", () => {
    expect(effectiveEventDate("MoneyFlow", { flow_date: "2024-09-01" })).toBe(
      "2024-09-01",
    );
  });

  it("returns signed_at for Filing", () => {
    expect(effectiveEventDate("Filing", { signed_at: "2024-09-15" })).toBe(
      "2024-09-15",
    );
  });

  it("returns election_date for Election", () => {
    expect(effectiveEventDate("Election", { election_date: "2024-11-05" })).toBe(
      "2024-11-05",
    );
  });

  it("returns date for Proceeding", () => {
    expect(effectiveEventDate("Proceeding", { date: "2025-02-01" })).toBe(
      "2025-02-01",
    );
  });

  it("returns effective_date for Agreement and Amendment", () => {
    expect(
      effectiveEventDate("Agreement", { effective_date: "2023-07-01" }),
    ).toBe("2023-07-01");
    expect(
      effectiveEventDate("Amendment", { effective_date: "2024-07-01" }),
    ).toBe("2024-07-01");
  });

  it("returns filed_at for Case (range start only in Batch F)", () => {
    expect(
      effectiveEventDate("Case", {
        filed_at: "2024-03-01",
        closed_at: "2025-06-01",
      }),
    ).toBe("2024-03-01");
  });

  it("returns parent_meeting_date for AgendaItem, falling back to meeting_date", () => {
    expect(
      effectiveEventDate("AgendaItem", { parent_meeting_date: "2024-08-19" }),
    ).toBe("2024-08-19");
    expect(
      effectiveEventDate("AgendaItem", { meeting_date: "2024-08-19" }),
    ).toBe("2024-08-19");
  });

  it("returns published_at, falling back to captured_at for Record", () => {
    expect(
      effectiveEventDate("Record", { published_at: "2024-08-20" }),
    ).toBe("2024-08-20");
    expect(
      effectiveEventDate("Record", { captured_at: "2024-08-21" }),
    ).toBe("2024-08-21");
  });

  it("returns null for Candidacy (linked Election not loaded)", () => {
    expect(effectiveEventDate("Candidacy", {})).toBeNull();
  });

  it("returns started_at for SeatService (range start)", () => {
    expect(
      effectiveEventDate("SeatService", { started_at: "2022-12-12" }),
    ).toBe("2022-12-12");
  });

  it("returns null for durable types (Person/Org/Committee/Project/Program/Place/Issue/Seat)", () => {
    const durables: NodeType[] = [
      "Person",
      "Organization",
      "Committee",
      "Project",
      "Program",
      "Place",
      "Issue",
      "Seat",
    ];
    for (const t of durables) {
      expect(
        effectiveEventDate(t, { name: "X", meeting_date: "2024-01-01" }),
        `type=${t}`,
      ).toBeNull();
    }
  });

  it("returns null when the required field is missing", () => {
    expect(effectiveEventDate("Meeting", {})).toBeNull();
    expect(effectiveEventDate("Decision", {})).toBeNull();
    expect(effectiveEventDate("Filing", {})).toBeNull();
  });

  it("covers every node type exhaustively (type-check guard)", () => {
    for (const t of ALL_TYPES as readonly NodeType[]) {
      // calling should not throw for any type
      expect(() => effectiveEventDate(t, {})).not.toThrow();
    }
  });
});
