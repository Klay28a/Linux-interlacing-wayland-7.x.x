#!/usr/bin/env python3
"""
Linux Interlacing Suite (GUI Manager for CRT Interlacing & RDNA DP/HDMI Adapters)
=================================================================================
A standalone PyQt6 graphical suite for running and configuring the Linux CRT
interlacing scripts from one place without needing the terminal:
  - setup-interlace-env.sh (EDID firmware, initramfs, Limine/GRUB cmdline, live DRM reload)
  - fix-interlaced-kernel.sh (15kHz + Interlace + RDNA DP/HDMI adapter kernel patcher & GPU rules)
  - Separate integration to launch or install Linux CRU (linux-cru remains its own standalone app)

Design & layout inspired by Safe & Secure Dual-Boot Virtual Monitor:
  - Scrollable outer viewport so nothing ever gets clipped on small window resizes
  - UI Zoom (Ctrl + Scroll / Ctrl + +/- / Reset button)
  - Structured grid/table hardware & system verification cells in Section 1
  - Clearly separated Zone Cards & Step Sub-Cards with live ✓ verification badges
  - Completed/verified options automatically marked with ✓ and greyed out when appropriate
"""

import glob
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from PyQt6.QtCore import QEvent, QProcess, QProcessEnvironment, Qt, QTimer
from PyQt6.QtGui import QBrush, QColor, QFont, QKeySequence, QShortcut, QTextCursor
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

APP_TITLE = "Linux CRT Interlacing Suite"
CONFIG_DIR = Path.home() / ".config" / "linux-interlace-suite"
CONFIG_FILE = CONFIG_DIR / "config.json"

GPU_PROFILES = [
    ("auto", "Auto-Detect GPU Architecture & Setup (Recommended)"),
    ("__header_single__", "── Single-GPU Configurations ──"),
    ("rdna-single", "Single GPU — AMD RDNA 1 / 2 / 3 / 4 (DP/HDMI DAC Adapter)"),
    ("gcn-single", "Single GPU — AMD GCN 1–5 / Polaris / Vega (Native VGA / DVI-I or DP/HDMI DAC)"),
    ("nvidia-single", "Single GPU — NVIDIA (DP/HDMI DAC Adapter or Native Analog)"),
    ("__header_dual__", "── Dual-GPU Configurations ──"),
    ("dual-nvidia-amd", "Dual GPU — NVIDIA Primary + AMD Secondary (CRT Interlace Output)"),
    ("dual-amd-amd", "Dual GPU — AMD Primary (RDNA) + AMD Secondary (CRT Interlace Output)"),
]

ADAPTER_MODES = [
    ("auto", "Auto-Detect from Target Connector & GPU Profile"),
    ("dp-dac", "DisplayPort DAC Adapter — DP Mode (Reads as DP-1 / DP-2 / DP-3)"),
    ("hdmi-dac", "HDMI DAC Adapter — HDMI Mode (Reads as HDMI-A-* / DP-*)"),
    ("analog-native", "Native Analog DAC Output (VGA-1 / DVI-I-1)"),
]

KERNEL_VERSIONS = [
    ("auto", "Auto-Detect from Running Kernel (Recommended)"),
    ("__header_mainline__", "── Mainline & Current Stable Kernels ──"),
    ("7.3", "Linux 7.3 — CachyOS Mainline (linux-cachyos 7.3.x + linux-7.3 15kHz patches)"),
    ("7.2", "Linux 7.2 — CachyOS Stable (linux-cachyos 7.2.11 + linux-7.2 15kHz patches)"),
    ("__header_lts__", "── Long-Term Support (LTS) Kernels ──"),
    ("6.18", "Linux 6.18 LTS — CachyOS LTS (linux-cachyos-lts 6.18.x + linux-6.18 15kHz patches)"),
    ("6.12", "Linux 6.12 LTS — CachyOS LTS (linux-cachyos-lts 6.12.69 + linux-6.12 15kHz patches)"),
    ("6.6", "Linux 6.6 LTS — CachyOS LTS (linux-cachyos-lts 6.6.51 + linux-6.6 15kHz patches)"),
    ("6.1", "Linux 6.1 LTS — CachyOS LTS (linux-cachyos-lts 6.1.55 + linux-6.1 15kHz patches)"),
    ("__header_rc__", "── Release Candidate / Next ──"),
    ("linux-next", "Linux Release Candidate / Next (linux-cachyos-rc + linux-next 15kHz patches)"),
]

DEFAULT_CONFIG = {
    "gpu_profile": "auto",
    "adapter_mode": "auto",
    "connector": "auto",
    "kernel_version": "auto",
    "edid_path": "",
    "include_rdna_patch": True,
    "scripts_dir": "",
    "ui_scale": 1.0,
}



class AutoWrapLabel(QLabel):
    """QLabel that wraps text and reports exact heightForWidth in minimumSizeHint without ever mutating minimumHeight or expanding width."""

    def __init__(self, text: str = "", parent: QWidget | None = None):
        super().__init__(text, parent)
        self.setWordWrap(True)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    def minimumSizeHint(self):
        sh = super().minimumSizeHint()
        sh.setWidth(min(sh.width(), 160))
        if self.wordWrap() and self.width() > 60:
            h = self.heightForWidth(self.width())
            if h > 0:
                sh.setHeight(h)
        return sh

    def sizeHint(self):
        sh = super().sizeHint()
        sh.setWidth(min(sh.width(), 240))
        if self.wordWrap() and self.width() > 60:
            h = self.heightForWidth(self.width())
            if h > 0:
                sh.setHeight(h)
        return sh

    def setText(self, text: str):
        super().setText(text)
        self.updateGeometry()



class NoWheelComboBox(QComboBox):
    """QComboBox that ignores mouse wheel events so scrolling the window never changes dropdown settings."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def wheelEvent(self, event):
        event.ignore()




def resolve_scripts_dir(saved_dir: str = "") -> Path:
    candidates = []
    if saved_dir:
        candidates.append(Path(saved_dir))
    self_dir = Path(__file__).resolve().parent
    candidates.extend([
        self_dir,
        Path("/usr/share/linux-interlace-suite"),
        Path("/usr/local/share/linux-interlace-suite"),
        Path.home() / ".local" / "share" / "linux-interlace-suite",
        Path.home() / "Projects" / "linux-interlacing-scripts",
        Path.home() / "Linux-interlacing-wayland-7.x.x",
    ])

    for cand in candidates:
        if (cand / "setup-interlace-env.sh").exists() and (cand / "fix-interlaced-kernel.sh").exists():
            return cand
    return self_dir


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                cfg.update(data)
        except Exception:
            pass
    if cfg.get("adapter_mode") not in ("auto", "dp-dac", "hdmi-dac", "analog-native"):
        cfg["adapter_mode"] = "auto"
    return cfg




def save_config(cfg: dict) -> None:
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    except Exception:
        pass


def is_rdna_pci_line(line: str, devid: str) -> bool:
    if re.search(r"Navi|RDNA|Radeon RX [56789]\d{3}", line, re.I):
        return True
    devid = devid.lower()
    if re.match(r"^(73[1-9a-f][0-9a-f]|74[0-9a-f]{2}|75[0-9a-f]{2}|15bf|15c8|163f|164d|1681|1900)$", devid):
        return True
    return False



def parse_pci_gpu_line(line: str) -> dict:
    slot = line.split()[0] if line.split() else ""
    m_vd = re.search(r"\[([0-9a-fA-F]{4}:[0-9a-fA-F]{4})\]", line)
    vendor_dev = m_vd.group(1).lower() if m_vd else ""
    devid = vendor_dev.split(":")[1] if ":" in vendor_dev else ""
    desc = re.sub(r"^[0-9a-fA-F:.]+\s+[^:]+:\s*", "", line)
    desc = re.sub(r"\s*\([0-9a-fA-F\s]*rev[^)]*\)\s*$", "", desc)
    desc = re.sub(r"\s*\[[0-9a-fA-F]{4}:[0-9a-fA-F]{4}\]", "", desc).strip()
    if vendor_dev.startswith("10de:"):
        arch = "NVIDIA GPU"
    elif vendor_dev.startswith("1002:"):
        arch = "AMD RDNA (DCN)" if is_rdna_pci_line(line, devid) else "AMD GCN / DCE"
    else:
        arch = "PCI Display Controller"
    return {
        "raw": line,
        "slot": slot,
        "vendor_dev": vendor_dev,
        "devid": devid,
        "model": desc,
        "arch": arch,
    }


def detect_system_info() -> dict:
    info = {
        "gpus": [],
        "gpu_items": [],
        "nv_devid": "",
        "amd_devids": [],
        "has_analog_drm": False,
        "recommended_profile": "rdna-single",
        "kernel": os.uname().release,
        "bootloader": "Unknown",
        "initramfs": "Unknown",
        "cmdline": "",
        "active_edid_fw": "",
        "active_edid_map": {},
        "linux_cru_installed": bool(
            shutil.which("linux-cru")
            or os.path.exists("/usr/local/bin/linux-cru")
            or os.path.exists(str(Path.home() / ".local" / "bin" / "linux-cru"))
        ),
        "kernel_15khz_active": False,
        "kernel_rdna_patch_in_pkgbuild": False,
        "ports": [],
    }

    try:
        out = subprocess.check_output(["lspci", "-D", "-nn"], text=True, stderr=subprocess.DEVNULL)
        for line in out.splitlines():
            if not re.search(r"VGA|3D|Display", line, re.I):
                continue
            s_line = line.strip()
            info["gpus"].append(s_line)
            info["gpu_items"].append(parse_pci_gpu_line(s_line))
            m_nv = re.search(r"\[10de:([0-9a-fA-F]{4})\]", s_line, re.I)
            if m_nv and not info["nv_devid"]:
                info["nv_devid"] = m_nv.group(1).lower()
            m_amd = re.search(r"\[1002:([0-9a-fA-F]{4})\]", s_line, re.I)
            if m_amd:
                info["amd_devids"].append((s_line, m_amd.group(1).lower()))
    except Exception:
        pass


    active_overrides = {}
    edid_param = Path("/sys/module/drm/parameters/edid_firmware")
    if edid_param.exists():
        try:
            raw = edid_param.read_text(encoding="utf-8").strip()
            info["active_edid_fw"] = raw
            for item in raw.split(","):
                if ":" in item:
                    k, v = item.split(":", 1)
                    active_overrides[k.strip()] = v.strip()
        except Exception:
            pass
    info["active_edid_map"] = active_overrides

    for st_path in sorted(glob.glob("/sys/class/drm/card*-*/status")):
        pdir = os.path.dirname(st_path)
        folder = os.path.basename(pdir)
        if "-" not in folder:
            continue
        card, port = folder.split("-", 1)
        if port.startswith("Writeback"):
            continue
        try:
            st = Path(st_path).read_text(encoding="utf-8").strip()
        except Exception:
            st = "unknown"
        if port.startswith(("VGA-", "DVI-I-")):
            info["has_analog_drm"] = True
        modes_path = os.path.join(pdir, "modes")
        has_interlace_mode = False
        if os.path.exists(modes_path):
            try:
                modes_txt = Path(modes_path).read_text(encoding="utf-8")
                if re.search(r"\d+x\d+i\b", modes_txt):
                    has_interlace_mode = True
            except Exception:
                pass
        if has_interlace_mode:
            info["kernel_15khz_active"] = True
        info["ports"].append({
            "card": card,
            "port": port,
            "status": st,
            "override": active_overrides.get(port, ""),
            "has_interlace_mode": has_interlace_mode,
        })

    pkgbuild_p = Path.home() / "kernel-build" / "linux-cachyos" / "linux-cachyos" / "PKGBUILD"
    if pkgbuild_p.exists():
        try:
            pb_txt = pkgbuild_p.read_text(encoding="utf-8", errors="ignore")
            if "01_linux_15khz.patch" in pb_txt:
                info["kernel_15khz_active"] = True
            if "11_linux_rdna_dp_hdmi_interlace.patch" in pb_txt:
                info["kernel_rdna_patch_in_pkgbuild"] = True
        except Exception:
            pass

    if info["nv_devid"] and info["amd_devids"]:
        info["recommended_profile"] = "dual-nvidia-amd"
    elif len(info["amd_devids"]) >= 2:
        info["recommended_profile"] = "dual-amd-amd"
    elif info["nv_devid"] and not info["amd_devids"]:
        info["recommended_profile"] = "nvidia-single"
    elif info["amd_devids"]:
        last_line, last_id = info["amd_devids"][-1]
        if is_rdna_pci_line(last_line, last_id) or not info["has_analog_drm"]:
            info["recommended_profile"] = "rdna-single"
        else:
            info["recommended_profile"] = "gcn-single"
    elif not info["has_analog_drm"]:
        info["recommended_profile"] = "rdna-single"
    else:
        info["recommended_profile"] = "gcn-single"


    if os.path.exists("/etc/default/limine") or shutil.which("limine-mkinitcpio"):
        info["bootloader"] = "Limine"
    elif os.path.exists("/etc/default/grub"):
        info["bootloader"] = "GRUB"
    elif os.path.exists("/boot/loader/loader.conf"):
        info["bootloader"] = "systemd-boot"

    if shutil.which("limine-mkinitcpio"):
        info["initramfs"] = "limine-mkinitcpio"
    elif shutil.which("mkinitcpio"):
        info["initramfs"] = "mkinitcpio"
    elif shutil.which("dracut"):
        info["initramfs"] = "dracut"
    elif shutil.which("update-initramfs"):
        info["initramfs"] = "initramfs-tools"

    try:
        info["cmdline"] = Path("/proc/cmdline").read_text(encoding="utf-8").strip()
    except Exception:
        pass

    return info


def verify_gpu_profile_rules(profile: str) -> tuple[bool, str]:
    cursor_conf = Path.home() / ".config" / "environment.d" / "kwin-cursor.conf"
    nv_prime = Path.home() / ".config" / "environment.d" / "nvidia-prime.conf"
    amd_dual = Path.home() / ".config" / "environment.d" / "amd-dual-gpu.conf"
    udev_rules = Path("/etc/udev/rules.d/99-kwin-gpu.rules")
    modprobe_crt = Path("/etc/modprobe.d/amdgpu-crt.conf")

    has_cursor = cursor_conf.exists()
    udev_txt = udev_rules.read_text(encoding="utf-8", errors="ignore") if udev_rules.exists() else ""

    if profile == "dual-nvidia-amd":
        ok = (
            has_cursor
            and nv_prime.exists()
            and "primary-nvidia" in udev_txt
            and "secondary-amd" in udev_txt
            and modprobe_crt.exists()
        )
        return ok, "Dual-GPU NVIDIA + AMD rules active" if ok else "Dual-GPU NVIDIA + AMD rules not applied yet"
    if profile == "dual-amd-amd":
        ok = (
            has_cursor
            and amd_dual.exists()
            and "primary-amd" in udev_txt
            and "secondary-amd" in udev_txt
            and modprobe_crt.exists()
        )
        return ok, "Dual-GPU AMD + AMD rules active" if ok else "Dual-GPU AMD + AMD rules not applied yet"
    if profile in ("rdna-single", "nvidia-single"):
        label = "Single-GPU RDNA" if profile == "rdna-single" else "Single-GPU NVIDIA"
        ok = (
            has_cursor
            and not nv_prime.exists()
            and not amd_dual.exists()
            and not udev_rules.exists()
            and not modprobe_crt.exists()
        )
        return ok, f"{label} rules active" if ok else f"{label} rules not applied yet"
    # gcn-single
    ok = (
        has_cursor
        and not nv_prime.exists()
        and not amd_dual.exists()
        and not udev_rules.exists()
        and modprobe_crt.exists()
    )
    return ok, "Single-GPU GCN rules active" if ok else "Single-GPU GCN rules not applied yet"


def resolve_target_connector(conn_sel: str, adapter_mode: str, gpu_profile: str, ports: list[dict]) -> str:
    if conn_sel and conn_sel != "auto":
        return conn_sel

    def find_port(want_connected: bool, prefixes: tuple[str, ...]) -> str:
        for p in ports:
            if p["port"].startswith(prefixes):
                if not want_connected or p["status"] == "connected":
                    return p["port"]
        return ""

    if adapter_mode == "dp-dac":
        return find_port(True, ("DP-", "HDMI-")) or find_port(False, ("DP-", "HDMI-")) or "DP-1"
    if adapter_mode == "hdmi-dac":
        return find_port(True, ("HDMI-", "DP-")) or find_port(False, ("HDMI-", "DP-")) or "HDMI-A-1"
    if adapter_mode == "analog-native":
        return find_port(True, ("VGA-", "DVI-I-")) or find_port(False, ("VGA-", "DVI-I-")) or "VGA-1"
    if gpu_profile in ("rdna-single", "nvidia-single"):
        return find_port(True, ("DP-", "HDMI-", "VGA-", "DVI-I-")) or find_port(False, ("DP-", "HDMI-")) or "DP-1"
    return find_port(True, ("VGA-", "DVI-I-", "DP-", "HDMI-")) or find_port(False, ("VGA-", "DVI-I-", "DP-", "HDMI-")) or "VGA-1"




def verify_edid_env_status(conn: str, sys_info: dict, custom_edid_path: str) -> tuple[bool, str]:
    if custom_edid_path:
        return False, f"Custom EDID selected ({os.path.basename(custom_edid_path)}) — Click to install"
    edid_name = "crufile.bin" if conn == "VGA-1" else f"cru-{conn.lower()}.bin"
    edid_dest = Path(f"/usr/lib/firmware/edid/{edid_name}")
    rel_fw = f"edid/{edid_name}"
    if not edid_dest.exists():
        return False, f"Missing {edid_dest}"

    active_fw = sys_info.get("active_edid_map", {}).get(conn, "")
    cmdline = sys_info.get("cmdline", "")
    in_cmdline = f"{conn}:{rel_fw}" in cmdline or active_fw == rel_fw

    in_boot_cfg = False
    for bpath in ("/etc/default/limine", "/etc/default/grub"):
        if os.path.exists(bpath):
            try:
                btxt = Path(bpath).read_text(encoding="utf-8", errors="ignore")
                if f"{conn}:{rel_fw}" in btxt and f"video={conn}:e" in btxt:
                    in_boot_cfg = True
            except Exception:
                pass
    if not os.path.exists("/etc/default/limine") and not os.path.exists("/etc/default/grub"):
        in_boot_cfg = True

    ok = edid_dest.exists() and (in_cmdline or active_fw == rel_fw) and in_boot_cfg
    if ok:
        return True, f"{conn}:{rel_fw}"
    return False, f"Not configured for {conn} yet"


class InterlaceSuiteWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.cfg = load_config()
        self.scripts_dir = resolve_scripts_dir(self.cfg.get("scripts_dir", ""))
        self.sys_info = detect_system_info()
        self.proc: QProcess | None = None
        self.askpass_dir: tempfile.TemporaryDirectory | None = None
        self._sudo_pw: str = ""
        self.ui_scale = float(self.cfg.get("ui_scale", 1.0))
        self.ui_scale = max(0.85, min(1.45, self.ui_scale))


        self.sudo_keepalive_timer = QTimer(self)
        self.sudo_keepalive_timer.setInterval(45000)
        self.sudo_keepalive_timer.timeout.connect(self._refresh_sudo_timestamp)

        self.task_start_time: float = 0.0
        self.compiled_objects: int = 0
        self.current_stage_text: str = "Idle — Ready"
        self.is_kernel_build: bool = False
        self.elapsed_timer = QTimer(self)
        self.elapsed_timer.setInterval(1000)
        self.elapsed_timer.timeout.connect(self._update_elapsed_time)


        self.setWindowTitle(APP_TITLE)
        self.resize(1020, 880)
        self.setMinimumSize(640, 480)
        self._build_ui()
        self._setup_zoom_shortcuts()
        self.apply_ui_scale(self.ui_scale, save=False)
        self.refresh_status()

    def _setup_zoom_shortcuts(self):
        for seq in ("Ctrl++", "Ctrl+="):
            sc = QShortcut(QKeySequence(seq), self)
            sc.activated.connect(lambda: self.apply_ui_scale(self.ui_scale + 0.05))
        sc_minus = QShortcut(QKeySequence("Ctrl+-"), self)
        sc_minus.activated.connect(lambda: self.apply_ui_scale(self.ui_scale - 0.05))
        sc_zero = QShortcut(QKeySequence("Ctrl+0"), self)
        sc_zero.activated.connect(lambda: self.apply_ui_scale(1.0))
        self.installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Wheel:
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                delta = event.angleDelta().y()
                if delta > 0:
                    self.apply_ui_scale(self.ui_scale + 0.05)
                elif delta < 0:
                    self.apply_ui_scale(self.ui_scale - 0.05)
                return True
        return super().eventFilter(obj, event)

    def apply_ui_scale(self, scale: float, save: bool = True):
        self.ui_scale = max(0.85, min(1.45, round(scale, 2)))
        if save:
            self.cfg["ui_scale"] = self.ui_scale
            save_config(self.cfg)
        self.zoom_btn.setText(f"🔍 {int(round(self.ui_scale * 100))}%")

        base_pt = round(10.0 * self.ui_scale, 1)
        small_pt = round(9.0 * self.ui_scale, 1)
        title_pt = round(15.5 * self.ui_scale, 1)
        zone_pt = round(14.5 * self.ui_scale, 1)


        self.setStyleSheet(f"""
            QMainWindow, QWidget#scrollContent {{ background-color: #16181d; color: #e6edf3; font-size: {base_pt}pt; }}
            QScrollArea {{ border: none; background-color: #16181d; }}
            QLabel {{ color: #e6edf3; font-size: {base_pt}pt; }}
            QLabel#mainTitle {{ font-size: {title_pt}pt; font-weight: bold; color: #ffffff; }}
            QLabel#mainSubtitle {{ font-size: {small_pt}pt; color: #9da7b3; }}
            QLabel#zoneHeader {{ font-size: {zone_pt}pt; font-weight: bold; color: #f0f6fc; padding: 2px 2px; }}
            QFrame#bannerCard {{ background-color: #1f2530; border: 1px solid #384457; border-radius: 10px; }}
            QFrame#zone1Card {{ background-color: #1c2028; border: 1px solid #353d4b; border-radius: 10px; }}
            QFrame#zone2Card {{ background-color: #192230; border: 1px solid #315a8a; border-radius: 10px; }}
            QFrame#zone3Card {{ background-color: #1b2228; border: 1px solid #2e5948; border-radius: 10px; }}
            QFrame#zone4Card {{ background-color: #181b21; border: 1px solid #323844; border-radius: 10px; }}
            QFrame#infoCell {{ background-color: #242933; border: 1px solid #363f4f; border-radius: 8px; }}
            QFrame#gpuTableCard {{ background-color: #222731; border: 1px solid #363f4f; border-radius: 8px; }}
            QFrame#summaryCard {{ background-color: #142336; border: 1px solid #3b74b5; border-radius: 8px; }}
            QFrame#stepSubCard {{ background-color: #222831; border: 1px solid #384352; border-radius: 8px; }}
            QLabel#cellTitle {{ font-size: {small_pt}pt; font-weight: bold; color: #8b949e; }}
            QLabel#cellValue {{ font-size: {base_pt}pt; font-weight: 600; color: #f0f6fc; }}
            QLabel#badgeOk {{
                background-color: #153726; color: #56d364; border: 1px solid #2ea043;
                border-radius: 5px; padding: 3px 9px; font-size: {small_pt}pt; font-weight: bold;
            }}
            QLabel#badgeWarn {{
                background-color: #3a2d13; color: #e3b341; border: 1px solid #9e6a03;
                border-radius: 5px; padding: 3px 9px; font-size: {small_pt}pt; font-weight: bold;
            }}
            QComboBox, QLineEdit {{
                background-color: #262c36; color: #f0f6fc; border: 1px solid #424b59;
                border-radius: 6px; padding: 6px 10px; min-height: 22px; font-size: {base_pt}pt;
            }}
            QComboBox:focus, QLineEdit:focus {{ border: 1px solid #58a6ff; }}
            QPushButton {{
                background-color: #2b323d; color: #f0f6fc; border: 1px solid #485263;
                border-radius: 6px; padding: 7px 14px; font-size: {base_pt}pt; font-weight: 600;
            }}
            QPushButton:hover:enabled {{ background-color: #353e4c; border-color: #637085; }}
            QPushButton:disabled {{ background-color: #1d2229; color: #6e7681; border: 1px solid #2f3540; }}
            QPushButton#primaryBtn {{ background-color: #1f6feb; color: #ffffff; border: 1px solid #388bfd; }}
            QPushButton#primaryBtn:hover:enabled {{ background-color: #2a7aef; }}
            QPushButton#verifiedBtn {{ background-color: #193626; color: #7ee787; border: 1px solid #2ea043; }}
            QPushButton#verifiedBtn:hover:enabled {{ background-color: #214531; }}
            QPushButton#verifiedDisabledBtn:disabled {{
                background-color: #15291e; color: #56d364; border: 1px solid #245e33;
            }}
            QProgressBar {{
                background-color: #141820;
                color: #f0f6fc;
                border: 1px solid #384352;
                border-radius: 6px;
                text-align: center;
                font-weight: bold;
                min-height: 22px;
                font-size: {small_pt}pt;
            }}
            QProgressBar::chunk {{
                background-color: #238636;
                border-radius: 5px;
            }}
            QCheckBox {{ spacing: 8px; font-size: {base_pt}pt; color: #e6edf3; }}
        """)

        if self.centralWidget():
            self.centralWidget().updateGeometry()



    def _make_info_cell(self, title: str) -> tuple[QFrame, QLabel, QLabel]:
        cell = QFrame()
        cell.setObjectName("infoCell")
        vbox = QVBoxLayout(cell)
        vbox.setContentsMargins(10, 8, 10, 8)
        vbox.setSpacing(4)

        top_row = QHBoxLayout()
        t_lbl = QLabel(title)
        t_lbl.setObjectName("cellTitle")
        badge = QLabel()
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        top_row.addWidget(t_lbl, 1)
        top_row.addWidget(badge, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        vbox.addLayout(top_row)

        v_lbl = AutoWrapLabel("-")
        v_lbl.setObjectName("cellValue")
        v_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        vbox.addWidget(v_lbl)
        return cell, v_lbl, badge


    def _set_badge(self, badge: QLabel, ok: bool, text: str):
        badge.setText(f"✓ {text}" if ok else f"⚠ {text}")
        badge.setObjectName("badgeOk" if ok else "badgeWarn")
        badge.style().unpolish(badge)
        badge.style().polish(badge)

    def _build_ui(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setCentralWidget(scroll)

        content = QWidget()
        content.setObjectName("scrollContent")
        scroll.setWidget(content)

        outer_vbox = QVBoxLayout(content)
        outer_vbox.setContentsMargins(16, 14, 16, 18)
        outer_vbox.setSpacing(12)

        # Header Row
        hdr_layout = QHBoxLayout()
        hdr_text_box = QVBoxLayout()
        hdr_text_box.setSpacing(2)
        title_lbl = QLabel("Linux CRT Interlacing & RDNA Adapter Suite")
        title_lbl.setObjectName("mainTitle")
        sub_lbl = QLabel(
            "Configure custom EDIDs, RDNA/GCN single & dual-GPU rules, and 15kHz/interlaced kernel builds from one place."
        )
        sub_lbl.setObjectName("mainSubtitle")
        sub_lbl.setWordWrap(True)
        hdr_text_box.addWidget(title_lbl)
        hdr_text_box.addWidget(sub_lbl)
        hdr_layout.addLayout(hdr_text_box, 1)

        self.zoom_btn = QPushButton("🔍 100%")
        self.zoom_btn.setToolTip("Hold Ctrl + Scroll Wheel (or Ctrl + / -) to scale UI text. Click to reset to 100%.")
        self.zoom_btn.clicked.connect(lambda: self.apply_ui_scale(1.0))
        hdr_layout.addWidget(self.zoom_btn, 0, Qt.AlignmentFlag.AlignTop)
        outer_vbox.addLayout(hdr_layout)

        # Top Readiness Banner Card
        banner_card = QFrame()
        banner_card.setObjectName("bannerCard")
        banner_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        banner_hbox = QHBoxLayout(banner_card)
        banner_hbox.setContentsMargins(14, 10, 14, 10)
        banner_hbox.setSpacing(12)

        self.banner_status_lbl = AutoWrapLabel()
        banner_hbox.addWidget(self.banner_status_lbl, 1)

        self.refresh_btn = QPushButton("↻ Re-Check System")
        self.refresh_btn.clicked.connect(self.refresh_status)
        banner_hbox.addWidget(self.refresh_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        outer_vbox.addWidget(banner_card)

        # ======================================================================
        # SECTION 1: Detected Hardware, Kernel & Bootloader Status (Grid/Table)
        # ======================================================================
        sec1_hdr = QLabel("1. Detected Hardware, Kernel & Bootloader Status")
        sec1_hdr.setObjectName("zoneHeader")
        outer_vbox.addWidget(sec1_hdr)

        zone1_card = QFrame()
        zone1_card.setObjectName("zone1Card")
        zone1_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)

        z1_vbox = QVBoxLayout(zone1_card)
        z1_vbox.setContentsMargins(14, 12, 14, 14)
        z1_vbox.setSpacing(10)

        # Structured PCI GPUs Table Card
        gpu_table_card = QFrame()
        gpu_table_card.setObjectName("gpuTableCard")
        gpu_table_vbox = QVBoxLayout(gpu_table_card)
        gpu_table_vbox.setContentsMargins(12, 10, 12, 10)
        gpu_table_vbox.setSpacing(6)

        gpu_hdr_lbl = QLabel("DETECTED PCI GRAPHICS ADAPTERS")
        gpu_hdr_lbl.setObjectName("cellTitle")
        gpu_table_vbox.addWidget(gpu_hdr_lbl)

        self.gpu_grid = QGridLayout()
        self.gpu_grid.setContentsMargins(0, 2, 0, 0)
        self.gpu_grid.setHorizontalSpacing(14)
        self.gpu_grid.setVerticalSpacing(6)
        self.gpu_grid.setColumnStretch(2, 1)
        gpu_table_vbox.addLayout(self.gpu_grid)
        z1_vbox.addWidget(gpu_table_card)

        # 6-Cell System Status & Verification Grid (2 columns x 3 rows — scales cleanly at all widths)
        self.cells_grid = QGridLayout()
        self.cells_grid.setSpacing(8)
        self.cells_grid.setColumnStretch(0, 1)
        self.cells_grid.setColumnStretch(1, 1)

        c_arch, self.cell_arch_val, self.cell_arch_badge = self._make_info_cell("DETECTED GPU PROFILE")
        c_kern, self.cell_kern_val, self.cell_kern_badge = self._make_info_cell("RUNNING KERNEL & 15KHZ")
        c_boot, self.cell_boot_val, self.cell_boot_badge = self._make_info_cell("BOOTLOADER & INITRAMFS")
        c_edid, self.cell_edid_val, self.cell_edid_badge = self._make_info_cell("ACTIVE DRM EDID OVERRIDE")
        c_rules, self.cell_rules_val, self.cell_rules_badge = self._make_info_cell("SINGLE / DUAL-GPU RULES")
        c_cru, self.cell_cru_val, self.cell_cru_badge = self._make_info_cell("STANDALONE LINUX CRU")

        self.cells_grid.addWidget(c_arch, 0, 0)
        self.cells_grid.addWidget(c_kern, 0, 1)
        self.cells_grid.addWidget(c_boot, 1, 0)
        self.cells_grid.addWidget(c_edid, 1, 1)
        self.cells_grid.addWidget(c_rules, 2, 0)
        self.cells_grid.addWidget(c_cru, 2, 1)
        z1_vbox.addLayout(self.cells_grid)
        outer_vbox.addWidget(zone1_card)



        # ======================================================================
        # SECTION 2: GPU Architecture, Single/Dual-GPU Mode & Adapter Config
        # ======================================================================
        sec2_hdr = QLabel("2. GPU Architecture, Single/Dual-GPU Mode & Adapter Configuration")
        sec2_hdr.setObjectName("zoneHeader")
        outer_vbox.addWidget(sec2_hdr)

        zone2_card = QFrame()
        zone2_card.setObjectName("zone2Card")
        zone2_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        z2_vbox = QVBoxLayout(zone2_card)
        z2_vbox.setContentsMargins(14, 14, 14, 14)
        z2_vbox.setSpacing(10)


        cfg_grid = QGridLayout()
        cfg_grid.setHorizontalSpacing(12)
        cfg_grid.setVerticalSpacing(10)
        cfg_grid.setColumnStretch(1, 1)

        self.gpu_combo = NoWheelComboBox()
        self.gpu_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.gpu_combo.setMinimumContentsLength(20)
        hdr_font = QFont()
        hdr_font.setBold(True)
        for key, label in GPU_PROFILES:
            self.gpu_combo.addItem(label, key)
            row_i = self.gpu_combo.count() - 1
            if key.startswith("__header_"):
                item = self.gpu_combo.model().item(row_i)
                if item is not None:
                    item.setEnabled(False)
                    item.setFont(hdr_font)
                    item.setForeground(QBrush(QColor("#58a6ff")))
        # Default to Auto-Detect on launch
        self.gpu_combo.setCurrentIndex(0)
        self.gpu_combo.currentIndexChanged.connect(self.on_config_changed)

        self.adapter_combo = NoWheelComboBox()
        self.adapter_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.adapter_combo.setMinimumContentsLength(20)
        for key, label in ADAPTER_MODES:
            self.adapter_combo.addItem(label, key)
        # Default to Auto-Detect on launch
        self.adapter_combo.setCurrentIndex(0)
        self.adapter_combo.currentIndexChanged.connect(self.on_config_changed)

        self.conn_combo = NoWheelComboBox()
        self.conn_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.conn_combo.setMinimumContentsLength(20)
        self.conn_combo.currentIndexChanged.connect(self.on_config_changed)




        edid_row = QHBoxLayout()
        edid_row.setSpacing(8)
        self.edid_edit = QLineEdit(self.cfg.get("edid_path", ""))
        self.edid_edit.setPlaceholderText("Default: Generate/Convert 2048x1536i@160Hz + 1600x1200p@85Hz CRT EDID (or select .bin)")
        self.edid_edit.textChanged.connect(self.on_config_changed)
        browse_edid_btn = QPushButton("Browse .bin...")
        browse_edid_btn.clicked.connect(self.browse_edid)
        clear_edid_btn = QPushButton("Use Default")
        clear_edid_btn.clicked.connect(lambda: self.edid_edit.setText(""))
        edid_row.addWidget(self.edid_edit, 1)
        edid_row.addWidget(browse_edid_btn)
        edid_row.addWidget(clear_edid_btn)

        cfg_grid.addWidget(QLabel("<b>GPU Architecture &amp; Setup:</b>"), 0, 0)
        cfg_grid.addWidget(self.gpu_combo, 0, 1)
        cfg_grid.addWidget(QLabel("<b>Adapter / Output Base:</b>"), 1, 0)
        cfg_grid.addWidget(self.adapter_combo, 1, 1)
        cfg_grid.addWidget(QLabel("<b>Target Video Connector:</b>"), 2, 0)
        cfg_grid.addWidget(self.conn_combo, 2, 1)
        cfg_grid.addWidget(QLabel("<b>Custom EDID (.bin):</b>"), 3, 0)
        cfg_grid.addLayout(edid_row, 3, 1)
        z2_vbox.addLayout(cfg_grid)

        # Auto-expanding Blue Summary Card (Never clips or stretches gaps on resize)
        summary_card = QFrame()
        summary_card.setObjectName("summaryCard")
        summary_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        sum_vbox = QVBoxLayout(summary_card)
        sum_vbox.setContentsMargins(14, 10, 14, 10)
        sum_vbox.setSpacing(5)

        self.sum_prof_lbl = AutoWrapLabel()
        self.sum_adap_lbl = AutoWrapLabel()
        self.sum_target_lbl = AutoWrapLabel()

        sum_vbox.addWidget(self.sum_prof_lbl)
        sum_vbox.addWidget(self.sum_adap_lbl)
        sum_vbox.addWidget(self.sum_target_lbl)
        z2_vbox.addWidget(summary_card)
        outer_vbox.addWidget(zone2_card)



        # ======================================================================
        # SECTION 3: Interlacing Suite Actions (Step-by-Step Sub-Cards)
        # ======================================================================
        sec3_hdr_row = QHBoxLayout()
        sec3_hdr = QLabel("3. Interlacing Suite Actions (Step-by-Step Workflow)")
        sec3_hdr.setObjectName("zoneHeader")
        sec3_hdr.setWordWrap(True)
        sec3_hdr_row.addWidget(sec3_hdr, 1)

        self.force_rerun_chk = QCheckBox("Unlock Verified Steps")
        self.force_rerun_chk.setToolTip(
            "Steps already verified active on this system are marked ✓ and greyed out. Check this box to force re-running them."
        )
        self.force_rerun_chk.stateChanged.connect(self.update_architecture_summary)
        sec3_hdr_row.addWidget(self.force_rerun_chk, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        outer_vbox.addLayout(sec3_hdr_row)



        zone3_card = QFrame()
        zone3_card.setObjectName("zone3Card")
        zone3_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        z3_vbox = QVBoxLayout(zone3_card)
        z3_vbox.setContentsMargins(14, 14, 14, 14)
        z3_vbox.setSpacing(12)


        # --- Step A Sub-Card: Custom EDID, Initramfs & Bootloader Setup ---
        step_a_card = QFrame()
        step_a_card.setObjectName("stepSubCard")
        sa_vbox = QVBoxLayout(step_a_card)
        sa_vbox.setContentsMargins(12, 10, 12, 12)
        sa_vbox.setSpacing(8)

        sa_hdr = QHBoxLayout()
        sa_title = QLabel("<b>Step A — Custom EDID, Initramfs &amp; Bootloader Setup</b>  <code>(setup-interlace-env.sh)</code>")
        sa_title.setWordWrap(True)
        self.step3a_badge = QLabel()
        sa_hdr.addWidget(sa_title, 1)
        sa_hdr.addWidget(self.step3a_badge, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        sa_vbox.addLayout(sa_hdr)

        self.step3a_desc_lbl = QLabel(
            "Installs the Linux full-frame interlaced EDID to <code>/usr/lib/firmware/edid/</code>, embeds it in initramfs, "
            "updates bootloader <code>CMDLINE</code>, and reloads the DRM connector."
        )
        self.step3a_desc_lbl.setWordWrap(True)
        self.step3a_desc_lbl.setObjectName("mainSubtitle")
        sa_vbox.addWidget(self.step3a_desc_lbl)

        sa_btns = QVBoxLayout()
        sa_btns.setSpacing(6)
        self.run_env_btn = QPushButton("Run Environment && Bootloader Setup (setup-interlace-env.sh)")
        self.run_env_btn.setMinimumHeight(34)
        self.run_env_btn.clicked.connect(lambda: self.run_setup_env(live_only=False))

        self.run_live_btn = QPushButton("↻ Reload EDID Live Into Running Kernel Only (No Reboot)")
        self.run_live_btn.setMinimumHeight(32)
        self.run_live_btn.setToolTip("Reloads the custom EDID into the running kernel DRM without rebuilding initramfs/bootloader.")
        self.run_live_btn.clicked.connect(lambda: self.run_setup_env(live_only=True))

        sa_btns.addWidget(self.run_env_btn)
        sa_btns.addWidget(self.run_live_btn)
        sa_vbox.addLayout(sa_btns)
        z3_vbox.addWidget(step_a_card)

        # --- Step B Sub-Card: GPU Architecture Rules & Patched 15kHz Kernel ---
        step_b_card = QFrame()
        step_b_card.setObjectName("stepSubCard")
        sb_vbox = QVBoxLayout(step_b_card)
        sb_vbox.setContentsMargins(12, 10, 12, 12)
        sb_vbox.setSpacing(8)

        sb_hdr = QHBoxLayout()
        sb_title = QLabel("<b>Step B — Single/Dual-GPU Rules &amp; 15kHz Interlaced Kernel</b>  <code>(fix-interlaced-kernel.sh)</code>")
        sb_title.setWordWrap(True)
        self.step3b_rules_badge = QLabel()
        self.step3b_kern_badge = QLabel()
        sb_hdr.addWidget(sb_title, 1)
        sb_hdr.addWidget(self.step3b_rules_badge, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        sb_hdr.addWidget(self.step3b_kern_badge, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        sb_vbox.addLayout(sb_hdr)

        kver_row = QHBoxLayout()
        kver_row.setSpacing(10)
        kver_lbl = QLabel("<b>Target Kernel &amp; 15kHz Patch Version:</b>")
        self.kernel_ver_combo = NoWheelComboBox()
        self.kernel_ver_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.kernel_ver_combo.setMinimumContentsLength(20)
        for key, label in KERNEL_VERSIONS:
            self.kernel_ver_combo.addItem(label, key)
            row_i = self.kernel_ver_combo.count() - 1
            if key.startswith("__header_"):
                item = self.kernel_ver_combo.model().item(row_i)
                if item is not None:
                    item.setEnabled(False)
                    item.setFont(hdr_font)
                    item.setForeground(QBrush(QColor("#58a6ff")))
        self.kernel_ver_combo.setCurrentIndex(0)
        self.kernel_ver_combo.currentIndexChanged.connect(self.on_config_changed)
        kver_row.addWidget(kver_lbl, 0)
        kver_row.addWidget(self.kernel_ver_combo, 1)
        sb_vbox.addLayout(kver_row)

        rdna_chk_row = QHBoxLayout()

        rdna_chk_row.setSpacing(8)
        self.rdna_patch_chk = QCheckBox()
        self.rdna_patch_chk.setChecked(bool(self.cfg.get("include_rdna_patch", True)))
        self.rdna_patch_chk.stateChanged.connect(self.on_config_changed)
        self.rdna_patch_lbl = AutoWrapLabel(
            "✓ Include RDNA DCN &amp; DP/HDMI DAC Adapter Unlock Patch "
            "(<code>11_linux_rdna_dp_hdmi_interlace.patch</code>)"
        )
        self.rdna_patch_lbl.mousePressEvent = lambda _e: self.rdna_patch_chk.toggle()
        rdna_chk_row.addWidget(self.rdna_patch_chk, 0, Qt.AlignmentFlag.AlignTop)
        rdna_chk_row.addWidget(self.rdna_patch_lbl, 1)
        sb_vbox.addLayout(rdna_chk_row)

        sb_btns = QVBoxLayout()
        sb_btns.setSpacing(6)
        self.run_cfg_only_btn = QPushButton("Apply Single/Dual-GPU Rules Only (Fast)")
        self.run_cfg_only_btn.setMinimumHeight(34)
        self.run_cfg_only_btn.setToolTip(
            "Applies udev, modprobe, and KWin Wayland environment rules for the selected GPU Architecture Profile without recompiling the kernel."
        )
        self.run_cfg_only_btn.clicked.connect(lambda: self.run_fix_kernel(config_only=True))

        self.run_kernel_btn = QPushButton("Compile && Install Patched Interlaced Kernel (fix-interlaced-kernel.sh)")
        self.run_kernel_btn.setMinimumHeight(34)
        self.run_kernel_btn.clicked.connect(lambda: self.run_fix_kernel(config_only=False))

        sb_btns.addWidget(self.run_cfg_only_btn)
        sb_btns.addWidget(self.run_kernel_btn)
        sb_vbox.addLayout(sb_btns)

        # Kernel Build & Script Progress Bar inside Step B
        self.stepb_prog_box = QWidget()
        sb_prog_vbox = QVBoxLayout(self.stepb_prog_box)
        sb_prog_vbox.setContentsMargins(0, 4, 0, 0)
        sb_prog_vbox.setSpacing(4)
        self.stepb_stage_lbl = AutoWrapLabel("Build Progress: Idle — Ready to compile or apply GPU rules")
        self.stepb_stage_lbl.setObjectName("mainSubtitle")
        self.stepb_prog_bar = QProgressBar()
        self.stepb_prog_bar.setRange(0, 100)
        self.stepb_prog_bar.setValue(0)
        self.stepb_prog_bar.setFormat("%p%")
        self.stepb_prog_bar.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        sb_prog_vbox.addWidget(self.stepb_stage_lbl)
        sb_prog_vbox.addWidget(self.stepb_prog_bar)
        sb_vbox.addWidget(self.stepb_prog_box)
        z3_vbox.addWidget(step_b_card)



        # --- Step C Sub-Card: Standalone Linux CRU Resolution Editor ---
        step_c_card = QFrame()
        step_c_card.setObjectName("stepSubCard")
        sc_vbox = QVBoxLayout(step_c_card)
        sc_vbox.setContentsMargins(12, 10, 12, 12)
        sc_vbox.setSpacing(8)

        sc_hdr = QHBoxLayout()
        sc_title = QLabel("<b>Step C — Standalone Linux CRU Resolution Editor</b>  <code>(linux-cru)</code>")
        sc_title.setWordWrap(True)
        self.step3c_badge = QLabel()
        sc_hdr.addWidget(sc_title, 1)
        sc_hdr.addWidget(self.step3c_badge, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        sc_vbox.addLayout(sc_hdr)

        sc_desc = QLabel(
            "Linux CRU remains its own standalone application for creating and editing custom CRT detailed resolutions and timings."
        )
        sc_desc.setWordWrap(True)
        sc_desc.setObjectName("mainSubtitle")
        sc_vbox.addWidget(sc_desc)

        sc_btns = QVBoxLayout()
        sc_btns.setSpacing(6)
        self.launch_cru_btn = QPushButton("Launch Linux CRU (Standalone App)")
        self.launch_cru_btn.setMinimumHeight(34)
        self.launch_cru_btn.clicked.connect(self.launch_linux_cru)

        self.install_cru_btn = QPushButton("Install / Update Linux CRU (install-linux-cru.sh)")
        self.install_cru_btn.setMinimumHeight(32)
        self.install_cru_btn.clicked.connect(self.run_install_cru)

        sc_btns.addWidget(self.launch_cru_btn)
        sc_btns.addWidget(self.install_cru_btn)
        sc_vbox.addLayout(sc_btns)
        z3_vbox.addWidget(step_c_card)


        outer_vbox.addWidget(zone3_card)

        # ======================================================================
        # Live Script Output & Execution Log
        # ======================================================================
        sec4_hdr = QLabel("Live Script Output & Execution Log")
        sec4_hdr.setObjectName("zoneHeader")
        outer_vbox.addWidget(sec4_hdr)


        zone4_card = QFrame()
        zone4_card.setObjectName("zone4Card")
        log_vbox = QVBoxLayout(zone4_card)
        log_vbox.setContentsMargins(14, 12, 14, 12)
        log_vbox.setSpacing(8)

        self.log_view = QPlainTextEdit()


        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(140)
        mono = QFont("Monospace", 9)
        mono.setStyleHint(QFont.StyleHint.TypeWriter)
        self.log_view.setFont(mono)
        self.log_view.setStyleSheet("QPlainTextEdit { background-color: #111318; color: #e6edf3; border: 1px solid #2d3440; border-radius: 6px; padding: 6px; }")
        log_vbox.addWidget(self.log_view, 1)

        log_btns = QHBoxLayout()
        self.task_state_lbl = AutoWrapLabel("Status: Idle — Ready")

        self.stop_btn = QPushButton("Stop Running Task")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_current_task)
        copy_log_btn = QPushButton("Copy Log")
        copy_log_btn.clicked.connect(self.copy_log)
        clear_log_btn = QPushButton("Clear Log")
        clear_log_btn.clicked.connect(self.log_view.clear)

        log_btns.addWidget(self.task_state_lbl, 1)
        log_btns.addWidget(self.stop_btn)
        log_btns.addWidget(copy_log_btn)
        log_btns.addWidget(clear_log_btn)
        log_vbox.addLayout(log_btns)

        outer_vbox.addWidget(zone4_card, 1)

    def _clear_grid(self, grid: QGridLayout):
        while grid.count():
            item = grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.hide()
                w.setParent(None)
                w.deleteLater()

    def refresh_status(self):
        self.sys_info = detect_system_info()

        # Populate structured PCI GPU table
        self._clear_grid(self.gpu_grid)
        headers = ("PCI Slot", "Vendor:Device", "Graphics Adapter Model", "Architecture / Role")
        for col, htxt in enumerate(headers):
            hlbl = QLabel(f"<b>{htxt}</b>")
            hlbl.setStyleSheet("color: #8b949e;")
            self.gpu_grid.addWidget(hlbl, 0, col)

        if not self.sys_info["gpu_items"]:
            empty_lbl = QLabel("<i>No PCI display controller detected</i>")
            self.gpu_grid.addWidget(empty_lbl, 1, 0, 1, 4)
        else:
            for row_idx, g in enumerate(self.sys_info["gpu_items"], start=1):
                slot_lbl = QLabel(f"<code>{html.escape(g['slot'])}</code>")
                vd_lbl = QLabel(f"<code>{html.escape(g['vendor_dev'])}</code>")
                model_lbl = AutoWrapLabel(html.escape(g["model"]))
                arch_lbl = QLabel(f"<b>{html.escape(g['arch'])}</b>")
                self.gpu_grid.addWidget(slot_lbl, row_idx, 0, Qt.AlignmentFlag.AlignTop)
                self.gpu_grid.addWidget(vd_lbl, row_idx, 1, Qt.AlignmentFlag.AlignTop)
                self.gpu_grid.addWidget(model_lbl, row_idx, 2, Qt.AlignmentFlag.AlignTop)
                self.gpu_grid.addWidget(arch_lbl, row_idx, 3, Qt.AlignmentFlag.AlignTop)


        # Populate connector combo: Auto-Detect first, then Connected ports, then Disconnected ports (greyed out)
        prev_conn = self.conn_combo.currentData() or "auto"
        self.conn_combo.blockSignals(True)
        self.conn_combo.clear()
        self.conn_combo.addItem("Auto-Detect Target Port (Based on GPU & Adapter Selection)", "auto")

        connected_ports = [p for p in self.sys_info["ports"] if p["status"] == "connected"]
        disconnected_ports = [p for p in self.sys_info["ports"] if p["status"] != "connected"]

        hdr_font = QFont()
        hdr_font.setBold(True)
        seen_ports = set()

        if connected_ports:
            self.conn_combo.addItem("── Connected Video Ports ──", "__header_conn__")
            h_item = self.conn_combo.model().item(self.conn_combo.count() - 1)
            if h_item is not None:
                h_item.setEnabled(False)
                h_item.setFont(hdr_font)
                h_item.setForeground(QBrush(QColor("#56d364")))
            for p in connected_ports:
                port_name = p["port"]
                seen_ports.add(port_name)
                tag = f" [✓ EDID: {p['override']}]" if p["override"] else ""
                label = f"● {port_name} ({p['card']}, connected){tag}"
                self.conn_combo.addItem(label, port_name)

        if disconnected_ports:
            self.conn_combo.addItem("── Disconnected Video Ports ──", "__header_disc__")
            h_item = self.conn_combo.model().item(self.conn_combo.count() - 1)
            if h_item is not None:
                h_item.setEnabled(False)
                h_item.setFont(hdr_font)
                h_item.setForeground(QBrush(QColor("#8b949e")))
            for p in disconnected_ports:
                port_name = p["port"]
                seen_ports.add(port_name)
                tag = f" [EDID: {p['override']}]" if p["override"] else ""
                label = f"○ {port_name} ({p['card']}, {p['status']}){tag}"
                self.conn_combo.addItem(label, port_name)
                d_item = self.conn_combo.model().item(self.conn_combo.count() - 1)
                if d_item is not None:
                    d_item.setEnabled(False)
                    d_item.setForeground(QBrush(QColor("#6e7681")))

        # Fallback pre-configuration ports (greyed out at bottom)
        missing_fallbacks = [fb for fb in ("DP-1", "DP-2", "DP-3", "HDMI-A-1", "HDMI-A-2", "VGA-1", "DVI-I-1") if fb not in seen_ports]
        if missing_fallbacks:
            self.conn_combo.addItem("── Pre-Configure / Unlisted Ports ──", "__header_pre__")
            h_item = self.conn_combo.model().item(self.conn_combo.count() - 1)
            if h_item is not None:
                h_item.setEnabled(False)
                h_item.setFont(hdr_font)
                h_item.setForeground(QBrush(QColor("#8b949e")))
            for fallback in missing_fallbacks:
                self.conn_combo.addItem(f"○ {fallback} (Pre-configure / Not currently detected)", fallback)
                f_item = self.conn_combo.model().item(self.conn_combo.count() - 1)
                if f_item is not None:
                    f_item.setEnabled(False)
                    f_item.setForeground(QBrush(QColor("#6e7681")))

        idx = self.conn_combo.findData(prev_conn)
        if idx >= 0:
            item_chk = self.conn_combo.model().item(idx)
            if item_chk is not None and not item_chk.isEnabled():
                idx = 0
        self.conn_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.conn_combo.blockSignals(False)

        self.update_architecture_summary()

    def get_effective_profile(self) -> str:
        sel = self.gpu_combo.currentData() or "auto"
        if sel == "auto" or str(sel).startswith("__header_"):
            return self.sys_info["recommended_profile"]
        return sel

    def get_effective_adapter(self) -> str:
        sel = self.adapter_combo.currentData() or "auto"
        if sel != "auto":
            return sel
        conn = self.conn_combo.currentData() or "auto"
        if conn.startswith("DP-"):
            return "dp-dac"
        if conn.startswith(("HDMI-", "DVI-D-")):
            return "hdmi-dac"
        if conn.startswith(("VGA-", "DVI-I-")):
            return "analog-native"
        return "dp-dac" if self.get_effective_profile() in ("rdna-single", "nvidia-single") else "analog-native"



    def _update_cells_and_banner(self, prof: str, eff_conn: str, edid_ok: bool, rules_ok: bool, kern_15khz: bool, cru_ok: bool):
        self.cell_arch_val.setText(f"<code>{prof}</code>")
        self._set_badge(self.cell_arch_badge, True, "Detected")

        self.cell_kern_val.setText(f"<code>{self.sys_info['kernel']}</code>")
        self._set_badge(self.cell_kern_badge, kern_15khz, "15kHz Patched" if kern_15khz else "Unpatched")

        self.cell_boot_val.setText(f"{self.sys_info['bootloader']}  |  {self.sys_info['initramfs']}")
        self._set_badge(self.cell_boot_badge, self.sys_info["bootloader"] != "Unknown", "Ready")

        fw_str = self.sys_info["active_edid_fw"] or "None active"
        self.cell_edid_val.setText(f"<code>{html.escape(fw_str)}</code>")
        self._set_badge(self.cell_edid_badge, edid_ok, f"Active ({eff_conn})" if edid_ok else "Needs Setup")

        self.cell_rules_val.setText(f"Profile: <code>{prof}</code>")
        self._set_badge(self.cell_rules_badge, rules_ok, "Active" if rules_ok else "Unapplied")

        self.cell_cru_val.setText("linux-cru (/usr/local/bin)" if cru_ok else "Not installed")
        self._set_badge(self.cell_cru_badge, cru_ok, "Installed" if cru_ok else "Missing")

        all_ready = edid_ok and rules_ok and kern_15khz and cru_ok
        if all_ready:
            self.banner_status_lbl.setText(
                f"<span style='color:#56d364; font-weight:bold;'>✓ All CRT Interlacing Components Verified &amp; Active</span> "
                f"— Target Port: <code>{eff_conn}</code> | Profile: <code>{prof}</code> | Kernel: <code>{self.sys_info['kernel']}</code>"
            )
        else:
            pending = []
            if not edid_ok:
                pending.append(f"EDID Setup ({eff_conn})")
            if not rules_ok:
                pending.append(f"GPU Profile Rules ({prof})")
            if not kern_15khz:
                pending.append("15kHz Kernel Patch")
            if not cru_ok:
                pending.append("Linux CRU")
            self.banner_status_lbl.setText(
                f"<span style='color:#e3b341; font-weight:bold;'>⚠ Action Needed for Selected Configuration:</span> "
                f"{', '.join(pending)}"
            )

    def update_architecture_summary(self):
        prof = self.get_effective_profile()
        adap = self.get_effective_adapter()
        conn_raw = self.conn_combo.currentData() or "auto"
        eff_conn = resolve_target_connector(conn_raw, adap, prof, self.sys_info["ports"])
        rdna_patch = self.rdna_patch_chk.isChecked()
        custom_edid = self.edid_edit.text().strip()

        edid_ok, edid_msg = verify_edid_env_status(eff_conn, self.sys_info, custom_edid)
        rules_ok, _ = verify_gpu_profile_rules(prof)
        kern_15khz = bool(self.sys_info.get("kernel_15khz_active", False))
        cru_ok = bool(self.sys_info.get("linux_cru_installed", False))

        self._update_cells_and_banner(prof, eff_conn, edid_ok, rules_ok, kern_15khz, cru_ok)

        prof_desc = {
            "rdna-single": (
                "• <b>Single-GPU AMD RDNA (RDNA 1 / 2 / 3 / 4):</b> "
                "Uses native <code>amdgpu</code> DCN pipeline without legacy GCN <code>radeon.si_support</code>/<code>cik_support</code> "
                "flags, removes dual-GPU PRIME overrides, and aligns interlaced vertical field timings to even line counts."
            ),
            "gcn-single": (
                "• <b>Single-GPU AMD GCN / Polaris / Vega:</b> "
                "Enables <code>amdgpu.si_support=1 amdgpu.cik_support=1</code> and blacklists legacy <code>radeon</code> "
                "so GCN 1.0/1.1 cards use Display Core (DC) for native analog or DAC adapter interlacing."
            ),
            "nvidia-single": (
                "• <b>Single-GPU NVIDIA:</b> "
                "Uses standalone NVIDIA DRM output without dual-GPU udev symlinks or legacy AMD SI/CIK module overrides, "
                "and configures custom EDID firmware override on the selected connector."
            ),
            "dual-nvidia-amd": (
                "• <b>Dual-GPU (NVIDIA Primary + AMD Secondary CRT Card):</b> "
                "Configures PCI-slot-independent <code>/dev/dri/primary-nvidia</code> &amp; <code>/dev/dri/secondary-amd</code> udev symlinks, "
                "sets <code>KWIN_DRM_DEVICES</code> + NVIDIA PRIME offload, and enables <code>amdgpu</code> SI/CIK support."
            ),
            "dual-amd-amd": (
                "• <b>Dual-GPU (AMD Primary RDNA + AMD Secondary CRT Card):</b> "
                "Configures <code>/dev/dri/primary-amd</code> &amp; <code>/dev/dri/secondary-amd</code> udev symlinks for KWin Wayland "
                "without NVIDIA PRIME overrides, and enables <code>amdgpu</code> SI/CIK support."
            ),
        }.get(prof, "")


        adap_desc = {
            "dp-dac": (
                "• <b>DisplayPort DAC Adapter (DP Mode / Active DP-to-VGA):</b> "
                "Targets <code>DP-*</code> connector, formats EDID as Digital 1.4 8bpc RGB444 (<code>0xA5</code>) with even-field interlaced timings, "
                "and unlocks DPCD active dongle resolution/pixel-clock caps (<code>DC_EXCEED_DONGLE_CAP</code>)."
            ),
            "hdmi-dac": (
                "• <b>HDMI DAC Adapter (HDMI Mode / HDMI-to-VGA):</b> "
                "Targets <code>HDMI-A-*</code> / <code>DP-*</code> connector, formats EDID as Digital 1.4 8bpc RGB444 (<code>0xA2</code>), "
                "and unlocks HDMI/DVI 15kHz low-dotclock (&lt;25 MHz) &amp; high-clock (&gt;165 MHz) validation."
            ),
            "analog-native": (
                "• <b>Native Analog DAC (VGA-1 / DVI-I-1):</b> "
                "Targets native analog RAMDAC output with Analog RGB EDID header (<code>0x0E</code>) and full-frame interlaced timings."
            ),
        }.get(adap, "")

        patch_status = "✓ Enabled (11_linux_rdna_dp_hdmi_interlace.patch)" if rdna_patch else "Disabled"
        self.sum_prof_lbl.setText(prof_desc)
        self.sum_adap_lbl.setText(adap_desc)
        self.sum_target_lbl.setText(
            f"• <b>Resolved Target Port:</b> <code>{eff_conn}</code> (Selected: <code>{conn_raw}</code>) &nbsp;|&nbsp; "
            f"<b>RDNA &amp; DP/HDMI DAC Kernel Unlock Patch:</b> {patch_status}"
        )
        self._update_step3_buttons(prof, eff_conn, edid_ok, edid_msg, rules_ok, kern_15khz, cru_ok)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        for lbl in self.findChildren(AutoWrapLabel):
            lbl.updateGeometry()




    def _update_step3_buttons(
        self,
        prof: str,
        eff_conn: str,
        edid_ok: bool,
        edid_msg: str,
        rules_ok: bool,
        kern_15khz: bool,
        cru_ok: bool,
    ):
        busy = self.proc is not None and self.proc.state() != QProcess.ProcessState.NotRunning
        unlock = hasattr(self, "force_rerun_chk") and self.force_rerun_chk.isChecked()
        self._set_badge(self.step3a_badge, edid_ok, f"Verified ({edid_msg})" if edid_ok else edid_msg)
        self._set_badge(self.step3b_rules_badge, rules_ok, f"Rules Active ({prof})" if rules_ok else f"Rules Needed ({prof})")
        self._set_badge(self.step3b_kern_badge, kern_15khz, "15kHz Kernel Active" if kern_15khz else "Rebuild Needed")
        self._set_badge(self.step3c_badge, cru_ok, "Installed & Ready" if cru_ok else "Not Installed")

        if edid_ok:
            if unlock:
                self.run_env_btn.setText(f"✓ Environment && Bootloader Configured on {eff_conn} (Re-Run setup-interlace-env.sh)")
                self.run_env_btn.setObjectName("verifiedBtn")
                self.run_env_btn.setEnabled(not busy)
            else:
                self.run_env_btn.setText(f"✓ Environment && Bootloader Configured && Active ({eff_conn})")
                self.run_env_btn.setObjectName("verifiedDisabledBtn")
                self.run_env_btn.setEnabled(False)
        else:
            self.run_env_btn.setText(f"Run Environment && Bootloader Setup for {eff_conn} (setup-interlace-env.sh)")
            self.run_env_btn.setObjectName("primaryBtn")
            self.run_env_btn.setEnabled(not busy)
        self.run_live_btn.setEnabled(not busy)

        if rules_ok:
            if unlock:
                self.run_cfg_only_btn.setText(f"✓ Single/Dual-GPU Rules Active ({prof}) — Click to Re-Apply")
                self.run_cfg_only_btn.setObjectName("verifiedBtn")
                self.run_cfg_only_btn.setEnabled(not busy)
            else:
                self.run_cfg_only_btn.setText(f"✓ Single/Dual-GPU Rules Active && Verified ({prof})")
                self.run_cfg_only_btn.setObjectName("verifiedDisabledBtn")
                self.run_cfg_only_btn.setEnabled(False)
        else:
            self.run_cfg_only_btn.setText(f"Apply Single/Dual-GPU Rules Only ({prof})")
            self.run_cfg_only_btn.setObjectName("primaryBtn")
            self.run_cfg_only_btn.setEnabled(not busy)

        # Always keep the fix-interlaced-kernel.sh button enabled & clickable so the user can rebuild
        # anytime a system/kernel update overwrites or breaks interlacing, or switch kernel versions.
        sel_kver = self.kernel_ver_combo.currentData() or "auto"
        if str(sel_kver).startswith("__header_"):
            sel_kver = "auto"
        running_maj_min = re.match(r"^(\d+\.\d+)", self.sys_info["kernel"])
        run_mm = running_maj_min.group(1) if running_maj_min else "7.3"
        eff_kver = run_mm if sel_kver == "auto" else sel_kver
        same_series = (sel_kver == "auto") or (eff_kver == run_mm)

        if kern_15khz and same_series:
            self._set_badge(self.step3b_kern_badge, True, f"15kHz Kernel Active ({run_mm})")
            self.run_kernel_btn.setText(
                f"✓ 15kHz Interlaced Kernel Active ({self.sys_info['kernel']}) — Click to Rebuild / Update (fix-interlaced-kernel.sh)"
            )
            self.run_kernel_btn.setObjectName("verifiedBtn")
        elif not same_series:
            self._set_badge(self.step3b_kern_badge, False, f"Switch to Linux {eff_kver}")
            self.run_kernel_btn.setText(
                f"Fetch, Patch && Install Linux {eff_kver} Interlaced Kernel (fix-interlaced-kernel.sh --kernel-version {eff_kver})"
            )
            self.run_kernel_btn.setObjectName("primaryBtn")
        else:
            self._set_badge(self.step3b_kern_badge, False, "Rebuild Needed")
            self.run_kernel_btn.setText(
                f"Compile && Install Patched Linux {eff_kver} Interlaced Kernel (fix-interlaced-kernel.sh)"
            )
            self.run_kernel_btn.setObjectName("primaryBtn")
        self.run_kernel_btn.setEnabled(not busy)



        if cru_ok:
            if unlock:
                self.install_cru_btn.setText("✓ Linux CRU Installed — Click to Reinstall (install-linux-cru.sh)")
                self.install_cru_btn.setObjectName("verifiedBtn")
                self.install_cru_btn.setEnabled(not busy)
            else:
                self.install_cru_btn.setText("✓ Linux CRU Installed && Verified")
                self.install_cru_btn.setObjectName("verifiedDisabledBtn")
                self.install_cru_btn.setEnabled(False)
            self.launch_cru_btn.setText("✓ Launch Linux CRU (Standalone App)")
            self.launch_cru_btn.setObjectName("primaryBtn")
        else:
            self.install_cru_btn.setText("Install Linux CRU (install-linux-cru.sh)")
            self.install_cru_btn.setObjectName("primaryBtn")
            self.install_cru_btn.setEnabled(not busy)
            self.launch_cru_btn.setText("Launch Linux CRU (Standalone App)")
            self.launch_cru_btn.setObjectName("")

        for btn in (self.run_env_btn, self.run_cfg_only_btn, self.run_kernel_btn, self.install_cru_btn, self.launch_cru_btn):
            btn.style().unpolish(btn)
            btn.style().polish(btn)




    def on_config_changed(self, *_):
        self.cfg["gpu_profile"] = self.gpu_combo.currentData() or "auto"
        self.cfg["adapter_mode"] = self.adapter_combo.currentData() or "auto"
        self.cfg["connector"] = self.conn_combo.currentData() or "auto"
        self.cfg["kernel_version"] = self.kernel_ver_combo.currentData() or "auto"
        self.cfg["edid_path"] = self.edid_edit.text().strip()
        self.cfg["include_rdna_patch"] = self.rdna_patch_chk.isChecked()
        self.cfg["scripts_dir"] = str(self.scripts_dir)
        save_config(self.cfg)
        self.update_architecture_summary()


    def browse_edid(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Custom EDID Binary (.bin)",
            str(Path.home()),
            "EDID Binary Files (*.bin);;All Files (*)",
        )
        if path:
            self.edid_edit.setText(path)

    def append_log(self, text: str):
        self.log_view.moveCursor(QTextCursor.MoveOperation.End)
        self.log_view.insertPlainText(text)
        self.log_view.moveCursor(QTextCursor.MoveOperation.End)

    def copy_log(self):
        QApplication.clipboard().setText(self.log_view.toPlainText())

    def _cleanup_askpass(self):
        self.sudo_keepalive_timer.stop()
        if self.askpass_dir is not None:
            try:
                self.askpass_dir.cleanup()
            except Exception:
                pass
            self.askpass_dir = None

    def _refresh_sudo_timestamp(self):
        if self.askpass_dir is None:
            return
        askpass_bin = Path(self.askpass_dir.name) / "askpass.sh"
        env = dict(os.environ)
        env["SUDO_ASKPASS"] = str(askpass_bin)
        subprocess.run(["/usr/bin/sudo", "-A", "-v"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _prepare_sudo_auth(self) -> str | None:
        self._cleanup_askpass()
        pw = self._sudo_pw
        need_prompt = True
        if pw:
            verify_cached = subprocess.run(
                ["/usr/bin/sudo", "-S", "-v"],
                input=pw + "\n",
                text=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if verify_cached.returncode == 0:
                need_prompt = False

        if need_prompt:
            while True:
                pw, ok = QInputDialog.getText(
                    self,
                    "Administrator Authentication Required",
                    "Enter your sudo password to run privileged system steps:",
                    QLineEdit.EchoMode.Password,
                )
                if not ok:
                    return None
                verify = subprocess.run(
                    ["/usr/bin/sudo", "-S", "-v"],
                    input=pw + "\n",
                    text=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                )
                if verify.returncode == 0:
                    self._sudo_pw = pw
                    break
                QMessageBox.warning(self, "Authentication Failed", "Incorrect sudo password. Please try again.")

        self.askpass_dir = tempfile.TemporaryDirectory(prefix="interlace-suite-auth-")
        tdir = Path(self.askpass_dir.name)
        os.chmod(tdir, 0o700)

        pw_file = tdir / "pw.txt"
        pw_file.write_text(pw + "\n", encoding="utf-8")
        os.chmod(pw_file, 0o600)

        askpass_script = tdir / "askpass.sh"
        askpass_script.write_text(
            f"#!/usr/bin/env bash\ncat '{pw_file}'\n",
            encoding="utf-8",
        )
        os.chmod(askpass_script, 0o700)

        # Wrapper sudo in PATH so non-tty `sudo` and `makepkg`'s `sudo -k pacman` calls
        # automatically authenticate via SUDO_ASKPASS without interactive terminal prompts.
        sudo_wrap = tdir / "sudo"
        sudo_wrap.write_text(
            f"#!/usr/bin/env bash\n"
            f"export SUDO_ASKPASS='{askpass_script}'\n"
            f"args=()\n"
            f"for a in \"$@\"; do\n"
            f"    [ \"$a\" = \"-k\" ] && continue\n"
            f"    args+=(\"$a\")\n"
            f"done\n"
            f"exec /usr/bin/sudo -A \"${{args[@]}}\"\n",
            encoding="utf-8",
        )
        os.chmod(sudo_wrap, 0o700)

        self.sudo_keepalive_timer.start()
        return str(tdir)


    def set_buttons_Busy(self, busy: bool):
        self.stop_btn.setEnabled(busy)
        if busy:
            self.run_env_btn.setEnabled(False)
            self.run_live_btn.setEnabled(False)
            self.run_kernel_btn.setEnabled(False)
            self.run_cfg_only_btn.setEnabled(False)
            self.install_cru_btn.setEnabled(False)
        else:
            self.update_architecture_summary()

    def _format_elapsed(self) -> str:
        if self.task_start_time <= 0:
            return "00m 00s"
        sec = max(0, int(time.time() - self.task_start_time))
        return f"{sec // 60:02d}m {sec % 60:02d}s"

    def _set_progress(self, pct: int, stage: str):
        pct = max(0, min(100, pct))
        self.current_stage_text = stage
        el = self._format_elapsed()
        bar_txt = f"{pct}% ({el})" if self.task_start_time > 0 else f"{pct}%"
        self.stepb_prog_bar.setValue(pct)
        self.stepb_prog_bar.setFormat(bar_txt)
        self.stepb_stage_lbl.setText(f"<b>Progress ({pct}%):</b> {html.escape(stage)} &nbsp;|&nbsp; <b>Elapsed:</b> <code>{el}</code>")

    def _reset_progress(self, status_msg: str = "Build Progress: Idle — Ready to compile or apply GPU rules"):
        self.task_start_time = 0.0
        self.compiled_objects = 0
        self.current_stage_text = "Idle — Ready"
        self.stepb_prog_bar.setValue(0)
        self.stepb_prog_bar.setFormat("0% — Ready")
        self.stepb_stage_lbl.setText(status_msg)




    def _update_elapsed_time(self):
        if self.proc is not None and self.proc.state() != QProcess.ProcessState.NotRunning:
            self._set_progress(self.stepb_prog_bar.value(), self.current_stage_text)

    def _parse_progress_from_output(self, data: str):
        cur = self.stepb_prog_bar.value()
        for raw_line in data.splitlines():
            line = raw_line.strip()
            if not line:
                continue

            m_step = re.search(r"==>\s*\[(\d+)/(\d+)\]\s*(.+)", line)
            if m_step:
                step_num = int(m_step.group(1))
                step_tot = max(1, int(m_step.group(2)))
                desc = m_step.group(3).strip()
                if self.is_kernel_build:
                    step_map = {1: 4, 2: 8, 3: 12, 4: 15, 5: 18, 6: 97}
                    pct = step_map.get(step_num, max(cur, int(100 * step_num / step_tot)))
                else:
                    pct = min(95, int(90 * step_num / step_tot))
                self._set_progress(max(cur, pct), f"[{step_num}/{step_tot}] {desc}")
                cur = self.stepb_prog_bar.value()
                continue

            if not self.is_kernel_build:
                continue

            if "Retrieving sources" in line or "Validating source" in line:
                self._set_progress(max(cur, 20), "Step 5/6: Validating kernel sources & patches...")
            elif "Extracting sources" in line:
                self._set_progress(max(cur, 23), "Step 5/6: Extracting kernel source archive...")
            elif "Starting prepare()" in line or "Applying patch" in line:
                self._set_progress(max(cur, 26), f"Step 5/6: {line.lstrip('=> ')}")
            elif "Starting build()" in line:
                self._set_progress(max(cur, 28), "Step 5/6: Compiling patched kernel (build started)...")
            elif re.match(r"^(CC|CC \[M\]|LD|LD \[M\]|AR|AS|HOSTCC|HOSTLD|OBJCOPY|BTF|GEN)\s+\S+", line):
                self.compiled_objects += 1
                parts = line.split(None, 2)
                target = parts[-1] if parts else ""
                if "vmlinux" in target:
                    self._set_progress(max(cur, 83), f"Step 5/6: Linking {target} ({self.compiled_objects:,} objects built)...")
                else:
                    est = 28 + min(54, int(54 * self.compiled_objects / 4200))
                    short_t = target if len(target) <= 48 else "..." + target[-45:]
                    self._set_progress(
                        max(cur, est),
                        f"Compiling Kernel ({self.compiled_objects:,} objects): {short_t}",
                    )
            elif "MODPOST" in line:
                self._set_progress(max(cur, 85), "Step 5/6: Running MODPOST module symbol verification...")
            elif "Entering fakeroot" in line or "Starting package" in line:
                self._set_progress(max(cur, 88), "Step 5/6: Packaging kernel & compressing modules...")
            elif "Creating package" in line:
                self._set_progress(max(cur, 92), f"Step 5/6: {line.lstrip('=> ')}")
            elif "Installing package" in line or "installing linux-cachyos" in line.lower():
                self._set_progress(max(cur, 95), "Step 5/6: Installing compiled kernel packages via pacman...")
            cur = self.stepb_prog_bar.value()

    def start_script_process(self, title: str, cmd: list[str]):
        if self.proc is not None and self.proc.state() != QProcess.ProcessState.NotRunning:
            QMessageBox.information(self, "Task Running", "Another task is already running. Please wait or stop it first.")
            return

        auth_dir = self._prepare_sudo_auth()
        if auth_dir is None:
            return

        self.task_start_time = time.time()
        self.compiled_objects = 0
        self.is_kernel_build = ("fix-interlaced-kernel.sh" in " ".join(cmd)) and ("--config-only" not in cmd)
        self._set_progress(2, f"Starting: {title}")
        self.elapsed_timer.start()

        self.append_log(f"\n{'=' * 72}\n>>> Starting: {title}\n>>> Command : {' '.join(cmd)}\n{'=' * 72}\n")
        self.task_state_lbl.setText(f"Status: Running — {title}...")
        self.set_buttons_Busy(True)

        self.proc = QProcess(self)
        self.proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.proc.setWorkingDirectory(str(self.scripts_dir))

        env = QProcessEnvironment.systemEnvironment()
        env.insert("SUDO_ASKPASS", str(Path(auth_dir) / "askpass.sh"))
        env.insert("PATH", f"{auth_dir}:{os.environ.get('PATH', '/usr/local/bin:/usr/bin:/bin')}")
        self.proc.setProcessEnvironment(env)

        self.proc.readyReadStandardOutput.connect(self._on_proc_output)
        self.proc.finished.connect(lambda code, status: self._on_proc_finished(title, code, status))
        self.proc.start(cmd[0], cmd[1:])

    def _on_proc_output(self):
        if self.proc is None:
            return
        data = bytes(self.proc.readAllStandardOutput()).decode("utf-8", errors="replace")
        if data:
            self.append_log(data)
            self._parse_progress_from_output(data)

    def _on_proc_finished(self, title: str, code: int, _status):
        self.elapsed_timer.stop()
        el_final = self._format_elapsed()
        self._cleanup_askpass()
        self.set_buttons_Busy(False)
        self.refresh_status()
        if code == 0:
            self._reset_progress(f"Build Progress: Idle — Last task completed in {el_final} (Ready)")
            self.task_state_lbl.setText(f"Status: Completed Successfully ({title})")
            self.append_log(f"\n>>> [SUCCESS] {title} finished (exit code 0).\n")
            QMessageBox.information(self, "Task Completed", f"{title} completed successfully!")
        else:
            self._reset_progress(f"Build Progress: Idle — Last task stopped/failed (exit code {code}) — Ready")
            self.task_state_lbl.setText(f"Status: Failed / Stopped ({title}, exit code {code})")
            self.append_log(f"\n>>> [FAILED] {title} exited with code {code}.\n")
            QMessageBox.warning(self, "Task Stopped or Failed", f"{title} exited with code {code}.\nCheck the log output for details.")

    def stop_current_task(self):
        if self.proc is not None and self.proc.state() != QProcess.ProcessState.NotRunning:
            self.append_log("\n>>> Terminating running task...\n")
            self.proc.terminate()
            self._reset_progress("Build Progress: Idle — Task stopped by user (Ready)")
            QTimer.singleShot(3000, lambda: self.proc.kill() if self.proc and self.proc.state() != QProcess.ProcessState.NotRunning else None)


    def run_setup_env(self, live_only: bool = False):
        script = self.scripts_dir / "setup-interlace-env.sh"
        if not script.exists():
            QMessageBox.critical(self, "Missing Script", f"Could not find {script}")
            return
        cmd = [
            "bash",
            str(script),
            "--gpu-profile",
            self.gpu_combo.currentData() or "auto",
            "--adapter-mode",
            self.adapter_combo.currentData() or "auto",
            "--connector",
            self.conn_combo.currentData() or "auto",
        ]
        edid_path = self.edid_edit.text().strip()
        if edid_path:
            cmd.extend(["--edid", edid_path])
        if live_only:
            cmd.append("--live-only")
            title = "Live EDID Reload (setup-interlace-env.sh --live-only)"
        else:
            title = "Environment & Bootloader Setup (setup-interlace-env.sh)"
        self.start_script_process(title, cmd)

    def run_fix_kernel(self, config_only: bool = False):
        script = self.scripts_dir / "fix-interlaced-kernel.sh"
        if not script.exists():
            QMessageBox.critical(self, "Missing Script", f"Could not find {script}")
            return
        kver = self.kernel_ver_combo.currentData() or "auto"
        if str(kver).startswith("__header_"):
            kver = "auto"
        cmd = [
            "bash",
            str(script),
            "--gpu-profile",
            self.gpu_combo.currentData() or "auto",
            "--adapter-mode",
            self.adapter_combo.currentData() or "auto",
            "--kernel-version",
            kver,
        ]
        if not self.rdna_patch_chk.isChecked():
            cmd.append("--no-rdna-patch")
        if config_only:
            cmd.append("--config-only")
            title = "Apply GPU Architecture Rules Only (fix-interlaced-kernel.sh --config-only)"
        else:
            title = f"Compile & Install Interlaced Kernel [{kver}] (fix-interlaced-kernel.sh)"
        self.start_script_process(title, cmd)


    def run_install_cru(self):
        script = self.scripts_dir / "install-linux-cru.sh"
        if not script.exists():
            QMessageBox.critical(self, "Missing Script", f"Could not find {script}")
            return
        self.start_script_process("Install / Update Linux CRU (install-linux-cru.sh)", ["bash", str(script)])

    def launch_linux_cru(self):
        for candidate in (
            str(Path.home() / ".local" / "bin" / "linux-cru"),
            "/usr/local/bin/linux-cru",
            shutil.which("linux-cru"),
        ):
            if candidate and os.path.exists(candidate):
                subprocess.Popen([candidate], start_new_session=True)
                self.append_log(f"\n>>> Launched standalone Linux CRU: {candidate}\n")
                return
        ans = QMessageBox.question(
            self,
            "Linux CRU Not Installed",
            "Linux CRU (linux-cru) is not installed yet.\nWould you like to run install-linux-cru.sh now?",
        )
        if ans == QMessageBox.StandardButton.Yes:
            self.run_install_cru()

    def closeEvent(self, event):
        self._cleanup_askpass()
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("linux-interlace-suite")
    win = InterlaceSuiteWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()








