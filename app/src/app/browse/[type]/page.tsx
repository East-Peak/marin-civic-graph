// app/src/app/browse/[type]/page.tsx
//
// Per-type browse page (Plan 3 Phase E). Server component — validates the URL
// segment, loads the first 50 rows directly via runBrowseQuery (no HTTP
// self-fetch), and hands off to the client BrowseTable for pagination.

import { notFound } from "next/navigation";
import { StatusBar } from "@/components/layout/status-bar";
import { NavHeader } from "@/components/layout/nav-header";
import { BrowseTable } from "@/components/browse/browse-table";
import { loadStatus } from "@/lib/server/homepage-data";
import { displayNameForType, urlSegmentForType } from "@/lib/type-display";
import {
  nodeTypeForUrlSegment,
  runBrowseQuery,
} from "@/lib/server/browse-queries";

export const dynamic = "force-dynamic";

export default async function BrowseTypePage({
  params,
}: {
  params: Promise<{ type: string }>;
}) {
  const { type: urlSeg } = await params;
  const canonicalType = nodeTypeForUrlSegment(urlSeg);
  if (!canonicalType) notFound();

  const status = await loadStatus();

  let initial;
  let loadError: string | null = null;
  try {
    initial = await runBrowseQuery({ type: canonicalType, limit: 50 });
  } catch (err) {
    console.error(`/browse/${urlSeg} initial load failed:`, err);
    initial = { rows: [], next_cursor: null, columns: [] };
    loadError = "Failed to load rows. Check AuraDB connectivity.";
  }

  const displayName = displayNameForType(canonicalType);

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
      <NavHeader currentPath={`/browse/${urlSegmentForType(canonicalType)}`} />
      <div className="mx-[18px] mt-6">
        <div className="mb-2 font-mono text-[10px] uppercase tracking-[0.12em] text-hairline">
          BROWSE · {displayName.toUpperCase()}
        </div>
        <h1
          className="mb-5 text-body"
          style={{
            fontFamily: "var(--font-vt323)",
            fontSize: "28px",
            letterSpacing: "0.02em",
          }}
        >
          {displayName}
        </h1>
        {loadError ? (
          <div className="rounded border border-[#7f3a3a] bg-[#1a0d0d] p-4 font-mono text-xs text-[#e5a0a0]">
            {loadError}
          </div>
        ) : (
          <BrowseTable type={canonicalType} initial={initial} />
        )}
      </div>
    </div>
  );
}
