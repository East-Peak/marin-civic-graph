import "server-only";

export async function signBlobUrl(blobPath: string, ttlSeconds: number): Promise<string> {
  // v2.0 stub: in production this calls @vercel/blob's signed URL API
  // (or an S3 PreSign equivalent). For the rehearsal we serve from a local
  // file accessed by URL.
  const base = process.env.CONSTELLATION_BLOB_BASE ?? "https://blob.vercel-storage.com";
  const exp = Math.floor(Date.now() / 1000) + ttlSeconds;
  // Placeholder signature so the URL shape matches production.
  return `${base}/${blobPath}?exp=${exp}&sig=stub-${Math.random().toString(36).slice(2, 10)}`;
}
