#!/usr/bin/env python3
"""Manual fetch-on-demand of minutes whose URLs are already in the public substrate but not yet cached.

    python scripts/fetch_indexed_documents.py --source <source-id> --body <filter> [--limit N]

The 2026-10-15 Granicus-minutes decision authorizes these single-document fetches by hand; this helper does not use
or change scripts/robots_gate.py, and nothing else calls it. The rules it enforces:

  1. One document per request; every request, each redirect hop included, starts >= 3.0 s after the previous.
  2. A cached document (<raw>/<source>/minutes/<meeting_id>.{pdf,html,docx}) is never refetched.
  3. An honest User-Agent with no personal contact details.
  4. No listing or crawl: only exact minutes URLs taken from the substrate; any other URL is refused (RefusedUrl).
  5. Redirects are not followed automatically; each hop's host must be in the source's allow-list (below) or that
     document is skipped uncached. At most MAX_HOPS hops.
  6. Only real documents are cached: PDF magic bytes, or HTML without bot-wall markers. Nothing else, ever.
  7. The WHOLE run stops (no retry, exit 1) on any 403, any 429, or a bot-wall page (a 200 included, any hop).
     Other failures (404, network error, non-document bytes, bad redirect host) are logged and skipped.
  8. --limit caps the documents attempted.

Each attempt appends one JSON line to <raw>/<source>/minutes-fetch-log.jsonl (beside the minutes dir, never in it).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))

from minutes_bodies import SOURCES, normalize_body  # noqa: E402
from votes_inventory import normalize_url, sniff_format  # noqa: E402

MIN_INTERVAL_S = 3.0
MAX_HOPS = 5
DEFAULT_LIMIT = 25
USER_AGENT = "OpenMarin/1.0 (civic records research; single-document fetches)"
DEFAULT_SUBSTRATE = Path("~/projects/marin-civic-graph/data/exports/public-substrate.sqlite").expanduser()
DEFAULT_RAW = Path("~/projects/marin-civic-graph/data/raw").expanduser()

OWN_HOSTS = {  # a source's initial minutes URLs must be on its own host
    "corte-madera-town-council": {"cortemadera.gov", "www.cortemadera.gov"},
    "novato-city-council": {"novato.granicus.com"},
    "marin-county-bos": {"marin.granicus.com"},
    "sausalito-city-council": {"sausalito.granicus.com"},
    "san-anselmo-town-council": {"sananselmo-ca.granicus.com"},
}
# The known Granicus document hosts (unverified live in this goal); redirect targets only, for Granicus sources.
GRANICUS_DOC_HOSTS = {"granicus_production_attachments.s3.amazonaws.com", "d3n9y02raazwpg.cloudfront.net"}
ALLOWED_HOSTS = {s: hosts | (GRANICUS_DOC_HOSTS if any("granicus" in h for h in hosts) else set())
                 for s, hosts in OWN_HOSTS.items()}

CHALLENGE_MARKERS = (b"cf-challenge", b"challenge-platform", b"cf_chl_", b"just a moment", b"attention required",
                     b"checking your browser", b"captcha", b"access denied", b"request unsuccessful. incapsula",
                     b"_incapsula_resource", b"are you a robot", b"bot detection")
Fetch = Callable[[str], tuple[int, bytes, str | None]]


class RefusedUrl(ValueError):
    """The URL is not one of the substrate's minutes URLs for the source."""


class Failure(Exception):
    """One document failed; `stop` ends the whole run."""

    def __init__(self, message: str, *, stop: bool = False, status: int | None = None, final_url: str | None = None):
        super().__init__(message)
        self.stop, self.status, self.final_url = stop, status, final_url


@dataclass
class Result:
    attempted: int
    cached: int
    stop_reason: str | None


def http_fetch(url: str) -> tuple[int, bytes, str | None]:
    """One HTTP request; redirects are NOT followed (the caller validates and paces every hop)."""
    import requests  # only the fetch step needs the network stack

    resp = requests.get(url, timeout=60, allow_redirects=False, headers={"User-Agent": USER_AGENT})
    loc = resp.headers.get("Location")
    return resp.status_code, resp.content, urljoin(url, loc) if loc else None


class Pacer:
    """Every request goes through here: at least MIN_INTERVAL_S after the previous one finished."""

    def __init__(self, fetch: Fetch = http_fetch, sleep=time.sleep, now=time.monotonic):
        self._fetch, self._sleep, self._now, self._last = fetch, sleep, now, None

    def __call__(self, url: str) -> tuple[int, bytes, str | None]:
        if self._last is not None and (wait := MIN_INTERVAL_S - (self._now() - self._last)) > 0:
            self._sleep(wait)
        try:
            return self._fetch(url)
        finally:
            self._last = self._now()


def _rows(substrate: Path, source: str) -> list[tuple[str, str, str, str]]:
    """(meeting_id, date, title, minutes_url) for the source's meetings with a minutes URL, newest first."""
    db = sqlite3.connect(f"file:{substrate}?mode=ro", uri=True)
    try:
        found = db.execute(
            "select m.id, m.props, r.props from nodes m join edges e on e.source = m.id and e.rel = 'EVIDENCED_BY' "
            "join nodes r on r.id = e.target where m.type = 'Meeting' and m.id like ? "
            "and json_extract(r.props, '$.record_type') = 'meeting_minutes'", (f"meeting-{source}-%",)).fetchall()
    finally:
        db.close()
    rows = {}
    for mid, mprops, rprops in found:
        m, url = json.loads(mprops), normalize_url(json.loads(rprops).get("preferred_public_url"))
        if url:
            rows.setdefault(mid, (mid, m.get("meeting_date") or "", m.get("title") or "", url))
    return sorted(rows.values(), key=lambda r: r[1], reverse=True)


def _cache_path(raw: Path, source: str, meeting_id: str) -> Path | None:
    d = raw / source / "minutes"
    return next((p for ext in ("pdf", "html", "docx") if (p := d / f"{meeting_id}.{ext}").exists()), None)


def candidates(substrate: Path, source: str, body: str, raw: Path | None = None) -> list[tuple[str, str]]:
    """(meeting_id, url) newest first for meetings of `source` whose normalized body contains `body`, uncached."""
    return [(mid, url) for mid, _, title, url in _rows(substrate, source)
            if body.lower() in normalize_body(source, title)[0].lower()
            and (raw is None or _cache_path(raw, source, mid) is None)]


def _classify(data: bytes) -> str:
    """'pdf' | 'html' | 'challenge' | 'other' (a bot-wall page is never a document)."""
    if data[:5] == b"%PDF-":
        return "pdf"
    if sniff_format(data) == "html":
        return "challenge" if any(m in data.lower() for m in CHALLENGE_MARKERS) else "html"
    return "other"


def fetch_document(source: str, url: str, substrate: Path, request: Fetch | None = None) -> tuple[bytes, str, str]:
    """Fetch one substrate minutes URL (hop by hop, validated and paced) → (bytes, 'pdf'|'html', final_url).

    Raises RefusedUrl for a URL the substrate does not list; Failure for anything uncacheable."""
    url = normalize_url(url)
    if url not in {u for *_, u in _rows(substrate, source)} or urlsplit(url).hostname not in OWN_HOSTS[source]:
        raise RefusedUrl(f"not a substrate minutes URL for {source}: {url}")
    request = request or Pacer()
    for _ in range(MAX_HOPS + 1):
        try:
            status, data, location = request(url)
        except Exception as exc:  # network error: log and skip, no retry
            raise Failure(f"request failed: {exc}", final_url=url) from exc
        kind = _classify(data)
        if status in (403, 429) or kind == "challenge":
            raise Failure(f"stopped: HTTP {status}" + (" bot-wall page" if kind == "challenge" else ""),
                          stop=True, status=status, final_url=url)
        if 300 <= status < 400 and location:
            location = urljoin(url, location)
            host = urlsplit(location).hostname
            if host not in ALLOWED_HOSTS[source]:
                raise Failure(f"redirect host not allowed: {host}", status=status, final_url=url)
            url = location
            continue
        if status != 200:
            raise Failure(f"HTTP {status}", status=status, final_url=url)
        if kind == "other":
            raise Failure("response is not a document", status=status, final_url=url)
        return data, kind, url
    raise Failure(f"more than {MAX_HOPS} redirects", final_url=url)


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_bytes(data)
    tmp.rename(path)


def fetch_indexed(source: str, body: str, substrate: Path, raw: Path, *, limit: int = DEFAULT_LIMIT,
                  fetch: Fetch = http_fetch, sleep=time.sleep, now=time.monotonic) -> Result:
    """Fetch up to `limit` uncached minutes of the matching body; stops the whole run on a block."""
    pacer, log = Pacer(fetch, sleep, now), raw / source / "minutes-fetch-log.jsonl"
    todo, result = candidates(substrate, source, body, raw)[:limit], Result(0, 0, None)
    for mid, url in todo:
        entry = {"meeting_id": mid, "url": url, "final_url": url, "fetched_at": datetime.now(UTC).isoformat()}
        result.attempted += 1
        try:
            data, kind, entry["final_url"] = fetch_document(source, url, substrate, pacer)
            _write_atomic(raw / source / "minutes" / f"{mid}.{kind}", data)
            entry |= {"status": "ok", "http_status": 200, "path": f"{mid}.{kind}",
                      "sha256": hashlib.sha256(data).hexdigest()}
            result.cached += 1
        except Failure as fail:
            entry |= {"status": "failed", "http_status": fail.status, "error": str(fail),
                      "final_url": fail.final_url or url}
            result.stop_reason = str(fail) if fail.stop else None
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
        if result.stop_reason:
            break
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--source", required=True, choices=sorted(SOURCES))
    ap.add_argument("--body", required=True, help="case-insensitive substring of the normalized body")
    ap.add_argument("--substrate", type=Path, default=DEFAULT_SUBSTRATE)
    ap.add_argument("--raw", type=Path, default=DEFAULT_RAW)
    ap.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    args = ap.parse_args(argv)
    result = fetch_indexed(args.source, args.body, args.substrate, args.raw, limit=args.limit)
    print(f"attempted {result.attempted}, cached {result.cached}")
    if result.stop_reason:
        print(f"STOPPED: {result.stop_reason}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
