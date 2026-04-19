import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { EvidenceDrawer } from "@/components/entity/evidence-drawer";
import type { EvidenceRecord } from "@/lib/server/entity-evidence";

const recordPublic: EvidenceRecord = {
  id: "record-sr-minutes-2024-08-19",
  record_type: "minutes",
  captured_at: "2024-09-01T00:00:00Z",
  preferred_public_url: "https://example.gov/minutes.pdf",
  preferred_display_artifact: "Council minutes PDF",
  has_public_source: true,
};

const recordNoSource: EvidenceRecord = {
  id: "record-sr-staff-report-2024-08-19",
  record_type: "staff_report",
  captured_at: "2024-09-01T00:00:00Z",
  preferred_public_url: null,
  preferred_display_artifact: "Staff report",
  has_public_source: false,
};

describe("EvidenceDrawer", () => {
  it("renders collapsed by default with the record count", () => {
    render(<EvidenceDrawer records={[recordPublic, recordNoSource]} />);
    const toggle = screen.getByTestId("evidence-toggle");
    expect(toggle.textContent).toContain("2");
    expect(screen.queryByTestId("evidence-list")).toBeNull();
  });

  it("expands to show rows when clicked", () => {
    render(<EvidenceDrawer records={[recordPublic, recordNoSource]} />);
    fireEvent.click(screen.getByTestId("evidence-toggle"));
    expect(screen.getByTestId("evidence-list")).toBeInTheDocument();
    expect(screen.getAllByTestId("evidence-row")).toHaveLength(2);
  });

  it("records with has_public_source=true render as <a> with target=_blank", () => {
    render(<EvidenceDrawer records={[recordPublic]} />);
    fireEvent.click(screen.getByTestId("evidence-toggle"));
    const row = screen.getByTestId("evidence-row");
    expect(row.tagName).toBe("A");
    expect(row.getAttribute("href")).toBe("https://example.gov/minutes.pdf");
    expect(row.getAttribute("target")).toBe("_blank");
    expect(row.getAttribute("rel")).toContain("noopener");
  });

  it("records with has_public_source=false render as a dim non-link with tooltip", () => {
    render(<EvidenceDrawer records={[recordNoSource]} />);
    fireEvent.click(screen.getByTestId("evidence-toggle"));
    const row = screen.getByTestId("evidence-row");
    expect(row.tagName).toBe("SPAN");
    expect(row.getAttribute("title")).toBe("no public source captured");
  });

  it("renders the record id as selectable (select-all)", () => {
    render(<EvidenceDrawer records={[recordPublic]} />);
    fireEvent.click(screen.getByTestId("evidence-toggle"));
    const idEl = screen.getByTestId("evidence-record-id");
    expect(idEl.className).toContain("select-all");
    expect(idEl.textContent).toBe("record-sr-minutes-2024-08-19");
  });
});
