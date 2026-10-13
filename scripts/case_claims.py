"""The claim-register checker for the grant-chain case file.

A case file is only as good as the link between each sentence and its source. The register holds one row per
claim; this module re-derives every claim from the bytes behind it so that nothing rests on a typed number:

- the locator must resolve: a document is re-hashed and its page text must contain the claim's verbatim context
  (and, for exact amounts, the amount in a standard rendering); a record is looked up in a re-hashed export;
  a gap or negative points into a re-hashed search log;
- a record_field claim equals the record's field to the cent; a computed claim is reproduced by a registered
  recomputation (sum/count) over the pinned source;
- approximate and projected figures are labelled and can never be marked reconciled.

CASE.md is then checked against the register: every sentence of an answer section cites a claim, every dollar
figure sits on a line that cites a claim of that amount, and a word-list tripwire reports loaded words outside
quotations (a tripwire for a human reader, not proof of anything).

Reports never repeat claim text; they name claim ids and line numbers.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import subprocess
import sys
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from pathlib import Path

QUESTIONS = {"Q1", "Q2", "Q3", "Q4", "Q5", "Q6", "X"}
PRECISIONS = {"exact_cents", "approximate", "projected", "none"}
STATUSES = {"documented", "partially_documented", "gap", "negative"}
DERIVATIONS = {"quoted", "record_field", "computed"}
REQUIRED = ("claim_id", "question", "text", "amount", "precision", "locator", "derivation", "status", "reconciled")
CENTS = re.compile(r"-?\d+\.\d{2}")
CLAIM_ID = re.compile(r"C-[\w-]+")


# --- register schema --------------------------------------------------------------------------------------------

def _row_problems(row: dict) -> list[str]:
    cid = row.get("claim_id", "?")
    problems = [f"{cid}: missing key {key}" for key in REQUIRED if key not in row]
    if problems:
        return problems
    for key, allowed in (("question", QUESTIONS), ("precision", PRECISIONS), ("status", STATUSES)):
        if row[key] not in allowed:
            problems.append(f"{cid}: {key} {row[key]!r} not one of {sorted(allowed)}")
    amount, precision = row["amount"], row["precision"]
    if amount is not None and _decimal(amount) is None:
        problems.append(f"{cid}: amount is not a decimal string")
    elif precision == "exact_cents" and not (isinstance(amount, str) and CENTS.fullmatch(amount)):
        problems.append(f"{cid}: exact_cents amount must be a decimal string with exactly 2 decimals")
    if precision == "none" and amount is not None:
        problems.append(f"{cid}: precision none requires a null amount")
    if precision in ("approximate", "projected") and row["reconciled"] is True:
        problems.append(f"{cid}: {precision} figure must not be marked reconciled")
    locator = row["locator"]
    if not isinstance(locator, dict) or locator.get("kind") not in ("document", "record", "search_log"):
        problems.append(f"{cid}: locator.kind must be document, record or search_log")
    derivation = row["derivation"]
    if not isinstance(derivation, dict) or derivation.get("kind") not in DERIVATIONS:
        problems.append(f"{cid}: derivation.kind must be one of {sorted(DERIVATIONS)}")
    return problems


def check_schema(rows: list[dict]) -> list[str]:
    problems, seen = [], set()
    for row in rows:
        problems += _row_problems(row)
        cid = row.get("claim_id")
        if cid in seen:
            problems.append(f"{cid}: duplicate claim_id")
        seen.add(cid)
    return problems


def _decimal(value) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return None
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


# --- sources: pinned files, re-hashed on first use --------------------------------------------------------------

class Sources:
    """The operator's sources JSON, with every file re-hashed before it is believed. Errors come back as strings."""

    def __init__(self, spec: dict):
        self.spec = spec
        self._hashes: dict[str, str | None] = {}
        self._docs: dict[str, str] | None = None
        self._records: dict[str, dict] = {}
        self._text: dict[tuple, str] = {}
        self._log: dict[str, dict] | None = None

    def _hash(self, path: str) -> str | None:
        if path not in self._hashes:
            try:
                self._hashes[path] = hashlib.sha256(Path(path).read_bytes()).hexdigest()
            except OSError:
                self._hashes[path] = None
        return self._hashes[path]

    def _verified(self, path: str, pinned: str, what: str) -> str | None:
        """None when the file at path hashes to pinned, else a problem string."""
        actual = self._hash(path)
        if actual is None:
            return f"{what}: file unreadable"
        return None if actual == pinned else f"{what}: hash mismatch (file changed since it was pinned)"

    def _document_paths(self) -> dict[str, str]:
        if self._docs is None:
            docs = dict(self.spec.get("documents", {}))
            root = Path(self.spec.get("raw_root", "."))
            for manifest in self.spec.get("manifests", []):
                for row in _read_jsonl(Path(manifest)):
                    docs[row["sha256"]] = str(root / row["path"])
            self._docs = docs
        return self._docs

    def document_text(self, sha: str, page: int | None) -> tuple[str | None, str | None]:
        """(whitespace-normalized text of the page or whole document, problem)."""
        path = self._document_paths().get(sha)
        if path is None:
            return None, f"document {sha[:12]} not in sources"
        problem = self._verified(path, sha, f"document {sha[:12]}")
        if problem:
            return None, problem
        if (sha, page) not in self._text:
            self._text[(sha, page)] = _normalize(_extract_text(Path(path), page))
        return self._text[(sha, page)], None

    def records(self, label: str) -> tuple[dict | None, str | None]:
        """(rows by id, problem). The source file is re-hashed against its pin."""
        if label not in self._records:
            self._records[label] = self._load_records(label)
        return self._records[label]

    def _load_records(self, label: str) -> tuple[dict | None, str | None]:
        spec = self.spec.get("records", {}).get(label)
        if spec is None:
            return None, f"record source {label!r} not in sources"
        problem = self._verified(spec["path"], spec["sha256"], f"record source {label!r}")
        if problem:
            return None, problem
        try:
            rows = _load_rows(spec)
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            return None, f"record source {label!r}: cannot read rows ({type(exc).__name__})"
        return {"rows": rows, "by_id": {str(_get(r, spec["id_field"])): r for r in rows}, "sha": spec["sha256"]}, None

    def search_ids(self) -> tuple[set | None, str | None]:
        spec = self.spec.get("search_log")
        if spec is None:
            return None, "search log not in sources"
        problem = self._verified(spec["path"], spec["sha256"], "search log")
        if problem:
            return None, problem
        return {row["search_id"] for row in _read_jsonl(Path(spec["path"]))}, None


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _load_rows(spec: dict) -> list[dict]:
    path = Path(spec["path"])
    if spec["format"] in ("graph_nodes_jsonl", "ledger_jsonl"):
        return _read_jsonl(path)
    if spec["format"] != "json_rows":
        raise ValueError("unknown record format")
    node = json.loads(path.read_text(encoding="utf-8"))
    for part in filter(None, spec.get("rows_pointer", "").split("/")):
        part = part.replace("~1", "/").replace("~0", "~")
        node = node[int(part)] if isinstance(node, list) else node[part]
    return node


def _get(row: dict, dotted: str):
    """A (dotted) field of a row; graph nodes keep their fields under props, so that is the fallback."""
    for scope in (row, row.get("props") or {}):
        node = scope
        for part in dotted.split("."):
            node = node.get(part) if isinstance(node, dict) else None
        if node is not None:
            return node
    return None


# --- text extraction --------------------------------------------------------------------------------------------

def _normalize(text: str) -> str:
    return " ".join(text.split())


class _TextOnly(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        self._skip += tag in ("script", "style")

    def handle_endtag(self, tag):
        self._skip -= tag in ("script", "style") and self._skip > 0

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def _extract_text(path: Path, page: int | None) -> str:
    data = path.read_bytes()
    if data.startswith(b"%PDF"):
        command = ["pdftotext", "-layout"] + (["-f", str(page), "-l", str(page)] if page else []) + [str(path), "-"]
        done = subprocess.run(command, capture_output=True, check=False)
        return done.stdout.decode("utf-8", errors="replace") if done.returncode == 0 else ""
    text = data.decode("utf-8", errors="replace")
    if path.suffix.lower() in (".html", ".htm"):
        parser = _TextOnly()
        parser.feed(text)
        return html.unescape(" ".join(parser.parts))
    return text


def amount_in(text: str, amount: Decimal) -> bool:
    """True when the amount occurs in text as $724,500 / 724,500.00 / 724500 ... but not inside a larger number."""
    whole, cents = f"{int(amount):d}", f"{abs(amount) % 1:.2f}"[1:]
    bodies = {whole, f"{int(amount):,}"}
    forms = {b + cents for b in bodies} | (bodies if cents == ".00" else set())
    pattern = r"(?<![\d,])(?<!\d\.)(?:%s)(?!\d|,\d|\.\d)" % "|".join(re.escape(f) for f in sorted(forms, key=len, reverse=True))
    return re.search(pattern, text) is not None


# --- per-claim checks -------------------------------------------------------------------------------------------

def check_locator(row: dict, sources: Sources) -> list[str]:
    """The locator resolves: file re-hashed, record or search id present."""
    cid, loc = row["claim_id"], row["locator"]
    if loc["kind"] == "document":
        _, problem = sources.document_text(loc.get("doc_sha256", ""), None)
    elif loc["kind"] == "record":
        found, problem = sources.records(loc.get("source", ""))
        if found and str(loc.get("record_id")) not in found["by_id"]:
            problem = f"record {loc.get('record_id')!r} not found in {loc['source']!r}"
    else:
        ids, problem = sources.search_ids()
        if ids is not None and loc.get("search_id") not in ids:
            problem = f"search_id {loc.get('search_id')!r} not in the search log"
    return [f"{cid}: locator: {problem}"] if problem else []


def check_document_context(row: dict, sources: Sources) -> list[str]:
    """The verbatim context occurs on the located page, and holds the amount when the amount is exact."""
    cid, loc = row["claim_id"], row["locator"]
    text, problem = sources.document_text(loc["doc_sha256"], loc.get("page"))
    if problem:
        return []  # already reported by check_locator
    context = _normalize(loc.get("context", ""))
    if not context or context not in text:
        return [f"{cid}: context not found on page {loc.get('page')}"]
    if row["precision"] == "exact_cents" and not amount_in(context, Decimal(row["amount"])):
        return [f"{cid}: amount does not appear inside the located context"]
    return []


def check_record_field(row: dict, sources: Sources) -> list[str]:
    cid, loc = row["claim_id"], row["locator"]
    found, _ = sources.records(loc["source"])
    record = found["by_id"].get(str(loc["record_id"])) if found else None
    if record is None or row["amount"] is None:
        return [] if record is None else [f"{cid}: record_field claim has no amount"]
    value = _decimal(_get(record, loc.get("field", "amount")))
    if value is None or value != Decimal(row["amount"]):
        return [f"{cid}: amount does not equal the record's {loc.get('field', 'amount')} to the cent"]
    return []


def _matches(row: dict, criteria: dict) -> bool:
    for field, want in criteria.items():
        have = _get(row, field)
        ok = str(have).startswith(want["prefix"]) if isinstance(want, dict) else have == want
        if not ok:
            return False
    return True


def recompute(spec: dict, rows: list[dict]) -> Decimal:
    """The registered recomputations: sum or count of a field over rows matching an exact/prefix filter."""
    chosen = [r for r in rows if _matches(r, spec.get("filter") or {})]
    if spec["name"] == "count":
        return Decimal(len(chosen))
    if spec["name"] != "sum":
        raise ValueError(f"unknown recompute {spec['name']!r}")
    values = [_decimal(_get(r, spec["field"])) for r in chosen]
    if any(v is None for v in values):
        raise ValueError("non-numeric value in summed field")
    return sum(values, Decimal(0))


def check_computed(row: dict, sources: Sources) -> list[str]:
    cid, spec, derivation = row["claim_id"], row["derivation"].get("recompute"), row["derivation"]
    if not isinstance(spec, dict) or "source" not in spec or "name" not in spec:
        return [f"{cid}: computed claim lacks a recompute spec"]
    found, problem = sources.records(spec["source"])
    if problem:
        return [f"{cid}: recompute: {problem}"]
    problems = []
    if derivation.get("artifact_sha") != found["sha"]:
        problems.append(f"{cid}: artifact_sha does not equal the pinned sha256 of {spec['source']!r}")
    try:
        result = recompute(spec, found["rows"])
    except (ValueError, KeyError) as exc:
        return problems + [f"{cid}: recompute failed: {exc}"]
    if row["amount"] is None or result != Decimal(row["amount"]):
        problems.append(f"{cid}: recompute does not reproduce the amount to the cent")
    return problems


def check_status(row: dict) -> list[str]:
    cid, kind = row["claim_id"], row["locator"]["kind"]
    if row["status"] in ("gap", "negative") and kind not in ("search_log", "document"):
        return [f"{cid}: a {row['status']} claim needs a search_log (or absence-document) locator"]
    if row["status"] == "documented" and row["amount"] is not None and kind == "search_log":
        return [f"{cid}: a documented amount must not rest on a search_log locator"]
    return []


def check_register(register_rows: list[dict], sources: dict) -> list[str]:
    """Every problem in the register against its pinned sources (empty list = the register holds)."""
    problems = check_schema(register_rows)
    resolver = Sources(sources)
    for row in register_rows:
        if _row_problems(row):
            continue
        found = check_locator(row, resolver) + check_status(row)
        if not found:
            kind = row["locator"]["kind"]
            if kind == "document":
                found += check_document_context(row, resolver)
            if row["derivation"]["kind"] == "record_field":
                found += (check_record_field(row, resolver) if kind == "record"
                          else [f"{row['claim_id']}: record_field derivation needs a record locator"])
            elif row["derivation"]["kind"] == "computed":
                found += check_computed(row, resolver)
        problems += found
    return problems


# --- CASE.md ----------------------------------------------------------------------------------------------------

FIGURE = re.compile(r"(?P<approx>~\s*|\b(?:about|approximately)\s+)?\$(?P<num>\d[\d,]*(?:\.\d+)?)"
                    r"(?:\s?(?P<suffix>million|M|K)\b)?", re.IGNORECASE)
SCALE = {"million": Decimal(1_000_000), "m": Decimal(1_000_000), "k": Decimal(1_000)}


def _cited(line: str) -> list[str]:
    return [i for group in re.findall(r"\[([^\]]*)\]", line) for i in CLAIM_ID.findall(group)]


def _figure(match: re.Match) -> tuple[Decimal, Decimal | None]:
    """(value, rounding tolerance), tolerance None for an exact figure written without approximation marks."""
    digits = match["num"].replace(",", "")
    scale = SCALE.get((match["suffix"] or "").lower(), Decimal(1))
    value = Decimal(digits) * scale
    if not match["approx"] and not match["suffix"]:
        return value, None
    # Half a unit of the last significant digit: the figure's own rounding.
    if "." in digits:
        place = Decimal(1).scaleb(-len(digits.split(".")[1]))
    else:
        place = Decimal(1).scaleb(len(digits) - len(digits.rstrip("0")))
    return value, place * scale / 2


def check_case_md(text: str, register_rows: list[dict]) -> list[str]:
    by_id = {r["claim_id"]: r for r in register_rows}
    problems, in_q = [], False
    for number, line in enumerate(text.splitlines(), start=1):
        heading = re.match(r"#{1,6}\s", line)
        if heading and re.match(r"#{1,2}\s", line):
            in_q = line.startswith("## Q")
        cited = _cited(line)
        problems += [f"line {number}: cites unknown claim {i}" for i in cited if i not in by_id]
        if in_q and line.strip() and not heading and not cited:
            problems.append(f"line {number}: no claim cited")
        claims = [by_id[i] for i in cited if i in by_id]
        for match in FIGURE.finditer(line):
            value, tolerance = _figure(match)
            if not any(_supports(c, value, tolerance) for c in claims):
                problems.append(f"line {number}: figure {match.group(0).strip()} has no matching cited claim")
    return problems


def _supports(claim: dict, value: Decimal, tolerance: Decimal | None) -> bool:
    amount = _decimal(claim["amount"])
    if amount is None:
        return False
    if tolerance is None:
        return claim["precision"] == "exact_cents" and amount == value
    return claim["precision"] in ("approximate", "projected") and abs(amount - value) <= tolerance


LOADED = re.compile(r"\b(launder|kickback|payoff|patronage|scheme|corrupt|deadbeat|favoritism|quid\s+pro\s+quo)",
                    re.IGNORECASE)
OPEN_QUOTES, CLOSE_QUOTES = '"“', '"”'


def tripwire(text: str) -> list[tuple[int, str]]:
    """Loaded words outside double quotes and blockquotes: a prompt for a human re-read, not proof of anything."""
    hits, inside = [], False
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            inside = False  # an unbalanced quote must not swallow the rest of the document
        if line.lstrip().startswith(">"):
            continue
        outside = []
        for ch in line:
            if inside and ch in CLOSE_QUOTES or not inside and ch in OPEN_QUOTES:
                inside = not inside
                outside.append(" ")
            else:
                outside.append(" " if inside else ch)
        hits += [(number, _word(m)) for m in LOADED.finditer("".join(outside))]
    return hits


def _word(match: re.Match) -> str:
    """The full word the prefix match sits in, lower-cased and whitespace-collapsed."""
    text = match.string
    end = match.end()
    while end < len(text) and text[end].isalpha():
        end += 1
    return " ".join(text[match.start():end].lower().split())


# --- CLI --------------------------------------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--register", required=True, type=Path)
    parser.add_argument("--sources", required=True, type=Path)
    parser.add_argument("--case-md", type=Path)
    args = parser.parse_args(argv)
    try:
        rows = _read_jsonl(args.register)
        problems = check_register(rows, json.loads(args.sources.read_text(encoding="utf-8")))
        if args.case_md:
            text = args.case_md.read_text(encoding="utf-8")
            problems += check_case_md(text, rows)
            problems += [f"line {n}: tripwire word {w!r} outside quotation" for n, w in tripwire(text)]
    except (OSError, ValueError, KeyError) as exc:
        print(f"cannot run: {type(exc).__name__}", file=sys.stderr)
        return 2
    print(f"{len(rows)} claims, {len(problems)} problems")
    for problem in problems:
        print(f"  {problem}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
