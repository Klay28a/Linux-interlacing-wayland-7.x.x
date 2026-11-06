#!/usr/bin/env python3
"""
CachyOS PKGBUILD editor for the patched 15kHz/interlace kernel build.

Replaces the ``sed -i`` calls and the heredoc in ``fix-interlaced-kernel.sh``. ``transform`` is a
pure ``str -> str`` function (so tests feed a mock PKGBUILD); ``main`` is the CLI the shell script
calls, with ``--dry-run`` to report the change without writing.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

RDNA_HOOK = (
    '\n    echo "Applying universal RDNA DCN & DP/HDMI DAC Interlace Unlock..."\n'
    "    python3 ../apply_rdna_dac_unlock.py\n"
)
RDNA_ANCHOR = 'echo "Setting config..."'
BLOCK_MARKER = "# --- Custom 15kHz & Interlace Patches ---"
PLACEHOLDER_SUM = "0" * 128


class PkgbuildError(Exception):
    """A user-facing failure (printed without a traceback)."""


def strip_previous(txt: str) -> str:
    """Remove a block this tool added earlier, so re-running never duplicates sources/hooks/checksums.

    Exactly reverses ``add_patches`` (patch block, RDNA hook and trailing ``b2sums+=``); text this tool
    did not write is left alone.
    """
    if BLOCK_MARKER not in txt:
        return txt
    txt = re.sub(
        r"\n" + re.escape(BLOCK_MARKER) + r"\nsource\+=\(\n(?:  \"[^\"\n]*\"\n)*\)\n", "", txt,
    )
    txt = txt.replace(RDNA_HOOK + "    " + RDNA_ANCHOR, RDNA_ANCHOR)
    return re.sub(r"\n\nb2sums\+=\(\n(?:  '[^'\n]*'\n)*\)\n\Z", "\n", txt)


def set_default(txt: str, var: str, value: str) -> str:
    """Rewrite the ``: "${var:=old}"`` default of a PKGBUILD variable to ``value``."""
    return re.sub(r': "\$\{' + re.escape(var) + r':=[^}]*\}"', lambda _m: f': "${{{var}:={value}}}"', txt)


def relax_constraints(txt: str) -> str:
    """Relax pahole's pkgrel constraint and the exact nvidia-utils pin so makepkg does not abort."""
    txt = re.sub(r"'pahole>=[^']*'", "'pahole'", txt)
    return re.sub(r'"nvidia-utils=\$\{_nv_ver\}"', '"nvidia-utils"', txt)


def add_patches(txt: str, patches: Sequence[str], sums: Sequence[str], include_rdna: bool) -> str:
    """Append the patch ``source+=`` block, the RDNA hook in prepare(), and the matching b2sums."""
    block_lines = [f"\n{BLOCK_MARKER}", "source+=("]
    block_lines += [f'  "{p}"' for p in patches]
    block_lines.append(")\n")
    block = "\n".join(block_lines)
    idx = txt.find("\nprepare()")
    txt = (txt[:idx] + block + txt[idx:]) if idx != -1 else (txt + block)

    if include_rdna and RDNA_ANCHOR in txt:
        txt = txt.replace(RDNA_ANCHOR, RDNA_HOOK + "    " + RDNA_ANCHOR, 1)

    sum_lines = ["\nb2sums+=("] + [f"  '{h}'" for h in sums] + [")\n"]
    return txt.rstrip() + "\n" + "\n".join(sum_lines)


def transform(
    txt: str,
    patches: Sequence[str],
    sums: Sequence[str],
    include_rdna: bool,
    defaults: dict[str, str],
    processor_opt: str | None,
) -> str:
    """Full PKGBUILD transform (idempotent). ``defaults`` maps variable -> new default value."""
    txt = strip_previous(txt)
    if processor_opt is not None and "_use_auto_optimization" not in txt:
        txt = set_default(txt, "_processor_opt", processor_opt)
    for var, value in defaults.items():
        txt = set_default(txt, var, value)
    txt = relax_constraints(txt)
    return add_patches(txt, patches, sums, include_rdna)


def blake2b_hex(path: Path) -> str:
    return hashlib.blake2b(path.read_bytes()).hexdigest()


def run(
    pkgbuild: Path,
    patches: Sequence[str],
    include_rdna: bool,
    defaults: dict[str, str],
    processor_opt: str | None,
    dry_run: bool,
    say: Callable[[str], None] = print,
) -> str:
    """Transform ``pkgbuild`` (patch files are resolved relative to its directory) and return the new text."""
    base = pkgbuild.parent
    sums: list[str] = []
    for p in patches:
        f = base / p
        if f.is_file():
            sums.append(blake2b_hex(f))
        elif dry_run:
            # A dry run did not copy the file yet, so there is nothing to hash.
            say(f"[dry-run]   (not copied yet; placeholder checksum for {p})")
            sums.append(PLACEHOLDER_SUM)
        else:
            raise PkgbuildError(f"patch file not found next to the PKGBUILD: {f}")
    old = pkgbuild.read_text(encoding="utf-8")
    new = transform(old, patches, sums, include_rdna, defaults, processor_opt)
    if dry_run:
        say(f"[dry-run] would rewrite {pkgbuild} ({len(old)} -> {len(new)} bytes)")
        for p in patches:
            say(f"[dry-run]   + source patch: {p}")
        for var, value in defaults.items():
            say(f"[dry-run]   + {var} default := {value}")
        if processor_opt is not None:
            say(f"[dry-run]   + _processor_opt default := {processor_opt} (unless _use_auto_optimization)")
        if include_rdna:
            say("[dry-run]   + prepare() hook: python3 ../apply_rdna_dac_unlock.py")
    else:
        pkgbuild.write_text(new, encoding="utf-8")
    return new


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Add 15kHz/interlace patches to a CachyOS PKGBUILD")
    p.add_argument("pkgbuild", type=Path)
    p.add_argument("patches", nargs="*", help="patch file names (relative to the PKGBUILD directory)")
    p.add_argument("--include-rdna", action="store_true", help="hook apply_rdna_dac_unlock.py into prepare()")
    p.add_argument("--set", action="append", default=[], metavar="VAR=VALUE", help="override a ': \"${VAR:=...}\"' default")
    p.add_argument("--processor-opt", default=None, help="value for _processor_opt (omit to leave unchanged)")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)

    defaults: dict[str, str] = {}
    for item in args.set:
        var, sep, value = item.partition("=")
        if not sep or not var:
            p.error(f"--set expects VAR=VALUE, got {item!r}")
        defaults[var] = value
    try:
        run(args.pkgbuild, args.patches, args.include_rdna, defaults, args.processor_opt, args.dry_run)
    except (PkgbuildError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
