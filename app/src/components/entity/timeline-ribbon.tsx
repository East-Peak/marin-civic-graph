// Tier 1 horizontal temporal ribbon per spec §7.1 item 8 + §5.4.
//
// Server component (no client hooks). Each neighbor arrives from the loader
// with a real `event_date` (null for durable types or missing properties);
// the focus entity contributes its own `focus_event_date` if dated.
//
// Batch F is read-only — no slider, no filter interaction. That comes later
// once we wire the explorer time slider against the same temporal contract.

import Link from "next/link";
import { palette } from "@/lib/palette";
import type { EntityPayload, Neighbor } from "@/lib/server/entity-loader";
import { colorClassForType } from "@/components/graph/obsidian-style";

type DatedEvent = {
  /** null ⇒ the focus entity itself (anchors the ribbon). */
  neighbor: Neighbor | null;
  label: string;
  route: string | null;
  type: string;
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
  // Focus's own effective date (anchors the ribbon when the focus itself is
  // a dated event — Meeting, Decision, Filing, …). Never fabricated from id.
  if (entity.focus_event_date) {
    const t = parseDate(entity.focus_event_date);
    if (t != null) {
      out.push({
        neighbor: null,
        label: entity.label,
        route: null,
        type: entity.type,
        date: entity.focus_event_date,
        time: t,
      });
    }
  }
  for (const n of entity.neighbors) {
    if (!n.event_date) continue;
    const t = parseDate(n.event_date);
    if (t == null) continue;
    out.push({
      neighbor: n,
      label: n.label,
      route: n.route,
      type: n.type,
      date: n.event_date,
      time: t,
    });
  }
  return out.sort((a, b) => a.time - b.time);
}

function yearTicks(minMs: number, maxMs: number): number[] {
  const first = new Date(minMs).getUTCFullYear();
  const last = new Date(maxMs).getUTCFullYear();
  const out: number[] = [];
  // Include both the event year's Jan 1 AND the following Jan 1 so single-
  // event ribbons still show a year label within the plot window.
  for (let y = first; y <= last + 1; y++) {
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

  const eventMin = events[0].time;
  const eventMax = events[events.length - 1].time;
  // Snap the plot range to Jan 1 of the earliest event year and Jan 1 of the
  // year *after* the latest event so at least two year-boundary ticks are
  // always visible inside the plot window.
  const firstYear = new Date(eventMin).getUTCFullYear();
  const lastYear = new Date(eventMax).getUTCFullYear();
  const minMs = Date.UTC(firstYear, 0, 1);
  const maxMs = Date.UTC(lastYear + 1, 0, 1);
  const spanMs = Math.max(maxMs - minMs, 1000 * 60 * 60 * 24 * 30);
  const plotWidth = WIDTH - MARGIN_LEFT - MARGIN_RIGHT;

  const xFor = (t: number): number => {
    return MARGIN_LEFT + ((t - minMs) / spanMs) * plotWidth;
  };

  const ticks = yearTicks(eventMin, eventMax);

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
        {/* Event diamonds (wrapped in anchor for navigation). The focus
            entity itself may be a dated event — its diamond is un-linked. */}
        {events.map((e) => {
          const x = xFor(e.time);
          const color = colorForType(e.type);
          const key = e.neighbor ? e.neighbor.id : `focus-${e.date}`;
          const diamond = (
            <>
              <title>
                {e.label} · {e.date}
              </title>
              <path
                d={diamondPath(x, AXIS_Y, DIAMOND_SIZE)}
                fill={color}
                stroke={color}
                strokeWidth={0.5}
                opacity={0.9}
              />
            </>
          );
          if (e.route) {
            return (
              <a key={key} href={e.route} data-testid="timeline-event">
                {diamond}
              </a>
            );
          }
          return (
            <g key={key} data-testid="timeline-event-focus">
              {diamond}
            </g>
          );
        })}
      </svg>
      {/* Accessible textual fallback (also makes the links testable in jsdom) */}
      <ul className="sr-only">
        {events.map((e) => {
          const key = e.neighbor ? `sr-${e.neighbor.id}` : `sr-focus-${e.date}`;
          return (
            <li key={key}>
              {e.route ? (
                <Link href={e.route}>
                  {e.label} · {e.date}
                </Link>
              ) : (
                <span>
                  {e.label} · {e.date}
                </span>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
