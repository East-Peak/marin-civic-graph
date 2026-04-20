import { describe, it, expect } from "vitest";
import { initState, handleKey } from "@/lib/shortcuts/chord-machine";

const t0 = 1_700_000_000_000;

function keyEvent(
  key: string,
  opts: { meta?: boolean; ctrl?: boolean; target?: EventTarget | null } = {},
) {
  return {
    key,
    meta: opts.meta ?? false,
    ctrl: opts.ctrl ?? false,
    target: opts.target ?? null,
  };
}

function makeInput(): HTMLInputElement {
  return document.createElement("input");
}

function makeTextarea(): HTMLTextAreaElement {
  return document.createElement("textarea");
}

function makeContentEditable(): HTMLDivElement {
  const el = document.createElement("div");
  el.setAttribute("contenteditable", "true");
  return el;
}

describe("chord-machine", () => {
  it("meta+K emits palette", () => {
    const { state, events } = handleKey(initState(), keyEvent("k", { meta: true }), t0);
    expect(events).toEqual([{ kind: "palette" }]);
    expect(state.buffer).toBeNull();
  });

  it("ctrl+K emits palette", () => {
    const { state, events } = handleKey(initState(), keyEvent("k", { ctrl: true }), t0);
    expect(events).toEqual([{ kind: "palette" }]);
    expect(state.buffer).toBeNull();
  });

  it("/ emits focus-search", () => {
    const { state, events } = handleKey(initState(), keyEvent("/"), t0);
    expect(events).toEqual([{ kind: "focus-search" }]);
    expect(state.buffer).toBeNull();
  });

  it("g alone buffers, no events", () => {
    const { state, events } = handleKey(initState(), keyEvent("g"), t0);
    expect(events).toEqual([]);
    expect(state.buffer).toBe("g");
    expect(state.buffer_at).toBe(t0);
  });

  it("g then h navigates to /", () => {
    const first = handleKey(initState(), keyEvent("g"), t0);
    const second = handleKey(first.state, keyEvent("h"), t0 + 100);
    expect(second.events).toEqual([{ kind: "navigate", to: "/" }]);
    expect(second.state.buffer).toBeNull();
  });

  it("g then g navigates to /graph", () => {
    const first = handleKey(initState(), keyEvent("g"), t0);
    const second = handleKey(first.state, keyEvent("g"), t0 + 100);
    expect(second.events).toEqual([{ kind: "navigate", to: "/graph" }]);
    expect(second.state.buffer).toBeNull();
  });

  it("g then d navigates to /data", () => {
    const first = handleKey(initState(), keyEvent("g"), t0);
    const second = handleKey(first.state, keyEvent("d"), t0 + 100);
    expect(second.events).toEqual([{ kind: "navigate", to: "/data" }]);
    expect(second.state.buffer).toBeNull();
  });

  it("g then c navigates to /chat", () => {
    const first = handleKey(initState(), keyEvent("g"), t0);
    const second = handleKey(first.state, keyEvent("c"), t0 + 100);
    expect(second.events).toEqual([{ kind: "navigate", to: "/chat" }]);
    expect(second.state.buffer).toBeNull();
  });

  it("g then 900ms pause then h — buffer expired, no events", () => {
    const first = handleKey(initState(), keyEvent("g"), t0);
    const second = handleKey(first.state, keyEvent("h"), t0 + 900);
    expect(second.events).toEqual([]);
    expect(second.state.buffer).toBeNull();
  });

  it("/ inside an <input> target emits nothing", () => {
    const { state, events } = handleKey(initState(), keyEvent("/", { target: makeInput() }), t0);
    expect(events).toEqual([]);
    expect(state.buffer).toBeNull();
  });

  it("g inside an <input> target — no event, no buffering", () => {
    const { state, events } = handleKey(initState(), keyEvent("g", { target: makeInput() }), t0);
    expect(events).toEqual([]);
    expect(state.buffer).toBeNull();
  });

  it("esc inside an <input> target still emits escape", () => {
    const { state, events } = handleKey(
      initState(),
      keyEvent("Escape", { target: makeInput() }),
      t0,
    );
    expect(events).toEqual([{ kind: "escape" }]);
    expect(state.buffer).toBeNull();
  });

  it("? emits overlay open", () => {
    const { state, events } = handleKey(initState(), keyEvent("?"), t0);
    expect(events).toEqual([{ kind: "overlay", open: true }]);
    expect(state.buffer).toBeNull();
  });

  it("Escape (not in input) emits escape", () => {
    const { state, events } = handleKey(initState(), keyEvent("Escape"), t0);
    expect(events).toEqual([{ kind: "escape" }]);
    expect(state.buffer).toBeNull();
  });

  it("unknown key with no buffer — no event, no state change", () => {
    const start = initState();
    const { state, events } = handleKey(start, keyEvent("x"), t0);
    expect(events).toEqual([]);
    expect(state).toEqual(start);
  });

  it("/ inside a <textarea> target emits nothing", () => {
    const { events } = handleKey(initState(), keyEvent("/", { target: makeTextarea() }), t0);
    expect(events).toEqual([]);
  });

  it("/ inside a contenteditable target emits nothing", () => {
    const { events } = handleKey(
      initState(),
      keyEvent("/", { target: makeContentEditable() }),
      t0,
    );
    expect(events).toEqual([]);
  });
});
