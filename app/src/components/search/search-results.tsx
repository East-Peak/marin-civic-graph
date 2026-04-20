// app/src/components/search/search-results.tsx
//
// Server component that calls runSearch() directly (no HTTP self-fetch) and
// renders the bucketed results per spec §3.3.
//
// Buckets:
//   1. Exact-id match (if present) — rendered first with an "EXACT MATCH"
//      kicker. Always shown even when includeRecords=false, so a Record ID
//      pasted into the search box still lands the user on that record.
//   2. Entity results — the primary list.
//   3. Record results — only when includeRecords=true, beneath a divider.
//
// Each card: Plex Mono type kicker + Plex Sans label + mini-meta with
// key_fact and last_activity, matched to the homepage typographic scale.

import Link from "next/link";
import { runSearch, type SearchResult } from "@/lib/server/search-backend";

export type SearchResultsProps = {
  query: string;
  includeRecords: boolean;
};

function ResultCard({
  result,
  kicker,
}: {
  result: SearchResult;
  kicker?: string;
}) {
  return (
    <Link
      href={result.route}
      className="block border border-border-hairline bg-panel px-4 py-3 hover:border-[#262b35] hover:bg-surface"
    >
      {kicker && (
        <div className="mb-1 font-mono text-[10px] uppercase tracking-[0.18em] text-[#a4e8bf]">
          {kicker}
        </div>
      )}
      <div className="font-mono uppercase text-dim text-[10px] tracking-[0.12em]">
        {result.type.toUpperCase()}
      </div>
      <div
        className="mt-1 text-body"
        style={{
          fontFamily: "var(--font-plex-sans)",
          fontWeight: 500,
          fontSize: "14px",
        }}
      >
        {result.search_label}
      </div>
      {result.key_fact && (
        <div className="mt-1 font-mono text-hairline text-[11px]">
          {result.key_fact}
        </div>
      )}
      {result.last_activity && (
        <div className="font-mono text-hairline text-[10px]">
          {result.last_activity}
        </div>
      )}
    </Link>
  );
}

function IncludeRecordsToggle({
  query,
  includeRecords,
}: {
  query: string;
  includeRecords: boolean;
}) {
  const base = `/search?q=${encodeURIComponent(query)}`;
  const href = includeRecords ? base : `${base}&include_records=true`;
  return (
    <Link
      href={href}
      className="inline-flex items-center gap-2 font-mono text-[11px] text-dim hover:text-body"
    >
      <span
        className={`inline-block h-3 w-3 border border-border-hairline ${
          includeRecords ? "bg-[#a4e8bf]" : "bg-transparent"
        }`}
        aria-hidden
      />
      <span>include source records</span>
    </Link>
  );
}

/**
 * Test-only split helper — extracted so the test file can exercise the
 * bucket/exact-match partitioning without hitting the DB.
 *
 * Exact-match rules:
 *   - If one result.id === the trimmed query (case-sensitive, matches how
 *     runSearch passes `$q` to Neo4j's exact node match), that result is the
 *     exact match.
 *   - The exact result is pulled out regardless of its type — it shows up
 *     with an EXACT MATCH kicker above the entity bucket.
 */
export function partitionResults(
  query: string,
  results: SearchResult[],
): {
  exact: SearchResult | null;
  entities: SearchResult[];
  records: SearchResult[];
} {
  const trimmed = query.trim();
  let exact: SearchResult | null = null;
  const entities: SearchResult[] = [];
  const records: SearchResult[] = [];
  for (const r of results) {
    if (exact == null && r.id === trimmed) {
      exact = r;
      continue;
    }
    if (r.type === "Record") {
      records.push(r);
    } else {
      entities.push(r);
    }
  }
  return { exact, entities, records };
}

export async function SearchResults({ query, includeRecords }: SearchResultsProps) {
  let payload;
  try {
    payload = await runSearch(query, includeRecords);
  } catch (err) {
    console.error("search-results: runSearch failed", err);
    return (
      <div className="rounded border border-[#7f3a3a] bg-[#1a0d0d] p-4 font-mono text-xs text-[#e5a0a0]">
        Search failed. Try again.
      </div>
    );
  }

  const { exact, entities, records } = partitionResults(query, payload.results);
  const total = payload.results.length;

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-4 font-mono text-[11px] text-hairline">
        <span>{total.toLocaleString()} result{total === 1 ? "" : "s"}</span>
        <span className="flex-1" />
        <IncludeRecordsToggle query={query} includeRecords={includeRecords} />
      </div>

      {total === 0 ? (
        <div className="rounded border border-border-hairline bg-panel p-4 font-mono text-xs text-dim">
          <div className="mb-1 text-body">no matches</div>
          <div>
            Try a shorter term, a person&apos;s last name, a project slug, or
            toggle <em>include source records</em> to widen the search.
          </div>
        </div>
      ) : (
        <>
          {exact && (
            <div className="space-y-2">
              <ResultCard result={exact} kicker="EXACT MATCH" />
            </div>
          )}

          {entities.length > 0 && (
            <div className="space-y-2">
              {entities.map((r) => (
                <ResultCard key={r.id} result={r} />
              ))}
            </div>
          )}

          {records.length > 0 && (
            <div className="space-y-2">
              <div
                data-testid="records-divider"
                className="mt-6 flex items-center gap-3 font-mono text-[10px] uppercase tracking-[0.18em] text-hairline"
              >
                <span>records</span>
                <span className="h-px flex-1 bg-border-hairline" />
                <span>{records.length}</span>
              </div>
              {records.map((r) => (
                <ResultCard key={r.id} result={r} />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
