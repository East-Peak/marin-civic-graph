# Open Marin Frontend — Plan 4a: Palette + Shortcuts + /about

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans.

**Scope note:** Plan 4 in the plan hierarchy was originally "palette + shortcuts + auth + deploy + /about." This plan (**4a**) covers the three **safe** surfaces only: command palette, keyboard shortcuts, /about page. Auth + Vercel deploy are separated into a future **Plan 4b** because they affect production — Stuart reviews 4a first, then decides whether to proceed to 4b or reshape.

**Goal:** Ship the power-user keyboard surface and the methodology page. After 4a: `⌘K` opens a command palette that searches + jumps to any entity; `/` focuses search on non-homepage routes; `g h / g g / g d / g c` chord shortcuts jump between surfaces; `?` shows a keyboard-shortcut overlay; `/about` explains the project.

**Architecture:**
- Command palette is a client component using the existing `/api/search` backend (same corpus as homepage search + search results page — spec §3.3 single-source-of-truth rule).
- Keyboard shortcuts live in a shared `useKeyboardShortcuts()` hook mounted in the root layout.
- Shortcut help overlay is a small dialog-style component toggled by `?`.
- `/about` is a static Markdown-flavored page — no Cypher, just prose.

**Tech stack:** no new packages needed.

**Spec:** `docs/specs/2026-04-19-open-marin-frontend-design.md` §4.3 (command palette), §4.4 (keyboard shortcuts), §11 (out of scope reminders).

**Prerequisites:** Plans 1 + 2 + 3 landed on `main` at `bf3fc80`. All APIs exist.

---

## File structure (new or modified)

```
app/src/
  app/
    about/page.tsx                        MODIFY — replace ComingSoon with real content
    layout.tsx                            MODIFY — mount KeyboardShortcutsProvider + CommandPalette
  components/
    palette/
      command-palette.tsx                 NEW — ⌘K modal
      palette-results.tsx                 NEW — live search results inside palette
    shortcuts/
      keyboard-shortcuts-provider.tsx     NEW — global hotkey listener (client wrapper)
      shortcuts-overlay.tsx               NEW — `?` help dialog
  lib/
    shortcuts/
      chord-machine.ts                    NEW — `g h` / `g g` / `g d` / `g c` chord state machine
  tests/
    components/
      palette/command-palette.test.tsx    NEW
      palette/palette-results.test.tsx    NEW
      shortcuts/keyboard-shortcuts-provider.test.tsx  NEW
      shortcuts/shortcuts-overlay.test.tsx            NEW
    lib/
      shortcuts/chord-machine.test.ts     NEW
```

---

## Conventions (same as Plans 1-3)

- Push directly to `main`.
- Never `git add -A`.
- Ambient dirty state in `data/extracted/*`, `data/raw/*`, `data/normalized/*`, `data/projected/graph-v2/*`, `docs/specs/2026-04-14-marin-civic-graph-v1-design.md` — untouched.
- TDD for chord machine + palette search; pragmatic for UI composition.
- `npm run verify` green before each commit.

---

## Task 1: Chord state machine (TDD)

**Files:**
- Create: `app/src/lib/shortcuts/chord-machine.ts`
- Create: `app/src/tests/lib/shortcuts/chord-machine.test.ts`

Spec §4.4 defines these global chords:

| Key sequence | Action |
|---|---|
| `⌘K` | Open palette |
| `/` | Focus search |
| `g h` | Navigate to Home |
| `g g` | Navigate to Graph |
| `g d` | Navigate to Data |
| `g c` | Navigate to Chat |
| `?` | Shortcut overlay |
| `esc` | Close modal / clear focus |

The chord machine needs to:
- Track a buffered first-key (`g`) with a timeout (say 800ms); second key (`h`/`g`/`d`/`c`) completes the chord.
- Ignore keystrokes when focus is inside a text input (so `g` inside a search field doesn't trigger nav).
- `⌘K` / `/` / `?` / `esc` are single-key (plus meta for ⌘K). No chord buffering.

**Signature:**

```typescript
export type ChordEvent =
  | { kind: "palette" }
  | { kind: "focus-search" }
  | { kind: "navigate"; to: "/" | "/graph" | "/data" | "/chat" }
  | { kind: "overlay"; open: boolean }
  | { kind: "escape" };

export type KeyState = {
  buffer: string | null;       // first key of a chord, or null
  buffer_at: number;           // ms since epoch when buffered
};

export function initState(): KeyState;
export function handleKey(state: KeyState, e: { key: string; meta: boolean; ctrl: boolean; target: EventTarget | null }, nowMs: number): { state: KeyState; events: ChordEvent[] };
```

- `handleKey` is pure — takes current state + synthetic event + current time; returns next state + emitted events.
- Chord expiry: if `nowMs - buffer_at > 800`, drop the buffer before processing the new key.
- Target check: if target is an `<input>`, `<textarea>`, or `[contenteditable]`, only `esc` still emits an event.

Tests:
- `⌘K` emits `palette`
- `/` emits `focus-search`
- `g` alone buffers, no events
- `g` then `h` emits `navigate` to `/`
- `g` then `g` emits `navigate` to `/graph`
- `g` then (900ms pause) then `h` — treats `h` as standalone (no event; `h` is not a shortcut)
- `/` inside an input focus → no event (lets the input handle it)
- `esc` inside an input → emits `escape` (to let the app dismiss modals)
- `?` emits `overlay: {open: true}`

Commit: `add chord-machine: keyboard shortcut state (§4.4)`

## Task 2: KeyboardShortcutsProvider

**Files:**
- Create: `app/src/components/shortcuts/keyboard-shortcuts-provider.tsx`
- Create: `app/src/tests/components/shortcuts/keyboard-shortcuts-provider.test.tsx`

Client component. Mounts a global `keydown` listener on window. Dispatches events:
- `palette` → show a shared PaletteContext's `open` state
- `focus-search` → programmatic focus of any visible `input[name="q"]` (the prompt-search on home) OR navigate to `/search?q=` on other routes
- `navigate` → `router.push(to)`
- `overlay` → show/hide ShortcutsOverlay
- `escape` → broadcast via a context or custom event; palette/overlay listen

Props:
```tsx
type Props = { children: React.ReactNode };
```

Internal state: chord machine + open flags for palette + overlay.

Provides context:
```typescript
export const PaletteContext = createContext<{
  open: boolean;
  setOpen: (b: boolean) => void;
}>({ open: false, setOpen: () => {} });
```

Mounted in root layout wrapping the tree.

Tests verify:
- `⌘K` keydown opens palette (via context)
- `g g` keydown calls router.push("/graph")
- `?` opens overlay
- Typing in a mocked input focus doesn't trigger g-chords

## Task 3: CommandPalette component

**Files:**
- Create: `app/src/components/palette/command-palette.tsx`
- Create: `app/src/components/palette/palette-results.tsx`
- Create: `app/src/tests/components/palette/command-palette.test.tsx`
- Create: `app/src/tests/components/palette/palette-results.test.tsx`

Spec §4.3 palette structure:
1. **Results** — up to 20 from `/api/search?q=&include_records=false`. Ranked per spec §3.3.
2. **Recent entities** — last 10 viewed (from sessionStorage `openmarin_recent_entities`, appended when entity pages mount).
3. **Quick jumps** — `go home`, `go graph`, `go data`, `go chat`, `go about`.

**UI:**
- Centered modal overlay. Dark panel, ~600px wide, ~400px tall.
- Prompt-style input at top: `>` chevron + VT323 cursor.
- Below: results (virtualized scroll if needed; for v1 just overflow-scroll).
- Keyboard navigation: ↑/↓ to move selection, ↵ to navigate, esc to close.

**Behavior:**
- Palette opens empty with Recent Entities + Quick Jumps shown.
- As user types, fetch `/api/search?q=...` (debounced 150ms) and replace Recent+Quick with results (keep Quick Jumps at the bottom if query is empty).
- Each result row shows type badge + search_label + key_fact.
- Return navigates to the selected row's route.

**Records toggle:** small checkbox at the bottom of the palette — `include records`. Default off. When on, re-fetches with `include_records=true`.

**Keyboard:**
- Arrow Up/Down navigates within result list
- Enter selects
- Esc closes (PaletteContext.setOpen(false))
- `cmd+K` inside palette also closes

Tests:
- Empty query shows Recent + Quick Jumps
- Typing fetches /api/search (mocked) and renders results
- ↑/↓ moves selection highlight
- ↵ calls router.push
- Records toggle calls include_records=true

Commit tasks 2+3 together: `add command palette ⌘K + keyboard shortcuts provider (§4.3, §4.4)`.

## Task 4: ShortcutsOverlay

**Files:**
- Create: `app/src/components/shortcuts/shortcuts-overlay.tsx`

Opened by `?` key. Centered dialog listing all shortcuts in a Plex Mono table:

```
⌘K        Open palette
/         Focus search
g h       Home
g g       Graph
g d       Data
g c       Chat
?         Show this overlay
esc       Close modal / clear focus
```

Styled consistent with other dialogs. Escape closes.

No tests needed — purely presentational.

## Task 5: Mount in root layout

**Files:**
- Modify: `app/src/app/layout.tsx`

Wrap `{children}` in `<KeyboardShortcutsProvider>`. Both palette and overlay render as portals from inside the provider.

Also: track recently-viewed entities. Add a small `RecentEntityTracker` client component that mounts inside every entity page (modify `/{type}/{slug}/page.tsx` to include it). On mount, it appends the current entity to sessionStorage `openmarin_recent_entities` (LIFO, max 10).

Actually simpler: in entity-page.tsx (the composer), add a `<RecentEntityTracker entity={entity} />` line inside a `useEffect`. Client component that writes to sessionStorage on mount.

Commit: `mount keyboard shortcuts + palette + recent-entity tracker in layout`.

## Task 6: `/about/page.tsx`

**Files:**
- Modify: `app/src/app/about/page.tsx` (currently ComingSoon)

Static content. Sections:

1. **What Open Marin is** — 1-paragraph product description from the spec's Section 1.
2. **What's in the graph** — bullet list of the 21 node types + current counts (hit `/api/catalog`).
3. **Methodology** — paragraph on primary-source discipline per the spec's Section 1 thesis.
4. **Jurisdictions** — list of the 11 covered + coverage notes.
5. **Built with** — tech stack credits.
6. **Credits** — Stuart Watson (East Peak Advisors); built with Claude (model IDs, session provenance).

No tests. Server component that fetches catalog counts. Plex Sans for body, VT323 for section headers.

Commit: `add /about static page with methodology + catalog counts`.

## Task 7: Smoke test

Start dev server:
```bash
cd app && PORT=3100 npm run dev &
sleep 3
```

Open:
- http://localhost:3100/ — press `⌘K`, palette opens; type "kate colin", results appear
- Press `esc` to close palette
- Press `?` — shortcuts overlay appears
- Press `g g` — navigates to /graph
- Press `g d` — navigates to /data
- Visit `/about` — renders methodology page with catalog counts

Commit: none — verification only.

## Verification before reporting

1. `cd app && npm run verify` — green (~15-20 new tests)
2. `cd app && npm run build` — green
3. Manual smoke: palette opens, shortcuts fire, /about renders

## Plan 4a completion checklist

- [ ] All 7 tasks committed.
- [ ] Palette opens on ⌘K from any page.
- [ ] `/` focuses search on homepage; navigates to `/search?q=` on other routes.
- [ ] `g h / g g / g d / g c` chord shortcuts navigate.
- [ ] `?` toggles overlay.
- [ ] `/about` renders real content.
- [ ] Recent entities persist across palette openings.

Plan 4b (separate plan, Stuart review gate): invite-only auth, Vercel deploy polish.

Plan 5 (deferred per spec §9): AI chat.
