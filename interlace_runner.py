"""
Single choke point for every state-changing action of the Linux CRT Interlacing Suite.

With ``dry_run=True`` the ``Runner`` prints the exact command / file write instead of performing
it. All filesystem locations live in ``SystemPaths`` and all host facts in ``Host`` so tests can
point them at a temp directory and fake ``which``/``exists`` without touching real hardware.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path


class CommandError(Exception):
    """A required command failed or is missing. The message is safe to show to the user."""


def _print_flush(message: str) -> None:
    print(message, flush=True)


@dataclass(frozen=True)
class SystemPaths:
    drm_class: Path = Path("/sys/class/drm")
    edid_firmware_param: Path = Path("/sys/module/drm/parameters/edid_firmware")
    debugfs_dri: Path = Path("/sys/kernel/debug/dri")
    firmware_edid_dir: Path = Path("/usr/lib/firmware/edid")
    udev_rules_dir: Path = Path("/etc/udev/rules.d")
    modprobe_dir: Path = Path("/etc/modprobe.d")
    mkinitcpio_conf: Path = Path("/etc/mkinitcpio.conf")
    dracut_conf_dir: Path = Path("/etc/dracut.conf.d")
    initramfs_hooks_dir: Path = Path("/etc/initramfs-tools/hooks")
    default_limine: Path = Path("/etc/default/limine")
    default_grub: Path = Path("/etc/default/grub")
    kernel_cmdline: Path = Path("/etc/kernel/cmdline")
    loader_entry_dirs: tuple[Path, ...] = (
        Path("/boot/loader/entries"), Path("/efi/loader/entries"), Path("/boot/efi/loader/entries"),
    )
    grub_cfg_candidates: tuple[Path, ...] = (Path("/boot/grub/grub.cfg"), Path("/boot/grub2/grub.cfg"))
    home: Path = field(default_factory=Path.home)

    @property
    def state_file(self) -> Path:
        return self.firmware_edid_dir / ".interlace-suite-state.json"

    @property
    def user_env_dir(self) -> Path:
        return self.home / ".config" / "environment.d"

    @property
    def gpu_udev_rules(self) -> Path:
        return self.udev_rules_dir / "99-kwin-gpu.rules"

    @property
    def gpu_modprobe_conf(self) -> Path:
        return self.modprobe_dir / "amdgpu-crt.conf"


class Runner:
    """Executes (or, with ``dry_run``, merely prints) every state-changing action."""

    def __init__(
        self,
        dry_run: bool = False,
        out: Callable[[str], None] | None = None,
        is_root: bool | None = None,
        sleep: Callable[[float], None] = time.sleep,
        environ: Mapping[str, str] | None = None,
        interactive: bool | None = None,
    ) -> None:
        self.dry_run = dry_run
        self._out = out if out is not None else _print_flush
        self.is_root = (os.geteuid() == 0) if is_root is None else is_root
        self._sleep = sleep
        self._environ = os.environ if environ is None else environ
        # A real terminal may be prompted for a sudo password; headless runs must never block on one.
        self.interactive = sys.stdin.isatty() if interactive is None else interactive

    def say(self, message: str) -> None:
        self._out(message)

    def plan(self, message: str) -> None:
        self._out(f"[dry-run] {message}")

    def _exec(
        self, cmd: Sequence[str], ok_to_fail: bool, input_text: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        """The only place a subprocess is created; tests override this to record/mock commands."""
        argv = [str(c) for c in cmd]
        try:
            return subprocess.run(argv, check=True, text=True, capture_output=True, input=input_text)
        except subprocess.CalledProcessError as exc:
            if not ok_to_fail:
                detail = (exc.stderr or exc.stdout or "").strip().splitlines()
                hint = f": {detail[-1]}" if detail else ""
                raise CommandError(f"command failed (exit {exc.returncode}): {shlex.join(argv)}{hint}") from exc
            return subprocess.CompletedProcess(argv, exc.returncode, exc.stdout or "", exc.stderr or "")
        except FileNotFoundError as exc:
            if not ok_to_fail:
                raise CommandError(f"command not found: {argv[0]}") from exc
            return subprocess.CompletedProcess(argv, 127, "", str(exc))

    def sudo(self, cmd: Sequence[str]) -> list[str]:
        """``cmd`` prefixed with sudo, chosen so a background run can never hang on a password prompt.

        Root: no sudo. ``SUDO_ASKPASS`` set (the GUI supplies it): ``sudo -A``. Attached terminal:
        plain ``sudo`` (the user can type the password). Otherwise: ``sudo -n`` (fail fast).
        """
        argv = [str(c) for c in cmd]
        if self.is_root:
            return argv
        if self._environ.get("SUDO_ASKPASS"):
            return ["sudo", "-A", *argv]
        if self.interactive:
            return ["sudo", *argv]
        return ["sudo", "-n", *argv]

    def query(self, cmd: Sequence[str], *, ok_to_fail: bool = False) -> subprocess.CompletedProcess[str]:
        """Run a READ-ONLY command. Always executes, even in dry-run mode."""
        return self._exec(cmd, ok_to_fail)

    def run(
        self, cmd: Sequence[str], *, ok_to_fail: bool = False, privileged: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        """Run a state-changing command (printed instead of executed in dry-run mode)."""
        argv = self.sudo(cmd) if privileged else [str(c) for c in cmd]
        if self.dry_run:
            self.plan("would run: " + shlex.join(argv))
            return subprocess.CompletedProcess(argv, 0, "", "")
        result = self._exec(argv, ok_to_fail)
        for stream in (result.stdout, result.stderr):
            for line in (stream or "").splitlines():
                self.say(line)
        return result

    def read_text(self, path: Path) -> str:
        """Read a file, falling back to ``sudo -n cat`` when root-only. A missing file reads as ''."""
        try:
            return path.read_text(encoding="utf-8", errors="ignore")
        except FileNotFoundError:
            return ""
        except PermissionError:
            res = self.query(self.sudo(["cat", str(path)]), ok_to_fail=True)
            return res.stdout if res.returncode == 0 else ""

    def list_files(self, directory: Path, pattern: str = "*.conf") -> list[Path] | None:
        """Files matching ``pattern`` in ``directory``; None when it is not a readable directory."""
        try:
            return sorted(directory.glob(pattern)) if directory.is_dir() else None
        except PermissionError:
            probe = self.query(self.sudo(["test", "-d", str(directory)]), ok_to_fail=True)
            if probe.returncode != 0:
                return None
            found = self.query(
                self.sudo(["find", str(directory), "-maxdepth", "1", "-name", pattern]), ok_to_fail=True,
            )
            return sorted(Path(p) for p in found.stdout.splitlines() if p.strip())

    def _install(self, path: Path, data: bytes, mode: int, privileged: bool) -> None:
        """Install ``data`` at ``path`` via a temp file. Tests override this to capture writes."""
        with tempfile.NamedTemporaryFile("wb", delete=False) as tmp:
            tmp.write(data)
            tmp_name = tmp.name
        try:
            cmd = ["install", "-D", "-m", f"{mode:04o}", tmp_name, str(path)]
            self._exec(self.sudo(cmd) if privileged else cmd, False)
        finally:
            Path(tmp_name).unlink(missing_ok=True)

    def install_bytes(self, path: Path, data: bytes, mode: int = 0o644, privileged: bool = True) -> None:
        if self.dry_run:
            self.plan(f"would install {len(data)} bytes to {path} (mode {mode:04o})")
            return
        self._install(path, data, mode, privileged)

    def write_text(self, path: Path, content: str, mode: int = 0o644, privileged: bool = True) -> None:
        if self.dry_run:
            self.plan(f"would write {len(content.encode('utf-8'))} bytes to {path} (mode {mode:04o})")
            for line in content.splitlines():
                self.say(f"[dry-run]   | {line}")
            return
        self._install(path, content.encode("utf-8"), mode, privileged)

    def backup_once(self, path: Path) -> None:
        """Copy ``path`` to ``path.orig.bak`` unless that backup already exists."""
        backup = Path(f"{path}.orig.bak")
        if backup.exists():
            return
        self.run(["cp", "-a", str(path), str(backup)], privileged=True)

    def remove(self, path: Path, privileged: bool = True) -> None:
        self.run(["rm", "-f", str(path)], privileged=privileged)

    def write_sysfs(self, path: Path, value: str) -> None:
        """Write a sysfs/procfs attribute (needs root)."""
        if self.dry_run:
            self.plan(f"would write {value!r} to {path}")
            return
        self._exec(self.sudo(["tee", str(path)]), True, input_text=value)

    def write_raw(self, path: Path, data: bytes) -> bool:
        """Write binary data straight to a root-only node (e.g. debugfs ``edid_override``).

        Only possible when running as root (the pkexec case); otherwise it is skipped and False is
        returned. Never raises for a missing/unwritable node.
        """
        if self.dry_run:
            self.plan(f"would write {len(data)} raw bytes to {path}")
            return True
        try:
            with open(path, "wb") as fh:
                fh.write(data)
        except OSError as exc:
            self.say(f"  -> Skipped {path}: {exc}")
            return False
        return True

    def pause(self, seconds: float) -> None:
        if not self.dry_run:
            self._sleep(seconds)


@dataclass
class Host:
    """Everything that touches the live machine, injectable for tests."""

    runner: Runner
    paths: SystemPaths = field(default_factory=SystemPaths)
    which: Callable[[str], str | None] = shutil.which
    exists: Callable[[Path], bool] = field(default=lambda p: p.exists())

