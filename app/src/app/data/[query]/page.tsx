// app/src/app/data/[query]/page.tsx
//
// Per-query view. Reads slug from params, filter values from searchParams,
// dispatches through the shared server query helper, and renders the left-rail
// nav + filter chips + sortable table + CSV export.

import { notFound } from "next/navigation";
import {
  DATA_QUERIES,
  applyFilterDefaults,
  findDataQuery,
} from "@/lib/server/data-queries";
import { executeDataQuery } from "@/lib/server/data-queries-dispatch";
import { loadStatus } from "@/lib/server/homepage-data";
import { StatusBar } from "@/components/layout/status-bar";
import { NavHeader } from "@/components/layout/nav-header";
import { DataQueryNav } from "@/components/data/data-query-nav";
import { DataFilters } from "@/components/data/data-filters";
import { DataTable } from "@/components/data/data-table";

export const dynamic = "force-dynamic";

export async function generateStaticParams() {
  return DATA_QUERIES.map((q) => ({ query: q.slug }));
}

export default async function DataQueryPage({
  params,
  searchParams,
}: {
  params: Promise<{ query: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { query: slug } = await params;
  const def = findDataQuery(slug);
  if (!def) notFound();

  const raw = await searchParams;
  // Flatten arrays (e.g. when the same key shows up twice) to a single value.
  const providedFilters: Record<string, string> = {};
  for (const [k, v] of Object.entries(raw)) {
    if (Array.isArray(v)) {
      if (v.length > 0 && typeof v[0] === "string") providedFilters[k] = v[0] as string;
    } else if (typeof v === "string") {
      providedFilters[k] = v;
    }
  }
  const filters = applyFilterDefaults(def, providedFilters);

  // Enforce required filters — same contract as /api/data, but render a
  // friendly message instead of a JSON error.
  const missingRequired = def.filters.filter(
    (f) => f.required && !filters[f.key],
  );

  let rows: Record<string, unknown>[] = [];
  let queryError: string | null = null;
  if (missingRequired.length === 0) {
    try {
      const result = await executeDataQuery(def, filters);
      rows = result.rows;
    } catch (err) {
      console.error(`/data/${slug} failed:`, err);
      queryError = "Query failed. Check the filter values.";
    }
  }

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
      <NavHeader currentPath="/data" />
      <div className="flex gap-0">
        <DataQueryNav activeSlug={slug} />
        <div className="min-w-0 flex-1 p-6">
          <div className="mb-6">
            <h1 className="font-mono text-[10px] uppercase tracking-[0.14em] text-hairline">
              DATA · {slug}
            </h1>
            <h2 className="mt-1 text-xl text-body">{def.display_name}</h2>
            <p className="mt-1 font-mono text-xs text-dim">{def.description}</p>
          </div>
          <DataFilters
            def={{ slug: def.slug, filters: def.filters }}
            values={providedFilters}
          />
          {missingRequired.length > 0 ? (
            <div className="rounded border border-border-hairline bg-surface p-4 font-mono text-xs text-dim">
              <div className="mb-1 text-body">Required filter missing.</div>
              <div>
                Provide a value for{" "}
                {missingRequired.map((f, i) => (
                  <span key={f.key}>
                    {i > 0 ? ", " : ""}
                    <code className="text-body">{f.label}</code>
                  </span>
                ))}{" "}
                to run this query.
              </div>
            </div>
          ) : queryError ? (
            <div className="rounded border border-[#7f3a3a] bg-[#1a0d0d] p-4 font-mono text-xs text-[#e5a0a0]">
              {queryError}
            </div>
          ) : (
            <DataTable rows={rows} columns={def.columns} slug={slug} />
          )}
        </div>
      </div>
    </div>
  );
}
