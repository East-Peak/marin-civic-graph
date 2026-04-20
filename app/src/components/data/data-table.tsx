"use client";

// app/src/components/data/data-table.tsx
//
// Plex Mono, dense table. Sort-on-click per column (toggles ASC/DESC; first
// click = DESC since most tables here are time-ordered). Renders id columns
// as links to entity pages using the id-prefix heuristic. CSV export button
// below the table streams the current rows as a browser download.
//
// Cell rendering notes:
// - Amount cells (alignment: "right" + amount heuristic): amber, Plex Mono.
// - Date cells: plain body color.
// - Link cells: colored + underlined on hover.

import Link from "next/link";
import { useMemo, useState } from "react";
import type { ColumnDef } from "@/lib/server/data-queries";
import { urlSegmentForType, type NodeType, ALL_TYPES } from "@/lib/type-display";

export type DataTableProps = {
  rows: Record<string, unknown>[];
  columns: ColumnDef[];
  /** Query slug — used as CSV filename prefix. */
  slug: string;
};

type SortState = {
  key: string;
  dir: "asc" | "desc";
} | null;

const NODE_TYPE_SET: ReadonlySet<string> = new Set(ALL_TYPES);

function routeForId(id: string): string | null {
  if (!id.includes("-")) return null;
  const prefix = id.slice(0, id.indexOf("-"));
  // Map prefix -> canonical NodeType. Keep this small and explicit; if a
  // prefix isn't in the table, we fall back to no-link.
  const PREFIX_TO_TYPE: Record<string, NodeType> = {
    person: "Person",
    org: "Organization",
    committee: "Committee",
    seat: "Seat",
    seatservice: "SeatService",
    election: "Election",
    candidacy: "Candidacy",
    meeting: "Meeting",
    agendaitem: "AgendaItem",
    decision: "Decision",
    filing: "Filing",
    moneyflow: "MoneyFlow",
    case: "Case",
    proceeding: "Proceeding",
    project: "Project",
    program: "Program",
    agreement: "Agreement",
    amendment: "Amendment",
    record: "Record",
    place: "Place",
    issue: "Issue",
  };
  const type = PREFIX_TO_TYPE[prefix];
  if (!type || !NODE_TYPE_SET.has(type)) return null;
  const slug = id.slice(id.indexOf("-") + 1);
  return `/${urlSegmentForType(type)}/${slug}`;
}

function formatAmount(v: unknown): string {
  if (v == null || v === "") return "—";
  const n = typeof v === "number" ? v : Number(v);
  if (!Number.isFinite(n)) return String(v);
  return n.toLocaleString("en-US", { maximumFractionDigits: 2 });
}

function formatCell(value: unknown): string {
  if (value == null) return "—";
  if (value === "") return "—";
  return String(value);
}

function compare(a: unknown, b: unknown): number {
  if (a == null && b == null) return 0;
  if (a == null) return -1;
  if (b == null) return 1;
  if (typeof a === "number" && typeof b === "number") return a - b;
  return String(a).localeCompare(String(b));
}

function escapeCsv(v: unknown): string {
  if (v == null) return "";
  const s = String(v);
  if (s.includes(",") || s.includes("\n") || s.includes('"')) {
    return `"${s.replace(/"/g, '""')}"`;
  }
  return s;
}

export function exportCsv(
  rows: Record<string, unknown>[],
  columns: ColumnDef[],
  slug: string,
): { blob: Blob; filename: string } {
  const header = columns.map((c) => escapeCsv(c.label)).join(",");
  const body = rows
    .map((r) => columns.map((c) => escapeCsv(r[c.key])).join(","))
    .join("\n");
  const blob = new Blob([`${header}\n${body}`], { type: "text/csv" });
  const filename = `${slug}-${new Date().toISOString().slice(0, 10)}.csv`;
  return { blob, filename };
}

function triggerDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export function DataTable({ rows, columns, slug }: DataTableProps) {
  const [sort, setSort] = useState<SortState>(null);

  const sortedRows = useMemo(() => {
    if (!sort) return rows;
    const copy = [...rows];
    copy.sort((a, b) => {
      const cmp = compare(a[sort.key], b[sort.key]);
      return sort.dir === "asc" ? cmp : -cmp;
    });
    return copy;
  }, [rows, sort]);

  function onHeaderClick(col: ColumnDef) {
    if (!col.sortable) return;
    setSort((prev) => {
      if (!prev || prev.key !== col.key) return { key: col.key, dir: "desc" };
      return { key: col.key, dir: prev.dir === "desc" ? "asc" : "desc" };
    });
  }

  function onExport() {
    const { blob, filename } = exportCsv(sortedRows, columns, slug);
    triggerDownload(blob, filename);
  }

  return (
    <div>
      <div className="overflow-auto rounded border border-border-hairline">
        <table
          data-testid="data-table"
          className="w-full border-collapse font-mono text-xs"
        >
          <thead>
            <tr className="bg-surface">
              {columns.map((col) => {
                const isSorted = sort?.key === col.key;
                const arrow = isSorted ? (sort?.dir === "desc" ? "↓" : "↑") : "";
                const align = col.alignment === "right" ? "text-right" : "text-left";
                const sortable = col.sortable
                  ? "cursor-pointer select-none hover:text-body"
                  : "";
                return (
                  <th
                    key={col.key}
                    scope="col"
                    onClick={() => onHeaderClick(col)}
                    className={`${align} ${sortable} border-b border-border-hairline px-3 py-2 text-[10px] font-medium uppercase tracking-[0.14em] text-hairline`}
                  >
                    {col.label} {arrow}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {sortedRows.length === 0 && (
              <tr>
                <td
                  colSpan={columns.length}
                  className="px-3 py-6 text-center text-dim"
                >
                  No rows.
                </td>
              </tr>
            )}
            {sortedRows.map((row, idx) => (
              <tr
                key={idx}
                className="border-b border-border-hairline hover:bg-[#14171d]"
              >
                {columns.map((col) => {
                  const rawValue = row[col.key];
                  const align =
                    col.alignment === "right" ? "text-right" : "text-left";
                  if (col.link === "entity-route" && typeof rawValue === "string") {
                    const route = routeForId(rawValue);
                    if (route) {
                      return (
                        <td
                          key={col.key}
                          className={`${align} px-3 py-1.5 text-body`}
                        >
                          <Link
                            href={route}
                            className="underline decoration-[#262b35] hover:text-[#a4e8bf] hover:decoration-[#a4e8bf]"
                          >
                            {rawValue}
                          </Link>
                        </td>
                      );
                    }
                  }
                  if (col.alignment === "right") {
                    return (
                      <td
                        key={col.key}
                        className={`${align} px-3 py-1.5 text-[#f2c77a]`}
                      >
                        {formatAmount(rawValue)}
                      </td>
                    );
                  }
                  return (
                    <td
                      key={col.key}
                      className={`${align} px-3 py-1.5 text-body`}
                    >
                      {formatCell(rawValue)}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-3 flex items-center gap-3 font-mono text-[11px] text-dim">
        <span>{sortedRows.length.toLocaleString()} rows</span>
        <span className="flex-1" />
        <button
          type="button"
          onClick={onExport}
          className="rounded border border-border-hairline bg-surface px-3 py-1 text-dim hover:text-body"
        >
          Export CSV
        </button>
      </div>
    </div>
  );
}
