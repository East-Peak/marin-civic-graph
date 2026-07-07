// GET /api/parity-entity/{type}/{slug} — dev-only parity capture surface.
//
// Returns the raw EntityPayload JSON that the entity page renders as HTML,
// so the parity harness (spec 2026-07-07 §3) can diff entity semantics
// across serving backends without scraping SSR output. Exposes nothing the
// public entity page doesn't already render.
//
// Gated on PARITY_DEBUG=1 at request time: absent the env var this route is
// indistinguishable from a missing one (404).

import { loadEntity } from "@/lib/server/entity-loader";
import { jsonError } from "@/lib/api-errors";

export async function GET(
  _req: Request,
  { params }: { params: Promise<{ type: string; slug: string }> },
) {
  if (process.env.PARITY_DEBUG !== "1") {
    return jsonError("not found", 404);
  }
  const { type, slug } = await params;
  try {
    const payload = await loadEntity(type, slug);
    if (!payload) return jsonError("entity not found", 404);
    return Response.json(payload);
  } catch (err) {
    console.error(`/api/parity-entity/${type}/${slug} failed:`, err);
    return jsonError("entity load failed", 500);
  }
}
