import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { RecordSourceLink } from "@/components/entity/entity-page";
import type { EntityPayload } from "@/lib/server/entity-loader";

function makeRecord(props: Record<string, unknown>): EntityPayload {
  return {
    id: "record-foo",
    type: "Record",
    label: "Foo",
    properties: { id: "record-foo", ...props },
    neighbors: [],
    edges: [],
    neighbor_total: 0,
    focus_event_date: null,
  };
}

describe("RecordSourceLink (Codex round 1 fix 7)", () => {
  it("renders a clickable source link when preferred_public_url is present", () => {
    render(
      <RecordSourceLink
        entity={makeRecord({
          preferred_public_url: "https://marin.granicus.com/foo.pdf",
          preferred_display_artifact: "Staff report PDF",
        })}
      />,
    );
    const link = screen.getByTestId("record-source-link").querySelector("a");
    expect(link).not.toBeNull();
    expect(link?.getAttribute("href")).toBe("https://marin.granicus.com/foo.pdf");
    expect(link?.getAttribute("target")).toBe("_blank");
    expect(link?.getAttribute("rel")).toBe("noopener noreferrer");
    expect(link?.textContent).toContain("Staff report PDF");
  });

  it("falls back to 'open source' label when display artifact is missing", () => {
    render(
      <RecordSourceLink
        entity={makeRecord({ preferred_public_url: "https://marin.granicus.com/foo" })}
      />,
    );
    const link = screen.getByTestId("record-source-link").querySelector("a");
    expect(link?.textContent).toContain("open source");
  });

  it("renders an empty-state block when preferred_public_url is null", () => {
    render(<RecordSourceLink entity={makeRecord({ preferred_public_url: null })} />);
    expect(screen.getByTestId("record-source-link-empty").textContent).toContain(
      "no public source captured",
    );
    expect(screen.queryByTestId("record-source-link")).toBeNull();
  });
});
