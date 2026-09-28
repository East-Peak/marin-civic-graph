"""One exclusive lock for everything that writes ingestion state.

`ingest.py` captures, and `refresh_weekly.py` stage / load / publish / rollback,
all read-modify-write the same files (captures, the run ledger, the meeting
identity map, data/normalized, data/exports). Two at once is last-writer-wins,
so each takes an exclusive flock on data/ingest-runs/.lock and refuses, without
waiting, when another run holds it.

A holder that launches a child which also takes the lock (refresh_weekly's
`stage` runs `ingest.py`) passes OWNER_ENV=<its pid>. The child skips the lock
only when that pid is its own parent, so a stale variable is no pass.
"""
from __future__ import annotations

import fcntl
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

LOCK_PATH = Path("data/ingest-runs/.lock")
OWNER_ENV = "OPEN_MARIN_RUN_LOCK_OWNER"


class RunLockHeld(RuntimeError):
    """Another ingestion run holds the lock; nothing was changed."""


@contextmanager
def run_lock(root: Path) -> Iterator[None]:
    if os.environ.get(OWNER_ENV) == str(os.getppid()):
        yield  # our parent holds the lock and launched us under it
        return
    path = root / LOCK_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            holder = os.pread(fd, 32, 0).decode(errors="replace").strip() or "unknown"
            raise RunLockHeld(f"another ingestion run (pid {holder}) holds {path}; "
                              "not waiting. Retry when it finishes.") from None
        os.ftruncate(fd, 0)
        os.pwrite(fd, f"{os.getpid()}\n".encode(), 0)
        yield
    finally:
        os.close(fd)  # closing the descriptor releases the flock
