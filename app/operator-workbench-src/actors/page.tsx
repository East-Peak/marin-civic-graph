// Operator-local route group — copied into src/app/(operator-workbench)/ ONLY under OPERATOR_WORKBENCH=1, never in
// a public build. /actors: every registry actor by kind, one line of counts each (facts attached by id, EIN, a
// reviewed pattern or a reviewed role; possible matches counted apart). Plain on purpose.
import Link from "next/link";
import { notFound } from "next/navigation";
import { operatorEnabled } from "@/lib/operator-gate";
import { KIND_ORDER, loadActorList, type ListEntry } from "../_lib/actors";
import { Absent } from "../_lib/actor-parts";

export const dynamic = "force-dynamic";

function countLine(a: ListEntry): string {
  const parts = KIND_ORDER.filter((k) => a.counts[k]).map((k) => `${a.counts[k]} ${k.replaceAll("_", " ")}`);
  const line = parts.length ? parts.join(" · ") : "no attached facts";
  return a.possible ? `${line} · ${a.possible} possible matches` : line;
}

export default function ActorsPage() {
  if (!operatorEnabled()) notFound(); // defense-in-depth if ever shipped/leaked
  const data = loadActorList();
  return (
    <main className="mx-[18px] mt-6 max-w-[1000px] text-body">
      <h1 className="font-semibold">Actor files (operator only)</h1>
      {data.status === "absent" ? (
        <Absent path={data.path} />
      ) : (
        <>
          <p className="text-sm">Substrate as of {data.asOf}. Counts are facts the documents show; they are not scores.</p>
          {data.groups.map((g) => (
            <section key={g.kind} className="mt-6">
              <h2 className="font-semibold">{g.kind.replaceAll("_", " ")}</h2>
              <ul className="mt-1 space-y-1">
                {g.actors.map((a) => (
                  <li key={a.slug}>
                    <Link className="underline" href={`/actors/${a.slug}`}>{a.name}</Link>
                    <span className="text-sm"> — {countLine(a)}</span>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </>
      )}
    </main>
  );
}
