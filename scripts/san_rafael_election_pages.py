from __future__ import annotations

import html
import re
from urllib.parse import urlparse


DISCOVERY_PAGES = [
    {
        "source_id": "san-rafael-elections-index",
        "label": "San Rafael Elections Index",
        "entry_url": "https://www.cityofsanrafael.org/elections/",
    },
    {
        "source_id": "san-rafael-past-elections",
        "label": "San Rafael Past Elections Index",
        "entry_url": "https://www.cityofsanrafael.org/past-elections/",
    },
]

KNOWN_ELECTION_PAGES = [
    {
        "source_id": "san-rafael-june-2-2026-special-municipal-election",
        "label": "San Rafael June 2 2026 Special Municipal Election Page",
        "entry_url": "https://www.cityofsanrafael.org/june-2-2026-special-municipal-election/",
    },
    {
        "source_id": "san-rafael-november-5-2024-election",
        "label": "San Rafael November 5 2024 Election Page",
        "entry_url": "https://www.cityofsanrafael.org/november-5-2024-election/",
    },
    {
        "source_id": "san-rafael-november-8-2022-election",
        "label": "San Rafael November 8 2022 Election Page",
        "entry_url": "https://www.cityofsanrafael.org/november-8-2022-election/",
    },
    {
        "source_id": "san-rafael-november-3-2020-election",
        "label": "San Rafael November 3 2020 Election Page",
        "entry_url": "https://www.cityofsanrafael.org/november-3-2020-election/",
    },
    {
        "source_id": "san-rafael-june-5-2018-special-municipal-election",
        "label": "San Rafael June 5 2018 Special Municipal Election Page",
        "entry_url": "https://www.cityofsanrafael.org/june-5-2018-special-municipal-election/",
    },
    {
        "source_id": "san-rafael-november-6-2018-election",
        "label": "San Rafael November 6 2018 Election Page",
        "entry_url": "https://www.cityofsanrafael.org/november-6-2018-election/",
    },
    {
        "source_id": "san-rafael-november-7-2017-election",
        "label": "San Rafael November 7 2017 General Municipal Election Page",
        "entry_url": "https://www.cityofsanrafael.org/november-7-2017-election/",
    },
    {
        "source_id": "san-rafael-june-7-2016-election",
        "label": "San Rafael June 7 2016 Election Page",
        "entry_url": "https://www.cityofsanrafael.org/june-7-2016-election/",
    },
    {
        "source_id": "san-rafael-november-3-2015-election",
        "label": "San Rafael November 3 2015 Election Page",
        "entry_url": "https://www.cityofsanrafael.org/november-3-2015-election/",
    },
    {
        "source_id": "san-rafael-november-5-2013-election",
        "label": "San Rafael November 5 2013 Election Page",
        "entry_url": "https://www.cityofsanrafael.org/november-5-2013-election/",
    },
    {
        "source_id": "san-rafael-november-8-2011-election",
        "label": "San Rafael November 8 2011 Election Page",
        "entry_url": "https://www.cityofsanrafael.org/november-8-2011-election/",
    },
    {
        "source_id": "san-rafael-november-2-2010-election",
        "label": "San Rafael November 2 2010 Election Page",
        "entry_url": "https://www.cityofsanrafael.org/november-2-2010-election/",
    },
    {
        "source_id": "san-rafael-june-8-2010-election",
        "label": "San Rafael June 8 2010 Election Page",
        "entry_url": "https://www.cityofsanrafael.org/june-8-2010-election/",
    },
]

KNOWN_ELECTION_PAGE_MAP = {page["entry_url"]: page for page in KNOWN_ELECTION_PAGES}


def slug_to_source_id(url: str) -> str:
    slug = urlparse(url).path.strip("/").lower()
    return f"san-rafael-{slug}"


def fallback_label(url: str) -> str:
    slug = urlparse(url).path.strip("/").replace("-", " ").title()
    return f"San Rafael {slug}"


def get_election_page_metadata(url: str) -> dict[str, str]:
    normalized_url = normalize_url(url)
    page = KNOWN_ELECTION_PAGE_MAP.get(normalized_url)
    if page is not None:
        return dict(page)
    return {
        "source_id": slug_to_source_id(normalized_url),
        "label": fallback_label(normalized_url),
        "entry_url": normalized_url,
    }


def normalize_url(url: str) -> str:
    clean = html.unescape(url).strip()
    if clean.startswith("//"):
        clean = "https:" + clean
    if clean.startswith("http://"):
        clean = "https://" + clean[len("http://") :]
    if clean and not clean.endswith("/"):
        clean += "/"
    return clean


def extract_election_page_urls(html_text: str) -> list[str]:
    urls = re.findall(r"https://www\.cityofsanrafael\.org/[a-z0-9\-]+election/", html_text)
    seen: set[str] = set()
    ordered: list[str] = []
    for url in urls:
        normalized = normalize_url(url)
        if normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return ordered


def build_discovered_election_pages(discovery_html_texts: list[str]) -> list[dict[str, str]]:
    seen: set[str] = set()
    ordered_urls: list[str] = []
    for html_text in discovery_html_texts:
        for url in extract_election_page_urls(html_text):
            if url in seen:
                continue
            seen.add(url)
            ordered_urls.append(url)

    for page in KNOWN_ELECTION_PAGES:
        if page["entry_url"] in seen:
            continue
        seen.add(page["entry_url"])
        ordered_urls.append(page["entry_url"])

    return [get_election_page_metadata(url) for url in ordered_urls]
