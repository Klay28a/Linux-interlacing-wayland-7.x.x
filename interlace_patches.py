#!/usr/bin/env python3
"""
Choose the D0023R 15kHz patches that really apply to the kernel being built.

The patch repository keeps one folder per kernel series (``linux-6.12``, ``linux-7.3``,
``linux-next`` ...). A folder named for the right series is not a guarantee: ``linux-next`` targets
whatever the CachyOS RC currently is, and its ``03_*`` patch stopped applying to 7.4-rc1 while the
``linux-7.3`` one still does. So every patch is checked (``patch --dry-run``) against the *extracted
source* and, if the preferred series' copy does not apply, the nearest series that does is used.
Patches are applied in order to the probe tree, because later patches build on earlier ones.

Optional patches (``09``: Intel gen9 i915 only) are dropped with a warning when none applies; a
failing required patch is an error that names the patch instead of a half-patched kernel.

  interlace_patches.py fetch [--repo DIR] [--dry-run]     # clone/update D0023R's linux_kernel_15khz
  interlace_patches.py plan --kernel-version 6.12 [--repo DIR]   # which series/patches would be used
"""

from __future__ import annotations

import argparse
import re
import sys
import tarfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from interlace_runner import CommandError, Runner

PATCH_NUMBERS = ("01", "02", "03", "04", "05", "07", "08", "09")
OPTIONAL_NUMBERS = frozenset({"09"})  # i915 gen9: Intel iGPUs only
_NUMERIC_SERIES = re.compile(r"linux-\d+(\.\d+)*")


class PatchError(Exception):
    """A required patch cannot be applied by any series. The message is safe to show to the user."""


@dataclass(frozen=True)
class PatchChoice:
    number: str
    series: str
    path: Path
    preferred: bool  # True when it came from the first-choice series


@dataclass
class PatchSet:
    chosen: list[PatchChoice] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)

    @property
    def paths(self) -> list[Path]:
        return [c.path for c in self.chosen]


def version_key(name: str) -> tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"\d+", name))


def candidate_series(available: Sequence[str], want_series: str, kver: str) -> list[str]:
    """Series to try, best first: the exact ones, then older (newest first), then newer (oldest first)."""
    order: list[str] = []
    for wanted in (want_series, f"linux-{kver}"):
        if wanted in available and wanted not in order:
            order.append(wanted)
    numeric = [n for n in available if _NUMERIC_SERIES.fullmatch(n) and n not in order]
    target = version_key(kver)
    older = sorted((n for n in numeric if version_key(n) <= target), key=version_key, reverse=True)
    newer = sorted((n for n in numeric if version_key(n) > target), key=version_key)
    return order + older + newer


def touched_files(patches: Sequence[Path]) -> set[str]:
    """Repository-relative files that ``patch -p1`` would modify (the ``+++ b/path`` headers)."""
    files: set[str] = set()
    for patch in patches:
        for line in patch.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith("+++ ") and "/dev/null" not in line:
                name = line[4:].split("\t")[0].strip()
                if "/" in name:
                    files.add(name.split("/", 1)[1])  # drop the a/ b/ prefix (-p1)
    return files


def extract_files(tarball: Path, rels: set[str], dest: Path) -> int:
    """Extract just ``rels`` (paths relative to the archive's top directory) into ``dest``.

    A pristine copy of every file the candidate patches touch is all ``patch --dry-run`` needs, so the
    multi-GB tree is never unpacked. Returns the number of files written.
    """
    written = 0
    with tarfile.open(tarball, "r:*") as tar:
        for member in tar:
            if not member.isfile() or "/" not in member.name:
                continue
            rel = member.name.split("/", 1)[1]
            if rel not in rels:
                continue
            handle = tar.extractfile(member)
            if handle is None:
                continue
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(handle.read())
            written += 1
    return written


def list_series(repo: Path) -> list[str]:
    if not repo.is_dir():
        return []
    return sorted((p.name for p in repo.iterdir() if p.is_dir() and p.name.startswith("linux-")), key=version_key)


def find_patch(repo: Path, series: str, number: str) -> Path | None:
    found = sorted((repo / series).glob(f"{number}_*.patch"))
    return found[0] if found else None


def pick_unverified(repo: Path, order: Sequence[str]) -> PatchSet:
    """The preferred series' own patches, untested (used when there is no source tree to test against)."""
    result = PatchSet()
    for number in PATCH_NUMBERS:
        path = find_patch(repo, order[0], number) if order else None
        if path is not None:
            result.chosen.append(PatchChoice(number, order[0], path, True))
    return result


def resolve_patch_set(
    repo: Path,
    order: Sequence[str],
    applies: Callable[[Path], bool],
    apply: Callable[[Path], None],
    say: Callable[[str], None] = print,
) -> PatchSet:
    """Verify each patch against the source via ``applies`` and apply it via ``apply`` before the next one.

    The preferred series (``order[0]``) decides which patches exist for this kernel: a patch it does not
    ship (e.g. 6.1 has no ``07``/``08``) is simply not part of the set and is never borrowed from another
    series. Only when the preferred series ships a patch that fails to apply are the other series tried.
    """
    result = PatchSet()
    for number in PATCH_NUMBERS:
        if not order or find_patch(repo, order[0], number) is None:
            continue
        picked: PatchChoice | None = None
        for series in order:
            path = find_patch(repo, series, number)
            if path is None:
                continue
            if applies(path):
                apply(path)
                picked = PatchChoice(number, series, path, series == order[0])
                break
            say(f"  -> {path.name} from {series} does not apply to this kernel source; trying another series")
        if picked is not None:
            result.chosen.append(picked)
            if not picked.preferred:
                say(f"  -> Using {picked.path.name} from {picked.series} (preferred series did not apply)")
        elif number in OPTIONAL_NUMBERS:
            result.dropped.append(number)
            say(f"  -> Skipping optional patch {number}_* (no series applies; it only affects Intel gen9 GPUs)")
        else:
            raise PatchError(
                f"no series in the 15kHz patch repository has a {number}_* patch that applies to this kernel "
                f"(tried: {', '.join(order) or 'none'}). The 15kHz patches need updating for this kernel version.",
            )
    return result


PATCHES_URL = "https://github.com/D0023R/linux_kernel_15khz.git"
_ARCHIVE_SUFFIXES = (".tar.gz", ".tar.xz", ".tar.zst", ".tar.bz2")


def kernel_source_name(srcinfo: str) -> str | None:
    """File name of the kernel source archive listed in ``makepkg --printsrcinfo`` output.

    NVIDIA/ZFS archives and git sources are not the kernel; the first remaining archive is.
    """
    for line in srcinfo.splitlines():
        key, _, value = line.strip().partition(" = ")
        if key != "source":
            continue
        name = value.split("::", 1)[0] if "::" in value else value.rsplit("/", 1)[-1]
        if name.endswith(_ARCHIVE_SUFFIXES) and not name.startswith(("NVIDIA", "zfs")):
            return name
    return None


def fetch_repo(runner: Runner, repo: Path) -> None:
    """Clone D0023R's patch repository, or bring an existing clone to its latest commit."""
    runner.makedirs(repo.parent)
    if (repo / ".git").exists():
        runner.run(["git", "-C", repo, "fetch", "--depth", "1", "origin"])
        runner.run(["git", "-C", repo, "reset", "--hard", "FETCH_HEAD"])
        runner.run(["git", "-C", repo, "clean", "-fd"])
    else:
        runner.run(["git", "clone", "--depth", "1", PATCHES_URL, repo], stream=True)


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Fetch and plan D0023R's 15kHz kernel patches")
    sub = p.add_subparsers(dest="action", required=True)
    for name in ("fetch", "plan"):
        s = sub.add_parser(name)
        s.add_argument("--repo", type=Path, default=Path.home() / "kernel-build" / "linux_kernel_15khz")
        s.add_argument("--dry-run", action="store_true")
    sub.choices["plan"].add_argument("--kernel-version", required=True, help="X.Y or linux-next")
    args = p.parse_args(argv)
    runner = Runner(dry_run=args.dry_run)
    try:
        if args.action == "fetch":
            fetch_repo(runner, args.repo)
            return 0
        kver = args.kernel_version
        want = "linux-next" if kver in ("linux-next", "rc") else f"linux-{kver}"
        order = candidate_series(list_series(args.repo), want, "99.99" if want == "linux-next" else kver)
        for choice in pick_unverified(args.repo, order).chosen:
            print(f"{choice.number}  {choice.series}/{choice.path.name}")
        return 0
    except CommandError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
