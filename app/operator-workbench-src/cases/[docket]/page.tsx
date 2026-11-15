// Operator-local route group — never in a public build. /cases/[docket]: one cached docket — caption, court, dates,
// cause, link, every party, attorney and firm as the cache gives them — and its roles. Sides come only from the
// reviewed case roles; the cache does not say which attorney or firm acted for which party.
import Link from "next/link";
import { notFound } from "next/navigation";
import { operatorEnabled } from "@/lib/operator-gate";
import { SIDE_UNKNOWN, loadCasePage } from "../../_lib/actors";
import { Absent } from "../../_lib/actor-parts";

export const dynamic = "force-dynamic";

const nice = (s: string | null) => (s ?? "").replaceAll("_", " ");

function decode(raw: string): string {
  try {
    return decodeURIComponent(raw);
  } catch {
    return raw;
  }
}

function List({ title, items, empty }: { title: string; items: string[]; empty: string }) {
  return (
    <section className="mt-4" aria-label={title}>
      <h2 className="font-semibold">{title}</h2>
      {items.length === 0 ? <p>{empty}</p> : <ul className="text-sm">{items.map((x) => <li key={x}>{x}</li>)}</ul>}
    </section>
  );
}

export default async function CasePage({ params }: { params: Promise<{ docket: string }> }) {
  if (!operatorEnabled()) notFound(); // defense-in-depth if ever shipped/leaked
  const docket = decode((await params).docket);
  const data = loadCasePage(docket);
  if (data.status === "absent") return <main className="mx-[18px] mt-6 text-body"><Absent path={data.path} /></main>;
  if (data.status === "not_found") {
    return <main className="mx-[18px] mt-6 text-body"><p>No cached docket “{docket}” in the index.</p></main>;
  }
  const c = data.case;
  return (
    <main className="mx-[18px] mt-6 max-w-[1000px] text-body">
      <p className="text-sm"><Link className="underline" href="/actors">All actors</Link></p>
      <h1 className="font-semibold">{c.caption}</h1>
      <p className="text-sm">
        {c.docket} · {c.court} · filed {c.filed ?? "unknown"} · closed {c.closed ?? "open or unknown"} · {c.cause}
        {c.courtlistener_url && <> · <a className="underline" href={c.courtlistener_url} target="_blank"
          rel="noreferrer noopener">CourtListener docket</a></>}
      </p>

      <section className="mt-4" aria-label="Reviewed roles">
        <h2 className="font-semibold">Reviewed roles</h2>
        {c.roles_reviewed ? (
          <>
            <ul className="text-sm">
              {data.roles.map((f) => (
                <li key={f.fact_key}>
                  {nice((JSON.parse(f.detail) as { role: string }).role)}:{" "}
                  <Link className="underline" href={`/actors/${f.actor_slug}`}>{f.actor_name}</Link>
                </li>
              ))}
            </ul>
            <p className="text-sm">
              Outcome: {c.outcome_kind ? `${nice(c.outcome_kind)} (${c.outcome_date}); evidence: ${c.outcome_evidence}`
                : "not recorded"}
            </p>
          </>
        ) : (
          <p>No reviewed roles for this docket: every party, attorney and firm below is {SIDE_UNKNOWN}.</p>
        )}
      </section>

      <List title="Parties (as the docket cache lists them)" items={c.parties} empty="No party listed in the source." />
      <List title={`Attorneys (${SIDE_UNKNOWN})`} items={c.attorneys} empty={c.attorney_note ?? "No attorney listed in the source."} />
      <List title={`Firms (${SIDE_UNKNOWN})`} items={c.firms} empty="No firm listed in the source." />

      <section className="mt-4" aria-label="Registry actors on this docket">
        <h2 className="font-semibold">Registry actors named on this docket</h2>
        {data.appearances.length === 0 ? <p>None matched by a registry pattern.</p> : (
          <ul className="text-sm">
            {data.appearances.map((f) => (
              <li key={f.fact_key}>
                <Link className="underline" href={`/actors/${f.actor_slug}`}>{f.actor_name}</Link> — {f.label} (“{f.quote}”)
                {f.identity_basis !== "pattern_reviewed" && " · possible match only"}
              </li>
            ))}
          </ul>
        )}
      </section>
    </main>
  );
}
