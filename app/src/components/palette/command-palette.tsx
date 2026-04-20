"use client";

// Command palette (spec §4.3): opened via ⌘K, consumed via PaletteContext
// so the provider doesn't need to prop-drill.
//
// Behaviour:
//   - Empty query: Recent Entities (sessionStorage, LIFO max 10) +
//     Quick Jumps. Quick Jumps are always present.
//   - Non-empty query: 150ms-debounced /api/search, Quick Jumps drop out.
//   - Arrow Up / Down move the selection; Enter routes; Esc closes; ⌘K
//     inside the palette closes (toggle).
//   - Records checkbox at the bottom refetches with include_records=true.

import { useContext, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { PaletteContext } from "@/components/shortcuts/keyboard-shortcuts-provider";
import {
  PaletteResults,
  type PaletteResultItem,
} from "@/components/palette/palette-results";
import { urlSegmentForType } from "@/lib/type-display";

const SEARCH_DEBOUNCE_MS = 150;
const RECENT_KEY = "openmarin_recent_entities";

type RecentEntity = {
  id: string;
  type: string;
  label: string;
};

type ApiResult = {
  id: string;
  type: string;
  search_label: string;
  key_fact: string | null;
  search_rank: number;
};

function readRecents(): RecentEntity[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = sessionStorage.getItem(RECENT_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.slice(0, 10) as RecentEntity[];
  } catch {
    return [];
  }
}

const QUICK_JUMPS: PaletteResultItem[] = [
  {
    kind: "quickjump",
    id: "qj:home",
    type: "jump",
    label: "go home",
    key_fact: "/",
    route: "/",
  },
  {
    kind: "quickjump",
    id: "qj:graph",
    type: "jump",
    label: "go graph",
    key_fact: "/graph",
    route: "/graph",
  },
  {
    kind: "quickjump",
    id: "qj:data",
    type: "jump",
    label: "go data",
    key_fact: "/data",
    route: "/data",
  },
  {
    kind: "quickjump",
    id: "qj:chat",
    type: "jump",
    label: "go chat",
    key_fact: "/chat",
    route: "/chat",
  },
  {
    kind: "quickjump",
    id: "qj:about",
    type: "jump",
    label: "go about",
    key_fact: "/about",
    route: "/about",
  },
];

function recentsAsItems(rs: RecentEntity[]): PaletteResultItem[] {
  return rs.map((r) => {
    // Best-effort: type-display handles all known node types; if we get a
    // stray string we fall back to the type itself so the route is still
    // clickable and visible.
    let segment: string;
    try {
      segment = urlSegmentForType(r.type as Parameters<typeof urlSegmentForType>[0]);
    } catch {
      segment = r.type.toLowerCase();
    }
    const slug = r.id.includes("-") ? r.id.slice(r.id.indexOf("-") + 1) : r.id;
    return {
      kind: "recent" as const,
      id: r.id,
      type: r.type,
      label: r.label,
      key_fact: null,
      route: `/${segment}/${slug}`,
    };
  });
}

function apiResultsAsItems(results: ApiResult[]): PaletteResultItem[] {
  return results.map((r) => {
    let segment: string;
    try {
      segment = urlSegmentForType(r.type as Parameters<typeof urlSegmentForType>[0]);
    } catch {
      segment = r.type.toLowerCase();
    }
    const slug = r.id.includes("-") ? r.id.slice(r.id.indexOf("-") + 1) : r.id;
    return {
      kind: "result" as const,
      id: r.id,
      type: r.type,
      label: r.search_label,
      key_fact: r.key_fact,
      route: `/${segment}/${slug}`,
    };
  });
}

export function CommandPalette() {
  const { open } = useContext(PaletteContext);
  // The inner panel owns the transient input/results state. Remounting it
  // on every open transition (via `key`) gives us a free state reset without
  // an effect that calls setState on the close side — the React 19 lint
  // rejects setState-in-effect.
  return open ? <PalettePanel key="palette-open" /> : null;
}

function PalettePanel() {
  const { setOpen } = useContext(PaletteContext);
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);

  const [query, setQuery] = useState("");
  const [includeRecords, setIncludeRecords] = useState(false);
  const [results, setResults] = useState<ApiResult[]>([]);
  const [selectedIndex, setSelectedIndex] = useState(0);

  // Focus the input on mount (open transition).
  useEffect(() => {
    const id = requestAnimationFrame(() => inputRef.current?.focus());
    return () => cancelAnimationFrame(id);
  }, []);

  // Debounced search effect. The setState calls live inside the timer
  // callback (async path), not the effect body — that's the pattern the
  // React 19 lint allows.
  const q = query.trim();
  useEffect(() => {
    if (!q) return;
    const t = window.setTimeout(async () => {
      try {
        const url = `/api/search?q=${encodeURIComponent(q)}&include_records=${
          includeRecords ? "true" : "false"
        }`;
        const res = await fetch(url);
        if (!res.ok) return;
        const json = (await res.json()) as { results: ApiResult[] };
        setResults(json.results ?? []);
        setSelectedIndex(0);
      } catch {
        /* palette tolerates transient search failures */
      }
    }, SEARCH_DEBOUNCE_MS);
    return () => window.clearTimeout(t);
  }, [q, includeRecords]);

  // When the query clears (e.g. user deletes text), drop stale results
  // without using an effect — derive an empty list in the memo instead.
  const items: PaletteResultItem[] = useMemo(() => {
    if (q.length === 0) {
      const recents = recentsAsItems(readRecents());
      return [...recents, ...QUICK_JUMPS];
    }
    return apiResultsAsItems(results);
  }, [q, results]);

  function activate(item: PaletteResultItem) {
    router.push(item.route);
    setOpen(false);
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    // During IME composition the keystroke belongs to the composer — do not
    // steal Enter (commit) / Escape (cancel) / arrow keys (candidate nav).
    if (e.nativeEvent.isComposing) {
      return;
    }
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setSelectedIndex((i) => Math.min(items.length - 1, i + 1));
      return;
    }
    if (e.key === "ArrowUp") {
      e.preventDefault();
      setSelectedIndex((i) => Math.max(0, i - 1));
      return;
    }
    if (e.key === "Enter") {
      e.preventDefault();
      const item = items[selectedIndex];
      if (item) activate(item);
      return;
    }
    if (e.key === "Escape") {
      e.preventDefault();
      setOpen(false);
      return;
    }
    if ((e.metaKey || e.ctrlKey) && (e.key === "k" || e.key === "K")) {
      // ⌘K inside the palette closes it — the global listener already
      // toggles, but we stop propagation so we don't double-toggle back open.
      e.preventDefault();
      e.stopPropagation();
      setOpen(false);
      return;
    }
  }

  return (
    <div
      data-testid="command-palette"
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/60 pt-[12vh]"
      onClick={() => setOpen(false)}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="w-[600px] max-w-[95vw] rounded border border-border-primary bg-panel font-mono text-xs text-body shadow-xl"
      >
        <div className="flex items-center gap-2 border-b border-border-hairline px-3 py-2">
          <span
            className="text-[#a4e8bf]"
            style={{
              fontFamily: "var(--font-vt323)",
              fontSize: "16px",
              letterSpacing: "0.08em",
            }}
          >
            &gt;
          </span>
          <input
            ref={inputRef}
            role="combobox"
            aria-expanded="true"
            aria-controls="palette-listbox"
            aria-label="Command palette"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="jump to anything — people, projects, decisions, records…"
            className="flex-1 bg-transparent text-body placeholder:text-hairline focus:outline-none"
          />
        </div>

        <div id="palette-listbox">
          <PaletteResults
            items={items}
            selectedIndex={selectedIndex}
            onSelect={activate}
          />
        </div>

        <div className="flex items-center justify-between border-t border-border-hairline px-3 py-2 text-[11px] text-dim">
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              aria-label="include records"
              checked={includeRecords}
              onChange={(e) => setIncludeRecords(e.target.checked)}
              className="accent-[#a4e8bf]"
            />
            <span>include records</span>
          </label>
          <span className="text-hairline">
            ↑↓ navigate · ↵ open · esc close
          </span>
        </div>
      </div>
    </div>
  );
}
