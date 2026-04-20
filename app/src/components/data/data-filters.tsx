"use client";

// app/src/components/data/data-filters.tsx
//
// Horizontal chip-row above the data table. Each FilterDef renders as a
// labelled input (date/number/select/text). Editing any field pushes the new
// state into the URL via router.replace() so the page re-renders on the
// server and re-runs the Cypher. Typing in text boxes is debounced to avoid
// a round-trip per keystroke.

import { useRouter, usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import type { FilterDef } from "@/lib/server/data-queries";

const DEBOUNCE_MS = 400;

// Serializable slice of DataQueryDef — excludes the Cypher builder function,
// which can't cross the server -> client boundary per React Server Components.
export type DataFiltersDef = {
  slug: string;
  filters: FilterDef[];
};

export type DataFiltersProps = {
  def: DataFiltersDef;
  /** Current filter values from the page's searchParams. */
  values: Record<string, string>;
};

function effectiveDefaults(
  def: DataFiltersDef,
  values: Record<string, string>,
): Record<string, string> {
  const out: Record<string, string> = {};
  for (const f of def.filters) {
    out[f.key] = values[f.key] ?? f.default ?? "";
  }
  return out;
}

export function DataFilters({ def, values }: DataFiltersProps) {
  const router = useRouter();
  const pathname = usePathname();
  const [local, setLocal] = useState<Record<string, string>>(() =>
    effectiveDefaults(def, values),
  );

  // Re-sync when the URL-driven values change (e.g. switching queries).
  const prevSlugRef = useRef<string>(def.slug);
  useEffect(() => {
    if (prevSlugRef.current !== def.slug) {
      setLocal(effectiveDefaults(def, values));
      prevSlugRef.current = def.slug;
    }
  }, [def, values]);

  function pushToUrl(next: Record<string, string>) {
    const qs = new URLSearchParams();
    for (const f of def.filters) {
      const value = next[f.key];
      if (value != null && value !== "") qs.set(f.key, value);
    }
    const query = qs.toString();
    router.replace(query ? `${pathname}?${query}` : pathname);
  }

  function onChange(key: string, value: string, filterType: FilterDef["type"]) {
    const next = { ...local, [key]: value };
    setLocal(next);
    if (filterType === "text" || filterType === "amount") {
      // Debounce text/number to avoid per-keystroke navigation.
      const id = window.setTimeout(() => pushToUrl(next), DEBOUNCE_MS);
      return () => window.clearTimeout(id);
    }
    pushToUrl(next);
  }

  if (def.filters.length === 0) {
    return (
      <div className="mb-4 font-mono text-xs text-hairline">No filters.</div>
    );
  }

  return (
    <div
      data-testid="data-filters"
      className="mb-4 flex flex-wrap gap-3 font-mono text-xs"
    >
      {def.filters.map((f) => {
        const id = `filter-${f.key}`;
        const value = local[f.key] ?? "";
        const labelText = f.required ? `${f.label} *` : f.label;
        return (
          <label
            key={f.key}
            htmlFor={id}
            className="flex items-center gap-2 rounded border border-border-hairline bg-surface px-2 py-1 text-dim"
          >
            <span className="text-[10px] uppercase tracking-[0.14em] text-hairline">
              {labelText}
            </span>
            {f.type === "select" ? (
              <select
                id={id}
                aria-label={f.label}
                className="bg-transparent font-mono text-xs text-body outline-none"
                value={value}
                onChange={(e) => onChange(f.key, e.target.value, f.type)}
              >
                {(f.options ?? []).map((opt) => (
                  <option key={opt} value={opt}>
                    {opt === "" ? "—" : opt}
                  </option>
                ))}
              </select>
            ) : (
              <input
                id={id}
                aria-label={f.label}
                type={
                  f.type === "date"
                    ? "date"
                    : f.type === "amount"
                      ? "number"
                      : "text"
                }
                placeholder={f.placeholder ?? ""}
                className="w-[170px] bg-transparent font-mono text-xs text-body outline-none placeholder:text-hairline"
                value={value}
                onChange={(e) => onChange(f.key, e.target.value, f.type)}
              />
            )}
          </label>
        );
      })}
    </div>
  );
}
