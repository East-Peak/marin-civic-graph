// app/src/app/contributions/by-name/[type]/[slug]/page.tsx
//
// Contributions reported under one name: the rows a Person/Organization node groups,
// and nothing else about the node — no profile, roles, graph or identity links. The
// node's type is how the filings classified the name, not a verified identity.

import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { StatusBar } from "@/components/layout/status-bar";
import { NavHeader } from "@/components/layout/nav-header";
import {
  COVERAGE_NOTE,
  ContributionTotal,
  DETAILS_DISCLAIMER,
  NOT_AVAILABLE,
  Note,
  ReportedDetailsCell,
  SectionLabel,
  amountClass,
  cellClass,
  formatCents,
  headCellClass,
  linkClass,
  recordedAs,
  tableClass,
} from "@/components/contributions/contribution-parts";
import { loadStatus } from "@/lib/server/homepage-data";
import { contributionNameMetadata } from "@/lib/server/contribution-metadata";
import { loadContributionsByName, resolveContributorNode } from "@/lib/server/contributions-sql";

export const dynamic = "force-dynamic";

type Props = { params: Promise<{ type: string; slug: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { type, slug } = await params;
  return contributionNameMetadata(resolveContributorNode(type, slug));
}

export default async function ContributionsByNamePage({ params }: Props) {
  const { type, slug } = await params;
  const contributor = resolveContributorNode(type, slug);
  const view = contributor ? loadContributionsByName(contributor.id) : null;
  if (!contributor || !view) notFound();

  const status = await loadStatus();
  const kind = contributor.type;

  return (
    <div className="min-h-screen bg-bg">
      <StatusBar
        connected={status.connected}
        nodeCount={status.node_count}
        edgeCount={status.edge_count}
        jurisdictionCount={status.jurisdiction_count}
        ingestAt={status.ingest_at}
        subgraphsBuiltAt={status.subgraphs_built_at}
      />
      <NavHeader currentPath="/contributions" />
      <main className="mx-[18px] mt-6 pb-12">
        <SectionLabel>Campaign contributions · reported under a name</SectionLabel>
        <h1
          className="mb-3 break-words text-body"
          style={{ fontFamily: "var(--font-vt323)", fontSize: "28px", letterSpacing: "0.02em" }}
        >
          Contributions reported under {contributor.label}
        </h1>
        <div className="mb-5 max-w-3xl space-y-1">
          <Note>
            Recorded on the filings as {recordedAs(kind)}. This name groups every contribution filed under it; it is
            not a verified identity.
          </Note>
          <Note>{COVERAGE_NOTE}</Note>
        </div>

        <div className="mb-6 flex flex-wrap items-start gap-6 rounded border border-border-hairline bg-panel px-4 py-3 font-mono text-xs">
          <div>
            <div className="text-[10px] uppercase tracking-[0.14em] text-hairline">Contributions</div>
            <div className="text-body">{view.totals.count.toLocaleString("en-US")}</div>
          </div>
          <div>
            <div className="text-[10px] uppercase tracking-[0.14em] text-hairline">Total reported under this name</div>
            <ContributionTotal cents={view.totals.total_cents} type={kind} />
          </div>
        </div>

        <section className="mb-8">
          <SectionLabel>By recipient committee</SectionLabel>
          <div className="overflow-x-auto rounded border border-border-hairline">
            <table className={tableClass}>
              <thead>
                <tr className="bg-surface">
                  <th className={headCellClass}>Committee</th>
                  <th className={`${headCellClass} text-right`}>Contributions</th>
                  <th className={`${headCellClass} text-right`}>Total</th>
                </tr>
              </thead>
              <tbody>
                {view.by_committee.map((entry) => (
                  <tr key={entry.recipient.id} className="border-b border-border-hairline last:border-b-0">
                    <td className={cellClass}>
                      <Link href={entry.recipient.route} className={linkClass}>
                        {entry.recipient.label}
                      </Link>
                    </td>
                    <td className={`${cellClass} text-right`}>{entry.count.toLocaleString("en-US")}</td>
                    <td className={`${cellClass} text-right`}>
                      <ContributionTotal cents={entry.total_cents} type={kind} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section>
          <SectionLabel>Contributions</SectionLabel>
          <div className="mb-2">
            <Note>{DETAILS_DISCLAIMER}</Note>
          </div>
          <div className="overflow-x-auto rounded border border-border-hairline">
            <table className={tableClass}>
              <thead>
                <tr className="bg-surface">
                  <th className={headCellClass}>Date</th>
                  <th className={`${headCellClass} text-right`}>Amount</th>
                  <th className={headCellClass}>Recipient committee</th>
                  <th className={headCellClass}>Reported details</th>
                  <th className={headCellClass}>Filing</th>
                </tr>
              </thead>
              <tbody data-testid="contribution-rows">
                {view.rows.map((row) => (
                  <tr
                    key={`${row.flow_id}:${row.recipient?.id ?? ""}`}
                    className="border-b border-border-hairline last:border-b-0"
                  >
                    <td className={`${cellClass} whitespace-nowrap`}>{row.date ?? "—"}</td>
                    <td className={amountClass}>{formatCents(row.amount_cents)}</td>
                    <td className={cellClass}>
                      {row.recipient ? (
                        <Link href={row.recipient.route} className={linkClass}>
                          {row.recipient.label}
                        </Link>
                      ) : (
                        <span className="text-hairline">{NOT_AVAILABLE}</span>
                      )}
                    </td>
                    <td className={`${cellClass} min-w-[220px]`}>
                      <ReportedDetailsCell details={row.details} />
                    </td>
                    <td className={cellClass}>
                      <Link href={row.flow_route} className={linkClass}>
                        record
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </main>
    </div>
  );
}
