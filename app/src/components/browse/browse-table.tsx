"use client";

// app/src/components/browse/browse-table.tsx
//
// Plex Mono, dense browse table with cursor-based pagination. The page
// server-rendered the first slice and passed it in as `initial`; "Load more"
// fetches `/api/browse/{type}?cursor=...` and appends rows to the accumulator.
//
// Search input at the top filters by search_label. Typing resets the
// accumulator and requests the first page anew.

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { urlSegmentForType, type NodeType } from "@/lib/type-display";
import type {
  BrowseColumn,
  BrowseResult,
  BrowseRow,
} from "@/lib/server/browse-queries";

export type BrowseTableProps = {
  type: NodeType;
  initial: BrowseResult;
};

function formatCell(value: unknown): string {
  if (value == null) return "—";
  if (value === "") return "—";
  return String(value);
}

export function BrowseTable({ type, initial }: BrowseTableProps) {
  const urlSeg = urlSegmentForType(type);
  const [rows, setRows] = useState<BrowseRow[]>(initial.rows);
  const [cursor, setCursor] = useState<string | null>(initial.next_cursor);
  const [search, setSearch] = useState<string>("");
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  // Track the search value that was last fetched so we know when the user
  // has typed something new. Without this, debounced fetches can race and
  // stale responses overwrite fresh ones.
  const lastFetchedSearch = useRef<string>("");

  async function fetchPage(opts: {
    cursor: string | null;
    search: string;
    append: boolean;
  }): Promise<void> {
    setLoading(true);
    setError(null);
    try {
      const url = new URL(`/api/browse/${urlSeg}`, window.location.origin);
      if (opts.cursor) url.searchParams.set("cursor", opts.cursor);
      if (opts.search) url.searchParams.set("q", opts.search);
      url.searchParams.set("limit", "50");
      const res = await fetch(url.toString());
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const body = (await res.json()) as BrowseResult & { type: string };
      if (lastFetchedSearch.current !== opts.search) {
        // A newer search term was submitted while this request was in flight —
        // drop the stale response.
        return;
      }
      setRows((prev) => (opts.append ? [...prev, ...body.rows] : body.rows));
      setCursor(body.next_cursor);
    } catch (err) {
      console.error("browse fetch failed", err);
      setError("Failed to load more rows.");
    } finally {
      setLoading(false);
    }
  }

  // Debounce search input — 250ms after the last keystroke.
  useEffect(() => {
    if (search === lastFetchedSearch.current) return;
    const handle = window.setTimeout(() => {
      lastFetchedSearch.current = search;
      void fetchPage({ cursor: null, search, append: false });
    }, 250);
    return () => window.clearTimeout(handle);
    // fetchPage depends only on urlSeg; stable for the lifetime of the row set.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search]);

  const columns = initial.columns;
  const total = rows.length;

  return (
    <div>
      <div className="mb-3 flex items-center gap-3">
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder={`filter ${urlSeg} by name`}
          aria-label={`filter ${urlSeg} by name`}
          className="w-[360px] rounded border border-border-hairline bg-panel px-3 py-1.5 font-mono text-xs text-body placeholder:text-hairline focus:border-[#262b35] focus:outline-none"
        />
        <span className="font-mono text-[11px] text-hairline">
          {total.toLocaleString()} loaded
          {cursor != null ? " (more available)" : ""}
        </span>
      </div>
      <div className="overflow-auto rounded border border-border-hairline">
        <table
          data-testid="browse-table"
          className="w-full border-collapse font-mono text-xs"
        >
          <thead>
            <tr className="bg-surface">
              {columns.map((col: BrowseColumn) => (
                <th
                  key={col.key}
                  scope="col"
                  className="border-b border-border-hairline px-3 py-2 text-left text-[10px] font-medium uppercase tracking-[0.14em] text-hairline"
                >
                  {col.label}
                </th>
              ))}
              <th
                scope="col"
                className="border-b border-border-hairline px-3 py-2 text-left text-[10px] font-medium uppercase tracking-[0.14em] text-hairline"
              >
                ID
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && !loading && (
              <tr>
                <td
                  colSpan={columns.length + 1}
                  className="px-3 py-6 text-center text-dim"
                >
                  No rows.
                </td>
              </tr>
            )}
            {rows.map((row) => (
              <tr
                key={row.id}
                className="border-b border-border-hairline hover:bg-[#14171d]"
              >
                {columns.map((col) => {
                  if (col.key === "search_label") {
                    return (
                      <td key={col.key} className="px-3 py-1.5 text-body">
                        <Link
                          href={row.route}
                          className="underline decoration-[#262b35] hover:text-[#a4e8bf] hover:decoration-[#a4e8bf]"
                        >
                          {row.search_label}
                        </Link>
                      </td>
                    );
                  }
                  return (
                    <td key={col.key} className="px-3 py-1.5 text-body">
                      {formatCell(row[col.key])}
                    </td>
                  );
                })}
                <td className="px-3 py-1.5 text-dim">{row.id}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-3 flex items-center gap-3 font-mono text-[11px] text-dim">
        {error && <span className="text-[#e5a0a0]">{error}</span>}
        <span className="flex-1" />
        {cursor != null && (
          <button
            type="button"
            onClick={() =>
              fetchPage({ cursor, search: lastFetchedSearch.current, append: true })
            }
            disabled={loading}
            className="rounded border border-border-hairline bg-surface px-3 py-1 text-dim hover:text-body disabled:opacity-50"
          >
            {loading ? "Loading…" : "Load more"}
          </button>
        )}
      </div>
    </div>
  );
}
