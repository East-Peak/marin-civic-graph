import { ComingSoon } from "@/components/layout/coming-soon";

export default async function BrowseTypePage({ params }: { params: Promise<{ type: string }> }) {
  const { type } = await params;
  return (
    <ComingSoon
      currentPath={`/browse/${type}`}
      heading="browse"
      body={`Filtered browse for \`${type}\` lands in Plan 2.`}
      planName="PLAN 2 · BROWSE"
    />
  );
}
