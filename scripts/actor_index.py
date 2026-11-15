#!/usr/bin/env python3
"""Actor index: for each organization or person in the hand-reviewed actor registry, every fact the inputs hold that
names them (board items, delegated contracts, reported grants, their own returns, officers, political gifts, agenda
items, case roles, docket appearances, minutes mentions), dated and sourced, and the connections between them.

Operator-local, like the minutes text index: inputs are read by absolute path, read-only, and ONE SQLite file is
written outside every repo (ACTORS_DB_PATH, default ~/open-marin-research/actors.sqlite), with
identity-candidates.jsonl beside it. The bake, the snapshot push and the exports never read it. No Neo4j.

The registry is the identity gate:
  - a fact attaches by substrate id or EIN where the source carries one; a name pattern is used only for sources
    without ids (ledger counterparties, Schedule I recipients without an EIN, docket strings, officer names, agenda
    titles, minutes pages). A fact attached through an unreviewed pattern is kept as `pattern_unreviewed`: a
    possible match, never in totals or connections;
  - two actors sharing a substrate id or EIN, or one source string matching reviewed patterns of two actors, fails
    the build. A match lying wholly inside another actor's match (a person's name inside a firm's name) is part of
    that name, not a second match;
  - affiliation is not identity: affiliated actors stay separate.

The tool states what documents show. Labels never impute motive, and the hop labels for board items, delegated
contracts and reported grants say "committed", "contract ceiling" and "reported grant". No street address
reaches the index, and Schedule I Part III is never read.

    python scripts/actor_index.py copy-inputs     # once: board ledger + docket cache → ~/open-marin-research/inputs
    python scripts/actor_index.py build           # index + identity candidates + build report
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

import yaml

import identity_ledger
import ingest_990
import schedule_i_990

HOME = Path.home()
RESEARCH = HOME / "open-marin-research"
CANONICAL = HOME / "projects/marin-civic-graph"
INDEX_PATH = Path(os.environ.get("ACTORS_DB_PATH") or RESEARCH / "actors.sqlite")
REPORT_DIR = HOME / "open-marin-staging/actor-index"
STAGED_LEDGER = HOME / "open-marin-staging/linking-pilot/ledger/ledger.jsonl"
STAGED_DOCKETS = HOME / "open-marin-staging/actor-files/dockets"
MANIFEST = "inputs-manifest.json"

CONFIRMED = frozenset({"substrate_id", "ein", "pattern_reviewed", "reviewed_role", "ledger_body"})
REPEAT_NOTE = "amendments restate agreement ceilings; this sum overcounts"
OVERLAP_NOTE = "same name, not confirmed the same person"
SIDE_UNKNOWN = "side not established"
NO_ATTORNEY = "no attorney listed in the source"
ADDRESS_WITHHELD = "[address withheld]"
LEDGER_DIRECTIONS = ("county_pays", "county_receives", "no_money", "unclear")
FORMS = ("commitment_grant", "commitment_grant_litigation", "shared_officer")
CASE_ROLES = ("defendant", "plaintiff", "plaintiff_counsel")

_STREET = (r"Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Drive|Dr|Lane|Ln|Way|Court|Ct|Place|Pl|Circle|Cir|"
           r"Highway|Hwy|Terrace|Parkway|Pkwy|Square|Plaza|Alley")
_PREFIX = r"Camino|Calle|Via|Avenida|Paseo|Rancho|Vista|Corte|Avenue of the"
ADDRESS_RE = re.compile(
    rf"\b\d{{1,6}}(?:-\d{{1,6}})?[A-Z]?\s+(?:(?:[A-Z0-9][\w.'’-]*\s+){{0,4}}(?:{_STREET})\b\.?"
    rf"|(?:{_PREFIX})\s+[A-Z][\w'’-]*(?:\s+[A-Z][\w'’-]*)?)", re.IGNORECASE)
_SUFFIXES = {"JR", "SR", "II", "III", "IV", "MD", "PHD", "ESQ", "CPA", "DDS"}
_MONTHS = {m: i for i, m in enumerate(("JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE", "JULY", "AUGUST",
                                       "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER"), start=1)}

SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE actors (slug TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL, registered INTEGER NOT NULL,
    public_body INTEGER NOT NULL, reviewed INTEGER NOT NULL, public_role TEXT, substrate_ids TEXT NOT NULL,
    eins TEXT NOT NULL, affiliated_with TEXT NOT NULL, patterns TEXT NOT NULL, organization_slug TEXT);
CREATE TABLE facts (fact_key TEXT PRIMARY KEY, actor_slug TEXT, actor_name TEXT NOT NULL, kind TEXT NOT NULL,
    counterparty_name TEXT, counterparty_slug TEXT, metric TEXT, amount REAL, direction TEXT, date TEXT,
    date_kind TEXT NOT NULL, source_ref TEXT NOT NULL, source_url TEXT, quote TEXT, label TEXT NOT NULL,
    identity_basis TEXT NOT NULL, counterparty_basis TEXT, assertion_status TEXT NOT NULL, repeat_of TEXT,
    detail TEXT NOT NULL);
CREATE INDEX facts_actor ON facts (actor_slug, kind);
CREATE INDEX facts_counterparty ON facts (counterparty_slug, kind);
CREATE TABLE totals (actor_slug TEXT NOT NULL, side TEXT NOT NULL, kind TEXT NOT NULL, metric TEXT NOT NULL,
    direction TEXT NOT NULL, n INTEGER NOT NULL, amount REAL NOT NULL, note TEXT,
    PRIMARY KEY (actor_slug, side, kind, metric, direction));
CREATE TABLE by_year (actor_slug TEXT NOT NULL, side TEXT NOT NULL, year TEXT NOT NULL, kind TEXT NOT NULL,
    metric TEXT NOT NULL, direction TEXT NOT NULL, n INTEGER NOT NULL, amount REAL,
    PRIMARY KEY (actor_slug, side, year, kind, metric, direction));
CREATE TABLE cases (docket TEXT PRIMARY KEY, court TEXT, caption TEXT, filed TEXT, closed TEXT, cause TEXT,
    courtlistener_url TEXT, courtlistener_id TEXT, parties TEXT NOT NULL, attorneys TEXT NOT NULL,
    firms TEXT NOT NULL, attorney_note TEXT, roles_reviewed INTEGER NOT NULL, outcome_kind TEXT, outcome_date TEXT,
    outcome_evidence TEXT);
CREATE TABLE connections (connection_id TEXT PRIMARY KEY, form TEXT NOT NULL, label TEXT NOT NULL,
    actors TEXT NOT NULL, hops TEXT NOT NULL, person_identity TEXT);
CREATE TABLE name_overlaps (name_norm TEXT NOT NULL, left_kind TEXT NOT NULL, left_name TEXT NOT NULL,
    left_org TEXT NOT NULL, left_source TEXT NOT NULL, right_kind TEXT NOT NULL, right_name TEXT NOT NULL,
    right_org TEXT NOT NULL, right_source TEXT NOT NULL, note TEXT NOT NULL);
CREATE TABLE coverage (input TEXT NOT NULL, item TEXT NOT NULL, state TEXT NOT NULL, detail TEXT NOT NULL,
    PRIMARY KEY (input, item));
"""
FACT_COLUMNS = ("fact_key", "actor_slug", "actor_name", "kind", "counterparty_name", "counterparty_slug", "metric",
                "amount", "direction", "date", "date_kind", "source_ref", "source_url", "quote", "label",
                "identity_basis", "counterparty_basis", "assertion_status", "repeat_of", "detail")


class RegistryError(Exception):
    """The registry cannot gate identity: overlapping ids/EINs or an ambiguous source string."""


class IndexBuildError(Exception):
    pass


@dataclasses.dataclass(frozen=True)
class Inputs:
    registry: Path
    roles: Path
    ledger: Path
    dockets: Path
    substrate: Path
    returns: tuple[Path, ...]
    courtlistener: Path | None = None
    minutes: Path | None = None

    @classmethod
    def default(cls) -> "Inputs":
        runs = sorted((CANONICAL / "data/ingest-runs").glob("*/staged/courtlistener"))
        minutes = RESEARCH / "minutes-text.sqlite"
        return cls(registry=RESEARCH / "actors.yaml", roles=RESEARCH / "inputs/case-roles.yaml",
                   ledger=RESEARCH / "inputs/board-ledger.jsonl", dockets=RESEARCH / "inputs/dockets",
                   substrate=CANONICAL / "data/exports/public-substrate.sqlite",
                   returns=(CANONICAL / "data/raw/990", CANONICAL / "data/raw/irs-990"),
                   courtlistener=runs[-1] if runs else None, minutes=minutes if minutes.is_file() else None)


# --- small helpers -----------------------------------------------------------------------------------------------

def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _j(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def withhold_addresses(text: str | None) -> str | None:
    """Street addresses replaced by a marker: no address reaches the index."""
    return ADDRESS_RE.sub(ADDRESS_WITHHELD, text) if text else text


def _scrubbed(row: tuple) -> tuple:
    """Every persisted string passes the address filter (keys, labels, JSON details and lists alike)."""
    return tuple(withhold_addresses(v) if isinstance(v, str) else v for v in row)


def normalize_person(name: str) -> str:
    """Upper case, punctuation and suffixes dropped: the comparison key for 'same name' (never identity)."""
    words = re.sub(r"[^A-Z ]", " ", name.upper()).split()
    return " ".join(x for x in words if x not in _SUFFIXES)


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def ledger_date(raw: str | None) -> str | None:
    m = re.match(r"^([A-Z]+) (\d{1,2}), (\d{4})$", (raw or "").strip().upper())
    if not m or m.group(1) not in _MONTHS:
        return None
    return f"{m.group(3)}-{_MONTHS[m.group(1)]:02d}-{int(m.group(2)):02d}"


def _amount(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


# --- the registry -------------------------------------------------------------------------------------------------

@dataclasses.dataclass
class Pattern:
    match: re.Pattern
    exclude: re.Pattern | None
    reviewed: bool
    text: str


@dataclasses.dataclass
class Actor:
    slug: str
    name: str
    kind: str
    reviewed: bool
    public_body: bool
    substrate_ids: list[str]
    eins: list[str]
    patterns: list[Pattern]
    affiliated_with: list[str]
    public_role: str | None = None
    ledger_body: bool = False


class Registry:
    def __init__(self, actors: list[Actor], reviewed_on: str):
        self.actors = {a.slug: a for a in actors}
        self.reviewed_on = reviewed_on
        self.by_id: dict[str, str] = {}
        self.by_ein: dict[str, str] = {}
        for a in actors:
            for table, keys, what in ((self.by_id, a.substrate_ids, "substrate id"), (self.by_ein, a.eins, "EIN")):
                for key in keys:
                    if key in table and table[key] != a.slug:
                        raise RegistryError(f"{what} {key} is assigned to both {table[key]} and {a.slug}")
                    table[key] = a.slug
        bodies = [a for a in actors if a.ledger_body]
        if len(bodies) != 1:
            raise RegistryError(f"exactly one public body must be the ledger body; found {len(bodies)}")
        self.ledger_body = bodies[0]

    def match(self, text: str | None) -> list[tuple[str, str]]:
        """[(slug, basis)] for one source string that names at most one actor. Reviewed matches decide; a match
        lying wholly inside another actor's match is subsumed; two reviewed actors left over fail the build.
        Without a reviewed match, each actor whose unreviewed pattern matches is a possible match."""
        hits = self.spans(text)
        reviewed = {s for s, _, rv in hits if rv}
        if len(reviewed) > 1:
            raise RegistryError(f"{text!r} matches reviewed patterns of {', '.join(sorted(reviewed))}")
        if reviewed:
            return [(reviewed.pop(), "pattern_reviewed")]
        return [(s, "pattern_unreviewed") for s in sorted({s for s, _, _ in hits})]

    def spans(self, text: str | None) -> list[tuple[str, tuple[int, int], bool]]:
        """Every actor's pattern match in `text` (upper-cased), minus matches nested inside another actor's."""
        t = (text or "").upper()
        if not t:
            return []
        raw = []
        for a in self.actors.values():
            for p in a.patterns:
                if p.exclude and p.exclude.search(t):
                    continue
                raw += [(a.slug, m.span(), p.reviewed) for m in p.match.finditer(t) if m.end() > m.start()]
        return [(s, sp, rv) for s, sp, rv in raw
                if not any(o != s and o_sp[0] <= sp[0] and sp[1] <= o_sp[1] and o_sp != sp for o, o_sp, _ in raw)]

    def mentions(self, text: str | None) -> dict[str, str]:
        """{slug: basis} for every actor a page of text mentions (minutes pages name many actors at once)."""
        spans = self.spans(text)
        reviewed = [(s, sp) for s, sp, rv in spans if rv]
        for i, (a, (a0, a1)) in enumerate(reviewed):
            for b_, (b0, b1) in reviewed[i + 1:]:
                if a != b_ and a0 < b1 and b0 < a1:
                    raise RegistryError(f"one occurrence {text[max(a0, b0):min(a1, b1)]!r} matches reviewed "
                                        f"patterns of {', '.join(sorted({a, b_}))}")
        out: dict[str, str] = {}
        for slug, _, rv in spans:
            if rv:
                out[slug] = "pattern_reviewed"
            else:
                out.setdefault(slug, "pattern_unreviewed")
        return out


def _patterns(entries) -> list[Pattern]:
    out = []
    for p in entries or []:
        try:
            out.append(Pattern(re.compile(p["match"]), re.compile(p["exclude"]) if p.get("exclude") else None,
                               bool(p.get("reviewed")), p["match"]))
        except re.error as e:
            raise RegistryError(f"bad pattern {p.get('match')!r}: {e}") from e
    return out


def load_registry(path: Path) -> Registry:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    actors = []
    for entry in raw.get("actors") or []:
        actors.append(Actor(
            slug=entry["slug"], name=entry["name"], kind=entry["kind"], reviewed=bool(entry.get("reviewed")),
            public_body=False, substrate_ids=list(entry.get("substrate_ids") or []),
            eins=[re.sub(r"\D", "", str(e)) for e in entry.get("eins") or []], patterns=_patterns(entry.get("patterns")),
            affiliated_with=list(entry.get("affiliated_with") or []), public_role=entry.get("public_role")))
    for entry in raw.get("public_bodies") or []:
        actors.append(Actor(
            slug=entry["slug"], name=entry["name"], kind="public_body", reviewed=entry.get("reviewed", True) is True,
            public_body=True, substrate_ids=list(entry.get("substrate_ids") or []), eins=[],
            patterns=_patterns(entry.get("patterns")), affiliated_with=[], ledger_body=bool(entry.get("ledger_body"))))
    slugs = [a.slug for a in actors]
    if len(set(slugs)) != len(slugs):
        raise RegistryError("a slug is listed twice")
    for a in actors:
        unknown = set(a.affiliated_with) - set(slugs)
        if unknown:
            raise RegistryError(f"{a.slug} is affiliated with unknown actors {sorted(unknown)}")
    return Registry(actors, str(raw.get("reviewed_on") or ""))


# --- copied inputs -------------------------------------------------------------------------------------------------

def copy_inputs(ledger: Path, dockets: Path, dest: Path, copied_on: str) -> dict:
    """Copy the board ledger and the docket cache once into `dest`, with inputs-manifest.json (file, sha256, source,
    date). Idempotent; never overwrites different bytes."""
    dest = Path(dest)
    pairs = [(Path(ledger), "board-ledger.jsonl")]
    pairs += [(p, f"dockets/{p.name}") for p in sorted(Path(dockets).glob("*.json"))]
    previous = {}
    if (dest / MANIFEST).is_file():
        previous = {f["file"]: f for f in json.loads((dest / MANIFEST).read_text())["files"]}
    files = []
    for src, name in pairs:
        data = src.read_bytes()
        target = dest / name
        if target.exists() and target.read_bytes() != data:
            raise IndexBuildError(f"{target} exists and differs from {src}")
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.write_bytes(data)
            os.chmod(target, 0o600)
        files.append({"file": name, "sha256": _sha(data), "from": str(src),
                      "copied_on": previous.get(name, {}).get("copied_on", copied_on)})
    manifest = {"copied_on": min(f["copied_on"] for f in files) if files else copied_on, "files": files}
    (dest / MANIFEST).write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n")
    return manifest


def _verify_manifest(path: Path, root: Path) -> None:
    """A copied input must still match the sha256 its manifest recorded."""
    manifest = root / MANIFEST
    if not manifest.is_file():
        return
    entries = {f["file"]: f["sha256"] for f in json.loads(manifest.read_text())["files"]}
    name = path.relative_to(root).as_posix()
    if name in entries and _sha(path.read_bytes()) != entries[name]:
        raise IndexBuildError(f"{path} no longer matches the sha256 in {manifest}")


# --- fact construction -----------------------------------------------------------------------------------------------

def hop_label(f: dict) -> str:
    """The generated label for one fact used as a connection hop (states what the document shows, nothing more)."""
    kind = f["kind"]
    if kind == "board_item":
        return {"county_pays": "committed (stated in a board item)",
                "county_receives": "county receives (stated in a board item)",
                "no_money": "board item, no amount", "unclear": "board item, direction unclear"}[f["direction"]]
    if kind == "delegated_contract":
        return "contract ceiling"
    if kind == "reported_grant":
        return "reported grant"
    if kind == "case_role":
        return {"defendant": "defendant", "plaintiff": "plaintiff", "plaintiff_counsel": "plaintiff counsel"}[
            f["role"]]
    raise ValueError(kind)


def _fact(**kw) -> dict:
    f = {c: None for c in FACT_COLUMNS}
    f.update(kw)
    f["detail"] = _j(kw.get("detail") or {})
    return f


class Builder:
    def __init__(self, registry: Registry):
        self.reg = registry
        self.facts: dict[str, dict] = {}
        self.coverage: dict[tuple[str, str], tuple[str, dict]] = {}
        self.people: dict[str, dict] = {}
        self.filers: dict[str, dict] = {}  # held filers outside the registry: entries for their officers' pages
        self.overlap_people: list[dict] = []

    def add(self, f: dict) -> None:
        if f["fact_key"] in self.facts:
            raise IndexBuildError(f"duplicate fact key {f['fact_key']}")
        for col in ("quote", "counterparty_name", "label"):
            f[col] = withhold_addresses(f[col])
        self.facts[f["fact_key"]] = f

    def cover(self, input_: str, item: str, state: str, **detail) -> None:
        self.coverage[(input_, item)] = (state, detail)

    def name(self, slug: str | None) -> str | None:
        return self.reg.actors[slug].name if slug in self.reg.actors else None

    def attach_by_id(self, node_id: str | None) -> tuple[str | None, str | None]:
        slug = self.reg.by_id.get(node_id or "")
        return (slug, "substrate_id") if slug else (None, None)


# --- inputs → facts ------------------------------------------------------------------------------------------------

def add_ledger(b: Builder, path: Path) -> None:
    data = Path(path).read_bytes()
    sha = _sha(data)[:16]
    body = b.reg.ledger_body
    first_of: dict[tuple, str] = {}
    dates = []
    for line_no, line in enumerate(data.decode("utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("direction") not in LEDGER_DIRECTIONS:
            raise IndexBuildError(f"ledger line {line_no}: unknown direction {r.get('direction')!r}")
        date = ledger_date(r.get("date"))
        dates += [date] if date else []
        group = (r.get("meeting"), r.get("item"), r.get("counterparty"), r.get("action"), r.get("amount"))
        matches = b.reg.match(r.get("counterparty"))
        for slug, basis in matches:
            key = f"board_item:{sha}:{line_no}" + (f":{slug}" if len(matches) > 1 else "")
            repeat_of = first_of.setdefault(group + (slug,), key)
            b.add(_fact(
                fact_key=key, actor_slug=slug, actor_name=b.name(slug), kind="board_item",
                counterparty_name=body.name, counterparty_slug=body.slug, counterparty_basis="ledger_body",
                metric="stated_in_item", amount=_amount(r.get("amount")), direction=r["direction"], date=date,
                date_kind="meeting_date", source_ref=f"{r.get('meeting')} item {r.get('item')}",
                quote=r.get("quote"), label=hop_label({"kind": "board_item", "direction": r["direction"]}),
                identity_basis=basis, assertion_status="extracted_unsampled",
                repeat_of=None if repeat_of == key else repeat_of,
                detail={"line": line_no, "input_sha256": sha, "n": r.get("n"), "meeting": r.get("meeting"),
                        "item": r.get("item"), "counterparty": withhold_addresses(r.get("counterparty")),
                        "action": r.get("action"), "date_raw": r.get("date"), "ledger_kind": r.get("kind")}))
    b.cover("board_ledger", "rows", "covered", rows=len(data.splitlines()), body=body.name,
            first=min(dates, default=None), last=max(dates, default=None), input_sha256=_sha(data),
            note="Board of Supervisors items only: amounts are stated in the item text, sampled extraction")


def _first(db, sql, *args):
    row = db.execute(sql, args).fetchone()
    return row[0] if row else None


def add_substrate(b: Builder, path: Path) -> dict:
    db = sqlite3.connect(f"file:{Path(path)}?mode=ro", uri=True)
    try:
        label = dict(db.execute("SELECT id, search_label FROM nodes WHERE type IN ('Organization', 'Committee')"))
        flows = db.execute(
            "SELECT n.id, json_extract(n.props, '$.flow_type'), json_extract(n.props, '$.amount'), "
            "json_extract(n.props, '$.flow_date'), "
            "(SELECT e.source FROM edges e WHERE e.rel = 'FROM_SOURCE' AND e.target = n.id ORDER BY e.source LIMIT 1), "
            "(SELECT e.target FROM edges e WHERE e.rel = 'TO_TARGET' AND e.source = n.id ORDER BY e.target LIMIT 1) "
            "FROM nodes n WHERE n.type = 'MoneyFlow' AND json_extract(n.props, '$.flow_type') IN "
            "('delegated_contract', 'contribution', 'campaign_contribution') ORDER BY n.id").fetchall()
        counts = defaultdict(int)
        for fid, ftype, amount, date, src, tgt in flows:
            counts[ftype] += 1
            if ftype == "delegated_contract":
                slug, basis = b.attach_by_id(tgt)
                if not slug:
                    continue
                body_slug, body_basis = b.attach_by_id(src)
                b.add(_fact(
                    fact_key=f"delegated_contract:{fid}", actor_slug=slug, actor_name=b.name(slug),
                    kind="delegated_contract", counterparty_name=label.get(src) or src, counterparty_slug=body_slug,
                    counterparty_basis=body_basis or "stated_name", metric="contract_ceiling", amount=_amount(amount),
                    direction="body_pays", date=date, date_kind="flow_date" if date else "unknown",
                    source_ref=fid, label=hop_label({"kind": "delegated_contract"}), identity_basis=basis,
                    assertion_status="source_record", detail={"from_id": src, "to_id": tgt}))
            else:
                slug, basis = b.attach_by_id(src)
                if not slug:
                    continue
                b.add(_fact(
                    fact_key=f"political_gift:{fid}", actor_slug=slug, actor_name=b.name(slug), kind="political_gift",
                    counterparty_name=label.get(tgt) or tgt, counterparty_slug=b.attach_by_id(tgt)[0],
                    counterparty_basis=b.attach_by_id(tgt)[1] or "stated_name", metric="contribution",
                    amount=_amount(amount), direction="actor_gives", date=date, date_kind="flow_date",
                    source_ref=fid, label="political contribution (as reported)", identity_basis=basis,
                    assertion_status="source_record", detail={"flow_type": ftype, "from_id": src, "to_id": tgt}))
        b.cover("delegated_contracts", "county", "covered", flows=counts["delegated_contract"],
                note="County delegated-authority contracts: ceilings, not invoices; the source carries no dates")
        b.cover("political_gifts", "campaign finance", "covered",
                flows=counts["contribution"] + counts["campaign_contribution"],
                note="Contributions an actor's substrate organization made, as reported")
        b.cover("city_contracts", "all cities", "absent",
                note="No city-level contract or payment source exists in the inputs")

        items = db.execute(
            "SELECT a.id, json_extract(a.props, '$.title'), json_extract(a.props, '$.item_number'), m.id, "
            "json_extract(m.props, '$.meeting_date') FROM nodes a "
            "LEFT JOIN edges e ON e.source = a.id AND e.rel = 'PART_OF_MEETING' "
            "LEFT JOIN nodes m ON m.id = e.target WHERE a.type = 'AgendaItem' ORDER BY a.id").fetchall()
        seen = set()
        dates = []
        for iid, title, number, mid, date in items:
            if iid in seen:
                continue
            seen.add(iid)
            dates += [date] if date else []
            matches = b.reg.match(title)
            for slug, basis in matches:
                body = meeting_body(mid)
                b.add(_fact(
                    fact_key=f"agenda_item:{iid}" + (f":{slug}" if len(matches) > 1 else ""), actor_slug=slug,
                    actor_name=b.name(slug), kind="agenda_item", counterparty_name=body, date=date,
                    date_kind="meeting_date", source_ref=iid, quote=title, label="named in an agenda item title",
                    identity_basis=basis, assertion_status="source_record",
                    detail={"meeting_id": mid, "item_number": number}))
        b.cover("agenda_items", "all bodies", "covered", items=len(seen), first=min(dates, default=None),
                last=max(dates, default=None), note="Agenda item titles only, matched by reviewed name patterns")

        officials = sorted({lbl for (lbl,) in db.execute(
            "SELECT p.search_label FROM nodes p JOIN edges e ON e.target = p.id AND e.rel = 'HELD_BY' "
            "JOIN nodes s ON s.id = e.source AND s.type = 'SeatService' WHERE p.type = 'Person'")})
        org_ids = {i for (i,) in db.execute("SELECT id FROM nodes WHERE type = 'Organization'")}
        as_of = _first(db, "SELECT value FROM meta WHERE key = 'as_of_date'") or ""
        return {"officials": officials, "labels": label, "org_ids": org_ids, "as_of": as_of}
    finally:
        db.close()


def meeting_body(meeting_id: str | None) -> str:
    """A readable body key from a meeting id (the id carries the source; dates and sequence numbers dropped)."""
    s = re.sub(r"^meeting-", "", meeting_id or "unknown")
    s = re.sub(r"^\d{4}-\d\d-\d\d-", "", s)
    return re.sub(r"-(event-)?\d+$|-\d{4}-\d\d-\d\d.*$", "", s)


# --- returns ---------------------------------------------------------------------------------------------------------

def _ts(value: str | None) -> dt.datetime | None:
    try:
        t = dt.datetime.fromisoformat(value) if value else None
    except ValueError:
        return None
    return t if t and t.tzinfo else None


def select_returns(parsed: list[dict]) -> dict[tuple[str, str], dict]:
    """{(ein, tax year): {chosen, superseded, status}} over every year present (no year limit: unlike
    schedule_i_990.select_latest_per_year, which keeps three). The latest ReturnTs wins; an amended return beats an
    original at an equal or missing timestamp; then the highest object id. A latest return of an unsupported
    version is a gap, never replaced by an older one."""
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in parsed:
        if r.get("return_type") == "990" and r.get("status") in ("ok", "unsupported_version") and r.get("tax_year"):
            groups[(r["ein"], r["tax_year"])].append(r)
    floor = dt.datetime.min.replace(tzinfo=dt.timezone.utc)
    out = {}
    for key, group in sorted(groups.items()):
        chosen = max(group, key=lambda r: (_ts(r.get("return_ts")) or floor, bool(r.get("amended")),
                                           r.get("object_id") or ""))
        out[key] = {"chosen": chosen, "status": "ok" if chosen["status"] == "ok" else "unsupported_latest",
                    "superseded": sorted(r["object_id"] for r in group if r is not chosen)}
    return out


def add_returns(b: Builder, dirs: Iterable[Path]) -> None:
    files = sorted({p for d in dirs if Path(d).is_dir() for p in Path(d).rglob("*.xml")})
    parsed, by_object = [], {}
    for p in files:
        try:
            r = schedule_i_990.parse_return(p)
        except (ValueError, OSError) as e:  # recorded, never silently dropped
            b.cover("form_990_files", p.name, "unreadable", reason=str(e))
            continue
        seen = by_object.get(r["object_id"])
        if seen is not None:  # the same return under two roots is one return; different bytes cannot both be it
            if seen.read_bytes() != p.read_bytes():
                raise IndexBuildError(f"return {r['object_id']} has different copies: {seen} and {p}")
            continue
        parsed.append(r)
        by_object[r["object_id"]] = p
    selected = select_returns(parsed)
    per_ein: dict[str, dict] = defaultdict(lambda: {"tax_years": [], "superseded": [], "gaps": [], "name": None})
    for (ein, year), sel in selected.items():
        r = sel["chosen"]
        cov = per_ein[ein]
        cov["superseded"] += sel["superseded"]
        if sel["status"] != "ok":
            cov["gaps"].append({"tax_year": year, "object_id": r["object_id"], "status": sel["status"]})
            continue
        cov["tax_years"].append(year)
        base = ingest_990.parse_return_file(by_object[r["object_id"]]) or {}
        filer_name = base.get("legal_name") or ein
        cov["name"] = filer_name
        grantor = b.reg.by_ein.get(ein)
        oid = r["object_id"]
        if grantor:
            for metric in ("total_revenue", "government_grants"):
                if r.get(metric) is not None:
                    b.add(_fact(
                        fact_key=f"own_return:{oid}:{metric}", actor_slug=grantor, actor_name=b.name(grantor),
                        kind="own_return", metric=metric, amount=_amount(r[metric]), direction="reported",
                        date=year, date_kind="tax_year", source_ref=f"990 {oid}",
                        label={"total_revenue": "total revenue (own return)",
                               "government_grants": "government grants (own return)"}[metric],
                        identity_basis="ein", assertion_status="source_record",
                        detail={"object_id": oid, "amended": r.get("amended"), "return_ts": r.get("return_ts")}))
        officers = base.get("officers") or []
        filer_slug = grantor
        if officers and not grantor:  # never reviewed, never in totals' registry list or connections
            filer_slug = f"filer-{ein}"
            b.filers.setdefault(filer_slug, {"slug": filer_slug, "name": filer_name, "ein": ein})
        for i, o in enumerate(officers):
            add_officer(b, ein, filer_slug, filer_name, year, oid, i, o)
        for i, g in enumerate(((r.get("schedule_i") or {}).get("grants") or [])):
            add_grant(b, ein, grantor, filer_name, year, oid, i, g)
    for ein, cov in sorted(per_ein.items()):
        b.cover("form_990", ein, "held", name=cov["name"], tax_years=sorted(cov["tax_years"]),
                superseded=sorted(cov["superseded"]), gaps=cov["gaps"])
    for a in b.reg.actors.values():
        if a.public_body:
            continue
        if not a.eins:
            b.cover("form_990_registry", a.slug, "no EIN in the registry")
        else:
            held = sorted({y for e in a.eins for y in per_ein.get(e, {}).get("tax_years", [])})
            b.cover("form_990_registry", a.slug, "returns held" if held else "no return held", eins=a.eins,
                    tax_years=held)


def add_officer(b: Builder, ein, filer_slug, filer_name, year, oid, i, o) -> None:
    norm = normalize_person(o.get("name_raw") or o.get("name") or "")
    if not norm:
        return
    b.overlap_people.append({"kind": "officer", "name": o["name"], "norm": norm, "org": filer_name,
                             "org_key": ein, "source": f"990 {oid} (tax year {year}), Part VII row {i + 1}"})
    registered = [s for s, basis in b.reg.match(o.get("name_raw")) if basis == "pattern_reviewed"
                  and b.reg.actors[s].kind == "person"]
    if registered:
        person, basis = registered[0], "pattern_reviewed"
    else:
        person, basis = f"officer-{filer_slug}-{slugify(norm)}", "stated_name"
        b.people.setdefault(person, {"slug": person, "name": o["name"], "organization_slug": filer_slug})
    b.add(_fact(
        fact_key=f"officer:{oid}:{i}", actor_slug=filer_slug, actor_name=b.name(filer_slug) or filer_name,
        kind="officer",
        counterparty_name=o["name"], counterparty_slug=person, counterparty_basis=basis, date=year,
        date_kind="tax_year", source_ref=f"990 {oid}", label=f"officer listed on the return: {o.get('role') or ''}",
        identity_basis="ein", assertion_status="source_record",
        detail={"object_id": oid, "title": o.get("role"), "row": i + 1}))


def add_grant(b: Builder, ein, grantor, filer_name, year, oid, i, g) -> None:
    rein = g.get("recipient_ein")
    if rein and rein in b.reg.by_ein:
        recipients = [(b.reg.by_ein[rein], "ein")]
    elif rein:
        # The row's EIN decides and the registry does not list it: a name match is only a possible match, shown
        # with the EIN so the registry can be extended, never attached.
        recipients = [(s, "pattern_ein_not_in_registry" if basis == "pattern_reviewed" else basis)
                      for s, basis in b.reg.match(g.get("recipient_name"))]
    else:
        recipients = b.reg.match(g.get("recipient_name"))
    if not grantor and not recipients:
        return
    for n, (slug, basis) in enumerate(recipients or [(None, None)]):
        for metric, field in (("cash_grant", "cash_grant_amt"), ("noncash_assistance", "non_cash_assistance_amt")):
            if g.get(field) is None:
                continue
            first = f"reported_grant:{oid}:{i}:{metric}" + (f":{recipients[0][0]}" if len(recipients) > 1 else "")
            key = f"reported_grant:{oid}:{i}:{metric}" + (f":{slug}" if len(recipients) > 1 else "")
            b.add(_fact(
                fact_key=key, actor_slug=grantor, actor_name=b.name(grantor) or filer_name, kind="reported_grant",
                counterparty_name=g.get("recipient_name"), counterparty_slug=slug,
                counterparty_basis=basis or "stated_name", metric=metric, amount=_amount(g[field]),
                direction="grantor_reports", date=year, date_kind="tax_year",
                source_ref=f"990 {oid} Schedule I row {i + 1}", quote=g.get("purpose"),
                label=hop_label({"kind": "reported_grant"}), identity_basis="ein",
                assertion_status="source_record", repeat_of=first if n else None,  # one row, several candidates
                detail={"object_id": oid, "row": i + 1, "filer_ein": ein, "filer_name": filer_name,
                        "recipient_ein": rein, "irc_section": g.get("irc_section"),
                        "non_cash_description": g.get("non_cash_description")}))


# --- cases ---------------------------------------------------------------------------------------------------------

def load_courtlistener(staged: Path | None) -> dict[str, dict]:
    if not staged or not (Path(staged) / "nodes.jsonl").is_file():
        return {}
    out = {}
    for line in (Path(staged) / "nodes.jsonl").read_text(encoding="utf-8").splitlines():
        n = json.loads(line) if line.strip() else {}
        if n.get("node_type") == "Case" and n.get("properties", {}).get("docket_number"):
            out[n["properties"]["docket_number"]] = n["properties"] | {"id": n["id"]}
    return out


def add_cases(b: Builder, dockets_dir: Path, roles_path: Path, staged: Path | None) -> list[dict]:
    roles = (yaml.safe_load(Path(roles_path).read_text(encoding="utf-8")) or {}).get("cases") or []
    by_docket = {}
    for c in roles:
        if c["docket"] in by_docket:
            raise IndexBuildError(f"case-roles lists {c['docket']} twice")
        by_docket[c["docket"]] = c
    cl = load_courtlistener(staged)
    cases = []
    for p in sorted(Path(dockets_dir).glob("*.json")):
        _verify_manifest(p, Path(dockets_dir).parent)
        for r in json.loads(p.read_text(encoding="utf-8")).get("results") or []:
            number = r["docketNumber"]
            staged_case = cl.get(number, {})
            role = by_docket.get(number)
            outcome = (role or {}).get("outcome") or {}
            url = staged_case.get("courtlistener_url") or (
                f"https://www.courtlistener.com{r['docket_absolute_url']}" if r.get("docket_absolute_url") else None)
            case = {
                "docket": number, "court": r.get("court") or staged_case.get("court"),
                "caption": withhold_addresses(staged_case.get("case_name") or r.get("caseName")),
                "filed": staged_case.get("date_filed") or r.get("dateFiled"),
                "closed": staged_case.get("date_terminated") or r.get("dateTerminated"),
                "cause": staged_case.get("cause") or r.get("cause"), "courtlistener_url": url,
                "courtlistener_id": str(r.get("docket_id") or ""),
                "parties": _j([withhold_addresses(x) for x in r.get("party") or []]),
                "attorneys": _j([withhold_addresses(x) for x in r.get("attorney") or []]),
                "firms": _j([withhold_addresses(x) for x in r.get("firm") or []]),
                "attorney_note": None if r.get("attorney") else NO_ATTORNEY, "roles_reviewed": int(role is not None),
                "outcome_kind": outcome.get("kind"), "outcome_date": str(outcome["date"]) if outcome.get("date") else None,
                "outcome_evidence": outcome.get("evidence")}
            cases.append(case)
            b.cover("dockets", number, "cached, roles reviewed" if role else "cached, no reviewed roles",
                    caption=case["caption"], file=p.name)
            for field in ("party", "attorney", "firm"):
                for s in sorted(set(r.get(field) or [])):
                    for slug, basis in b.reg.match(s):
                        b.add(_fact(
                            fact_key=f"docket_appearance:{number}:{field}:{_sha(s.encode())[:12]}:{slug}",
                            actor_slug=slug,
                            actor_name=b.name(slug), kind="docket_appearance", counterparty_name=case["caption"],
                            date=case["filed"], date_kind="filed", source_ref=f"docket {number}", source_url=url,
                            quote=s, label=f"named on the docket as a {field}; {SIDE_UNKNOWN}",
                            identity_basis=basis, assertion_status="side_unknown",
                            detail={"docket": number, "field": field}))
    known = {c["docket"]: c for c in cases}
    for number, role in sorted(by_docket.items()):
        if number not in known:
            raise IndexBuildError(f"case-roles names {number}, which is not in the docket cache")
        case = known[number]
        assigned = [("defendant", role.get("defendant_body"))]
        assigned += [("plaintiff", s) for s in (role.get("plaintiff_orgs") or []) + (role.get("plaintiff_persons") or [])]
        assigned += [("plaintiff_counsel", s) for s in role.get("plaintiff_counsel") or []]
        for r_name, slug in assigned:
            if not slug:
                continue
            if slug not in b.reg.actors:
                raise IndexBuildError(f"case-roles {number}: {slug} is not in the registry")
            against = role.get("defendant_body") if r_name != "defendant" else None
            b.add(_fact(
                fact_key=f"case_role:{number}:{r_name}:{slug}", actor_slug=slug, actor_name=b.name(slug),
                kind="case_role", counterparty_name=b.name(against) if against else case["caption"],
                counterparty_slug=against, counterparty_basis="reviewed_role" if against else None,
                date=case["filed"], date_kind="filed", source_ref=f"docket {number}",
                source_url=case["courtlistener_url"], quote=case["caption"],
                label=f"{hop_label({'kind': 'case_role', 'role': r_name})} in {number}", identity_basis="reviewed_role",
                assertion_status="reviewed_role",
                detail={"docket": number, "role": r_name, "outcome_kind": case["outcome_kind"],
                        "outcome_date": case["outcome_date"], "outcome_evidence": case["outcome_evidence"]}))
    return cases


# --- minutes ---------------------------------------------------------------------------------------------------------

def add_minutes(b: Builder, path: Path | None) -> None:
    if not path or not Path(path).is_file():
        b.cover("minutes", "minutes text index", "absent", note="No minutes text index was available to this build")
        return
    db = sqlite3.connect(f"file:{Path(path)}?mode=ro", uri=True)
    try:
        counts: dict[tuple[str, str, str], int] = defaultdict(int)
        for body, text in db.execute("SELECT body, text FROM pages ORDER BY id"):
            for slug, basis in b.reg.mentions(text).items():
                counts[(slug, body, basis)] += 1
        for (slug, body, basis), n in sorted(counts.items()):
            b.add(_fact(
                fact_key=f"minutes_mentions:{slug}:{body}" + (":unreviewed" if basis != "pattern_reviewed" else ""),
                actor_slug=slug, actor_name=b.name(slug), kind="minutes_mentions", counterparty_name=body,
                metric="page_count", amount=float(n), date_kind="none", source_ref=f"minutes text index: {body}",
                label="minutes pages naming the actor", identity_basis=basis, assertion_status="count_only",
                detail={"body": body}))
        for body, state, first, last, n in db.execute(
                "SELECT body, state, MIN(meeting_date), MAX(meeting_date), COUNT(*) FROM coverage "
                "GROUP BY body, state ORDER BY body, state"):
            st, det = b.coverage.get(("minutes", body), ("covered", {"states": {}, "first": first, "last": last}))
            det["states"][state] = n
            det["first"], det["last"] = min(det["first"], first), max(det["last"], last)
            b.cover("minutes", body, st, **det)
    finally:
        db.close()


# --- totals, people, overlaps, connections -------------------------------------------------------------------------

def _sides(f: dict):
    if f["actor_slug"] and f["identity_basis"] in CONFIRMED:
        yield f["actor_slug"], "subject"
    if f["kind"] == "reported_grant" and f["counterparty_slug"] and f["counterparty_basis"] in CONFIRMED:
        yield f["counterparty_slug"], "counterparty"


def totals(facts: Iterable[dict]) -> tuple[list[tuple], list[tuple]]:
    """Totals only within one kind, metric and direction, per actor and side; never across kinds. Unconfirmed
    attachments and `repeat_of` rows are excluded; board-item totals carry the fixed overcount note."""
    tot: dict[tuple, list] = defaultdict(lambda: [0, 0.0])
    year: dict[tuple, list] = defaultdict(lambda: [0, None])
    for f in facts:
        if f["repeat_of"]:
            continue
        for slug, side in _sides(f):
            k = (slug, side, f["kind"], f["metric"] or "", f["direction"] or "")
            if f["amount"] is not None and f["kind"] not in ("minutes_mentions",):
                tot[k][0] += 1
                tot[k][1] += f["amount"]
            y = (slug, side, (f["date"] or "")[:4] or "undated", *k[2:])
            year[y][0] += 1
            if f["amount"] is not None:
                year[y][1] = (year[y][1] or 0.0) + f["amount"]
    t_rows = [(*k, n, round(s, 2), REPEAT_NOTE if k[2] == "board_item" else None) for k, (n, s) in sorted(tot.items())]
    y_rows = [(*k, n, None if s is None else round(s, 2)) for k, (n, s) in sorted(year.items())]
    return t_rows, y_rows


def name_overlaps(people: list[dict], officials: list[str]) -> list[tuple]:
    by_norm: dict[str, list[dict]] = defaultdict(list)
    for p in people:
        by_norm[p["norm"]].append(p)
    out = set()
    for norm, group in by_norm.items():
        first: dict[str, dict] = {}  # one filer (EIN) is one organization, whatever legal name a year shows
        for p in sorted(group, key=lambda p: (p["org_key"], p["source"])):
            first.setdefault(p["org_key"], p)
        orgs = sorted(first)
        for i, lk in enumerate(orgs):
            for rk in orgs[i + 1:]:
                left, right = first[lk], first[rk]
                out.add((norm, "officer", left["name"], left["org"], left["source"], "officer", right["name"],
                         right["org"], right["source"], OVERLAP_NOTE))
    for official in officials:
        norm = normalize_person(official)
        for p in by_norm.get(norm, []):
            out.add((norm, "officer", p["name"], p["org"], p["source"], "official", official, "elected or appointed seat",
                     "public substrate SeatService (HELD_BY)", OVERLAP_NOTE))
    return sorted(out)


def _confirmed_hop(f: dict, reg: Registry) -> bool:
    """Every actor the fact attaches is reviewed and attached by id, EIN, a reviewed pattern or a reviewed role."""
    ends = [(f["actor_slug"], f["identity_basis"])]
    if f["counterparty_slug"] or f["kind"] != "case_role":
        ends.append((f["counterparty_slug"], f["counterparty_basis"]))
    return not f["repeat_of"] and all(s in reg.actors and reg.actors[s].reviewed and basis in CONFIRMED
                                      for s, basis in ends)


def _source(f: dict) -> dict:
    return {"fact_key": f["fact_key"], "label": f["label"], "source_ref": f["source_ref"], "date": f["date"],
            "date_kind": f["date_kind"], "amount": f["amount"], "metric": f["metric"]}


def _hop(kind, metric, frm, to, label, fs) -> dict:
    return {"kind": kind, "metric": metric, "from": frm, "to": to, "label": label,
            "sources": [_source(f) for f in sorted(fs, key=lambda f: (f["date"] or "", f["fact_key"]))]}


def connections(facts: list[dict], reg: Registry) -> list[tuple]:
    """Paths whose every actor is reviewed and every hop attached by id, EIN or a reviewed pattern:
    body → X (committed or contract ceiling) → Y (reported grant), extended, when it exists, by Y (or Y's reviewed
    counsel) as plaintiff (counsel) in a case a registry public body defends; and pairs of actors sharing an
    officer name (never confirmed the same person). A money chain is emitted at its longest."""
    ok = [f for f in facts if f["kind"] in ("board_item", "delegated_contract", "reported_grant", "case_role")
          and _confirmed_hop(f, reg)]
    commits: dict[tuple[str, str], list] = defaultdict(list)  # (body, X)
    for f in ok:
        if f["kind"] == "board_item" and f["direction"] == "county_pays" or f["kind"] == "delegated_contract":
            if reg.actors[f["counterparty_slug"]].public_body:
                commits[(f["counterparty_slug"], f["actor_slug"])].append(f)
    grants: dict[tuple[str, str], list] = defaultdict(list)  # (X, Y)
    for f in ok:
        if f["kind"] == "reported_grant" and f["actor_slug"] != f["counterparty_slug"]:
            grants[(f["actor_slug"], f["counterparty_slug"])].append(f)
    roles: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))  # docket → role → facts
    for f in ok:
        if f["kind"] == "case_role":
            d = json.loads(f["detail"])
            roles[d["docket"]][d["role"]].append(f)

    def litigation(y: str) -> list[tuple[list, list]]:
        """[(hops, actors after y)] for each case where y, or y's counsel, acts against a registry public body."""
        out = []
        for docket, by_role in sorted(roles.items()):
            defendants = [f for f in by_role["defendant"] if reg.actors[f["actor_slug"]].public_body]
            for d in defendants:
                tail = _hop("case_role", None, docket, d["actor_slug"], f"defendant in {docket}", [d])
                for p in by_role["plaintiff"]:
                    if p["actor_slug"] == y:
                        out.append(([_hop("case_role", None, y, docket, f"plaintiff in {docket}", [p]), tail],
                                    [d["actor_slug"]]))
                if any(p["actor_slug"] == y for p in by_role["plaintiff"]):
                    continue
                for c in by_role["plaintiff_counsel"]:
                    for other, other_roles in sorted(roles.items()):
                        if other == docket:
                            continue
                        # The roles file does not pair counsel with clients: only a sole plaintiff's counsel is
                        # that plaintiff's counsel.
                        mine = [p for p in other_roles["plaintiff"] if p["actor_slug"] == y]
                        theirs = [k for k in other_roles["plaintiff_counsel"] if k["actor_slug"] == c["actor_slug"]]
                        if mine and theirs and len(other_roles["plaintiff"]) == 1:
                            out.append(([_hop("case_role", None, y, c["actor_slug"],
                                              f"plaintiff counsel for the sole plaintiff in {other}", mine + theirs),
                                         _hop("case_role", None, c["actor_slug"], docket,
                                              f"plaintiff counsel in {docket}", [c]), tail],
                                        [c["actor_slug"], d["actor_slug"]]))
        return out

    out = []
    for (body, x), cfs in sorted(commits.items()):
        for (gx, y), gfs in sorted(grants.items()):
            if gx != x:
                continue
            kinds = sorted({f["kind"] for f in cfs})
            first = [_hop(k, "stated_in_item" if k == "board_item" else "contract_ceiling", body, x,
                          hop_label(next(f for f in cfs if f["kind"] == k)), [f for f in cfs if f["kind"] == k])
                     for k in kinds]
            # One grant hop; each source keeps its own metric (cash and non-cash are never added together).
            money = first + [_hop("reported_grant", ", ".join(sorted({f["metric"] for f in gfs})), x, y,
                                  "reported grant", gfs)]
            for case_hops, tail in litigation(y) or [([], [])]:
                form = "commitment_grant_litigation" if case_hops else "commitment_grant"
                actors = [body, x, y] + tail
                hops = money + case_hops
                cid = "connection-" + _sha(_j([form, actors, [(h["kind"], h["from"], h["to"], h["label"])
                                                               for h in hops]]).encode())[:16]
                label = "connection: " + " → ".join(h["label"] for h in hops)
                out.append((cid, form, label, _j(actors), _j(hops), None))
    officers: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for f in facts:
        if f["kind"] == "officer" and f["identity_basis"] == "ein" and f["actor_slug"] in reg.actors \
                and reg.actors[f["actor_slug"]].reviewed:
            officers[normalize_person(f["counterparty_name"])][f["actor_slug"]].append(f)
    for norm, by_actor in sorted(officers.items()):
        slugs = sorted(by_actor)
        for i, a in enumerate(slugs):
            for c in slugs[i + 1:]:
                hops = [_hop("officer", None, a, c, f"officer name on {s}'s return", by_actor[s]) for s in (a, c)]
                cid = "connection-" + _sha(_j(["shared_officer", norm, a, c]).encode())[:16]
                out.append((cid, "shared_officer", f"shared officer name {norm.title()}: {OVERLAP_NOTE}",
                            _j([a, c]), _j(hops), "unconfirmed"))
    return sorted(set(out))


# --- identity candidates -----------------------------------------------------------------------------------------------

def identity_candidates(reg: Registry, sub: dict) -> tuple[list[dict], list[str]]:
    """Queued IdentityAssertions (identity_ledger.make_assertion, status 'queued') for every pair of substrate
    Organization ids one registry entry treats as the same actor. Never applied here."""
    rows, missing = [], []
    for a in sorted(reg.actors.values(), key=lambda a: a.slug):
        present = sorted(i for i in a.substrate_ids if i in sub["org_ids"])
        missing += [f"{a.slug}: {i}" for i in a.substrate_ids if i not in sub["org_ids"]]
        for i, left in enumerate(present):
            for right in present[i + 1:]:
                rows.append(identity_ledger.make_assertion(
                    subject_ref=left, target_ref=right, status="queued", basis="actor_registry_same_actor",
                    subject={"id": left, "display_label": sub["labels"].get(left)},
                    target={"id": right, "display_label": sub["labels"].get(right)},
                    reviewer="actor-registry", decided_at=reg.reviewed_on, policy_version="actor-index-v1",
                    evidence_refs=[f"actors.yaml#{a.slug}"]))
    return rows, missing


# --- build -------------------------------------------------------------------------------------------------------------

def build_index(inputs: Inputs, out: Path) -> dict:
    reg = load_registry(inputs.registry)
    _verify_manifest(Path(inputs.ledger), Path(inputs.ledger).parent)
    b = Builder(reg)
    add_ledger(b, inputs.ledger)
    sub = add_substrate(b, inputs.substrate)
    add_returns(b, inputs.returns)
    cases = add_cases(b, inputs.dockets, inputs.roles, inputs.courtlistener)
    add_minutes(b, inputs.minutes)
    facts = [b.facts[k] for k in sorted(b.facts)]
    t_rows, y_rows = totals(facts)
    conns = connections(facts, reg)
    overlaps = name_overlaps(b.overlap_people, sub["officials"])
    candidates, missing_ids = identity_candidates(reg, sub)
    searched = {"forms": list(FORMS), "reviewed_cases": sum(1 for c in cases if c["roles_reviewed"]),
                "commitments": sum(1 for f in facts if f["kind"] in ("board_item", "delegated_contract")
                                   and f["direction"] in ("county_pays", "body_pays") and _confirmed_hop(f, reg)),
                "reported_grants": sum(1 for f in facts if f["kind"] == "reported_grant" and _confirmed_hop(f, reg)),
                "officer_rows": sum(1 for f in facts if f["kind"] == "officer")}

    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=out.parent, prefix=".actors-", suffix=".sqlite")
    os.close(fd)
    db = sqlite3.connect(tmp)
    try:
        db.executescript(SCHEMA)
        meta = {"schema": "actor-index-v1", "registry_reviewed_on": reg.reviewed_on, "substrate_as_of_date": sub["as_of"],
                "ledger_sha256": _sha(Path(inputs.ledger).read_bytes()),
                "registry_sha256": _sha(Path(inputs.registry).read_bytes()),
                "roles_sha256": _sha(Path(inputs.roles).read_bytes()), "connections_searched": _j(searched)}
        db.executemany("INSERT INTO meta VALUES (?, ?)", sorted(meta.items()))
        for a in sorted(reg.actors.values(), key=lambda a: a.slug):
            db.execute("INSERT INTO actors VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, NULL)",
                       (a.slug, a.name, a.kind, int(a.public_body), int(a.reviewed), a.public_role, _j(a.substrate_ids),
                        _j(a.eins), _j(a.affiliated_with), _j([{"match": p.text, "reviewed": p.reviewed} for p in a.patterns])))
        for f in sorted(b.filers.values(), key=lambda f: f["slug"]):
            db.execute("INSERT INTO actors VALUES (?, ?, 'organization', 0, 0, 0, 'Form 990 filer, not in the registry',"
                       " '[]', ?, '[]', '[]', NULL)", (f["slug"], f["name"], _j([f["ein"]])))
        for p in sorted(b.people.values(), key=lambda p: p["slug"]):
            db.execute("INSERT INTO actors VALUES (?, ?, 'person', 0, 0, 0, 'officer listed on Form 990', '[]', '[]',"
                       " '[]', '[]', ?)", (p["slug"], p["name"], p["organization_slug"]))
        db.executemany(f"INSERT INTO facts VALUES ({', '.join('?' * len(FACT_COLUMNS))})",
                       [_scrubbed(tuple(f[c] for c in FACT_COLUMNS)) for f in facts])
        db.executemany("INSERT INTO totals VALUES (?, ?, ?, ?, ?, ?, ?, ?)", t_rows)  # numbers and fixed vocabulary
        db.executemany("INSERT INTO by_year VALUES (?, ?, ?, ?, ?, ?, ?, ?)", y_rows)
        cols = ("docket", "court", "caption", "filed", "closed", "cause", "courtlistener_url", "courtlistener_id",
                "parties", "attorneys", "firms", "attorney_note", "roles_reviewed", "outcome_kind", "outcome_date",
                "outcome_evidence")
        db.executemany(f"INSERT INTO cases VALUES ({', '.join('?' * len(cols))})",
                       [_scrubbed(tuple(c[k] for k in cols)) for c in sorted(cases, key=lambda c: c["docket"])])
        db.executemany("INSERT INTO connections VALUES (?, ?, ?, ?, ?, ?)", [_scrubbed(c) for c in conns])
        db.executemany("INSERT INTO name_overlaps VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       [_scrubbed(o) for o in overlaps])
        db.executemany("INSERT INTO coverage VALUES (?, ?, ?, ?)",
                       [_scrubbed((i, item, st, _j(det))) for (i, item), (st, det) in sorted(b.coverage.items())])
        db.commit()
    finally:
        db.close()
    os.chmod(tmp, 0o600)
    os.replace(tmp, out)
    identity_ledger.write_assertions(candidates, out.parent / "identity-candidates.jsonl")

    return {
        "index": str(out), "meta": meta, "facts": len(facts),
        "facts_by_kind": dict(sorted(_count(f["kind"] for f in facts).items())),
        "actors": len(reg.actors), "unregistered_people": len(b.people), "unregistered_filers": len(b.filers),
        "cases": len(cases),
        "connections": {"found": [{"form": c[1], "label": c[2], "actors": json.loads(c[3]), "hops": json.loads(c[4])}
                                  for c in conns], "searched": searched},
        "name_overlaps": [dict(zip(("name_norm", "left_kind", "left_name", "left_org", "left_source", "right_kind",
                                    "right_name", "right_org", "right_source", "note"), o)) for o in overlaps],
        "identity_candidates": len(candidates), "registry_ids_not_in_substrate": missing_ids,
        "coverage": [{"input": i, "item": item, "state": st, **det} for (i, item), (st, det) in sorted(b.coverage.items())],
    }


def _count(items) -> dict:
    out: dict = defaultdict(int)
    for i in items:
        out[i] += 1
    return out


def render_report(r: dict) -> str:
    lines = [f"# Actor index build report (substrate as of {r['meta']['substrate_as_of_date']}, registry reviewed "
             f"{r['meta']['registry_reviewed_on']})", "",
             f"{r['facts']} facts, {r['actors']} registry entries, {r['unregistered_people']} unregistered officer "
             f"entries ({r['unregistered_filers']} filers outside the registry hold some of them), {r['cases']} cases, {r['identity_candidates']} identity candidates.", "", "## Facts by kind", ""]
    lines += [f"- {k}: {n}" for k, n in r["facts_by_kind"].items()]
    lines += ["", "## Connections", ""]
    if r["connections"]["found"]:
        for c in r["connections"]["found"]:
            lines.append(f"- **{c['form']}** {' → '.join(c['actors'])}")
            for h in c["hops"]:
                lines.append(f"  - {h['label']} ({h['kind']}): " + "; ".join(
                    f"{s['source_ref']} ({s['metric'] or '-'}, {s['date'] or 'undated'}"
                    + (f", {s['amount']:,.0f}" if s["amount"] is not None else "") + ")" for s in h["sources"]))
    else:
        s = r["connections"]["searched"]
        lines.append(f"None found. Searched forms {', '.join(s['forms'])} over {s['commitments']} confirmed commitments, "
                     f"{s['reported_grants']} confirmed reported grants and {s['reviewed_cases']} cases with reviewed "
                     "roles.")
    lines += ["", "## Officer-name overlaps (same name, not confirmed the same person)", ""]
    lines += [f"- {o['name_norm']}: {o['left_kind']} at {o['left_org']} ({o['left_source']}) / {o['right_kind']} "
              f"{o['right_org']} ({o['right_source']})" for o in r["name_overlaps"]] or ["None."]
    lines += ["", "## Registry substrate ids absent from the substrate", ""]
    lines += [f"- {m}" for m in r["registry_ids_not_in_substrate"]] or ["None."]
    lines += ["", "## Coverage", ""]
    for c in r["coverage"]:
        rest = {k: v for k, v in c.items() if k not in ("input", "item", "state")}
        lines.append(f"- {c['input']} / {c['item']}: **{c['state']}** {_j(rest) if rest else ''}")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("copy-inputs")
    c.add_argument("--ledger", type=Path, default=STAGED_LEDGER)
    c.add_argument("--dockets", type=Path, default=STAGED_DOCKETS)
    c.add_argument("--dest", type=Path, default=RESEARCH / "inputs")
    b = sub.add_parser("build")
    b.add_argument("--out", type=Path, default=INDEX_PATH)
    b.add_argument("--report-dir", type=Path, default=REPORT_DIR)
    args = ap.parse_args(argv)
    if args.cmd == "copy-inputs":
        m = copy_inputs(args.ledger, args.dockets, args.dest, copied_on=dt.date.today().isoformat())
        print(f"copied/verified {len(m['files'])} files into {args.dest}")
        return 0
    try:
        report = build_index(Inputs.default(), args.out)
    except (RegistryError, IndexBuildError) as e:
        print(f"actor index build FAILED: {e}", file=sys.stderr)
        return 2
    args.report_dir.mkdir(parents=True, exist_ok=True)
    (args.report_dir / "build-report.json").write_text(json.dumps(report, indent=1, sort_keys=True) + "\n")
    (args.report_dir / "build-report.md").write_text(render_report(report))
    print(f"{report['facts']} facts; {len(report['connections']['found'])} connections; "
          f"{len(report['name_overlaps'])} officer-name overlaps")
    print(f"wrote {args.out} and {args.report_dir / 'build-report.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
