"""interlace_patches: reading patch headers, archives and srcinfo, plus the fetch/plan CLI (all offline)."""

import io
import tarfile
from pathlib import Path

import interlace_patches as ip
from conftest import FakeRunner
from test_patches import NUMS, make_repo


def test_touched_files_reads_plus_plus_plus_headers(tmp_path: Path) -> None:
    patch = tmp_path / "x.patch"
    patch.write_text(
        "--- a/drivers/a.c\t2026\n+++ b/drivers/a.c\t2026\n@@\n--- /dev/null\n+++ b/new/file.h\n"
        "--- a/gone.c\n+++ /dev/null\n", encoding="utf-8",
    )
    assert ip.touched_files([patch]) == {"drivers/a.c", "new/file.h"}


def test_extract_files_pulls_only_the_requested_files(tmp_path: Path) -> None:
    tarball = tmp_path / "kernel.tar.gz"
    with tarfile.open(tarball, "w:gz") as tar:
        for name, data in (("linux-1/a/x.c", b"X"), ("linux-1/a/y.c", b"Y"), ("linux-1/z.h", b"Z")):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    dest = tmp_path / "out"
    assert ip.extract_files(tarball, {"a/x.c", "z.h", "missing.c"}, dest) == 2
    assert (dest / "a/x.c").read_bytes() == b"X"
    assert not (dest / "a/y.c").exists()


def test_kernel_source_name_skips_nvidia_and_non_archives() -> None:
    info = (
        "pkgbase = linux-cachyos\n"
        "\tsource = https://cdn.kernel.org/pub/linux/kernel/v7.x/linux-7.3.tar.xz\n"
        "\tsource = NVIDIA-kernel-module-source-615.78.08.tar.xz::https://github.com/x/y.tar.xz\n"
    )
    assert ip.kernel_source_name(info) == "linux-7.3.tar.xz"
    nvidia_first = "\tsource = NVIDIA-x.tar.xz\n\tsource = cachyos-7.3.1-1.tar.gz::https://x/y\n"
    assert ip.kernel_source_name(nvidia_first) == "cachyos-7.3.1-1.tar.gz"
    assert ip.kernel_source_name("\tsource = a.patch\n\tsource = config\n") is None


def test_fetch_repo_clones_when_absent_and_updates_when_present(tmp_path: Path) -> None:
    repo = tmp_path / "kb" / "linux_kernel_15khz"
    r = FakeRunner(dry_run=True)
    ip.fetch_repo(r, repo)
    assert any("git clone --depth 1 https://github.com/D0023R/linux_kernel_15khz.git" in m for m in r.messages)
    (repo / ".git").mkdir(parents=True)
    r2 = FakeRunner(dry_run=True)
    ip.fetch_repo(r2, repo)
    text = "\n".join(r2.messages)
    assert "fetch --depth 1 origin" in text
    assert "reset --hard FETCH_HEAD" in text
    assert "git clone" not in text


def test_cli_plan_lists_the_series_it_would_use(tmp_path: Path, capsys) -> None:
    repo = make_repo(tmp_path, {"linux-6.12": ("01", "02", "03"), "linux-7.3": NUMS})
    assert ip.main(["plan", "--kernel-version", "6.12", "--repo", str(repo)]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "01  linux-6.12/01_linux-6.12.patch",
        "02  linux-6.12/02_linux-6.12.patch",
        "03  linux-6.12/03_linux-6.12.patch",
    ]
