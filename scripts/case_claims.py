"""The claim-register checker for the grant-chain case file.

A case file is only as good as the link between each sentence and its source. The register holds one row per
claim; this module re-derives every claim from the bytes behind it so that nothing rests on a typed number:

- the derivation and locator must be a compatible pair, and every exact amount runs a check: a quoted amount must
  sit, as a currency token, inside a verbatim context at a pinned page / line / XML element of a re-hashed
  document; a record_field amount equals the record's field; a computed amount is reproduced by a registered
  recomputation (sum/count) over the pinned source;
- a gap or negative claim carries no amount and points into a re-hashed, fully populated search log;
- approximate and projected figures are labelled and can never be marked reconciled.

CASE.md is then checked against the register: every sentence of an answer section cites a claim, every dollar
figure sits in a sentence that cites a claim of that amount, and a word-list tripwire reports loaded words outside
quotations (a tripwire for a human reader, not proof of anything).

Reports never repeat claim text: they name validated claim ids and line numbers only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from pathlib import Path

QUESTIONS = {"Q1", "Q2", "Q3", "Q4", "Q5", "Q6", "X"}
PRECISIONS = {"exact_cents", "approximate", "projected", "none"}
STATUSES = {"documented", "partially_documented", "gap", "negative"}
DERIVATIONS = {"quoted", "record_field", "computed"}
REQUIRED = ("claim_id", "question", "text", "amount", "precision", "locator", "derivation", "status", "reconciled")
SEARCH_FIELDS = ("search_id", "question", "source", "query_or_path", "performed_at", "result", "stop_reason",
                 "next_step")
CENTS = re.compile(r"-?\d+\.\d{2}")
CLAIM_ID = re.compile(r"C-[A-Z0-9-]+")
MINUS = "-−"


# --- register schema --------------------------------------------------------------------------------------------

def _label(row, number: int) -> str:
    """What a report may call a row: its claim id if well-formed, else its position. Never unvalidated text."""
    cid = row.get("claim_id") if isinstance(row, dict) else None
    return cid if isinstance(cid, str) and CLAIM_ID.fullmatch(cid) else f"row {number}"


def _decimal(value) -> Decimal | None:
    if not isinstance(value, str):
        return None
    try:
        number = Decimal(value)
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


def _is_pos_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _row_problems(row, label: str) -> list[str]:
    if not isinstance(row, dict):
        return [f"{label}: not an object"]
    problems = [f"{label}: missing key {key}" for key in REQUIRED if key not in row]
    if problems:
        return problems
    for key, allowed in (("question", QUESTIONS), ("precision", PRECISIONS), ("status", STATUSES)):
        if row[key] not in allowed:
            problems.append(f"{label}: {key} is not one of the allowed values")
    if not isinstance(row["claim_id"], str) or not CLAIM_ID.fullmatch(row["claim_id"]):
        problems.append(f"{label}: claim_id must match C-[A-Z0-9-]+")
    amount, precision = row["amount"], row["precision"]
    if amount is not None and _decimal(amount) is None:
        problems.append(f"{label}: amount is not a decimal string")
    elif precision == "exact_cents" and not (isinstance(amount, str) and CENTS.fullmatch(amount)):
        problems.append(f"{label}: exact_cents amount must be a decimal string with exactly 2 decimals")
    if precision == "none" and amount is not None:
        problems.append(f"{label}: precision none requires a null amount")
    if precision in ("approximate", "projected") and row["reconciled"] is True:
        problems.append(f"{label}: {precision} figure must not be marked reconciled")
    locator, derivation = row["locator"], row["derivation"]
    kind = locator.get("kind") if isinstance(locator, dict) else None
    dkind = derivation.get("kind") if isinstance(derivation, dict) else None
    if kind not in ("document", "record", "search_log"):
        problems.append(f"{label}: locator.kind must be document, record or search_log")
    if dkind not in DERIVATIONS:
        problems.append(f"{label}: derivation.kind must be one of {sorted(DERIVATIONS)}")
    return problems or _pairing_problems(row, label, kind, dkind)


def _pairing_problems(row: dict, label: str, kind: str, dkind: str) -> list[str]:
    """The derivation/locator/status/amount compatibility matrix: no exact amount escapes a check."""
    problems = []
    needs = {"quoted": ("document", "search_log"), "record_field": ("record",)}
    if dkind in needs and kind not in needs[dkind]:
        problems.append(f"{label}: a {dkind} derivation cannot use a {kind} locator")
    if row["precision"] == "exact_cents" and (dkind, kind) not in (("quoted", "document"), ("record_field", "record"),
                                                                    ("computed", "document"), ("computed", "record")):
        problems.append(f"{label}: an exact amount must be quoted from a document, read from a record, or computed")
    if row["status"] in ("gap", "negative"):
        if row["amount"] is not None or kind != "search_log":
            problems.append(f"{label}: a {row['status']} claim has a null amount and a search_log locator")
    elif row["amount"] is not None and kind == "search_log":
        problems.append(f"{label}: an amount must not rest on a search_log locator")
    return problems


def check_schema(rows: list[dict]) -> list[str]:
    problems, seen = [], set()
    for number, row in enumerate(rows, start=1):
        label = _label(row, number)
        problems += _row_problems(row, label)
        if not label.startswith("row "):
            if label in seen:
                problems.append(f"{label}: duplicate claim_id")
            seen.add(label)
    return problems


# --- sources: pinned files, re-hashed on first use --------------------------------------------------------------

class Sources:
    """The operator's sources JSON, with every file re-hashed before it is believed. Errors come back as strings."""

    def __init__(self, spec: dict):
        self.spec = spec
        self._hashes: dict[str, str | None] = {}
        self._docs: dict[str, str] | None = None
        self._records: dict[str, tuple] = {}
        self._units: dict[tuple, tuple] = {}
        self._log: tuple | None = None

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

    def unit_text(self, sha: str, loc: dict) -> tuple[str | None, str | None]:
        """(whitespace-normalized text at the locator's page / line / element, problem)."""
        key = (sha, loc.get("page"), loc.get("line"), loc.get("element"))
        if key not in self._units:
            self._units[key] = self._locate(sha, loc)
        return self._units[key]

    def _locate(self, sha: str, loc: dict) -> tuple[str | None, str | None]:
        path = self._document_paths().get(sha)
        if path is None:
            return None, "document not in sources"
        problem = self._verified(path, sha, "document")
        if problem:
            return None, problem
        data = Path(path).read_bytes()
        kind = _doc_kind(Path(path), data)
        wanted = {"pdf": "page", "html": "line", "text": "line", "xml": "element"}[kind]
        given = {k for k in ("page", "line", "element") if loc.get(k) is not None}
        if given != {wanted}:
            return None, f"a {kind} document needs exactly a {wanted} locator"
        if kind == "xml":
            return _xml_element_text(data, loc["element"])
        position = loc[wanted]
        if not _is_pos_int(position):
            return None, f"{wanted} must be a positive integer"
        if kind == "pdf":
            return _pdf_page_text(Path(path), position)
        lines = [n for n in map(_normalize, _plain_text(data, kind).split("\n")) if n]
        if position > len(lines):
            return None, "line is beyond the end of the document"
        return lines[position - 1], None

    def records(self, label) -> tuple[dict | None, str | None]:
        """(rows, by id, pinned sha; problem). The source file is re-hashed against its pin."""
        if label not in self._records:
            self._records[label] = self._load_records(label)
        return self._records[label]

    def _load_records(self, label) -> tuple[dict | None, str | None]:
        spec = self.spec.get("records", {}).get(label) if isinstance(label, str) else None
        if spec is None:
            return None, "record source not in sources"
        problem = self._verified(spec["path"], spec["sha256"], "record source")
        if problem:
            return None, problem
        try:
            rows = _load_rows(spec)
            by_id = {str(_get(r, spec["id_field"])): r for r in rows}
        except (ValueError, KeyError, IndexError, TypeError, AttributeError):
            return None, "record source: cannot read rows"
        return {"rows": rows, "by_id": by_id, "sha": spec["sha256"]}, None

    def search_rows(self) -> tuple[dict | None, str | None]:
        if self._log is None:
            self._log = self._load_log()
        return self._log

    def _load_log(self) -> tuple[dict | None, str | None]:
        spec = self.spec.get("search_log")
        if spec is None:
            return None, "search log not in sources"
        problem = self._verified(spec["path"], spec["sha256"], "search log")
        if problem:
            return None, problem
        try:
            return {r["search_id"]: r for r in _read_jsonl(Path(spec["path"]))}, None
        except (ValueError, KeyError, TypeError):
            return None, "search log: cannot read rows"


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


BLOCK_TAGS = {"p", "div", "br", "li", "ul", "ol", "tr", "td", "th", "table", "section", "article", "header",
              "footer", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre"}


class _TextOnly(HTMLParser):
    """Visible text, one line per block element; scripts and styles dropped."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        self._skip += tag in ("script", "style")
        if tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        self._skip -= tag in ("script", "style") and self._skip > 0
        if tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def _doc_kind(path: Path, data: bytes) -> str:
    if data.startswith(b"%PDF"):
        return "pdf"
    if path.suffix.lower() in (".html", ".htm"):
        return "html"
    if path.suffix.lower() == ".xml" or data.lstrip().startswith(b"<?xml"):
        return "xml"
    return "text"


def _plain_text(data: bytes, kind: str) -> str:
    text = data.decode("utf-8", errors="replace")
    if kind == "html":
        parser = _TextOnly()
        parser.feed(text)
        return "".join(parser.parts)
    return text


def _pdf_page_text(path: Path, page: int) -> tuple[str | None, str | None]:
    done = subprocess.run(["pdftotext", "-layout", "-f", str(page), "-l", str(page), str(path), "-"],
                          capture_output=True, check=False)
    if done.returncode != 0:
        return None, "page could not be extracted"
    return _normalize(done.stdout.decode("utf-8", errors="replace")), None


_SEGMENT = re.compile(r"([A-Za-z_][\w.-]*)(?:\[([1-9]\d*)\])?")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _xml_element_text(data: bytes, path: str) -> tuple[str | None, str | None]:
    """Text of the one element at a local-name path like 'A/B[3]/C': the first segment matches anywhere,
    later ones are children; [n] is the 1-based index among same-named matches."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return None, "xml document is unreadable"
    segments = [_SEGMENT.fullmatch(s) for s in str(path).split("/")]
    if not path or None in segments:
        return None, "element path is malformed"

    def pick(nodes, segment):
        nodes = [n for n in nodes if _local(n.tag) == segment[1]]
        return nodes[int(segment[2]) - 1:int(segment[2])] if segment[2] else nodes

    found = pick(root.iter(), segments[0])
    for segment in segments[1:]:
        found = [hit for node in found for hit in pick(list(node), segment)]
    if len(found) != 1:
        return None, f"element path matches {len(found)} elements, needs exactly 1"
    return _normalize(" ".join(found[0].itertext())), None


# A currency token: optional sign / parentheses, optional $, digits with commas, optional decimals.
INT = r"\d{1,3}(?:,\d{3})+|\d+"
MONEY = re.compile(rf"(?<![\w,.])(?P<open>\()?(?P<s1>[{MINUS}])?(?P<cur>\$)?(?P<s2>[{MINUS}])?(?P<int>{INT})"
                   rf"(?P<frac>\.\d+)?(?P<word>\s(?:million|billion|thousand)(?!\w))?(?P<close>\))?(?!\w|,\d|\.\d)",
                   re.IGNORECASE)
WORD_SCALE = {"million": Decimal(1_000_000), "billion": Decimal(10**9), "thousand": Decimal(1_000)}


def _signed(match: re.Match) -> Decimal:
    """The token's value; a written scale ("$2 million") counts only on a $ token, never on a bare number."""
    value = Decimal(match["int"].replace(",", "") + (match["frac"] or ""))
    if match["word"]:
        value *= WORD_SCALE[match["word"].strip().lower()] if match["cur"] else Decimal("NaN")
    return -value if match["s1"] or match["s2"] or (match["open"] and match["close"]) else value


def amount_in(unit: str, context: str, amount: Decimal, bare_ok: bool = False) -> bool:
    """True when a currency token overlapping the context, read with its sign from the full unit text, equals the
    amount ($1,234 / -$100 / ($100) ...). A sign or parenthesis just outside the context still counts, so a source
    "-$100.00" never supports +100.00. A bare number (no $) only counts when it is the unit's entire text."""
    starts = [m.start() for m in re.finditer(re.escape(context), unit)]
    return any(m.start() < start + len(context) and m.end() > start and _signed(m) == amount
               for start in starts for m in MONEY.finditer(unit)
               if m["cur"] or (bare_ok and m.group(0) == unit.strip()))


# --- per-claim checks -------------------------------------------------------------------------------------------

def check_locator(row: dict, sources: Sources) -> list[str]:
    """The locator resolves: file re-hashed, shape right for its format, record or search entry present."""
    cid, loc = row["claim_id"], row["locator"]
    if loc["kind"] == "document":
        _, problem = sources.unit_text(str(loc.get("doc_sha256", "")), loc)
    elif loc["kind"] == "record":
        found, problem = sources.records(loc.get("source"))
        if found and str(loc.get("record_id")) not in found["by_id"]:
            problem = "record not found in its source"
    else:
        problem = _search_problem(row, sources)
    return [f"{cid}: locator: {problem}"] if problem else []


def _search_problem(row: dict, sources: Sources) -> str | None:
    rows, problem = sources.search_rows()
    if problem:
        return problem
    entry = rows.get(row["locator"].get("search_id"))
    if entry is None:
        return "search_id not in the search log"
    if any(not isinstance(entry.get(f), str) or not entry[f].strip() for f in SEARCH_FIELDS):
        return "search log row is incomplete"
    if entry["question"] != row["question"]:
        return "search log row answers a different question"
    return None


def _amount_element(loc: dict) -> bool:
    """A bare number is a monetary field only when the element locator ends in an IRS amount element (...Amt)."""
    last = str(loc.get("element") or "").rsplit("/", 1)[-1]
    return re.sub(r"\[\d+\]$", "", last).endswith("Amt")


def check_document_context(row: dict, sources: Sources) -> list[str]:
    """The verbatim context occurs at the located page/line/element, and holds the amount when it is exact."""
    cid, loc = row["claim_id"], row["locator"]
    unit, problem = sources.unit_text(str(loc.get("doc_sha256", "")), loc)
    if problem:
        return []  # already reported by check_locator
    context = _normalize(str(loc.get("context", "")))
    if not context or context not in unit:
        return [f"{cid}: context not found at the located position"]
    if row["precision"] == "exact_cents" and not amount_in(
            unit, context, Decimal(row["amount"]), bare_ok=_amount_element(loc)):
        return [f"{cid}: amount does not appear as a currency token inside the located context"]
    return []


def check_record_field(row: dict, sources: Sources) -> list[str]:
    cid, loc = row["claim_id"], row["locator"]
    found, _ = sources.records(loc["source"])
    record = found["by_id"].get(str(loc["record_id"])) if found else None
    if record is None:
        return []
    if row["amount"] is None:
        return [f"{cid}: record_field claim has no amount"]
    try:
        value = _decimal(str(_get(record, loc.get("field", "amount"))))
    except (TypeError, AttributeError):
        value = None
    if value is None or value != Decimal(row["amount"]):
        return [f"{cid}: amount does not equal the record's field to the cent"]
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
        raise ValueError("unknown recompute")
    values = [_decimal(str(_get(r, spec["field"]))) for r in chosen]
    if any(v is None for v in values):
        raise ValueError("non-numeric value in summed field")
    return sum(values, Decimal(0))


def check_computed(row: dict, sources: Sources) -> list[str]:
    cid, derivation = row["claim_id"], row["derivation"]
    spec = derivation.get("recompute")
    if not isinstance(spec, dict) or "source" not in spec or "name" not in spec:
        return [f"{cid}: computed claim lacks a recompute spec"]
    found, problem = sources.records(spec["source"])
    if problem:
        return [f"{cid}: recompute: {problem}"]
    problems = []
    if derivation.get("artifact_sha") != found["sha"]:
        problems.append(f"{cid}: artifact_sha does not equal the pinned sha256 of the recompute source")
    try:
        result = recompute(spec, found["rows"])
    except (ValueError, KeyError, TypeError, AttributeError):
        return problems + [f"{cid}: recompute failed"]
    if row["amount"] is None or result != Decimal(row["amount"]):
        problems.append(f"{cid}: recompute does not reproduce the amount to the cent")
    return problems


def check_register(register_rows: list[dict], sources: dict) -> list[str]:
    """Every problem in the register against its pinned sources (empty list = the register holds)."""
    problems = check_schema(register_rows)
    resolver = Sources(sources)
    for number, row in enumerate(register_rows, start=1):
        if _row_problems(row, _label(row, number)):
            continue
        found = check_locator(row, resolver)
        if not found:
            kind, dkind = row["locator"]["kind"], row["derivation"]["kind"]
            if kind == "document":
                found += check_document_context(row, resolver)
            if dkind == "record_field":
                found += check_record_field(row, resolver)
            elif dkind == "computed":
                found += check_computed(row, resolver)
        problems += found
    return problems


# --- CASE.md ----------------------------------------------------------------------------------------------------

SUFFIX = r"(?:\s?(?:million|billion|thousand|[MBK])\b)"
APPROX = r"(?:~\s*|\b(?:about|approximately|roughly|nearly|some)\s+)"
FIGURE = re.compile(
    rf"(?P<approx>{APPROX})?(?P<open>\()?(?P<s1>[{MINUS}])?\$(?P<s2>[{MINUS}])?(?P<num>{INT})(?P<frac>\.\d+)?"
    rf"(?P<suf>{SUFFIX})?(?P<close>\))?"
    rf"(?:(?P<sep>\s*(?:[–—-]|to)\s*)(?P<s3>[{MINUS}])?(?P<cur2>\$)?(?P<s4>[{MINUS}])?(?P<num2>{INT})(?P<frac2>\.\d+)?(?P<suf2>{SUFFIX})?)?",
    re.IGNORECASE)
SCALE = {"million": Decimal(1_000_000), "m": Decimal(1_000_000), "billion": Decimal(10**9), "b": Decimal(10**9),
         "thousand": Decimal(1_000), "k": Decimal(1_000)}


def _endpoint(digits: str, frac: str | None, suffix: str | None, negative: bool, approximate: bool):
    """(value, rounding tolerance); tolerance None for a figure written without approximation language."""
    scale = SCALE.get((suffix or "").strip().lower(), Decimal(1))
    number = digits.replace(",", "") + (frac or "")
    value = Decimal(number) * scale * (-1 if negative else 1)
    if not approximate:
        return value, None
    # Half a unit of the figure's own last significant digit.
    place = Decimal(1).scaleb(-len(frac) + 1) if frac else Decimal(1).scaleb(len(number) - len(number.rstrip("0")))
    return value, place * scale / 2


def figures(line: str):
    """(display text, value, tolerance) for every dollar figure in a unit, with both ends of a range.

    A range's first endpoint inherits a trailing suffix ("$2-$3 million") only if that keeps it at or below the
    second ("$500 to $2M" stays 500); a range still reversed is reported with value None."""
    for m in FIGURE.finditer(line):
        negative = bool(m["s1"] or m["s2"] or (m["open"] and m["close"]))
        approximate = bool(m["approx"])
        text = m.group(0).strip()
        first = _endpoint(m["num"], m["frac"], m["suf"], negative, approximate)
        if not m["num2"]:
            yield (text, *first)
            continue
        second = _endpoint(m["num2"], m["frac2"], m["suf2"] or (m["suf"] if not m["cur2"] else None),
                           bool(m["s3"] or m["s4"]), approximate)
        if not m["suf"] and m["suf2"]:
            scaled = _endpoint(m["num"], m["frac"], m["suf2"], negative, approximate)
            first = scaled if scaled[0] <= second[0] else first
        if first[0] > second[0]:
            yield (text, None, None)
        else:
            yield (text, *first)
            yield (text, *second)


def _supports(claim: dict, value: Decimal, tolerance: Decimal | None) -> bool:
    amount = _decimal(claim["amount"])
    if amount is None:
        return False
    if tolerance is None:
        return claim["precision"] == "exact_cents" and amount == value
    return claim["precision"] in ("approximate", "projected") and abs(amount - value) <= tolerance


ABBREVIATIONS = {"e.g", "i.e", "vs", "mr", "ms", "mrs", "dr", "jr", "sr", "no"}  # "Inc. Approved" is a sentence end
STRUCTURAL_HEADINGS = {"what the records show", "what the records do not show", "public-funds connection", "gaps",
                       "sources searched"}
LIST_ITEM = re.compile(r"\s*(?:[-*+]|\d+[.)])\s+")
SEPARATOR = re.compile(r"[\s|:*_=-]{3,}")
HEADING = re.compile(r"(#{1,6})\s+(.*)")


def _sentences(text: str) -> list[tuple[int, str]]:
    """(offset, sentence) pairs, splitting at . ! ? before whitespace but not at abbreviations or initials."""
    found, start = [], 0
    for m in re.finditer(r"[.!?][\"')\]]*(?=\s|$)", text):
        if text[m.start()] == ".":
            following = text[m.end():].lstrip()[:1]
            if following and (following.islower() or following.isdigit()):
                continue  # "approx. 2.5", "U.S. agency": the sentence goes on
            word = re.search(r"(\S+)$", text[start:m.start()])
            w = word.group(1).lower().lstrip("([\"'") if word else ""
            if w in ABBREVIATIONS or re.fullmatch(r"[a-z]", w) or re.search(r"\w\.\w", w):
                continue
        found.append((start, text[start:m.end()]))
        start = m.end()
    found.append((start, text[start:]))
    return [(o + len(s) - len(s.lstrip()), s.strip()) for o, s in found if s.strip()]


def _units(text: str):
    """(line, text, role, in_answer) for each heading and each sentence of the document."""
    paragraph: list[tuple[int, str]] = []
    in_answer = False

    def flush():
        if paragraph:
            joined = "\n".join(line for _, line in paragraph)
            for offset, sentence in _sentences(joined):
                yield paragraph[0][0] + joined.count("\n", 0, offset), sentence, "body", in_answer
        paragraph.clear()

    for number, line in enumerate(text.splitlines(), start=1):
        body = re.sub(r"^\s*>+\s?", "", line)
        heading = HEADING.fullmatch(line.strip())
        if heading:
            yield from flush()
            level, title = len(heading[1]), heading[2].strip()
            if level <= 2:
                in_answer = level == 2 and re.match(r"Q[1-6]\b", title) is not None
            yield number, title, f"h{level}", in_answer
        elif not body.strip() or SEPARATOR.fullmatch(body):
            yield from flush()
        else:
            item = LIST_ITEM.match(body)
            if item or body.lstrip().startswith("|"):
                yield from flush()
            paragraph.append((number, body[item.end():] if item else body))
    yield from flush()


def _cited(unit: str) -> list[str]:
    return [i for group in re.findall(r"\[([^\]]*)\]", unit) for i in re.findall(r"C-[A-Z0-9-]+", group)]


def check_case_md(text: str, register_rows: list[dict]) -> list[str]:
    """Every answer sentence and every dollar figure is backed by a cited claim of the right amount."""
    by_id = {r["claim_id"]: r for r in register_rows if isinstance(r, dict) and "claim_id" in r}
    problems = []
    for number, unit, role, in_answer in _units(text):
        cited = _cited(unit)
        problems += [f"line {number}: cites unknown claim {i}" for i in cited if i not in by_id]
        if role.startswith("h") and re.match(r"(?:q|question)\s*\.?\s*\d", unit, re.IGNORECASE) \
                and not (role == "h2" and re.fullmatch(r"Q[1-6]", unit.strip())):
            problems.append(f"line {number}: answer heading must read exactly '## Q1' to '## Q6'")
        if in_answer and role == "body" and not cited:
            problems.append(f"line {number}: no claim cited")
        if in_answer and role not in ("body", "h1", "h2") and not cited \
                and unit.strip().rstrip(":").lower() not in STRUCTURAL_HEADINGS:
            problems.append(f"line {number}: heading states a fact without a cited claim")
        claims = [by_id[i] for i in cited if i in by_id]
        for display, value, tolerance in figures(unit):
            if value is None:
                problems.append(f"line {number}: range {display} is reversed")
            elif not any(_supports(c, value, tolerance) for c in claims):
                problems.append(f"line {number}: figure {display} has no matching cited claim")
    return problems


LOADED = re.compile(r"\b(launder|kickback|payoff|patronage|scheme|corrupt|deadbeat|favoritism|quid\s+pro\s+quo)",
                    re.IGNORECASE)


def _mask_quotes(paragraph: str) -> str:
    """Blank out balanced quotation spans (curly pairs; straight quotes only if they pair up evenly)."""
    chars = list(paragraph)

    def blank(start: int, end: int):
        chars[start:end] = [c if c == "\n" else " " for c in chars[start:end]]

    for m in re.finditer("“[^“”]*”", paragraph):
        blank(*m.span())
    straight = [i for i, c in enumerate(chars) if c == '"']
    if len(straight) % 2 == 0:
        for a, b in zip(straight[::2], straight[1::2]):
            blank(a, b + 1)
    return "".join(chars)


def _word(match: re.Match) -> str:
    """The full word the prefix match sits in, lower-cased and whitespace-collapsed."""
    text, end = match.string, match.end()
    while end < len(text) and text[end].isalpha():
        end += 1
    return " ".join(text[match.start():end].lower().split())


def tripwire(text: str) -> list[tuple[int, str]]:
    """Loaded words outside quotations and blockquotes: a prompt for a human re-read, not proof of anything.

    Quotation masking is per paragraph, so a stray quote mark cannot hide later paragraphs; a phrase split
    across a line break still matches."""
    hits, paragraph = [], []

    def flush():
        if paragraph:
            masked = _mask_quotes("\n".join(line for _, line in paragraph))
            hits.extend((paragraph[0][0] + masked.count("\n", 0, m.start()), _word(m)) for m in LOADED.finditer(masked))
        paragraph.clear()

    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith(">"):
            flush()
        else:
            paragraph.append((number, line))
    flush()
    return hits


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
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        print(f"cannot run: {type(exc).__name__}", file=sys.stderr)
        return 2
    print(f"{len(rows)} claims, {len(problems)} problems")
    for problem in problems:
        print(f"  {problem}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
