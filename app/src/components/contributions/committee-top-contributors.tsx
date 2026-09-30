// app/src/components/contributions/committee-top-contributors.tsx
//
// A committee page's ranking of the names contributions to it were reported under.
// Only this committee's rows feed a name's count, total and details; each name links
// to its name view, never to a Person/Organization profile.

import Link from "next/link";
import {
  COVERAGE_NOTE,
  ContributionTotal,
  DETAILS_DISCLAIMER,
  Note,
  ReportedDetailsCell,
  SectionLabel,
  amountClass,
  cellClass,
  formatCents,
  headCellClass,
  linkClass,
  tableClass,
} from "@/components/contributions/contribution-parts";
import {
  InvalidCursorError,
  loadCommitteeTopContributors,
  type CommitteeTopContributors as Ranking,
} from "@/lib/server/contributions-sql";

export const COMMITTEE_CAPTION =
  "Totals group contributions reported under the same name to this committee; a name may represent multiple people.";

const ANCHOR = "top-contributors";

type Props = {
  committeeId: string;
  /** The committee page's own path, for the pagination links. */
  committeePath: string;
  after: string | null;
  pageSize?: number;
};

function loadPage(committeeId: string, after: string | null, limit: number): { ranking: Ranking; paged: boolean } {
  try {
    return { ranking: loadCommitteeTopContributors(committeeId, { limit, after }), paged: after !== null };
  } catch (err) {
    if (!(err instanceof InvalidCursorError)) throw err;
    return { ranking: loadCommitteeTopContributors(committeeId, { limit }), paged: false };
  }
}

export async function CommitteeTopContributors({ committeeId, committeePath, after, pageSize = 25 }: Props) {
  const { ranking, paged } = loadPage(committeeId, after, pageSize);
  if (ranking.summary.count === 0) return null;
  const { summary } = ranking;

  return (
    <section id={ANCHOR} className="mx-[18px] mt-6" data-testid="committee-top-contributors">
      <SectionLabel>Top contributors to this committee</SectionLabel>
      <div className="mb-2 max-w-3xl space-y-1">
        <Note>{COVERAGE_NOTE}</Note>
        <Note>{DETAILS_DISCLAIMER}</Note>
        <Note>
          {summary.names.toLocaleString("en-US")} names · {summary.count.toLocaleString("en-US")} contributions ·{" "}
          {formatCents(summary.total_cents)} in all
        </Note>
      </div>
      <div className="overflow-x-auto rounded border border-border-hairline">
        <table className={tableClass}>
          <caption className="caption-top border-b border-border-hairline px-3 py-2 text-left text-[11px] text-dim">
            {COMMITTEE_CAPTION}
          </caption>
          <thead>
            <tr className="bg-surface">
              <th className={`${headCellClass} text-right`}>#</th>
              <th className={headCellClass}>Reported name</th>
              <th className={`${headCellClass} text-right`}>Contributions</th>
              <th className={`${headCellClass} text-right`}>Total reported under this name</th>
              <th className={headCellClass}>Rows to this committee</th>
            </tr>
          </thead>
          <tbody>
            {ranking.rows.map((entry) => (
              <tr
                key={entry.contributor.id}
                className="border-b border-border-hairline last:border-b-0"
                data-testid="ranked-name"
              >
                <td className={`${cellClass} text-right text-dim`}>{entry.rank}</td>
                <td className={`${cellClass} min-w-[160px]`}>
                  <Link href={entry.contributor.name_route} className={linkClass}>
                    {entry.contributor.label}
                  </Link>
                  <div className="text-[10px] text-dim">
                    {entry.contributor.type === "Organization" ? "Organization" : "Individual"}
                  </div>
                </td>
                <td className={`${cellClass} text-right`}>{entry.count.toLocaleString("en-US")}</td>
                <td className={`${cellClass} text-right`}>
                  <ContributionTotal cents={entry.total_cents} type={entry.contributor.type} />
                </td>
                <td className={`${cellClass} min-w-[300px]`}>
                  <ul className="space-y-2">
                    {entry.rows.map((row) => (
                      <li key={row.flow_id} data-testid="ranked-row" className="grid grid-cols-[88px_76px_1fr] gap-x-2">
                        <Link href={row.flow_route} className={`${linkClass} whitespace-nowrap`}>
                          {row.date ?? "—"}
                        </Link>
                        <span className={`${amountClass} px-0 py-0`}>{formatCents(row.amount_cents)}</span>
                        <ReportedDetailsCell details={row.details} />
                      </li>
                    ))}
                  </ul>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-2 flex gap-4 font-mono text-xs">
        {paged && (
          <Link href={`${committeePath}#${ANCHOR}`} className={linkClass} data-testid="first-names">
            ← First names
          </Link>
        )}
        {ranking.next_cursor && (
          <Link
            href={`${committeePath}?contributors_after=${encodeURIComponent(ranking.next_cursor)}#${ANCHOR}`}
            className={linkClass}
            data-testid="next-names"
          >
            Next {pageSize} names →
          </Link>
        )}
      </div>
    </section>
  );
}
