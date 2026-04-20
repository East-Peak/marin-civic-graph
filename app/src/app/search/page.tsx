// app/src/app/search/page.tsx
//
// Real search results page (Plan 3 Phase D). Server component — reads the
// query from searchParams and hands off to <SearchResults />, which calls
// runSearch() directly against AuraDB.

import { StatusBar } from "@/components/layout/status-bar";
import { NavHeader } from "@/components/layout/nav-header";
import { loadStatus } from "@/lib/server/homepage-data";
import { SearchResults } from "@/components/search/search-results";

export const dynamic = "force-dynamic";

export default async function SearchPage({
  searchParams,
}: {
  searchParams: Promise<{ q?: string; include_records?: string }>;
}) {
  const { q, include_records } = await searchParams;
  const query = (q ?? "").trim();
  const includeRecords = include_records === "true";
  const status = await loadStatus();

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
      <NavHeader currentPath="/search" />
      <div className="mx-[18px] mt-6 max-w-[900px]">
        <div className="mb-4 font-mono text-[10px] uppercase tracking-[0.14em] text-hairline">
          {query ? `SEARCH · ${query.toUpperCase()}` : "SEARCH"}
        </div>
        <div
          className="mb-6 flex items-center gap-3 text-body"
          style={{
            fontFamily: "var(--font-vt323)",
            fontSize: "22px",
            letterSpacing: "0.04em",
          }}
        >
          <span className="text-[#a4e8bf]">&gt;</span>
          <span>{query || "no query"}</span>
        </div>
        {query ? (
          <SearchResults query={query} includeRecords={includeRecords} />
        ) : (
          <p className="font-mono text-sm text-dim">
            Type a search term in the homepage prompt to search.
          </p>
        )}
      </div>
    </div>
  );
}
