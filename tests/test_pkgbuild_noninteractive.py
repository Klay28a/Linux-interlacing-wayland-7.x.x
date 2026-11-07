"""Regression for the hung/failed kernel builds in the second user log.

* every CachyOS prepare() ran ``make prepare`` before ``olddefconfig``; ``syncconfig`` then asked
  ``(NEW)`` Kconfig questions on a stdin nobody could answer, so the GUI sat there forever;
* 6.1/6.6 host tools (libbpf, objtool) are built with a bare ``-Werror`` that modern GCC rejects.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

import interlace_pkgbuild as pb
from interlace_runner import Runner

MODERN = """pkgname=linux-cachyos
: "${_processor_opt:=}"
: "${_build_nvidia_open:=yes}"
prepare() {
    echo "Setting config..."
    ### Rewrite configuration
    echo "Rewrite configuration..."
    make "${BUILD_FLAGS[@]}" prepare
    yes "" | make "${BUILD_FLAGS[@]}" config >/dev/null
    make -s kernelrelease > version
}
"""
LEGACY = """pkgname=linux-cachyos-lts
_processor_opt=${_processor_opt-}
_build_nvidia_open=${_build_nvidia_open-y}
prepare() {
    echo "Setting config..."
    echo "Rewrite configuration..."
    make ${BUILD_FLAGS[*]} prepare
    yes "" | make ${BUILD_FLAGS[*]} config >/dev/null
}
"""


@pytest.mark.parametrize("pkgbuild", [MODERN, LEGACY], ids=["modern", "legacy"])
def test_olddefconfig_runs_before_prepare_and_stdin_is_closed(pkgbuild: str) -> None:
    out = pb.make_noninteractive(pkgbuild)
    lines = [ln.strip() for ln in out.splitlines()]
    prepare = next(i for i, ln in enumerate(lines) if re.fullmatch(r"make \S+ prepare", ln))
    olddef = next(i for i, ln in enumerate(lines) if "olddefconfig" in ln)
    assert lines.index("exec < /dev/null") < olddef < prepare
    assert any("-Werror" in ln and ln.startswith("find ") for ln in lines[:prepare])
    # the kernel's own flags spelling is preserved so clang/LLVM builds keep working
    flags = "${BUILD_FLAGS[@]}" if "[@]" in pkgbuild else "${BUILD_FLAGS[*]}"
    assert any(ln.startswith("make ") and flags in ln and "olddefconfig" in ln for ln in lines)


def test_noninteractive_block_is_idempotent_and_reversible() -> None:
    once = pb.transform(MODERN, ["01_a.patch"], ["h"], False, {}, None)
    twice = pb.transform(once, ["01_a.patch"], ["h"], False, {}, None)
    assert once == twice
    assert once.count(pb.NI_BEGIN) == 1
    assert pb.NI_BEGIN not in pb.strip_previous(once)


def test_pkgbuild_without_a_prepare_make_line_is_left_alone() -> None:
    assert pb.make_noninteractive("prepare() {\n    :\n}\n") == "prepare() {\n    :\n}\n"


@pytest.mark.parametrize("pkgbuild", [MODERN, LEGACY], ids=["modern", "legacy"])
def test_generated_pkgbuild_is_valid_bash(pkgbuild: str, tmp_path: Path) -> None:
    f = tmp_path / "PKGBUILD"
    f.write_text(pb.transform(pkgbuild, ["01_a.patch"], ["h"], True, {"_build_nvidia_open": "no"}, "native"))
    subprocess.run(["bash", "-n", str(f)], check=True, capture_output=True, text=True)


def test_set_default_handles_both_cachyos_styles() -> None:
    assert ': "${_build_nvidia_open:=no}"' in pb.set_default(MODERN, "_build_nvidia_open", "no")
    # legacy: any non-empty value means "on", so "no" must become empty and "yes" must become "y"
    assert "_build_nvidia_open=${_build_nvidia_open-}" in pb.set_default(LEGACY, "_build_nvidia_open", "no")
    assert "_build_nvidia_open=${_build_nvidia_open-y}" in pb.set_default(LEGACY, "_build_nvidia_open", "yes")
    assert "_processor_opt=${_processor_opt-native}" in pb.set_default(LEGACY, "_processor_opt", "native")
    assert pb.set_default(LEGACY, "_not_there", "no") == LEGACY


def test_transform_actually_changes_a_legacy_pkgbuild() -> None:
    out = pb.transform(LEGACY, [], [], False, {"_build_nvidia_open": "no"}, "native")
    assert "_processor_opt=${_processor_opt-native}" in out
    assert "_build_nvidia_open=${_build_nvidia_open-}" in out


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash required")
def test_the_inserted_werror_sed_strips_only_a_bare_werror(tmp_path: Path) -> None:
    mk = tmp_path / "tools" / "lib" / "bpf" / "Makefile"
    mk.parent.mkdir(parents=True)
    mk.write_text("override CFLAGS += -Werror -Wall\nCFLAGS := -Werror=shadow -Werror\nX := foo-Werror\n")
    block = pb.noninteractive_block("", "${BUILD_FLAGS[*]}")
    find_line = next(ln for ln in block.splitlines() if ln.startswith("find "))
    subprocess.run(["bash", "-c", find_line], cwd=tmp_path, check=True, capture_output=True, text=True)
    text = mk.read_text()
    assert "-Werror -Wall" not in text
    assert "-Wall" in text
    assert "-Werror=shadow" in text, "the specific -Werror=<warning> flag must survive"
    assert "foo-Werror" in text, "only a standalone -Werror token may be removed"


def test_runner_children_never_inherit_stdin(tmp_path: Path) -> None:
    """A child that tries to read must see EOF immediately rather than blocking on our stdin."""
    script = "import sys; sys.stdout.write('got:' + repr(sys.stdin.read()))"
    res = Runner(is_root=True, interactive=False)._exec(["python3", "-c", script], False)
    assert res.stdout == "got:''"
