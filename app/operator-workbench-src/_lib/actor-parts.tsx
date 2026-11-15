// Shared plain-UI pieces for the operator actor pages (/actors, /actors/[slug], /cases/[docket]).
import Link from "next/link";
import type { CoverageRow, Fact } from "./actors";

export function Absent({ path }: { path: string }) {
  return (
    <p>
      The actor index is not built: no file at <code>{path}</code>. Run <code>scripts/actor_index.py build</code>. The
      rest of the app is unaffected.
    </p>
  );
}

export function money(n: number | null): string {
  return n === null ? "no amount" : `$${n.toLocaleString("en-US", { maximumFractionDigits: 2 })}`;
}

export function caseHref(docket: string): string {
  return `/cases/${encodeURIComponent(docket)}`;
}

/** Coverage as "what this section searched", so "none found" and "not covered" read differently. */
export function Coverage({ rows }: { rows: CoverageRow[] }) {
  if (rows.length === 0) return <p className="text-sm">Coverage: not recorded for this section.</p>;
  return (
    <ul className="text-sm">
      {rows.map((c) => {
        const d = JSON.parse(c.detail) as Record<string, unknown>;
        const extra = Object.entries(d)
          .filter(([, v]) => v !== null && v !== "" && !(Array.isArray(v) && v.length === 0))
          .map(([k, v]) => `${k.replaceAll("_", " ")}: ${show(v)}`)
          .join("; ");
        return (
          <li key={`${c.input}/${c.item}`}>
            Coverage — {c.input.replaceAll("_", " ")} / {c.item}: <strong>{c.state}</strong>
            {extra && ` (${extra})`}
          </li>
        );
      })}
    </ul>
  );
}

/** A coverage value as text: lists joined, objects (a gap, a per-state count) as their values. */
function show(v: unknown): string {
  if (Array.isArray(v)) return v.map(show).join(", ");
  if (v && typeof v === "object") {
    return Object.entries(v).map(([k, x]) => (typeof x === "number" ? `${k} ${x}` : String(x).replaceAll("_", " ")))
      .join(" ");
  }
  return String(v);
}

export function Source({ f }: { f: Fact }) {
  if (f.kind === "minutes_mentions") {
    // The count is the evidence's index; the pages themselves are in the minutes search.
    return <Link className="underline" href={`/minutes?q=${encodeURIComponent(`"${f.actor_name}"`)}`}>{f.source_ref}</Link>;
  }
  const d = JSON.parse(f.detail) as { docket?: string };
  if (d.docket) {
    return <Link className="underline" href={caseHref(d.docket)}>{f.source_ref}</Link>;
  }
  return f.source_url ? (
    <a className="underline" href={f.source_url} target="_blank" rel="noreferrer noopener">{f.source_ref}</a>
  ) : (
    <span>{f.source_ref}</span>
  );
}

const BASIS: Record<string, string> = {
  substrate_id: "by substrate id", ein: "by EIN", pattern_reviewed: "by reviewed name pattern",
  pattern_unreviewed: "by an unreviewed name pattern", pattern_ein_not_in_registry:
    "by name, on an EIN the registry does not list", reviewed_role: "by the reviewed case roles",
  ledger_body: "the ledger's own body", stated_name: "name as stated",
};

export function basisText(basis: string | null): string {
  return basis ? BASIS[basis] ?? basis : "";
}
