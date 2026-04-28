import { describe, it, expect } from "vitest";
import {
  buildTierAAtlas, buildTierBAtlas, TIER_A_DOT_SIZES,
} from "@/components/constellation/sprite-atlas";
import { ALL_TYPES } from "@/lib/type-display";

describe("Tier-A atlas", () => {
  it("contains 21 types × 3 sizes = 63 sprites", () => {
    const atlas = buildTierAAtlas();
    expect(atlas.spriteCount).toBe(ALL_TYPES.length * TIER_A_DOT_SIZES.length);
  });

  it("each type has a colored dot at each size", () => {
    const atlas = buildTierAAtlas();
    for (const t of ALL_TYPES) {
      for (const s of TIER_A_DOT_SIZES) {
        expect(atlas.spriteIndex[`${t}:${s}`]).toBeTypeOf("number");
      }
    }
  });
});

describe("Tier-B atlas", () => {
  it("has one sprite per type with abbreviation", () => {
    const atlas = buildTierBAtlas();
    expect(atlas.spriteCount).toBe(ALL_TYPES.length);
    for (const t of ALL_TYPES) {
      expect(atlas.spriteIndex[t]).toBeTypeOf("number");
    }
  });
});
