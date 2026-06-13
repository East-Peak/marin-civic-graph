import { ALL_TYPES, type NodeType } from "@/lib/type-display";

export const TIER_A_DOT_SIZES = [4, 6, 8] as const;

const TYPE_COLORS: Record<NodeType, string> = {
  Person: "#8db8ff",
  Organization: "#b8a8d9",
  Committee: "#b8a8d9",
  Seat: "#e8ecf3",
  SeatService: "#e8ecf3",
  Election: "#e8ecf3",
  Candidacy: "#e8ecf3",
  Meeting: "#e8ecf3",
  AgendaItem: "#e8ecf3",
  Decision: "#a4e8bf",
  Filing: "#e8ecf3",
  MoneyFlow: "#f2c77a",
  Case: "#e27a7a",
  Proceeding: "#e27a7a",
  Project: "#d9a88d",
  Program: "#d9a88d",
  Agreement: "#e8ecf3",
  Amendment: "#e8ecf3",
  Record: "#e8ecf3",
  Place: "#e8ecf3",
  Issue: "#e8ecf3",
  // Muted teal — the only unused hue in the pastel band; sits between the
  // Person blue and Decision green for the person↔org connective type.
  Membership: "#8fd9c9",
  // Muted sand — distinct from MoneyFlow's brighter gold (#f2c77a); the Form 700
  // disclosure connective (Filing→Organization) reads as economic without
  // implying a transactional money flow.
  EconomicInterest: "#e3cfa3",
};

const TYPE_ABBREV: Record<NodeType, string> = {
  Person: "PER", Organization: "ORG", Committee: "CMT",
  Seat: "ST", SeatService: "STS", Election: "ELC",
  Candidacy: "CND", Meeting: "MTG", AgendaItem: "AI",
  Decision: "DEC", Filing: "FLG", MoneyFlow: "$$$",
  Case: "CSE", Proceeding: "PRC", Project: "PRJ",
  Program: "PRG", Agreement: "AGR", Amendment: "AMD",
  Record: "REC", Place: "PLC", Issue: "ISS",
  Membership: "MBR", EconomicInterest: "ECI",
};

export type SpriteAtlas = {
  spriteCount: number;
  spriteIndex: Record<string, number>;
  // texture data — Uint8ClampedArray of RGBA values; consumed by Cosmograph
  // as a sprite sheet via WebGL texture upload. v2.0 stub returns empty
  // texture; the prototype client (Task 14) doesn't need pixel-perfect
  // sprites — full rendering lands in v2.1 alongside Tier-C.
  textureRGBA: Uint8ClampedArray;
  textureWidth: number;
  textureHeight: number;
};

export function buildTierAAtlas(): SpriteAtlas {
  const spriteIndex: Record<string, number> = {};
  let i = 0;
  for (const t of ALL_TYPES) {
    for (const s of TIER_A_DOT_SIZES) {
      spriteIndex[`${t}:${s}`] = i++;
    }
  }
  return {
    spriteCount: i,
    spriteIndex,
    textureRGBA: new Uint8ClampedArray(0),
    textureWidth: 0,
    textureHeight: 0,
  };
}

export function buildTierBAtlas(): SpriteAtlas {
  const spriteIndex: Record<string, number> = {};
  let i = 0;
  for (const t of ALL_TYPES) {
    spriteIndex[t] = i++;
  }
  return {
    spriteCount: i,
    spriteIndex,
    textureRGBA: new Uint8ClampedArray(0),
    textureWidth: 0,
    textureHeight: 0,
  };
}

export { TYPE_COLORS, TYPE_ABBREV };
