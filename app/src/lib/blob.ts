import "server-only";

/**
 * Mints a short-TTL signed URL for a Constellation payload blob.
 *
 * v2.0 status: development stub — returns a URL with the production
 * shape but a non-cryptographic signature so the prototype client +
 * manifest endpoint can be exercised end-to-end without a real blob
 * host. Plan v2.1 wires this to one of:
 *   - Vercel Blob's signed-URL API (`@vercel/blob`'s token mint)
 *   - Cloudflare R2 / AWS S3 presign equivalent
 *
 * See spec §9.7 for the auth-respecting transport contract this is
 * the placeholder for.
 */
export async function signBlobUrl(blobPath: string, ttlSeconds: number): Promise<string> {
  const base = process.env.CONSTELLATION_BLOB_BASE ?? "https://blob.vercel-storage.com";
  const exp = Math.floor(Date.now() / 1000) + ttlSeconds;
  return `${base}/${blobPath}?exp=${exp}&sig=DEV-PROTOTYPE-${Math.random().toString(36).slice(2, 10)}`;
}
