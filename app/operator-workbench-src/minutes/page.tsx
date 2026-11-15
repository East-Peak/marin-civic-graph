// Operator-local route group — copied into src/app/(operator-workbench)/ ONLY under OPERATOR_WORKBENCH=1, never
// in a public build. /minutes: one search box over the minutes text index, results grouped by meeting (newest
// first), and per-body coverage so "no results" is distinguishable from "not covered". Plain on purpose; a design
// pass comes later.
import { notFound } from "next/navigation";
import { operatorEnabled } from "@/lib/operator-gate";
import {
  COVERAGE_STATES,
  MARK_END,
  MARK_START,
  loadMinutesPage,
  type BodyCoverage,
  type MeetingResult,
} from "../_lib/minutes-text";

export const dynamic = "force-dynamic";

function Passage({ text }: { text: string }) {
  // The snippet marks matches with control characters: split, never inject HTML.
  const parts = text.split(new RegExp(`${MARK_START}(.*?)${MARK_END}`, "g"));
  return <>{parts.map((p, i) => (i % 2 === 1 ? <mark key={i}>{p}</mark> : <span key={i}>{p}</span>))}</>;
}

function Result({ m }: { m: MeetingResult }) {
  return (
    <article className="border-t border-hairline py-3">
      <div className="flex flex-wrap gap-x-3">
        <strong>{m.body}</strong>
        <span>{m.meetingDate}</span>
        {m.officialUrl ? (
          <a className="underline" href={m.officialUrl} target="_blank" rel="noreferrer noopener">
            official document
          </a>
        ) : (
          <span>no official link</span>
        )}
      </div>
      <ul className="mt-1 space-y-1">
        {m.hits.map((h) => (
          <li key={h.page}>
            <span className="text-hairline">page {h.page}: </span>
            <Passage text={h.snippet} />
          </li>
        ))}
      </ul>
    </article>
  );
}

function Coverage({ rows, asOf }: { rows: BodyCoverage[]; asOf: string }) {
  return (
    <section className="mt-8">
      <h2 className="font-semibold">Coverage (meetings with a minutes link, substrate as of {asOf})</h2>
      <table className="mt-2 text-sm">
        <thead>
          <tr>
            <th className="pr-4 text-left">body</th>
            <th className="pr-4 text-left">dates</th>
            {COVERAGE_STATES.map((s) => (
              <th key={s} className="pr-4 text-right">{s}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((b) => (
            <tr key={b.body}>
              <td className="pr-4">{b.body}</td>
              <td className="pr-4">{`${b.first} – ${b.last}`}</td>
              {COVERAGE_STATES.map((s) => (
                <td key={s} className="pr-4 text-right">{b.counts[s]}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

export default async function MinutesPage({
  searchParams,
}: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  if (!operatorEnabled()) notFound(); // defense-in-depth if ever shipped/leaked
  const raw = (await searchParams).q;
  const query = (Array.isArray(raw) ? raw[0] : raw ?? "").trim();
  const data = loadMinutesPage(query);

  return (
    <main className="mx-[18px] mt-6 max-w-[900px] text-body">
      <h1 className="font-semibold">Minutes text search (operator only)</h1>
      <form method="get" action="/minutes" className="my-4 flex gap-2">
        <input name="q" defaultValue={query} aria-label="Search minutes text" className="flex-1 border px-2 py-1" />
        <button type="submit" className="border px-3">Search</button>
      </form>
      {data.status === "absent" ? (
        <p>
          The minutes text index is not built: no file at <code>{data.path}</code>. Run{" "}
          <code>scripts/minutes_text_index.py build</code>. The rest of the app is unaffected.
        </p>
      ) : (
        <>
          {query &&
            (data.results.length ? (
              <p>
                {data.results.length} meetings, {data.results.reduce((n, m) => n + m.hits.length, 0)} pages
              </p>
            ) : (
              <p>No matches in the indexed minutes. Check coverage below before reading this as “never discussed”.</p>
            ))}
          {data.results.map((m) => (
            <Result key={m.meetingId} m={m} />
          ))}
          <Coverage rows={data.coverage} asOf={data.asOf} />
        </>
      )}
    </main>
  );
}
