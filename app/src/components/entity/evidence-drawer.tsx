"use client";

// Expandable evidence drawer per spec §7.1 item 10. Collapsed by default; on
// expand lists up to 50 Records. Each row honors the record display contract
// (preferred_public_url / preferred_display_artifact / has_public_source).

import { useState } from "react";
import type { EvidenceRecord } from "@/lib/server/entity-evidence";

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return iso.slice(0, 10);
}

export function EvidenceDrawer({ records }: { records: EvidenceRecord[] }) {
  const [open, setOpen] = useState(false);
  const count = records.length;

  return (
    <section className="mx-[18px] my-6 border border-border-hairline bg-panel" data-testid="evidence-drawer">
      <button
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        className="flex w-full items-center justify-between px-4 py-3 text-left font-mono uppercase text-dim hover:text-body"
        style={{ fontSize: "10px", letterSpacing: "0.14em" }}
        aria-expanded={open}
        data-testid="evidence-toggle"
      >
        <span>
          Evidence <span className="ml-2 text-hairline">{count}</span>
        </span>
        <span className="text-hairline" aria-hidden>
          {open ? "▾" : "▸"}
        </span>
      </button>
      {open && (
        <ul className="border-t border-border-hairline" data-testid="evidence-list">
          {count === 0 && (
            <li
              className="px-4 py-3 font-mono text-hairline"
              style={{ fontSize: "11px" }}
            >
              no records linked
            </li>
          )}
          {records.map((r) => (
            <EvidenceRow key={r.id} record={r} />
          ))}
        </ul>
      )}
    </section>
  );
}

function EvidenceRow({ record }: { record: EvidenceRecord }) {
  const label = record.preferred_display_artifact ?? record.record_type;
  const commonInner = (
    <div className="grid grid-cols-[120px_110px_1fr_auto] items-center gap-3">
      <span
        className="font-mono uppercase text-dim"
        style={{ fontSize: "10px", letterSpacing: "0.14em" }}
      >
        {record.record_type}
      </span>
      <span className="font-mono text-hairline" style={{ fontSize: "11px" }}>
        {formatDate(record.captured_at)}
      </span>
      <span
        className={
          record.has_public_source ? "font-mono text-body" : "font-mono text-hairline"
        }
        style={{ fontSize: "12px" }}
      >
        {label}
        {!record.has_public_source && (
          <span className="ml-2 text-hairline" style={{ fontSize: "10px" }}>
            (no public source captured)
          </span>
        )}
      </span>
      <span
        className="select-all font-mono text-hairline"
        style={{ fontSize: "10px" }}
        data-testid="evidence-record-id"
      >
        {record.id}
      </span>
    </div>
  );

  if (record.has_public_source && record.preferred_public_url) {
    return (
      <li className="border-b border-border-hairline last:border-b-0">
        <a
          href={record.preferred_public_url}
          target="_blank"
          rel="noopener noreferrer"
          className="block px-4 py-2.5 hover:bg-surface"
          data-testid="evidence-row"
        >
          {commonInner}
        </a>
      </li>
    );
  }

  return (
    <li className="border-b border-border-hairline last:border-b-0">
      <span
        className="block cursor-not-allowed px-4 py-2.5 opacity-70"
        title="no public source captured"
        data-testid="evidence-row"
      >
        {commonInner}
      </span>
    </li>
  );
}
