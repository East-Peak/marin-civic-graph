import { describe, it, expect } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { HeroTitle } from "@/components/entity/hero-title";
import type { EntityPayload } from "@/lib/server/entity-loader";

function makeEntity(overrides: Partial<EntityPayload>): EntityPayload {
  return {
    id: "person-kate-colin",
    type: "Person",
    label: "Kate Colin",
    properties: { id: "person-kate-colin" },
    neighbors: [],
    edges: [],
    neighbor_total: 0,
    focus_event_date: null,
    ...overrides,
  };
}

describe("HeroTitle", () => {
  it("renders kicker, VT323 title, and jurisdiction meta for a Person", () => {
    render(
      <HeroTitle
        entity={makeEntity({
          type: "Person",
          label: "Kate Colin",
          properties: {
            id: "person-kate-colin",
            name: "Kate Colin",
            jurisdiction_name: "San Rafael",
          },
        })}
      />,
    );
    expect(screen.getByTestId("hero-kicker").textContent).toBe("PERSON");
    expect(screen.getByTestId("hero-title").textContent).toBe("Kate Colin");
    expect(screen.getByTestId("hero-meta").textContent).toContain("San Rafael");
  });

  it("includes decided_at in the kicker for Decision", () => {
    render(
      <HeroTitle
        entity={makeEntity({
          id: "decision-2024-08-19-resolution-15336",
          type: "Decision",
          label: "Resolution 15336",
          properties: {
            id: "decision-2024-08-19-resolution-15336",
            decided_at: "2024-08-19",
            institution_name: "San Rafael City Council",
            status: "adopted",
          },
        })}
      />,
    );
    const kicker = screen.getByTestId("hero-kicker").textContent ?? "";
    expect(kicker).toContain("DECISION");
    expect(kicker).toContain("2024-08-19");
    const meta = screen.getByTestId("hero-meta").textContent ?? "";
    expect(meta).toContain("San Rafael City Council");
    expect(meta).toContain("adopted");
  });

  it("omits meta strip when there are no meta parts", () => {
    render(
      <HeroTitle
        entity={makeEntity({
          type: "Issue",
          label: "Homelessness",
          properties: { id: "issue-homelessness" },
        })}
      />,
    );
    expect(screen.queryByTestId("hero-meta")).toBeNull();
  });

  it("renders verified identity chips with key kind, digits, and toggle details", () => {
    render(
      <HeroTitle
        entity={makeEntity({
          id: "org-target",
          type: "Organization",
          label: "Target Vendor",
          properties: { id: "org-target" },
          identity_links: [
            {
              peer_id: "org-bmf-ein-123456789",
              peer_label: "Target Vendor EIN",
              direction: "verified_by",
              assertion_id: "assertion-ein",
              basis: "BMF hard-key match",
              decided_at: "2026-07-01",
            },
            {
              peer_id: "org-casos-7654321",
              peer_label: "Target Vendor CA SOS",
              direction: "verifies",
              assertion_id: "assertion-sos",
              basis: "CA SOS hard-key match",
              decided_at: "2026-07-02",
            },
          ],
        })}
      />,
    );

    expect(screen.getByTestId("verified-identity-row")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /EIN 123456789/i })).toBeInTheDocument();
    const sos = screen.getByRole("button", { name: /CA SOS 7654321/i });
    fireEvent.click(sos);
    const details = screen.getByTestId("verified-identity-popover");
    expect(details.textContent).toContain("CA SOS hard-key match");
    expect(details.textContent).toContain("2026-07-02");
    expect(details.textContent).toContain("assertion-sos");
  });

  it("does not render verified identity chips when identity links are absent", () => {
    render(<HeroTitle entity={makeEntity({ type: "Organization", label: "Target Vendor" })} />);
    expect(screen.queryByTestId("verified-identity-row")).toBeNull();
  });
});
