import type { StylesheetStyle } from "cytoscape";
import { palette } from "@/lib/palette";

// Per spec §5.1 + §5.2 + §2.2 shape encoding.
// Shape applies only to generic bucket at radius >= 5.
// Cast needed because @types/cytoscape doesn't expose the shadow-* properties
// (they're supported by the runtime — see cytoscape docs on node/edge shadows).

export const obsidianStylesheet: StylesheetStyle[] = ([
  {
    selector: "node",
    style: {
      "background-color": palette.node.generic,
      width: "data(size)",
      height: "data(size)",
      "border-width": 0,
      label: "data(visibleLabel)",
      "font-family": "IBM Plex Mono, ui-monospace, monospace",
      "font-size": "9px",
      color: "#b0b7c3",
      "text-valign": "bottom",
      "text-margin-y": 4,
      "shadow-blur": "data(glowBlur)",
      "shadow-color": "data(glowColor)",
      "shadow-opacity": 1,
    },
  },
  {
    selector: "node[role = 'focus']",
    style: { "background-color": palette.node.focus },
  },
  {
    selector: "node[colorClass = 'decision']",
    style: { "background-color": palette.node.decision },
  },
  {
    selector: "node[colorClass = 'money']",
    style: { "background-color": palette.node.money },
  },
  {
    selector: "node[colorClass = 'person']",
    style: { "background-color": palette.node.person },
  },
  {
    selector: "node[colorClass = 'legal']",
    style: { "background-color": palette.node.legal },
  },
  {
    selector: "node[colorClass = 'organization']",
    style: { "background-color": palette.node.organization },
  },
  {
    selector: "node[colorClass = 'projectProgram']",
    style: { "background-color": palette.node.projectProgram },
  },
  { selector: "node[shape = 'square']", style: { shape: "rectangle" } },
  { selector: "node[shape = 'ring']", style: { "background-opacity": 0, "border-width": 1.5, "border-color": palette.node.generic } },

  // Edges
  {
    selector: "edge",
    style: {
      "curve-style": "bezier",
      "line-color": palette.edge.governance,
      width: 0.9,
      "target-arrow-shape": "none",
    },
  },
  {
    selector: "edge[style = 'money']",
    style: {
      "line-color": palette.edge.money,
      width: 1.2,
      "shadow-blur": 4,
      "shadow-color": palette.edge.money,
      "shadow-opacity": 0.6,
    },
  },
  {
    selector: "edge[style = 'legal-constrains']",
    style: {
      "line-color": palette.edge.legalConstrains,
      width: 1.1,
      "line-style": "dashed",
      "line-dash-pattern": [3, 3],
      "shadow-blur": 3,
      "shadow-color": palette.edge.legalConstrains,
      "shadow-opacity": 0.6,
    },
  },
] as unknown) as StylesheetStyle[];

// Per-type color class resolution (used when building Cytoscape data).
export function colorClassForType(type: string): string | null {
  switch (type) {
    case "Decision":
      return "decision";
    case "MoneyFlow":
      return "money";
    case "Person":
      return "person";
    case "Case":
    case "Proceeding":
      return "legal";
    case "Organization":
      return "organization";
    case "Project":
    case "Program":
      return "projectProgram";
    default:
      return null;
  }
}

// Shape encoding for generic bucket per §2.2.
export function shapeForType(type: string): "circle" | "square" | "ring" {
  if (["Place", "Issue"].includes(type)) return "square";
  if (["Seat", "SeatService", "Candidacy", "Committee"].includes(type)) return "ring";
  return "circle";
}

// Size by role per §5.1.
export function sizeForRole(role: string): number {
  if (role === "focus") return 22;
  if (role === "primary") return 14;
  if (role === "secondary") return 10;
  return 8;
}

// Glow blur by role + colorClass.
export function glowForRole(role: string, colorClass: string | null): { blur: number; color: string } {
  if (role === "focus") return { blur: 8, color: "#ffffff" };
  const color =
    colorClass === "money"
      ? palette.node.money
      : colorClass === "person"
        ? palette.node.person
        : colorClass === "legal"
          ? palette.node.legal
          : colorClass === "decision"
            ? palette.node.decision
            : colorClass === "organization"
              ? palette.node.organization
              : colorClass === "projectProgram"
                ? palette.node.projectProgram
                : palette.node.generic;
  return { blur: 5, color };
}
