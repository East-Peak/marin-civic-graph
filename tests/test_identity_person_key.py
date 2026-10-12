"""The identity key: created only by init-key, read only after every path check, never regenerated.

Every path is under a resolved tmp_path (on macOS the raw tmp path runs through the /var symlink).
"""
from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import identity_person_key as ik  # noqa: E402

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture
def home(tmp_path):
    return tmp_path.resolve()


@pytest.fixture
def private(home):
    return home / "private" / "identity"


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.lstat().st_mode)


def test_init_key_creates_a_32_byte_key_owner_only(private):
    created = ik.init_key(private, version=1)
    assert created == private / "key-v1"
    assert len(created.read_bytes()) == 32
    assert _mode(created) == 0o600
    assert _mode(private) == 0o700 and _mode(private.parent) == 0o700
    key = ik.load_key(private)
    assert key.version == 1 and key.secret == created.read_bytes()


def test_init_key_never_overwrites_or_adds_a_second_key(private):
    ik.init_key(private, version=1)
    before = (private / "key-v1").read_bytes()
    with pytest.raises(ik.IdentityKeyError, match="already holds key-v1"):
        ik.init_key(private, version=1)
    with pytest.raises(ik.IdentityKeyError, match="already holds key-v1"):
        ik.init_key(private, version=2)
    assert (private / "key-v1").read_bytes() == before
    assert not (private / "key-v2").exists()


def test_init_key_refuses_a_version_the_decisions_already_used(private):
    with pytest.raises(ik.IdentityKeyError, match="version 2 or higher"):
        ik.init_key(private, version=1, min_version=2)
    assert not private.exists() or not any(private.iterdir())


def test_missing_key_fails_closed_and_creates_nothing(private):
    with pytest.raises(ik.KeyMissing, match="run init-key"):
        ik.load_key(private)
    assert not private.exists()


@pytest.mark.parametrize("bad_mode", [0o640, 0o604, 0o700, 0o400])
def test_a_key_file_with_the_wrong_mode_is_refused(private, bad_mode):
    path = ik.init_key(private, version=1)
    path.chmod(bad_mode)
    with pytest.raises(ik.IdentityKeyError, match="mode"):
        ik.load_key(private)


@pytest.mark.parametrize("bad_mode", [0o750, 0o705, 0o770])
def test_a_private_dir_open_to_others_is_refused(private, bad_mode):
    ik.init_key(private, version=1)
    private.chmod(bad_mode)
    with pytest.raises(ik.IdentityKeyError, match="mode"):
        ik.load_key(private)


def test_a_key_of_the_wrong_size_is_refused(private):
    path = ik.init_key(private, version=1)
    path.write_bytes(b"short")
    with pytest.raises(ik.IdentityKeyError, match="32 bytes"):
        ik.load_key(private)


def test_two_keys_are_ambiguous(private):
    ik.init_key(private, version=1)
    fd = os.open(private / "key-v2", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.write(fd, os.urandom(32))
    os.close(fd)
    with pytest.raises(ik.IdentityKeyError, match="more than one key"):
        ik.load_key(private)


def test_a_symlinked_key_file_is_refused(private, home):
    ik.init_key(private, version=1)
    real = home / "elsewhere"
    real.mkdir(mode=0o700)
    (private / "key-v1").rename(real / "key-v1")
    (private / "key-v1").symlink_to(real / "key-v1")
    with pytest.raises(ik.IdentityKeyError, match="symlink"):
        ik.load_key(private)


def test_a_symlink_anywhere_on_the_path_is_refused(home):
    real = home / "real"
    ik.init_key(real / "identity", version=1)
    (home / "link").symlink_to(real)
    with pytest.raises(ik.IdentityKeyError, match="symlink"):
        ik.load_key(home / "link" / "identity")
    with pytest.raises(ik.IdentityKeyError, match="symlink"):
        ik.init_key(home / "link" / "other", version=1)


def test_init_key_refuses_a_preexisting_dir_open_to_others(private):
    private.mkdir(parents=True, mode=0o755)
    private.chmod(0o755)
    with pytest.raises(ik.IdentityKeyError, match="mode"):
        ik.init_key(private, version=1)
    assert not (private / "key-v1").exists()


def test_private_dir_comes_from_the_env_or_the_default(home, monkeypatch):
    monkeypatch.setenv(ik.ENV, str(home / "chosen"))
    assert ik.private_dir() == home / "chosen"
    monkeypatch.delenv(ik.ENV)
    assert ik.private_dir() == Path("~/.open-marin-private/identity").expanduser()


def test_a_private_dir_inside_this_repo_or_any_git_checkout_is_refused(home, monkeypatch):
    for inside in (REPO / "data" / "identity-private", REPO / "scripts"):
        monkeypatch.setenv(ik.ENV, str(inside))
        with pytest.raises(ik.IdentityKeyError, match="inside"):
            ik.private_dir()
    checkout = home / "some-checkout"
    (checkout / ".git").mkdir(parents=True)
    monkeypatch.setenv(ik.ENV, str(checkout / "deep" / "identity"))
    with pytest.raises(ik.IdentityKeyError, match="inside"):
        ik.private_dir()


def test_a_private_dir_reached_through_a_symlink_into_a_repo_is_refused(home, monkeypatch):
    (home / "sneaky").symlink_to(REPO)
    monkeypatch.setenv(ik.ENV, str(home / "sneaky" / "identity"))
    with pytest.raises(ik.IdentityKeyError, match="inside"):
        ik.private_dir()


def test_protected_roots_include_every_worktree_of_this_repo():
    roots = ik.protected_roots()
    listed = subprocess.run(["git", "-C", str(REPO), "worktree", "list", "--porcelain"],
                            capture_output=True, text=True, check=True).stdout
    for line in listed.splitlines():
        if line.startswith("worktree "):
            assert Path(line.split(" ", 1)[1]).resolve() in roots


def test_nothing_outside_the_identity_tools_imports_the_key_module():
    users = [p.name for p in (REPO / "scripts").glob("*.py")
             if "identity_person_key" in p.read_text(errors="replace") and not p.name.startswith("identity_person")]
    assert users == []
    app = REPO / "app"
    assert not any("identity_person" in p.read_text(errors="replace")
                   for p in app.rglob("*.ts") if "node_modules" not in p.parts)
