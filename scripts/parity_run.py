"""Replay the committed parity corpus against a running Open Marin app."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, TextIO

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.parity_core import apply_deltas, diff_case, iter_corpus, load_deltas  # noqa: E402

Fetcher = Callable[[str, dict[str, Any]], tuple[int, dict[str, Any]]]


def fetch_case(base_url: str, request: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    method = request.get("method", "GET")
    if method != "GET":
        raise ValueError(f"unsupported parity request method: {method}")

    url_path = request["url_path"]
    params = request.get("params") or {}
    query = urllib.parse.urlencode(params)
    url = f"{base_url.rstrip('/')}{url_path}"
    if query:
        url = f"{url}?{query}"

    req = urllib.request.Request(url, headers={"accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, _decode_json_body(exc.read())


def fetch_page_case(
    base_url: str, request: dict[str, Any], expected_payload: dict[str, Any]
) -> tuple[int, dict[str, Any]]:
    # Pages surface: recompute the marker booleans stored at capture time from
    # the live HTML — never diff raw markup.
    url = f"{base_url.rstrip('/')}{request['url_path']}"
    req = urllib.request.Request(url, headers={"accept": "text/html"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            html, status = resp.read().decode("utf-8", errors="replace"), resp.status
    except urllib.error.HTTPError as exc:
        html, status = exc.read().decode("utf-8", errors="replace"), exc.code
    lowered = html.lower()
    markers = {m: (m.lower() in lowered) for m in expected_payload.get("markers", {})}
    payload = {
        "markers": markers,
        "error_markers": (
            "application error" in lowered or "internal server error" in lowered
        ),
    }
    return status, payload


def run_parity(
    *,
    base_url: str,
    corpus_dir: str | Path,
    surfaces: set[str] | None,
    allow_delta: str | Path,
    fetcher: Fetcher = fetch_case,
    out: TextIO | None = None,
) -> int:
    output = out or sys.stdout
    deltas = load_deltas(allow_delta)
    hard_failures = 0

    for surface, case_name, expected_case in iter_corpus(corpus_dir):
        if surfaces is not None and surface not in surfaces:
            continue

        if surface == "pages":
            status, payload = fetch_page_case(
                base_url, expected_case["request"], expected_case["payload"]
            )
        else:
            status, payload = fetcher(base_url, expected_case["request"])
        mismatches = diff_case(expected_case, payload, status)
        errors, warnings = apply_deltas(surface, case_name, mismatches, deltas)

        if errors:
            hard_failures += 1
            print(f"FAIL {surface}/{case_name}", file=output)
            for error in errors:
                print(f"  {error}", file=output)
        elif warnings:
            print(f"WARN(delta) {surface}/{case_name}", file=output)
            for warning in warnings:
                print(f"  {warning}", file=output)
        else:
            print(f"PASS {surface}/{case_name}", file=output)

    return 1 if hard_failures else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--corpus-dir", default="tests/parity/corpus")
    parser.add_argument("--surfaces", default="all")
    parser.add_argument("--allow-delta", default="tests/parity/approved-deltas.yaml")
    args = parser.parse_args(argv)

    return run_parity(
        base_url=args.base_url,
        corpus_dir=args.corpus_dir,
        surfaces=_parse_surfaces(args.surfaces),
        allow_delta=args.allow_delta,
    )


def _decode_json_body(body: bytes) -> dict[str, Any]:
    text = body.decode("utf-8", errors="replace")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {"raw": text[:500]}
    if not isinstance(parsed, dict):
        return {"raw": parsed}
    return parsed


def _parse_surfaces(raw: str) -> set[str] | None:
    if raw.strip().lower() == "all":
        return None
    surfaces = {part.strip() for part in raw.split(",") if part.strip()}
    if not surfaces:
        raise ValueError("--surfaces must be 'all' or a comma list")
    return surfaces


if __name__ == "__main__":
    raise SystemExit(main())
