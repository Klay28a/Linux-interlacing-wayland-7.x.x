"""Shared pytest fixtures: a hermetic Host that never touches real hardware or the real filesystem."""

import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from interlace_runner import Host, Runner, SystemPaths

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

    def _exec(self, cmd: Sequence[str], ok_to_fail: bool, input_text: str | None = None):
        argv = [str(c) for c in cmd]
        self.executed.append(argv)
        if argv[0] == "lspci":
            return subprocess.CompletedProcess(argv, 0, self.lspci, "")
        # canned output is keyed by the command's last argument (e.g. "--print-esp-path")
        if argv[-1] in self.queries_ok:
            return subprocess.CompletedProcess(argv, 0, self.queries_ok[argv[-1]], "")
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
