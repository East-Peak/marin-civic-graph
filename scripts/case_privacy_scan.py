"""Value-level privacy scan of the grant-chain case outputs.

The case file may name organizations and officials in official capacity, never private individuals: not a
Form 990 officer, preparer or other person, and not an individual contributor from the campaign ledger. The set of
names to keep out is built at run time from the restricted originals themselves (so no name is ever written into
this repository), minus an allowlist of officials, and every case output (bundle, register, CASE.md, report,
diagnostics) is scanned for it.

The scan reports file, line and category only. A matched value is never printed, logged or put in an exception,
so the report is safe to read and to paste.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

Entry = tuple[str, str]  # (name, category)


def _norm(name: str) -> str:
    return " ".join(name.lower().split())


def _tokens(name: str) -> list[str]:
    return name.replace(",", " ").split()


def forbidden_from_990(xml_paths) -> list[Entry]:
    """Every person name in the 990 XML: any element whose local name ends in PersonNm (PersonNm, PreparerPersonNm)."""
    entries = []
    for path in xml_paths:
        for _, element in ET.iterparse(path):
            if element.tag.rsplit("}", 1)[-1].endswith("PersonNm") and (element.text or "").strip():
                entries.append((element.text.strip(), "990_person"))
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


def _words(name: str) -> list[str]:
    """Name tokens of two or more characters; single letters are initials and carry no identifying weight."""
    return [t for t in _tokens(name) if len(re.sub(r"\W", "", t)) >= 2]


def _usable(name: str) -> bool:
    """Matchable without flooding the scan with false hits: at least two real name tokens."""
    return len(_words(name)) >= 2


def _variants(name: str) -> list[str]:
    """The name as given, plus (for 'Jane Q Doe') the form without single-letter middle initials."""
    out = [_norm(name)]
    if len(_words(name)) < len(_tokens(name)):
        out.append(_norm(" ".join(_words(name))))
    return out


def _allowed(name: str) -> set[str]:
    """An allowlist entry in every order it can appear: 'First Last' and 'Last, First'."""
    tokens = _tokens(name)
    flipped = [f"{tokens[-1]}, {' '.join(tokens[:-1])}"] if "," not in name and len(tokens) == 2 else \
        [" ".join(tokens[1:] + tokens[:1])] if "," in name else []
    return {v for n in [name, *flipped] for v in _variants(n)}


def build_forbidden(entries: list[Entry], allow: list[str]) -> tuple[dict[str, str], int]:
    """({normalized name: category}, number of entries skipped as too short to match safely)."""
    allowed = set().union(*(_allowed(a) for a in allow)) if allow else set()
    names, skipped = {}, 0
    for name, category in entries:
        if not _usable(name):
            skipped += 1
            continue
        for variant in _variants(name):
            if variant not in allowed:
                names.setdefault(variant, category)
    return names, skipped


def scan(paths, forbidden: dict[str, str]) -> list[dict]:
    """File/line/category of each hit. The matched text is deliberately never returned."""
    if not forbidden:
        return []
    ordered = sorted(forbidden, key=len, reverse=True)
    pattern = re.compile(r"(?<!\w)(?:%s)(?!\w)" % "|".join(r"\s+".join(map(re.escape, n.split())) for n in ordered),
                         re.IGNORECASE)
    hits = []
    for path in paths:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
        found = {(text.count("\n", 0, m.start()) + 1, forbidden[_norm(m.group(0))]) for m in pattern.finditer(text)}
        hits += [{"file": str(path), "line": line, "category": cat} for line, cat in sorted(found)]
    return hits


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scan", nargs="+", required=True, type=Path, help="case output files to scan")
    parser.add_argument("--xml", nargs="*", default=[], type=Path, help="990 XML originals")
    parser.add_argument("--ledger", nargs="*", default=[], type=Path, help="ledger JSONL files")
    parser.add_argument("--extra", type=Path, help="operator list of further names, one per line")
    parser.add_argument("--allow", type=Path, help="officials allowed by name, one per line")
    args = parser.parse_args(argv)
    entries = forbidden_from_990(args.xml) + forbidden_from_ledger(args.ledger)
    entries += forbidden_from_file(args.extra) if args.extra else []
    allow = forbidden_from_file(args.allow) if args.allow else []
    forbidden, skipped = build_forbidden(entries, [name for name, _ in allow])
    counts = Counter(forbidden.values())
    print("forbidden names: " + (", ".join(f"{c} {n}" for c, n in sorted(counts.items())) or "none")
          + f"; skipped {skipped} too short to match")
    hits = scan(args.scan, forbidden)
    print(f"{len(hits)} hits")
    for hit in hits:
        print(f"{hit['file']}:{hit['line']}:{hit['category']}")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
