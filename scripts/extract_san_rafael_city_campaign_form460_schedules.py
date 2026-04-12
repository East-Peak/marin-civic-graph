#!/usr/bin/env python3

from __future__ import annotations

import html
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
RAW_CAPTURE_PATH = (
    ROOT / "data" / "raw" / "san-rafael-city-campaign-form460-ocr" / "2026-04-12" / "results.json"
)
CANONICAL_SEEDS_PATH = ROOT / "data" / "normalized" / "canonical-seeds-san-rafael-01.json"
CAMPAIGN_SAMPLE_BUNDLE_PATH = (
    ROOT / "data" / "normalized" / "campaign-finance-sample-basket-01" / "bundle-01.json"
)
EXTRACTED_DIR = ROOT / "data" / "extracted" / "san-rafael-city-campaign-form460-schedules"
EXTRACTED_PATH = EXTRACTED_DIR / "2026-04-12.json"
NORMALIZED_DIR = ROOT / "data" / "normalized" / "san-rafael-city-campaign-form460-schedules-01"
NORMALIZED_PATH = NORMALIZED_DIR / "bundle-01.json"
PDF_EXPORT_EXTRACTED_PATH = (
    ROOT / "data" / "extracted" / "san-rafael-city-campaign-form460-pdf-export" / "2026-04-12.json"
)

CASE_STUDY_ID = "san-rafael-city-campaign-form460-schedules-01"
BUNDLE_ID = f"{CASE_STUDY_ID}__bundle-01"
EXTRACTED_ARTIFACT_PATH = "data/extracted/san-rafael-city-campaign-form460-schedules/2026-04-12.json"

DATE_LINE_RE = re.compile(r"^\s*\d{1,2}(?:[^0-9]+)\d{1,2}(?:[^0-9]+)\d{2,4}\s*$")
LEADING_DATE_FRAGMENT_RE = re.compile(
    r"^\s*(?P<prefix>\d[\dA-Za-z()/\s]{3,14}\d)(?P<rest>\s+.*)?$"
)
AMOUNT_RE = re.compile(r"-?\d{1,3}(?:,\d{3})*(?:\.\d{1,2})")
SPACED_AMOUNT_RE = re.compile(r"-?\d{1,3}(?:[ ,]\d{3})*(?:\.\s?\d{1,2})?")
STATE_ZIP_RE = re.compile(r"\b[A-Z]{2}\s+\d{5}(?:-\d{4})?$")
PER_ELECTION_RE = re.compile(r"(?:[GSP]\s*)?20\d{2}\s*\$?\s*-?\d", re.IGNORECASE)
SELECTED_CODE_PATTERNS = [
    re.compile(r"(?:®|0|O|Q|Z|@|●|•|◉|El|E1|Ll|LI|L1)\s*(IND|COM|OTH|PTY|SCC)\b", re.IGNORECASE),
    re.compile(r"(?:®|0|O|Q|Z|@|●|•|◉|El|E1|Ll|LI|L1)(IND|COM|OTH|PTY|SCC)\b", re.IGNORECASE),
]
COMBINED_E_LINE_RE = re.compile(
    r"^(?P<payee>.+?)\s+(?P<code>CMP|CNS|CTB|CVC|FIL|FND|IND|LEG|LIT|MBR|MTG|OFC|PET|PHO|POL|POS|PRT|PRO|RAD|RFD|SAL|TEL|TRC|TRS|TSF|VOT|WEB)\s+(?P<description>.+?)\s+(?P<amount>-?\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?)$",
    re.IGNORECASE,
)
PAYMENT_CODE_RE = re.compile(
    r"\b(CMP|CNS|CTB|CVC|FIL|FND|IND|LEG|LIT|MBR|MTG|OFC|PET|PHO|POL|POS|PRT|PRO|RAD|RFD|SAL|TEL|TRC|TRS|TSF|VOT|WEB)\b",
    re.IGNORECASE,
)
PAYMENT_CODE_GROUP = "CMP|CNS|CTB|CVC|FIL|FND|IND|LEG|LIT|MBR|MTG|OFC|PET|PHO|POL|POS|PRT|PRO|RAD|RFD|SAL|TEL|TRC|TRS|TSF|VOT|WEB"
SUMMARY_AMOUNT_RE = re.compile(r"\$?\s*(-?\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?)")
CONTRIBUTOR_CODE_TOKEN_RE = re.compile(r"\b(IND|COM|OTH|PTY|SCC)\b", re.IGNORECASE)
SCHEDULE_E_DESCRIPTION_HINTS = [
    "Printing of literature",
    "Campaign consultant",
    "Political data",
    "Software",
    "Campaign kickoff reception.",
    "Venue for",
    "Venue rental for",
    "Voter Data",
]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n")


def slugify(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")


def clean_line(value: str) -> str:
    value = html.unescape(value)
    value = value.replace("\r", "")
    value = value.replace("\u00a0", " ")
    value = re.sub(r"[ \t]+", " ", value)
    return value.strip()


def normalize_numeric_spacing(value: str) -> str:
    old_value = None
    while old_value != value:
        old_value = value
        value = re.sub(r"(?<=\d)[ \t]+(?=[\d,\.])", "", value)
        value = re.sub(r"(?<=[,\.])[ \t]+(?=\d)", "", value)
    return value


def normalize_name_key(value: str) -> str:
    value = value.lower()
    value = value.replace("&", "and")
    value = re.sub(r"[^a-z0-9]+", "", value)
    return value


def parse_float(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return float(value.replace(",", ""))
    except ValueError:
        return None


def extract_last_amount_from_line(value: str) -> float | None:
    normalized = normalize_numeric_spacing(value)
    matches = list(SPACED_AMOUNT_RE.finditer(normalized))
    if not matches:
        return None
    token = matches[-1].group(0).replace(" ", "").replace(",", "")
    return parse_float(token)


def extract_strict_amounts_from_line(value: str) -> list[float]:
    return [
        parse_float(match.group(0))
        for match in AMOUNT_RE.finditer(value)
        if parse_float(match.group(0)) is not None
    ]


def parse_date_line(value: str) -> str | None:
    value = value.translate(
        str.maketrans(
            {
                "O": "0",
                "o": "0",
                "I": "1",
                "l": "1",
                "S": "5",
                "s": "5",
            }
        )
    )
    cleaned = re.sub(r"[^0-9]+", "/", value).strip("/")
    parts = cleaned.split("/")
    if len(parts) != 3:
        return None
    month, day, year = parts
    if len(year) == 2:
        year = f"20{year}"
    try:
        return datetime(int(year), int(month), int(day)).date().isoformat()
    except ValueError:
        return None


def normalize_year_token(value: str) -> int | None:
    digits = re.sub(r"[^0-9]", "", value)
    if not digits:
        return None
    if len(digits) >= 4:
        digits = digits[-4:]
    else:
        digits = digits[-2:]
        digits = f"20{digits}"
    year = int(digits)
    if year < 100:
        year += 2000
    if 2000 <= year <= 2100:
        return year
    return None


def parse_date_line_loose(value: str) -> str | None:
    parsed = parse_date_line(value)
    if parsed is not None:
        return parsed

    groups = re.findall(r"\d+", value)
    if not groups:
        return None

    month: int | None = None
    day: int | None = None
    year: int | None = None

    if len(groups) >= 3:
        year = normalize_year_token(groups[2])
        day_digits = groups[1][-2:]
        if day_digits.isdigit():
            day = int(day_digits)
        month_candidates = [groups[0], groups[0][-1:], groups[0][:1]]
        for candidate in month_candidates:
            if candidate.isdigit():
                candidate_int = int(candidate)
                if 1 <= candidate_int <= 12:
                    month = candidate_int
                    break
    elif len(groups) == 2:
        year = normalize_year_token(groups[1])
        prefix = groups[0]
        if len(prefix) >= 3:
            day_digits = prefix[-2:]
            if day_digits.isdigit():
                day = int(day_digits)
            month_candidates = []
            if len(prefix) >= 4:
                month_candidates.append(prefix[:2])
            month_candidates.extend([prefix[:1], prefix[1:2], prefix[-3:-2]])
            for candidate in month_candidates:
                if candidate and candidate.isdigit():
                    candidate_int = int(candidate)
                    if 1 <= candidate_int <= 12:
                        month = candidate_int
                        break

    if month is None or day is None or year is None:
        return None

    try:
        return datetime(year, month, day).date().isoformat()
    except ValueError:
        return None


def extract_leading_date_parts(line: str) -> tuple[str | None, str | None, str | None]:
    match = LEADING_DATE_FRAGMENT_RE.match(line)
    if not match:
        return None, None, None
    prefix = match.group("prefix").strip()
    rest = (match.group("rest") or "").strip()
    parsed = parse_date_line_loose(prefix)
    if parsed is None:
        return None, None, None
    return parsed, prefix, rest or None


def line_is_amountish(value: str) -> bool:
    normalized = normalize_numeric_spacing(value.strip().replace("$", ""))
    return bool(re.fullmatch(r"-?\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?", normalized))


def line_is_address(value: str) -> bool:
    return bool(STATE_ZIP_RE.search(value))


def line_is_checkbox(value: str) -> bool:
    return any(marker in value for marker in ("❑", "☐", "□"))


def line_is_per_election(value: str) -> bool:
    return bool(PER_ELECTION_RE.search(value))


def extract_amounts_from_line(value: str) -> list[float]:
    normalized = normalize_numeric_spacing(value)
    amounts = []
    for match in SPACED_AMOUNT_RE.finditer(normalized):
        token = match.group(0).replace(" ", "").replace(",", "")
        parsed = parse_float(token)
        if parsed is not None:
            amounts.append(parsed)
    return amounts


def extract_selected_code(lines: list[str]) -> str | None:
    for line in lines:
        if line_is_checkbox(line):
            continue
        compact = line.replace(" ", "")
        for pattern in SELECTED_CODE_PATTERNS:
            match = pattern.search(compact)
            if match:
                return match.group(1).upper()
        if re.fullmatch(r"(IND|COM|OTH|PTY|SCC)", line.strip(), re.IGNORECASE):
            return line.strip().upper()
    return None


def extract_first_code_token(line: str) -> str | None:
    match = CONTRIBUTOR_CODE_TOKEN_RE.search(line)
    if match:
        return match.group(1).upper()
    return None


def clean_contributor_name(value: str) -> str:
    value = re.sub(r"\(ID#\s*\d+\)?", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\bID#\s*\d+\b", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\s+#\d+\b", "", value)
    value = re.sub(r"\s{2,}", " ", value)
    return value.strip(" ,;")


def infer_actor_type(name: str, code: str | None, default: str = "organization") -> str:
    if code == "IND":
        return "person"
    if code in {"COM", "PTY", "SCC"}:
        return "political_organization"
    if code == "OTH":
        return "business"
    lowered = name.lower()
    if "committee" in lowered or "pac" in lowered or "party" in lowered:
        return "political_organization"
    if any(token in lowered for token in ("inc", "llc", "company", "group")):
        return "business"
    return default


def resolve_actor(
    raw_name: str,
    actor_type: str,
    known_actor_map: dict[str, dict[str, Any]],
    actor_candidates_by_id: dict[str, dict[str, Any]],
    evidence_record_ids: list[str],
) -> str:
    cleaned_name = clean_contributor_name(raw_name)
    key = normalize_name_key(cleaned_name)
    known = known_actor_map.get(key)
    if known is not None:
        return known["id"]

    actor_id = f"actor-{slugify(cleaned_name)}"
    candidate = actor_candidates_by_id.setdefault(
        actor_id,
        {
            "id": actor_id,
            "name": cleaned_name,
            "actor_type": actor_type,
            "observed_labels": [],
            "evidence_record_ids": [],
        },
    )
    if raw_name not in candidate["observed_labels"]:
        candidate["observed_labels"].append(raw_name)
    for record_id in evidence_record_ids:
        if record_id not in candidate["evidence_record_ids"]:
            candidate["evidence_record_ids"].append(record_id)
    return actor_id


def split_date_blocks(lines: list[str]) -> list[list[str]]:
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if "SUBTOTAL" in line.upper():
            if current:
                blocks.append(current)
            break
        date_received, _, _ = extract_leading_date_parts(line)
        if date_received is not None:
            if current:
                blocks.append(current)
            current = [line]
            continue
        if current:
            current.append(line)
    if current:
        blocks.append(current)
    return blocks


def split_line_on_contributor_code(line: str, selected_code: str) -> tuple[str, str]:
    match = re.search(selected_code, line, re.IGNORECASE)
    if match is None:
        return line, ""
    prefix = line[: match.start()].strip(" -")
    suffix = line[match.end() :].strip(" -")
    return prefix, suffix


def clean_code_prefix(value: str) -> str:
    value = re.sub(r"(?:\s+[®©❑●•◉0ZWIElm/]+)+$", "", value).strip()
    value = re.sub(r"\s{2,}", " ", value)
    return value


def extract_section_lines(page_text: str) -> list[str]:
    return [clean_line(line) for line in page_text.splitlines() if clean_line(line)]


def page_header_text(lines: list[str], limit: int = 14) -> str:
    return " ".join(lines[:limit]).upper()


def is_schedule_a_page(lines: list[str]) -> bool:
    header = page_header_text(lines)
    return ("SCHEDULE A" in header or "SCHEDULEA" in header) and any(
        "CONTRIBUTOR" in line.upper() for line in lines[:35]
    )


def is_schedule_d_page(lines: list[str]) -> bool:
    header = page_header_text(lines)
    return "SCHEDULE D" in header or "SCHEDULED" in header


def is_schedule_e_page(lines: list[str]) -> bool:
    header = page_header_text(lines)
    return ("SCHEDULE E" in header or "SCHEDULEE" in header) and any(
        "NAME AND ADDRESS OF PAYEE" in line.upper() for line in lines
    )


def page_subtotal(page_text: str) -> float | None:
    lines = extract_section_lines(page_text)
    for line in lines:
        if "SUBTOTAL" not in line.upper():
            continue
        amount = extract_last_amount_from_line(line)
        if amount is not None:
            return amount
    return None


def parse_schedule_a_block(block_lines: list[str], page_num: int) -> dict[str, Any] | None:
    if not block_lines:
        return None
    date_received, date_received_raw, first_line_rest = extract_leading_date_parts(block_lines[0])
    if date_received is None:
        return None
    content_lines = ([first_line_rest] if first_line_rest else []) + block_lines[1:]
    code_index = None
    selected_code = None
    for index, line in enumerate(content_lines):
        code = extract_selected_code([line]) or extract_first_code_token(line)
        if code:
            code_index = index
            selected_code = code
            break
    if code_index is None:
        return None

    code_line = content_lines[code_index]
    code_line_prefix, code_line_suffix = split_line_on_contributor_code(code_line, selected_code)
    code_line_prefix = clean_code_prefix(code_line_prefix)
    name_lines = [line for line in content_lines[:code_index] if not line_is_address(line)]
    if code_line_prefix and not line_is_address(code_line_prefix):
        name_lines.append(code_line_prefix)
    contributor_name = clean_contributor_name(" ".join(name_lines))
    if not contributor_name:
        return None

    descriptor_lines: list[str] = []
    address_lines: list[str] = []
    numeric_values: list[float] = []
    tail_lines = ([code_line_suffix] if code_line_suffix else []) + content_lines[code_index + 1 :]
    for line in tail_lines:
        if line_is_checkbox(line) or line_is_per_election(line):
            amounts = extract_strict_amounts_from_line(line)
            if amounts:
                numeric_values.extend(amounts)
            continue
        if line_is_address(line):
            address_lines.append(line)
            continue
        if line_is_amountish(line):
            amount = parse_float(line)
            if amount is not None:
                numeric_values.append(amount)
            continue
        if any(token in line.lower() for token in ("fppc form", "contributor codes", "www.", "http")):
            continue
        amounts = extract_strict_amounts_from_line(line)
        if amounts and PAYMENT_CODE_RE.search(line) is None:
            numeric_values.extend(amounts)
            continue
        if line and len(line) > 1:
            descriptor_lines.append(line)

    meaningful_values = [value for value in numeric_values if value >= 10]
    if meaningful_values:
        numeric_values = meaningful_values

    amount_received = numeric_values[0] if len(numeric_values) >= 1 else None
    cumulative_to_date = numeric_values[1] if len(numeric_values) >= 2 else None
    per_election_to_date = numeric_values[2] if len(numeric_values) >= 3 else None
    if amount_received is None:
        return None

    parse_confidence = "high" if selected_code and contributor_name and cumulative_to_date is not None else "medium"
    return {
        "page_num": page_num,
        "row_type": "schedule_a_itemized_contribution",
        "date_received": date_received,
        "date_received_raw": date_received_raw,
        "contributor_name": contributor_name,
        "contributor_name_raw": " ".join(name_lines),
        "contributor_code": selected_code,
        "occupation_employer_raw": " ".join(descriptor_lines).strip() or None,
        "address_raw": ", ".join(address_lines).strip() or None,
        "amount_received_this_period": amount_received,
        "cumulative_to_date": cumulative_to_date,
        "per_election_to_date": per_election_to_date,
        "parse_confidence": parse_confidence,
        "raw_block_text": "\n".join(block_lines),
    }


def parse_schedule_a_summary_page(page_text: str) -> dict[str, float | None]:
    lines = extract_section_lines(page_text)
    summary_index = next((index for index, line in enumerate(lines) if "SCHEDULE A SUMMARY" in line.upper()), None)
    if summary_index is None:
        return {}
    summary_amounts: list[float] = []
    for line in lines[summary_index + 1 : summary_index + 18]:
        upper = line.upper()
        if "CONTRIBUTOR CODES" in upper or upper.startswith("FPPC "):
            break
        amount = extract_last_amount_from_line(line)
        if amount is not None and amount >= 100:
            summary_amounts.append(amount)
    if len(summary_amounts) < 3:
        return {}
    return {
        "reported_itemized_contributions": summary_amounts[-3],
        "reported_unitemized_contributions": summary_amounts[-2],
        "reported_total_contributions": summary_amounts[-1],
    }


def parse_schedule_d_block(block_lines: list[str], page_num: int) -> dict[str, Any] | None:
    if not block_lines:
        return None
    if any(
        token in "\n".join(block_lines).upper()
        for token in ("NAME OF CANDIDATE", "CANDIDATES, MEASURES AND COMMITTEES")
    ):
        return None
    flow_date = parse_date_line(block_lines[0])
    if flow_date is None:
        return None

    selected_payment_type = None
    payment_type_index = None
    stance = None
    target_lines: list[str] = []
    amounts: list[float] = []

    for index, line in enumerate(block_lines[1:], start=1):
        compact = line.replace(" ", "")
        if "Support" in line and "Oppose" in line:
            if "®Support" in compact or "ZSupport" in compact:
                stance = "support"
            elif "®Oppose" in compact or "ZOppose" in compact:
                stance = "oppose"
            continue
        if re.search(r"(?:®|Z|0|O|Q)\s*Monetary", line, re.IGNORECASE):
            selected_payment_type = "monetary_contribution"
            payment_type_index = index
            continue
        if re.search(r"(?:®|Z|0|O|Q)\s*Nonmonetary", line, re.IGNORECASE):
            selected_payment_type = "nonmonetary_contribution"
            payment_type_index = index
            continue
        if re.search(r"(?:®|Z|0|O|Q)\s*Independent", line, re.IGNORECASE):
            selected_payment_type = "independent_expenditure"
            payment_type_index = index
            continue
        if line_is_amountish(line):
            amount = parse_float(line)
            if amount is not None:
                amounts.append(amount)
            continue
        for amount in extract_strict_amounts_from_line(line):
            amounts.append(amount)
        if STATE_ZIP_RE.search(line):
            continue
        if selected_payment_type is not None:
            continue
        if len(target_lines) < 2:
            target_lines.append(line)

    amount_period = amounts[0] if len(amounts) >= 1 else None
    cumulative_to_date = amounts[1] if len(amounts) >= 2 else None
    per_election_to_date = amounts[2] if len(amounts) >= 3 else None
    if amount_period is None:
        return None

    target_name = " ".join(target_lines).strip()
    if not target_name:
        return None

    description_raw = None
    if payment_type_index is not None:
        for line in block_lines[payment_type_index + 1 :]:
            if line_is_amountish(line) or line_is_checkbox(line):
                continue
            if line in {"Contribution", "Expenditure"}:
                continue
            if "Support" in line and "Oppose" in line:
                continue
            description_raw = line
            break

    return {
        "page_num": page_num,
        "row_type": "schedule_d_payment",
        "date_received": flow_date,
        "target_name": target_name,
        "target_name_raw": " ".join(target_lines),
        "payment_type": selected_payment_type or "unknown",
        "stance": stance,
        "description_raw": description_raw,
        "amount_this_period": amount_period,
        "cumulative_to_date": cumulative_to_date,
        "per_election_to_date": per_election_to_date,
        "parse_confidence": "high" if selected_payment_type and stance else "medium",
        "raw_block_text": "\n".join(block_lines),
    }


def split_schedule_e_sections(lines: list[str]) -> tuple[list[str], list[str], list[float]]:
    payee_lines: list[str] = []
    code_lines: list[str] = []
    amount_values: list[float] = []
    section = "seek_payee"
    for line in lines:
        upper = line.upper()
        if "NAME AND ADDRESS OF PAYEE" in upper:
            section = "payee"
            continue
        if "CODE OR DESCRIPTION OF PAYMENT" in upper:
            section = "code"
            continue
        if "AMOUNT PAID" in upper:
            section = "amount"
            continue
        if "SCHEDULE E SUMMARY" in upper:
            break
        if section == "payee":
            if "IF COMMITTEE, ALSO ENTER I.D. NUMBER" in upper:
                continue
            payee_lines.append(line)
        elif section == "code":
            if "SUBTOTAL" in upper:
                continue
            code_lines.append(line)
        elif section == "amount":
            amount_values.extend(extract_amounts_from_line(line))
    return payee_lines, code_lines, amount_values


def parse_schedule_e_payees(payee_lines: list[str]) -> list[dict[str, str | None]]:
    payees: list[dict[str, str | None]] = []
    current_name: str | None = None
    current_address_parts: list[str] = []
    for line in payee_lines:
        if line_is_address(line):
            if current_name:
                current_address_parts.append(line)
            continue
        if current_name is not None:
            payees.append(
                {
                    "payee_name": clean_contributor_name(current_name),
                    "payee_name_raw": current_name,
                    "address_raw": ", ".join(current_address_parts).strip() or None,
                }
            )
        current_name = line
        current_address_parts = []
    if current_name is not None:
        payees.append(
            {
                "payee_name": clean_contributor_name(current_name),
                "payee_name_raw": current_name,
                "address_raw": ", ".join(current_address_parts).strip() or None,
            }
        )
    return payees


def parse_schedule_e_descriptions(code_lines: list[str]) -> list[dict[str, str | None]]:
    descriptions: list[dict[str, str | None]] = []
    current: dict[str, str | None] | None = None
    for line in code_lines:
        if line.startswith("* Payments"):
            break
        match = PAYMENT_CODE_RE.match(line)
        if match:
            if current is not None:
                descriptions.append(current)
            current = {
                "payment_code": match.group(1).upper(),
                "description_raw": line[match.end() :].strip(" -") or None,
            }
            continue
        if current is not None:
            addition = line.strip()
            if addition:
                existing = current.get("description_raw") or ""
                current["description_raw"] = f"{existing} {addition}".strip()
    if current is not None:
        descriptions.append(current)
    return descriptions


def extract_schedule_e_amounts(lines: list[str]) -> list[float]:
    amounts: list[float] = []
    capture = False
    for line in lines:
        upper = line.upper()
        if "AMOUNT PAID" in upper:
            capture = True
            continue
        if capture:
            if upper.startswith("FPPC FORM") or upper.startswith("FPPC ADVICE") or upper.startswith("<A HREF"):
                break
            amounts.extend(extract_amounts_from_line(line))
    return amounts


def parse_schedule_e_page(page_text: str, page_num: int) -> list[dict[str, Any]]:
    lines = extract_section_lines(page_text)
    payee_section, code_section, amount_section = split_schedule_e_sections(lines)
    rows: list[dict[str, Any]] = []

    payees = parse_schedule_e_payees(payee_section)
    descriptions = parse_schedule_e_descriptions(code_section)
    aligned_amounts = amount_section or extract_schedule_e_amounts(lines)

    section_payee_rows: list[dict[str, Any]] = []
    if payees and descriptions and aligned_amounts:
        count = min(len(payees), len(descriptions), len(aligned_amounts))
        if count > 0:
            for payee, description, amount in zip(
                payees[:count],
                descriptions[:count],
                aligned_amounts[:count],
            ):
                section_payee_rows.append(
                    {
                        "page_num": page_num,
                        "row_type": "schedule_e_payment",
                        "payee_name": payee["payee_name"],
                        "payee_name_raw": payee["payee_name_raw"],
                        "address_raw": payee["address_raw"],
                        "payment_code": description["payment_code"],
                        "description_raw": description["description_raw"],
                        "amount_paid": amount,
                        "parse_confidence": "high",
                        "raw_block_text": "\n".join(
                            [
                                payee["payee_name_raw"],
                                description["payment_code"],
                                description.get("description_raw") or "",
                                str(amount),
                            ]
                        ).strip(),
                    }
                )

    rows.extend(section_payee_rows)

    # Some OCR pages collapse payee, code, description, and amount into one line instead of preserving columns.
    for line in lines:
        match = COMBINED_E_LINE_RE.match(line)
        if not match:
            continue
        payee_name = clean_contributor_name(match.group("payee"))
        if any(existing["payee_name"] == payee_name and existing["amount_paid"] == parse_float(match.group("amount")) for existing in rows):
            continue
        rows.append(
            {
                "page_num": page_num,
                "row_type": "schedule_e_payment",
                "payee_name": payee_name,
                "payee_name_raw": match.group("payee"),
                "address_raw": None,
                "payment_code": match.group("code").upper(),
                "description_raw": match.group("description").strip(),
                "amount_paid": parse_float(match.group("amount")),
                "parse_confidence": "high",
                "raw_block_text": line,
            }
        )

    return rows


def load_pdf_export_map() -> dict[int, str]:
    if not PDF_EXPORT_EXTRACTED_PATH.exists():
        return {}
    payload = json.loads(PDF_EXPORT_EXTRACTED_PATH.read_text())
    return {item["entry_id"]: item["artifact_path"] for item in payload.get("items", [])}


def load_pdf_layout_pages(pdf_path: str) -> list[str]:
    output = subprocess.check_output(["pdftotext", "-layout", pdf_path, "-"])
    return [page for page in output.decode("utf-8", "ignore").split("\f") if page.strip()]


def extract_schedule_e_body_lines(page_text: str) -> list[str]:
    lines = extract_section_lines(page_text)
    start_index = None
    for index, line in enumerate(lines):
        if "IF COMMITTEE, ALSO ENTER I. D. NUMBER" in line:
            start_index = index + 1
            break
    if start_index is None:
        return []

    body_lines: list[str] = []
    for line in lines[start_index:]:
        upper = line.upper()
        if (
            upper.startswith("PAYMENTS THAT ARE CONTRIBUTIONS")
            or upper.startswith("SCHEDULE E SUMMARY")
            or upper.startswith("FPPC FORM 460")
            or upper.startswith("FPPC ADVICE")
            or upper.startswith("WWW.")
        ):
            break
        body_lines.append(line)
    return body_lines


def looks_like_schedule_e_row_start(line: str) -> bool:
    if extract_last_amount_from_line(line) is None:
        return False
    if PAYMENT_CODE_RE.search(line):
        return True
    return any(hint in line for hint in SCHEDULE_E_DESCRIPTION_HINTS)


def split_schedule_e_payee_and_description(value: str) -> tuple[str, str | None]:
    for hint in SCHEDULE_E_DESCRIPTION_HINTS:
        index = value.find(hint)
        if index > 0:
            return clean_contributor_name(value[:index].strip()), value[index:].strip()
    return clean_contributor_name(value), None


def parse_schedule_e_page_from_pdf_layout(page_text: str, page_num: int) -> list[dict[str, Any]]:
    lines = extract_schedule_e_body_lines(page_text)
    rows: list[dict[str, Any]] = []
    index = 0

    while index < len(lines):
        line = lines[index]

        code_only_match = re.match(
            rf"^(?P<code>{PAYMENT_CODE_GROUP})\b(?P<rest>.*)$",
            line,
            re.IGNORECASE,
        )
        if code_only_match:
            code = code_only_match.group("code").upper()
            amount_paid = extract_last_amount_from_line(line)
            payee_name_raw = None
            description_raw = None
            next_index = index + 1
            if next_index < len(lines):
                payee_name_raw = lines[next_index]
                next_index += 1
                if (
                    next_index < len(lines)
                    and not line_is_address(lines[next_index])
                    and not looks_like_schedule_e_row_start(lines[next_index])
                ):
                    description_raw = lines[next_index]
                    next_index += 1
            address_raw = lines[next_index] if next_index < len(lines) and line_is_address(lines[next_index]) else None
            if address_raw is not None:
                next_index += 1
            payee_name, inferred_description = split_schedule_e_payee_and_description(payee_name_raw or "")
            if inferred_description and not description_raw:
                description_raw = inferred_description
            rows.append(
                {
                    "page_num": page_num,
                    "row_type": "schedule_e_payment",
                    "payee_name": payee_name,
                    "payee_name_raw": payee_name_raw or payee_name,
                    "address_raw": address_raw,
                    "payment_code": code,
                    "description_raw": description_raw,
                    "amount_paid": amount_paid,
                    "parse_confidence": "medium",
                    "raw_block_text": "\n".join(
                        [part for part in [line, payee_name_raw, description_raw, address_raw] if part]
                    ),
                }
            )
            index = next_index
            continue

        combined_match = re.match(
            rf"^(?P<payee>.+?)\s+(?P<code>{PAYMENT_CODE_GROUP})\b(?P<rest>.*)$",
            line,
            re.IGNORECASE,
        )
        if combined_match:
            payee_name_raw = combined_match.group("payee").strip()
            code = combined_match.group("code").upper()
            rest = combined_match.group("rest").strip()
            amount_paid = extract_last_amount_from_line(rest or line)
            description_raw = normalize_numeric_spacing(rest)
            if amount_paid is not None:
                description_raw = re.sub(
                    r"-?\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?\s*$",
                    "",
                    description_raw,
                ).strip(" .")
            next_index = index + 1
            while (
                next_index < len(lines)
                and not line_is_address(lines[next_index])
                and not looks_like_schedule_e_row_start(lines[next_index])
            ):
                description_raw = f"{description_raw} {lines[next_index]}".strip() if description_raw else lines[next_index]
                next_index += 1
            address_raw = lines[next_index] if next_index < len(lines) and line_is_address(lines[next_index]) else None
            if address_raw is not None:
                next_index += 1
            rows.append(
                {
                    "page_num": page_num,
                    "row_type": "schedule_e_payment",
                    "payee_name": clean_contributor_name(payee_name_raw),
                    "payee_name_raw": payee_name_raw,
                    "address_raw": address_raw,
                    "payment_code": code,
                    "description_raw": description_raw or None,
                    "amount_paid": amount_paid,
                    "parse_confidence": "high",
                    "raw_block_text": "\n".join(
                        [part for part in [line, description_raw or None, address_raw] if part]
                    ),
                }
            )
            index = next_index
            continue

        # Fallback for lines that preserve payee + description + amount but lose the exact code token.
        if extract_last_amount_from_line(line) is not None:
            payee_name, description_raw = split_schedule_e_payee_and_description(
                re.sub(r"-?\d{1,3}(?:[ ,]\d{3})*(?:\.\s?\d{1,2})?\s*$", "", line).strip()
            )
            if payee_name:
                next_index = index + 1
                address_raw = lines[next_index] if next_index < len(lines) and line_is_address(lines[next_index]) else None
                if address_raw is not None:
                    next_index += 1
                rows.append(
                    {
                        "page_num": page_num,
                        "row_type": "schedule_e_payment",
                        "payee_name": payee_name,
                        "payee_name_raw": payee_name,
                        "address_raw": address_raw,
                        "payment_code": None,
                        "description_raw": description_raw,
                        "amount_paid": extract_last_amount_from_line(line),
                        "parse_confidence": "medium",
                        "raw_block_text": "\n".join(
                            [part for part in [line, address_raw] if part]
                        ),
                    }
                )
                index = next_index
                continue

        index += 1

    return rows


def parse_schedule_e_summary_page(page_text: str) -> dict[str, float | None]:
    lines = extract_section_lines(page_text)
    if "Schedule E Summary" not in lines:
        return {}

    summary: dict[str, float | None] = {
        "reported_itemized_payments": None,
        "reported_unitemized_payments": None,
        "reported_interest_paid": None,
        "reported_total_payments": None,
    }
    previous_amount = None
    for line in lines:
        current_amount = extract_last_amount_from_line(line)
        if "1. Itemized payments made this period." in line:
            summary["reported_itemized_payments"] = previous_amount if previous_amount is not None else current_amount
        elif "2. Unitemized payments made this period" in line:
            summary["reported_unitemized_payments"] = previous_amount if previous_amount is not None else current_amount
        elif "3. Total interest paid this period on loans." in line:
            summary["reported_interest_paid"] = previous_amount if previous_amount is not None else current_amount
        elif "4. Total payments made this period." in line:
            summary["reported_total_payments"] = previous_amount if previous_amount is not None else current_amount
        if current_amount is not None:
            previous_amount = current_amount
    return summary


def parse_filing_summary_page(page_text: str) -> dict[str, float | None]:
    lines = extract_section_lines(page_text)
    normalized_lines = [line.upper() for line in lines]

    def extract_after(anchor: str) -> float | None:
        for index, line in enumerate(normalized_lines):
            if anchor not in line:
                continue
            for lookahead in lines[index + 1 : index + 12]:
                amounts = extract_strict_amounts_from_line(lookahead)
                if amounts:
                    return amounts[-1]
        return None

    summary = {
        "reported_monetary_contributions": extract_after("1. MONETARY CONTRIBUTIONS"),
        "reported_loans_received": extract_after("2. LOANS RECEIVED"),
        "reported_total_contributions_received": extract_after("5. TOTAL CONTRIBUTIONS RECEIVED"),
        "reported_payments_made": extract_after("6. PAYMENTS MADE"),
        "reported_total_expenditures_made": extract_after("11. TOTAL EXPENDITURES MADE"),
    }
    return summary


def load_known_actor_map() -> dict[str, dict[str, Any]]:
    bundles = [
        json.loads(CANONICAL_SEEDS_PATH.read_text()),
        json.loads(CAMPAIGN_SAMPLE_BUNDLE_PATH.read_text()),
    ]
    actor_map: dict[str, dict[str, Any]] = {}
    for bundle in bundles:
        for actor in bundle.get("actor_candidates", []):
            actor_id = actor["id"]
            names = [actor.get("name")]
            names.extend(actor.get("aliases", []))
            names.extend(actor.get("observed_labels", []))
            for name in names:
                if not name:
                    continue
                actor_map.setdefault(normalize_name_key(name), {"id": actor_id, "name": actor.get("name", name)})
    return actor_map


def build_money_flow_id(parts: list[str]) -> str:
    return f"moneyflow-{slugify('-'.join(part for part in parts if part))}"


def build_validation_check_id(parts: list[str]) -> str:
    return f"validationcheck-{slugify('-'.join(part for part in parts if part))}"


def build_validation_check(
    *,
    check_id: str,
    check_type: str,
    subject_node_id: str,
    subject_node_type: str,
    metric_name: str,
    measured_value_number: float | None,
    measured_value_label: str,
    reference_value_number: float | None,
    reference_value_label: str,
    derived_from_record_id: str,
    evidence_record_ids: list[str],
) -> dict[str, Any]:
    delta_value_number: float | None = None
    absolute_delta_value_number: float | None = None
    delta_direction: str | None = None
    status = "needs_review"
    severity = "warn"
    confidence = "medium"

    if measured_value_number is not None and reference_value_number is not None:
        confidence = "high"
        delta_value_number = round(measured_value_number - reference_value_number, 2)
        absolute_delta_value_number = round(abs(delta_value_number), 2)
        if absolute_delta_value_number == 0:
            status = "reconciled"
            severity = "info"
            delta_direction = "equal"
        elif delta_value_number < 0:
            status = "extraction_gap"
            delta_direction = "reference_gt_measured"
        else:
            status = "source_inconsistency"
            delta_direction = "measured_gt_reference"

    notes: list[str] = []
    if status == "extraction_gap":
        notes.append("Measured value trails the official or reference value.")
    elif status == "source_inconsistency":
        notes.append("Measured value exceeds the official or reference value and needs review.")

    return {
        "id": check_id,
        "check_type": check_type,
        "subject_node_id": subject_node_id,
        "subject_node_type": subject_node_type,
        "metric_name": metric_name,
        "measured_value_number": measured_value_number,
        "measured_value_label": measured_value_label,
        "reference_value_number": reference_value_number,
        "reference_value_label": reference_value_label,
        "delta_value_number": delta_value_number,
        "absolute_delta_value_number": absolute_delta_value_number,
        "delta_direction": delta_direction,
        "status": status,
        "severity": severity,
        "confidence": confidence,
        "derived_from_record_id": derived_from_record_id,
        "evidence_record_ids": evidence_record_ids,
        "notes": notes,
    }


def dedupe_schedule_rows(rows: list[dict[str, Any]], keys: list[str]) -> list[dict[str, Any]]:
    seen: set[tuple[Any, ...]] = set()
    deduped: list[dict[str, Any]] = []
    for row in rows:
        key = tuple(row.get(field) for field in keys)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def main() -> None:
    raw_capture = json.loads(RAW_CAPTURE_PATH.read_text())
    known_actor_map = load_known_actor_map()
    pdf_export_map = load_pdf_export_map()
    generated_at = utc_now_iso()

    actor_candidates_by_id: dict[str, dict[str, Any]] = {}
    filing_candidates: list[dict[str, Any]] = []
    money_flow_candidates: list[dict[str, Any]] = []
    validation_check_candidates: list[dict[str, Any]] = []
    record_refs: list[dict[str, Any]] = []
    extracted_filings: list[dict[str, Any]] = []

    for capture in raw_capture["captures"]:
        if capture["status"] != "captured":
            continue

        target = capture["target"]
        filing_candidate = target["filing_candidate"]
        source_record_id = target["record_id"]
        ocr_record_id = f"record-san-rafael-campaign-ocr-entry-{target['entry_id']}"
        pdf_record_id = f"record-san-rafael-campaign-pdf-entry-{target['entry_id']}"
        pdf_path = pdf_export_map.get(target["entry_id"])
        pdf_pages = load_pdf_layout_pages(pdf_path) if pdf_path else []
        evidence_record_ids = [source_record_id, ocr_record_id]
        if pdf_path:
            evidence_record_ids.append(pdf_record_id)

        summary_page = next((page for page in capture["pages"] if page["page_num"] == 3), None)
        filing_summary = parse_filing_summary_page(summary_page["text"]) if summary_page else {}

        schedule_a_rows: list[dict[str, Any]] = []
        schedule_d_rows: list[dict[str, Any]] = []
        schedule_e_rows: list[dict[str, Any]] = []
        schedule_a_page_subtotals: list[float] = []
        schedule_a_summary: dict[str, float | None] = {}
        schedule_e_summary: dict[str, float | None] = {}

        for page in capture["pages"]:
            page_text = page["text"]
            lines = extract_section_lines(page_text)
            if is_schedule_a_page(lines):
                blocks = split_date_blocks(lines)
                schedule_a_rows.extend(
                    [row for block in blocks if (row := parse_schedule_a_block(block, page["page_num"])) is not None]
                )
                subtotal = page_subtotal(page_text)
                if subtotal is not None:
                    schedule_a_page_subtotals.append(subtotal)
                schedule_a_summary.update(parse_schedule_a_summary_page(page_text))
            elif is_schedule_d_page(lines):
                blocks = split_date_blocks(lines)
                schedule_d_rows.extend(
                    [row for block in blocks if (row := parse_schedule_d_block(block, page["page_num"])) is not None]
                )
            elif is_schedule_e_page(lines) and not pdf_pages:
                schedule_e_rows.extend(parse_schedule_e_page(page_text, page["page_num"]))

        if pdf_pages:
            for page_num, page_text in enumerate(pdf_pages, start=1):
                pdf_lines = extract_section_lines(page_text)
                if is_schedule_e_page(pdf_lines):
                    schedule_e_rows.extend(parse_schedule_e_page_from_pdf_layout(page_text, page_num))
                if "Schedule E Summary" in page_text:
                    schedule_e_summary.update(parse_schedule_e_summary_page(page_text))

        schedule_a_rows = dedupe_schedule_rows(
            schedule_a_rows,
            ["page_num", "date_received", "contributor_name", "amount_received_this_period"],
        )
        schedule_d_rows = dedupe_schedule_rows(
            schedule_d_rows,
            ["page_num", "date_received", "target_name", "amount_this_period", "payment_type"],
        )

        extracted_contributions_total = round(
            sum(row["amount_received_this_period"] for row in schedule_a_rows if row["amount_received_this_period"] is not None),
            2,
        )
        extracted_schedule_d_total = round(
            sum(row["amount_this_period"] for row in schedule_d_rows if row["amount_this_period"] is not None),
            2,
        )
        extracted_payments_total = round(
            sum(row["amount_paid"] for row in schedule_e_rows if row["amount_paid"] is not None),
            2,
        )

        if schedule_e_summary.get("reported_total_payments") is not None:
            filing_summary["reported_payments_made"] = schedule_e_summary["reported_total_payments"]
            filing_summary["reported_total_expenditures_made"] = schedule_e_summary["reported_total_payments"]
        if schedule_a_summary.get("reported_total_contributions") is not None:
            filing_summary["reported_monetary_contributions"] = schedule_a_summary["reported_total_contributions"]
            filing_summary["reported_total_contributions_received"] = schedule_a_summary["reported_total_contributions"]

        filing_summary["reported_loans_received"] = None
        if (
            filing_summary.get("reported_payments_made") is not None
            and extracted_payments_total
            and filing_summary["reported_payments_made"] < extracted_payments_total
        ):
            filing_summary["reported_payments_made"] = None
        if (
            filing_summary.get("reported_total_expenditures_made") is not None
            and extracted_payments_total
            and filing_summary["reported_total_expenditures_made"] < extracted_payments_total
        ):
            filing_summary["reported_total_expenditures_made"] = None

        extracted_filings.append(
            {
                "entry_id": target["entry_id"],
                "filing_id": target["filing_id"],
                "record_id": source_record_id,
                "ocr_record_id": ocr_record_id,
                "label": target["label"],
                "page_count": len(capture["pages"]),
                "schedule_a_rows": schedule_a_rows,
                "schedule_d_rows": schedule_d_rows,
                "schedule_e_rows": schedule_e_rows,
                "reported_totals": {
                    **filing_summary,
                    **schedule_a_summary,
                    "schedule_a_page_subtotals_sum": round(sum(schedule_a_page_subtotals), 2) if schedule_a_page_subtotals else None,
                    **schedule_e_summary,
                },
                "counts": {
                    "schedule_a_row_count": len(schedule_a_rows),
                    "schedule_d_row_count": len(schedule_d_rows),
                    "schedule_e_row_count": len(schedule_e_rows),
                },
                "extracted_totals": {
                    "itemized_contributions_total": extracted_contributions_total,
                    "schedule_d_total": extracted_schedule_d_total,
                    "itemized_payments_total": extracted_payments_total,
                },
            }
        )

        filing_record_id = f"record-san-rafael-campaign-form460-schedule-extract-entry-{target['entry_id']}"
        record_refs.append(
            {
                "id": filing_record_id,
                "record_class": "financial_record",
                "record_type": "form_460_schedule_extract",
                "source_id": "san-rafael-city-campaign-form460-ocr",
                "artifact_path": EXTRACTED_ARTIFACT_PATH,
                "capture_status": "derived_from_ocr_capture",
                "source_record_id": source_record_id,
                "ocr_record_id": ocr_record_id,
                "source_filing_id": target["filing_id"],
                "title": f"Schedule extraction for {filing_candidate['title']}",
                "entry_id": target["entry_id"],
            }
        )

        validation_check_ids: list[str] = []
        validation_specs = [
            {
                "check_type": "reconciliation_check",
                "metric_name": "schedule_a_itemized_contributions",
                "measured_value_number": extracted_contributions_total,
                "measured_value_label": "extracted_itemized_contributions_total",
                "reference_value_number": schedule_a_summary.get("reported_itemized_contributions"),
                "reference_value_label": "reported_itemized_contributions",
            },
            {
                "check_type": "summary_consistency_check",
                "metric_name": "schedule_a_total_contributions_rollup",
                "measured_value_number": round(
                    (schedule_a_summary.get("reported_itemized_contributions") or 0.0)
                    + (schedule_a_summary.get("reported_unitemized_contributions") or 0.0),
                    2,
                ),
                "measured_value_label": "reported_itemized_plus_unitemized_contributions",
                "reference_value_number": schedule_a_summary.get("reported_total_contributions"),
                "reference_value_label": "reported_total_contributions",
            },
            {
                "check_type": "reconciliation_check",
                "metric_name": "schedule_e_itemized_payments",
                "measured_value_number": extracted_payments_total,
                "measured_value_label": "extracted_itemized_payments_total",
                "reference_value_number": schedule_e_summary.get("reported_itemized_payments"),
                "reference_value_label": "reported_itemized_payments",
            },
            {
                "check_type": "summary_consistency_check",
                "metric_name": "schedule_e_total_payments_rollup",
                "measured_value_number": round(
                    (schedule_e_summary.get("reported_itemized_payments") or 0.0)
                    + (schedule_e_summary.get("reported_unitemized_payments") or 0.0)
                    + (schedule_e_summary.get("reported_interest_paid") or 0.0),
                    2,
                ),
                "measured_value_label": "reported_itemized_plus_unitemized_plus_interest_payments",
                "reference_value_number": schedule_e_summary.get("reported_total_payments"),
                "reference_value_label": "reported_total_payments",
            },
        ]

        for spec in validation_specs:
            check = build_validation_check(
                check_id=build_validation_check_id(
                    [target["filing_id"], spec["metric_name"], spec["check_type"]]
                ),
                check_type=spec["check_type"],
                subject_node_id=target["filing_id"],
                subject_node_type="Filing",
                metric_name=spec["metric_name"],
                measured_value_number=spec["measured_value_number"],
                measured_value_label=spec["measured_value_label"],
                reference_value_number=spec["reference_value_number"],
                reference_value_label=spec["reference_value_label"],
                derived_from_record_id=filing_record_id,
                evidence_record_ids=evidence_record_ids + [filing_record_id],
            )
            validation_check_candidates.append(check)
            validation_check_ids.append(check["id"])

        filing_candidates.append(
            {
                "id": target["filing_id"],
                "filing_type": "form_460",
                "committee_id": filing_candidate["committee_id"],
                "filer_actor_id": filing_candidate["filer_actor_id"],
                "election_id": filing_candidate["election_id"],
                "record_id": source_record_id,
                "schedule_extract_record_id": filing_record_id,
                "schedule_a_row_count": len(schedule_a_rows),
                "schedule_d_row_count": len(schedule_d_rows),
                "schedule_e_row_count": len(schedule_e_rows),
                "extracted_itemized_contributions_total": extracted_contributions_total,
                "extracted_schedule_d_total": extracted_schedule_d_total,
                "extracted_itemized_payments_total": extracted_payments_total,
                "reported_itemized_contributions": schedule_a_summary.get("reported_itemized_contributions"),
                "reported_unitemized_contributions": schedule_a_summary.get("reported_unitemized_contributions"),
                "reported_monetary_contributions": filing_summary.get("reported_monetary_contributions"),
                "reported_payments_made": filing_summary.get("reported_payments_made"),
                "reported_itemized_payments": schedule_e_summary.get("reported_itemized_payments"),
                "reported_unitemized_payments": schedule_e_summary.get("reported_unitemized_payments"),
                "validation_check_ids": validation_check_ids,
                "evidence_record_ids": evidence_record_ids + [filing_record_id],
            }
        )

        for index, row in enumerate(schedule_a_rows, start=1):
            actor_id = resolve_actor(
                row["contributor_name_raw"],
                infer_actor_type(row["contributor_name"], row["contributor_code"], default="person"),
                known_actor_map,
                actor_candidates_by_id,
                evidence_record_ids,
            )
            money_flow_candidates.append(
                {
                    "id": build_money_flow_id(
                        [
                            row["date_received"] or "undated",
                            row["contributor_name"],
                            filing_candidate["committee_id"],
                            str(index),
                        ]
                    ),
                    "flow_type": "campaign_contribution",
                    "amount": row["amount_received_this_period"],
                    "flow_date": row["date_received"],
                    "from_actor_id": actor_id,
                    "to_committee_id": filing_candidate["committee_id"],
                    "filing_id": target["filing_id"],
                    "contributor_code": row["contributor_code"],
                    "source_schedule": "schedule_a",
                    "source_page_num": row["page_num"],
                    "parse_confidence": row["parse_confidence"],
                    "occupation_employer_raw": row["occupation_employer_raw"],
                    "address_raw": row["address_raw"],
                    "evidence_record_ids": evidence_record_ids,
                }
            )

        for index, row in enumerate(schedule_d_rows, start=1):
            actor_id = resolve_actor(
                row["target_name_raw"],
                "person",
                known_actor_map,
                actor_candidates_by_id,
                evidence_record_ids,
            )
            money_flow = {
                "id": build_money_flow_id(
                    [
                        row["date_received"] or "undated",
                        filing_candidate["committee_id"],
                        row["target_name"],
                        "schedule-d",
                        str(index),
                    ]
                ),
                "amount": row["amount_this_period"],
                "flow_date": row["date_received"],
                "from_committee_id": filing_candidate["committee_id"],
                "beneficiary_actor_id": actor_id,
                "filing_id": target["filing_id"],
                "source_schedule": "schedule_d",
                "source_page_num": row["page_num"],
                "parse_confidence": row["parse_confidence"],
                "description_raw": row["description_raw"],
                "stance": row["stance"],
                "evidence_record_ids": evidence_record_ids,
            }
            if row["payment_type"] == "independent_expenditure":
                money_flow["flow_type"] = "campaign_independent_expenditure"
            else:
                money_flow["flow_type"] = "campaign_contribution"
            money_flow_candidates.append(money_flow)

        for index, row in enumerate(schedule_e_rows, start=1):
            actor_id = resolve_actor(
                row["payee_name_raw"],
                infer_actor_type(row["payee_name"], None, default="organization"),
                known_actor_map,
                actor_candidates_by_id,
                evidence_record_ids,
            )
            money_flow_candidates.append(
                {
                    "id": build_money_flow_id(
                        [
                            filing_candidate["committee_id"],
                            row["payee_name"],
                            row["payment_code"] or "uncoded",
                            str(index),
                        ]
                    ),
                    "flow_type": "campaign_expenditure",
                    "amount": row["amount_paid"],
                    "from_committee_id": filing_candidate["committee_id"],
                    "to_actor_id": actor_id,
                    "filing_id": target["filing_id"],
                    "payment_code": row["payment_code"],
                    "description_raw": row["description_raw"],
                    "address_raw": row["address_raw"],
                    "source_schedule": "schedule_e",
                    "source_page_num": row["page_num"],
                    "parse_confidence": row["parse_confidence"],
                    "evidence_record_ids": evidence_record_ids,
                }
            )

    extracted_payload = {
        "capture_date": "2026-04-12",
        "extracted_at": generated_at,
        "source_id": "san-rafael-city-campaign-form460-ocr",
        "filing_extracts": extracted_filings,
        "notes": [
            "This is a conservative schedule extractor over the OCR bundle plus the selective raw-PDF evidence path.",
            "Schedule A and Schedule D still primarily depend on the OCR capture. Schedule E now prefers the PDF text layer when the raw export exists.",
        ],
    }

    normalized_payload = {
        "case_study_id": CASE_STUDY_ID,
        "bundle_id": BUNDLE_ID,
        "status": "working",
        "generated_at": generated_at,
        "scope": [
            "Selected San Rafael 2024 Form 460 filings with schedule-level OCR extraction",
            "Promotion of itemized contribution and expenditure rows into graph-ready MoneyFlow candidates where OCR is strong enough",
            "Reuse of existing filing and committee IDs instead of inventing a parallel campaign namespace",
            "Automatic filing-level validation checks against official itemized and rollup summary values",
        ],
        "record_refs": sorted(record_refs, key=lambda item: item["entry_id"]),
        "actor_candidates": sorted(actor_candidates_by_id.values(), key=lambda item: item["id"]),
        "filing_candidates": sorted(filing_candidates, key=lambda item: item["id"]),
        "money_flow_candidates": money_flow_candidates,
        "validation_check_candidates": sorted(validation_check_candidates, key=lambda item: item["id"]),
        "open_questions": [
            {
                "id": "OQ-027",
                "status": "watch",
                "question": "How should the project treat schedule extraction when validation checks still show a bounded contribution-side extraction gap after the raw PDFs are preserved?",
            }
        ],
        "notes": [
            "This bundle intentionally promotes only row-level facts that are legible from the current OCR or PDF text capture.",
            "The filing totals are preserved as filing-level enrichments and now emit explicit ValidationCheck candidates so later anomaly work can distinguish extraction gaps from filing-level inconsistencies.",
            "Committee-contributor rows are currently normalized through actor candidates unless a stronger committee identity already exists elsewhere in the graph.",
        ],
    }

    write_json(EXTRACTED_PATH, extracted_payload)
    write_json(NORMALIZED_PATH, normalized_payload)


if __name__ == "__main__":
    main()
