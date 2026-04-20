// GET /api/browse/{type}?cursor=...&limit=50&q=...
//
// Returns a page of rows of the given NodeType plus a next_cursor. Cursor-
// based pagination — rows sorted by id ASC; the cursor is the last-seen id.
// Unknown types and mis-typed filters return 400.

import { jsonError } from "@/lib/api-errors";
import {
  MAX_LIMIT,
  MAX_SEARCH_LENGTH,
  nodeTypeForUrlSegment,
  runBrowseQuery,
} from "@/lib/server/browse-queries";

const MAX_CURSOR_LENGTH = 500;

export async function GET(
  req: Request,
  { params }: { params: Promise<{ type: string }> },
) {
  const { type: urlSeg } = await params;
  const type = nodeTypeForUrlSegment(urlSeg);
  if (!type) return jsonError(`unknown type: ${urlSeg}`, 400);

  const { searchParams } = new URL(req.url);
  const cursorRaw = searchParams.get("cursor");
  const limitRaw = searchParams.get("limit");
  const qRaw = searchParams.get("q");

  if (cursorRaw && cursorRaw.length > MAX_CURSOR_LENGTH) {
    return jsonError("cursor too long", 400);
  }

  let limit: number | undefined;
  if (limitRaw != null) {
    const parsed = Number(limitRaw);
    if (!Number.isFinite(parsed) || parsed <= 0) {
      return jsonError("invalid limit", 400);
    }
    if (parsed > MAX_LIMIT) {
      return jsonError(`limit exceeds ${MAX_LIMIT}`, 400);
    }
    limit = parsed;
  }

  if (qRaw && qRaw.length > MAX_SEARCH_LENGTH) {
    return jsonError("q too long", 400);
  }

  try {
    const result = await runBrowseQuery({
      type,
      cursor: cursorRaw ?? undefined,
      limit,
      search: qRaw ?? undefined,
    });
    return Response.json({
      type,
      rows: result.rows,
      next_cursor: result.next_cursor,
      columns: result.columns,
    });
  } catch (err) {
    console.error(`/api/browse/${urlSeg} failed:`, err);
    return jsonError("browse failed", 500);
  }
}
