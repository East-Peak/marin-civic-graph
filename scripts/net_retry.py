"""A bounded retry for transient network failures in the source fetch helpers.

Retried: what a second try can plausibly fix — a timeout, a dropped, refused or
reset connection, an HTTP 5xx, and a 429 whose Retry-After names a wait of at most
RETRY_AFTER_CAP_SECS (it is retried after exactly that wait). Never any other 4xx:
the request itself is wrong, and repeating it only leans on a public server; a 429
with no wait, or a longer one, is a spent quota a retry can't fix. At most ATTEMPTS
tries, backing off BACKOFF_SECS, then twice that; the last failure propagates
unchanged, so callers record it exactly as before. Each fetch's own `timeout=` bounds every wait, and
refresh_weekly's per-step timeout bounds the whole source.

The retry log names the function and the exception type only, never the exception
text, which can carry a URL (a heartbeat URL is a secret).
"""
from __future__ import annotations

import functools
import re
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
RETRY_AFTER_CAP_SECS = 120
sleep = time.sleep  # module-level so tests can stub it

F = TypeVar("F", bound=Callable)


def _http_status(exc: BaseException) -> int | None:
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code
    return getattr(getattr(exc, "response", None), "status_code", None)  # requests.HTTPError


def retry_after_secs(exc: BaseException) -> int | None:
    """The wait a 429 asks for, when it is a whole number of seconds within the cap; else None."""
    if _http_status(exc) != 429:
        return None
    headers = getattr(exc, "headers", None) or getattr(getattr(exc, "response", None), "headers", None) or {}
    raw = str(headers.get("Retry-After", "")).strip()
    # ASCII digits, few enough that int() can't refuse them: anything else (absent, an HTTP
    # date, negative, a fraction, a superscript) is no usable wait, and the 429 stands.
    if not re.fullmatch(r"[0-9]{1,6}", raw):
        return None
    secs = int(raw)
    return secs if secs <= RETRY_AFTER_CAP_SECS else None


def is_transient(exc: BaseException) -> bool:
    status = _http_status(exc)
    if status == 429:
        return retry_after_secs(exc) is not None
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
                    delay = retry_after_secs(exc)
                    if delay is None:
                        delay = (BACKOFF_SECS if backoff is None else backoff) * 2 ** (attempt - 1)
                    print(f"{fn.__qualname__}: transient {type(exc).__name__}; "
                          f"retry {attempt + 1}/{attempts} in {delay:g}s", file=sys.stderr)
                    sleep(delay)
        return wrapper  # type: ignore[return-value]
    return decorate(fn) if fn is not None else decorate  # type: ignore[return-value]
