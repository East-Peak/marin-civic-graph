"""Capture the parity replay corpus from a running Open Marin app.

Spec: docs/specs/2026-07-07-public-product-substrate-design.md §3.

Hits every public serving surface on a live base URL and records normalized
semantic payloads via scripts/parity_core. Entity pages are captured through
the dev-only /api/parity-entity route (requires the server to run with
PARITY_DEBUG=1).

Usage:
  python scripts/parity_capture.py --base-url http://localhost:3000 \
      [--corpus-dir tests/parity/corpus]

Stability probe: every case is fetched twice; if the normalized payloads
differ (timeout fallbacks, plan-dependent ordering) the case is stored with
"stable": false and parity runners must treat it as advisory (spec §3).
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.parity_core import normalize_payload, save_case  # noqa: E402

# ---------------------------------------------------------------------------
# Case lists — mirrors of the live serving surfaces (read: data-queries.ts,
# type-display.ts, search-backend.ts, expand/path routes).
# ---------------------------------------------------------------------------

DATA_CASES: list[tuple[str, str, dict[str, str]]] = [
    ("decisions-default", "san-rafael-decisions-since-2019", {}),
    ("decisions-institution", "san-rafael-decisions-since-2019",
     {"institution_id": "org-san-rafael-city-council"}),
    ("money-default", "money-flows-by-year", {}),
    ("money-10k-2024", "money-flows-by-year", {"min_amount": "10000", "year": "2024"}),
    ("filings-default", "filings-by-person-or-committee", {}),
    ("filings-form700", "filings-by-person-or-committee", {"filing_type": "form_700"}),
    ("officeholders-default", "current-officeholders-form-coverage", {}),
    ("officeholders-sr", "current-officeholders-form-coverage",
     {"jurisdiction_id": "place-san-rafael"}),
    ("agreements-default", "agreements-and-amendments-for-project", {}),
    ("proceedings-default", "legal-proceedings-affecting-local", {}),
    ("proceedings-boyd", "legal-proceedings-affecting-local",
     {"case_id": "case-boyd-v-city-of-san-rafael"}),
    ("evidence-merrydale", "evidence-records-supporting",
     {"target_id": "project-san-rafael-350-merrydale-interim-shelter"}),
    ("pressure-default", "local-pressure-ranking-sr", {}),
    ("campaign-money-30d", "campaign-money-near-decisions", {"window_days": "30"}),
    ("campaign-money-90d", "campaign-money-near-decisions", {"window_days": "90"}),
    ("qa-gaps", "qa-validation-gaps", {}),
]

# All 23 public NodeTypes as URL segments (kebab-case of the type name).
BROWSE_SEGMENTS = [
    "person", "decision", "project", "program", "case", "meeting", "filing",
    "committee", "organization", "money-flow", "seat", "seat-service",
    "election", "candidacy", "agenda-item", "proceeding", "agreement",
    "amendment", "record", "place", "issue", "membership", "economic-interest",
]
BROWSE_SEARCH_CASES = [
    ("person", "colin"),
    ("organization", "marin"),
    ("record", "form"),
]

SEARCH_GOLDEN: list[tuple[str, bool]] = [
    ("kate colin", False), ("kate colin", True),
    ("person-kate-colin", False),
    ("merrydale", False), ("merrydale", True),
    ("350 merrydale", False),
    ("boyd", False),
    ("san rafael city council", False),
    ("library", False),
    ("form 700", False), ("form 700", True),
    ("willdan", False),
    ("housing", False),
    ("gerrod herndon", False),
    ("marin county", False),
    ("canal", False),
    ("shelter", False),
    ("albert park", False),
    ("measure", False),
    ("dominican", False),
]

# (case_name, url segment, slug) — slug is the id minus its prefix, matching
# routeFor(). Includes tier-1, tier-2, and the Record/Place waiver types, plus
# deliberately-warty cases (doc-* Records) so live behavior is pinned as-is.
ENTITY_CASES: list[tuple[str, str, str]] = [
    ("person-kate-colin", "person", "kate-colin"),
    ("project-merrydale", "project", "san-rafael-350-merrydale-interim-shelter"),
    ("case-boyd", "case", "boyd-v-city-of-san-rafael"),
    ("meeting-2010-02-16", "meeting", "2010-02-16-san-rafael-city-council"),
    ("filing-colin-803", "filing", "2025-09-04-kate-colin-form-803"),
    ("committee-eli-hill", "committee", "eli-hill-for-san-rafael-city-council-2022"),
    ("decision-library-call", "decision", "2010-06-08-san-rafael-library-special-call"),
    ("program-csl", "program", "csl-building-forward"),
    ("org-entrada", "organization", "250-entrada-drive-llc"),
    ("moneyflow-sample", "money-flow", "1242561-Ckk8lh1b9YWc"),
    ("record-doc-prefixed", "record", "2023-12-14-implementation-plan"),
    ("place-merrydale-road", "place", "350-merrydale-road"),
    ("seatservice-fredericks", "seat-service", "alice-fredericks-tiburon-2022"),
]

EXPAND_CASES: list[tuple[str, dict[str, str]]] = [
    ("kate-colin-hop1", {"focus": "person-kate-colin", "hop": "1"}),
    ("kate-colin-hop2", {"focus": "person-kate-colin", "hop": "2"}),
    ("merrydale-hop1", {"focus": "project-san-rafael-350-merrydale-interim-shelter", "hop": "1"}),
    ("merrydale-hop1-excl", {"focus": "project-san-rafael-350-merrydale-interim-shelter",
                             "hop": "1", "excluded_node_types": "MoneyFlow,Filing"}),
    ("boyd-hop1-universals", {"focus": "case-boyd-v-city-of-san-rafael", "hop": "1",
                              "include_universals": "true"}),
    ("org-entrada-hop1", {"focus": "org-250-entrada-drive-llc", "hop": "1"}),
]

PATH_CASES: list[tuple[str, dict[str, str]]] = [
    ("colin-to-merrydale", {"from": "person-kate-colin",
                            "to": "project-san-rafael-350-merrydale-interim-shelter"}),
    ("colin-to-boyd", {"from": "person-kate-colin", "to": "case-boyd-v-city-of-san-rafael"}),
    ("colin-to-boyd-loose", {"from": "person-kate-colin",
                             "to": "case-boyd-v-city-of-san-rafael", "loose": "true"}),
    ("unconnected", {"from": "seat-belvedere-seat-1",
                     "to": "doc-2023-12-14-implementation-plan"}),
]

# ---------------------------------------------------------------------------


def fetch(base_url: str, path: str, params: dict[str, str]) -> tuple[int, dict]:
    qs = ("?" + urllib.parse.urlencode(params)) if params else ""
    url = f"{base_url}{path}{qs}"
    req = urllib.request.Request(url, headers={"accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        try:
            return e.code, json.loads(body)
        except json.JSONDecodeError:
            return e.code, {"raw": body[:500]}


def capture_case(
    corpus_dir: str,
    base_url: str,
    surface: str,
    case_name: str,
    path: str,
    params: dict[str, str],
) -> bool:
    status1, payload1 = fetch(base_url, path, params)
    status2, payload2 = fetch(base_url, path, params)
    stable = (
        status1 == status2
        and normalize_payload(surface, payload1) == normalize_payload(surface, payload2)
    )
    save_case(
        corpus_dir,
        surface,
        case_name,
        {
            "request": {"method": "GET", "url_path": path, "params": params},
            "http_status": status1,
            "payload": payload1,
            "stable": stable,
        },
    )
    return stable


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://localhost:3000")
    ap.add_argument("--corpus-dir", default="tests/parity/corpus")
    args = ap.parse_args()

    cases: list[tuple[str, str, str, dict[str, str]]] = []
    for name, slug, params in DATA_CASES:
        cases.append(("data", name, f"/api/data/{slug}", params))
    for seg in BROWSE_SEGMENTS:
        cases.append(("browse", f"{seg}-page1", f"/api/browse/{seg}", {}))
    for seg, q in BROWSE_SEARCH_CASES:
        cases.append(("browse", f"{seg}-q-{q}", f"/api/browse/{seg}", {"q": q}))
    for q, include_records in SEARCH_GOLDEN:
        suffix = "-records" if include_records else ""
        name = q.replace(" ", "-").replace("&", "and") + suffix
        params = {"q": q}
        if include_records:
            params["include_records"] = "true"
        cases.append(("search", name, "/api/search", params))
    for name, seg, slug in ENTITY_CASES:
        cases.append(("entity", name, f"/api/parity-entity/{seg}/{slug}", {}))
    for name, params in EXPAND_CASES:
        cases.append(("expand", name, "/api/expand", params))
    for name, params in PATH_CASES:
        cases.append(("path", name, "/api/path", params))
    cases.append(("status", "status", "/api/status", {}))

    unstable: list[str] = []
    for surface, name, path, params in cases:
        stable = capture_case(args.corpus_dir, args.base_url, surface, name, path, params)
        flag = "" if stable else "  [UNSTABLE]"
        print(f"  {surface}/{name}: captured{flag}")
        if not stable:
            unstable.append(f"{surface}/{name}")

    print(f"\n{len(cases)} cases captured to {args.corpus_dir}")
    if unstable:
        print(f"{len(unstable)} unstable (advisory-only): {', '.join(unstable)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
