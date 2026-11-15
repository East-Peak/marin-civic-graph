#!/usr/bin/env python3
"""Minutes text: which real governing body a Meeting is, from its listing title.

A source's meeting-id space is not one body: San Anselmo's council-prefixed ids hold its commissions and
committees, Corte Madera's hold the Planning Commission, Sanitary District No. 2 and the Fire Authority, and every
source titles session variants differently ("Town Council - Special Meeting", "Special Town Council (No Video
Available)"). Each source has an ordered rule list — the first pattern found in the title names the body — so a
variant folds into its body. A title no rule recognises passes through unchanged and is reported as unknown.
"""
from __future__ import annotations

import re

SOURCES = {  # source id (the meeting-id prefix) → jurisdiction
    "corte-madera-town-council": "Corte Madera",
    "novato-city-council": "Novato",
    "marin-county-bos": "Marin County",
    "sausalito-city-council": "Sausalito",
    "san-anselmo-town-council": "San Anselmo",
}

# A cached minutes document is <raw>/<source>/minutes/<meeting_id>.<one of these> (the index and the fetch helper).
MINUTES_EXTENSIONS = ("pdf", "html", "htm", "docx")

_SAN_ANSELMO_BODIES = (  # its listing titles name the body itself; order only matters for overlaps
    "Town Council", "Parks and Recreation Commission", "Bicycle and Pedestrian Advisory Committee",
    "Planning Commission", "Arts Commission", "Open Space Committee", "Climate Action Commission",
    "Economic Development Committee", "Historical Commission", "Red Hill Dog Park Steering Committee",
    "Racial Equity Committee", "Robson-Harrington Community Garden Committee", "Library Advisory Board",
    "General Plan Advisory Committee",
)

_RULES: dict[str, tuple[tuple[str, str], ...]] = {
    "corte-madera-town-council": (
        (r"\bjoint\b", "Corte Madera joint meeting"),
        (r"central marin fire authority|\bfire council\b", "Central Marin Fire Authority Fire Council"),
        (r"\bcouncil\b", "Corte Madera Town Council"),
        (r"\bplanning commission\b", "Corte Madera Planning Commission"),
        (r"\bsanitary district no\.? ?2\b", "Sanitary District No. 2 Board of Directors"),
        (r"\bsales tax citizens'? oversight committee\b", "Corte Madera Sales Tax Citizens' Oversight Committee"),
        (r"\bparks and recreation\b", "Corte Madera Parks and Recreation Commission"),
        (r"\bflood control board\b", "Corte Madera Flood Control Board"),
        (r"\bclimate action committee\b", "Corte Madera Climate Action Committee"),
        (r"\bbicycle (?:and )?pedestrian advisory committee\b|\bbpac\b",
         "Corte Madera Bicycle and Pedestrian Advisory Committee"),
    ),
    "novato-city-council": (
        (r"\bsuccessor agency\b|\bpublic finance authority\b", "Novato City Council"),
        (r"\bjoint\b", "Novato joint meeting"),
        (r"\bcouncil\b", "Novato City Council"),
        (r"\bplanning commission\b", "Novato Planning Commission"),
    ),
    "marin-county-bos": (
        (r"\bjoint\b", "Marin County joint meeting"),
        (r"^board of supervisors\b|^budget\b", "Marin County Board of Supervisors"),
    ),
    "sausalito-city-council": (
        (r"\bjoint\b", "Sausalito joint meeting"),
        (r"\bcity council\b", "Sausalito City Council"),
    ),
    "san-anselmo-town-council": (
        (r"\bjoint\b", "San Anselmo joint meeting"),
        *((rf"\b{re.escape(b.lower())}\b", f"San Anselmo {b}") for b in _SAN_ANSELMO_BODIES),
    ),
}
_COMPILED = {s: tuple((re.compile(p, re.I), body) for p, body in rules) for s, rules in _RULES.items()}


def source_of(meeting_id: str) -> str | None:
    """The source whose id space holds this Meeting id (None for any other id)."""
    return next((s for s in SOURCES if meeting_id.startswith(f"meeting-{s}-")), None)


def normalize_body(source: str, title: str) -> tuple[str, bool]:
    """(the real body, True) — or (the title unchanged, False) when no rule recognises it."""
    for pattern, body in _COMPILED.get(source, ()):
        if pattern.search(title or ""):
            return body, True
    return title or "", False
