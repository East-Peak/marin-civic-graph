"""One lock per graph target, shared by every checkout: writers that must not overlap on a graph take it.

The run lock (scripts/run_lock.py) belongs to a checkout's data/ingest-runs, so two worktrees pointed at one Neo4j
hold two different run locks. This lock is named by the target itself (host and port; a fake graph by its
directory) and lives outside any repo (~/.open-marin/locks/, or $OPEN_MARIN_LOCK_DIR), so every checkout's writers
meet on it. The AgendaItem writers take it: the weekly agenda-items stage and the legacy extractor. A held lock is
refused at once, never waited on.
"""
from __future__ import annotations

import fcntl
import hashlib
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from urllib.parse import urlsplit

LOCK_DIR_ENV = "OPEN_MARIN_LOCK_DIR"
DEFAULT_LOCK_DIR = Path.home() / ".open-marin" / "locks"


class GraphLockHeld(RuntimeError):
    """Another writer holds this graph's lock; nothing was done."""


def lock_name(uri: str) -> str:
    parts = urlsplit(uri)
    if parts.scheme == "fakegraph":
        return f"graph-fakegraph-{hashlib.sha256(parts.path.encode()).hexdigest()[:8]}.lock"
    return f"graph-{(parts.hostname or 'unknown').lower()}-{parts.port or 'default'}.lock"


@contextmanager
def graph_lock(uri: str) -> Iterator[None]:
    path = Path(os.environ.get(LOCK_DIR_ENV) or DEFAULT_LOCK_DIR) / lock_name(uri)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            holder = os.pread(fd, 32, 0).decode(errors="replace").strip() or "unknown"
            raise GraphLockHeld(f"another writer (pid {holder}) holds {path}; not waiting") from None
        os.ftruncate(fd, 0)
        os.pwrite(fd, f"{os.getpid()}\n".encode(), 0)
        yield
    finally:
        os.close(fd)  # closing the descriptor releases the flock
