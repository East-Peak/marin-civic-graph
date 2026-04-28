import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { ConstellationCanvas } from "@/lib/cosmograph-mount";

// Cosmograph is a real WebGL library; mock the constructor so the
// component-shape test can run in jsdom.
vi.mock("@cosmograph/cosmos", () => ({
  Graph: class FakeGraph {
    setConfig() {}
    setData() {}
    fitView() {}
    destroy() {}
  },
}));

describe("ConstellationCanvas", () => {
  it("renders a canvas element", () => {
    render(
      <ConstellationCanvas
        nodes={[]}
        edges={[]}
        spritesA={null}
        spritesB={null}
        onNodeClick={() => {}}
      />
    );
    expect(screen.getByTestId("constellation-canvas")).toBeInTheDocument();
  });
});
