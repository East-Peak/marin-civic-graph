"""A fictional campaign-finance world for the person-identity tests: raw NetFile workbooks WITH contributor
streets, the ledger bundle built from them by the real pipeline, a backup-shaped graph export, and a decision file.

Every name, street and committee here is invented. Streets are filled in on purpose: the tests prove they never
leave memory. Treasurer and intermediary streets are filled in too, to prove they are never read.
"""
from __future__ import annotations

import copy
import hashlib
import json
import sys
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from campaign_ledger import build_ledger, build_transactions, write_ledger  # noqa: E402
from normalize_campaign_finance import normalize_campaign_source  # noqa: E402
from tests.netfile_workbooks import HEADERS, contribution, expenditure, filing, summary, write_export  # noqa: E402

SOURCE = "example-cf"
CAPTURE = "2026-10-01"
YEAR = "2024"
EXTRA_COLS = ["Tres_NamL", "Tres_Adr1", "Tres_Adr2", "Tres_Zip", "Intr_Adr1", "Intr_Adr2", "Intr_Zip4"]
LAYOUT = {**HEADERS, "A-Contributions": HEADERS["A-Contributions"] + EXTRA_COLS}

# Every street value the world can hold, raw: the privacy scans look for each of these and its canonical form.
STREETS = ("12 Sample Street", "Apt. 3", "400 Example Avenue", "77 Fictional Way", "5 Placeholder Lane",
           "9 Imaginary Court", "31 Invented Road", "88 Madeup Drive", "250 Notreal Blvd")
TREASURER_STREET = "1 Treasurer Terrace"
INTERMEDIARY_STREET = "2 Intermediary Ivy Lane"
CANONICAL_STREETS = ("12 SAMPLE ST", "12 SAMPLE ST UNIT 3", "400 EXAMPLE AVE", "77 FICTIONAL WAY", "5 PLACEHOLDER LN",
                     "9 IMAGINARY CT", "31 INVENTED RD", "88 MADEUP DR", "250 NOTREAL BLVD",
                     "1 TREASURER TER", "2 INTERMEDIARY IVY LN")

COUNCIL = filing("1400001", "Friends of Example for Council 2024", rpt="2024-02-01", start="2024-01-01",
                 thru="2024-01-31")
COUNCIL_2 = filing("1400001", "Friends of Example for Council 2024", rpt="2024-03-01", start="2024-02-01",
                   thru="2024-02-29")
MEASURE = filing("1400002", "Example Measure Committee", rpt="2024-02-05", start="2024-01-01", thru="2024-01-31")


def _c(f, tran_id, amount, last, first, street, adr2="", zip_="94901", **extra):
    return contribution(f, tran_id, amount, last=last, first=first, Tran_Adr1=street, Tran_Adr2=adr2,
                        Tran_Zip4=zip_, Tran_City="Exampleton", Tran_State="CA", Tran_Occ="Teacher",
                        Tran_Emp="Example School District", Tres_NamL="Ledger", Tres_Adr1=TREASURER_STREET,
                        Tres_Zip="94903", Intr_Adr1=INTERMEDIARY_STREET, **extra)


def base_rows() -> dict[str, list[dict]]:
    """The world's rows by sheet. Tests copy and mutate them before building."""
    contributions = [
        # B: the bucket node itself controls a committee. Two address clusters (12 Sample / 400 Example).
        _c(COUNCIL, "A-1", 500, "Quill", "Avery", "12 Sample Street", date="2024-01-05"),
        _c(COUNCIL, "A-2", 250, "Quill", "Avery", "12 SAMPLE ST.", date="2024-01-10"),
        _c(MEASURE, "M-1", 100, "Quill", "Avery", "400 Example Avenue", zip_="94903", date="2024-01-12"),
        # A: the bucket matches a Form 700 filer on another node ("Robin Q. Larkspur").
        _c(COUNCIL, "A-3", 1000, "Larkspur", "Robin", "77 Fictional Way", date="2024-01-07"),
        _c(MEASURE, "M-2", 300, "Larkspur", "Robin", "77 Fictional Way", date="2024-01-20"),
        # A: the bucket matches a council member who votes (CAST_VOTE) on another node.
        _c(MEASURE, "M-3", 150, "Osprey", "Sam", "31 Invented Road", date="2024-01-08"),
        # C: two clusters, no government match.
        _c(COUNCIL, "A-4", 2000, "Thornbury", "Casey", "5 Placeholder Lane", date="2024-01-03"),
        _c(MEASURE, "M-4", 700, "Thornbury", "Casey", "9 Imaginary Court", zip_="94904", date="2024-01-15"),
        # No usable address: a placeholder street, then an invalid ZIP.
        _c(COUNCIL, "A-5", 120, "Fable", "Jordan", "N/A", date="2024-01-09"),
        _c(MEASURE, "M-5", 130, "Fable", "Jordan", "88 Madeup Drive", zip_="9490", date="2024-01-16"),
        # A street with a unit on the second line, and a payee who also gives.
        _c(COUNCIL, "A-6", 400, "Printwright", "Taylor", "12 Sample Street", adr2="Apt. 3", date="2024-01-11"),
        _c(MEASURE, "M-6", 90, "Printwright", "Taylor", "250 Notreal Blvd", date="2024-01-18"),
    ]
    # One flow, two physical rows: the same Tran_ID reported unchanged by two of the council's filings.
    vale = dict(last="Vale", first="Morgan", street="31 Invented Road", date="2024-01-25")
    contributions += [_c(COUNCIL, "A-7", 600, vale["last"], vale["first"], vale["street"], date=vale["date"]),
                      _c(COUNCIL_2, "A-7", 600, vale["last"], vale["first"], vale["street"], date=vale["date"])]
    expenditures = [expenditure(MEASURE, "E-1", 75, payee="Printwright", Payee_NamF="Taylor", entity="IND")]
    return {"A-Contributions": contributions, "E-Expenditure": expenditures}


def with_summaries(rows: dict[str, list[dict]]) -> dict[str, list[dict]]:
    """Add each filing's Summary line 1 (A and E) equal to its itemized total, so every group validates."""
    out = copy.deepcopy(rows)
    totals: dict[tuple, Decimal] = {}
    filings: dict[tuple, dict] = {}
    for sheet, form in (("A-Contributions", "A"), ("E-Expenditure", "E")):
        for row in out.get(sheet, []):
            f = {k: row[k] for k in ("Filer_ID", "Filer_NamL", "Report_Num", "Committee_Type", "Rpt_Date",
                                     "From_Date", "Thru_Date")}
            key = (form, *f.values())
            filings[key] = f
            amount = row["Tran_Amt1"] if form == "A" else row["Amount"]
            totals[key] = totals.get(key, Decimal(0)) + Decimal(str(amount))
    out["Summary"] = [summary(filings[k], k[0], "1", float(v)) for k, v in sorted(totals.items())]
    return out


@dataclass
class World:
    root: Path
    raw_root: Path
    ledger_dir: Path
    export_dir: Path
    decisions: Path
    private: Path

    @property
    def inputs(self) -> list[Path]:
        """The fixture's raw input workbooks: the only files allowed to hold a street."""
        return sorted(p for root in (self.raw_root, self.root / "ledger-input") if root.exists()
                      for p in root.rglob("*.zip"))

    def build_args(self, as_of="2026-10-12", out="test") -> list[str]:
        return ["build", "--ledger", str(self.ledger_dir), "--raw-root", str(self.raw_root), "--export",
                str(self.export_dir), "--decisions", str(self.decisions), "--as-of", as_of, "--out", out]


GOVERNMENT_NODES = [
    {"id": "filing-form700-example-2024-larkspur", "labels": ["Filing"],
     "properties": {"filing_type": "form_700", "filed_at": "2024-03-01", "filer_name": "Larkspur, Robin Q"}},
    {"id": "person-robin-q-larkspur", "labels": ["Person"], "properties": {"name": "Robin Q. Larkspur"}},
    {"id": "person-sam-osprey", "labels": ["Person"], "properties": {"name": "Sam Osprey", "aliases": ["Samuel Osprey"]}},
    {"id": "decision-2024-01-22-example-council-4", "labels": ["Decision"], "properties": {"title": "Consent"}},
]
GOVERNMENT_EDGES = [
    {"start_id": "committee-netfile-1400001", "end_id": "person-quill-avery", "type": "CONTROLLED_BY",
     "properties": {"resolved_by": "resolve_committee_candidates", "candidate_name": "Avery Quill"}},
    {"start_id": "filing-form700-example-2024-larkspur", "end_id": "person-robin-q-larkspur", "type": "FILED_BY",
     "properties": {}},
    {"start_id": "person-sam-osprey", "end_id": "decision-2024-01-22-example-council-4", "type": "CAST_VOTE",
     "properties": {"vote": "aye"}},
]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_world(tmp: Path, rows: dict | None = None, ledger_rows: dict | None = None, private: Path | None = None
                ) -> World:
    """Write raw workbooks from `rows`, and the ledger bundle + export from `ledger_rows` (default: the same).

    Separate `ledger_rows` let a test change the raw workbook (a re-download) without rebuilding the ledger, or
    rebuild both together, as the real pipeline would.
    """
    tmp = Path(tmp).resolve()
    rows = base_rows() if rows is None else rows
    raw_root, ledger_dir, export_dir = tmp / "raw", tmp / "ledger", tmp / "export"
    rel = f"{SOURCE}/{CAPTURE}/{YEAR}.zip"
    workbook = write_export(raw_root / rel, with_summaries(rows), headers=LAYOUT)
    source_rows = with_summaries(ledger_rows) if ledger_rows is not None else None
    ledger_workbook = workbook
    if source_rows is not None:
        ledger_workbook = write_export(tmp / "ledger-input" / rel, source_rows, headers=LAYOUT)
    ledger = build_ledger(SOURCE, [(rel, ledger_workbook)])
    assert not ledger.errors, ledger.errors
    build_transactions(ledger)
    out = ledger_dir / SOURCE
    write_ledger(ledger, out)
    (out / "manifest.json").write_text(json.dumps({
        "capture_id": f"{SOURCE}__{CAPTURE}",
        "inputs": [{"path": rel, "source_id": SOURCE, "year": YEAR, "bytes": ledger_workbook.stat().st_size,
                    "sha256": _sha(ledger_workbook), "coverage": "workbook"}]}, indent=2, sort_keys=True) + "\n")
    capture = {"source_id": SOURCE, "capture_id": f"{SOURCE}__{CAPTURE}", "jurisdiction_id": "place-exampleton",
               "institution_id": "inst-exampleton"}
    nodes, edges, _ = normalize_campaign_source(capture, ledger, out)
    export_dir.mkdir(parents=True, exist_ok=True)
    with open(export_dir / "nodes.jsonl", "w") as f:
        for node in sorted([{"id": n["id"], "labels": n["labels"], "properties": {**n["properties"], "id": n["id"]}}
                            for n in nodes] + GOVERNMENT_NODES, key=lambda n: n["id"]):
            f.write(json.dumps(node, sort_keys=True) + "\n")
    with open(export_dir / "edges.jsonl", "w") as f:
        for edge in [{"start_id": e["source_id"], "end_id": e["target_id"], "type": e["relationship_type"],
                      "properties": e["properties"]} for e in edges] + GOVERNMENT_EDGES:
            f.write(json.dumps(edge, sort_keys=True) + "\n")
    decisions = tmp / "data-repo" / "identity" / "person" / "decisions.jsonl"
    decisions.parent.mkdir(parents=True, exist_ok=True)
    decisions.touch()
    return World(tmp, raw_root, ledger_dir, export_dir, decisions, private or tmp / "private" / "identity")


def every_text(paths: list[Path], skip: list[Path] = (), exclude: list[Path] = ()) -> str:
    """Every byte under the given roots, decoded leniently (ZIP members too), plus every file name; `skip` names the
    exact input files allowed to hold streets, `exclude` whole directories left out (e.g. the private dir)."""
    import zipfile

    chunks = []
    skipped = {Path(p).resolve() for p in skip}
    excluded = [Path(p).resolve() for p in exclude]
    for root in paths:
        for path in sorted(Path(root).rglob("*")):
            real = path.resolve()
            if any(real == e or e in real.parents for e in excluded):
                continue
            chunks.append(str(path))
            if not path.is_file() or path.is_symlink() or real in skipped:
                continue
            data = path.read_bytes()
            chunks.append(data.decode("utf-8", errors="replace"))
            if zipfile.is_zipfile(path):
                with zipfile.ZipFile(path) as zf:
                    chunks += [zf.read(n).decode("utf-8", errors="replace") for n in zf.namelist()]
    return "\n".join(chunks)


def assert_no_street(text: str) -> None:
    upper = text.upper()
    for street in (*STREETS, TREASURER_STREET, INTERMEDIARY_STREET):
        assert street.upper() not in upper, f"a fictional street leaked: {street!r}"
    for street in CANONICAL_STREETS:
        assert street not in upper, f"a canonical street leaked: {street!r}"
