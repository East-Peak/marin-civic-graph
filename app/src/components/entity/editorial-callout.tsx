// Optional Plex Serif italic blurb. Per spec §7.1 item 9 + §2.3.
// Renders `entity.properties.editorial_note` (or `editorial_blurb` as a
// fallback — the ingestion contract hasn't locked the property name yet).
// Returns null when no note exists.

import type { EntityPayload } from "@/lib/server/entity-loader";

function pickNote(props: Record<string, unknown>): string | null {
  const candidates = [props.editorial_note, props.editorial_blurb, props.editorial];
  for (const c of candidates) {
    if (typeof c === "string" && c.length > 0) return c;
  }
  return null;
}

export function EditorialCallout({ entity }: { entity: EntityPayload }) {
  const note = pickNote(entity.properties);
  if (!note) return null;
  return (
    <aside
      className="mx-[18px] my-6 border-l-2 border-[#262b35] bg-panel px-5 py-4 text-dim"
      style={{
        fontFamily: "var(--font-plex-serif), ui-serif, serif",
        fontStyle: "italic",
        fontSize: "15px",
        lineHeight: 1.55,
      }}
      data-testid="editorial-callout"
    >
      {note}
    </aside>
  );
}
