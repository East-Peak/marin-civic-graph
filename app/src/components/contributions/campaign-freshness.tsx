// app/src/components/contributions/campaign-freshness.tsx
//
// How fresh the campaign data is, per NetFile source, exactly as the bake published it: the latest report
// date observed in the exports, the date each year's export was downloaded, and the years not available or
// held. It says what was observed, never "filings through".

import { Note } from "@/components/contributions/contribution-parts";
import type { CampaignFreshness as Freshness, SourceFreshness } from "@/lib/server/campaign-freshness";

export const NO_FRESHNESS = "Campaign data coverage dates are not available for this build.";

/** The jurisdictions of the NetFile sources (registry/netfile-sources.yaml; a test keeps them in step). */
export const NETFILE_JURISDICTIONS: readonly string[] = ["place-marin-county", "place-novato"];

/** "2019–2021, 2023, 2025–2026" */
export function yearRanges(years: string[]): string {
  const sorted = [...new Set(years.map(Number))].sort((a, b) => a - b);
  const runs: string[] = [];
  for (let i = 0; i < sorted.length; ) {
    let j = i;
    while (j + 1 < sorted.length && sorted[j + 1] === sorted[j] + 1) j++;
    runs.push(i === j ? `${sorted[i]}` : `${sorted[i]}–${sorted[j]}`);
    i = j + 1;
  }
  return runs.join(", ");
}

function exportsLine(source: SourceFreshness): string {
  const byDate = new Map<string, string[]>();
  for (const e of source.exports) byDate.set(e.export_date, [...(byDate.get(e.export_date) ?? []), e.year]);
  return [...byDate.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([day, years]) => `${yearRanges(years)} downloaded ${day}`)
    .join("; ");
}

function Source({ source }: { source: SourceFreshness }) {
  const exported = new Set(source.exports.map((e) => e.year));
  const heldWithExport = source.held_years.filter((y) => exported.has(y));
  const heldWithout = source.held_years.filter((y) => !exported.has(y));
  return (
    <div data-testid="campaign-freshness-source">
      <Note>
        {source.name}: latest report date observed: {source.latest_report_date ?? "none"}
      </Note>
      {source.exports.length > 0 && <Note>{source.name} exports: {exportsLine(source)}</Note>}
      {source.unavailable_years.length > 0 && (
        <Note>
          {source.name}: {yearRanges(source.unavailable_years)} not available
        </Note>
      )}
      {heldWithExport.length > 0 && (
        <Note>
          {source.name}: a newer download for {yearRanges(heldWithExport)} did not validate and is held; the earlier
          export is shown
        </Note>
      )}
      {heldWithout.length > 0 && (
        <Note>
          {source.name}: a download for {yearRanges(heldWithout)} did not validate and is held
        </Note>
      )}
    </div>
  );
}

/** `jurisdictions`: show only those sources (a committee's or a money flow's); none matching renders nothing. */
export function CampaignFreshness({
  freshness,
  jurisdictions,
}: {
  freshness: Freshness | null;
  jurisdictions?: string[];
}) {
  const netfile = jurisdictions?.filter((j) => NETFILE_JURISDICTIONS.includes(j));
  if (netfile && netfile.length === 0) return null; // San Rafael and other non-NetFile pages: nothing to say
  if (!freshness) return <Note>{NO_FRESHNESS}</Note>;
  const sources = netfile ? freshness.sources.filter((s) => netfile.includes(s.jurisdiction_id)) : freshness.sources;
  if (sources.length === 0) return null;
  return (
    <div data-testid="campaign-freshness" className="space-y-1">
      {sources.map((source) => (
        <Source key={source.source_id} source={source} />
      ))}
    </div>
  );
}
