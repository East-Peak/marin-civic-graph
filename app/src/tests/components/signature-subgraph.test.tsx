import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { SignatureSubgraph } from "@/components/home/signature-subgraph";

// Mock cytoscape-base to avoid DOM rendering the actual graph in tests.
vi.mock("@/components/graph/cytoscape-base", () => ({
  CytoscapeBase: (props: { onNodeClick?: (id: string) => void }) => {
    // Expose a deterministic test hook.
    (globalThis as unknown as { __onNodeClick?: typeof props.onNodeClick }).__onNodeClick =
      props.onNodeClick;
    return <div data-testid="cy-stub" />;
  },
}));

// useRouter needs the app-router context — stub it out for jsdom.
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn(), back: vi.fn(), forward: vi.fn(), prefetch: vi.fn() }),
}));

const manifest = {
  built_at: "2026-04-18T00:00:00Z",
  subgraphs: [
    { slug: "merrydale", display_name: "Merrydale", focus_node_id: "project-merrydale" },
  ],
};
const bundle = {
  slug: "merrydale",
  display_name: "Merrydale",
  built_at: "2026-04-18T00:00:00Z",
  focus_node_id: "project-merrydale",
  headline_stats: { caption: "$15.3M · 6 decisions", kicker: "SIGNATURE SUBGRAPH · MERRYDALE" },
  nodes: [
    { id: "project-merrydale", type: "Project", label: "Merrydale", role: "focus", route: "/graph?focus=project-merrydale" },
  ],
  edges: [],
};

beforeEach(() => {
  global.fetch = vi.fn(async (url: RequestInfo | URL) => {
    const s = String(url);
    const body = s.includes("manifest.json") ? manifest : bundle;
    return new Response(JSON.stringify(body), { status: 200 });
  }) as unknown as typeof fetch;
});

describe("SignatureSubgraph", () => {
  it("renders caption + kicker after loading", async () => {
    render(<SignatureSubgraph />);
    await waitFor(() => expect(screen.getByText("$15.3M · 6 decisions")).toBeInTheDocument());
    expect(screen.getByText(/SIGNATURE SUBGRAPH · MERRYDALE/)).toBeInTheDocument();
  });
});
