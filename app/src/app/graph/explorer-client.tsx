"use client";

// Full-screen explorer workbench per spec §6.3.
//
// Renders a Cytoscape fcose canvas and the docked toolbar. Click-to-expand
// fires /api/expand; right-click opens a tiny context menu that calls the
// same endpoint with the current hop slider. Shift+click manages a pathfind
// selection (up to two). URL state round-trips through explorer-state.ts.
//
// Cytoscape is 100% client-side — the server wrapper (graph/page.tsx) only
// ships the serializable EntityPayload; Cytoscape is `new`'d up inside the
// effect below so Next's SSR pass never touches it.

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import cytoscape, {
  type Core,
  type ElementDefinition,
  type EventObject,
  type LayoutOptions,
  type NodeSingular,
} from "cytoscape";
import fcose from "cytoscape-fcose";

import { obsidianStylesheet } from "@/components/graph/obsidian-style";
import {
  colorClassForType,
  glowForRole,
  shapeForType,
  sizeForRole,
} from "@/components/graph/obsidian-style";
import { ExplorerToolbar } from "@/components/explorer/explorer-toolbar";
import {
  PathDialog,
  type HighlightPathArgs,
} from "@/components/explorer/path-dialog";
import { SaveViewMenu } from "@/components/explorer/save-view-menu";
import {
  OverflowIndicator,
  type OverflowItem,
} from "@/components/explorer/overflow-indicator";
import {
  autoEnableFiltersForFocus,
  edgeKey,
  mergeExpansion,
  parseUrlToState,
  stateToUrl,
  type EdgeLike,
  type ExplorerState,
} from "@/lib/explorer/explorer-state";
import type { EntityPayload } from "@/lib/server/entity-loader";
import type { NodeType } from "@/lib/type-display";

// Ensure fcose is registered once at module load time.
cytoscape.use(fcose);

// ---------------------------------------------------------------------------
// Local types
// ---------------------------------------------------------------------------

type NodeRow = {
  id: string;
  type: NodeType;
  label: string;
  route: string;
  ring: number;
  event_date?: string | null;
  role?: "focus" | "primary" | "secondary";
};

type EdgeRow = {
  source: string;
  target: string;
  type: string;
  style: "governance" | "money" | "legal-constrains";
};

type ExpandResponse = {
  nodes: NodeRow[];
  edges: EdgeRow[];
  new_count: number;
  cap: number;
};

// ---------------------------------------------------------------------------
// Helpers — EntityPayload / expand response → Cytoscape elements
// ---------------------------------------------------------------------------

function roleForRing(ring: number): "focus" | "primary" | "secondary" {
  if (ring === 0) return "focus";
  if (ring === 1) return "primary";
  return "secondary";
}

function nodeToElement(
  n: NodeRow,
  opts: { isFocus: boolean; showLabel: boolean } = { isFocus: false, showLabel: true },
): ElementDefinition {
  const role: "focus" | "primary" | "secondary" = opts.isFocus
    ? "focus"
    : roleForRing(n.ring);
  const colorClass = colorClassForType(n.type);
  const shape = shapeForType(n.type);
  const size = sizeForRole(role);
  const glow = glowForRole(role, colorClass);
  const visibleLabel =
    opts.showLabel && (role === "focus" || role === "primary") ? n.label : "";
  return {
    data: {
      id: n.id,
      visibleLabel,
      label: n.label,
      type: n.type,
      role,
      ring: role === "focus" ? 0 : n.ring,
      colorClass,
      shape: colorClass ? "circle" : shape,
      size: String(size),
      glowBlur: glow.blur,
      glowColor: glow.color,
      route: n.route,
      eventDate: n.event_date ?? "",
    },
  };
}

function edgeToElement(e: EdgeRow, i: number): ElementDefinition {
  return {
    data: {
      id: `e-${i}-${e.source}-${e.target}-${e.type}`,
      source: e.source,
      target: e.target,
      style: e.style,
      type: e.type,
    },
  };
}

function payloadToElements(payload: EntityPayload): ElementDefinition[] {
  const focus: NodeRow = {
    id: payload.id,
    type: payload.type,
    label: payload.label,
    route: "",
    ring: 0,
    event_date: payload.focus_event_date,
  };
  const nodes: ElementDefinition[] = [
    nodeToElement(focus, { isFocus: true, showLabel: true }),
    ...payload.neighbors.map((n) =>
      nodeToElement({
        id: n.id,
        type: n.type,
        label: n.label,
        route: n.route,
        ring: n.ring,
        event_date: n.event_date,
      }),
    ),
  ];
  const seen = new Set(nodes.map((n) => String(n.data.id)));
  const edges: ElementDefinition[] = payload.edges
    .filter((e) => seen.has(e.source) && seen.has(e.target))
    .map((e, i) => edgeToElement(e, i));
  return [...nodes, ...edges];
}

// fcose layout — reusable so the explorer can re-layout cleanly after node
// additions.
const fcoseLayout: LayoutOptions = {
  name: "fcose",
  quality: "proof",
  animate: true,
  animationDuration: 500,
  padding: 30,
  randomize: false,
} as unknown as LayoutOptions;

// ---------------------------------------------------------------------------
// Signature subgraph empty-state picks
// ---------------------------------------------------------------------------

type SubgraphManifest = {
  built_at?: string;
  subgraphs: {
    slug: string;
    display_name: string;
    focus_node_id: string;
  }[];
};

// ---------------------------------------------------------------------------
// Public component
// ---------------------------------------------------------------------------

export type ExplorerClientProps = {
  initial: EntityPayload | null;
  ingestAt: string | null;
};

export function ExplorerClient({ initial, ingestAt }: ExplorerClientProps) {
  const router = useRouter();

  // Ingest defaults when not available — the time slider must still render
  // something. Fall back to today.
  const effectiveIngestAt =
    ingestAt ?? new Date().toISOString().slice(0, 19) + "Z";

  // Build initial ExplorerState — URL first, then auto-enable focus-type
  // waivers per §6.3. Wrapped in useState initializer so we only compute once.
  const [state, setState] = useState<ExplorerState>(() => {
    const params =
      typeof window !== "undefined"
        ? new URLSearchParams(window.location.search)
        : new URLSearchParams();
    let s = parseUrlToState(params, effectiveIngestAt);
    if (initial) {
      s = autoEnableFiltersForFocus(s, initial.type);
      // Seed loadedNodeIds with the focus + payload neighbors.
      const loadedNodeIds = new Set<string>([initial.id]);
      for (const n of initial.neighbors) loadedNodeIds.add(n.id);
      const loadedEdgeKeys = new Set<string>();
      for (const e of initial.edges) loadedEdgeKeys.add(edgeKey(e));
      s = { ...s, focus: initial.id, loadedNodeIds, loadedEdgeKeys };
    }
    return s;
  });

  // Cytoscape instance ref + container.
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);

  // Path selection: up to two nodes the user has shift+clicked.
  const [pathSelection, setPathSelection] = useState<string[]>([]);

  // Context menu: shown on right-click near a node.
  const [contextMenu, setContextMenu] = useState<{
    x: number;
    y: number;
    nodeId: string;
  } | null>(null);

  // Dialogs.
  const [pathDialogOpen, setPathDialogOpen] = useState(false);
  const [saveViewOpen, setSaveViewOpen] = useState(false);

  // Overflow tray — accumulates as expand calls hit caps.
  const [overflow, setOverflow] = useState<OverflowItem[]>([]);

  // Known labels per node id, populated from the initial payload + expand
  // responses. Used to render the overflow tray with friendly names.
  const labelsRef = useRef<Map<string, string>>(new Map());

  // Forward-declared ref to expandNode so the Cytoscape event handlers,
  // which are wired up during the mount effect, can reach the callback
  // that we don't declare until below.
  const expandNodeRef = useRef<
    ((nodeId: string, hop: 1 | 2 | 3 | 4) => Promise<void>) | null
  >(null);

  // Signature-subgraph manifest for the empty state.
  const [manifest, setManifest] = useState<SubgraphManifest | null>(null);

  useEffect(() => {
    if (initial) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch("/subgraphs/manifest.json");
        if (!res.ok) return;
        const json = (await res.json()) as SubgraphManifest;
        if (!cancelled) setManifest(json);
      } catch {
        /* ignore */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [initial]);

  // ---------------------------------------------------------------------------
  // URL ↔ state sync
  // ---------------------------------------------------------------------------

  // Throttle via a ref + setTimeout so rapid state updates don't saturate
  // the history API.
  const urlSyncTimer = useRef<number | null>(null);
  useEffect(() => {
    if (urlSyncTimer.current) window.clearTimeout(urlSyncTimer.current);
    urlSyncTimer.current = window.setTimeout(() => {
      const params = stateToUrl(state);
      const qs = params.toString();
      router.replace(qs ? `/graph?${qs}` : "/graph");
    }, 150);
    return () => {
      if (urlSyncTimer.current) window.clearTimeout(urlSyncTimer.current);
    };
  }, [state, router]);

  // ---------------------------------------------------------------------------
  // Cytoscape mount
  // ---------------------------------------------------------------------------

  // Build initial elements once on mount from the seed payload. All subsequent
  // mutations happen via cy.add()/cy.remove() directly — React never rebuilds
  // elements from React state again, because Cytoscape owns the canvas.
  const initialElements = useMemo<ElementDefinition[]>(() => {
    if (!initial) return [];
    return payloadToElements(initial);
  }, [initial]);

  useEffect(() => {
    if (!containerRef.current || !initial) return;
    // Seed labels cache for overflow chips + path highlight fallbacks.
    for (const n of initial.neighbors) labelsRef.current.set(n.id, n.label);
    labelsRef.current.set(initial.id, initial.label);

    const cy = cytoscape({
      container: containerRef.current,
      elements: initialElements,
      style: obsidianStylesheet,
      layout: fcoseLayout,
      wheelSensitivity: 0.2,
      boxSelectionEnabled: false,
    });
    cyRef.current = cy;

    // Tap handlers.
    cy.on("tap", "node", (event: EventObject) => {
      const node = event.target as NodeSingular;
      const id = node.id();
      const orig = event.originalEvent as MouseEvent | undefined;
      if (orig?.shiftKey) {
        // Shift+click → path selection.
        setPathSelection((prev) => {
          if (prev.includes(id)) return prev.filter((x) => x !== id);
          const next = [...prev, id];
          return next.length > 2 ? next.slice(-2) : next;
        });
        return;
      }
      if (id === state.focus) return; // focus click = no-op
      void expandNodeRef.current?.(id, 1);
    });

    // Right-click → context menu (context menu positions in viewport space).
    cy.on("cxttap", "node", (event: EventObject) => {
      const node = event.target as NodeSingular;
      const pos = node.renderedPosition();
      const rect = containerRef.current?.getBoundingClientRect();
      if (!rect) return;
      setContextMenu({
        x: rect.left + pos.x,
        y: rect.top + pos.y,
        nodeId: node.id(),
      });
    });

    // Clicking the blank canvas → close menu.
    cy.on("tap", (event: EventObject) => {
      if (event.target === cy) setContextMenu(null);
    });

    // Hover → reveal label for ring > 1.
    cy.on("mouseover", "node", (event: EventObject) => {
      const node = event.target as NodeSingular;
      const label = String(node.data("label") ?? "");
      node.data("visibleLabel", label);
    });
    cy.on("mouseout", "node", (event: EventObject) => {
      const node = event.target as NodeSingular;
      const role = String(node.data("role") ?? "");
      if (role !== "focus" && role !== "primary") {
        node.data("visibleLabel", "");
      }
    });

    return () => {
      cy.destroy();
      cyRef.current = null;
    };
    // Intentional: we only want to initialize Cytoscape once per focus.
    // state/focus changes do not rebuild — we mutate via cy.* below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initial]);

  // ---------------------------------------------------------------------------
  // Apply node/edge filters to the live Cytoscape instance
  // ---------------------------------------------------------------------------

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.batch(() => {
      cy.nodes().forEach((n) => {
        const t = n.data("type") as NodeType | undefined;
        const hidden = t ? !state.nodeFilters[t] : false;
        n.style("display", hidden ? "none" : "element");
      });
      cy.edges().forEach((e) => {
        const style = e.data("style") as string;
        const type = e.data("type") as string;
        const universal = (
          ["EVIDENCED_BY", "IN_JURISDICTION", "RELATES_TO_ISSUE"] as const
        ).includes(type as "EVIDENCED_BY" | "IN_JURISDICTION" | "RELATES_TO_ISSUE");
        let visible = true;
        if (universal) visible = state.edgeFilters.universal;
        else if (style === "money") visible = state.edgeFilters.money;
        else if (style === "legal-constrains") visible = state.edgeFilters.legalConstrains;
        else visible = state.edgeFilters.governance;
        e.style("display", visible ? "element" : "none");
      });
    });
  }, [state.nodeFilters, state.edgeFilters]);

  // ---------------------------------------------------------------------------
  // Apply time slider filter — hide nodes whose event_date falls outside.
  // ---------------------------------------------------------------------------

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    const from = state.timeFrom;
    const to = state.timeTo;
    cy.batch(() => {
      cy.nodes().forEach((n) => {
        const d = String(n.data("eventDate") ?? "").slice(0, 10);
        if (!d) return; // durable / undated — always visible
        const out = d < from || d > to;
        if (out) n.style("display", "none");
      });
    });
  }, [state.timeFrom, state.timeTo]);

  // ---------------------------------------------------------------------------
  // Path selection visualization
  // ---------------------------------------------------------------------------

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.batch(() => {
      cy.nodes().forEach((n) => {
        if (pathSelection.includes(n.id())) {
          n.style("border-width", 2);
          n.style("border-color", "#f2b441");
        } else if (!n.hasClass("highlighted")) {
          n.style("border-width", 0);
        }
      });
    });
  }, [pathSelection]);

  // ---------------------------------------------------------------------------
  // Expand (click or right-click)
  // ---------------------------------------------------------------------------

  const expandNode: (nodeId: string, hop: 1 | 2 | 3 | 4) => Promise<void> = useCallback(
    async (nodeId: string, hop: 1 | 2 | 3 | 4) => {
      const cy = cyRef.current;
      if (!cy) return;
      const alreadyLoaded = Array.from(state.loadedNodeIds).join(",");
      const excludedNodeTypes = (Object.keys(state.nodeFilters) as NodeType[])
        .filter((t) => !state.nodeFilters[t])
        .join(",");
      const url = `/api/expand?focus=${encodeURIComponent(nodeId)}&hop=${hop}&already_loaded=${encodeURIComponent(alreadyLoaded)}&excluded_node_types=${encodeURIComponent(excludedNodeTypes)}`;
      try {
        const res = await fetch(url);
        if (!res.ok) return;
        const json = (await res.json()) as ExpandResponse;
        const newNodes = json.nodes.filter((n) => !state.loadedNodeIds.has(n.id));
        const elementsToAdd: ElementDefinition[] = newNodes.map((n) =>
          nodeToElement({
            id: n.id,
            type: n.type,
            label: n.label,
            route: n.route,
            ring: 2, // incoming expand neighbors are secondary
          }),
        );
        // Add edges that connect existing-or-new nodes. We let mergeExpansion
        // dedupe edge keys so we don't double-render on re-expand.
        const nextState = mergeExpansion(
          state,
          newNodes.map((n) => ({ id: n.id })),
          json.edges,
        );
        const existingIds = new Set(cy.nodes().map((n) => n.id()));
        for (const n of newNodes) {
          existingIds.add(n.id);
          labelsRef.current.set(n.id, n.label);
        }
        const edgeElements: ElementDefinition[] = json.edges
          .filter((e) => existingIds.has(e.source) && existingIds.has(e.target))
          .map((e, i) => edgeToElement(e, i + cy.edges().length));

        if (elementsToAdd.length > 0 || edgeElements.length > 0) {
          cy.add([...elementsToAdd, ...edgeElements]);
          // Layout with animation so additions settle into the force graph.
          cy.layout(fcoseLayout).run();
        }
        // Overflow: if the response returned cap-many nodes, assume more are
        // hiding. This is a proxy — the API doesn't yet return a
        // neighbor_total per node.
        if (json.new_count >= json.cap && json.cap > 0) {
          const label =
            labelsRef.current.get(nodeId) ?? nodeId;
          setOverflow((prev) => {
            const existing = prev.find((x) => x.nodeId === nodeId);
            const remaining = Math.max(1, json.cap); // best-effort placeholder
            if (existing) {
              return prev.map((x) =>
                x.nodeId === nodeId ? { ...x, remaining: x.remaining + remaining } : x,
              );
            }
            return [...prev, { nodeId, label, remaining }];
          });
        }
        setState(nextState);
      } catch (err) {
        console.warn("expand failed", err);
      }
    },
    [state],
  );

  // Forward the latest expandNode to the ref so the Cytoscape event handlers
  // wired up during mount always see the current closure.
  useEffect(() => {
    expandNodeRef.current = expandNode;
  }, [expandNode]);

  // ---------------------------------------------------------------------------
  // Path highlight
  // ---------------------------------------------------------------------------

  const onHighlightPath = useCallback((args: HighlightPathArgs) => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.batch(() => {
      cy.elements().removeClass("highlighted");
      cy.nodes().forEach((n) => {
        if (args.nodeIds.includes(n.id())) {
          n.addClass("highlighted");
          n.style("border-width", 2);
          n.style("border-color", "#f2b441");
        }
      });
      cy.edges().forEach((e) => {
        const k = edgeKey({
          source: e.data("source"),
          target: e.data("target"),
          type: e.data("type"),
        } as EdgeLike);
        if (args.edgeKeys.includes(k)) {
          e.addClass("highlighted");
          e.style("line-color", "#f2b441");
          e.style("width", 2);
        }
      });
    });
  }, []);

  // Load a saved view — replace state and fire navigation.
  const onLoadView = useCallback(
    (next: ExplorerState) => {
      setState(next);
      if (next.focus && next.focus !== state.focus) {
        const params = stateToUrl(next);
        router.push(`/graph?${params.toString()}`);
      }
      setSaveViewOpen(false);
    },
    [router, state.focus],
  );

  // ---------------------------------------------------------------------------
  // Render — empty state vs. canvas
  // ---------------------------------------------------------------------------

  if (!initial) {
    const picks =
      manifest?.subgraphs.slice(0, 5) ?? [
        { slug: "merrydale", display_name: "350 Merrydale Interim Shelter", focus_node_id: "project-san-rafael-350-merrydale-interim-shelter" },
        { slug: "kate-colin", display_name: "Kate Colin — Mayor", focus_node_id: "person-kate-colin" },
      ];
    return (
      <div className="flex flex-1 items-center justify-center bg-[radial-gradient(ellipse_at_center,#121821_0%,#05070a_90%)]">
        <div className="flex flex-col items-center gap-4 font-mono text-dim">
          <div
            className="text-[#a4e8bf]"
            style={{ fontFamily: "var(--font-vt323)", fontSize: "18px", letterSpacing: "0.08em" }}
          >
            &gt; type a name or pick a signature subgraph
          </div>
          <ul className="flex flex-col items-center gap-1 text-xs">
            {picks.map((p) => (
              <li key={p.slug}>
                <Link
                  href={`/graph?focus=${encodeURIComponent(p.focus_node_id)}`}
                  className="text-dim underline-offset-2 hover:text-body hover:underline"
                >
                  {p.display_name}
                </Link>
              </li>
            ))}
          </ul>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-1 flex-col">
      <ExplorerToolbar
        state={state}
        onStateChange={setState}
        onOpenPath={() => setPathDialogOpen(true)}
        onOpenSaveView={() => setSaveViewOpen(true)}
      />
      <div className="relative flex-1">
        <div
          ref={containerRef}
          className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,#121821_0%,#05070a_90%)]"
          data-testid="explorer-canvas"
        />
        {contextMenu && (
          <div
            className="absolute z-10 rounded border border-border-primary bg-panel px-2 py-1 font-mono text-[11px] text-body shadow-lg"
            style={{ left: contextMenu.x, top: contextMenu.y }}
          >
            <button
              type="button"
              onClick={() => {
                void expandNodeRef.current?.(contextMenu.nodeId, state.hop);
                setContextMenu(null);
              }}
              className="block w-full px-2 py-1 text-left text-dim hover:text-body"
            >
              expand all ({state.hop} hop{state.hop > 1 ? "s" : ""})
            </button>
            <button
              type="button"
              onClick={() => setContextMenu(null)}
              className="block w-full px-2 py-1 text-left text-hairline hover:text-body"
            >
              cancel
            </button>
          </div>
        )}
        <OverflowIndicator items={overflow} />
        <div
          className="pointer-events-none absolute right-4 top-3 z-10 font-mono uppercase text-hairline"
          style={{ fontSize: "10px", letterSpacing: "0.12em" }}
        >
          EXPLORER · FCOSE · HOP {state.hop}
        </div>
        {pathSelection.length > 0 && (
          <div className="absolute left-4 top-3 z-10 font-mono text-[10px] text-[#f2b441]">
            PATH SELECTION: {pathSelection.join(" → ")}
            {pathSelection.length === 2 && (
              <button
                type="button"
                onClick={() => setPathDialogOpen(true)}
                className="ml-2 rounded border border-[#f2b441] bg-panel px-1.5 py-0.5 text-[10px]"
              >
                find path
              </button>
            )}
          </div>
        )}
      </div>

      <PathDialog
        open={pathDialogOpen}
        onClose={() => setPathDialogOpen(false)}
        onHighlightPath={(args) => {
          onHighlightPath(args);
          setPathDialogOpen(false);
        }}
      />
      <SaveViewMenu
        open={saveViewOpen}
        state={state}
        onClose={() => setSaveViewOpen(false)}
        onLoadView={onLoadView}
      />
    </div>
  );
}
