"""The private operator report: effective persons and their cross-committee totals, every bucket's address
clusters (letters, never streets or hashes), and the queue, stale and conflict counts."""
from __future__ import annotations

from collections import Counter, defaultdict
from decimal import Decimal

from identity_person_evidence import Evidence
from identity_person_queue import Queue, total_cents


def build_report(q: Queue, evidence: Evidence) -> dict:
    rows = {r.row_id: r for r in evidence.rows}
    persons = []
    for p in q.state.persons:
        member = [rows[r] for r in sorted(p.rows) if r in rows]
        persons.append({
            "label": p.label, "target": p.target, "buckets": sorted({r.bucket for r in member}),
            "rows": len(member), "flows": len({r.moneyflow_id for r in member}),
            "committees": len({r.filer_id for r in member}), "total_cents": total_cents(member),
            "row_ids": [r.row_id for r in member]})
    buckets = []
    for b in q.buckets.values():
        clustered = {rid for c in b.clusters for rid in c.rows}
        buckets.append({
            "id": b.id, "rows": len(b.rows), "flows": len({r.moneyflow_id for r in b.rows}),
            "total_cents": b.total_cents, "classes": b.classes, "assigned": b.assigned, "payee_only": b.payee_only,
            "clusters": [{"label": c.label, "rows": len(c.rows),
                          "flows": len({rows[r].moneyflow_id for r in c.rows})} for c in b.clusters],
            "unclustered": dict(sorted(Counter(r.address_reason for r in b.rows
                                               if r.row_id not in clustered).items()))})
    items = defaultdict(int)
    for i in q.items:
        items[i.cls] += 1
    return {
        "as_of": q.as_of,
        "persons": sorted(persons, key=lambda p: (-p["total_cents"], p["label"])),
        "buckets": sorted(buckets, key=lambda b: b["id"]),
        "queue": {"items": dict(sorted(items.items())), "first_batch": len(q.batch)},
        "decisions": q.counts["decisions"], "conflicts": q.counts["conflicts"],
        "classes": {"inclusive": q.counts["inclusive"], "assigned": q.counts["assigned"],
                    "payee_only_would_be": q.counts["payee_only_would_be"], "a_pairs": q.counts["a_pairs"]},
        "overlap": q.counts["overlap"],
        "evidence": evidence.counts,
    }


def _usd(cents: int) -> str:
    return f"${Decimal(cents) / 100:,.2f}"


def render_report(report: dict) -> str:
    out = [f"# Person-identity operator report — as of {report['as_of']}", "",
           "Private. Clusters are letters; no street or address hash appears here.", "",
           "## Queue", "", f"- items by class: {report['queue']['items']}",
           f"- first batch: {report['queue']['first_batch']}", f"- decisions: {report['decisions']}",
           f"- conflicts: {report['conflicts']}", "",
           "## Classes", "", f"- inclusive: {report['classes']['inclusive']}",
           f"- assigned: {report['classes']['assigned']}",
           f"- payee-only buckets that would otherwise be queued: {report['classes']['payee_only_would_be']}",
           f"- A pairs (bucket, government Person): {report['classes']['a_pairs']}", "",
           "## Donor buckets with another edge", "", f"- buckets: {report['overlap']['buckets']}",
           f"- by edge: {report['overlap']['by_edge']}", f"- by class: {report['overlap']['by_class']}", "",
           "## Evidence", "", f"- {report['evidence']}", "",
           f"## Effective persons ({len(report['persons'])})", "",
           "| person | target | buckets | rows | flows | committees | total |", "|---|---|---|---|---|---|---|"]
    for p in report["persons"]:
        out.append(f"| {p['label']} | {p['target'] or '—'} | {', '.join(p['buckets'])} | {p['rows']} | "
                   f"{p['flows']} | {p['committees']} | {_usd(p['total_cents'])} |")
    out += ["", f"## Buckets ({len(report['buckets'])})", "",
            "| bucket | rows | flows | total | classes | clusters (rows) | no cluster |", "|---|---|---|---|---|---|---|"]
    for b in report["buckets"]:
        clusters = ", ".join(f"{c['label']}({c['rows']})" for c in b["clusters"]) or "—"
        none = ", ".join(f"{k}: {v}" for k, v in b["unclustered"].items()) or "—"
        classes = "/".join(b["classes"]) + (" payee-only" if b["payee_only"] else "")
        out.append(f"| {b['id']} | {b['rows']} | {b['flows']} | {_usd(b['total_cents'])} | {classes or '—'} | "
                   f"{clusters} | {none} |")
    return "\n".join(out) + "\n"
