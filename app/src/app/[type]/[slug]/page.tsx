import { ComingSoon } from "@/components/layout/coming-soon";

export default async function EntityPage({
  params,
}: {
  params: Promise<{ type: string; slug: string }>;
}) {
  const { type, slug } = await params;
  return (
    <ComingSoon
      currentPath={`/${type}/${slug}`}
      heading="entity"
      body={`Entity pages land in Plan 2. (type: \`${type}\`, slug: \`${slug}\`)`}
      planName="PLAN 2 · ENTITY"
    />
  );
}
