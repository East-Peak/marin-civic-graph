import { describe, it, expect } from "vitest";
import { renderCardSprite, LRU_CAPACITY } from "@/workers/tier-c-sprites";

describe("renderCardSprite", () => {
  it("returns an OffscreenCanvas-compatible bitmap structure", async () => {
    const node = {
      id: "person-kate-colin",
      type: "Person" as const,
      label: "Kate Colin",
      key_fact: "Council member",
    };
    const sprite = await renderCardSprite(node);
    // jsdom OffscreenCanvas may not exist; the function should fall back
    // to a typed-array stub that callers can detect and render server-side.
    expect(sprite).toMatchObject({
      nodeId: "person-kate-colin",
      width: expect.any(Number),
      height: expect.any(Number),
    });
  });

  it("LRU capacity matches spec §4.4 budget (2000)", () => {
    expect(LRU_CAPACITY).toBe(2000);
  });
});
