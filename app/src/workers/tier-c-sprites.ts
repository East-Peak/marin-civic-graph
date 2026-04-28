import type { ConstellationNode } from "@/lib/constellation-types";

export const LRU_CAPACITY = 2000;
export const CARD_WIDTH = 120;
export const CARD_HEIGHT = 60;

export type CardSprite = {
  nodeId: string;
  width: number;
  height: number;
  // ImageBitmap in browser; null in jsdom (callers fall back to dot rendering).
  bitmap: ImageBitmap | null;
};

const cache = new Map<string, CardSprite>();

export async function renderCardSprite(node: ConstellationNode | {
  id: string; type: string; label: string; key_fact?: string | null;
}): Promise<CardSprite> {
  const cached = cache.get(node.id);
  if (cached) {
    // LRU: re-insert to push to most-recently-used position.
    cache.delete(node.id);
    cache.set(node.id, cached);
    return cached;
  }

  let bitmap: ImageBitmap | null = null;
  if (typeof OffscreenCanvas !== "undefined") {
    const canvas = new OffscreenCanvas(CARD_WIDTH, CARD_HEIGHT);
    const ctx = canvas.getContext("2d");
    if (ctx) {
      // Simple v2.0 card: type-colored panel + label + key_fact.
      ctx.fillStyle = "#0b0d11";
      ctx.fillRect(0, 0, CARD_WIDTH, CARD_HEIGHT);
      ctx.fillStyle = "#c2c8d2";
      ctx.font = "12px IBM Plex Sans, system-ui, sans-serif";
      ctx.fillText(node.label.slice(0, 18), 6, 18);
      if (node.key_fact) {
        ctx.fillStyle = "#7b8494";
        ctx.font = "10px IBM Plex Mono, ui-monospace, monospace";
        ctx.fillText(node.key_fact.slice(0, 22), 6, 38);
      }
      bitmap = await createImageBitmap(canvas);
    }
  }

  const sprite: CardSprite = {
    nodeId: node.id,
    width: CARD_WIDTH,
    height: CARD_HEIGHT,
    bitmap,
  };
  cache.set(node.id, sprite);
  if (cache.size > LRU_CAPACITY) {
    const oldest = cache.keys().next().value;
    if (oldest) cache.delete(oldest);
  }
  return sprite;
}

export function clearSpriteCache(): void {
  cache.clear();
}
