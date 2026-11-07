"""The complete 6-step kernel workflow for every kernel choice the GUI offers, on the Arch fixture."""

import re
from pathlib import Path

import pytest

import interlace_kernel as ik
from conftest import arch_pc, make_build_tree, make_suite_dir

GUI_KERNELS = ("auto", "7.3", "7.2", "6.18", "6.12", "6.6", "6.1", "linux-next")
MAKEPKG = ik.MAKEPKG_BUILD


@pytest.mark.parametrize("kver", GUI_KERNELS)
def test_every_gui_kernel_choice_builds_end_to_end(kver: str, tmp_path: Path) -> None:
    _, host, runner = arch_pc(tmp_path)
    root = make_build_tree(tmp_path)
    args = ["--kernel-version", kver, "--build-root", str(root)]
    assert ik.main(args, host=host, suite_dir=make_suite_dir(tmp_path)) == 0, "\n".join(runner.messages)
    text = "\n".join(runner.messages)
    for step in range(1, 7):
        assert f"==> [{step}/6]" in text, f"progress marker {step}/6 missing for {kver}"
    target = ik.resolve_kernel_target(kver, "7.3.1-2-cachyos")
    workdir = root / "linux-cachyos" / target.subdir
    assert MAKEPKG in runner.executed
    assert workdir in runner.cwds, "makepkg must run inside the selected PKGBUILD directory"
    pkgbuild = (workdir / "PKGBUILD").read_text(encoding="utf-8")
    assert "01_" in pkgbuild
    assert "apply_rdna_dac_unlock.py" in pkgbuild
    assert (workdir / "apply_rdna_dac_unlock.py").is_file()
    assert re.search(r"^b2sums\+=\(", pkgbuild, re.MULTILINE)
    assert "SUCCESS" in text
    assert ["sudo", "-n", "limine-mkinitcpio"] in runner.executed, "step 6 must sync the initramfs"


def test_build_stages_only_the_numbered_patches(tmp_path: Path) -> None:
    _, host, _ = arch_pc(tmp_path)
    root = make_build_tree(tmp_path)
    assert ik.main(["--kernel-version", "6.12", "--build-root", str(root)], host=host, suite_dir=make_suite_dir(tmp_path)) == 0
    staged = sorted(p.name for p in (root / "linux-cachyos" / "linux-cachyos-lts").glob("*.patch"))
    assert staged == [f"{n}_linux-6.12.patch" for n in ("01", "02", "03", "04", "05", "07", "08", "09")]


def test_pinned_commit_falls_back_to_master_when_unavailable(tmp_path: Path) -> None:
    _, host, runner = arch_pc(tmp_path)
    repo = tmp_path / "kb" / "linux-cachyos"
    runner.failing[f"git -C {repo} fetch --depth 1 origin {ik.PINNED_COMMITS['7.2']}"] = 128
    root = make_build_tree(tmp_path)
    args = ["--kernel-version", "7.2", "--build-root", str(root)]
    assert ik.main(args, host=host, suite_dir=make_suite_dir(tmp_path)) == 0
    assert "is unavailable; using current master" in "\n".join(runner.messages)
    assert not any(c[-1] == ik.PINNED_COMMITS["7.2"] and "reset" in c for c in runner.executed)
    assert any(c[-2:] == ["reset", "--hard"] or c[-3:] == ["reset", "--hard", "FETCH_HEAD"] for c in runner.executed)


def test_missing_patch_series_uses_latest_and_says_so(tmp_path: Path) -> None:
    _, host, runner = arch_pc(tmp_path)
    root = make_build_tree(tmp_path, series=("linux-6.1", "linux-6.12"))
    args = ["--kernel-version", "7.3", "--build-root", str(root)]
    assert ik.main(args, host=host, suite_dir=make_suite_dir(tmp_path)) == 0
    assert "using the latest available: linux-6.12" in "\n".join(runner.messages)


def test_dry_run_build_changes_nothing(tmp_path: Path) -> None:
    _, host, runner = arch_pc(tmp_path, dry_run=True)
    root = make_build_tree(tmp_path)
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    assert ik.main(["--dry-run", "--build-root", str(root)], host=host, suite_dir=make_suite_dir(tmp_path)) == 0
    assert {p: p.read_bytes() for p in root.rglob("*") if p.is_file()} == before
    assert MAKEPKG not in runner.executed
    text = "\n".join(runner.messages)
    assert "[dry-run] would run: makepkg -Csfi -f --noconfirm --skipinteg" in text
    assert "[dry-run] would copy" in text


def test_dry_run_before_first_fetch_explains_itself(tmp_path: Path) -> None:
    _, host, runner = arch_pc(tmp_path, dry_run=True)
    root = tmp_path / "fresh"
    assert ik.main(["--dry-run", "--build-root", str(root)], host=host, suite_dir=make_suite_dir(tmp_path)) == 0
    text = "\n".join(runner.messages)
    assert "sources are not fetched yet" in text
    assert "git clone" in text
    assert not root.exists()


def test_empty_processor_opt_leaves_pkgbuild_default(tmp_path: Path) -> None:
    _, host, _ = arch_pc(tmp_path)
    root = make_build_tree(tmp_path)
    args = ["--processor-opt", "", "--build-root", str(root)]
    assert ik.main(args, host=host, suite_dir=make_suite_dir(tmp_path)) == 0
    text = (root / "linux-cachyos" / "linux-cachyos" / "PKGBUILD").read_text(encoding="utf-8")
    assert ': "${_processor_opt:=}"' in text


def test_build_root_comes_from_environment(tmp_path: Path) -> None:
    _, host, runner = arch_pc(tmp_path, dry_run=True)
    env = {"BUILD_ROOT": str(tmp_path / "custom")}
    assert ik.main(["--dry-run"], host=host, suite_dir=make_suite_dir(tmp_path), environ=env) == 0
    assert str(tmp_path / "custom" / "linux-cachyos") in "\n".join(runner.messages)
