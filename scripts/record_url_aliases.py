"""Reviewed Record-URL aliases: an existing Record is the artifact a page now links at another url.

A city's files get re-hosted (Lakeport's moved twice within one storage bucket). The no-overwrite load
(scripts/guarded_load.py) refuses a meeting whose established Record's `source_url` is not the url the page
links, and it never re-points a Record. An entry here, built by scripts/record_url_alias_evidence.py from bytes
fetched through the robots gate, lets the load resolve that artifact to the Record it already has:

    format: 1
    sources:
      <source id>:
      - record_id: <the existing Record>
        art: <the adapter's artifact name: agenda, packet, minutes, ...>
        established_url: <the Record's source_url when it was reviewed>
        page_url: <the url the page links now>
        evidence: {kind: identical_bytes, sha256: <both urls' bytes>}
                | {kind: reviewed_variant, established_sha256: .., page_sha256: .., rationale: <one line>}
        reviewed: 'YYYY-MM-DD'

The load matches reviewed url identity, never bytes: it does not fetch. A capture pins this file's sha256 at
stage time (only for a source with entries), and a load under a different file holds. Anything malformed,
duplicated or ambiguous refuses to load at all; a missing file is no aliases.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml

FORMAT = 1
PATH = "registry/record-url-aliases.yaml"
KEYS = ("record_id", "art", "established_url", "page_url", "evidence", "reviewed")
ARTS = ("agenda", "packet", "minutes", "video", "captions", "mp3", "mp4")  # guarded_load.ARTIFACT_KINDS
EVIDENCE = {"identical_bytes": ("kind", "sha256"),
            "reviewed_variant": ("kind", "established_sha256", "page_sha256", "rationale")}
SHA_RE = re.compile(r"[0-9a-f]{64}")


class AliasError(ValueError):
    """The alias list is unreadable, malformed or ambiguous: nothing in it may be used."""


@dataclass(frozen=True)
class Aliases:
    sha256: str | None
    by_source: dict[str, list[dict]] = field(default_factory=dict)

    def entries(self, source_id: str) -> list[dict]:
        return list(self.by_source.get(source_id, ()))


class _UniqueKeyLoader(yaml.SafeLoader):
    """safe_load keeps the last of two equal keys; an alias list with two must not load at all."""

    def construct_mapping(self, node, deep=False):
        keys = [self.construct_object(k, deep=deep) for k, _ in node.value]
        dupes = sorted({str(k) for k in keys if keys.count(k) > 1})
        if dupes:
            raise AliasError(f"duplicate keys {dupes}")
        return super().construct_mapping(node, deep=deep)


def load(root: Path) -> Aliases:
    path = Path(root) / PATH
    if not path.exists():
        return Aliases(None)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise AliasError(f"{PATH} is unreadable: {exc}") from None
    return parse(raw)


def parse(raw: bytes) -> Aliases:
    """The list in `raw` (the file's bytes), validated; its hash is the version a capture pins."""
    try:
        body = yaml.load(raw, Loader=_UniqueKeyLoader)  # noqa: S506 (a SafeLoader)
    except AliasError as exc:
        raise AliasError(f"{PATH}: {exc}") from None
    except yaml.YAMLError as exc:
        raise AliasError(f"{PATH} is unreadable: {exc}") from None
    if not isinstance(body, dict) or set(body) != {"format", "sources"}:
        raise AliasError(f"{PATH} must have exactly the keys format and sources")
    if body["format"] != FORMAT:
        raise AliasError(f"{PATH} is not format {FORMAT}")
    if not isinstance(body["sources"], dict):
        raise AliasError(f"{PATH}: sources must map a source id to its entries")
    for source_id, entries in body["sources"].items():
        _validate(source_id, entries)
    return Aliases(hashlib.sha256(raw).hexdigest(), {s: list(e) for s, e in body["sources"].items()})


def binding(root: Path, source_id: str) -> dict | None:
    """What a capture of `source_id` pins: the file and its hash, or None when the source has no entries."""
    aliases = load(root)
    return {"path": PATH, "sha256": aliases.sha256} if aliases.entries(source_id) else None


def _validate(source_id, entries) -> None:
    if not isinstance(source_id, str) or not source_id:
        raise AliasError(f"{PATH}: {source_id!r} is not a source id")
    if not isinstance(entries, list) or not entries:
        raise AliasError(f"{PATH}: {source_id} has no entries")
    pairs, page_owner, of_record = set(), {}, {}
    for e in entries:
        _validate_entry(source_id, e)
        pair = (e["record_id"], e["page_url"])
        if pair in pairs:
            raise AliasError(f"{PATH}: {source_id}: {pair} is listed twice")
        pairs.add(pair)
        if page_owner.setdefault(e["page_url"], e["record_id"]) != e["record_id"]:
            raise AliasError(f"{PATH}: {source_id}: {e['page_url']} is aliased to two Records "
                             f"({page_owner[e['page_url']]}, {e['record_id']})")
        if of_record.setdefault(e["record_id"], (e["art"], e["established_url"])) != (e["art"], e["established_url"]):
            raise AliasError(f"{PATH}: {source_id}: {e['record_id']} must have one art and one established url")
    established = {url: rid for rid, (_, url) in of_record.items()}
    for url, rid in page_owner.items():
        if url in established:
            raise AliasError(f"{PATH}: {source_id}: {url} (a page url of {rid}) is the established url of "
                             f"{established[url]}")


def _validate_entry(source_id: str, e) -> None:
    where = f"{PATH}: {source_id}: {e.get('record_id') if isinstance(e, dict) else e!r}"
    if not isinstance(e, dict) or not all(isinstance(k, str) for k in e) or sorted(e) != sorted(KEYS):
        raise AliasError(f"{where}: an entry has exactly the keys {', '.join(KEYS)}")
    if not (isinstance(e["record_id"], str) and e["record_id"].startswith("record-")):
        raise AliasError(f"{where}: record_id must be a Record id")
    if not isinstance(e["art"], str) or e["art"] not in ARTS:
        raise AliasError(f"{where}: art must be one of {', '.join(ARTS)}")
    for key in ("established_url", "page_url"):
        if not (isinstance(e[key], str) and re.fullmatch(r"https://[^\s]+", e[key])):
            raise AliasError(f"{where}: {key} must be an https url")
    if e["established_url"] == e["page_url"]:
        raise AliasError(f"{where}: the same url on both sides is not an alias")
    try:
        ok = isinstance(e["reviewed"], str) and date.fromisoformat(e["reviewed"]).isoformat() == e["reviewed"]
    except ValueError:
        ok = False
    if not ok:
        raise AliasError(f"{where}: reviewed must be a quoted YYYY-MM-DD date")
    ev = e["evidence"]
    keys = EVIDENCE.get(ev["kind"]) if isinstance(ev, dict) and isinstance(ev.get("kind"), str) else None
    if keys is None or not all(isinstance(k, str) for k in ev) or sorted(ev) != sorted(keys) \
            or not all(isinstance(ev[k], str) and SHA_RE.fullmatch(ev[k]) for k in keys if k.endswith("sha256")):
        raise AliasError(f"{where}: evidence must be {{kind: identical_bytes, sha256}} or "
                         "{kind: reviewed_variant, established_sha256, page_sha256, rationale}")
    if ev["kind"] == "reviewed_variant" and (ev["established_sha256"] == ev["page_sha256"]
                                             or not (isinstance(ev["rationale"], str) and ev["rationale"].strip())):
        raise AliasError(f"{where}: evidence: a reviewed variant has two different hashes and a rationale")
