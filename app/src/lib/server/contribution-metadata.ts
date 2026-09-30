// app/src/lib/server/contribution-metadata.ts
//
// Search-engine metadata for pages about a contributor name group: never indexed, and
// titled for what they are — contributions reported under a name, not a profile.
import "server-only";

import type { Metadata } from "next";
import type { ContributorType } from "@/lib/entity-route";
import { isContributorOnly, resolveContributorNode, type ContributorNode } from "@/lib/server/contributions-sql";

export const NOINDEX: Metadata["robots"] = { index: false, follow: true };

export function contributionNameMetadata(contributor: ContributorNode | null): Metadata {
  if (!contributor) return { robots: NOINDEX };
  const people: Record<ContributorType, string> = { Person: "people", Organization: "organizations" };
  return {
    title: `Contributions reported under ${contributor.label}`,
    description:
      `Contributions reported under ${contributor.label} in Marin County and Novato campaign filings; ` +
      `may represent multiple ${people[contributor.type]}.`,
    robots: NOINDEX,
  };
}

/**
 * For a Person/Organization entity page whose node's only public role is contributing:
 * noindex and a "Contributions reported under" title. Every other page keeps the defaults.
 */
export function entityPageMetadata(segment: string, slug: string): Metadata {
  let contributor: ContributorNode | null;
  try {
    contributor = resolveContributorNode(segment, slug);
  } catch (err) {
    console.warn(`[entity-metadata] substrate lookup failed for /${segment}/${slug}:`, err);
    return {};
  }
  return contributor && isContributorOnly(contributor.id) ? contributionNameMetadata(contributor) : {};
}
