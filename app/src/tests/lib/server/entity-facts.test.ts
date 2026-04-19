import { describe, it, expect } from "vitest";
import { factsForEntity } from "@/lib/server/entity-facts";
import { ALL_TYPES, type NodeType } from "@/lib/type-display";

describe("factsForEntity", () => {
  it("returns Person rows from known props", () => {
    const rows = factsForEntity("Person", {
      id: "person-kate-colin",
      name: "Kate Colin",
      current_seat_display: "Mayor — San Rafael",
      jurisdiction_name: "San Rafael",
      aliases: ["Kathleen Colin"],
    });
    const map = Object.fromEntries(rows.map((r) => [r.key, r.value]));
    expect(map["Name"]).toBe("Kate Colin");
    expect(map["Current seat"]).toBe("Mayor — San Rafael");
    expect(map["Jurisdiction"]).toBe("San Rafael");
    expect(map["Aliases"]).toBe("Kathleen Colin");
    expect(map["ID"]).toBe("person-kate-colin");
  });

  it("returns Decision rows including decided_at", () => {
    const rows = factsForEntity("Decision", {
      id: "decision-2024-08-19-resolution-15336",
      decided_at: "2024-08-19",
      institution_name: "San Rafael City Council",
      vote_summary: "5-0",
      status: "adopted",
    });
    const map = Object.fromEntries(rows.map((r) => [r.key, r.value]));
    expect(map["Decided"]).toBe("2024-08-19");
    expect(map["Institution"]).toBe("San Rafael City Council");
    expect(map["Vote"]).toBe("5-0");
    expect(map["Status"]).toBe("adopted");
  });

  it("collapses Filing period_start + period_end into one row", () => {
    const rows = factsForEntity("Filing", {
      id: "filing-1",
      filing_type: "Form 460",
      signed_at: "2024-09-15",
      period_start: "2024-07-01",
      period_end: "2024-09-30",
      filed_by_name: "Committee to Elect",
    });
    const period = rows.find((r) => r.key === "Period")?.value;
    expect(period).toBe("2024-07-01 – 2024-09-30");
  });

  it("emits nulls for missing props (not the id row)", () => {
    const rows = factsForEntity("Project", {
      id: "project-350-merrydale-interim-shelter",
      name: "350 Merrydale Interim Shelter",
    });
    const map = Object.fromEntries(rows.map((r) => [r.key, r.value]));
    expect(map["Name"]).toBe("350 Merrydale Interim Shelter");
    expect(map["Status"]).toBeNull();
    expect(map["ID"]).toBe("project-350-merrydale-interim-shelter");
  });

  it("returns a non-empty array for each of the 21 node types", () => {
    for (const type of ALL_TYPES as readonly NodeType[]) {
      const rows = factsForEntity(type, { id: `${type}-sample` });
      expect(rows.length, `type=${type}`).toBeGreaterThan(0);
      // Last row is always the ID row.
      expect(rows[rows.length - 1].key).toBe("ID");
    }
  });
});
