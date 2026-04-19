// Tier 1 hero-stats strip — VT323 30px big-numeral block + Plex Mono
// 10px uppercase label below each value. Per spec §7.1 item 4.
//
// Values come from heroStatsForEntity (entity-facts.ts). Missing props render
// as em-dash; Tier 2 types return an empty list and this component returns
// null so the composer's conditional wrapper collapses cleanly.

import type { EntityPayload } from "@/lib/server/entity-loader";
import { heroStatsForEntity } from "@/lib/server/entity-facts";

export function HeroStats({ entity }: { entity: EntityPayload }) {
  const stats = heroStatsForEntity(entity.type, entity.properties);
  if (stats.length === 0) return null;

  return (
    <div
      className="mx-[18px] mt-3 flex flex-wrap items-baseline gap-x-8 gap-y-3"
      data-testid="hero-stats"
    >
      {stats.map((stat) => (
        <div key={stat.label} className="flex flex-col">
          <span
            className="text-[#f2c77a]"
            style={{
              fontFamily: "var(--font-vt323)",
              fontSize: "30px",
              lineHeight: 1,
              textShadow: "0 0 6px rgba(242,199,122,0.4)",
            }}
            data-testid="hero-stat-value"
          >
            {stat.value}
          </span>
          <span
            className="mt-1 font-mono uppercase text-hairline"
            style={{ fontSize: "10px", letterSpacing: "0.12em" }}
            data-testid="hero-stat-label"
          >
            {stat.label}
          </span>
        </div>
      ))}
    </div>
  );
}
