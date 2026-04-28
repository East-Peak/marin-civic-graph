"use client";

import { useEffect, useState } from "react";
import { ConstellationCanvas } from "@/lib/cosmograph-mount";
import type { ConstellationPayload } from "@/lib/constellation-types";

type LoadState =
  | { kind: "loading" }
  | { kind: "ready"; payload: ConstellationPayload }
  | { kind: "rebuilding"; message: string }
  | { kind: "error"; message: string };

export function ConstellationClient() {
  const [state, setState] = useState<LoadState>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const m = await fetch("/api/constellation-manifest", { credentials: "same-origin" });
        if (m.status === 503) {
          setState({ kind: "rebuilding", message: "Constellation is rebuilding…" });
          return;
        }
        if (!m.ok) {
          setState({ kind: "error", message: `manifest ${m.status}` });
          return;
        }
        const manifest = await m.json();
        const b = await fetch(manifest.signed_url);
        if (!b.ok) {
          setState({ kind: "error", message: `blob ${b.status}` });
          return;
        }
        const payload = (await b.json()) as ConstellationPayload;
        if (!cancelled) setState({ kind: "ready", payload });
      } catch (e) {
        if (!cancelled) setState({ kind: "error", message: String(e) });
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  if (state.kind === "loading") {
    return <div className="p-6 text-dim">Loading constellation…</div>;
  }
  if (state.kind === "rebuilding") {
    return <div className="p-6 text-dim">{state.message}</div>;
  }
  if (state.kind === "error") {
    return <div className="p-6 text-[#f2b441]">Constellation error: {state.message}</div>;
  }
  return (
    <div className="h-[calc(100vh-100px)] w-full">
      <ConstellationCanvas
        nodes={state.payload.nodes}
        edges={state.payload.edges}
        spritesA={null}
        spritesB={null}
        onNodeClick={(id) => console.log("clicked", id)}
      />
    </div>
  );
}
