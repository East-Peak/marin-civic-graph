import { NextResponse } from "next/server";
import { runQuery } from "@/lib/neo4j";
import { signBlobUrl } from "@/lib/blob";

const SIGNED_URL_TTL_SECONDS = 5 * 60;

// Pre-Plan-4b: allow only Stuart's home + tailnet ranges. Replaced by
// real session-cookie middleware once 4b lands.
const ALLOWED_IP_PREFIXES = (process.env.MANIFEST_ALLOWED_IP_PREFIXES ?? "127.0.0.1,::1,100.")
  .split(",")
  .map((p) => p.trim())
  .filter(Boolean);

function toNumber(v: unknown): number {
  return typeof v === "object" && v !== null && "toNumber" in v
    ? (v as { toNumber(): number }).toNumber()
    : Number(v);
}

function isAllowed(req: Request): boolean {
  const fwd = req.headers.get("x-forwarded-for") ?? "";
  const first = fwd.split(",")[0]?.trim() ?? "";
  return ALLOWED_IP_PREFIXES.some((p) => first.startsWith(p));
}

export async function GET(req: Request): Promise<NextResponse> {
  if (!isAllowed(req)) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }
  const rows = await runQuery(
    "MATCH (s:_SyncState {kind: 'constellation'}) " +
      "RETURN s.version_id AS version_id, s.umap_version AS umap_version, " +
      "s.blob_url AS blob_url, toString(s.updated_at) AS built_at, " +
      "s.size_gz AS size_gz",
    {},
  );
  if (rows.length === 0) {
    return NextResponse.json(
      { error: "constellation not yet built", current_version: null },
      { status: 503 },
    );
  }
  const r = rows[0];
  const signed = await signBlobUrl(r.get("blob_url") as string, SIGNED_URL_TTL_SECONDS);
  return NextResponse.json({
    schema_version: 1,
    current_version: r.get("version_id") as string,
    umap_version: toNumber(r.get("umap_version")),
    signed_url: signed,
    expires_at: new Date(Date.now() + SIGNED_URL_TTL_SECONDS * 1000).toISOString(),
    built_at: r.get("built_at") as string,
    size_gz: toNumber(r.get("size_gz")),
  });
}
