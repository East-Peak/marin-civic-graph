// Operator-local route group — never in a public build. /actors/[slug]: one actor (organization, public body or
// person; registered or an officer listed on a return) with a by-year summary, a section per fact kind with rows,
// labels, sources and that section's coverage, possible matches, affiliations, case roles with outcomes,
// connections, and full coverage. States what documents show; nothing here is a score or an imputation.
import Link from "next/link";
import { notFound } from "next/navigation";
import { operatorEnabled } from "@/lib/operator-gate";
import {
  SIDE_UNKNOWN,
  isConfirmed,
  loadActorPage,
  type Connection,
  type Fact,
  type Searched,
  type Section,
  type YearRow,
} from "../../_lib/actors";
import { Absent, Coverage, Source, basisText, caseHref, money } from "../../_lib/actor-parts";

export const dynamic = "force-dynamic";

const nice = (s: string | null) => (s ?? "").replaceAll("_", " ");

function decode(raw: string): string {
  try {
    return decodeURIComponent(raw);
  } catch {
    return raw;
  }
}

function Pager({ kind, page, pageSize, total, slug }: { kind: string; page: number; pageSize: number; total: number;
  slug: string }) {
  if (total <= pageSize) return null;
  const last = Math.ceil(total / pageSize);
  const href = (n: number) => `/actors/${slug}?section=${kind}&page=${n}`;
  return (
    <p className="text-sm">
      Rows {(page - 1) * pageSize + 1}–{Math.min(page * pageSize, total)} of {total} rows; totals cover all.{" "}
      {page > 1 && <Link className="underline" href={href(page - 1)}>previous</Link>}{" "}
      {page < last && <Link className="underline" href={href(page + 1)}>next</Link>}
    </p>
  );
}

function OtherEnd({ slug, name, basis, names }: { slug: string | null; name: string | null; basis: string | null;
  names: Record<string, string> }) {
  if (!slug || !names[slug]) return <>{name}</>;
  if (isConfirmed(basis)) return <Link className="underline" href={`/actors/${slug}`}>{name}</Link>;
  // Attached only as a possible match: the name as the source states it, the candidate named apart, no link.
  return <>{name} <span className="text-xs">(possible match: {names[slug]}, {basisText(basis)})</span></>;
}

function FactRow({ f, slug, names }: { f: Fact; slug: string; names: Record<string, string> }) {
  const asCounterparty = f.actor_slug !== slug;
  const other = asCounterparty ? f.actor_slug : f.counterparty_slug;
  const otherName = asCounterparty ? f.actor_name : f.counterparty_name;
  const otherBasis = asCounterparty ? f.identity_basis : f.counterparty_basis;
  return (
    <tr className="border-t border-hairline align-top">
      <td className="pr-3 whitespace-nowrap">{f.date ?? "undated"}<div className="text-xs">{nice(f.date_kind)}</div></td>
      <td className="pr-3">
        {f.label}
        {f.repeat_of && <div className="text-xs">repeats an earlier row; kept, excluded from totals</div>}
        {f.quote && <div className="text-xs">“{f.quote}”</div>}
      </td>
      <td className="pr-3">
        {asCounterparty && <span className="text-xs">{f.kind === "reported_grant" ? "from " : "with "}</span>}
        <OtherEnd slug={other} name={otherName} basis={otherBasis} names={names} />
      </td>
      <td className="pr-3 text-right whitespace-nowrap">
        {f.metric && f.kind !== "minutes_mentions" ? money(f.amount) : f.amount ?? ""}
        <div className="text-xs">{nice(f.metric)} {nice(f.direction)}</div>
      </td>
      <td className="pr-3"><Source f={f} /><div className="text-xs">{nice(f.assertion_status)}</div></td>
    </tr>
  );
}

function SectionView({ s, slug, names }: { s: Section; slug: string; names: Record<string, string> }) {
  return (
    <section className="mt-8" aria-label={s.title}>
      <h2 className="font-semibold">{s.title}</h2>
      {s.totals.length > 0 && (
        <ul className="text-sm">
          {s.totals.map((t) => (
            <li key={`${t.side}/${t.metric}/${t.direction}`}>
              Total {t.side === "counterparty" ? "received" : ""} — {nice(t.metric)}, {nice(t.direction)}: {money(t.amount)}{" "}
              over {t.n} rows{t.note && <em> ({t.note})</em>}
            </li>
          ))}
        </ul>
      )}
      {s.rows.length === 0 ? (
        <p>None found in the covered sources.</p>
      ) : (
        <>
          <Pager kind={s.kind} page={s.page} pageSize={s.pageSize} total={s.total} slug={slug} />
          <table className="mt-2 text-sm">
            <thead>
              <tr>
                <th className="pr-3 text-left">date</th><th className="pr-3 text-left">what the document shows</th>
                <th className="pr-3 text-left">counterparty</th><th className="pr-3 text-right">amount</th>
                <th className="pr-3 text-left">source</th>
              </tr>
            </thead>
            <tbody>{s.rows.map((f) => <FactRow key={f.fact_key} f={f} slug={slug} names={names} />)}</tbody>
          </table>
        </>
      )}
      <Coverage rows={s.coverage} />
    </section>
  );
}

function ByYear({ rows }: { rows: YearRow[] }) {
  if (rows.length === 0) return <p>No dated facts attached.</p>;
  return (
    <table className="text-sm">
      <thead><tr><th className="pr-3 text-left">year</th><th className="pr-3 text-left">kind · metric · direction</th>
        <th className="pr-3 text-right">rows</th><th className="pr-3 text-right">amount</th></tr></thead>
      <tbody>
        {rows.map((r) => (
          <tr key={`${r.side}/${r.year}/${r.kind}/${r.metric}/${r.direction}`}>
            <td className="pr-3">{r.year}</td>
            <td className="pr-3">{[r.kind, r.metric, r.direction].filter(Boolean).map(nice).join(" · ")}
              {r.side === "counterparty" && " (received)"}</td>
            <td className="pr-3 text-right">{r.n}</td>
            <td className="pr-3 text-right">{r.amount === null || r.kind === "minutes_mentions" ? "" : money(r.amount)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Connections({ rows, searched, names }: { rows: Connection[]; searched: Searched | null;
  names: Record<string, string> }) {
  return (
    <section className="mt-8" aria-label="Connections">
      <h2 className="font-semibold">Connections</h2>
      {rows.length === 0 ? (
        <p>
          No connection found. Searched{searched ? `: forms ${searched.forms.map(nice).join(", ")}; ` +
            `${searched.commitments} commitments and ${searched.reported_grants} reported grants between reviewed actors, ` +
            `${searched.reviewed_cases} cases with reviewed roles, ${searched.officer_rows} officer rows` : " (not recorded)"}.
          Only reviewed actors and hops attached by id, EIN, a reviewed pattern or a reviewed role are considered.
        </p>
      ) : (
        rows.map((c) => (
          <article key={c.connection_id} className="border-t border-hairline py-2">
            <div><strong>{nice(c.form)}</strong>: {c.actors.map((a) => names[a] ?? a).join(" → ")}
              {c.person_identity === "unconfirmed" && <em> — same name, not confirmed the same person</em>}</div>
            <ol className="ml-5 list-decimal text-sm">
              {c.hops.map((h, i) => (
                <li key={i}>
                  {names[h.from] ?? h.from} → {names[h.to] ?? h.to}: {h.label} ({nice(h.kind)}{h.metric ? `, ${nice(h.metric)}` : ""})
                  <ul className="ml-4">
                    {h.sources.map((s) => (
                      <li key={s.fact_key}>{s.label} — {s.source_ref}, {s.date ?? "undated"} ({nice(s.date_kind)})
                        {s.amount !== null && `, ${nice(s.metric)} ${money(s.amount)}`}</li>
                    ))}
                  </ul>
                </li>
              ))}
            </ol>
          </article>
        ))
      )}
    </section>
  );
}

export default async function ActorPage({ params, searchParams }: {
  params: Promise<{ slug: string }>;
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  if (!operatorEnabled()) notFound(); // defense-in-depth if ever shipped/leaked
  const slug = decode((await params).slug);
  const sp = await searchParams;
  const one = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v);
  const page = Number.parseInt(one(sp.page) ?? "1", 10);
  const data = loadActorPage(slug, { section: one(sp.section), page: Number.isFinite(page) ? page : 1 });
  if (data.status === "absent") {
    return <main className="mx-[18px] mt-6 max-w-[1100px] text-body"><Absent path={data.path} /></main>;
  }
  if (data.status === "not_found") {
    return <main className="mx-[18px] mt-6 max-w-[1100px] text-body"><p>No actor “{slug}” in the index.</p></main>;
  }
  const { actor, names } = data;
  const sections = data.sections.filter((s) => s.kind !== "case_role");
  return (
    <main className="mx-[18px] mt-6 max-w-[1100px] text-body">
      <p className="text-sm"><Link className="underline" href="/actors">All actors</Link></p>
      <h1 className="font-semibold">{actor.name}</h1>
      <p className="text-sm">
        {nice(actor.kind)}
        {actor.registered ? (actor.reviewed ? " · registry entry, reviewed" : " · registry entry, NOT reviewed") :
          actor.kind === "person" ? " · not in the registry: a name listed on Form 990"
            : " · not in the registry: a Form 990 filer (never in connections)"}
        {actor.public_role && ` · public role: ${actor.public_role}`} · substrate as of {data.asOf}
      </p>
      {data.organization && (
        <p>Listed as an officer of <Link className="underline" href={`/actors/${data.organization.slug}`}>
          {data.organization.name}</Link>. This entry is a name on a return, not a confirmed identity.</p>
      )}

      <section className="mt-6" aria-label="By year">
        <h2 className="font-semibold">By year</h2>
        <ByYear rows={data.byYear} />
      </section>

      <section className="mt-8" aria-label="Case roles">
        <h2 className="font-semibold">Case roles (reviewed) and outcomes</h2>
        {data.caseRoles.length === 0 ? <p>No reviewed case role.</p> : (
          <ul className="text-sm">
            {data.caseRoles.map((f) => {
              const d = JSON.parse(f.detail) as { docket: string; role: string; outcome_kind: string | null;
                outcome_date: string | null; outcome_evidence: string | null };
              return (
                <li key={f.fact_key}>
                  <Link className="underline" href={caseHref(d.docket)}>{d.docket}</Link> — {nice(d.role)}
                  {f.counterparty_slug && <> against {names[f.counterparty_slug] ?? f.counterparty_slug}</>}; filed{" "}
                  {f.date ?? "undated"}; outcome: {d.outcome_kind ? `${nice(d.outcome_kind)} (${d.outcome_date}; ` +
                    `evidence: ${d.outcome_evidence})` : "not recorded"}
                </li>
              );
            })}
          </ul>
        )}
        <p className="text-sm">Sides come only from the reviewed case roles; everywhere else, {SIDE_UNKNOWN}.</p>
      </section>

      {sections.map((s) => <SectionView key={s.kind} s={s} slug={actor.slug} names={names} />)}

      <section className="mt-8" aria-label="Possible matches">
        <h2 className="font-semibold">Possible matches (not in totals or connections)</h2>
        {data.possible.length === 0 ? <p>None.</p> : (<>
          <Pager kind="possible" page={data.possiblePage} pageSize={data.pageSize} total={data.possibleTotal}
            slug={actor.slug} />
          <ul className="text-sm">
            {data.possible.map((f) => (
              <li key={f.fact_key}>
                {nice(f.kind)} · {f.date ?? "undated"} · {f.label}
                {f.amount !== null && f.kind !== "minutes_mentions" ? ` · ${money(f.amount)}` : ""} · attached{" "}
                {basisText(f.actor_slug === actor.slug ? f.identity_basis : f.counterparty_basis)}
                {(() => {
                  const ein = (JSON.parse(f.detail) as { recipient_ein?: string }).recipient_ein;
                  return ein ? ` · recipient EIN ${ein}` : "";
                })()}{" "}· <Source f={f} />
              </li>
            ))}
          </ul>
        </>)}
      </section>

      <section className="mt-8" aria-label="Affiliations">
        <h2 className="font-semibold">Affiliations (affiliation is not identity)</h2>
        {data.affiliations.length === 0 ? <p>None recorded in the registry.</p> : (
          <ul>{data.affiliations.map((a) => (
            <li key={a.slug}><Link className="underline" href={`/actors/${a.slug}`}>{a.name}</Link> ({nice(a.kind)})</li>
          ))}</ul>
        )}
      </section>

      {data.people.length > 0 && (
        <section className="mt-8" aria-label="People listed on returns">
          <h2 className="font-semibold">People listed on this organization&rsquo;s returns</h2>
          <ul className="text-sm">{data.people.map((p) => (
            <li key={p.slug}><Link className="underline" href={`/actors/${p.slug}`}>{p.name}</Link></li>
          ))}</ul>
        </section>
      )}

      <Connections rows={data.connections} searched={data.searched} names={names} />

      <section className="mt-8" aria-label="Coverage">
        <h2 className="font-semibold">Coverage of every input</h2>
        <Coverage rows={data.coverage.filter((c) => c.input !== "form_990_registry" || c.item === actor.slug)} />
      </section>
    </main>
  );
}
