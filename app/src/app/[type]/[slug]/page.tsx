import { notFound } from "next/navigation";
import { loadEntity } from "@/lib/server/entity-loader";
import { EntityPage } from "@/components/entity/entity-page";

export const dynamic = "force-dynamic";

export default async function EntityPageRoute({
  params,
}: {
  params: Promise<{ type: string; slug: string }>;
}) {
  const { type, slug } = await params;
  const entity = await loadEntity(type, slug);
  if (!entity) notFound();
  return <EntityPage entity={entity} />;
}
