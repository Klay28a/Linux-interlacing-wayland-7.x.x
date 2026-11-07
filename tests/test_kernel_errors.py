"""interlace_kernel failure modes: every one must be a short message and a distinct exit code."""

from pathlib import Path

import pytest

import interlace_kernel as ik
from conftest import arch_pc, make_build_tree, make_suite_dir


def test_build_failure_is_reported_without_traceback(tmp_path: Path, capsys) -> None:
    _, host, runner = arch_pc(tmp_path)
    runner.failing[" ".join(ik.MAKEPKG_BUILD)] = 4
    root = make_build_tree(tmp_path)
    assert ik.main(["--build-root", str(root)], host=host, suite_dir=make_suite_dir(tmp_path)) == 3
    err = capsys.readouterr().err
    assert err.startswith("ERROR: command failed (exit 4)")
    assert "Traceback" not in err
    assert "==> [6/6]" not in "\n".join(runner.messages), "must not sync the bootloader after a failed build"


def test_missing_rdna_tool_is_a_clear_error_unless_disabled(tmp_path: Path, capsys) -> None:
    _, host, _ = arch_pc(tmp_path)
    root = make_build_tree(tmp_path)
    empty = tmp_path / "empty"
    empty.mkdir()
    assert ik.main(["--build-root", str(root)], host=host, suite_dir=empty) == 1
    assert "interlace_rdna_patch.py is missing" in capsys.readouterr().err
    assert ik.main(["--build-root", str(root), "--no-rdna-patch"], host=host, suite_dir=empty) == 0


def test_missing_pkgbuild_is_a_clear_error(tmp_path: Path, capsys) -> None:
    _, host, _ = arch_pc(tmp_path)
    root = make_build_tree(tmp_path, with_pkgbuild=False)
    assert ik.main(["--build-root", str(root)], host=host, suite_dir=make_suite_dir(tmp_path)) == 1
    assert "PKGBUILD not found" in capsys.readouterr().err


def test_no_patch_files_is_a_clear_error(tmp_path: Path, capsys) -> None:
    _, host, _ = arch_pc(tmp_path)
    root = make_build_tree(tmp_path, series=())
    (root / "linux_kernel_15khz" / "linux-7.3").mkdir()
    assert ik.main(["--build-root", str(root)], host=host, suite_dir=make_suite_dir(tmp_path)) == 1
    assert "No 15kHz patch files were found" in capsys.readouterr().err


@pytest.mark.parametrize(
    "argv", [["--kernel-version", "latest"], ["--processor-opt", "na tive; rm"], ["--gpu-profile", "bogus"]],
)
def test_cli_rejects_bad_input_before_touching_anything(argv: list[str], tmp_path: Path) -> None:
    _, host, runner = arch_pc(tmp_path)
    with pytest.raises(SystemExit) as exc:
        ik.main(argv, host=host, suite_dir=make_suite_dir(tmp_path))
    assert exc.value.code == 2
    assert runner.executed == []


def test_refuses_to_run_as_root(tmp_path: Path, capsys) -> None:
    _, host, runner = arch_pc(tmp_path)
    runner.is_root = True
    assert ik.main([], host=host, suite_dir=make_suite_dir(tmp_path)) == 1
    assert "not root" in capsys.readouterr().err
    assert runner.mutating == []
