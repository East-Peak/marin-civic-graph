// app/src/app/api/search/route.ts
//
// Thin HTTP wrapper around runSearch() in @/lib/server/search-backend.
// All query logic lives there so the /search page can call it directly
// without a self-fetch.

import { jsonError } from "@/lib/api-errors";
import { runSearch, MAX_Q_LENGTH } from "@/lib/server/search-backend";

export async function GET(req: Request) {
  const { searchParams } = new URL(req.url);
  const q = (searchParams.get("q") ?? "").trim();
  const includeRecords = searchParams.get("include_records") === "true";
  if (!q) return jsonError("q required", 400);
  if (q.length > MAX_Q_LENGTH) return jsonError("q too long", 400);

  try {
    const payload = await runSearch(q, includeRecords);
    return Response.json(payload);
  } catch (err) {
    console.error("search error", err);
    return jsonError("search failed", 500);
  }
}
