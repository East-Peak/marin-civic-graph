// GET /api/path?from={id}&to={id}&loose=true|false
//
// Thin wrapper around `findPath()` (lib/server/path-finder.ts). Validates
// required params + length caps, returns the `PathResult` shape directly.
// Errors surface as {error: "<msg>"} with an HTTP status.

import { findPath } from "@/lib/server/path-finder";
import { jsonError } from "@/lib/api-errors";

const MAX_ID_LENGTH = 500;

export async function GET(req: Request) {
  const { searchParams } = new URL(req.url);
  const from = searchParams.get("from")?.trim();
  const to = searchParams.get("to")?.trim();
  const loose = searchParams.get("loose") === "true";

  if (!from || !to) return jsonError("from + to required", 400);
  if (from.length > MAX_ID_LENGTH || to.length > MAX_ID_LENGTH) {
    return jsonError("id too long", 400);
  }

  try {
    const result = await findPath(from, to, { loose });
    return Response.json(result);
  } catch (err) {
    console.error("/api/path failed:", err);
    return jsonError("pathfinding failed", 500);
  }
}
