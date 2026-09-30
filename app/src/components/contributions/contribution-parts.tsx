// app/src/components/contributions/contribution-parts.tsx
//
// The labels and cells every contribution surface shares. A contributor node groups
// every contribution filed under one name, so totals always say what they are:
// "reported under this name", possibly more than one person or organization.

import type { ContributorType } from "@/lib/entity-route";
import type { ReportedDetails } from "@/lib/server/contributions-sql";

export const COVERAGE_NOTE = "NetFile filings for Marin County and Novato; San Rafael not yet included.";
export const DETAILS_DISCLAIMER =
  "As reported on each filing. Reports under this name vary; differences do not establish whether contributors are the same or different.";
export const NOT_AVAILABLE = "Not available in this dataset";

export function mayRepresent(type: ContributorType): string {
  return type === "Organization" ? "May represent multiple organizations" : "May represent multiple people";
}

export function recordedAs(type: ContributorType): string {
  return type === "Organization" ? "an organization" : "an individual";
}

/** Signed dollars from integer cents; a refund reads "−$25.00". */
export function formatCents(cents: number): string {
  const dollars = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(
    Math.abs(cents) / 100,
  );
  return cents < 0 ? `−${dollars}` : dollars;
}

export const tableClass = "w-full border-collapse font-mono text-xs";
export const headCellClass =
  "border-b border-border-hairline px-3 py-2 text-left text-[10px] font-medium uppercase tracking-[0.14em] text-hairline";
export const cellClass = "px-3 py-1.5 align-top text-body";
export const amountClass = "px-3 py-1.5 align-top text-right whitespace-nowrap text-[#f2c77a]";
export const linkClass = "underline decoration-[#262b35] hover:text-[#a4e8bf] hover:decoration-[#a4e8bf]";

export function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="mb-2 font-mono text-[10px] uppercase tracking-[0.12em] text-hairline">{children}</div>
  );
}

export function Note({ children }: { children: React.ReactNode }) {
  return <p className="font-mono text-[11px] leading-relaxed text-dim">{children}</p>;
}

/** The filings' classification of a name, never a claim about who is behind it. */
export function RecordedType({ type }: { type: ContributorType }) {
  return <div className="text-[10px] text-dim">Recorded as {recordedAs(type)}</div>;
}

export function ContributionTotal({ cents, type }: { cents: number; type: ContributorType }) {
  return (
    <span data-testid="contribution-total" className="inline-flex flex-col">
      <span className="whitespace-nowrap text-[#f2c77a]">{formatCents(cents)}</span>
      <span className="text-[10px] text-dim">{mayRepresent(type)}</span>
    </span>
  );
}

function location(details: ReportedDetails): string | null {
  const cityState = [details.city, details.state].filter(Boolean).join(", ");
  return [cityState, details.zip5].filter(Boolean).join(" ") || null;
}

/** One filing's reported occupation, employer and location, never mixed with another row's. */
export function ReportedDetailsCell({ details }: { details: ReportedDetails }) {
  const fields = [
    ["Occupation", details.occupation],
    ["Employer", details.employer],
    ["Location", location(details)],
  ] as const;
  if (fields.every(([, value]) => value === null)) {
    return <span className="text-hairline">{NOT_AVAILABLE}</span>;
  }
  return (
    <dl className="grid grid-cols-[72px_1fr] gap-x-2">
      {fields.map(([key, value]) => (
        <div key={key} className="contents">
          <dt className="text-dim">{key}</dt>
          <dd className={value === null ? "text-hairline" : "break-words"}>{value ?? NOT_AVAILABLE}</dd>
        </div>
      ))}
    </dl>
  );
}
