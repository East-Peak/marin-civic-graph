"""Synthetic NetFile 'Export Amended' workbooks for tests: real sheet and column names, fictional rows.

No row carries a street address: address columns exist in the headers (as in the real export) but stay empty.
"""
from __future__ import annotations

import zipfile
from datetime import datetime
from pathlib import Path

import openpyxl

FILING_COLS = ["Filer_ID", "Filer_NamL", "Report_Num", "Committee_Type", "Rpt_Date", "From_Date", "Thru_Date",
               "Elect_Date", "tblCover_Office_Cd", "tblCover_Offic_Dscr", "Rec_Type", "Form_Type"]
_MEMO = ["Memo_Code", "Memo_RefNo", "BakRef_TID", "XRef_SchNm", "XRef_Match"]
_TRAN = ["Tran_ID", "Entity_Cd", "Tran_NamL", "Tran_NamF", "Tran_NamT", "Tran_NamS", "Tran_Adr1", "Tran_Adr2",
         "Tran_City", "Tran_State", "Tran_Zip4", "Tran_Emp", "Tran_Occ", "Tran_Self", "Tran_Type", "Tran_Date",
         "Tran_Date1", "Tran_Amt1", "Tran_Amt2", "Tran_Dscr", "Cmte_ID", "Intr_NamL", "Intr_NamF", *_MEMO]
_EXPN = ["Tran_ID", "Entity_Cd", "Payee_NamL", "Payee_NamF", "Payee_NamT", "Payee_NamS", "Payee_Adr1",
         "Payee_Adr2", "Payee_City", "Payee_State", "Payee_Zip4", "Expn_Date", "Amount", "Cum_YTD", "Expn_ChkNo",
         "Expn_Code", "Expn_Dscr", "Cmte_ID", *_MEMO]
_LOAN = ["Tran_ID", "Entity_Cd", "Lndr_NamL", "Lndr_NamF", "Loan_Date1", "Loan_Amt1", "Loan_Amt2", *_MEMO]
_NOTICE_497 = ["Filer_ID", "Filer_NamL", "Report_Num", "Committee_Type", "Rpt_Date", "From_Date", "Thru_Date",
               "Elect_Date", "Rec_Type", "Form_Type", "Tran_ID", "Entity_Cd", "Enty_NamL", "Enty_NamF",
               "Ctrib_Date", "Amount", "Memo_Code", "Memo_RefNo"]
_NOTICE_496 = ["Filer_ID", "Filer_NamL", "Report_Num", "Committee_Type", "Rpt_Date", "From_Date", "Thru_Date",
               "Elect_Date", "Rec_Type", "Form_Type", "Tran_ID", "Amount", "Exp_Date", "Expn_Dscr", "Memo_Code",
               "Memo_RefNo"]

HEADERS = {
    "A-Contributions": FILING_COLS + _TRAN,
    "C-Contributions": FILING_COLS + _TRAN,
    "I-Contributions": FILING_COLS + _TRAN,
    "F496P3-Contributions": FILING_COLS + _TRAN,
    "F465P3-Expenditure": FILING_COLS + _EXPN,
    "F461P5-Expenditure": FILING_COLS + _EXPN,
    "D-Expenditure": FILING_COLS + _EXPN,
    "G-Expenditure": FILING_COLS + _EXPN,
    "E-Expenditure": FILING_COLS + _EXPN,
    "F-Expenses": FILING_COLS + ["Tran_ID", "Entity_Cd", "Payee_NamL", "Beg_Bal", "Amt_Incur", "Amt_Paid",
                                 "End_Bal", "Expn_Code", *_MEMO],
    "B1-Loans": FILING_COLS + _LOAN,
    "B2-Loans": FILING_COLS + _LOAN,
    "H-Loans": FILING_COLS + _LOAN,
    "Summary": FILING_COLS + ["Line_Item", "Amount_A", "Amount_B", "Amount_C"],
    "497": _NOTICE_497,
    "496": _NOTICE_496,
}


def _date(value):
    return datetime.strptime(value, "%Y-%m-%d") if isinstance(value, str) and len(value) == 10 else value


def filing(filer_id="1400001", name="Friends of Example for Council 2024", report_num="000",
           rpt="2024-02-01", start="2024-01-01", thru="2024-01-20", committee_type="CTL") -> dict:
    return {"Filer_ID": filer_id, "Filer_NamL": name, "Report_Num": report_num, "Committee_Type": committee_type,
            "Rpt_Date": rpt, "From_Date": start, "Thru_Date": thru}


def contribution(f: dict, tran_id: str, amount, last="Doe", first="Pat", date="2024-01-05", entity="IND",
                 **extra) -> dict:
    return {**f, "Rec_Type": "RCPT", "Form_Type": "A", "Tran_ID": tran_id, "Entity_Cd": entity,
            "Tran_NamL": last, "Tran_NamF": first, "Tran_Date": date, "Tran_Amt1": amount, "Tran_Amt2": amount,
            **extra}


def expenditure(f: dict, tran_id: str, amount, payee="Example Print Co", date="2024-01-06", entity="OTH",
                **extra) -> dict:
    return {**f, "Rec_Type": "EXPN", "Form_Type": "E", "Tran_ID": tran_id, "Entity_Cd": entity,
            "Payee_NamL": payee, "Expn_Date": date, "Amount": amount, **extra}


def summary(f: dict, form_type: str, line: str, amount) -> dict:
    return {**f, "Rec_Type": "SMRY", "Form_Type": form_type, "Line_Item": line, "Amount_A": amount,
            "Amount_B": 0, "Amount_C": 0}


def other(f: dict, sheet: str, tran_id: str, amount, **extra) -> dict:
    """A row on an out-of-scope sheet, with the amount in that sheet's amount column."""
    col = {"B1-Loans": "Loan_Amt1", "B2-Loans": "Loan_Amt1", "H-Loans": "Loan_Amt1", "F-Expenses": "Amt_Paid",
           "C-Contributions": "Tran_Amt1", "I-Contributions": "Tran_Amt1",
           "F496P3-Contributions": "Tran_Amt1"}.get(sheet, "Amount")
    form = sheet.split("-")[0]
    return {**f, "Rec_Type": "RCPT", "Form_Type": form, "Tran_ID": tran_id, col: amount, **extra}


def write_export(path: Path, rows: dict[str, list[dict]], sheets=None, headers=None) -> Path:
    """Write a NetFile-shaped ZIP holding one workbook (default: all 16 sheets; rows as dicts keyed by header)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    layout = headers or HEADERS
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name in (sheets or layout):
        headers = layout[name]
        ws = wb.create_sheet(name)
        ws.append(headers)
        for row in rows.get(name, []):
            unknown = set(row) - set(headers)
            assert not unknown, f"{name}: unknown columns {unknown}"
            ws.append([_date(row.get(h)) for h in headers])
    xlsx = path.with_suffix(".xlsx")
    wb.save(xlsx)
    with zipfile.ZipFile(path, "w") as zf:
        zf.write(xlsx, f"efile_newest_TEST_{path.stem}.xlsx")
    xlsx.unlink()
    return path
