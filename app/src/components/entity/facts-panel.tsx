// Plex Mono key/value table for the entity-page right rail. Per spec §7.1
// item 6 (Tier 1) and §7.2 (Tier 2). Null values render as em-dash; the ID
// row is always present (see entity-facts.ts).

import type { EntityPayload } from "@/lib/server/entity-loader";
import { factsForEntity } from "@/lib/server/entity-facts";

export function FactsPanel({ entity }: { entity: EntityPayload }) {
  const rows = factsForEntity(entity.type, entity.properties);

  // Edge case: if every row is null (no ID either), skip the panel entirely.
  if (rows.every((r) => r.value === null)) return null;

  return (
    <div className="border border-border-hairline bg-panel" data-testid="facts-panel">
      <div
        className="border-b border-border-hairline px-3 py-2 font-mono uppercase text-dim"
        style={{ fontSize: "10px", letterSpacing: "0.14em" }}
      >
        Facts
      </div>
      <dl className="font-mono" style={{ fontSize: "12px" }}>
        {rows.map((row, i) => (
          <div
            key={`${row.key}-${i}`}
            className="grid grid-cols-[110px_1fr] gap-3 border-b border-border-hairline px-3 py-2 last:border-b-0"
            data-testid="fact-row"
          >
            <dt className="text-dim">{row.key}</dt>
            <dd
              className={
                row.value === null
                  ? "text-hairline"
                  : row.key === "ID"
                    ? "select-all break-all text-body"
                    : "break-words text-body"
              }
            >
              {row.value ?? "—"}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
