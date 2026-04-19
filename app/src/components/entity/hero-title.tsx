// Per spec §7.1 item 3 + §2.3. Kicker (Plex Mono 10px uppercase), big title
// (VT323 40px), and meta strip (Plex Mono 11px). The meta strip content is
// type-specific — see metaStripFor below.

import type { EntityPayload } from "@/lib/server/entity-loader";
import type { NodeType } from "@/lib/type-display";

function s(v: unknown): string | null {
  return typeof v === "string" && v.length > 0 ? v : null;
}

/**
 * Kicker suffix drawn from props when it adds recognition value to the type
 * label (e.g. `DECISION · 2024-08-19`). Null for types where no date belongs
 * in the kicker.
 */
function kickerSuffixFor(type: NodeType, props: Record<string, unknown>): string | null {
  switch (type) {
    case "Decision":
      return s(props.decided_at);
    case "Meeting":
      return s(props.meeting_date);
    default:
      return null;
  }
}

/**
 * Type-specific meta strip entries. Returns the list of non-null bits that
 * render beneath the title in Plex Mono 11px, separated by middots.
 */
export function metaStripFor(
  type: NodeType,
  props: Record<string, unknown>,
): string[] {
  const parts: (string | null)[] = (() => {
    switch (type) {
      case "Person":
        return [s(props.jurisdiction_name)];
      case "Decision":
        return [s(props.institution_name), s(props.status)];
      case "Project":
      case "Program":
        return [s(props.jurisdiction_name), s(props.status)];
      case "Case":
        return [s(props.docket_number), s(props.status)];
      case "Meeting":
        return [s(props.institution_name)];
      case "Filing": {
        const filer = s(props.filed_by_name) ?? s(props.filer_name);
        const a = s(props.period_start);
        const b = s(props.period_end);
        const window = a && b ? `${a} – ${b}` : (a ?? b);
        return [filer, window];
      }
      case "Committee":
        return [s(props.fppc_id)];
      default:
        return [s(props.jurisdiction_name)];
    }
  })();
  return parts.filter((p): p is string => p !== null && p.length > 0);
}

export function HeroTitle({ entity }: { entity: EntityPayload }) {
  const typeUpper = entity.type.toUpperCase();
  const kickerSuffix = kickerSuffixFor(entity.type, entity.properties);
  const meta = metaStripFor(entity.type, entity.properties);

  return (
    <div className="px-[18px] pt-8 pb-5">
      <div
        className="font-mono uppercase text-dim"
        style={{ fontSize: "10px", letterSpacing: "0.14em" }}
        data-testid="hero-kicker"
      >
        {kickerSuffix ? `${typeUpper} · ${kickerSuffix}` : typeUpper}
      </div>
      <h1
        className="mt-1.5 text-body"
        style={{
          fontFamily: "var(--font-vt323)",
          fontSize: "40px",
          lineHeight: 1.05,
          letterSpacing: "0.01em",
        }}
        data-testid="hero-title"
      >
        {entity.label}
      </h1>
      {meta.length > 0 && (
        <div
          className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 font-mono text-dim"
          style={{ fontSize: "11px" }}
          data-testid="hero-meta"
        >
          {meta.map((item, i) => (
            <span key={`${item}-${i}`} className="flex items-center gap-2">
              {i > 0 && <span className="text-hairline">·</span>}
              <span>{item}</span>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
