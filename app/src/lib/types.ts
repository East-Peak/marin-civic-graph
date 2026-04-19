import type { NodeType } from "./type-display";

export type SubgraphNode = {
  id: string;
  type: NodeType;
  label: string;
  role: "focus" | "primary" | "secondary";
  route: string;
};

export type SubgraphEdge = {
  source: string;
  target: string;
  type: string;
  style: "governance" | "money" | "legal-constrains";
};

export type SubgraphBundle = {
  slug: string;
  display_name: string;
  built_at: string;
  focus_node_id: string;
  headline_stats: { caption: string; kicker: string };
  nodes: SubgraphNode[];
  edges: SubgraphEdge[];
};

export type SubgraphManifest = {
  built_at: string;
  subgraphs: Array<{ slug: string; display_name: string; focus_node_id: string }>;
};
