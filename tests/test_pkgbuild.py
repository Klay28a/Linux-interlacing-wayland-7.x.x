"""PKGBUILD editing against a mock CachyOS PKGBUILD."""

import hashlib
from pathlib import Path

import interlace_pkgbuild as pb

MOCK = """pkgname=linux-cachyos
: "${_processor_opt:=}"
: "${_build_nvidia_open:=yes}"
: "${_build_nvidia_580xx:=yes}"
makedepends=('pahole>=1:1.32-2' "nvidia-utils=${_nv_ver}")
source=("a.tar.xz")
b2sums=('x')

prepare() {
    echo "Setting config..."
}
"""


def test_set_default_rewrites_only_named_variable():
    out = pb.set_default(MOCK, "_build_nvidia_open", "no")
    assert ': "${_build_nvidia_open:=no}"' in out
    assert ': "${_build_nvidia_580xx:=yes}"' in out


def test_relax_constraints():
    out = pb.relax_constraints(MOCK)
    assert "'pahole'" in out
    assert "pahole>=" not in out
    assert '"nvidia-utils"' in out


def test_add_patches_source_block_before_prepare_and_sums_at_end():
    out = pb.add_patches(MOCK, ["01_a.patch", "02_b.patch"], ["h1", "h2"], include_rdna=False)
    assert out.index('"02_b.patch"') < out.index("\nprepare()")
    assert out.rstrip().endswith(")")
    assert "b2sums+=(\n  'h1'\n  'h2'\n)" in out


def test_rdna_hook_inserted_once_before_setting_config():
    out = pb.add_patches(MOCK, ["01_a.patch"], ["h1"], include_rdna=True)
    assert out.count("apply_rdna_dac_unlock.py") == 1
    assert out.index("apply_rdna_dac_unlock.py") < out.index('echo "Setting config..."')


def test_processor_opt_skipped_when_auto_optimization_present():
    txt = MOCK + "# _use_auto_optimization\n"
    out = pb.transform(txt, [], [], False, {}, "native")
    assert ': "${_processor_opt:=}"' in out
    assert ': "${_processor_opt:=native}"' in pb.transform(MOCK, [], [], False, {}, "native")
    assert ': "${_processor_opt:=}"' in pb.transform(MOCK, [], [], False, {}, None)


def test_run_dry_run_writes_nothing_and_real_run_hashes_patches(tmp_path: Path):
    (tmp_path / "PKGBUILD").write_text(MOCK)
    patch = tmp_path / "01_a.patch"
    patch.write_text("diff\n")
    msgs: list[str] = []
    pb.run(tmp_path / "PKGBUILD", ["01_a.patch"], True, {"_build_nvidia_open": "no"}, "native", True, msgs.append)
    assert (tmp_path / "PKGBUILD").read_text() == MOCK
    assert any("would rewrite" in m for m in msgs)

    new = pb.run(tmp_path / "PKGBUILD", ["01_a.patch"], True, {"_build_nvidia_open": "no"}, "native", False)
    assert (tmp_path / "PKGBUILD").read_text() == new
    assert hashlib.blake2b(b"diff\n").hexdigest() in new


def test_transform_is_idempotent_on_an_already_patched_pkgbuild():
    """Regression: a PKGBUILD left over from a previous run must not get a second block/hook/b2sums."""
    once = pb.transform(MOCK, ["01_a.patch"], ["h1"], True, {"_build_nvidia_open": "no"}, "native")
    twice = pb.transform(once, ["01_a.patch"], ["h1"], True, {"_build_nvidia_open": "no"}, "native")
    assert twice == once
    assert twice.count("Custom 15kHz") == 1
    assert twice.count("python3 ../apply_rdna_dac_unlock.py") == 1  # the prepare() hook, exactly once
    assert twice.count("b2sums+=(") == 1


def test_rerun_with_different_patch_set_replaces_the_old_block():
    first = pb.transform(MOCK, ["01_a.patch", "02_b.patch"], ["h1", "h2"], True, {}, None)
    second = pb.transform(first, ["01_a.patch"], ["h9"], False, {}, None)
    assert "02_b.patch" not in second
    assert "apply_rdna_dac_unlock" not in second
    assert "'h2'" not in second
    assert "'h9'" in second


def test_strip_previous_leaves_unrelated_pkgbuilds_alone():
    assert pb.strip_previous(MOCK) == MOCK


def test_dry_run_uses_placeholder_checksum_for_patches_not_copied_yet(tmp_path: Path):
    """Regression: `fix-interlaced-kernel.sh --dry-run` crashed because the patches are only copied in a real run."""
    (tmp_path / "PKGBUILD").write_text(MOCK)
    msgs: list[str] = []
    new = pb.run(tmp_path / "PKGBUILD", ["01_missing.patch"], False, {}, None, True, msgs.append)
    assert pb.PLACEHOLDER_SUM in new
    assert (tmp_path / "PKGBUILD").read_text() == MOCK
    assert any("placeholder checksum for 01_missing.patch" in m for m in msgs)


def test_real_run_with_missing_patch_is_a_clean_error_not_a_traceback(tmp_path: Path, capsys):
    (tmp_path / "PKGBUILD").write_text(MOCK)
    assert pb.main([str(tmp_path / "PKGBUILD"), "01_missing.patch"]) == 2
    assert "patch file not found" in capsys.readouterr().err
    assert (tmp_path / "PKGBUILD").read_text() == MOCK


def test_cli_rejects_malformed_set(tmp_path: Path, capsys):
    (tmp_path / "PKGBUILD").write_text(MOCK)
    try:
        pb.main([str(tmp_path / "PKGBUILD"), "--set", "oops"])
    except SystemExit as exc:
        assert exc.code == 2
    assert "VAR=VALUE" in capsys.readouterr().err
