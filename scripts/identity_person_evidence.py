"""Per-row evidence for person-identity review: durable row references, private address hashes, keyed fingerprints.

The unit of evidence is one physical Schedule A row of a counted contribution whose MoneyFlow comes from a Person
bucket in the frozen graph export. A row is named by what survives a re-download (source, filer, filing period and
report, schedule, Tran_ID), never by file, sheet, row number or file hash.

The contributor street (Tran_Adr1 + Tran_Adr2, with Tran_Zip4) is read from the raw workbook into local variables
only. What leaves this module is a keyed HMAC of its canonical form (address_hash, operator-private) and a keyed
fingerprint of every row (allowed in the decision file). Treasurer and intermediary columns are never read. Errors
name rows by row id and never carry a cell value.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import unicodedata
import warnings
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple

import openpyxl

from contributor_detail import display
from identity_person_key import Key


class IdentityError(Exception):
    """An identity command cannot proceed; the message names rows, lines, paths and fields, never values."""


class InputError(IdentityError):
    """An input is missing, inconsistent with another, or unreadable."""


def canonical_json(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _hmac(key: Key, domain: str, *parts: bytes) -> str:
    message = b"\0".join([domain.encode(), str(key.version).encode(), *parts])
    return hmac.new(key.secret, message, hashlib.sha256).hexdigest()


# ---------------------------------------------------------------------------
# Address canonicalization (in memory only)
# ---------------------------------------------------------------------------

_PLACEHOLDER = re.compile(r"""[\W_]* | N/?A | N\.\s?A\.? | NONE | NULL | UNKNOWN | UNK | TBD
    | (?:INFO(?:RMATION)?|ADDRESS)\s+REQUESTED | REQUESTED | BEST\s+EFFORTS? | REFUSED | DECLINED
    | NOT\s+(?:PROVIDED|GIVEN|AVAILABLE) | NO\s+ADDRESS | SAME(?:\s+AS\s+ABOVE)? | SEE\s+ABOVE | REDACTED
    | X+ | 0+""", re.X)
_ZIP = re.compile(r"([0-9]{5})(?:-?[0-9]{4})?")
_TOKENS = {
    "STREET": "ST", "AVENUE": "AVE", "ROAD": "RD", "DRIVE": "DR", "LANE": "LN", "COURT": "CT",
    "BOULEVARD": "BLVD", "PLACE": "PL", "CIRCLE": "CIR", "TERRACE": "TER", "HIGHWAY": "HWY", "PARKWAY": "PKWY",
    "TRAIL": "TRL", "NORTH": "N", "SOUTH": "S", "EAST": "E", "WEST": "W",
    "APARTMENT": "UNIT", "APT": "UNIT", "SUITE": "UNIT", "STE": "UNIT",
}


class Address(NamedTuple):
    street: str | None  # canonical street; None when the row gives no usable address
    zip5: str | None
    reason: str | None  # why there is no hash
    evidence: tuple  # what the fingerprint covers: the address inputs even when there is no hash


def _upper(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).upper().split())


def _ascii(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def _street_tokens(text: str) -> list[str]:
    tokens = re.sub(r"[^A-Z0-9]+", " ", _ascii(text).replace("#", " UNIT ")).split()
    out: list[str] = []
    i = 0
    while i < len(tokens):
        if tokens[i:i + 3] in (["P", "O", "BOX"], ["POST", "OFFICE", "BOX"]):
            out += ["PO", "BOX"]
            i += 3
            continue
        token = tokens[i]
        if token == "POBOX":
            out += ["PO", "BOX"]
        elif token == "NO" and i + 1 < len(tokens) and tokens[i + 1][:1].isdigit():
            out.append("UNIT")
        else:
            out.append(_TOKENS.get(token, token))
        if out[-1] == "UNIT" and len(out) > 1 and out[-2] == "UNIT":
            out.pop()
        i += 1
    return out


def _zip5(cell) -> tuple[str | None, str | None]:
    """(zip5, reason): ASCII digits only; an Excel number keeps its digits."""
    if isinstance(cell, bool):
        text = str(cell)
    elif isinstance(cell, int) or (isinstance(cell, float) and cell.is_integer()):
        text = str(int(cell))
    else:
        text = (display(cell) or "") if cell is None or isinstance(cell, str) else str(cell)
    if not text:
        return None, "missing_zip"
    match = _ZIP.fullmatch(text)
    if not match or match.group(1) == "00000":
        return None, "invalid_zip"
    return match.group(1), None


def _cell(cell):
    """A source cell as the fingerprint covers it: whitespace-collapsed text, or tagged with its type."""
    if cell is None or isinstance(cell, str):
        return display(cell)
    return {"cell_type": type(cell).__name__, "value": str(cell)}


def canonical_address(adr1, adr2, zip_cell) -> Address:
    """The canonical (street, ZIP5) of a contributor address, or why there is none. Placeholders are detected on
    the raw text, before punctuation is stripped. `evidence` is the source cells themselves: any change to them
    changes the fingerprint, whatever the canonical form."""
    evidence = (_cell(adr1), _cell(adr2), _cell(zip_cell))
    zip5, zip_reason = _zip5(zip_cell)
    lines = []
    for cell in (adr1, adr2):
        if cell is not None and not isinstance(cell, str):
            return Address(None, zip5, "non_text_street", evidence)
        lines.append(_upper(cell or ""))
    first, second = lines
    if not first:
        return Address(None, zip5, "missing_street", evidence)
    if _PLACEHOLDER.fullmatch(first):
        return Address(None, zip5, "placeholder_street", evidence)
    if second and _PLACEHOLDER.fullmatch(second):
        second = ""
    street = " ".join(_street_tokens(f"{first} {second}"))
    if not street or _PLACEHOLDER.fullmatch(street) or not re.search(r"[A-Z0-9]", street):
        return Address(None, zip5, "placeholder_street", evidence)
    if zip5 is None:
        return Address(None, None, zip_reason, evidence)
    return Address(street, zip5, None, evidence)


def address_hash(key: Key, address: Address) -> str | None:
    if address.street is None:
        return None
    return _hmac(key, "open-marin/identity/address/v1", address.street.encode(), address.zip5.encode())


# ---------------------------------------------------------------------------
# Row references and fingerprints
# ---------------------------------------------------------------------------

def row_id(row_key: list) -> str:
    return "r-" + hashlib.sha256(b"open-marin/identity/row/v1\0" + canonical_json(row_key)).hexdigest()[:20]


FP_FIELDS = ["name", "entity", "filing", "date", "amount", "memo", "flow", "occupation", "employer", "city",
             "state", "zip", "address"]


def fingerprint(key: Key, rid: str, values: dict) -> str:
    """`fp1:k{v}:<row HMAC over every field>:<8-hex digest per field>`; the row HMAC alone decides staleness."""
    fields = [_hmac(key, "open-marin/identity/fingerprint/v1", rid.encode(), name.encode(),
                    canonical_json(values[name]))[:8] for name in FP_FIELDS]
    full = _hmac(key, "open-marin/identity/fingerprint-row/v1", rid.encode(),
                 canonical_json([values[name] for name in FP_FIELDS]))
    return f"fp1:k{key.version}:{full}:{'.'.join(fields)}"


FP_PATTERN = re.compile(r"fp1:k([1-9][0-9]{0,5}):([0-9a-f]{64}):((?:[0-9a-f]{8}\.){%d}[0-9a-f]{8})"
                        % (len(FP_FIELDS) - 1))


def diff_fields(old: str, new: str) -> list[str]:
    """The fields whose evidence changed between two fingerprints of one row (all of them when re-keyed)."""
    a, b = FP_PATTERN.fullmatch(old), FP_PATTERN.fullmatch(new)
    if not a or not b or a.group(1) != b.group(1):
        return list(FP_FIELDS)
    changed = [f for f, x, y in zip(FP_FIELDS, a.group(3).split("."), b.group(3).split(".")) if x != y]
    return changed or (["evidence"] if a.group(2) != b.group(2) else [])


# ---------------------------------------------------------------------------
# The frozen graph export
# ---------------------------------------------------------------------------

@dataclass
class Graph:
    labels: dict[str, frozenset[str]] = field(default_factory=dict)  # node id -> its labels
    props: dict[str, dict] = field(default_factory=dict)  # props of Person, Committee, Filing and MoneyFlow nodes
    flow_source: dict[str, str] = field(default_factory=dict)  # MoneyFlow id -> FROM_SOURCE start node
    person_edges: dict[str, list[tuple]] = field(default_factory=lambda: defaultdict(list))
    # person id -> [(direction "in"|"out", rel, other id, edge props)]

    def has(self, node_id: str | None, label: str) -> bool:
        return label in self.labels.get(node_id, ())


_KEPT = {"Person", "Committee", "Filing", "MoneyFlow"}


def _jsonl(path: Path):
    try:
        with open(path, encoding="utf-8") as f:
            for number, line in enumerate(f, start=1):
                if line.strip():
                    yield number, json.loads(line)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InputError(f"{path}: unreadable JSON lines ({type(exc).__name__})") from None


def load_graph(export_dir: Path) -> Graph:
    graph = Graph()
    for _, node in _jsonl(Path(export_dir) / "nodes.jsonl"):
        labels = frozenset(node.get("labels") or ())
        graph.labels[node["id"]] = labels
        if labels & _KEPT:
            graph.props[node["id"]] = node.get("properties") or {}
    for _, edge in _jsonl(Path(export_dir) / "edges.jsonl"):
        start, end, rel = edge["start_id"], edge["end_id"], edge["type"]
        props = edge.get("properties") or {}
        if rel == "FROM_SOURCE" and graph.has(end, "MoneyFlow"):
            graph.flow_source[end] = start
        if graph.has(start, "Person"):
            graph.person_edges[start].append(("out", rel, end, props))
        if graph.has(end, "Person"):
            graph.person_edges[end].append(("in", rel, start, props))
    return graph


# ---------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Inputs:
    ledger_dir: Path  # <dir>/<source>/{ledger.jsonl, filings.jsonl, manifest.json}
    raw_root: Path  # <root>/<source>/<capture YYYY-MM-DD>/<year>.zip
    export_dir: Path  # backup export: nodes.jsonl, edges.jsonl
    decisions: Path


@dataclass(frozen=True)
class Row:
    row_id: str
    row_key: tuple
    bucket: str
    source_id: str
    filing_id: str
    filer_id: str
    committee: str | None
    tran_id: str
    tran_date: str | None
    amount: str
    name: dict
    entity_cd: str | None
    reported: dict  # raw cells: city, state, zip, employer, occupation
    moneyflow_id: str
    address_hash: str | None
    address_reason: str | None
    fp: str


@dataclass
class Evidence:
    rows: list[Row]
    counts: dict
    inputs: list[dict]
    graph: Graph


_DATE_DIR = re.compile(r"\d{4}-\d{2}-\d{2}")
_READ = ("Filer_ID", "Report_Num", "Tran_ID", "Tran_Adr1", "Tran_Adr2", "Tran_Zip4")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _input(role: str, path: Path) -> dict:
    return {"role": role, "path": str(path), "sha256": _sha256(path), "bytes": path.stat().st_size}


def _raw_workbook(raw_root: Path, rel: str, sha: str) -> Path:
    """The raw file for a ledger input: the newest capture holding that year, and byte-identical to it."""
    parts = Path(rel).parts
    source, year_file = parts[0], parts[-1]
    captures = sorted((p.parent.name, p) for p in Path(raw_root, source).glob(f"*/{year_file}")
                      if _DATE_DIR.fullmatch(p.parent.name) and p.is_file())
    if not captures:
        raise InputError(f"ledger input {rel}: no raw workbook for {source} {year_file} under {raw_root}")
    newest = captures[-1][1]
    if _sha256(newest) == sha:
        return newest
    if any(_sha256(p) == sha for _, p in captures[:-1]):
        raise InputError(f"ledger input {rel} is not the newest raw capture for {source} {year_file}: rebuild the "
                         "ledger from the current raw set")
    raise InputError(f"ledger input {rel}: no raw workbook under {raw_root} has its sha256")


def _read_cells(path: Path, rel: str, wanted: set[int]) -> tuple[dict[int, tuple], bool]:
    """({excel row number: (Filer_ID, Report_Num, Tran_ID, Tran_Adr1, Tran_Adr2, Tran_Zip4)}, lossy).

    A parser warning can quote a cell (a street styled as a date) and means a value was not read losslessly.
    Warnings are recorded, never shown; since openpyxl parses ahead of the rows it yields, one cannot be pinned to
    a row, so any warning makes the whole workbook lossy."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            with zipfile.ZipFile(path) as zf:
                [inner] = [n for n in zf.namelist() if n.endswith(".xlsx")]
                with zf.open(inner) as f:
                    wb = openpyxl.load_workbook(f, read_only=True, data_only=True)
                    try:
                        rows = wb["A-Contributions"].iter_rows(values_only=True)
                        header = list(next(rows, ()))
                        index = [header.index(col) for col in _READ]
                        out = {number: tuple(values[i] if i < len(values) else None for i in index)
                               for number, values in enumerate(rows, start=2) if number in wanted}
                    finally:
                        wb.close()
        except Exception as exc:  # zip, XML, sheet or header problems: name the file, never a cell
            raise InputError(f"{rel}: not a readable workbook ({type(exc).__name__})") from None
    return out, bool(caught)


def _reported(cell):
    """A ledger `reported` cell (kept losslessly by campaign_ledger.cell) as the fingerprint covers it."""
    return cell if isinstance(cell, dict) else _cell(cell)


def _text(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def collect(inputs: Inputs, key: Key) -> Evidence:
    graph = load_graph(inputs.export_dir)
    manifest_inputs = [_input("export_nodes", Path(inputs.export_dir) / "nodes.jsonl"),
                       _input("export_edges", Path(inputs.export_dir) / "edges.jsonl")]
    counts: Counter = Counter()
    candidates = []  # (row_key, ledger row, filing, source_id, bucket, sha by input path)
    for source_dir in sorted(p for p in Path(inputs.ledger_dir).iterdir() if (p / "ledger.jsonl").is_file()):
        for name in ("manifest.json", "filings.jsonl", "ledger.jsonl"):
            manifest_inputs.append(_input("ledger", source_dir / name))
        try:
            pinned = {i["path"]: i["sha256"] for i in json.loads((source_dir / "manifest.json").read_text())["inputs"]}
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise InputError(f"{source_dir / 'manifest.json'}: unreadable ({type(exc).__name__})") from None
        filings = {f["filing_id"]: f for _, f in _jsonl(source_dir / "filings.jsonl")}
        for _, row in _jsonl(source_dir / "ledger.jsonl"):
            if row.get("schedule") != "A" or row.get("disposition") != "retained" or not row.get("counted"):
                continue
            flow = row["moneyflow_id"]
            if flow not in graph.labels:
                counts["flow_not_in_export"] += 1
                continue
            bucket = graph.flow_source.get(flow)
            if not graph.has(bucket, "Person"):
                counts["source_not_person"] += 1
                continue
            filing = filings[row["filing_id"]]
            row_key = (filing["source_id"], filing["filer_key"], filing["from_date"], filing["thru_date"],
                       filing["rpt_date"], filing["report_num"], "A", row["tran_id"])
            candidates.append((row_key, row, filing, bucket, pinned))
    prefixes = Counter(c[0] for c in candidates)
    counts["ambiguous_row_key"] = sum(1 for c in candidates if prefixes[c[0]] > 1)
    candidates = [c for c in candidates if prefixes[c[0]] == 1]

    by_file: dict[str, list] = defaultdict(list)
    for c in candidates:
        by_file[c[1]["row_ref"]["file"]].append(c)
    rows: list[Row] = []
    for rel in sorted(by_file):
        group = by_file[rel]
        pinned = group[0][4]
        if rel not in pinned:
            raise InputError(f"ledger row file {rel} is not in its source manifest")
        path = _raw_workbook(inputs.raw_root, rel, pinned[rel])
        manifest_inputs.append(_input("raw_workbook", path))
        cells, lossy = _read_cells(path, rel, {c[1]["row_ref"]["row"] for c in group})
        if lossy:
            counts["lossy_workbook_rows"] += len(group)
            continue
        for row_key, row, filing, bucket, _ in group:
            rid = row_id(list(row_key))
            found = cells.get(row["row_ref"]["row"])
            if found is None or row["row_ref"]["sheet"] != "A-Contributions" or \
                    (_text(found[0]), _text(found[1]), _text(found[2])) != \
                    (filing["filer_id"], filing["report_num"], row["tran_id"]):
                raise InputError(f"{rid}: workbook row does not match the ledger")
            address = canonical_address(found[3], found[4], found[5])
            counts[f"address:{address.reason or 'hashed'}"] += 1
            values = {
                "name": [row["name"].get(p) for p in ("last", "first", "title", "suffix")],
                "entity": row["entity_cd"], "filing": row["filing_id"], "date": row["tran_date"],
                "amount": row["amount"], "memo": [row["memo_code"], row["memo_ref"]],
                "flow": [row["moneyflow_id"], row["counted"], row["disposition"], bucket],
                "occupation": _reported(row["reported"].get("occupation")),
                "employer": _reported(row["reported"].get("employer")),
                "city": _reported(row["reported"].get("city")),
                "state": _reported(row["reported"].get("state")),
                "zip": _reported(row["reported"].get("zip")),
                "address": list(address.evidence),
            }
            rows.append(Row(
                row_id=rid, row_key=row_key, bucket=bucket, source_id=filing["source_id"],
                filing_id=row["filing_id"], filer_id=filing["filer_id"], committee=row.get("filer_name"),
                tran_id=row["tran_id"], tran_date=row["tran_date"], amount=row["amount"], name=row["name"],
                entity_cd=row["entity_cd"], reported=row["reported"], moneyflow_id=row["moneyflow_id"],
                address_hash=address_hash(key, address), address_reason=address.reason,
                fp=fingerprint(key, rid, values)))
            del address, values, found
        del cells
    rows.sort(key=lambda r: r.row_id)
    counts["in_scope"] = len(rows)
    counts["buckets"] = len({r.bucket for r in rows})
    if inputs.decisions.exists():
        manifest_inputs.append(_input("decisions", Path(inputs.decisions)))
    return Evidence(rows, dict(sorted(counts.items())), manifest_inputs, graph)




ROLE_KINDS = ("cast_vote", "form700_filer", "controller")


def government_roles(graph: Graph, person_id: str) -> dict[str, list[dict]]:
    """A Person's government roles in the frozen export, each fact with the edge or node it comes from:
    cast_vote (out CAST_VOTE), form700_filer (in FILED_BY from a form_700 Filing), controller (in CONTROLLED_BY
    from a Committee). Empty when the node holds none."""
    roles: dict[str, list[dict]] = {}
    for direction, rel, other, props in graph.person_edges.get(person_id, ()):
        if direction == "out" and rel == "CAST_VOTE":
            roles.setdefault("cast_vote", []).append({"decision": other, **props})
        elif direction == "in" and rel == "FILED_BY" and graph.props.get(other, {}).get("filing_type") == "form_700":
            filing = graph.props[other]
            roles.setdefault("form700_filer", []).append(
                {"filing": other, "filer_name": filing.get("filer_name"), "filed_at": filing.get("filed_at")})
        elif direction == "in" and rel == "CONTROLLED_BY" and graph.has(other, "Committee"):
            roles.setdefault("controller", []).append({"committee": other, **props})
    return {kind: sorted(facts, key=canonical_json) for kind, facts in sorted(roles.items())}
