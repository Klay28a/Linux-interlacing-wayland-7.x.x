#!/usr/bin/env python3
"""
Install an EDID exactly as given and apply it (used by Linux CRU's "Apply" buttons via pkexec).

Unlike ``interlace_setup.py`` this does NOT re-patch the EDID or touch GPU rules: Linux CRU already
built the timings the user wants. It reuses the same tested modules for everything else:
install firmware file -> (debugfs override) -> merge ``drm.edid_firmware`` live -> reprobe the
connector -> with ``--boot``: embed in initramfs, update bootloader command lines, rebuild initramfs.

Runs as root under pkexec (the Runner then adds no sudo) or as a user (it uses sudo). ``--dry-run``
prints every write/command instead of performing it.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Sequence
from pathlib import Path

from interlace_boot import (
    embed_edid_in_initramfs,
    rebuild_initramfs,
    update_bootloaders,
)
from interlace_edid import EDID_HEADER
from interlace_gpu import (
    GPU_PROFILES,
    edid_file_name,
    list_connectors,
    parse_lspci,
    resolve_gpu_profile,
)
from interlace_runner import CommandError, Host, Runner
from interlace_setup import live_reload

_CONN_RE = re.compile(r"[A-Za-z0-9_.-]+")
_REL_FW_RE = re.compile(r"edid/[A-Za-z0-9_.-]+\.bin")


class ApplyError(Exception):
    """A user-facing failure (printed without a traceback)."""


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Install an EDID as-is and apply it live (and optionally at boot)")
    p.add_argument("edid", type=Path, help="EDID .bin file to install")
    p.add_argument("--connector", required=True, help="DRM connector name, e.g. DP-1")
    p.add_argument("--rel-fw", default="", help="firmware-relative name, e.g. edid/cru-dp-1.bin (default: derived)")
    p.add_argument("--boot", action="store_true", help="also embed in initramfs and update bootloader + rebuild")
    p.add_argument("--gpu-profile", choices=GPU_PROFILES, default="auto", help="only affects boot cmdline flags")
    p.add_argument("--dry-run", action="store_true")
    return p


def load_edid(path: Path) -> bytes:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ApplyError(f"Cannot read EDID {path}: {exc}") from exc
    if len(data) < 128 or data[:8] != EDID_HEADER:
        raise ApplyError(f"{path} is not a valid EDID (bad header or shorter than 128 bytes)")
    return data


def write_debugfs_override(host: Host, conn: str, data: bytes) -> None:
    """Best-effort ``/sys/kernel/debug/dri/N/<conn>/edid_override`` (needs root + debugfs)."""
    for entry in sorted(host.paths.drm_class.glob(f"card*-{conn}")) if host.paths.drm_class.is_dir() else []:
        m = re.match(r"card(\d+)-", entry.name)
        if not m:
            continue
        node = host.paths.debugfs_dri / m.group(1) / conn / "edid_override"
        if host.exists(node):
            host.runner.write_raw(node, data)


def apply_edid(args: argparse.Namespace, host: Host) -> int:
    runner, paths = host.runner, host.paths
    conn = args.connector
    if not _CONN_RE.fullmatch(conn):
        raise ApplyError(f"Invalid connector name: {conn!r}")
    rel_fw = args.rel_fw or f"edid/{edid_file_name(conn)}"
    if not _REL_FW_RE.fullmatch(rel_fw):
        raise ApplyError(f"Invalid firmware name: {rel_fw!r} (expected edid/<name>.bin)")
    data = load_edid(args.edid)
    dest = paths.firmware_edid_dir.parent / rel_fw

    runner.say(f"==> Installing EDID for {conn} at {dest}...")
    runner.install_bytes(dest, data)
    write_debugfs_override(host, conn, data)
    live_reload(host, conn, rel_fw)

    if args.boot:
        gpus = parse_lspci(_lspci(host))
        profile = resolve_gpu_profile(args.gpu_profile, gpus, [c.name for c in list_connectors(paths.drm_class)])
        runner.say("==> Embedding EDID in initramfs and updating bootloader...")
        embedded = embed_edid_in_initramfs(host, dest)
        runner.say(f"  -> Initramfs configs updated: {', '.join(embedded) or 'none found'}")
        updated = update_bootloaders(host, conn, rel_fw, profile)
        runner.say(f"  -> Bootloader configs updated: {', '.join(updated) or 'none found'}")
        rebuild_initramfs(host)
    runner.say(f"==> Done: {conn} -> {rel_fw}{' (boot persistent)' if args.boot else ' (live only)'}")
    return 0


def _lspci(host: Host) -> str:
    res = host.runner.query(["lspci", "-D", "-nn"], ok_to_fail=True)
    return res.stdout if res.returncode == 0 else ""


def main(argv: Sequence[str] | None = None, host: Host | None = None) -> int:
    args = build_parser().parse_args(argv)
    host = host or Host(runner=Runner(dry_run=args.dry_run))
    try:
        return apply_edid(args, host)
    except ApplyError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except CommandError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
