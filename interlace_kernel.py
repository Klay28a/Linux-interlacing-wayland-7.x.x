#!/usr/bin/env python3
"""
Interlaced / 15kHz kernel workflow (the logic behind ``fix-interlaced-kernel.sh``).

Everything that decides *what* to build is a pure function (``resolve_kernel_target``,
``parse_pkgbuild_kver``, ``nvidia_overrides``; patch choice lives in interlace_patches) so it is unit-tested with plain
strings. Everything that *does* something goes through ``Runner`` so ``--dry-run`` prints it and
tests record it. ``--config-only`` (GPU rules + initramfs) works on any distribution; the kernel
build itself needs an Arch-based host (pacman + makepkg) and says so instead of failing midway.

Progress markers (``==> [n/6] ...``) are parsed by the GUI's progress bar; keep their format.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import tempfile
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from interlace_apply_rules import apply_profile, resolve_profile
from interlace_boot import sync_boot
from interlace_gpu import ADAPTER_MODES, GPU_PROFILES
from interlace_patches import (
    PATCH_NUMBERS,
    PatchError,
    PatchSet,
    candidate_series,
    extract_files,
    fetch_repo,
    find_patch,
    kernel_source_name,
    list_series,
    pick_unverified,
    resolve_patch_set,
    touched_files,
)
from interlace_pkgbuild import PkgbuildError
from interlace_pkgbuild import run as edit_pkgbuild
from interlace_runner import CommandError, Host, Runner
from interlace_state import kernel_record

CACHYOS_URL = "https://github.com/CachyOS/linux-cachyos.git"
MASTER = "origin/master"
MAKEPKG_BUILD = ["makepkg", "-Csfi", "-f", "--noconfirm", "--skipinteg"]

# The CachyOS PKGBUILD revision matching each series that is not simply "current master".
PINNED_COMMITS: Mapping[str, str] = {
    "7.2": "4a8d2ec8509d0da7d5fd5293f42251ea99d5ea3c",
    "6.12": "1a3b979f284e343eb56a73c45c0ad8d3bf11ecde",
    "6.6": "07ecd945b581930dbf8212bd57b7dd90f3ed51a1",
    "6.1": "97ec6edeea4f4fba456e17bbfc49a8d0fdd5bf11",
}
LTS_SERIES = frozenset({"6.18", "6.12", "6.6", "6.1"})
RC_ALIASES = frozenset({"linux-next", "rc"})

# base-devel is a package *group* (``pacman -T`` cannot test groups), so its relevant members are listed.
REQUIRED_PACKAGES = (
    "binutils", "bison", "fakeroot", "flex", "gcc", "make", "patch", "pkgconf", "sudo",
    "git", "pacman-contrib", "rust", "rust-bindgen", "rust-src", "python", "bc", "cpio", "gettext",
    "libelf", "openssl", "pahole", "perl", "tar", "xxhash", "xz", "zlib", "zstd", "clang", "llvm", "lld",
)

_VERSION_RE = re.compile(r"^\d+\.\d+$")
_PROCESSOR_OPT_RE = re.compile(r"^[A-Za-z0-9_.+-]+$")


class KernelError(Exception):
    """A user-facing, non-command failure (bad input, missing prerequisite, unusable source tree)."""


@dataclass(frozen=True)
class KernelTarget:
    kver: str  # "7.3", "6.12", "linux-next" ...
    subdir: str  # directory inside the linux-cachyos repository
    commit: str  # a commit SHA, or MASTER
    patch_series: str  # preferred 15kHz patch directory name


def resolve_kernel_target(requested: str, uname_r: str) -> KernelTarget:
    """Map a GUI/CLI kernel choice (``auto``, ``7.3``, ``6.12``, ``linux-next`` ...) to a build target."""
    if requested == "auto":
        match = re.match(r"(\d+\.\d+)", uname_r.strip())
        if not match:
            raise KernelError("could not determine the running kernel series; pass --kernel-version")
        kver = match.group(1)
    elif requested in RC_ALIASES:
        return KernelTarget(requested, "linux-cachyos-rc", MASTER, "linux-next")
    elif _VERSION_RE.match(requested):
        kver = requested
    else:
        raise KernelError(f"unsupported --kernel-version {requested!r} (use auto, X.Y or linux-next)")
    return KernelTarget(
        kver=kver,
        subdir="linux-cachyos-lts" if kver in LTS_SERIES else "linux-cachyos",
        commit=PINNED_COMMITS.get(kver, MASTER),
        patch_series=f"linux-{kver}",
    )


def parse_pkgbuild_kver(pkgbuild_text: str, fallback: str) -> str:
    """The ``major.minor`` series a PKGBUILD builds (``_major=`` first, then ``pkgver=``)."""
    for key in ("_major", "pkgver"):
        match = re.search(rf"^{key}=(\d+\.\d+)", pkgbuild_text, re.MULTILINE)
        if match:
            return match.group(1)
    return fallback


def nvidia_overrides(
    *, open_module_pkg_installed: bool, installed_nv_ver: str, nv580_installed: bool, pkgbuild_text: str,
) -> tuple[dict[str, str], list[str]]:
    """PKGBUILD ``_build_nvidia_*`` defaults for this host, plus human-readable notes."""
    overrides: dict[str, str] = {}
    notes: list[str] = []
    build_open = "no"
    if not open_module_pkg_installed:
        notes.append("No linux-cachyos*-nvidia-open package installed; _build_nvidia_open=no")
    elif installed_nv_ver and re.search(rf"^_nv_ver={re.escape(installed_nv_ver)}$", pkgbuild_text, re.MULTILINE):
        notes.append(f"Detected matching nvidia-utils ({installed_nv_ver}); enabling _build_nvidia_open")
        build_open = "yes"
    else:
        notes.append(
            f"PKGBUILD _nv_ver differs from host nvidia-utils ({installed_nv_ver or 'none'}); _build_nvidia_open=no",
        )
    overrides["_build_nvidia_open"] = build_open
    if not nv580_installed:
        overrides["_build_nvidia_580xx"] = "no"
    return overrides, notes


@dataclass(frozen=True)
class KernelOptions:
    gpu_profile: str = "auto"
    adapter_mode: str = "auto"
    kernel_version: str = "auto"
    processor_opt: str | None = "native"
    include_rdna: bool = True
    config_only: bool = False
    build_root: Path = Path.home() / "kernel-build"
    srcdest: Path | None = None  # makepkg's SRCDEST (where it keeps downloaded sources); None = the PKGBUILD dir


def _installed(host: Host, package: str) -> bool:
    return host.runner.query(["pacman", "-Qq", package], ok_to_fail=True).returncode == 0


def _missing_build_packages(host: Host) -> list[str]:
    res = host.runner.query(["pacman", "-T", *REQUIRED_PACKAGES], ok_to_fail=True)
    return [line.strip() for line in res.stdout.splitlines() if line.strip()]


def _sync_to_master(host: Host, repo: Path) -> None:
    host.runner.run(["git", "-C", repo, "fetch", "--depth", "1", "origin", "master"])
    host.runner.run(["git", "-C", repo, "reset", "--hard", "FETCH_HEAD"])


def _prepare_repos(host: Host, target: KernelTarget, cachy: Path, patches: Path) -> None:
    runner = host.runner
    runner.makedirs(cachy.parent)
    if not host.exists(cachy / ".git"):
        runner.run(["git", "clone", "--depth", "1", CACHYOS_URL, cachy], stream=True)
    if target.commit == MASTER:
        _sync_to_master(host, cachy)
    else:
        fetched = runner.run(
            ["git", "-C", cachy, "fetch", "--depth", "1", "origin", target.commit], ok_to_fail=True,
        )
        if fetched.returncode == 0:
            runner.run(["git", "-C", cachy, "reset", "--hard", target.commit])
        else:
            runner.say(f"  -> Pinned PKGBUILD revision {target.commit[:12]} is unavailable; using current master.")
            _sync_to_master(host, cachy)
    runner.run(["git", "-C", cachy, "clean", "-fd", "-e", "*.tar.*", "-e", "*.run", "-e", "*.asc"])
    fetch_repo(runner, patches)  # D0023R's linux_kernel_15khz


def _announce_profile(host: Host, opts: KernelOptions) -> tuple[str, list]:
    profile, gpus = resolve_profile(host, opts.gpu_profile)
    host.runner.say(
        f"==> Selected GPU Architecture Profile: {profile} "
        f"(requested: {opts.gpu_profile} | adapter: {opts.adapter_mode})",
    )
    return profile, gpus


def run_config_only(host: Host, opts: KernelOptions) -> int:
    profile, gpus = _announce_profile(host, opts)
    say = host.runner.say
    say("==> [1/1] Applying GPU architecture & multi-GPU driver configuration only (--config-only)...")
    apply_profile(host, profile, gpus)
    say(f"==> SUCCESS! GPU profile '{profile}' applied.")
    return 0


def _verified_patch_set(
    host: Host, patches: Path, order: list[str], workdir: Path, srcdest: Path | None,
) -> PatchSet:
    """Pick, per patch number, the first series whose patch really applies to this kernel's source.

    Needs the kernel source archive, which ``makepkg --verifysource`` downloads (and later reuses). Only
    the handful of files the patches touch are unpacked, into a throw-away directory. Without an archive
    (dry run, or the download is unavailable) the preferred series is used unverified and makepkg's own
    prepare() remains the final judge.
    """
    runner = host.runner
    if runner.dry_run:
        runner.plan("would download the kernel source and verify each 15kHz patch against it")
        return pick_unverified(patches, order)
    runner.say("  -> Downloading the kernel source to verify the 15kHz patches against it...")
    # -f: without it makepkg refuses (exit 13) whenever a package from an earlier build is still in this
    # directory, which is every re-run. --verifysource only downloads; it never builds or deletes a package.
    runner.run(["makepkg", "--verifysource", "--skipinteg", "-d", "-f"], cwd=workdir, stream=True)
    info = runner.query(["makepkg", "--printsrcinfo"], cwd=workdir, ok_to_fail=True).stdout
    name = kernel_source_name(info)
    tarball = next((d / name for d in (srcdest, workdir) if name and d and (d / name).is_file()), None)
    if tarball is None:
        runner.say("  -> Could not locate the kernel source archive; using the preferred series unverified.")
        return pick_unverified(patches, order)
    candidates = [p for s in order for n in PATCH_NUMBERS if (p := find_patch(patches, s, n)) is not None]
    with tempfile.TemporaryDirectory(prefix="interlace-probe-") as tmp:
        scratch = Path(tmp)
        extract_files(tarball, touched_files(candidates), scratch)

        def applies(patch: Path) -> bool:
            argv = ["patch", "-Np1", "--dry-run", "-d", scratch, "-i", patch]
            return runner.query(argv, ok_to_fail=True).returncode == 0

        def apply(patch: Path) -> None:
            runner.query(["patch", "-Np1", "-s", "-d", scratch, "-i", patch], ok_to_fail=True)

        return resolve_patch_set(patches, order, applies, apply, runner.say)


def _stage_patches(host: Host, chosen: PatchSet, workdir: Path, rdna_tool: Path | None) -> list[str]:
    runner = host.runner
    names: list[str] = []
    for choice in chosen.chosen:
        runner.copy_file(choice.path, workdir / choice.path.name)
        names.append(choice.path.name)
        runner.say(f"  -> Added {choice.path.name}")
    if not names:
        raise KernelError("No 15kHz patch files were found for this kernel in the patch repository")
    if rdna_tool is not None:
        # prepare() runs this file from the extracted source tree, so it is listed in source=().
        runner.copy_file(rdna_tool, workdir / "apply_rdna_dac_unlock.py")
        names.append("apply_rdna_dac_unlock.py")
        runner.say("  -> Prepared RDNA DCN & DP/HDMI DAC Interlace Unlock (apply_rdna_dac_unlock.py)")
    return names


def _configure_pkgbuild(host: Host, opts: KernelOptions, pkgbuild: Path, patch_files: list[str]) -> None:
    runner = host.runner
    text = pkgbuild.read_text(encoding="utf-8", errors="ignore")
    nv = runner.query(["pacman", "-Q", "nvidia-utils"], ok_to_fail=True).stdout.split()
    overrides, notes = nvidia_overrides(
        open_module_pkg_installed=_installed(host, "linux-cachyos-nvidia-open")
        or _installed(host, "linux-cachyos-lts-nvidia-open"),
        installed_nv_ver=nv[1].split("-")[0] if len(nv) > 1 else "",
        nv580_installed=_installed(host, "nvidia-580xx-utils"),
        pkgbuild_text=text,
    )
    for note in notes:
        runner.say(f"  -> {note}")
    edit_pkgbuild(pkgbuild, patch_files, opts.include_rdna, overrides, opts.processor_opt, runner.dry_run, runner.say)


def run_build(host: Host, opts: KernelOptions, suite_dir: Path) -> int:
    runner = host.runner
    say = runner.say
    profile, gpus = _announce_profile(host, opts)

    if not host.which("pacman") or not host.which("makepkg"):
        raise KernelError(
            "Building the patched kernel needs an Arch-based system (pacman + makepkg). "
            "Use --config-only to apply just the GPU rules on this distribution.",
        )
    rdna_tool = suite_dir / "interlace_rdna_patch.py"
    if opts.include_rdna and not rdna_tool.is_file():
        raise KernelError(f"{rdna_tool} is missing; reinstall the suite or pass --no-rdna-patch")

    say("==> [1/6] Ensuring required build tools are installed...")
    missing = _missing_build_packages(host)
    if missing:
        say(f"  -> Installing missing build dependencies: {' '.join(missing)}")
        runner.run(["pacman", "-S", "--needed", "--noconfirm", *missing], privileged=True, stream=True)
    else:
        say("  -> All required build tools and dependencies are already installed.")

    target = resolve_kernel_target(opts.kernel_version, runner.query(["uname", "-r"], ok_to_fail=True).stdout)
    cachy = opts.build_root / "linux-cachyos"
    patches = opts.build_root / "linux_kernel_15khz"
    workdir = cachy / target.subdir
    pkgbuild = workdir / "PKGBUILD"

    say(f"==> [2/6] Fetching CachyOS kernel PKGBUILD ({target.subdir} @ {target.kver}) and 15kHz/interlace patches...")
    _prepare_repos(host, target, cachy, patches)
    if runner.dry_run and not host.exists(pkgbuild):
        say("[dry-run] sources are not fetched yet, so the remaining steps cannot be previewed in detail:")
        say("[dry-run]   [3/6] copy patches, [4/6] GPU rules + PKGBUILD edit, [5/6] makepkg, [6/6] sync initramfs/bootloader")
        return 0
    if not pkgbuild.is_file():
        raise KernelError(f"PKGBUILD not found in {workdir}")

    series = parse_pkgbuild_kver(pkgbuild.read_text(encoding="utf-8", errors="ignore"), target.kver)
    say(f"  -> Target Kernel Series in PKGBUILD: linux-{series} ({target.subdir})")
    available = list_series(patches)
    say(f"  -> Available 15kHz Patch Directories: {' '.join(available)}")
    order = candidate_series(available, target.patch_series, series)
    if not order:
        raise KernelError("no linux-* patch directories were found in the 15kHz patch repository")
    if order[0] not in (target.patch_series, f"linux-{series}"):
        say(f"  -> No exact patch series match; using the latest available: {order[0]}")
    say(f"  -> Selected 15kHz patch directory: {order[0]}")

    say("==> [3/6] Copying official 15kHz, interlace & RDNA DP/HDMI adapter patches...")
    chosen = _verified_patch_set(host, patches, order, workdir, opts.srcdest)
    patch_files = _stage_patches(host, chosen, workdir, rdna_tool if opts.include_rdna else None)

    say(f"==> [4/6] Configuring GPU driver rules and PKGBUILD (GPU Profile '{profile}' + Interlace Patches)...")
    apply_profile(host, profile, gpus, initramfs=False)
    _configure_pkgbuild(host, opts, pkgbuild, patch_files)

    say("==> [5/6] Compiling and installing patched kernel...")
    # -f: this build has just been patched, so an older package of the same version must be replaced, not
    # reinstalled. Without it makepkg either re-installs the previous (unpatched) package or exits 13.
    runner.run(MAKEPKG_BUILD, cwd=workdir, stream=True)

    srcinfo = runner.query(["makepkg", "--printsrcinfo"], cwd=workdir, ok_to_fail=True).stdout
    runner.write_text(
        host.paths.kernel_state_file,
        kernel_record(srcinfo, series, opts.include_rdna, patch_files, int(time.time())),
        privileged=False,
    )

    say("==> [6/6] Syncing initramfs and bootloader...")
    sync_boot(host)
    say("==> SUCCESS! Reboot to load your newly compiled interlaced kernel.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Build and install a 15kHz/interlace-patched CachyOS kernel")
    p.add_argument("--gpu-profile", choices=GPU_PROFILES, default="auto")
    p.add_argument("--adapter-mode", choices=ADAPTER_MODES, default="auto", help="adapter preset (informational)")
    p.add_argument("--kernel-version", default="auto", help="auto | X.Y (e.g. 7.3, 6.12) | linux-next")
    p.add_argument(
        "--processor-opt", default="native",
        help="CachyOS _processor_opt (native = tuned for THIS machine only; empty leaves the PKGBUILD default)",
    )
    p.add_argument("--no-rdna-patch", action="store_true", help="skip the RDNA DP/HDMI DAC source patcher")
    p.add_argument("--config-only", action="store_true", help="apply GPU rules + initramfs only (no kernel build)")
    p.add_argument("--build-root", type=Path, default=None, help="work dir (default: $BUILD_ROOT or ~/kernel-build)")
    p.add_argument("--dry-run", action="store_true", help="print every command that would run; change nothing")
    return p


def main(
    argv: Sequence[str] | None = None, host: Host | None = None, suite_dir: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    env = os.environ if environ is None else environ
    host = host or Host(runner=Runner(dry_run=args.dry_run))
    suite_dir = suite_dir or Path(__file__).resolve().parent

    kver = args.kernel_version
    if kver != "auto" and kver not in RC_ALIASES and not _VERSION_RE.match(kver):
        parser.error(f"--kernel-version must be auto, X.Y or linux-next (got {kver!r})")
    processor_opt = args.processor_opt.strip() or None
    if processor_opt is not None and not _PROCESSOR_OPT_RE.match(processor_opt):
        parser.error(f"--processor-opt contains unsupported characters: {args.processor_opt!r}")
    build_root = args.build_root or Path(env.get("BUILD_ROOT") or host.paths.home / "kernel-build")

    if host.runner.is_root and not args.dry_run:
        print("ERROR: Run this as your normal user, not root/sudo.", file=sys.stderr)
        return 1

    srcdest = Path(env["SRCDEST"]) if env.get("SRCDEST") else None
    opts = KernelOptions(
        gpu_profile=args.gpu_profile, adapter_mode=args.adapter_mode, kernel_version=kver,
        processor_opt=processor_opt, include_rdna=not args.no_rdna_patch, config_only=args.config_only,
        build_root=build_root, srcdest=srcdest,
    )
    try:
        return run_config_only(host, opts) if opts.config_only else run_build(host, opts, suite_dir)
    except (KernelError, PatchError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except (CommandError, PkgbuildError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
