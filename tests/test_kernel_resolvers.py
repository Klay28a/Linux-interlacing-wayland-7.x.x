"""interlace_kernel's pure functions: nothing here touches a filesystem, a process or the network."""

import pytest

import interlace_kernel as ik
from conftest import PKGBUILD_TEXT


def test_resolve_known_series() -> None:
    assert ik.resolve_kernel_target("7.3", "") == ik.KernelTarget("7.3", "linux-cachyos", "origin/master", "linux-7.3")
    assert ik.resolve_kernel_target("7.2", "").commit == ik.PINNED_COMMITS["7.2"]
    for lts in ("6.18", "6.12", "6.6", "6.1"):
        assert ik.resolve_kernel_target(lts, "").subdir == "linux-cachyos-lts"
    rc = ik.resolve_kernel_target("linux-next", "")
    assert (rc.subdir, rc.patch_series) == ("linux-cachyos-rc", "linux-next")


def test_resolve_auto_uses_the_running_kernel() -> None:
    assert ik.resolve_kernel_target("auto", "6.12.9-200.fc41.x86_64\n").kver == "6.12"
    assert ik.resolve_kernel_target("auto", "7.3.1-2-cachyos").subdir == "linux-cachyos"


@pytest.mark.parametrize("bad", ["", "latest", "7", "7.3.1", "../../etc", "6.1; rm -rf /"])
def test_resolve_rejects_garbage(bad: str) -> None:
    with pytest.raises(ik.KernelError):
        ik.resolve_kernel_target(bad, "")


def test_auto_with_unparseable_uname_fails_clearly() -> None:
    with pytest.raises(ik.KernelError, match="--kernel-version"):
        ik.resolve_kernel_target("auto", "weird")


def test_parse_pkgbuild_kver() -> None:
    assert ik.parse_pkgbuild_kver("_major=6.18\npkgver=6.18.3\n", "x") == "6.18"
    assert ik.parse_pkgbuild_kver("pkgver=7.2.11\n", "x") == "7.2"
    assert ik.parse_pkgbuild_kver("nothing\n", "7.3") == "7.3"


def test_nvidia_overrides_matching_version_enables_open_build() -> None:
    ov, notes = ik.nvidia_overrides(
        open_module_pkg_installed=True, installed_nv_ver="580.95.05", nv580_installed=False,
        pkgbuild_text=PKGBUILD_TEXT,
    )
    assert ov == {"_build_nvidia_open": "yes", "_build_nvidia_580xx": "no"}
    assert "enabling" in notes[0]


def test_nvidia_overrides_mismatch_or_missing_disables_open_build() -> None:
    ov, _ = ik.nvidia_overrides(
        open_module_pkg_installed=True, installed_nv_ver="570.1", nv580_installed=True, pkgbuild_text=PKGBUILD_TEXT,
    )
    assert ov == {"_build_nvidia_open": "no"}
    ov, _ = ik.nvidia_overrides(
        open_module_pkg_installed=False, installed_nv_ver="580.95.05", nv580_installed=True,
        pkgbuild_text=PKGBUILD_TEXT,
    )
    assert ov["_build_nvidia_open"] == "no"
