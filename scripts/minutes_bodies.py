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

from minutes_sources import MINUTES_EXTENSIONS, SOURCE_MAP  # noqa: F401  (MINUTES_EXTENSIONS: re-exported)
from minutes_sources import source_of as _source_of

SOURCES = {s.id: s.jurisdiction for s in SOURCE_MAP.values()}  # source id → jurisdiction (minutes_sources)

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
    "tiburon-town-council-granicus": (
        (r"\bjoint\b", "Tiburon joint meeting"),
        (r"\bdesign review board\b", "Tiburon Design Review Board"),
        (r"\bplanning commission\b", "Tiburon Planning Commission"),
        (r"\bparks,? open space,? ?(?:and|&) trails\b", "Tiburon Parks, Open Space and Trails Commission"),
        (r"\bheritage (?:and|&) arts commission\b", "Tiburon Heritage & Arts Commission"),
        (r"\bdiversity,? (?:and )?inclusion task force\b", "Tiburon Diversity Inclusion Task Force"),
        (r"\btown council\b", "Tiburon Town Council"),
    ),
    "mill-valley-committees": (  # aliases as registry/body-attribution.yaml records them
        (r"\bjoint\b", "Mill Valley joint meeting"),
        (r"\barts commission\b", "Mill Valley Arts Commission"),
        (r"\blibrary board\b", "Mill Valley Library Board of Trustees"),
        (r"\bemergency preparedness commission\b", "Mill Valley Emergency Preparedness Commission"),
        (r"\bsewerage agency of south(?:ern)? marin\b|\bsasm\b", "Sewerage Agency of Southern Marin"),
        (r"\bbicycle (?:and |& )?pedestrian advisory committee\b|\bbpac\b",
         "Mill Valley Bicycle & Pedestrian Advisory Committee"),
        (r"\b(?:traffic|transportation) (?:and |& )?mobility advisory committee\b|\btmac\b",
         "Mill Valley Transportation & Mobility Advisory Committee"),
        (r"\bzoning administrator\b", "Mill Valley Zoning Administrator"),
        (r"\bdesign advisory committee\b", "Mill Valley Design Advisory Committee"),
        (r"\binfrastructure funding study committee\b", "Mill Valley Infrastructure Funding Study Committee"),
        (r"\bplanning commission\b|\bplannig commission\b", "Mill Valley Planning Commission"),
        (r"\bparks? (?:and|&) recreation\b", "Mill Valley Parks & Recreation Commission"),
        (r"\bcity council\b", "Mill Valley City Council"),
    ),
    "fairfax-town-council": (
        (r"\bjoint\b", "Fairfax joint meeting"),
        (r"\btown council\b", "Fairfax Town Council"),
    ),
    "belvedere-city-council": (
        (r"\bjoint\b", "Belvedere joint meeting"),
        (r"\bcity council\b", "Belvedere City Council"),
    ),
    "ross-town-council": (
        (r"\bjoint\b", "Ross joint meeting"),
        (r"\badvisory design review\b", "Ross Advisory Design Review Group"),
        (r"\btown council\b|\bannual budget workshop\b", "Ross Town Council"),
    ),
    "san-rafael-city-council": (
        (r"\bjoint\b", "San Rafael joint meeting"),
        (r"\bcity council\b", "San Rafael City Council"),
    ),
}
_COMPILED = {s: tuple((re.compile(p, re.I), body) for p, body in rules) for s, rules in _RULES.items()}


def source_of(meeting_id: str) -> str | None:
    """The source whose id space holds this Meeting id (None for any other id): minutes_sources' id shapes."""
    return _source_of(meeting_id)


def normalize_body(source: str, title: str) -> tuple[str, bool]:
    """(the real body, True) — or (the title unchanged, False) when no rule recognises it."""
    for pattern, body in _COMPILED.get(source, ()):
        if pattern.search(title or ""):
            return body, True
    return title or "", False
