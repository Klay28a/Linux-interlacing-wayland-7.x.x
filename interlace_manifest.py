"""
The single list of files that make up an installed copy of the Linux CRT Interlacing Suite.

Every consumer (the kernel workflow's preflight, the packaging tests, the GUI's self-healing sync)
is checked against this manifest, so a half-populated install directory can be detected and
reported instead of failing later with ``No such file or directory`` deep inside a build.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path

SUITE_SCRIPTS: tuple[str, ...] = (
    "setup-interlace-env.sh",
    "fix-interlaced-kernel.sh",
    "install-linux-cru.sh",
    "install-interlace-suite.sh",
)
SUITE_DATA: tuple[str, ...] = ("11_linux_rdna_dp_hdmi_interlace.patch",)
SUITE_APPS: tuple[str, ...] = ("linux-interlace-suite.py", "linux_cru.py")
SUITE_MODULES: tuple[str, ...] = (
    "interlace_apply_edid.py",
    "interlace_apply_rules.py",
    "interlace_boot.py",
    "interlace_cmdline.py",
    "interlace_edid.py",
    "interlace_gpu.py",
    "interlace_gui_tasks.py",
    "interlace_kernel.py",
    "interlace_manifest.py",
    "interlace_patches.py",
    "interlace_pkgbuild.py",
    "interlace_rdna_patch.py",
    "interlace_rules.py",
    "interlace_runner.py",
    "interlace_selection.py",
    "interlace_setup.py",
    "interlace_state.py",
    "interlace_sysinfo.py",
    "interlace_verify.py",
)
SUITE_FILES: tuple[str, ...] = SUITE_SCRIPTS + SUITE_DATA + SUITE_APPS + SUITE_MODULES


def missing_files(
    directory: Path, names: Iterable[str] = SUITE_FILES, is_file: Callable[[Path], bool] = Path.is_file,
) -> list[str]:
    """Names from ``names`` that are not regular files inside ``directory`` (all of them if it is absent)."""
    return [name for name in names if not is_file(directory / name)]


def is_complete(directory: Path, is_file: Callable[[Path], bool] = Path.is_file) -> bool:
    return not missing_files(directory, SUITE_FILES, is_file)


def search_dirs(self_dir: Path, home: Path) -> list[Path]:
    """Directories an installed suite may live in, best candidates first."""
    return [
        self_dir,
        home / ".local" / "share" / "linux-interlace-suite",
        Path("/usr/local/share/linux-interlace-suite"),
        Path("/usr/share/linux-interlace-suite"),
        home / "Linux-interlacing-wayland-7.x.x",
    ]


def find_complete_dir(candidates: Sequence[Path], is_file: Callable[[Path], bool] = Path.is_file) -> Path | None:
    for cand in candidates:
        if is_complete(cand, is_file):
            return cand
    return None


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def resolve_suite_dir(saved: str, self_dir: Path, home: Path) -> Path:
    """The directory the GUI should run scripts from.

    Only a *complete* directory qualifies (every file in ``SUITE_FILES``), so a stale saved path or a
    half-populated ``~/.local/share/linux-interlace-suite`` can never be chosen over a good install.
    Among complete directories the most recently updated wins. When none is complete, the directory
    missing the fewest files is returned so ``sync_suite`` can heal it from the others.
    """
    candidates = search_dirs(self_dir, home)
    if saved:
        candidates.insert(0, Path(saved))
    unique = list(dict.fromkeys(candidates))
    complete = [c for c in unique if is_complete(c)]
    if complete:
        return max(complete, key=lambda c: _mtime(c / "interlace_kernel.py"))
    return min(unique, key=lambda c: len(missing_files(c)))


def sync_suite(dest: Path, sources: Sequence[Path]) -> list[str]:
    """Bring ``dest`` up to date, file by file, from the newest copy found in ``sources``.

    Heals a partial install even when no single source directory is complete. Returns the copied names.
    """
    dest.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    for name in SUITE_FILES:
        best: Path | None = None
        for src in sources:
            cand = src / name
            if cand.is_file() and src.resolve() != dest.resolve() and (best is None or _mtime(cand) > _mtime(best)):
                best = cand
        target = dest / name
        if best is not None and (not target.is_file() or _mtime(best) > _mtime(target)):
            shutil.copy2(best, target)
            copied.append(name)
    return copied
