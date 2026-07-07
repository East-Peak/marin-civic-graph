from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Iterable


DRIFT_KEYS = {"built_at", "expires_at", "signed_url"}
STATUS_DRIFT_KEYS = {"ingest_at"}
SURFACES = {"search", "browse", "data", "entity", "expand", "path", "status"}
MAX_MISMATCHES = 20


def normalize_payload(surface: str, payload: dict[str, Any]) -> dict[str, Any]:
    if surface not in SURFACES:
        raise ValueError(f"unknown parity surface: {surface}")
    if not isinstance(payload, dict):
        raise TypeError("payload must be a dict")

    strip_keys = set(DRIFT_KEYS)
    if surface == "status":
        strip_keys.update(STATUS_DRIFT_KEYS)

    normalized = _strip_keys(payload, strip_keys)

    if surface == "entity":
        _sort_list_key(normalized, "neighbors", ("id",))
        _sort_list_key(normalized, "edges", ("source", "target", "type"))
    elif surface == "expand":
        _sort_list_key(normalized, "nodes", ("id",))
        _sort_list_key(normalized, "edges", ("source", "target", "type"))

    return normalized


def save_case(
    corpus_dir: str | Path,
    surface: str,
    case_name: str,
    case: dict[str, Any],
) -> Path:
    path = _case_path(corpus_dir, surface, case_name)
    path.parent.mkdir(parents=True, exist_ok=True)

    stored_case = {
        "request": copy.deepcopy(case["request"]),
        "http_status": case["http_status"],
        "payload": normalize_payload(surface, case["payload"]),
    }
    path.write_text(json.dumps(stored_case, indent=2, sort_keys=True) + "\n")
    return path


def load_case(
    corpus_dir: str | Path,
    surface: str,
    case_name: str,
) -> dict[str, Any]:
    path = _case_path(corpus_dir, surface, case_name)
    loaded = json.loads(path.read_text())
    loaded["_surface"] = surface
    loaded["_case"] = _case_stem(case_name)
    return loaded


def iter_corpus(corpus_dir: str | Path) -> Iterable[tuple[str, str, dict[str, Any]]]:
    root = Path(corpus_dir)
    if not root.exists():
        return

    for surface_dir in sorted((path for path in root.iterdir() if path.is_dir()), key=lambda p: p.name):
        surface = surface_dir.name
        for case_path in sorted(surface_dir.glob("*.json"), key=lambda p: p.name):
            case_name = case_path.stem
            yield surface, case_name, load_case(root, surface, case_name)


def diff_case(
    expected_case: dict[str, Any],
    actual_payload: dict[str, Any],
    actual_status: int,
) -> list[str]:
    surface = expected_case.get("_surface") or expected_case.get("surface")
    if not surface:
        raise KeyError("expected_case must include _surface or surface")

    mismatches: list[str] = []
    expected_status = expected_case["http_status"]
    if expected_status != actual_status:
        mismatches.append(f"status mismatch: expected {expected_status}, got {actual_status}")

    expected_payload = normalize_payload(surface, expected_case["payload"])
    normalized_actual = normalize_payload(surface, actual_payload)
    _diff_value("$", expected_payload, normalized_actual, mismatches)

    if len(mismatches) <= MAX_MISMATCHES:
        return mismatches
    return mismatches[: MAX_MISMATCHES - 1] + [
        f"... truncated after {MAX_MISMATCHES} mismatches"
    ]


def load_deltas(path: str | Path) -> list[dict[str, str]]:
    delta_path = Path(path)
    if not delta_path.exists():
        return []

    text = delta_path.read_text()
    if not text.strip():
        return []

    try:
        import yaml  # type: ignore[import-not-found]
    except ImportError:
        parsed = _parse_tiny_delta_yaml(text)
    else:
        parsed = yaml.safe_load(text)

    return _validate_deltas(parsed)


def apply_deltas(
    surface: str,
    case_name: str,
    mismatches: Iterable[str],
    deltas: Iterable[dict[str, str]],
) -> tuple[list[str], list[str]]:
    mismatch_list = list(mismatches)
    if not mismatch_list:
        return [], []

    matching_delta = next(
        (
            delta
            for delta in deltas
            if delta["surface"] == surface and delta["case"] == case_name
        ),
        None,
    )
    if matching_delta is None:
        return mismatch_list, []

    reason = matching_delta["reason"]
    warnings = [
        f"approved delta for {surface}/{case_name} ({reason}): {mismatch}"
        for mismatch in mismatch_list
    ]
    return [], warnings


def _strip_keys(value: Any, strip_keys: set[str]) -> Any:
    if isinstance(value, dict):
        return {
            key: _strip_keys(child, strip_keys)
            for key, child in value.items()
            if key not in strip_keys
        }
    if isinstance(value, list):
        return [_strip_keys(item, strip_keys) for item in value]
    return copy.deepcopy(value)


def _sort_list_key(payload: dict[str, Any], key: str, fields: tuple[str, ...]) -> None:
    if isinstance(payload.get(key), list):
        payload[key] = sorted(payload[key], key=lambda item: _sort_tuple(item, fields))


def _sort_tuple(item: Any, fields: tuple[str, ...]) -> tuple[str, ...]:
    if not isinstance(item, dict):
        return tuple("" for _ in fields)
    return tuple("" if item.get(field) is None else str(item.get(field)) for field in fields)


def _case_path(corpus_dir: str | Path, surface: str, case_name: str) -> Path:
    filename = case_name if str(case_name).endswith(".json") else f"{case_name}.json"
    return Path(corpus_dir) / surface / filename


def _case_stem(case_name: str) -> str:
    return Path(case_name).stem if case_name.endswith(".json") else case_name


def _diff_value(path: str, expected: Any, actual: Any, mismatches: list[str]) -> None:
    if isinstance(expected, dict) and isinstance(actual, dict):
        expected_keys = set(expected)
        actual_keys = set(actual)
        for key in sorted(expected_keys - actual_keys, key=str):
            mismatches.append(f"{_path_key(path, key)}: missing key")
        for key in sorted(actual_keys - expected_keys, key=str):
            mismatches.append(f"{_path_key(path, key)}: extra key")
        for key in sorted(expected_keys & actual_keys, key=str):
            _diff_value(_path_key(path, key), expected[key], actual[key], mismatches)
        return

    if isinstance(expected, list) and isinstance(actual, list):
        if len(expected) != len(actual):
            mismatches.append(
                f"{path}: length mismatch: expected {len(expected)}, got {len(actual)}"
            )
        for index, (expected_item, actual_item) in enumerate(zip(expected, actual)):
            _diff_value(f"{path}[{index}]", expected_item, actual_item, mismatches)
        return

    if expected != actual:
        mismatches.append(
            f"{path}: expected {_format_json(expected)}, got {_format_json(actual)}"
        )


def _path_key(path: str, key: Any) -> str:
    if isinstance(key, str) and key.replace("_", "").replace("-", "").isalnum():
        return f"{path}.{key}"
    return f"{path}[{json.dumps(key, sort_keys=True)}]"


def _format_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True)


def _validate_deltas(parsed: Any) -> list[dict[str, str]]:
    if parsed is None:
        return []
    if not isinstance(parsed, list):
        raise ValueError("approved deltas must be a YAML list")

    deltas: list[dict[str, str]] = []
    required_keys = {"surface", "case", "reason"}
    for index, item in enumerate(parsed):
        if not isinstance(item, dict):
            raise ValueError(f"delta {index} must be a mapping")
        if set(item) != required_keys:
            raise ValueError(
                f"delta {index} must contain exactly surface, case, and reason"
            )
        delta = {key: item[key] for key in sorted(required_keys)}
        if not all(isinstance(value, str) for value in delta.values()):
            raise ValueError(f"delta {index} values must be strings")
        deltas.append(
            {
                "surface": delta["surface"],
                "case": delta["case"],
                "reason": delta["reason"],
            }
        )
    return deltas


def _parse_tiny_delta_yaml(text: str) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    current: dict[str, str] | None = None

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        if raw_line.startswith("- "):
            current = {}
            entries.append(current)
            remainder = raw_line[2:].strip()
            if remainder:
                key, value = _parse_delta_key_value(remainder, line_number)
                current[key] = value
            continue
        if raw_line.startswith("  ") and current is not None:
            key, value = _parse_delta_key_value(raw_line.strip(), line_number)
            current[key] = value
            continue
        raise ValueError(f"unsupported approved-deltas YAML at line {line_number}")

    return entries


def _parse_delta_key_value(line: str, line_number: int) -> tuple[str, str]:
    if ":" not in line:
        raise ValueError(f"expected key/value at line {line_number}")
    key, raw_value = line.split(":", 1)
    key = key.strip()
    if key not in {"surface", "case", "reason"}:
        raise ValueError(f"unsupported approved-deltas key {key!r} at line {line_number}")
    value = raw_value.strip()
    if not value:
        raise ValueError(f"missing approved-deltas value at line {line_number}")
    return key, _parse_tiny_scalar(value)


def _parse_tiny_scalar(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value
