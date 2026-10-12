"""The person-identity HMAC key and the private directory that holds it (operator-only, never in a repo).

The key is created only by an explicit `init-key` and is never regenerated: a missing key fails the identity
commands closed, and nothing else in the pipeline (normalize, bake, app, weekly run) imports this module. Every
read re-checks the path: no symlink on any component, the directory 0700 and the key file 0600, both owned by the
current user. The directory comes from OPEN_MARIN_IDENTITY_DIR (default ~/.open-marin-private/identity) and must
resolve outside both repos, their worktrees and any other git checkout.
"""
from __future__ import annotations

import os
import re
import secrets
import stat
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

ENV = "OPEN_MARIN_IDENTITY_DIR"
DEFAULT_DIR = "~/.open-marin-private/identity"
KEY_BYTES = 32
_KEY_NAME = re.compile(r"key-v([1-9][0-9]{0,5})")
REPO = Path(__file__).resolve().parent.parent


class IdentityKeyError(Exception):
    """The key or its directory is unsafe, ambiguous or cannot be created."""


class KeyMissing(IdentityKeyError):
    """No key exists yet: only an explicit init-key creates one."""


@dataclass(frozen=True)
class Key:
    version: int
    secret: bytes = field(repr=False)


def _worktrees(repo: Path) -> set[Path]:
    try:
        listed = subprocess.run(["git", "-C", str(repo), "worktree", "list", "--porcelain"],
                                capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return set()
    return {Path(line.split(" ", 1)[1]).resolve() for line in listed.splitlines() if line.startswith("worktree ")}


def protected_roots() -> set[Path]:
    """This repo, its main checkout and every worktree; the private data repo and its worktrees."""
    roots = {REPO} | _worktrees(REPO)
    for checkout in list(roots):
        link = checkout / "data" / "normalized"  # a symlink into the private data repo, where it exists
        if link.exists():
            data_repo = link.resolve().parent
            roots |= {data_repo} | _worktrees(data_repo)
    return roots


def private_dir() -> Path:
    """The private identity directory, refused when it would resolve inside a repo, a worktree or a checkout."""
    path = Path(os.path.abspath(Path(os.environ.get(ENV) or DEFAULT_DIR).expanduser()))
    real = path.resolve()
    for root in protected_roots():
        if real == root or root in real.parents:
            raise IdentityKeyError(f"{ENV} resolves inside {root}; the private directory must be outside every repo")
    for parent in (real, *real.parents):
        if (parent / ".git").exists():
            raise IdentityKeyError(f"{ENV} resolves inside the git checkout {parent}")
    return path


def _refuse_symlinks(path: Path) -> None:
    """lstat every existing component from the root down: none may be a symlink."""
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        try:
            if stat.S_ISLNK(current.lstat().st_mode):
                raise IdentityKeyError(f"{current} is a symlink; the identity key path may not contain one")
        except FileNotFoundError:
            return


def _check_owned(path: Path, mode: int, what: str) -> os.stat_result:
    info = path.lstat()
    if info.st_uid != os.getuid():
        raise IdentityKeyError(f"{what} {path} is not owned by the current user")
    if stat.S_IMODE(info.st_mode) != mode:
        raise IdentityKeyError(f"{what} {path} has mode {stat.S_IMODE(info.st_mode):o}, expected {mode:o}")
    return info


def _keys(directory: Path) -> list[tuple[int, Path]]:
    return sorted((int(m.group(1)), p) for p in directory.iterdir() if (m := _KEY_NAME.fullmatch(p.name)))


def init_key(directory: Path, version: int = 1, min_version: int = 1) -> Path:
    """Create the one key, `key-v{version}`: O_EXCL, 0600, in a 0700 directory. Refuses anything existing."""
    directory = Path(os.path.abspath(directory))
    if version < min_version:
        raise IdentityKeyError(f"the decision file already uses key versions below {min_version}; "
                               f"choose version {min_version} or higher")
    _refuse_symlinks(directory)
    missing = [p for p in (directory, *directory.parents) if not p.exists()]
    for part in reversed(missing):
        os.mkdir(part, 0o700)
        os.chmod(part, 0o700)
    _refuse_symlinks(directory)
    _check_owned(directory, 0o700, "private directory")
    existing = _keys(directory)
    if existing:
        raise IdentityKeyError(f"{directory} already holds {existing[0][1].name}; a key is never replaced in place")
    path = directory / f"key-v{version}"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        os.fchmod(fd, 0o600)
        os.write(fd, secrets.token_bytes(KEY_BYTES))
        os.fsync(fd)
    except BaseException:
        os.close(fd)
        path.unlink()
        raise
    os.close(fd)
    return path


def _open_dir_nofollow(directory: Path) -> int:
    """An fd on `directory`, reached from `/` one component at a time with O_NOFOLLOW: no symlink can intervene."""
    fd = os.open(directory.anchor, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in directory.parts[1:]:
            try:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            except FileNotFoundError:
                raise KeyMissing(f"no identity key at {directory}: run init-key") from None
            except OSError:  # ELOOP / ENOTDIR: a symlink (or a file) where a directory must be
                raise IdentityKeyError(f"{directory}: a component is a symlink or not a directory") from None
            os.close(fd)
            fd = child
    except BaseException:
        os.close(fd)
        raise
    return fd


def _check_fd(fd: int, mode: int, what: str) -> os.stat_result:
    info = os.fstat(fd)
    if info.st_uid != os.getuid():
        raise IdentityKeyError(f"{what} is not owned by the current user")
    if stat.S_IMODE(info.st_mode) != mode:
        raise IdentityKeyError(f"{what} has mode {stat.S_IMODE(info.st_mode):o}, expected {mode:o}")
    return info


def load_key(directory: Path) -> Key:
    """The key, after every check; KeyMissing when none exists (never created here)."""
    directory = Path(os.path.abspath(directory))
    dir_fd = _open_dir_nofollow(directory)
    try:
        _check_fd(dir_fd, 0o700, f"private directory {directory}")
        keys = sorted((int(m.group(1)), name) for name in os.listdir(dir_fd) if (m := _KEY_NAME.fullmatch(name)))
        if not keys:
            raise KeyMissing(f"no identity key at {directory}: run init-key")
        if len(keys) > 1:
            raise IdentityKeyError(f"{directory} holds more than one key; keep exactly one key-v*")
        version, name = keys[0]
        try:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=dir_fd)
        except OSError:
            raise IdentityKeyError(f"key file {directory / name} is a symlink or unreadable") from None
        try:
            info = _check_fd(fd, 0o600, f"key file {directory / name}")
            secret = os.read(fd, KEY_BYTES + 1) if stat.S_ISREG(info.st_mode) else b""
        finally:
            os.close(fd)
    finally:
        os.close(dir_fd)
    if len(secret) != KEY_BYTES:
        raise IdentityKeyError(f"key file {directory / name} must be a regular file of {KEY_BYTES} bytes")
    return Key(version, secret)
