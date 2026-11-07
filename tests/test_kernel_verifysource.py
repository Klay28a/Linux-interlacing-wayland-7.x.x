"""Regression: ``makepkg --verifysource`` aborts with exit 13 when a built package already sits in the PKGBUILD
directory unless ``-f`` is given. Every re-run after a successful build hit it (7.3 and auto in the user's log).

A stand-in ``makepkg`` on PATH reproduces makepkg's own refusal, and the REAL Runner executes it.
"""

import io
import os
import shutil
import tarfile

import pytest

import interlace_kernel as ik
from conftest import arch_pc
from interlace_runner import CommandError, Host, Runner

FAKE_MAKEPKG = """#!/usr/bin/env bash
force=0; verify=0; info=0
for a in "$@"; do
  case "$a" in -f|--force) force=1 ;; --verifysource) verify=1 ;; --printsrcinfo) info=1 ;; esac
done
if [ "$info" = 1 ]; then printf 'pkgbase = x\\n\\tsource = linux-1.tar.gz\\n'; exit 0; fi
if [ "$verify" = 1 ] && [ "$force" = 0 ] && ls ./*.pkg.tar.zst >/dev/null 2>&1; then
  echo "==> ERROR: The package group has already been built. (use -f to overwrite)" >&2
  exit 13
fi
exit 0
"""
PATCH = "--- a/dir/f01\n+++ b/dir/f01\n@@ -1 +1 @@\n-a\n+b\n"


@pytest.fixture
def tree(tmp_path, monkeypatch):
    if shutil.which("patch") is None:
        pytest.skip("patch(1) not installed")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake = bindir / "makepkg"
    fake.write_text(FAKE_MAKEPKG)
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    work = tmp_path / "work"
    work.mkdir()
    with tarfile.open(work / "linux-1.tar.gz", "w:gz") as tar:
        info = tarfile.TarInfo("linux-1/dir/f01")
        info.size = 2
        tar.addfile(info, io.BytesIO(b"a\n"))
    repo = tmp_path / "patches"
    (repo / "linux-1.0").mkdir(parents=True)
    (repo / "linux-1.0" / "01_x.patch").write_text(PATCH)
    return work, repo


def host_for(tmp_path):
    return Host(runner=Runner(is_root=True, interactive=False))


def test_verifysource_succeeds_even_when_a_built_package_already_exists(tree, tmp_path):
    work, repo = tree
    (work / "linux-cachyos-7.3.1-1-x86_64.pkg.tar.zst").write_bytes(b"built earlier")
    chosen = ik._verified_patch_set(host_for(tmp_path), repo, ["linux-1.0"], work, None)
    assert [c.number for c in chosen.chosen] == ["01"]


def test_verifysource_never_deletes_the_users_built_packages(tree, tmp_path):
    work, repo = tree
    pkg = work / "linux-cachyos-7.3.1-1-x86_64.pkg.tar.zst"
    pkg.write_bytes(b"built earlier")
    ik._verified_patch_set(host_for(tmp_path), repo, ["linux-1.0"], work, None)
    assert pkg.read_bytes() == b"built earlier"


def test_without_force_the_stand_in_really_would_fail(tree, tmp_path):
    """Guards the guard: proves the fake reproduces exit 13, so the tests above are meaningful."""
    work, _ = tree
    (work / "a-1-x86_64.pkg.tar.zst").write_bytes(b"x")
    with pytest.raises(CommandError, match="exit 13"):
        Runner(is_root=True, interactive=False).run(["makepkg", "--verifysource"], cwd=work)


def test_the_verify_command_carries_force(tmp_path):
    _, host, runner = arch_pc(tmp_path)
    work = tmp_path / "work"
    work.mkdir()
    ik._verified_patch_set(host, tmp_path, ["linux-1.0"], work, None)
    verify = [c for c in runner.executed if "--verifysource" in c]
    assert verify
    assert all("-f" in c for c in verify)
