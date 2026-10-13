"""Value-level privacy scan of the grant-chain case outputs.

The case file may name organizations and officials in official capacity, never private individuals: not a
Form 990 officer, preparer or other person, not the free text of Schedule I Part III (grants to individuals), and
not an individual contributor from the campaign ledger. The set of values to keep out is built at run time from
the restricted originals themselves (so none is ever written into this repository), minus an allowlist of
officials, and every case output (bundle, register, CASE.md, report, diagnostics) is scanned for it.

Names are matched in every common shape: First Last, Last, First, with or without middle names or initials,
case, punctuation and line breaks ignored; JSON files are also scanned as decoded string values, so escaped line
breaks cannot hide a name.

The scan reports file, line and category only. A matched value is never printed, logged or put in an exception.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

Entry = tuple[str, str]  # (value, category)
PART_III_GROUPS = {"GrantsOtherAsstToIndivInUSGrp"}  # Schedule I Part III: grants and assistance to individuals
SEP = r"[\s,.\-]+"
MIDDLE = rf"(?:{SEP}[^\W\d_]+(?=[\s,.\-])){{0,2}}"  # an inserted middle name or initial
APOSTROPHES = re.compile("['’]")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _tokens(text: str) -> list[str]:
    return re.findall(r"[^\W_]+", APOSTROPHES.sub("", text).lower())


def forbidden_from_990(xml_paths) -> list[Entry]:
    """Person names (any element ending in PersonNm) and every text under the Schedule I Part III groups."""
    entries = []
    for path in xml_paths:
        root = ET.parse(path).getroot()
        for element in root.iter():
            text = (element.text or "").strip()
            if text and _local(element.tag).endswith("PersonNm"):
                entries.append((text, "990_person"))
            if _local(element.tag) in PART_III_GROUPS:
                entries += [(t, "990_part_iii") for e in element.iter() if (t := (e.text or "").strip())]
    return entries


def forbidden_from_ledger(ledger_paths) -> list[Entry]:
    """Individual (entity_cd IND) contributors in a ledger JSONL, as 'First Last' and 'Last, First'."""
    entries = []
    for path in ledger_paths:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            row = json.loads(line) if line.strip() else {}
            if row.get("entity_cd") != "IND":
                continue
            first, last = ((row.get("name") or {}).get(part) or "" for part in ("first", "last"))
            entries += [(f"{first} {last}", "individual_contributor"), (f"{last}, {first}", "individual_contributor")]
    return entries


def forbidden_from_file(path) -> list[Entry]:
    """An operator-provided list, one name per line (blank lines and # comments ignored)."""
    lines = (line.strip() for line in Path(path).read_text(encoding="utf-8").splitlines())
    return [(line, "operator_list") for line in lines if line and not line.startswith("#")]


def _name_keys(name: str) -> set[str]:
    """Every ordering and middle-name form of a person's name, as space-joined lowercase tokens; empty if the name
    lacks two real tokens (single letters are initials and do not count)."""
    if "," in name:
        family, given = name.split(",", 1)
        last, rest = [t for t in _tokens(family) if len(t) > 1], [t for t in _tokens(given) if len(t) > 1]
        first, middles = rest[:1], rest[1:]
    else:
        real = [t for t in _tokens(name) if len(t) > 1]
        first, middles, last = real[:1], real[1:-1], real[-1:] if len(real) > 1 else []
    if not (first and last):
        return set()
    forms = [first + middles + last, first + last, last + first + middles, last + first]
    return {" ".join(form) for form in forms}


def _phrase_key(text: str) -> str | None:
    """A Part III phrase: at least two tokens and some letters (bare amounts and codes are not private text)."""
    tokens = _tokens(text)
    return " ".join(tokens) if len(tokens) >= 2 and any(c.isalpha() for c in text) else None


def build_forbidden(entries: list[Entry], allow: list[str]) -> tuple[dict[str, str], int]:
    """({normalized key: category}, number of entries skipped as too short to match safely)."""
    allowed = set().union(*(_name_keys(a) | _name_keys(" ".join(reversed(_tokens(a)))) for a in allow)) \
        if allow else set()
    names, skipped = {}, 0
    for value, category in entries:
        if category == "990_part_iii":
            keys = {key} if (key := _phrase_key(value)) else set()
        else:
            keys = _name_keys(value)
        skipped += not keys
        for key in keys - allowed:
            names.setdefault(key, category)
    return names, skipped


def _pattern(keys) -> re.Pattern:
    def one(key: str) -> str:
        tokens = [re.escape(t) for t in key.split()]
        return (tokens[0] + MIDDLE + SEP + tokens[1]) if len(tokens) == 2 else SEP.join(tokens)

    return re.compile(r"(?<!\w)(?:%s)(?!\w)" % "|".join(one(k) for k in sorted(keys)), re.IGNORECASE)


def _strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for key, value in node.items():
            yield from _strings(key)
            yield from _strings(value)
    elif isinstance(node, list):
        for item in node:
            yield from _strings(item)


def _chunks(path: Path, text: str):
    """(line, text, spans_lines): the raw text, plus for JSON the decoded string values (line 0 = whole document)."""
    yield 1, text, True
    try:
        if path.suffix == ".jsonl":
            for number, line in enumerate(text.splitlines(), start=1):
                if line.strip():
                    yield number, "\n".join(_strings(json.loads(line))), False
        elif path.suffix == ".json":
            yield 0, "\n".join(_strings(json.loads(text))), False
    except ValueError:
        return  # not valid JSON: the raw scan above still covered it


def scan(paths, forbidden: dict[str, str]) -> list[dict]:
    """File/line/category of each hit. The matched text is deliberately never returned."""
    by_category: dict[str, list[str]] = {}
    for key, category in forbidden.items():
        by_category.setdefault(category, []).append(key)
    patterns = {category: _pattern(keys) for category, keys in by_category.items()}
    hits = []
    for path in map(Path, paths):
        text = path.read_text(encoding="utf-8", errors="replace")
        found = set()
        for line, chunk, spans in _chunks(path, text):
            chunk = APOSTROPHES.sub("", chunk)
            for category, pattern in patterns.items():
                found |= {(line + (chunk.count("\n", 0, m.start()) if spans else 0), category)
                          for m in pattern.finditer(chunk)}
        hits += [{"file": str(path), "line": line, "category": category} for line, category in sorted(found)]
    return hits


def _shown(path) -> str:
    """A path as it may be printed: as given when relative, else just the file name."""
    path = Path(path)
    return path.name if path.is_absolute() else str(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scan", nargs="+", required=True, type=Path, help="case output files to scan")
    parser.add_argument("--xml", nargs="*", default=[], type=Path, help="990 XML originals")
    parser.add_argument("--ledger", nargs="*", default=[], type=Path, help="ledger JSONL files")
    parser.add_argument("--extra", type=Path, help="operator list of further names, one per line")
    parser.add_argument("--allow", type=Path, help="officials allowed by name, one per line")
    args = parser.parse_args(argv)
    sources = [*args.xml, *args.ledger, *([args.extra] if args.extra else [])]
    if not sources:
        print("cannot run: no sources given (--xml, --ledger or --extra)", file=sys.stderr)
        return 2
    try:
        entries = forbidden_from_990(args.xml) + forbidden_from_ledger(args.ledger)
        entries += forbidden_from_file(args.extra) if args.extra else []
        allow = [name for name, _ in forbidden_from_file(args.allow)] if args.allow else []
        forbidden, skipped = build_forbidden(entries, allow)
        digests = [(_shown(p), hashlib.sha256(p.read_bytes()).hexdigest()) for p in sources]
        hits = scan(args.scan, forbidden)
    except (OSError, ValueError, KeyError, TypeError, ET.ParseError) as exc:
        print(f"cannot run: {type(exc).__name__}", file=sys.stderr)
        return 2
    for name, digest in digests:
        print(f"source {name} sha256 {digest}")
    counts = Counter(forbidden.values())
    print("forbidden values: " + (", ".join(f"{c} {n}" for n, c in sorted(counts.items())) or "none")
          + f"; skipped {skipped} too short to match")
    print(f"{len(hits)} hits")
    for hit in hits:
        print(f"{_shown(hit['file'])}:{hit['line']}:{hit['category']}")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
