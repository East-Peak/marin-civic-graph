import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { loadEntity } from "@/lib/server/entity-loader";
import { entityPageMetadata } from "@/lib/server/contribution-metadata";
import { EntityPage } from "@/components/entity/entity-page";

export const dynamic = "force-dynamic";

type Props = { params: Promise<{ type: string; slug: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { type, slug } = await params;
  return entityPageMetadata(type, slug);
}

export default async function EntityPageRoute({ params }: Props) {
  const { type, slug } = await params;
  const entity = await loadEntity(type, slug);
  if (!entity) notFound();
  return <EntityPage entity={entity} />;
}
