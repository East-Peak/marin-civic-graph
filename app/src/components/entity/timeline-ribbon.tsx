// Tier 1 horizontal temporal ribbon per spec §7.1 item 8 + §5.4.
//
// Server component (no client hooks) so it can consume the server-only
// effectiveEventDate. Each neighbor with a non-null effective date renders
// as a small diamond on a linear time axis; year boundaries get VT323 tick
// labels. Clicking a diamond navigates to that neighbor's entity page.
//
// Batch F is read-only — no slider, no filter interaction. That comes later
// once we wire the explorer time slider against the same temporal contract.

import Link from "next/link";
import { palette } from "@/lib/palette";
import type { EntityPayload, Neighbor } from "@/lib/server/entity-loader";
import { effectiveEventDate } from "@/lib/server/entity-temporal";
import { colorClassForType } from "@/components/graph/obsidian-style";

type DatedEvent = {
  neighbor: Neighbor;
  date: string;
  time: number; // ms since epoch
};

const WIDTH = 1100; // intrinsic SVG width; viewbox scales
const HEIGHT = 90;
const AXIS_Y = 60;
const DIAMOND_SIZE = 5;
const MARGIN_LEFT = 20;
const MARGIN_RIGHT = 20;

function parseDate(iso: string): number | null {
  // Accept ISO date or date-time; return UTC ms or null if unparseable.
  const t = Date.parse(iso);
  return Number.isFinite(t) ? t : null;
}

function colorForType(type: string): string {
  const cls = colorClassForType(type);
  switch (cls) {
    case "decision":
      return palette.node.decision;
    case "money":
      return palette.node.money;
    case "person":
      return palette.node.person;
    case "legal":
      return palette.node.legal;
    case "organization":
      return palette.node.organization;
    case "projectProgram":
      return palette.node.projectProgram;
    default:
      return palette.node.generic;
  }
}

function collectEvents(entity: EntityPayload): DatedEvent[] {
  const out: DatedEvent[] = [];
  for (const n of entity.neighbors) {
    const d = effectiveEventDate(n.type, { id: n.id });
    // entity-loader doesn't carry full props on neighbors, so the per-date
    // projection above will largely return null. The common-useful signal we
    // have is the focus's own event date, plus what props exist. Inline a
    // second pass using any rich fields on the neighbor if present.
    const fallback = d ?? deriveDateFromNeighbor(n);
    if (!fallback) continue;
    const t = parseDate(fallback);
    if (t == null) continue;
    out.push({ neighbor: n, date: fallback, time: t });
  }
  return out.sort((a, b) => a.time - b.time);
}

/**
 * Neighbors come in from the loader with minimal properties (just id, type,
 * label, route, ring, role). The date contract in §5.4 expects full props;
 * we don't have those per-neighbor in Batch F. Embed a best-effort date
 * parse from the neighbor id suffix (e.g. `decision-2024-08-19-...`) when
 * present, so the ribbon renders *something* for dated-id patterns.
 */
function deriveDateFromNeighbor(n: Neighbor): string | null {
  // Ids frequently encode YYYY-MM-DD right after the type prefix.
  const match = n.id.match(/(\d{4}-\d{2}-\d{2})/);
  if (match) return match[1];
  return null;
}

function yearTicks(minMs: number, maxMs: number): number[] {
  const first = new Date(minMs).getUTCFullYear();
  const last = new Date(maxMs).getUTCFullYear();
  const out: number[] = [];
  for (let y = first; y <= last; y++) {
    out.push(Date.UTC(y, 0, 1));
  }
  return out;
}

function diamondPath(cx: number, cy: number, size: number): string {
  return `M ${cx} ${cy - size} L ${cx + size} ${cy} L ${cx} ${cy + size} L ${cx - size} ${cy} Z`;
}

export function TimelineRibbon({ entity }: { entity: EntityPayload }) {
  const events = collectEvents(entity);

  if (events.length === 0) {
    return (
      <div
        className="mx-[18px] my-6 border border-border-hairline bg-panel px-4 py-6 font-mono text-hairline"
        style={{ fontSize: "11px", letterSpacing: "0.04em" }}
        data-testid="timeline-ribbon-empty"
      >
        no dated events linked to this entity
      </div>
    );
  }

  const minMs = events[0].time;
  const maxMs = events[events.length - 1].time;
  // Pad the range so events at the edge aren't clipped; ensure non-zero span.
  const spanMs = Math.max(maxMs - minMs, 1000 * 60 * 60 * 24 * 30); // 30 days min
  const plotWidth = WIDTH - MARGIN_LEFT - MARGIN_RIGHT;

  const xFor = (t: number): number => {
    return MARGIN_LEFT + ((t - minMs) / spanMs) * plotWidth;
  };

  const ticks = yearTicks(minMs, maxMs);

  return (
    <section
      className="mx-[18px] my-6 border border-border-hairline bg-panel px-4 py-4"
      data-testid="timeline-ribbon"
    >
      <div
        className="mb-3 font-mono uppercase text-dim"
        style={{ fontSize: "10px", letterSpacing: "0.14em" }}
      >
        Timeline <span className="ml-2 text-hairline">{events.length}</span>
      </div>
      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        preserveAspectRatio="none"
        className="block w-full"
        style={{ height: `${HEIGHT}px` }}
      >
        {/* Axis line */}
        <line
          x1={MARGIN_LEFT}
          x2={WIDTH - MARGIN_RIGHT}
          y1={AXIS_Y}
          y2={AXIS_Y}
          stroke={palette.borderHairline}
          strokeWidth={1}
        />
        {/* Year ticks */}
        {ticks.map((ms) => {
          const x = xFor(ms);
          if (x < MARGIN_LEFT - 2 || x > WIDTH - MARGIN_RIGHT + 2) return null;
          const year = new Date(ms).getUTCFullYear();
          return (
            <g key={`tick-${year}`} data-testid="timeline-year-tick">
              <line
                x1={x}
                x2={x}
                y1={AXIS_Y - 4}
                y2={AXIS_Y + 4}
                stroke={palette.borderPrimary}
                strokeWidth={1}
              />
              <text
                x={x}
                y={AXIS_Y + 20}
                textAnchor="middle"
                fill={palette.hairlineText}
                style={{
                  fontFamily: "var(--font-vt323), ui-monospace, monospace",
                  fontSize: "14px",
                }}
              >
                {year}
              </text>
            </g>
          );
        })}
        {/* Event diamonds (wrapped in anchor for navigation) */}
        {events.map((e) => {
          const x = xFor(e.time);
          const color = colorForType(e.neighbor.type);
          return (
            <a
              key={e.neighbor.id}
              href={e.neighbor.route}
              data-testid="timeline-event"
            >
              <title>
                {e.neighbor.label} · {e.date}
              </title>
              <path
                d={diamondPath(x, AXIS_Y, DIAMOND_SIZE)}
                fill={color}
                stroke={color}
                strokeWidth={0.5}
                opacity={0.9}
              />
            </a>
          );
        })}
      </svg>
      {/* Accessible textual fallback (also makes the links testable in jsdom) */}
      <ul className="sr-only">
        {events.map((e) => (
          <li key={`sr-${e.neighbor.id}`}>
            <Link href={e.neighbor.route}>
              {e.neighbor.label} · {e.date}
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
