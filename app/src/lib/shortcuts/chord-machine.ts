export type ChordEvent =
  | { kind: "palette" }
  | { kind: "focus-search" }
  | { kind: "navigate"; to: "/" | "/graph" | "/data" | "/chat" }
  | { kind: "overlay"; open: boolean }
  | { kind: "escape" };

export type KeyState = {
  buffer: string | null;
  buffer_at: number;
};

const CHORD_WINDOW_MS = 800;

const CHORD_NAV: Record<string, "/" | "/graph" | "/data" | "/chat"> = {
  h: "/",
  g: "/graph",
  d: "/data",
  c: "/chat",
};

export function initState(): KeyState {
  return { buffer: null, buffer_at: 0 };
}

function isTextInput(target: EventTarget | null): boolean {
  if (!target || !(target instanceof Element)) return false;
  const tag = target.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA") return true;
  if (target.getAttribute("contenteditable") === "true") return true;
  return false;
}

export function handleKey(
  state: KeyState,
  e: { key: string; meta: boolean; ctrl: boolean; target: EventTarget | null },
  nowMs: number,
): { state: KeyState; events: ChordEvent[] } {
  // Escape always emits, even inside text inputs (exit focus).
  if (e.key === "Escape") {
    return { state: initState(), events: [{ kind: "escape" }] };
  }

  // Inside a text input: swallow everything else (incl. buffered chord leader).
  if (isTextInput(e.target)) {
    return { state, events: [] };
  }

  // ⌘K / Ctrl+K — palette.
  if ((e.meta || e.ctrl) && (e.key === "k" || e.key === "K")) {
    return { state: initState(), events: [{ kind: "palette" }] };
  }

  // Drop an expired buffer before processing this key.
  let working: KeyState = state;
  if (working.buffer !== null && nowMs - working.buffer_at > CHORD_WINDOW_MS) {
    working = initState();
  }

  // Complete an in-flight chord if the leader is buffered.
  if (working.buffer === "g") {
    const to = CHORD_NAV[e.key];
    if (to) {
      return { state: initState(), events: [{ kind: "navigate", to } satisfies ChordEvent] };
    }
    // Second key doesn't complete — drop buffer, fall through to normal handling.
    working = initState();
  }

  // Single-key shortcuts that do not require modifiers.
  if (e.key === "/") {
    return { state: initState(), events: [{ kind: "focus-search" }] };
  }

  if (e.key === "?") {
    return { state: initState(), events: [{ kind: "overlay", open: true }] };
  }

  // Chord leader.
  if (e.key === "g") {
    return { state: { buffer: "g", buffer_at: nowMs }, events: [] };
  }

  return { state: working, events: [] };
}
