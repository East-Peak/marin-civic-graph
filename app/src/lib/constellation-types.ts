export const CONSTELLATION_SCHEMA_VERSION = 1;

export type ConstellationNode = {
  id: string;
  type: string;
  label: string;
  key_fact?: string | null;
  x: number;
  y: number;
  cluster_id: number;
  embedding_hash?: string;
};

export type ConstellationEdge = {
  s: string;
  t: string;
  type: string;
  weight: number;
};

export type ConstellationCluster = {
  id: number;
  label: string;
  centroid: [number, number];
  member_count: number;
};

export type ConstellationPayload = {
  schema_version: number;
  version: string;
  umap_version: number;
  built_at: string;
  node_count: number;
  edge_count: number;
  cluster_count: number;
  nodes: ConstellationNode[];
  edges: ConstellationEdge[];
  clusters: ConstellationCluster[];
};
