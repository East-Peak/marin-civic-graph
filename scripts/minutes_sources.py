#!/usr/bin/env python3
"""Minutes coverage: the explicit source map. No source is found by guessing from a name.

For each source: its registry id (also its raw directory, `<raw>/<id>/minutes/`), the meeting-id prefix as the
substrate holds it (Tiburon's is `tiburon-town-council-granicus`, Mill Valley's `mill-valley-committees`), the
meeting-id suffix shapes it uses (`numeric`, `slug`, `date-row`; San Rafael also has date-first ids), and the exact
hosts its minutes documents may be requested from. A host rule is an exact host plus, for a shared cloud host
(Google Cloud Storage, S3, CloudFront), a required path prefix that names the publisher; every rule records its
evidence. A redirect target joins a source only by a change to this file.

Authorization (decisions/2026-10-15-granicus-minutes-fetching.md, reconfirmed 2026-11-14): `*.granicus.com` and
the Granicus attachment rules marked `authority="granicus"` are fetched without consulting robots; every other host
must be admitted by robots.txt for our agent (minutes_transport). marincounty.gov and novato.gov are refused outright.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import unquote, urlsplit

MINUTES_EXTENSIONS = ("pdf", "html", "htm", "docx")

SHAPES = {
    "numeric": r"\d+",
    "slug": r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*",
    "date-row": r"\d{4}-\d{2}-\d{2}-row-\d+",
}
OFF_LIMITS = ("marincounty.gov", "novato.gov")  # bot walls: never automated, never worked around
SHARED_CLOUD = (".amazonaws.com", ".cloudfront.net", ".googleapis.com", ".googleusercontent.com",
                ".blob.core.windows.net", ".azureedge.net")
GRANICUS = "granicus.com"


class SourceMapError(ValueError):
    pass


def _host(host: str) -> str:
    return (host or "").lower().rstrip(".")


def off_limits(host: str) -> bool:
    h = _host(host)
    return any(h == d or h.endswith("." + d) for d in OFF_LIMITS)


def shared_cloud(host: str) -> bool:
    h = _host(host)
    return any(h.endswith(s) or h == s[1:] for s in SHARED_CLOUD)


def host_family(host: str) -> str:
    """The unit of pacing and of stops: Granicus is one family; a shared cloud host is its own exact host (a stop on
    one bucket host stops every source on it); any other host is its registrable domain (the last two labels)."""
    h = _host(host)
    if h == GRANICUS or h.endswith("." + GRANICUS):
        return GRANICUS
    if shared_cloud(h):
        return h
    return ".".join(h.split(".")[-2:])


def _clean_path(path: str) -> bool:
    return not any(seg in (".", "..") for seg in unquote(path).split("/"))


@dataclass(frozen=True)
class HostRule:
    host: str
    path_prefix: str | None
    evidence: str
    authority: str = "robots"  # "robots" (robots.txt must admit) or "granicus" (the 2026-10-15 decision)

    def admits(self, url: str) -> bool:
        parts = urlsplit(url)
        if parts.scheme != "https" or _host(parts.hostname or "") != self.host:
            return False
        if self.path_prefix is None:
            return True
        return _clean_path(parts.path) and parts.path.startswith(self.path_prefix)


@dataclass(frozen=True)
class Source:
    id: str
    jurisdiction: str
    prefix: str
    shapes: tuple[str, ...]
    doc_hosts: tuple[HostRule, ...]
    redirect_hosts: tuple[HostRule, ...] = ()
    extra_id_patterns: tuple[str, ...] = ()
    _rx: re.Pattern = field(init=False, repr=False, compare=False)

    def __post_init__(self):
        alts = [rf"meeting-{re.escape(self.prefix)}-(?:{SHAPES[s]})" for s in self.shapes] + list(
            self.extra_id_patterns)
        object.__setattr__(self, "_rx", re.compile("(?:" + "|".join(alts) + ")"))

    @property
    def raw_dir(self) -> str:
        return self.id

    @property
    def rules(self) -> tuple[HostRule, ...]:
        return self.doc_hosts + self.redirect_hosts

    def matches(self, meeting_id: str) -> bool:
        return self._rx.fullmatch(meeting_id or "") is not None

    def file_meeting_id(self, name: str) -> str | None:
        """The meeting id a cached file `<meeting_id>.<ext>` names, if it has this source's shape."""
        stem, dot, ext = name.rpartition(".")
        return stem if dot and ext in MINUTES_EXTENSIONS and self.matches(stem) else None

    def admits(self, url: str) -> bool:
        """An initial document URL or a redirect hop this source may request."""
        return any(r.admits(url) for r in self.rules)

    def admits_initial(self, url: str) -> bool:
        return any(r.admits(url) for r in self.doc_hosts)

    def robots_hosts(self) -> set[str]:
        return {r.host for r in self.rules if r.authority == "robots"}


def granicus_authorized(url: str, rules: tuple[HostRule, ...] = ()) -> bool:
    parts = urlsplit(url)
    h = _host(parts.hostname or "")
    if parts.scheme == "https" and h.endswith("." + GRANICUS):
        return True
    return any(r.authority == "granicus" and r.admits(url) for r in rules)


def validate(source: Source) -> None:
    for r in source.rules:
        if r.host != _host(r.host) or not r.host:
            raise SourceMapError(f"{source.id}: host must be lower-case and exact: {r.host!r}")
        if off_limits(r.host):
            raise SourceMapError(f"{source.id}: {r.host} is refused outright")
        if not r.evidence.strip():
            raise SourceMapError(f"{source.id}: {r.host} has no recorded evidence")
        if r.path_prefix is not None and not (r.path_prefix.startswith("/") and r.path_prefix.endswith("/")
                                              and _clean_path(r.path_prefix)):
            raise SourceMapError(f"{source.id}: path prefix must be a whole /segment/ path: {r.path_prefix!r}")
        if shared_cloud(r.host) and not r.path_prefix:
            raise SourceMapError(f"{source.id}: {r.host} is a shared cloud host; a publisher path prefix is required")
        if r.authority not in ("robots", "granicus"):
            raise SourceMapError(f"{source.id}: unknown authority {r.authority!r}")
        if r.authority == "granicus" and not (r.host.endswith("." + GRANICUS) or shared_cloud(r.host)):
            raise SourceMapError(f"{source.id}: only Granicus hosts or its attachment buckets carry its authority")
    for s in source.shapes:
        if s not in SHAPES:
            raise SourceMapError(f"{source.id}: unknown id shape {s!r}")


SUBSTRATE_URL = "the substrate's own preferred_public_url values for this source's minutes Records"


def _granicus(sub: str) -> HostRule:
    return HostRule(f"{sub}.granicus.com", None, SUBSTRATE_URL, authority="granicus")


_SOURCES = (
    Source("san-anselmo-town-council", "San Anselmo", "san-anselmo-town-council", ("numeric",),
           (_granicus("sananselmo-ca"),)),
    Source("corte-madera-town-council", "Corte Madera", "corte-madera-town-council", ("numeric",),
           (HostRule("cortemadera.gov", None, SUBSTRATE_URL), HostRule("www.cortemadera.gov", None, SUBSTRATE_URL))),
    Source("tiburon-town-council-granicus", "Tiburon", "tiburon-town-council-granicus", ("numeric",),
           (_granicus("townoftiburon"),)),
    Source("novato-city-council", "Novato", "novato-city-council", ("numeric",), (_granicus("novato"),)),
    Source("marin-county-bos", "Marin County", "marin-county-bos", ("numeric",), (_granicus("marin"),)),
    Source("sausalito-city-council", "Sausalito", "sausalito-city-council", ("numeric",), (_granicus("sausalito"),)),
    Source("mill-valley-committees", "Mill Valley", "mill-valley-committees", ("numeric",),
           (HostRule("cityofmillvalley.org", "/AgendaCenter/ViewFile/Minutes/", SUBSTRATE_URL),)),
    Source("fairfax-town-council", "Fairfax", "fairfax-town-council", ("slug",),
           (HostRule("storage.googleapis.com", "/proudcity/fairfaxca/",
                     SUBSTRATE_URL + "; the ProudCity bucket's fairfaxca folder (the town's CMS vendor)"),)),
    Source("belvedere-city-council", "Belvedere", "belvedere-city-council", ("slug",),
           (HostRule("storage.googleapis.com", "/proudcity/belvedereca/",
                     SUBSTRATE_URL + "; the ProudCity bucket's belvedereca folder (the city's CMS vendor)"),)),
    Source("ross-town-council", "Ross", "ross-town-council", ("date-row", "slug"),
           (HostRule("www.townofrossca.gov", "/sites/default/files/fileattachments/", SUBSTRATE_URL),)),
    # San Rafael's minutes Records carry no URL (substrate as of 2026-11-16): nothing here is ever requested.
    Source("san-rafael-city-council", "San Rafael", "san-rafael-city-council", ("slug",), (),
           extra_id_patterns=(r"meeting-\d{4}-\d{2}-\d{2}-san-rafael-city-council(?:-[a-z0-9]+)*",)),
)
SOURCE_MAP: dict[str, Source] = {s.id: s for s in _SOURCES}
for _s in _SOURCES:
    validate(_s)


def source_of(meeting_id: str) -> str | None:
    hits = [s.id for s in _SOURCES if s.matches(meeting_id)]
    if len(hits) > 1:
        raise SourceMapError(f"{meeting_id} matches several sources: {hits}")
    return hits[0] if hits else None
