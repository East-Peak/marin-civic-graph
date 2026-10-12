"""Stuart's identity review queue: which donor buckets to look at, in what order, with what evidence.

Code never decides identity. It ranks questions:
  B  the bucket node itself holds a government role (cast a vote, filed a Form 700, controls a committee): which of
     its address clusters are that official's own?
  A  the bucket's reported name matches a government Person on another node: one item per (bucket, that Person).
  C  the bucket's rows form two or more address clusters (top 25 by total): one person or several?
Each bucket goes to the first class that applies. Payee-only buckets (paid by a committee, no role on the node) are
counted, never queued. Within a class: buckets whose rows form one address cluster first (same name + same address
is the strongest evidence, still a question), then total cents, then id. Stale decisions and conflicts come first.
Review text never shows a street or an address hash: clusters are letters.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

import identity_person_decisions as dec
from contributor_detail import classify, display
from identity_person_evidence import Evidence, Graph, Row, canonical_json, government_roles
from identity_person_key import Key

C_LIMIT = 25
BATCH = 60
SUFFIXES = {"JR", "SR", "II", "III", "IV", "V"}
TITLES = {"MR", "MRS", "MS", "MISS", "DR", "HON", "REV"}
GENERIC = {"RETIRED", "NONE", "SELF EMPLOYED", "SELF", "N A", "NA", "NOT EMPLOYED", "HOMEMAKER", "UNEMPLOYED",
           "INFORMATION REQUESTED", "INFO REQUESTED", "BEST EFFORTS", "REQUESTED"}
CAUTIONS = (
    "Same name + same address is the strongest evidence and still not proof (household namesakes, omitted "
    "suffixes, shared business addresses).",
    "Multiple address clusters do not show different people: people move.",
    "Generic employers and occupations (retired, none, self-employed, n/a …) are not evidence.",
    "There is no government-side address source: the official's side has names and roles only.",
    "Government Person nodes may themselves be name-joined across pipelines: check each fact's provenance.",
    "Never infer coordination, favoritism or patronage from any of this.",
)


# ---------------------------------------------------------------------------
# Names
# ---------------------------------------------------------------------------

def _tokens(text) -> list[str]:
    if not isinstance(text, str):
        return []
    folded = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    return re.sub(r"[^A-Z0-9]+", " ", folded.upper()).split()


@dataclass(frozen=True)
class Name:
    first: tuple[str, ...]
    last: tuple[str, ...]
    suffix: str | None
    comma: bool = True  # government names: False when written "First … Last" (last = the whole token list)


def _split_suffix(tokens: list[str]) -> tuple[list[str], str | None]:
    if len(tokens) > 1 and tokens[-1] in SUFFIXES:
        return tokens[:-1], tokens[-1]
    return tokens, None


def donor_name(name: dict) -> Name | None:
    """A reported contributor name, or None when it has no first or no last name (never last-name-only)."""
    first = _tokens(name.get("first"))
    while first and first[0] in TITLES:
        first = first[1:]
    first, s1 = _split_suffix(first)
    last, s2 = _split_suffix(_tokens(name.get("last")))
    suffix = " ".join(t for t in _tokens(name.get("suffix")) if t in SUFFIXES) or s1 or s2
    return Name(tuple(first), tuple(last), suffix) if first and last else None


def government_names(props: dict) -> list[Name]:
    out = []
    for text in [props.get("name"), *(props.get("aliases") or [])]:
        if not isinstance(text, str):
            continue
        if "," in text:
            before, after = text.split(",", 1)
            first = _tokens(after)
            while first and first[0] in TITLES:
                first = first[1:]
            first, s1 = _split_suffix(first)
            last, s2 = _split_suffix(_tokens(before))
            if first and last:
                out.append(Name(tuple(first), tuple(last), s1 or s2, True))
        else:
            tokens = _tokens(text)
            while tokens and tokens[0] in TITLES:
                tokens = tokens[1:]
            tokens, suffix = _split_suffix(tokens)
            if len(tokens) >= 2:
                out.append(Name((tokens[0],), tuple(tokens), suffix, False))
    return out


def _first_compatible(a: str, b: str) -> bool:
    return a == b or (len(a) == 1 and b.startswith(a)) or (len(b) == 1 and a.startswith(b))


def name_matches(donor: Name | None, gov: Name) -> bool:
    """Same last name (a token suffix of an uncommaed government name), compatible first name, agreeing suffixes."""
    if donor is None or (donor.suffix and gov.suffix and donor.suffix != gov.suffix):
        return False
    if not _first_compatible(donor.first[0], gov.first[0]):
        return False
    if gov.comma:
        return gov.last == donor.last
    n = len(donor.last)
    return len(gov.last) >= n + 1 and gov.last[-n:] == donor.last


# ---------------------------------------------------------------------------
# Buckets and items
# ---------------------------------------------------------------------------

@dataclass
class Cluster:
    label: str
    rows: list[str]


@dataclass
class Bucket:
    id: str
    rows: list[Row]
    clusters: list[Cluster]
    total_cents: int
    matches: list[str] = field(default_factory=list)
    roles: dict = field(default_factory=dict)
    payee: bool = False
    classes: list[str] = field(default_factory=list)
    assigned: str | None = None

    @property
    def payee_only(self) -> bool:
        return self.payee and not self.roles


@dataclass
class Item:
    id: str
    cls: str  # conflict | stale | B | A | C
    bucket: str | None
    target: str | None
    rows: list[str]
    n_clusters: int = 0
    total_cents: int = 0
    decisions: list[str] = field(default_factory=list)
    detail: dict = field(default_factory=dict)


@dataclass
class Queue:
    buckets: dict[str, Bucket]
    items: list[Item]
    counts: dict
    completeness: dict
    state: dec.State
    as_of: str
    clusters: dict[str, str]  # row id -> cluster label or "— <reason>"
    target_fps: dict[str, str]  # government Person id -> its current target fingerprint (queued targets)

    @property
    def batch(self) -> list[Item]:
        return self.items[:BATCH]

    def cluster_of(self, row_id: str) -> str:
        return self.clusters[row_id]


def _cents(amount: str) -> int:
    return int(Decimal(amount) * 100)


def total_cents(rows) -> int:
    """Signed total over distinct flows (rows of one flow share its amount)."""
    flows = {}
    for r in sorted(rows, key=lambda r: r.row_id):
        flows.setdefault(r.moneyflow_id, _cents(r.amount))
    return sum(flows.values())


def _clusters(rows: list[Row]) -> list[Cluster]:
    first_seen: dict[str, tuple] = {}
    members: dict[str, list[str]] = defaultdict(list)
    for r in rows:
        if r.address_hash:
            seen = (r.tran_date or "", r.row_id)
            first_seen[r.address_hash] = min(first_seen.get(r.address_hash, seen), seen)
            members[r.address_hash].append(r.row_id)
    ordered = sorted(first_seen, key=lambda h: first_seen[h])
    return [Cluster(_letter(i), sorted(members[h])) for i, h in enumerate(ordered)]


def _letter(i: int) -> str:
    return chr(65 + i) if i < 26 else _letter(i // 26 - 1) + chr(65 + i % 26)


def _payee(graph: Graph, pid: str) -> bool:
    return any(d == "in" and rel == "TO_TARGET" and graph.props.get(o, {}).get("flow_type") == "expenditure"
               for d, rel, o, _ in graph.person_edges.get(pid, ()))


def _item_id(*parts) -> str:
    return "q-" + str(parts[0]) + "-" + hashlib.sha256(canonical_json(list(parts))).hexdigest()[:10]


def target_fingerprints(key: Key, graph: Graph, decisions) -> dict[str, str]:
    return {t: fp for t in sorted({d.target for d in decisions if d.target})
            if (fp := dec.target_fingerprint(key, graph, t))}


def _government_index(graph: Graph) -> dict[str, list[tuple[str, Name]]]:
    """Government Persons by the last token of each name variant."""
    index: dict[str, list[tuple[str, Name]]] = defaultdict(list)
    for pid in sorted(graph.person_edges):
        if graph.has(pid, "Person") and government_roles(graph, pid):
            for name in government_names(graph.props.get(pid, {})):
                index[name.last[-1]].append((pid, name))
    return index


def _resolved(item_bucket: Bucket, target: str | None, state: dec.State) -> bool:
    rows = {r.row_id for r in item_bucket.rows}
    effective = [d for d in state.decisions if state.status[d.digest] == "effective"]
    if target is not None:
        covered = set()
        for d in effective:
            if d.kind in ("is", "reject") and d.target == target:
                covered |= d.rows
            if d.kind == "defer" and d.target == target and rows <= d.rows:
                return True
        return rows <= covered
    if any(d.kind == "defer" and rows <= d.rows for d in effective):
        return True
    # components of effective `same` decisions; rows no `same` covers are singletons
    component = {}
    for d in effective:
        if d.kind == "same" and d.rows & rows:
            label = min(d.rows)
            for r in d.rows:
                component.setdefault(r, label)
    comps = sorted({component.get(r, r) for r in rows})
    if len(comps) == 1:
        return any(d.kind == "same" and rows <= d.rows for d in effective) or \
            all(r in component for r in rows)
    members = defaultdict(set)
    for r in rows:
        members[component.get(r, r)].add(r)
    for i, a in enumerate(comps):
        for b in comps[i + 1:]:
            if not any(d.kind == "distinct" and _separates(d, members[a], members[b]) for d in effective):
                return False
    return True


def _separates(d, a: set[str], b: set[str]) -> bool:
    groups_a = {i for i, g in enumerate(d.groups) if a & set(g)}
    groups_b = {i for i, g in enumerate(d.groups) if b & set(g)}
    return bool(groups_a and groups_b) and not (groups_a & groups_b)


def build_queue(evidence: Evidence, state: dec.State, key: Key, as_of: str) -> Queue:
    graph = evidence.graph
    by_bucket: dict[str, list[Row]] = defaultdict(list)
    for r in evidence.rows:
        by_bucket[r.bucket].append(r)
    index = _government_index(graph)
    buckets: dict[str, Bucket] = {}
    for bid in sorted(by_bucket):
        rows = sorted(by_bucket[bid], key=lambda r: ((r.tran_date or ""), r.row_id))
        b = Bucket(bid, rows, _clusters(rows), total_cents(rows))
        b.roles = government_roles(graph, bid)
        b.payee = _payee(graph, bid)
        names = {donor_name(r.name) for r in rows} - {None}
        b.matches = sorted({pid for n in names for pid, g in index.get(n.last[-1], ()) if pid != bid
                            and name_matches(n, g)})
        b.classes = [c for c, applies in (("B", bool(b.roles)), ("A", bool(b.matches)),
                                          ("C", len(b.clusters) >= 2)) if applies]
        b.assigned = b.classes[0] if b.classes else None
        buckets[bid] = b

    def rank(b: Bucket, target: str | None = None):
        return (0 if len(b.clusters) == 1 else 1, -b.total_cents, b.id, target or "")

    items: list[Item] = []
    queued = [b for b in buckets.values() if b.assigned and not b.payee_only]
    for b in sorted((b for b in queued if b.assigned == "B"), key=rank):
        if not _resolved(b, b.id, state):
            items.append(_item("B", b, b.id))
    for b, t in sorted(((b, t) for b in queued if b.assigned == "A" for t in b.matches), key=lambda x: rank(*x)):
        if not _resolved(b, t, state):
            items.append(_item("A", b, t))
    open_c = [b for b in sorted((b for b in queued if b.assigned == "C"), key=lambda b: (-b.total_cents, b.id))
              if not _resolved(b, None, state)][:C_LIMIT]
    items += [_item("C", b, None) for b in sorted(open_c, key=rank)]

    redo = [Item(_item_id("conflict", c.id), "conflict", None, None,
                 sorted({r for d in state.decisions if d.digest in c.decisions for r in d.rows}),
                 decisions=list(c.decisions), detail={"conflict": c.id, "reasons": list(c.reasons)})
            for c in state.conflicts]
    for d in state.decisions:
        if state.status[d.digest] == "stale" or state.suspended.get(d.digest) == "no_covering_same":
            items_detail = state.stale.get(d.digest) or {"basis": ["the same this is rests on is not effective"]}
            redo.append(Item(_item_id("stale", d.digest), "stale", None, d.target, sorted(d.rows),
                             decisions=[d.digest], detail={"line": d.number, "kind": d.kind, "diff": items_detail}))
    items = sorted((i for i in redo if i.cls == "conflict"), key=lambda i: i.id) + \
        sorted((i for i in redo if i.cls == "stale"), key=lambda i: i.id) + items

    clusters = {}
    for b in buckets.values():
        for c in b.clusters:
            for rid in c.rows:
                clusters[rid] = c.label
        for r in b.rows:
            clusters.setdefault(r.row_id, f"— {r.address_reason}")
    counts = _counts(buckets, items, state, graph)
    target_fps = {t: fp for t in sorted({i.target for i in items if i.target})
                  if (fp := dec.target_fingerprint(key, graph, t))}
    q = Queue(buckets, items, counts, {}, state, as_of, clusters, target_fps)
    q.completeness = _completeness(q, evidence)
    return q


def _item(cls: str, b: Bucket, target: str | None) -> Item:
    return Item(_item_id(cls, b.id, target), cls, b.id, target, [r.row_id for r in b.rows], len(b.clusters),
                b.total_cents)


def _counts(buckets: dict[str, Bucket], items: list[Item], state: dec.State, graph: Graph) -> dict:
    inclusive = {"B": 0, "A": 0, "C": 0, "payee": 0, "payee_only": 0}
    assigned: dict[str, int] = {}
    would_be: dict[str, int] = {}
    for b in buckets.values():
        for c in b.classes:
            inclusive[c] += 1
        inclusive["payee"] += b.payee
        inclusive["payee_only"] += b.payee_only
        if b.payee_only and b.assigned:
            would_be[b.assigned] = would_be.get(b.assigned, 0) + 1
        elif b.assigned:
            assigned[b.assigned] = assigned.get(b.assigned, 0) + 1
    by_cls: dict[str, int] = {}
    for i in items:
        by_cls[i.cls] = by_cls.get(i.cls, 0) + 1
    return {
        "inclusive": inclusive, "assigned": dict(sorted(assigned.items())),
        "payee_only_would_be": dict(sorted(would_be.items())),
        "a_pairs": sum(len(b.matches) for b in buckets.values() if b.assigned == "A" and not b.payee_only),
        "items": by_cls, "queue": len(items), "first_batch": min(len(items), BATCH),
        "decisions": {s: sum(1 for v in state.status.values() if v == s) for s in ("effective", "stale", "suspended")},
        "conflicts": len(state.conflicts),
        "overlap": overlap_audit(graph, buckets),
    }


def overlap_audit(graph: Graph, buckets: dict[str, Bucket]) -> dict:
    """Donor buckets (Persons with a FROM_SOURCE contribution) that also have any other edge: by edge kind and by
    the class each was assigned (or why none)."""
    by_edge: dict[str, int] = defaultdict(int)
    by_class: dict[str, int] = defaultdict(int)
    total = 0
    for pid in sorted(graph.person_edges):
        edges = graph.person_edges[pid]
        donor = any(d == "out" and rel == "FROM_SOURCE" and graph.props.get(o, {}).get("flow_type") == "contribution"
                    for d, rel, o, _ in edges)
        if not donor:
            continue
        kinds = set()
        for d, rel, other, _ in edges:
            flow_type = graph.props.get(other, {}).get("flow_type")
            if d == "out" and rel == "FROM_SOURCE" and flow_type == "contribution":
                continue
            label = sorted(graph.labels.get(other, ())) or ["?"]
            kinds.add(f"{d}:{rel}:{label[0]}" + (f":{flow_type}" if flow_type else ""))
        if not kinds:
            continue
        total += 1
        for k in kinds:
            by_edge[k] += 1
        b = buckets.get(pid)
        cls = "not_in_scope" if b is None else "payee_only" if b.payee_only else b.assigned or "none"
        by_class[cls] += 1
    return {"buckets": total, "by_edge": dict(sorted(by_edge.items())), "by_class": dict(sorted(by_class.items()))}


# ---------------------------------------------------------------------------
# Review files
# ---------------------------------------------------------------------------

ROW_FIELDS = ("committee", "date", "amount", "occupation", "employer", "city", "zip5", "cluster")


def _row_fields(q: Queue, r: Row) -> dict[str, str]:
    """Each required field's value, or `missing: <reason>`."""
    out = {"committee": r.committee or "missing: source_missing", "date": r.tran_date or "missing: source_missing",
           "amount": f"${Decimal(r.amount):,.2f}"}
    for field_name, key in (("occupation", "occupation"), ("employer", "employer"), ("city", "city")):
        value = display(r.reported.get(key)) if isinstance(r.reported.get(key), (str, type(None))) else None
        if value is None:
            out[field_name] = "missing: " + ("source_missing" if r.reported.get(key) is None else "non_text_cell")
        elif " ".join(_tokens(value)) in GENERIC:
            out[field_name] = f"{value} (generic — not evidence)"
        else:
            out[field_name] = value
    outcome = classify("zip5", r.reported.get("zip"))
    out["zip5"] = outcome.value or f"missing: {outcome.rule}"
    out["cluster"] = q.cluster_of(r.row_id)
    return out


def _completeness(q: Queue, evidence: Evidence) -> dict:
    rows = {r.row_id: r for r in evidence.rows}
    present, reasons, missing = 0, defaultdict(int), 0
    for item in q.batch:
        for rid in item.rows:
            if rid not in rows:
                reasons["row gone"] += 1
                continue
            for name, value in _row_fields(q, rows[rid]).items():
                if value.startswith("missing: "):
                    reasons[f"{name}: {value[9:]}"] += 1
                elif value.startswith("— "):
                    reasons[f"cluster: {value[2:]}"] += 1
                elif value:
                    present += 1
                else:
                    missing += 1
        if item.target and not government_roles(evidence.graph, item.target):
            reasons["government facts: no role"] += 1
    return {"present": present, "missing_with_reason": dict(sorted(reasons.items())),
            "missing_without_reason": missing}


def _name(r: Row) -> str:
    parts = [r.name.get("last") or "∅", r.name.get("first") or "∅"]
    return ", ".join(parts) + (f" {r.name['suffix']}" if r.name.get("suffix") else "")


def _facts(graph: Graph, pid: str) -> list[str]:
    props = graph.props.get(pid, {})
    lines = [f"- **{pid}** — name {props.get('name')!r}" +
             (f", aliases {props.get('aliases')!r}" if props.get("aliases") else "")]
    for kind, facts in government_roles(graph, pid).items():
        shown = facts[:5]
        for f in shown:
            if kind == "controller":
                name = graph.props.get(f["committee"], {}).get("name")
                lines.append(f"  - controller: {f['committee']} ({name}) — CONTROLLED_BY edge {f['edge']}")
            elif kind == "form700_filer":
                lines.append(f"  - form700_filer: {f['filing']} — filer_name {f['filer_name']!r}, filed_at "
                             f"{f['filed_at']} (FILED_BY edge)")
            else:
                lines.append(f"  - cast_vote: {f['decision']} — CAST_VOTE edge {f['edge']}")
        if len(facts) > len(shown):
            lines.append(f"  - … {len(facts) - len(shown)} more {kind} fact(s)")
    return lines


def template_options(q: Queue, evidence: Evidence, item: Item) -> list[tuple[str, list[str]]]:
    """Ready-to-copy decision lines for an item, as labelled options (reviewer stuart, dated as_of). Each option
    is copied whole; an `is` always follows the `same` it rests on."""
    rows = {r.row_id: r for r in evidence.rows}
    item_rows = [rows[r] for r in item.rows if r in rows]
    fps = {r.row_id: r.fp for r in item_rows}
    everyone = [r.row_id for r in item_rows]
    if item.cls in ("conflict", "stale") or not everyone:
        return []

    def line(kind, groups, **extra):
        return dec.decision_line(kind, groups, fps, "stuart", q.as_of, **extra)

    b = q.buckets[item.bucket]
    options = []
    if item.target:
        t, tfp = item.target, q.target_fps[item.target]

        def same_is(group):
            same = line("same", [group])
            return [same, line("is", [group], target=t, target_fp=tfp, basis=dec.line_digest(same))]
        options.append((f"All {len(everyone)} rows are {t}", same_is(everyone)))
        if len(b.clusters) > 1:
            for c in b.clusters:
                rest = [r for r in everyone if r not in c.rows]
                options.append((f"Only cluster {c.label} ({len(c.rows)} rows) is {t}; the other rows are not",
                                same_is(c.rows) + ([line("reject", [rest], target=t, target_fp=tfp)] if rest else [])))
        options += [(f"None of these rows is {t}", [line("reject", [everyone], target=t, target_fp=tfp)]),
                    ("Cannot decide from these inputs", [line("defer", [everyone], target=t, target_fp=tfp)])]
    else:
        options.append((f"All {len(everyone)} rows are one person", [line("same", [everyone])]))
        clustered = [c.rows for c in b.clusters]
        unclustered = len(everyone) - sum(len(g) for g in clustered)
        if len(clustered) > 1:
            label = "Each address cluster is a different person" + (
                f" ({unclustered} row(s) without a cluster stay open)" if unclustered else "")
            options.append((label, [line("same", [g]) for g in clustered if len(g) > 1] +
                            [line("distinct", clustered)]))
        options.append(("Cannot decide from these inputs", [line("defer", [everyone])]))
    return options


def template_lines(q: Queue, evidence: Evidence, item: Item) -> list[str]:
    return [text for _, lines in template_options(q, evidence, item) for text in lines]


def diff_text(diff: dict) -> list[str]:
    """What changed, in words: field names only ("address changed"), never a value."""
    out = []
    for where, what in sorted(diff.items()):
        words = ["row gone (amended away or no longer counted)" if w == "row gone" else
                 w if where in ("target", "latched", "basis") else f"{w} changed" for w in what]
        out.append(f"{where}: {', '.join(words)}")
    return out


def _row_table(q: Queue, rows: dict, ids: list[str]) -> list[str]:
    if not ids:
        return []
    out = ["| row | reported name | " + " | ".join(ROW_FIELDS) + " |", "|" + "---|" * (len(ROW_FIELDS) + 2)]
    for rid in ids:
        r = rows[rid]
        fields = _row_fields(q, r)
        out.append(f"| {rid} | {_name(r)} | " + " | ".join(fields[f] for f in ROW_FIELDS) + " |")
    return out + [""]


def render_batch(q: Queue, evidence: Evidence) -> str:
    rows = {r.row_id: r for r in evidence.rows}
    out = [f"# Identity review — first batch ({len(q.batch)} of {len(q.items)} items), as of {q.as_of}", "",
           "Read before deciding:", *[f"- {c}" for c in CAUTIONS], "",
           "To decide: pick one option per item, copy all of its lines into a file (one per line), and run "
           "`identity_person.py ingest --build <this build> <that file>` (docs/person-identity-runbook.md). "
           "Skipping an item is fine: it stays in the queue.", ""]
    for n, item in enumerate(q.batch, start=1):
        out += [f"## {n}. {item.id} · {item.cls}" + (f" · {item.bucket}" if item.bucket else "") +
                (f" → {item.target}" if item.target else ""), ""]
        if item.cls in ("conflict", "stale"):
            out += [f"- decision(s): {', '.join(item.decisions)}" +
                    (f" (line {item.detail['line']}, {item.detail['kind']})" if "line" in item.detail else "")]
            if item.cls == "conflict":
                out.append(f"- why: {'; '.join(item.detail['reasons'])}")
            else:
                out += [f"- {line}" for line in diff_text(item.detail["diff"])]
            out += ["- Every decision listed is suspended (not effective). Edit or delete the line(s) in the decision "
                    "file, or re-ingest a line after review to revalidate it.", ""]
            out += _row_table(q, rows, [r for r in item.rows if r in rows])
        else:
            b = q.buckets[item.bucket]
            out.append(f"{len(b.rows)} row(s), {len(b.clusters)} address cluster(s), total "
                       f"${Decimal(b.total_cents) / 100:,.2f} over distinct flows.")
            if item.cls == "B" and b.matches:
                out.append(f"Also name-matches: {', '.join(b.matches)}")
            out += [""] + _row_table(q, rows, item.rows)
            if item.target:
                out += ["Government Person (facts with provenance):", *_facts(evidence.graph, item.target), ""]
        for n_option, (label, lines) in enumerate(template_options(q, evidence, item), start=1):
            out += [f"**Option {n_option} — {label}** ({len(lines)} line{'s' if len(lines) > 1 else ''}):", "",
                    "```", *lines, "```", ""]
    return "\n".join(out) + "\n"


def queue_json(q: Queue) -> dict:
    return {
        "as_of": q.as_of, "counts": q.counts, "completeness": q.completeness,
        "items": [{"id": i.id, "class": i.cls, "bucket": i.bucket, "target": i.target, "rows": i.rows,
                   "clusters": i.n_clusters, "total_cents": i.total_cents, "decisions": i.decisions,
                   "detail": i.detail} for i in q.items],
    }
