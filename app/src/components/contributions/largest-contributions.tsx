// app/src/components/contributions/largest-contributions.tsx
//
// One row per reconciled contribution, largest signed amount first (flow id breaks ties),
// paged by keyset cursor. Each name links to its name view, never to a profile.

import Link from "next/link";
import {
  NOT_AVAILABLE,
  RecordedType,
  ReportedDetailsCell,
  amountClass,
  cellClass,
  formatCents,
  headCellClass,
  linkClass,
  tableClass,
} from "@/components/contributions/contribution-parts";
import {
  InvalidCursorError,
  loadLargestContributions,
  type LargestContributions as Page,
} from "@/lib/server/contributions-sql";

function loadPage(after: string | null, limit: number): { page: Page; paged: boolean } {
  try {
    return { page: loadLargestContributions({ limit, after }), paged: after !== null };
  } catch (err) {
    if (!(err instanceof InvalidCursorError)) throw err;
    return { page: loadLargestContributions({ limit }), paged: false };
  }
}

export function LargestContributions({ after, pageSize = 50 }: { after: string | null; pageSize?: number }) {
  const { page, paged } = loadPage(after, pageSize);
  return (
    <>
      <div className="overflow-x-auto rounded border border-border-hairline">
        <table className={tableClass}>
          <thead>
            <tr className="bg-surface">
              <th className={headCellClass}>Date</th>
              <th className={`${headCellClass} text-right`}>Amount</th>
              <th className={headCellClass}>Reported name</th>
              <th className={headCellClass}>Recipient committee</th>
              <th className={headCellClass}>Reported details</th>
              <th className={headCellClass}>Filing</th>
            </tr>
          </thead>
          <tbody>
            {page.rows.map((row) => (
              <tr key={row.flow_id} className="border-b border-border-hairline last:border-b-0" data-testid="contribution-row">
                <td className={`${cellClass} whitespace-nowrap`} data-testid="row-date">
                  {row.date ?? "—"}
                </td>
                <td className={amountClass} data-testid="row-amount">
                  {formatCents(row.amount_cents)}
                </td>
                <td className={`${cellClass} min-w-[160px]`}>
                  {row.contributor ? (
                    <>
                      <Link href={row.contributor.name_route} className={linkClass}>
                        {row.contributor.label}
                      </Link>
                      <RecordedType type={row.contributor.type} />
                    </>
                  ) : (
                    <span className="text-hairline">{NOT_AVAILABLE}</span>
                  )}
                </td>
                <td className={`${cellClass} min-w-[160px]`}>
                  {row.recipient ? (
                    <Link href={row.recipient.route} className={linkClass}>
                      {row.recipient.label}
                    </Link>
                  ) : (
                    <span className="text-hairline">{NOT_AVAILABLE}</span>
                  )}
                </td>
                <td className={`${cellClass} min-w-[220px]`}>
                  <ReportedDetailsCell details={row.details} />
                </td>
                <td className={cellClass}>
                  <Link href={row.flow_route} className={linkClass}>
                    record
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-2 flex gap-4 font-mono text-xs">
        {paged && (
          <Link href="/contributions" className={linkClass} data-testid="first-contributions">
            ← Largest first
          </Link>
        )}
        {page.next_cursor && (
          <Link
            href={`/contributions?after=${encodeURIComponent(page.next_cursor)}`}
            className={linkClass}
            data-testid="next-contributions"
          >
            Next {pageSize} →
          </Link>
        )}
      </div>
    </>
  );
}
