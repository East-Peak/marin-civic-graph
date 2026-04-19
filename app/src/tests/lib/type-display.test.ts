// app/src/tests/lib/type-display.test.ts
import { describe, it, expect } from "vitest";
import { urlSegmentForType, displayNameForType, ALL_TYPES, INDEXED_TYPES } from "@/lib/type-display";

describe("type-display", () => {
  it("urlSegmentForType returns kebab-case lowercase", () => {
    expect(urlSegmentForType("Person")).toBe("person");
    expect(urlSegmentForType("SeatService")).toBe("seat-service");
    expect(urlSegmentForType("MoneyFlow")).toBe("money-flow");
    expect(urlSegmentForType("AgendaItem")).toBe("agenda-item");
  });

  it("displayNameForType returns human label", () => {
    expect(displayNameForType("Person")).toBe("People");
    expect(displayNameForType("MoneyFlow")).toBe("Money flows");
    expect(displayNameForType("SeatService")).toBe("Seat services");
  });

  it("ALL_TYPES lists all 21 node types", () => {
    expect(ALL_TYPES).toHaveLength(21);
    expect(ALL_TYPES).toContain("Person");
    expect(ALL_TYPES).toContain("Record");
  });

  it("INDEXED_TYPES is the 14 default search corpus (Record excluded)", () => {
    expect(INDEXED_TYPES).toHaveLength(14);
    expect(INDEXED_TYPES).not.toContain("Record");
    expect(INDEXED_TYPES).toContain("Person");
  });
});
