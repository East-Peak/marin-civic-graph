// app/src/app/contributions/page.tsx
//
// The largest reconciled campaign contributions, one row per contribution as filed.

import type { Metadata } from "next";
import { StatusBar } from "@/components/layout/status-bar";
import { NavHeader } from "@/components/layout/nav-header";
import { COVERAGE_NOTE, DETAILS_DISCLAIMER, Note, SectionLabel } from "@/components/contributions/contribution-parts";
import { LargestContributions } from "@/components/contributions/largest-contributions";
import { loadStatus } from "@/lib/server/homepage-data";
import { countContributions } from "@/lib/server/contributions-sql";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Largest contributions",
  description:
    "Campaign contributions reported in Marin County and Novato NetFile filings, largest first, each with its filing.",
};

type Props = { searchParams?: Promise<Record<string, string | string[] | undefined>> };

export default async function ContributionsPage({ searchParams }: Props) {
  const after = (await searchParams)?.after;
  const status = await loadStatus();
  const count = countContributions();

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
        <SectionLabel>Campaign contributions</SectionLabel>
        <h1
          className="mb-3 text-body"
          style={{ fontFamily: "var(--font-vt323)", fontSize: "28px", letterSpacing: "0.02em" }}
        >
          Largest contributions
        </h1>
        <div className="mb-5 max-w-3xl space-y-1">
          <Note>
            {count.toLocaleString("en-US")} contributions, one row each as filed. A reported name groups every
            contribution filed under it and may represent multiple people or organizations.
          </Note>
          <Note>{COVERAGE_NOTE}</Note>
          <Note>{DETAILS_DISCLAIMER}</Note>
        </div>
        <LargestContributions after={typeof after === "string" ? after : null} />
      </main>
    </div>
  );
}
