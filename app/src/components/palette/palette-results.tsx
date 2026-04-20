"use client";

// Rows for the ⌘K command palette (spec §4.3). One of three kinds:
//   - "result":   live /api/search hit
//   - "recent":   entity the user visited this session (sessionStorage)
//   - "quickjump": synthetic route bookmark (home/graph/data/chat/about)
//
// Purely presentational — selection index and keyboard wiring live in the
// parent CommandPalette component.

export type PaletteResultItem = {
  kind: "result" | "recent" | "quickjump";
  id: string;
  type: string;
  label: string;
  key_fact?: string | null;
  route: string;
};

export type PaletteResultsProps = {
  items: PaletteResultItem[];
  selectedIndex: number;
  onSelect: (item: PaletteResultItem) => void;
  // The combobox input uses aria-controls/aria-activedescendant to point at
  // this listbox and its selected row; the parent owns the id contract.
  listboxId?: string;
};

function badgeLabel(item: PaletteResultItem): string {
  if (item.kind === "quickjump") return "JUMP";
  return item.type.toUpperCase();
}

export function PaletteResults({
  items,
  selectedIndex,
  onSelect,
  listboxId,
}: PaletteResultsProps) {
  return (
    <ul
      id={listboxId}
      role="listbox"
      aria-label="palette results"
      className="max-h-[280px] overflow-auto"
    >
      {items.map((item, i) => {
        const selected = i === selectedIndex;
        return (
          <li
            key={`${item.kind}:${item.id}`}
            id={`palette-item-${i}`}
            role="option"
            aria-selected={selected}
            data-testid="palette-row"
            onClick={() => onSelect(item)}
            className={
              "cursor-pointer px-3 py-2 font-mono text-[12px] " +
              (selected
                ? "bg-surface ring-1 ring-[#a4e8bf] text-body"
                : "text-body hover:bg-surface")
            }
          >
            <div className="flex items-baseline gap-3">
              <span className="inline-block w-[64px] shrink-0 text-[10px] uppercase tracking-[0.14em] text-hairline">
                {badgeLabel(item)}
              </span>
              <span className="flex-1 truncate">{item.label}</span>
            </div>
            {item.key_fact && (
              <div className="mt-0.5 pl-[76px] text-[11px] text-dim">
                {item.key_fact}
              </div>
            )}
          </li>
        );
      })}
    </ul>
  );
}
