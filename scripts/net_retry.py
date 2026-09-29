"""A bounded retry for transient network failures in the source fetch helpers.

Retried: what a second try can plausibly fix — a timeout, a dropped, refused or
reset connection, an HTTP 5xx. Never a 4xx: the request itself is wrong, and
repeating it only leans on a public server. At most ATTEMPTS tries, backing off
BACKOFF_SECS, then twice that; the last failure propagates unchanged, so callers
record it exactly as before. Each fetch's own `timeout=` bounds every wait, and
refresh_weekly's per-step timeout bounds the whole source.

The retry log names the function and the exception type only, never the exception
text, which can carry a URL (a heartbeat URL is a secret).
"""
from __future__ import annotations

import functools
import sys
import time
import urllib.error
from typing import Callable, TypeVar

try:
    import requests
except ImportError:  # the urllib-only adapters don't need it
    requests = None

ATTEMPTS = 3
BACKOFF_SECS = 2.0
sleep = time.sleep  # module-level so tests can stub it

F = TypeVar("F", bound=Callable)


def _http_status(exc: BaseException) -> int | None:
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code
    return getattr(getattr(exc, "response", None), "status_code", None)  # requests.HTTPError


def is_transient(exc: BaseException) -> bool:
    status = _http_status(exc)
    if status is not None:
        return 500 <= status <= 599
    if isinstance(exc, urllib.error.URLError):  # urlopen wraps the socket error it hit
        return isinstance(exc.reason, BaseException) and is_transient(exc.reason)
    if requests is not None and isinstance(exc, (requests.Timeout, requests.ConnectionError)):
        return True
    return isinstance(exc, (TimeoutError, ConnectionError))


def retry_transient(fn: F | None = None, *, attempts: int = ATTEMPTS, backoff: float | None = None) -> F:
    """Decorate a fetch so a transient failure is retried, boundedly; usable bare or with arguments."""
    def decorate(fn: F) -> F:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            for attempt in range(1, attempts + 1):
                try:
                    return fn(*args, **kwargs)
                except Exception as exc:
                    if attempt == attempts or not is_transient(exc):
                        raise
                    delay = (BACKOFF_SECS if backoff is None else backoff) * 2 ** (attempt - 1)
                    print(f"{fn.__qualname__}: transient {type(exc).__name__}; "
                          f"retry {attempt + 1}/{attempts} in {delay:g}s", file=sys.stderr)
                    sleep(delay)
        return wrapper  # type: ignore[return-value]
    return decorate(fn) if fn is not None else decorate  # type: ignore[return-value]
