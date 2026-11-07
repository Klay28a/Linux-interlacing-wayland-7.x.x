"""Both installers, run the way the GUI runs them: FROM the installed directory (SCRIPT_DIR == the destination).

Regression: ``install-linux-cru.sh`` from ~/.local/share/linux-interlace-suite died with
"'X' and 'X' are the same file" because it copied every file onto itself.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from interlace_manifest import SUITE_FILES

ROOT = Path(__file__).resolve().parent.parent


def sandbox_env(home: Path) -> dict[str, str]:
    return {"PATH": os.environ["PATH"], "HOME": str(home), "LANG": "C"}


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    h.mkdir()
    probe = subprocess.run(["python3", "-c", "import PyQt6"], env=sandbox_env(h), check=False, capture_output=True)
    if probe.returncode != 0:
        pytest.skip("PyQt6 is not importable from a clean HOME (the installers would try to install it with sudo)")
    return h


def populate(dest: Path) -> Path:
    dest.mkdir(parents=True)
    for name in SUITE_FILES:
        shutil.copy2(ROOT / name, dest / name)
    return dest


def run(script: Path, home: Path, *args: str):
    return subprocess.run(
        ["bash", str(script), *args], env=sandbox_env(home), check=False, text=True, capture_output=True,
        stdin=subprocess.DEVNULL,
    )


@pytest.mark.parametrize("script", ["install-linux-cru.sh", "install-interlace-suite.sh"])
def test_installer_run_from_the_installed_directory_succeeds(home, script):
    installed = populate(home / ".local" / "share" / "linux-interlace-suite")
    res = run(installed / script, home)
    assert res.returncode == 0, res.stdout + res.stderr
    assert "same file" not in res.stderr
    assert (home / ".local" / "bin" / "linux-cru").exists() or script == "install-interlace-suite.sh"
    assert (home / ".local" / "bin" / "linux-interlace-suite").exists() or script == "install-linux-cru.sh"


@pytest.mark.parametrize("script", ["install-linux-cru.sh", "install-interlace-suite.sh"])
def test_installer_run_from_the_repository_still_installs_everything(home, script):
    res = run(ROOT / script, home)
    assert res.returncode == 0, res.stdout + res.stderr
    share = home / ".local" / "share" / "linux-interlace-suite"
    missing = [n for n in SUITE_FILES if not (share / n).is_file()]
    assert missing == [] or script == "install-linux-cru.sh" and set(missing) <= set()


def test_running_the_installer_twice_is_idempotent(home):
    installed = populate(home / ".local" / "share" / "linux-interlace-suite")
    assert run(installed / "install-linux-cru.sh", home).returncode == 0
    assert run(installed / "install-linux-cru.sh", home).returncode == 0


def test_dry_run_from_the_installed_directory_changes_nothing_and_succeeds(home):
    installed = populate(home / ".local" / "share" / "linux-interlace-suite")
    before = sorted(str(p) for p in home.rglob("*"))
    res = run(installed / "install-linux-cru.sh", home, "--dry-run")
    assert res.returncode == 0, res.stdout + res.stderr
    assert sorted(str(p) for p in home.rglob("*")) == before
