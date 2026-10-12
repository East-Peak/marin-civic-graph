"""Stuart's person-identity decisions: one reviewed JSONL file, its grammar, and its effective state.

A line is one decision over explicit groups of row ids, with the keyed fingerprint of every covered row:
  same     [G]                  the rows of G are one person
  distinct [G1, G2, ...]        no row of one group is the same person as a row of another (groups do not imply
                                sameness inside themselves)
  is       [G] target basis     the person of G is the government Person `target`; `basis` is the digest of the
                                `same` line it rests on, which must cover G
  reject   [G] target           the rows of G are not `target`
  defer    [G1, ...] [target]   cannot decide from these inputs
Git is the history: reversing a decision is editing or deleting its line. Recomputed on every run, a decision is
stale when a covered row changed, was amended away or is gone (or its target changed), and stays stale once
observed (the latch) until Stuart re-ingests it. Contradictions suspend every decision involved.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from identity_person_evidence import FP_PATTERN, Graph, IdentityError, _hmac, canonical_json, diff_fields
from identity_person_evidence import government_roles
from identity_person_key import Key

KINDS = ("same", "distinct", "is", "reject", "defer")
NOTE_CODES = ("household_namesake", "suffix_omitted", "moved", "shared_business_address", "generic_employer_only",
              "same_employer", "same_occupation", "insufficient_evidence", "official_record_differs", "other")
KEYS = {"v", "kind", "groups", "fp", "reviewer", "date", "target", "target_fp", "basis", "note"}
_ROW = re.compile(r"r-[0-9a-f]{20}")
_TARGET = re.compile(r"person-[a-z0-9][a-z0-9-]{0,199}")
_TF = re.compile(r"tf1:k[1-9][0-9]{0,5}:[0-9a-f]{64}")
_DIGEST = re.compile(r"d-[0-9a-f]{16}")
_REVIEWER = re.compile(r"[a-z][a-z0-9._-]{0,31}")


class DecisionError(IdentityError):
    """A decision line is malformed, or the file holds the same line twice."""


@dataclass(frozen=True)
class Decision:
    number: int
    kind: str
    groups: tuple[tuple[str, ...], ...]
    fp: dict = field(compare=False, hash=False)
    reviewer: str = ""
    date: str = ""
    target: str | None = None
    target_fp: str | None = None
    basis: str | None = None
    note: str | None = None
    line: str = ""
    digest: str = ""

    @property
    def rows(self) -> frozenset[str]:
        return frozenset(r for g in self.groups for r in g)


def canonical_line(obj: dict) -> str:
    return canonical_json(obj).decode()


def line_digest(text: str) -> str:
    return "d-" + hashlib.sha256(text.encode()).hexdigest()[:16]


def parse_line(text: str, number: int) -> Decision:
    def fail(why: str):
        raise DecisionError(f"line {number}: {why}")

    try:
        obj = json.loads(text)
    except ValueError:
        obj = None
    if not isinstance(obj, dict):
        fail("not a JSON object")
    if set(obj) - KEYS:
        fail(f"unknown key(s); allowed: {', '.join(sorted(KEYS))}")
    for name in ("v", "kind", "groups", "fp", "reviewer", "date"):
        if name not in obj:
            fail(f"missing {name}")
    if obj["v"] != 1:
        fail("v must be 1")
    kind = obj["kind"]
    if kind not in KINDS:
        fail(f"kind must be one of {', '.join(KINDS)}")
    if not isinstance(obj["reviewer"], str) or not _REVIEWER.fullmatch(obj["reviewer"]):
        fail("reviewer must be a short lowercase handle")
    try:
        ok = isinstance(obj["date"], str) and date.fromisoformat(obj["date"]).isoformat() == obj["date"]
    except ValueError:
        ok = False
    if not ok:
        fail("date must be YYYY-MM-DD")
    groups = obj["groups"]
    if not isinstance(groups, list) or not groups or not all(isinstance(g, list) for g in groups):
        fail("groups must be a list of row-id lists")
    for g in groups:
        if not g:
            fail("groups: empty group")
        if not all(isinstance(r, str) and _ROW.fullmatch(r) for r in g):
            fail("groups: not a row id")
        if g != sorted(set(g)):
            fail("groups: each group must be sorted, without repeats")
    if [g[0] for g in groups] != sorted(g[0] for g in groups):
        fail("groups must be sorted by their first row id")
    rows = [r for g in groups for r in g]
    if len(rows) != len(set(rows)):
        fail("groups: a row appears twice")
    if kind in ("same", "is", "reject") and len(groups) != 1:
        fail(f"{kind} takes one group")
    if kind == "distinct" and len(groups) < 2:
        fail("distinct takes two or more groups")
    target = obj.get("target")
    if kind in ("is", "reject") and target is None:
        fail(f"{kind} needs a target")
    if kind in ("same", "distinct") and ("target" in obj or "target_fp" in obj):
        fail(f"{kind} takes no target")
    if target is not None and (not isinstance(target, str) or not _TARGET.fullmatch(target)):
        fail("target must be a Person id")
    if (target is None) != ("target_fp" not in obj):
        fail("target and target_fp go together")
    if target is not None and not (isinstance(obj["target_fp"], str) and _TF.fullmatch(obj["target_fp"])):
        fail("target_fp is not a target fingerprint")
    if kind == "is" and not (isinstance(obj.get("basis"), str) and _DIGEST.fullmatch(obj["basis"])):
        fail("is needs basis: the digest of the same line it rests on")
    if kind != "is" and "basis" in obj:
        fail(f"{kind} takes no basis")
    fp = obj["fp"]
    if not isinstance(fp, dict) or set(fp) != set(rows):
        fail("fp must hold exactly one fingerprint per grouped row")
    if not all(isinstance(v, str) and FP_PATTERN.fullmatch(v) for v in fp.values()):
        fail("fp: not a row fingerprint")
    if "note" in obj and obj["note"] not in NOTE_CODES:
        fail(f"note must be one of {', '.join(NOTE_CODES)}")
    canonical = canonical_line(obj)
    return Decision(number, kind, tuple(tuple(g) for g in groups), dict(fp), obj["reviewer"], obj["date"], target,
                    obj.get("target_fp"), obj.get("basis"), obj.get("note"), canonical, line_digest(canonical))


def parse_lines(text: str) -> list[Decision]:
    """Every decision in a decision file's text; blank and #-comment lines skipped; a repeated line is an error."""
    out, seen = [], {}
    for number, raw in enumerate(text.splitlines(), start=1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        d = parse_line(raw, number)
        if d.digest in seen:
            raise DecisionError(f"line {number}: duplicates line {seen[d.digest]}")
        seen[d.digest] = number
        out.append(d)
    return out


def load_decisions(path: Path) -> list[Decision]:
    path = Path(path)
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise DecisionError(f"{path}: unreadable ({type(exc).__name__})") from None
    return parse_lines(text)


def target_fingerprint(key: Key, graph: Graph, person_id: str) -> str | None:
    """Keyed fingerprint of what an `is`/`reject` rests on: the government Person's name, aliases and role facts
    (votes cast; Form 700 filer names; controlled committees). None when the node is not a government Person."""
    if not graph.has(person_id, "Person"):
        return None
    roles = government_roles(graph, person_id)
    if not roles:
        return None
    props = graph.props.get(person_id, {})
    facts = {"cast_vote": "cast_vote" in roles,
             "form700_filer": sorted({f["filer_name"] or "" for f in roles.get("form700_filer", [])}),
             "controller": sorted({f["committee"] for f in roles.get("controller", [])})}
    payload = [person_id, props.get("name"), sorted(props.get("aliases") or []), facts]
    return f"tf1:k{key.version}:" + _hmac(key, "open-marin/identity/target/v1", canonical_json(payload))


# ---------------------------------------------------------------------------
# Effective state
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Conflict:
    id: str
    decisions: tuple[str, ...]
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class Person:
    label: str
    rows: frozenset[str]
    target: str | None


@dataclass
class State:
    decisions: list[Decision]
    status: dict[str, str]  # digest -> effective | stale | suspended
    stale: dict[str, dict]  # digest -> {row id | "target" | "latched": [what changed]}
    suspended: dict[str, str]  # digest -> no_covering_same | a conflict id
    conflicts: list[Conflict]
    persons: list[Person]
    person_of: dict[str, str]  # row id -> person label
    latch: frozenset[str]  # the stale lines still in the file: what the private latch should now hold
    flows: dict[str, str]  # row id -> MoneyFlow id

    def flows_of(self, person: Person) -> list[str]:
        return sorted({self.flows[r] for r in person.rows})


class _UnionFind:
    def __init__(self):
        self.parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


def _nodes(d: Decision) -> list[str]:
    return sorted(d.rows) + ([f"T:{d.target}"] if d.kind == "is" else [])


def _components(ds: list[Decision]):
    """Union-find over rows (and `T:<target>` nodes) joined by `same` and `is`; the decisions forming each root."""
    uf = _UnionFind()
    for d in ds:
        if d.kind in ("same", "is"):
            nodes = _nodes(d)
            for n in nodes[1:]:
                uf.union(nodes[0], n)
    formed: dict[str, set[str]] = defaultdict(set)
    members: dict[str, set[str]] = defaultdict(set)
    for d in ds:
        if d.kind in ("same", "is"):
            root = uf.find(_nodes(d)[0])
            formed[root].add(d.digest)
            members[root].update(_nodes(d))
    return uf, formed, members


def _unsupported(ds: list[Decision], live: set[str], by_digest: dict[str, Decision]) -> set[str]:
    out = set()
    for d in ds:
        if d.kind == "is":
            basis = by_digest.get(d.basis)
            if not (basis and basis.kind == "same" and basis.digest in live and d.rows <= basis.rows):
                out.add(d.digest)
    return out


def _conflicts(ds: list[Decision], flows: dict[str, str]) -> list[Conflict]:
    uf, formed, members = _components(ds)
    found: list[tuple[set[str], str]] = []
    for d in ds:
        if d.kind == "distinct":
            seen: dict[str, int] = {}
            for i, group in enumerate(d.groups):
                for root in {uf.find(r) for r in group if uf.find(r) in formed}:
                    if seen.setdefault(root, i) != i:
                        found.append(({d.digest} | formed[root], "distinct groups are joined by same"))
        if d.kind == "reject":
            for root in {uf.find(r) for r in d.rows if uf.find(r) in formed}:
                if f"T:{d.target}" in members[root]:
                    found.append(({d.digest} | formed[root], f"reject of {d.target} meets its is"))
    for root, nodes in members.items():
        if sum(n.startswith("T:") for n in nodes) > 1:
            found.append((set(formed[root]), "one person, two targets"))
    rows_of_flow: dict[str, set[str]] = defaultdict(set)
    for row, flow in flows.items():
        rows_of_flow[flow].add(row)
    for flow, rows in sorted(rows_of_flow.items()):
        roots = {uf.find(r) for r in rows if uf.find(r) in formed}
        if len(roots) > 1:
            found.append((set().union(*(formed[r] for r in roots)), f"flow {flow} split across people"))
    merged = _UnionFind()
    for digests, _ in found:
        first = min(digests)
        for x in digests:
            merged.union(first, x)
    groups: dict[str, tuple[set[str], set[str]]] = {}
    for digests, reason in found:
        entry = groups.setdefault(merged.find(min(digests)), (set(), set()))
        entry[0].update(digests)
        entry[1].add(reason)
    out = []
    for digests, reasons in groups.values():
        ids = tuple(sorted(digests))
        cid = "c-" + hashlib.sha256("\n".join(ids).encode()).hexdigest()[:16]
        out.append(Conflict(cid, ids, tuple(sorted(reasons))))
    return sorted(out, key=lambda c: c.id)


def effective_state(decisions: list[Decision], rows: dict[str, str], flows: dict[str, str],
                    targets: dict[str, str], latch: frozenset[str] = frozenset()) -> State:
    """stale (incl. latched) -> `is` without its basis -> contradictions -> `is` without its basis -> persons.

    `rows` maps every current row id to its fingerprint, `flows` every current row id to its MoneyFlow, `targets`
    every government Person id to its target fingerprint.
    """
    ordered = sorted(decisions, key=lambda d: d.digest)
    by_digest = {d.digest: d for d in ordered}
    stale: dict[str, dict] = {}
    for d in ordered:
        diff: dict[str, list[str]] = {}
        if d.digest in latch:
            diff["latched"] = ["evidence changed since review"]
        else:
            for r in sorted(d.rows):
                current = rows.get(r)
                if current is None:
                    diff[r] = ["row gone"]
                elif current != d.fp[r]:
                    diff[r] = diff_fields(d.fp[r], current)
            if d.target is not None and targets.get(d.target) != d.target_fp:
                diff["target"] = ["target changed" if d.target in targets else "target gone or holds no role"]
        if diff:
            stale[d.digest] = diff
    suspended: dict[str, str] = {}
    live = [d for d in ordered if d.digest not in stale]
    for digest in _unsupported(live, {d.digest for d in live}, by_digest):
        suspended[digest] = "no_covering_same"
    live = [d for d in live if d.digest not in suspended]
    conflicts = _conflicts(live, flows)
    for c in conflicts:
        for digest in c.decisions:
            suspended[digest] = c.id
    live = [d for d in live if d.digest not in suspended]
    for digest in _unsupported(live, {d.digest for d in live}, by_digest):
        suspended[digest] = "no_covering_same"
    live = [d for d in live if d.digest not in suspended]

    uf, formed, members = _components(live)
    persons = []
    for root, nodes in members.items():
        if not any(by_digest[x].kind == "same" for x in formed[root]):
            continue
        person_rows = frozenset(n for n in nodes if not n.startswith("T:"))
        target = next((n[2:] for n in nodes if n.startswith("T:")), None)
        label = target or "p-" + hashlib.sha256(min(person_rows).encode()).hexdigest()[:12]
        persons.append(Person(label, person_rows, target))
    persons.sort(key=lambda p: p.label)
    person_of = {r: p.label for p in persons for r in p.rows}
    owners: dict[str, set[str]] = defaultdict(set)
    for r, label in person_of.items():
        if r in flows:
            owners[flows[r]].add(label)
    if any(len(v) > 1 for v in owners.values()):
        raise AssertionError("a flow is counted for two people")
    status = {d.digest: "stale" if d.digest in stale else "suspended" if d.digest in suspended else "effective"
              for d in ordered}
    return State(ordered, status, stale, suspended, conflicts, persons, person_of, frozenset(stale), dict(flows))


def decision_line(kind: str, groups, fp: dict, reviewer: str, on: str, target: str | None = None,
                  target_fp: str | None = None, basis: str | None = None, note: str | None = None) -> str:
    """The canonical line for a decision (what review files offer to copy); validated before it is returned."""
    groups = sorted(sorted(g) for g in groups)
    obj = {"v": 1, "kind": kind, "groups": groups, "fp": {r: fp[r] for g in groups for r in g},
           "reviewer": reviewer, "date": on}
    for name, value in (("target", target), ("target_fp", target_fp), ("basis", basis), ("note", note)):
        if value is not None:
            obj[name] = value
    text = canonical_line(obj)
    parse_line(text, 0)
    return text


# ---------------------------------------------------------------------------
# The stale latch (private): decisions once observed stale stay stale until re-ingested
# ---------------------------------------------------------------------------

LATCH = "stale-latch.jsonl"


def latch_bytes(digests) -> bytes:
    return "".join(json.dumps(d) + "\n" for d in sorted(digests)).encode()


def load_latch(private: Path) -> frozenset[str]:
    path = Path(private) / LATCH
    if not path.exists():
        return frozenset()
    out = set()
    for number, raw in enumerate(path.read_text().splitlines(), start=1):
        try:
            digest = json.loads(raw)
        except ValueError:
            digest = None
        if not (isinstance(digest, str) and _DIGEST.fullmatch(digest)):
            raise DecisionError(f"{path} line {number}: not a decision digest")
        out.add(digest)
    return frozenset(out)


def write_latch(private: Path, digests) -> None:
    """Replace the latch atomically (a 0600 temp file in the private dir, then os.replace)."""
    import os
    import tempfile

    fd, tmp = tempfile.mkstemp(prefix=".latch-", dir=private)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(latch_bytes(digests))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, Path(private) / LATCH)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def state_json(state: State) -> dict:
    """The effective state as the build reports it: row ids, field names and digests only."""
    return {
        "decisions": [{"digest": d.digest, "line": d.number, "kind": d.kind, "status": state.status[d.digest]}
                      for d in state.decisions],
        "status": state.status,
        "stale": state.stale,
        "suspended": state.suspended,
        "conflicts": [{"id": c.id, "decisions": list(c.decisions), "reasons": list(c.reasons)}
                      for c in state.conflicts],
        "persons": [{"label": p.label, "target": p.target, "rows": sorted(p.rows), "flows": state.flows_of(p)}
                    for p in state.persons],
    }
