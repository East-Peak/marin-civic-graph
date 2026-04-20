import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import {
  PaletteResults,
  type PaletteResultItem,
} from "@/components/palette/palette-results";

const sampleItems: PaletteResultItem[] = [
  {
    kind: "result",
    id: "person-kate-colin",
    type: "Person",
    label: "Kate Colin",
    key_fact: "San Rafael City Council",
    route: "/person/kate-colin",
  },
  {
    kind: "quickjump",
    id: "qj:graph",
    type: "jump",
    label: "go graph",
    key_fact: null,
    route: "/graph",
  },
];

describe("PaletteResults", () => {
  it("renders all items with label and key_fact", () => {
    render(
      <PaletteResults items={sampleItems} selectedIndex={0} onSelect={() => {}} />,
    );
    expect(screen.getByText("Kate Colin")).toBeInTheDocument();
    expect(screen.getByText(/San Rafael City Council/)).toBeInTheDocument();
    expect(screen.getByText("go graph")).toBeInTheDocument();
  });

  it("marks the item at selectedIndex with aria-selected=true", () => {
    render(
      <PaletteResults items={sampleItems} selectedIndex={1} onSelect={() => {}} />,
    );
    const rows = screen.getAllByRole("option");
    expect(rows[0].getAttribute("aria-selected")).toBe("false");
    expect(rows[1].getAttribute("aria-selected")).toBe("true");
  });

  it("clicking an item calls onSelect with that item", () => {
    const onSelect = vi.fn();
    render(
      <PaletteResults items={sampleItems} selectedIndex={0} onSelect={onSelect} />,
    );
    fireEvent.click(screen.getByText("go graph"));
    expect(onSelect).toHaveBeenCalledWith(sampleItems[1]);
  });

  it("renders nothing meaningful for an empty list", () => {
    const { container } = render(
      <PaletteResults items={[]} selectedIndex={0} onSelect={() => {}} />,
    );
    // No option rows
    expect(screen.queryAllByRole("option")).toHaveLength(0);
    // Container is still a valid element but has no result rows
    expect(container.querySelectorAll("[data-testid='palette-row']")).toHaveLength(0);
  });

  it("each option row has id='palette-item-{index}' (for aria-activedescendant)", () => {
    render(
      <PaletteResults items={sampleItems} selectedIndex={0} onSelect={() => {}} />,
    );
    const rows = screen.getAllByRole("option");
    expect(rows[0].id).toBe("palette-item-0");
    expect(rows[1].id).toBe("palette-item-1");
  });

  it("applies listboxId to the <ul>", () => {
    render(
      <PaletteResults
        items={sampleItems}
        selectedIndex={0}
        onSelect={() => {}}
        listboxId="palette-listbox"
      />,
    );
    const list = screen.getByRole("listbox");
    expect(list.id).toBe("palette-listbox");
  });
});
