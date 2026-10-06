import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import path from "node:path";
import { CampaignFreshness, NETFILE_JURISDICTIONS, yearRanges } from "@/components/contributions/campaign-freshness";
import { CAMPAIGN_FRESHNESS } from "../../lib/server/contribution-fixtures";

describe("CampaignFreshness", () => {
  it("shows each source's latest report date, export dates and unavailable and held years", () => {
    const { container } = render(<CampaignFreshness freshness={CAMPAIGN_FRESHNESS} />);
    const text = container.textContent!;
    expect(text).toContain("Marin County: latest report date observed: 2026-09-30");
    expect(text).toContain("Marin County exports: 2019–2024 downloaded 2026-04-14; 2025–2026 downloaded 2026-10-01");
    expect(text).toContain("Novato: latest report date observed: 2024-12-16");
    expect(text).toContain("Novato: 2019–2021, 2025–2026 not available");
    expect(text).toContain("Novato: a newer download for 2024 did not validate and is held; the earlier export is shown");
    expect(text).not.toMatch(/filings through/i);
    expect(container.querySelectorAll("[data-testid='campaign-freshness-source']")).toHaveLength(2);
  });

  it("shows only the sources of the given jurisdictions", () => {
    const { container } = render(<CampaignFreshness freshness={CAMPAIGN_FRESHNESS} jurisdictions={["place-novato"]} />);
    expect(container.textContent).toContain("Novato:");
    expect(container.textContent).not.toContain("Marin County");
  });

  it("renders nothing for a page outside every NetFile jurisdiction", () => {
    const { container } = render(<CampaignFreshness freshness={CAMPAIGN_FRESHNESS} jurisdictions={[]} />);
    expect(container.innerHTML).toBe("");
  });

  it("says plainly when the artifact carries no freshness", () => {
    const { container } = render(<CampaignFreshness freshness={null} />);
    expect(container.textContent).toBe("Campaign data coverage dates are not available for this build.");
  });

  it("says nothing about NetFile coverage on a page outside the NetFile jurisdictions", () => {
    for (const freshness of [null, CAMPAIGN_FRESHNESS]) {
      const { container } = render(<CampaignFreshness freshness={freshness} jurisdictions={["place-san-rafael"]} />);
      expect(container.innerHTML).toBe("");
    }
    const novato = render(<CampaignFreshness freshness={null} jurisdictions={["place-novato"]} />);
    expect(novato.container.textContent).toContain("not available for this build");
  });

  it("knows the NetFile jurisdictions the registry configures", () => {
    const registry = readFileSync(path.join(process.cwd(), "..", "registry", "netfile-sources.yaml"), "utf8");
    const configured = [...registry.matchAll(/^\s+jurisdiction_id: (\S+)$/gm)].map((m) => m[1]).sort();
    expect([...NETFILE_JURISDICTIONS].sort()).toEqual(configured);
  });

  it("claims an earlier export for a held year only when there is one", () => {
    const held = { ...CAMPAIGN_FRESHNESS, sources: [{ ...CAMPAIGN_FRESHNESS.sources[1], held_years: ["2024", "2025"] }] };
    const text = render(<CampaignFreshness freshness={held} />).container.textContent!;
    expect(text).toContain("Novato: a newer download for 2024 did not validate and is held; the earlier export is shown");
    expect(text).toContain("Novato: a download for 2025 did not validate and is held");
    expect(text).not.toContain("for 2025 did not validate and is held; the earlier export is shown");
  });

  it("writes year lists as ranges", () => {
    expect(yearRanges(["2025", "2019", "2020", "2021", "2026", "2023"])).toBe("2019–2021, 2023, 2025–2026");
    expect(yearRanges([])).toBe("");
  });
});
