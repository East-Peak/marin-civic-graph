import { loadStatus } from "@/lib/server/homepage-data";

export async function GET() {
  return Response.json(await loadStatus());
}
