import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { Connections } from "@/components/entity/connections";
import type { EntityPayload } from "@/lib/server/entity-loader";

function makeEntity(overrides: Partial<EntityPayload> = {}): EntityPayload {
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

describe("Connections", () => {
  it("groups neighbors by rel type (heading per rel)", () => {
    const entity = makeEntity({
      neighbors: [
        {
          id: "meeting-sr-2024-08-19",
          type: "Meeting",
          label: "SR City Council — 2024-08-19",
          route: "/meeting/sr-2024-08-19",
          ring: 1,
          role: "must-show",
          event_date: null,
        },
        {
          id: "meeting-sr-2024-09-16",
          type: "Meeting",
          label: "SR City Council — 2024-09-16",
          route: "/meeting/sr-2024-09-16",
          ring: 1,
          role: "must-show",
          event_date: null,
        },
        {
          id: "org-san-rafael-city-council",
          type: "Organization",
          label: "San Rafael City Council",
          route: "/organization/san-rafael-city-council",
          ring: 1,
          role: "must-show",
          event_date: null,
        },
      ],
      edges: [
        {
          source: "person-kate-colin",
          target: "meeting-sr-2024-08-19",
          type: "ATTENDED",
          style: "governance",
        },
        {
          source: "person-kate-colin",
          target: "meeting-sr-2024-09-16",
          type: "ATTENDED",
          style: "governance",
        },
        {
          source: "person-kate-colin",
          target: "org-san-rafael-city-council",
          type: "MEMBER_OF",
          style: "governance",
        },
      ],
      neighbor_total: 3,
    });

    render(<Connections entity={entity} />);
    const groups = screen.getAllByTestId("connection-group");
    expect(groups).toHaveLength(2);
    const headings = screen
      .getAllByTestId("connection-group-heading")
      .map((h) => h.textContent ?? "");
    expect(headings.some((h) => h.includes("attended"))).toBe(true);
    expect(headings.some((h) => h.includes("member of"))).toBe(true);
  });

  it("renders neighbor cards with clickable links", () => {
    const entity = makeEntity({
      neighbors: [
        {
          id: "meeting-x",
          type: "Meeting",
          label: "Meeting X",
          route: "/meeting/x",
          ring: 1,
          role: "must-show",
          event_date: null,
        },
      ],
      edges: [
        {
          source: "person-kate-colin",
          target: "meeting-x",
          type: "ATTENDED",
          style: "governance",
        },
      ],
      neighbor_total: 1,
    });
    render(<Connections entity={entity} />);
    const link = screen.getByRole("link", { name: /Meeting X/i });
    expect(link.getAttribute("href")).toBe("/meeting/x");
  });

  it("shows overflow footer when neighbor_total exceeds rendered neighbors", () => {
    const entity = makeEntity({
      neighbors: [
        {
          id: "meeting-x",
          type: "Meeting",
          label: "Meeting X",
          route: "/meeting/x",
          ring: 1,
          role: "must-show",
          event_date: null,
        },
      ],
      edges: [
        {
          source: "person-kate-colin",
          target: "meeting-x",
          type: "ATTENDED",
          style: "governance",
        },
      ],
      neighbor_total: 42,
    });
    render(<Connections entity={entity} />);
    const overflow = screen.getByTestId("connections-overflow");
    expect(overflow.textContent).toContain("41");
    expect(overflow.getAttribute("href")).toContain("/graph?focus=person-kate-colin");
  });

  it("returns null when there are no neighbors", () => {
    const { container } = render(<Connections entity={makeEntity()} />);
    expect(container.firstChild).toBeNull();
  });

  it("shows each kind of money on its own line and never adds kinds together", () => {
    render(
      <Connections
        entity={makeEntity({
          type: "Organization",
          id: "org-target",
          label: "Target Vendor",
          money_rollup: {
            flows_in_count: 3,
            money_in_total: 12540,
            flows_out_count: 1,
            money_out_total: 2750,
            by_kind: [
              { kind: "county_contract", in_count: 2, in_total: 12500, out_count: 0, out_total: 0 },
              { kind: "campaign_spending", in_count: 1, in_total: 40, out_count: 0, out_total: 0 },
              { kind: "campaign_contribution", in_count: 0, in_total: 0, out_count: 1, out_total: 2750 },
            ],
            top_counterparties: [
              { id: "org-county", label: "County of Marin", total: 12500, kind: "county_contract" },
              { id: "org-consultant", label: "Consultant LLC", total: 2750, kind: "campaign_contribution" },
            ],
          },
        })}
      />,
    );

    const block = screen.getByTestId("verified-money");
    const text = block.textContent ?? "";
    expect(text).toContain("MONEY ON RECORD");
    expect(text).not.toContain("VERIFIED MONEY");
    expect(text).toContain("County contract amounts");
    expect(text).toContain("contract amounts, not payments");
    expect(text).toContain("$12,500");
    expect(text).toContain("2 contracts");
    expect(text).toContain("Campaign spending");
    expect(text).toContain("$40");
    expect(text).toContain("Campaign contributions");
    expect(text).toContain("$2,750");
    expect(text).toContain("1 given");
    expect(text).not.toContain("$12,540"); // kinds are never summed
    const county = screen.getByRole("link", { name: /County of Marin/i });
    expect(county.getAttribute("href")).toBe("/organization/county");
    expect(county.textContent).toContain("county contract");
    expect(screen.getByRole("link", { name: /Consultant LLC/i }).textContent).toContain("contribution");
  });

  it("does not render verified money when the rollup field is absent or null", () => {
    const { rerender } = render(<Connections entity={makeEntity()} />);
    expect(screen.queryByTestId("verified-money")).toBeNull();

    rerender(<Connections entity={makeEntity({ money_rollup: null })} />);
    expect(screen.queryByTestId("verified-money")).toBeNull();
  });

  it("renders groups + cards in deterministic order regardless of edge input order (round 3 fix)", () => {
    // Shuffled neighbor + edge input should still render: groups sorted alpha
    // by rel type (RELATED last), cards sorted by neighbor.id within each group.
    const entity = makeEntity({
      neighbors: [
        { id: "meeting-z", type: "Meeting", label: "Z", route: "/meeting/z", ring: 1, role: "must-show", event_date: null },
        { id: "meeting-a", type: "Meeting", label: "A", route: "/meeting/a", ring: 1, role: "must-show", event_date: null },
        { id: "org-z", type: "Organization", label: "Org Z", route: "/organization/z", ring: 1, role: "must-show", event_date: null },
        { id: "case-m", type: "Case", label: "Case M", route: "/case/m", ring: 1, role: "must-show", event_date: null },
      ],
      edges: [
        // Deliberately shuffled — MEMBER_OF first, then ZANDERS, then ATTENDED
        { source: "person-kate-colin", target: "org-z", type: "MEMBER_OF", style: "governance" },
        { source: "person-kate-colin", target: "case-m", type: "ZANDERS", style: "governance" },
        { source: "person-kate-colin", target: "meeting-z", type: "ATTENDED", style: "governance" },
        { source: "person-kate-colin", target: "meeting-a", type: "ATTENDED", style: "governance" },
      ],
      neighbor_total: 4,
    });

    render(<Connections entity={entity} />);
    const headings = screen
      .getAllByTestId("connection-group-heading")
      .map((h) => (h.textContent ?? "").split(/\d/)[0].trim());
    // Alphabetical: attended, member of, zanders
    expect(headings).toEqual(["attended", "member of", "zanders"]);

    // Cards within the ATTENDED group must be sorted by id ascending.
    const cards = screen.getAllByRole("link").map((a) => a.getAttribute("href"));
    const meetingAIdx = cards.indexOf("/meeting/a");
    const meetingZIdx = cards.indexOf("/meeting/z");
    expect(meetingAIdx).toBeGreaterThan(-1);
    expect(meetingZIdx).toBeGreaterThan(-1);
    expect(meetingAIdx).toBeLessThan(meetingZIdx);
  });

  it("orphan neighbors land in a RELATED group at the end", () => {
    const entity = makeEntity({
      neighbors: [
        { id: "person-alpha", type: "Person", label: "Alpha", route: "/person/alpha", ring: 1, role: "must-show", event_date: null },
        { id: "meeting-x", type: "Meeting", label: "Meeting X", route: "/meeting/x", ring: 1, role: "must-show", event_date: null },
      ],
      // Only meeting-x has an edge; person-alpha is orphaned → RELATED group
      edges: [
        { source: "person-kate-colin", target: "meeting-x", type: "ATTENDED", style: "governance" },
      ],
      neighbor_total: 2,
    });

    render(<Connections entity={entity} />);
    const headings = screen
      .getAllByTestId("connection-group-heading")
      .map((h) => (h.textContent ?? "").split(/\d/)[0].trim());
    // RELATED always last
    expect(headings[headings.length - 1]).toBe("related");
  });

  describe("votes on CAST_VOTE cards", () => {
    const VOTES = ["aye", "no", "abstain", "absent", "recused"] as const;
    const neighbor = (id: string, type: "Person" | "Decision") => ({
      id,
      type,
      label: id,
      route: `/${type.toLowerCase()}/${id}`,
      ring: 1 as const,
      role: "must-show" as const,
      event_date: null,
    });
    const cardFor = (route: string) => screen.getAllByRole("link").find((a) => a.getAttribute("href") === route)!;

    it("labels each decision on a Person page with how the person voted (the person is the edge's start)", () => {
      const entity = makeEntity({
        id: "person-avery-quill",
        type: "Person",
        label: "Avery Quill",
        neighbors: [...VOTES.map((v) => neighbor(`decision-${v}`, "Decision")), neighbor("decision-unknown", "Decision")],
        edges: [
          ...VOTES.map((vote) => ({
            source: "person-avery-quill",
            target: `decision-${vote}`,
            type: "CAST_VOTE",
            style: "governance" as const,
            props: { vote },
          })),
          { source: "person-avery-quill", target: "decision-unknown", type: "CAST_VOTE", style: "governance" },
        ],
        neighbor_total: 6,
      });

      render(<Connections entity={entity} />);

      expect(cardFor("/decision/decision-aye").textContent).toContain("voted aye");
      expect(cardFor("/decision/decision-no").textContent).toContain("voted no");
      expect(cardFor("/decision/decision-abstain").textContent).toContain("abstained");
      expect(cardFor("/decision/decision-absent").textContent).toContain("absent");
      expect(cardFor("/decision/decision-recused").textContent).toContain("recused");
      expect(cardFor("/decision/decision-absent").textContent).not.toMatch(/vot/);
      expect(cardFor("/decision/decision-recused").textContent).not.toMatch(/vot/);
      // A missing value shows no label at all.
      expect(cardFor("/decision/decision-unknown").querySelector('[data-testid="vote-label"]')).toBeNull();
      expect(screen.getAllByTestId("vote-label")).toHaveLength(5);
    });

    it("labels each member on a Decision page with their own vote (the decision is the edge's end)", () => {
      const entity = makeEntity({
        id: "decision-fictional-levee",
        type: "Decision",
        label: "Fictional levee",
        neighbors: [neighbor("person-avery-quill", "Person"), neighbor("person-bo-tarn", "Person")],
        edges: [
          { source: "person-avery-quill", target: "decision-fictional-levee", type: "CAST_VOTE", style: "governance", props: { vote: "absent" } },
          { source: "person-bo-tarn", target: "decision-fictional-levee", type: "CAST_VOTE", style: "governance", props: { vote: "no" } },
          // An edge between two neighbors never labels a card: only the focus's own vote edges do.
          { source: "person-bo-tarn", target: "person-avery-quill", type: "CAST_VOTE", style: "governance", props: { vote: "aye" } },
        ],
        neighbor_total: 2,
      });

      render(<Connections entity={entity} />);

      expect(cardFor("/person/person-avery-quill").querySelector('[data-testid="vote-label"]')?.textContent).toBe("absent");
      expect(cardFor("/person/person-bo-tarn").querySelector('[data-testid="vote-label"]')?.textContent).toBe("voted no");
    });

    it("heads the CAST_VOTE group 'roll call', so absent and recused members never sit under a voting heading", () => {
      const entity = makeEntity({
        id: "decision-fictional-levee",
        type: "Decision",
        neighbors: [neighbor("person-avery-quill", "Person")],
        edges: [
          { source: "person-avery-quill", target: "decision-fictional-levee", type: "CAST_VOTE", style: "governance", props: { vote: "absent" } },
        ],
        neighbor_total: 1,
      });

      render(<Connections entity={entity} />);

      const heading = screen.getByTestId("connection-group-heading").textContent ?? "";
      expect(heading).toMatch(/^roll call/);
      expect(heading).not.toMatch(/vote/);
    });

    it("never labels a card in another group, even when that neighbor also has a vote edge", () => {
      const entity = makeEntity({
        id: "person-avery-quill",
        type: "Person",
        neighbors: [neighbor("decision-aye", "Decision")],
        edges: [
          { source: "person-avery-quill", target: "decision-aye", type: "CAST_VOTE", style: "governance", props: { vote: "aye" } },
          { source: "person-avery-quill", target: "decision-aye", type: "MOVED", style: "governance" },
        ],
        neighbor_total: 1,
      });

      render(<Connections entity={entity} />);

      const groups = screen.getAllByTestId("connection-group");
      const labelled = groups.map((g) => g.querySelectorAll('[data-testid="vote-label"]').length);
      expect(labelled.sort()).toEqual([0, 1]);
    });
  });
});
