"""Shared pytest fixtures: a hermetic Host that never touches real hardware or the real filesystem."""

import json
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from interlace_runner import CommandError, Host, Runner, SystemPaths

pytest_plugins = ("gui_fixtures",)  # the offscreen-Qt fixtures live in their own module

LSPCI_RDNA_ONLY = "0000:03:00.0 VGA compatible controller [0300]: AMD Navi 22 [Radeon RX 6700 XT] [1002:73df]\n"
LSPCI_NV_AMD = (
    "0000:01:00.0 VGA compatible controller [0300]: NVIDIA GA104 [GeForce RTX 3070] [10de:2484]\n"
    "0000:03:00.0 VGA compatible controller [0300]: AMD Oland [Radeon R7 250] [1002:6610]\n"
    "0000:00:14.0 USB controller [0c03]: Intel Corp. [8086:1234]\n"
)
LSPCI_GCN_ONLY = "0000:03:00.0 VGA compatible controller [0300]: AMD Oland [Radeon R7 250] [1002:6610]\n"


class FakeRunner(Runner):
    """Runner whose only subprocess/write entry points are recorded instead of executed."""

    def __init__(
        self, dry_run: bool = False, lspci: str = "", is_root: bool = False,
        environ: dict[str, str] | None = None, interactive: bool = False,
    ) -> None:
        self.messages: list[str] = []
        super().__init__(
            dry_run=dry_run, out=self.messages.append, is_root=is_root, sleep=lambda _s: None,
            environ={} if environ is None else environ, interactive=interactive,
        )
        self.lspci = lspci
        self.executed: list[list[str]] = []
        self.installed: dict[str, bytes] = {}
        self.queries_ok: dict[str, str] = {}
        self.failing: dict[str, int] = {}
        self.cwds: list[Path | None] = []

    def _exec(
        self, cmd: Sequence[str], ok_to_fail: bool, input_text: str | None = None,
        *, stream: bool = False, cwd: Path | None = None,
    ):
        argv = [str(c) for c in cmd]
        self.executed.append(argv)
        self.cwds.append(cwd)
        if argv[0] == "lspci":
            return subprocess.CompletedProcess(argv, 0, self.lspci, "")
        key = " ".join(argv)
        # canned results: full command line first, then the command's last argument
        for candidate in (key, argv[-1]):
            if candidate in self.failing:
                if not ok_to_fail:
                    raise CommandError(f"command failed (exit {self.failing[candidate]}): {key}")
                return subprocess.CompletedProcess(argv, self.failing[candidate], "", "simulated failure")
            if candidate in self.queries_ok:
                return subprocess.CompletedProcess(argv, 0, self.queries_ok[candidate], "")
        return subprocess.CompletedProcess(argv, 0, "", "")

    def _install(self, path: Path, data: bytes, mode: int, privileged: bool) -> None:
        self.executed.append(["INSTALL", str(path), f"{mode:04o}", "sudo" if privileged else "user"])
        self.installed[str(path)] = data

    def write_raw(self, path: Path, data: bytes) -> bool:
        self.executed.append(["RAW", str(path), str(len(data))])
        self.installed[str(path)] = data
        return True

    @property
    def mutating(self) -> list[list[str]]:
        return [c for c in self.executed if c[0] != "lspci"]


def make_paths(root: Path) -> SystemPaths:
    return SystemPaths(
        drm_class=root / "sys/class/drm",
        edid_firmware_param=root / "sys/module/drm/parameters/edid_firmware",
        debugfs_dri=root / "sys/kernel/debug/dri",
        firmware_edid_dir=root / "usr/lib/firmware/edid",
        udev_rules_dir=root / "etc/udev/rules.d",
        modprobe_dir=root / "etc/modprobe.d",
        mkinitcpio_conf=root / "etc/mkinitcpio.conf",
        dracut_conf_dir=root / "etc/dracut.conf.d",
        initramfs_hooks_dir=root / "etc/initramfs-tools/hooks",
        default_limine=root / "etc/default/limine",
        default_grub=root / "etc/default/grub",
        kernel_cmdline=root / "etc/kernel/cmdline",
        loader_entry_dirs=(root / "boot/loader/entries",),
        grub_cfg_candidates=(root / "boot/grub/grub.cfg", root / "boot/grub2/grub.cfg"),
        proc_cmdline=root / "proc/cmdline",
        modules_dir=root / "usr/lib/modules",
        system_bin_dirs=(root / "usr/local/bin", root / "usr/bin"),
        home=root / "home/tester",
    )


def add_connector(root: Path, name: str, status: str, card: str = "card0") -> None:
    d = root / "sys/class/drm" / f"{card}-{name}"
    d.mkdir(parents=True, exist_ok=True)
    (d / "status").write_text(status + "\n", encoding="utf-8")


def assert_sandboxed(paths: SystemPaths, root: Path) -> None:
    """Fail loudly if ANY SystemPaths field escapes the temp dir (a test could otherwise touch the host)."""
    for name in paths.__dataclass_fields__:
        value = getattr(paths, name)
        for p in (value if isinstance(value, tuple) else (value,)):
            assert Path(p).is_relative_to(root), f"SystemPaths.{name}={p} escapes the sandbox {root}"


@pytest.fixture
def sandbox(tmp_path: Path):
    paths = make_paths(tmp_path)
    assert_sandboxed(paths, tmp_path)
    return tmp_path, paths


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
FIXTURE_NAMES = (
    "pc_cachyos_nvme_limine_dual_gpu",
    "pc_fedora_nvme_systemd_boot_rdna",
    "pc_ubuntu_sata_grub_gcn",
)


def load_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURE_DIR / f"{name}.json").read_text(encoding="utf-8"))


def materialize_fixture(pc: dict[str, Any], root: Path) -> None:
    """Create the mock PC's config files and DRM connectors inside the sandbox ``root``."""
    for rel, content in pc.get("files", {}).items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    for rel in pc.get("exists", []):
        target = root / rel.lstrip("/")
        if not target.exists():  # files from "files" are already there; anything else is a directory
            target.mkdir(parents=True, exist_ok=True)
    for conn in pc["connectors"]:
        add_connector(root, conn["name"], conn["status"], conn["card"])


class FixtureRunner(FakeRunner):
    """FakeRunner that answers read-only queries (lspci, uname, bootctl, pacman) from a PC fixture."""

    def __init__(self, pc: dict[str, Any], dry_run: bool = False) -> None:
        super().__init__(dry_run=dry_run, lspci=pc["lspci"])
        self.pc = pc
        self.queries_ok.update({"-r": pc["uname_r"] + "\n"})
        for flag, value in pc.get("bootctl", {}).items():
            self.queries_ok[flag] = value + "\n"

    def _exec(self, cmd, ok_to_fail, input_text=None, *, stream=False, cwd=None):
        argv = [str(c) for c in cmd]
        if argv[0] == "pacman" and "-T" in argv:
            self.executed.append(argv)
            self.cwds.append(cwd)
            return subprocess.CompletedProcess(argv, 0, "", "")  # nothing missing
        if argv[0] == "pacman" and any(a in argv for a in ("-Qq", "-Q")):
            self.executed.append(argv)
            self.cwds.append(cwd)
            return subprocess.CompletedProcess(argv, 1, "", "not installed")
        return super()._exec(cmd, ok_to_fail, input_text, stream=stream, cwd=cwd)


def build_fixture_host(
    pc: dict[str, Any], root: Path, paths: SystemPaths, *, dry_run: bool = False,
) -> tuple[Host, FixtureRunner]:
    """A Host for ``pc``: its tools are the only ones on PATH, its files live under the sandbox ``root``."""
    runner = FixtureRunner(pc, dry_run=dry_run)
    present = set(pc["which"])
    host = Host(
        runner=runner, paths=paths,
        which=lambda name: f"/usr/bin/{name}" if name in present else None,
        exists=lambda p: Path(p).exists(),
    )
    return host, runner


@pytest.fixture(params=FIXTURE_NAMES)
def pc(request: pytest.FixtureRequest) -> dict[str, Any]:
    return load_fixture(request.param)


PATCH_SERIES = ("linux-6.1", "linux-6.6", "linux-6.12", "linux-6.18", "linux-7.2", "linux-7.3", "linux-next")
PKGBUILD_TEXT = """pkgname=linux-cachyos
_major=7.3
: "${_processor_opt:=}"
: "${_build_nvidia_open:=yes}"
: "${_build_nvidia_580xx:=yes}"
_nv_ver=580.95.05
source=("a.tar.xz")
b2sums=('x')

prepare() {
    echo "Setting config..."
}
"""


def make_build_tree(tmp_path: Path, *, with_pkgbuild: bool = True, series: Sequence[str] = PATCH_SERIES) -> Path:
    """A fake ~/kernel-build with both repos checked out (.git present) and a patch dir per series."""
    root = tmp_path / "kb"
    for repo in ("linux-cachyos", "linux_kernel_15khz"):
        (root / repo / ".git").mkdir(parents=True)
    if with_pkgbuild:
        for sub in ("linux-cachyos", "linux-cachyos-lts", "linux-cachyos-rc"):
            (root / "linux-cachyos" / sub).mkdir(parents=True)
            (root / "linux-cachyos" / sub / "PKGBUILD").write_text(PKGBUILD_TEXT, encoding="utf-8")
    for name in series:
        d = root / "linux_kernel_15khz" / name
        d.mkdir(parents=True)
        for n in ("01", "02", "03", "04", "05", "06", "07", "08", "09"):
            (d / f"{n}_{name}.patch").write_text(f"patch {n} for {name}\n", encoding="utf-8")
    return root


def make_suite_dir(tmp_path: Path) -> Path:
    suite = tmp_path / "suite"
    suite.mkdir()
    (suite / "interlace_rdna_patch.py").write_text("# rdna\n", encoding="utf-8")
    return suite


def arch_pc(tmp_path: Path, *, dry_run: bool = False) -> tuple[dict[str, Any], Host, "FixtureRunner"]:
    """The CachyOS fixture (the only Arch layout), sandboxed under ``tmp_path``."""
    pc = load_fixture("pc_cachyos_nvme_limine_dual_gpu")
    paths = make_paths(tmp_path)
    assert_sandboxed(paths, tmp_path)
    materialize_fixture(pc, tmp_path)
    host, runner = build_fixture_host(pc, tmp_path, paths, dry_run=dry_run)
    return pc, host, runner


def build_host(root: Path, paths: SystemPaths, *, tools: Sequence[str] = (), dry_run: bool = False,
               lspci: str = LSPCI_RDNA_ONLY, is_root: bool = False) -> tuple[Host, FakeRunner]:
    runner = FakeRunner(dry_run=dry_run, lspci=lspci, is_root=is_root)
    present = set(tools)
    host = Host(
        runner=runner, paths=paths,
        which=lambda name: f"/usr/bin/{name}" if name in present else None,
        exists=lambda p: Path(p).exists(),
    )
    return host, runner
