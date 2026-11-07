"""Regression for the reported failure: every kernel button died with
``can't open file '~/.local/share/linux-interlace-suite/interlace_apply_rules.py'``.

The cause was a half-populated install directory being chosen (and never healed). These tests pin
the manifest-based resolution/sync and that the wrappers skip an incomplete directory.
"""

import os
import shutil
import subprocess
import time
from pathlib import Path

import interlace_manifest as im

ROOT = Path(__file__).resolve().parent.parent


def populate(directory: Path, names=im.SUITE_FILES, *, mtime: float | None = None) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    for name in names:
        f = directory / name
        f.write_text(f"# {name}\n", encoding="utf-8")
        if mtime is not None:
            os.utime(f, (mtime, mtime))
    return directory


def test_missing_files_reports_exactly_what_is_absent(tmp_path: Path) -> None:
    d = populate(tmp_path / "s", [n for n in im.SUITE_FILES if n != "interlace_apply_rules.py"])
    assert im.missing_files(d) == ["interlace_apply_rules.py"]
    assert not im.is_complete(d)
    assert im.missing_files(tmp_path / "nope") == list(im.SUITE_FILES)


def test_the_reported_half_populated_directory_is_never_chosen(tmp_path: Path) -> None:
    home = tmp_path / "home"
    half = populate(home / ".local/share/linux-interlace-suite", im.SUITE_SCRIPTS + im.SUITE_DATA)
    full = populate(tmp_path / "repo")
    chosen = im.resolve_suite_dir(str(half), full, home)
    assert chosen == full
    assert im.is_complete(chosen)


def test_saved_config_path_that_is_stale_or_incomplete_is_ignored(tmp_path: Path) -> None:
    home = tmp_path / "home"
    full = populate(tmp_path / "repo")
    assert im.resolve_suite_dir(str(tmp_path / "gone"), full, home) == full
    assert im.resolve_suite_dir("", full, home) == full


def test_newest_complete_directory_wins(tmp_path: Path) -> None:
    home = tmp_path / "home"
    now = time.time()
    old = populate(tmp_path / "old", mtime=now - 1000)
    new = populate(home / ".local/share/linux-interlace-suite", mtime=now)
    assert im.resolve_suite_dir("", old, home) == new


def test_when_nothing_is_complete_the_least_broken_directory_is_returned(tmp_path: Path) -> None:
    home = tmp_path / "home"
    nearly = populate(tmp_path / "nearly", im.SUITE_FILES[:-1])
    barely = populate(tmp_path / "barely", im.SUITE_FILES[:3])
    chosen = im.resolve_suite_dir(str(nearly), barely, home)
    assert chosen == nearly
    assert len(im.missing_files(chosen)) == 1


def test_sync_heals_a_partial_install_even_when_it_is_the_chosen_directory(tmp_path: Path) -> None:
    """The old sync skipped the case scripts_dir == ~/.local/share/..., so it could never repair itself."""
    home = tmp_path / "home"
    stamp = time.time() - 100  # identical timestamps: only genuinely missing files may be copied
    user_share = populate(home / ".local/share/linux-interlace-suite", im.SUITE_SCRIPTS, mtime=stamp)
    repo = populate(tmp_path / "repo", mtime=stamp)
    copied = im.sync_suite(user_share, [user_share, repo])
    assert im.is_complete(user_share)
    assert "interlace_apply_rules.py" in copied
    assert "setup-interlace-env.sh" not in copied, "files that are already current are not re-copied"


def test_sync_assembles_a_complete_install_from_several_partial_ones(tmp_path: Path) -> None:
    a = populate(tmp_path / "a", im.SUITE_SCRIPTS + im.SUITE_DATA + im.SUITE_APPS)
    b = populate(tmp_path / "b", im.SUITE_MODULES)
    dest = tmp_path / "dest"
    im.sync_suite(dest, [a, b])
    assert im.is_complete(dest)


def test_sync_does_not_overwrite_a_newer_file_with_an_older_one(tmp_path: Path) -> None:
    now = time.time()
    src = populate(tmp_path / "src", mtime=now - 500)
    dest = populate(tmp_path / "dest", mtime=now)
    (dest / "interlace_kernel.py").write_text("# newer local edit\n", encoding="utf-8")
    assert im.sync_suite(dest, [src]) == []
    assert (dest / "interlace_kernel.py").read_text(encoding="utf-8") == "# newer local edit\n"


def test_sync_skips_missing_sources_without_error(tmp_path: Path) -> None:
    repo = populate(tmp_path / "repo")
    dest = tmp_path / "dest"
    im.sync_suite(dest, [tmp_path / "does-not-exist", repo])
    assert im.is_complete(dest)


def _copy_wrapper(name: str, into: Path) -> Path:
    into.mkdir(parents=True, exist_ok=True)
    target = into / name
    shutil.copy2(ROOT / name, target)
    return target


def _run_wrapper(wrapper: Path, home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {"PATH": os.environ["PATH"], "HOME": str(home), "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run(["bash", str(wrapper), *args], check=False, text=True, capture_output=True, env=env)


def test_wrapper_skips_an_incomplete_directory_and_uses_a_complete_one(tmp_path: Path) -> None:
    """A copy of the wrapper next to NO python modules must fall through to ~/.local/share/..."""
    home = tmp_path / "home"
    shutil.copytree(ROOT, home / ".local/share/linux-interlace-suite", ignore=shutil.ignore_patterns(
        "tests", ".git", "__pycache__", "assets", "*.zst"))
    lonely = _copy_wrapper("fix-interlaced-kernel.sh", tmp_path / "lonely")
    res = _run_wrapper(lonely, home, "--help")
    assert res.returncode == 0, res.stderr
    assert "--config-only" in res.stdout


def test_wrapper_reports_a_clear_error_when_no_complete_suite_exists(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    for name in ("fix-interlaced-kernel.sh", "setup-interlace-env.sh"):
        lonely = _copy_wrapper(name, tmp_path / "lonely")
        res = _run_wrapper(lonely, home, "--help")
        if res.returncode == 0:  # a system-wide install on this machine legitimately satisfies it
            continue
        assert "could not find a complete copy" in res.stderr
        assert "Traceback" not in res.stderr
        assert "No such file" not in res.stderr
