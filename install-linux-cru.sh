#!/usr/bin/env bash
# Standalone Installer for Linux CRU (Standardized ToastyX-Style Edition)
set -euo pipefail
umask 022

TMP_APP="$(mktemp)"
trap 'rm -f "$TMP_APP"' EXIT

echo "==> [1/3] Installing Python 3 & PyQt6..."
if ! python3 -c "import PyQt6" >/dev/null 2>&1; then
    if command -v pacman >/dev/null 2>&1; then
        sudo pacman -S --needed --noconfirm python python-pyqt6
    elif command -v apt-get >/dev/null 2>&1; then
        sudo apt-get update && sudo apt-get install -y python3 python3-pyqt6
    elif command -v dnf >/dev/null 2>&1; then
        sudo dnf install -y python3 python3-pyqt6
    elif command -v zypper >/dev/null 2>&1; then
        sudo zypper install -y python3 python-PyQt6
    fi
else
    echo "  -> Python 3 & PyQt6 are already installed."
fi

echo "==> [2/3] Installing /usr/local/bin/linux-cru..."
cat << 'APP_EOF' > "$TMP_APP"
#!/usr/bin/env python3
"""
Linux CRU — Standardized ToastyX-Style Custom Resolution Utility for Linux
==========================================================================
Features:
  - Exact ToastyX CRU timing calculation engine (Automatic CRT, Automatic PC,
    Automatic HDTV, Native PC, Native HDTV, Exact, Exact CRT, CVT Standard,
    CVT-RB Standard, CVT-RB2 Standard, GTF Standard, Manual)
  - Preserves decimal points across Refresh Rate (Hz), Horizontal Scan (kHz),
    Pixel Clock (MHz), and ToastyX half-line (.5) interlaced vertical timings
  - Instant "Switch to Manual (Keep Values)" button that unlocks all calculated
    timings from GTF/CVT/Auto directly into Manual mode without losing values
  - Responsive, non-clipping card UI with Ctrl+Scroll / Ctrl++/- zoom scaling
"""

import glob
import html
import json
import math
import os
import re
import struct
import subprocess
import sys
from pathlib import Path

from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtGui import QBrush, QColor, QFont, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

DEFAULT_EDID_PATH = "/usr/lib/firmware/edid/crufile.bin"
CONFIG_DIR = os.path.expanduser("~/.config/linux-cru")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
DOCS_PROFILES_DIR = os.path.expanduser("~/Documents/linux-cru")
LEGACY_PROFILES_DIR = os.path.join(CONFIG_DIR, "profiles")
PROFILES_DIR = DOCS_PROFILES_DIR

DTD_OFFSETS = (54, 72, 90, 108)
ASPECT_MAP = {
    0: ("16:10", 10, 16),
    1: ("4:3", 3, 4),
    2: ("5:4", 4, 5),
    3: ("16:9", 9, 16),
}

TIMING_PRESETS = [
    "Manual",
    "Automatic CRT",
    "Automatic PC",
    "Automatic HDTV",
    "Native PC",
    "Native HDTV",
    "Exact",
    "Exact CRT",
    "CVT Standard",
    "CVT-RB Standard",
    "CVT-RB2 Standard",
    "GTF Standard",
]

STD_PRESETS = [
    ("1600x1200 (4:3)", 1600, 1),
    ("1400x1050 (4:3)", 1400, 1),
    ("1280x960 (4:3)", 1280, 1),
    ("1152x864 (4:3)", 1152, 1),
    ("1024x768 (4:3)", 1024, 1),
    ("800x600 (4:3)", 800, 1),
    ("640x480 (4:3)", 640, 1),
    ("1920x1440 (4:3)", 1920, 1),
    ("1920x1200 (16:10)", 1920, 0),
    ("1680x1050 (16:10)", 1680, 0),
    ("1440x900 (16:10)", 1440, 0),
    ("1280x800 (16:10)", 1280, 0),
    ("1920x1080 (16:9)", 1920, 3),
    ("1600x900 (16:9)", 1600, 3),
    ("1280x720 (16:9)", 1280, 3),
    ("1280x1024 (5:4)", 1280, 2),
]


def update_checksum(b):
    if len(b) >= 256:
        b[126] = 1
        b[127] = (256 - (sum(b[:127]) % 256)) % 256
        b[255] = (256 - (sum(b[128:255]) % 256)) % 256
    else:
        b[126] = 0
        b[127] = (256 - (sum(b[:127]) % 256)) % 256


def load_ui_config() -> dict:
    cfg = {"ui_scale": 1.0}
    try:
        if os.path.exists(CONFIG_FILE):
            data = json.loads(Path(CONFIG_FILE).read_text(encoding="utf-8"))
            if isinstance(data, dict):
                cfg.update(data)
    except Exception:
        pass
    cfg["ui_scale"] = max(0.75, min(1.65, float(cfg.get("ui_scale", 1.0) or 1.0)))
    return cfg


def save_ui_config(cfg: dict) -> None:
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        Path(CONFIG_FILE).write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    except Exception:
        pass


class AutoWrapLabel(QLabel):
    """QLabel that wraps text cleanly without forcing wide minimum widths or clipping on small windows."""

    def __init__(self, text: str = "", parent: QWidget | None = None):
        super().__init__(text, parent)
        self.setWordWrap(True)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    def minimumSizeHint(self):
        sh = super().minimumSizeHint()
        sh.setWidth(min(sh.width(), 120))
        if self.wordWrap() and self.width() > 50:
            h = self.heightForWidth(self.width())
            if h > 0:
                sh.setHeight(h)
        return sh

    def sizeHint(self):
        sh = super().sizeHint()
        sh.setWidth(min(sh.width(), 220))
        if self.wordWrap() and self.width() > 50:
            h = self.heightForWidth(self.width())
            if h > 0:
                sh.setHeight(h)
        return sh

    def setText(self, text: str):
        super().setText(text)
        self.updateGeometry()


class NoWheelComboBox(QComboBox):
    """QComboBox that ignores scroll wheel unless popup is open so scrolling never mutates settings."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.setMinimumContentsLength(10)

    def wheelEvent(self, event):
        event.ignore()


class NoWheelSpinBox(QSpinBox):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def wheelEvent(self, event):
        if not self.hasFocus():
            event.ignore()
        else:
            super().wheelEvent(event)


class NoWheelDoubleSpinBox(QDoubleSpinBox):
    """QDoubleSpinBox that formats clean integers when .0 and preserves .5 or decimals when present."""

    def __init__(self, trim_trailing_zeros: bool = False, parent: QWidget | None = None):
        super().__init__(parent)
        self.trim_trailing_zeros = trim_trailing_zeros
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def textFromValue(self, value: float) -> str:
        if self.trim_trailing_zeros:
            rounded = round(value, self.decimals())
            if abs(rounded - round(rounded)) < 1e-6:
                return str(int(round(rounded)))
            return f"{rounded:.{self.decimals()}f}".rstrip("0").rstrip(".")
        return super().textFromValue(value)

    def wheelEvent(self, event):
        if not self.hasFocus():
            event.ignore()
        else:
            super().wheelEvent(event)


TOASTYX_AUTO_PC = [
    (1920, 1080, False, 59500, 60500, 88, 44, 148, 4, 5, 36, True, True),
    (1920, 1080, False, 49500, 50500, 528, 44, 148, 4, 5, 36, True, True),
    (1920, 1080, False, 47500, 48500, 638, 44, 148, 4, 5, 36, True, True),
    (1920, 1080, False, 29500, 30500, 88, 44, 148, 4, 5, 36, True, True),
    (1920, 1080, False, 24500, 25500, 528, 44, 148, 4, 5, 36, True, True),
    (1920, 1080, False, 23500, 24500, 638, 44, 148, 4, 5, 36, True, True),
    (1920, 1080, True, 59500, 60500, 88, 44, 148, 4, 10, 31, True, True),
    (1920, 1080, True, 49500, 50500, 528, 44, 148, 4, 10, 31, True, True),
    (1600, 900, False, 59500, 60500, 24, 80, 96, 1, 3, 96, True, True),
    (1366, 768, False, 59500, 60500, 70, 143, 213, 3, 3, 24, True, True),
    (1360, 768, False, 59500, 60500, 64, 112, 256, 3, 6, 18, True, True),
    (1280, 720, False, 59500, 60500, 110, 40, 220, 5, 5, 20, True, True),
    (1280, 720, False, 49500, 50500, 440, 40, 220, 5, 5, 20, True, True),
    (1280, 720, False, 47500, 48500, 960, 40, 220, 5, 5, 20, True, True),
    (1280, 720, False, 29500, 30500, 1760, 40, 220, 5, 5, 20, True, True),
    (1280, 720, False, 24500, 25500, 2420, 40, 220, 5, 5, 20, True, True),
    (1280, 720, False, 23500, 24500, 1760, 40, 220, 5, 5, 20, True, True),
    (1440, 576, True, 49500, 50500, 24, 126, 138, 4, 6, 39, False, False),
    (1440, 480, True, 59500, 60500, 38, 124, 114, 8, 6, 31, False, False),
    (720, 576, False, 49500, 50500, 12, 64, 68, 5, 5, 39, False, False),
    (720, 480, False, 59500, 60500, 16, 62, 60, 9, 6, 30, False, False),
    (640, 480, False, 59500, 60500, 16, 96, 48, 10, 2, 33, False, False),
]

TOASTYX_AUTO_HDTV = [
    (3840, 2160, False, 119500, 120500, 176, 88, 296, 8, 10, 72, True, True),
    (3840, 2160, False, 99500, 100500, 1056, 88, 296, 8, 10, 72, True, True),
    (3840, 2160, False, 59500, 60500, 176, 88, 296, 8, 10, 72, True, True),
    (3840, 2160, False, 49500, 50500, 1056, 88, 296, 8, 10, 72, True, True),
    (3840, 2160, False, 47500, 48500, 1276, 88, 296, 8, 10, 72, True, True),
    (3840, 2160, False, 29500, 30500, 176, 88, 296, 8, 10, 72, True, True),
    (3840, 2160, False, 24500, 25500, 1056, 88, 296, 8, 10, 72, True, True),
    (3840, 2160, False, 23500, 24500, 1276, 88, 296, 8, 10, 72, True, True),
    (2560, 1080, False, 59500, 60500, 248, 44, 148, 4, 5, 11, True, True),
    (2560, 1080, False, 49500, 50500, 548, 44, 148, 4, 5, 36, True, True),
    (1920, 1080, False, 119500, 120500, 88, 44, 148, 4, 5, 36, True, True),
    (1920, 1080, False, 99500, 100500, 528, 44, 148, 4, 5, 36, True, True),
    (1920, 1080, False, 59500, 60500, 88, 44, 148, 4, 5, 36, True, True),
    (1920, 1080, False, 49500, 50500, 528, 44, 148, 4, 5, 36, True, True),
    (1920, 1080, False, 47500, 48500, 638, 44, 148, 4, 5, 36, True, True),
    (1920, 1080, False, 29500, 30500, 88, 44, 148, 4, 5, 36, True, True),
    (1920, 1080, False, 24500, 25500, 528, 44, 148, 4, 5, 36, True, True),
    (1920, 1080, False, 23500, 24500, 638, 44, 148, 4, 5, 36, True, True),
    (1920, 1080, True, 119500, 120500, 88, 44, 148, 4, 10, 31, True, True),
    (1920, 1080, True, 99500, 100500, 528, 44, 148, 4, 10, 31, True, True),
    (1920, 1080, True, 59500, 60500, 88, 44, 148, 4, 10, 31, True, True),
    (1920, 1080, True, 49500, 50500, 528, 44, 148, 4, 10, 31, True, True),
    (1600, 900, False, 59500, 60500, 24, 80, 96, 1, 3, 96, True, True),
    (1366, 768, False, 59500, 60500, 70, 143, 213, 3, 3, 24, True, True),
    (1360, 768, False, 59500, 60500, 64, 112, 256, 3, 6, 18, True, True),
    (1280, 720, False, 119500, 120500, 110, 40, 220, 5, 5, 20, True, True),
    (1280, 720, False, 99500, 100500, 440, 40, 220, 5, 5, 20, True, True),
    (1280, 720, False, 59500, 60500, 110, 40, 220, 5, 5, 20, True, True),
    (1280, 720, False, 49500, 50500, 440, 40, 220, 5, 5, 20, True, True),
    (1280, 720, False, 47500, 48500, 960, 40, 220, 5, 5, 20, True, True),
    (1280, 720, False, 29500, 30500, 1760, 40, 220, 5, 5, 20, True, True),
    (1280, 720, False, 24500, 25500, 2420, 40, 220, 5, 5, 20, True, True),
    (1280, 720, False, 23500, 24500, 1760, 40, 220, 5, 5, 20, True, True),
    (1440, 576, True, 49500, 50500, 24, 126, 138, 4, 6, 39, False, False),
    (1440, 480, True, 59500, 60500, 38, 124, 114, 8, 6, 31, False, False),
    (720, 576, False, 49500, 50500, 12, 64, 68, 5, 5, 39, False, False),
    (720, 480, False, 59500, 60500, 16, 62, 60, 9, 6, 30, False, False),
    (640, 480, False, 59500, 60500, 16, 96, 48, 10, 2, 33, False, False),
]

TOASTYX_AUTO_CRT = [
    (1920, 1440, False, 74500, 75500, 144, 224, 352, 1, 3, 56, False, True),
    (1920, 1440, False, 59500, 60500, 128, 208, 344, 1, 3, 56, False, True),
    (1856, 1392, False, 74500, 75500, 128, 224, 352, 1, 3, 104, False, True),
    (1856, 1392, False, 59500, 60500, 96, 224, 352, 1, 3, 43, False, True),
    (1792, 1344, False, 74500, 75500, 96, 216, 352, 1, 3, 69, False, True),
    (1792, 1344, False, 59500, 60500, 128, 200, 328, 1, 3, 46, False, True),
    (1600, 1200, False, 84500, 85500, 64, 192, 304, 1, 3, 46, True, True),
    (1600, 1200, False, 74500, 75500, 64, 192, 304, 1, 3, 46, True, True),
    (1600, 1200, False, 69500, 70500, 64, 192, 304, 1, 3, 46, True, True),
    (1600, 1200, False, 64500, 65500, 64, 192, 304, 1, 3, 46, True, True),
    (1600, 1200, False, 59500, 60500, 64, 192, 304, 1, 3, 46, True, True),
    (1280, 1024, False, 84500, 85500, 64, 160, 224, 1, 3, 44, True, True),
    (1280, 1024, False, 74500, 75500, 16, 144, 248, 1, 3, 38, True, True),
    (1280, 1024, False, 59500, 60500, 48, 112, 248, 1, 3, 38, True, True),
    (1280, 960, False, 84500, 85500, 64, 160, 224, 1, 3, 47, True, True),
    (1280, 960, False, 59500, 60500, 96, 112, 312, 1, 3, 36, True, True),
    (1152, 864, False, 74500, 75500, 64, 128, 256, 1, 3, 32, True, True),
    (1024, 768, False, 84500, 85500, 48, 96, 208, 1, 3, 36, True, True),
    (1024, 768, False, 74500, 75500, 16, 96, 176, 1, 3, 28, True, True),
    (1024, 768, False, 69500, 70500, 24, 136, 144, 3, 6, 29, False, False),
    (1024, 768, False, 59500, 60500, 24, 136, 160, 3, 6, 29, False, False),
    (800, 600, False, 84500, 85500, 32, 64, 152, 1, 3, 27, True, True),
    (800, 600, False, 74500, 75500, 16, 80, 160, 1, 3, 21, True, True),
    (800, 600, False, 71500, 72500, 56, 120, 64, 37, 6, 23, True, True),
    (800, 600, False, 59500, 60500, 40, 128, 88, 1, 4, 23, True, True),
    (800, 600, False, 55500, 56500, 24, 72, 128, 1, 2, 22, True, True),
    (1440, 576, True, 49500, 50500, 24, 126, 138, 4, 6, 39, False, False),
    (1440, 480, True, 59500, 60500, 38, 124, 114, 8, 6, 31, False, False),
    (720, 576, False, 49500, 50500, 12, 64, 68, 5, 5, 39, False, False),
    (720, 480, False, 59500, 60500, 16, 62, 60, 9, 6, 30, False, False),
    (640, 480, False, 84500, 85500, 56, 56, 80, 1, 3, 25, False, False),
    (640, 480, False, 74500, 75500, 16, 64, 120, 1, 3, 16, False, False),
    (640, 480, False, 71500, 72500, 24, 40, 128, 9, 3, 28, False, False),
    (640, 480, False, 59500, 60500, 16, 96, 48, 10, 2, 33, False, False),
]

TOASTYX_NATIVE = [
    (1920, 1080, False, 60000),
    (1920, 1080, True, 60000),
    (1600, 900, False, 60000),
    (1366, 768, False, 59789),
    (1360, 768, False, 60015),
    (1280, 720, False, 60000),
    (1440, 576, True, 50000),
    (1440, 480, True, 59940),
    (720, 576, False, 50000),
    (720, 480, False, 59940),
    (640, 480, False, 60000),
]

TOASTYX_ASPECT_VSYNC = [
    (2205, 2295, 5),  # 16:9 (2250)
    (2352, 2448, 7),  # 15:9 (2400)
    (2450, 2550, 6),  # 16:10 (2500)
    (2940, 3060, 4),  # 4:3 (3000)
    (3136, 3264, 7),  # 5:4 (3200)
]

CPRIME = 30
MPRIME = 300
MIN_TIME_CVT = 550_000_000
MIN_TIME_CVTRB = 460_000_000
MIN_TIME_CVTRB2 = 460_000_000
MIN_TIME_GTF = 550_000_000



def _toast_aspect_vsync(hactive: int, vactive_frame: int, fields: int) -> int:
    if hactive <= 0:
        return 10 * fields
    aspect = (vactive_frame * 4000) // hactive
    for lo, hi, vs in TOASTYX_ASPECT_VSYNC:
        if lo <= aspect <= hi:
            return vs * fields
    return 10 * fields


def _toast_vrate_divisor(fields: int, pclk_prec: int = 100) -> int:
    return (1_000_000_000 * fields) // pclk_prec


def _toast_hrate_divisor(pclk_prec: int = 100) -> int:
    return 1_000_000 // pclk_prec


def _toast_actual_pclk_from_vrate(vrate_mhz: int, htotal: int, vtotal_frame: int, fields: int, pclk_prec: int = 100) -> int:
    if vrate_mhz <= 0:
        return 1
    div = _toast_vrate_divisor(fields, pclk_prec)
    return (vrate_mhz * htotal * vtotal_frame + (div - 1)) // div


def _toast_actual_vrate(actual_pclk: int, htotal: int, vtotal_frame: int, fields: int, pclk_prec: int = 100) -> int:
    if htotal <= 0 or vtotal_frame <= 0:
        return 0
    return (actual_pclk * _toast_vrate_divisor(fields, pclk_prec)) // htotal // vtotal_frame


def _toast_actual_hrate(actual_pclk: int, htotal: int, pclk_prec: int = 100) -> int:
    if htotal <= 0:
        return 0
    return (actual_pclk * _toast_hrate_divisor(pclk_prec)) // htotal


def _toast_calc_cvt_pass(hactive: int, vactive_frame: int, vrate_mhz: int, interlaced: bool, pclk_prec: int = 100):
    fields = 2 if interlaced else 1
    int_bit = 1 if interlaced else 0
    vfront = 3 * fields
    vsync = _toast_aspect_vsync(hactive, vactive_frame, fields)
    denom = vactive_frame + vfront + int_bit
    hperiod = ((1_000_000_000_000_000 * fields) // max(1, vrate_mhz) - MIN_TIME_CVT * fields) // max(1, denom)
    if hperiod <= 0:
        hperiod = 1
    vsync_vback = MIN_TIME_CVT // hperiod + 1
    vback = vsync_vback * fields + int_bit - vsync
    if vback < 6 * fields + int_bit:
        vback = 6 * fields + int_bit

    ideal_duty = CPRIME * 1_000_000_000 - MPRIME * hperiod
    if ideal_duty < 20_000_000_000:
        ideal_duty = 20_000_000_000
    hblank = (hactive * ideal_duty // (100_000_000_000 - ideal_duty)) // 16 * 16
    hblank = max(32, int(hblank))
    hsync = ((hactive + hblank) // 100) * 8
    hback = hblank // 2
    hfront = hback - hsync
    if hfront < 1:
        hfront = 8
        hblank = (hfront + hsync) * 2
        hback = hblank - hfront - hsync

    htotal = hactive + hblank
    vblank = vfront + vsync + vback
    vtotal = vactive_frame + vblank

    mult = 1_000_000 * pclk_prec
    step = max(1, pclk_prec // 4)
    actual_pclk = ((htotal * mult) // hperiod) // step * step
    return hfront, hsync, hback, hblank, htotal, vfront, vsync, vback, vblank, vtotal, actual_pclk, False, True


def _toast_calc_cvtrb_pass(hactive: int, vactive_frame: int, vrate_mhz: int, interlaced: bool, pclk_prec: int = 100):
    fields = 2 if interlaced else 1
    int_bit = 1 if interlaced else 0
    hfront, hsync, hback = 48, 32, 80
    hblank = 160
    htotal = hactive + hblank
    vfront = 3 * fields
    vsync = _toast_aspect_vsync(hactive, vactive_frame, fields)
    hperiod = ((1_000_000_000_000_000 * fields) // max(1, vrate_mhz) - MIN_TIME_CVTRB * fields) // max(1, vactive_frame)
    if hperiod <= 0:
        hperiod = 1
    vblank_f = MIN_TIME_CVTRB // hperiod + 1
    vback = vblank_f * fields + int_bit - vfront - vsync
    if vback < 6 * fields + int_bit:
        vback = 6 * fields + int_bit
    vblank = vfront + vsync + vback
    vtotal = vactive_frame + vblank
    div = _toast_vrate_divisor(fields, pclk_prec)
    step = max(1, pclk_prec // 4)
    actual_pclk = ((vrate_mhz * htotal * vtotal) // div) // step * step
    return hfront, hsync, hback, hblank, htotal, vfront, vsync, vback, vblank, vtotal, actual_pclk, True, False


def _toast_calc_cvtrb2_pass(hactive: int, vactive_frame: int, vrate_mhz: int, interlaced: bool, pclk_prec: int = 100):
    fields = 2 if interlaced else 1
    int_bit = 1 if interlaced else 0
    hfront, hsync, hback = 8, 32, 40
    hblank = 80
    htotal = hactive + hblank
    vsync = 8 * fields
    vback = 6 * fields + int_bit
    hperiod = ((1_000_000_000_000_000 * fields) // max(1, vrate_mhz) - MIN_TIME_CVTRB2 * fields) // max(1, vactive_frame)
    if hperiod <= 0:
        hperiod = 1
    vblank_f = MIN_TIME_CVTRB2 // hperiod + 1
    vfront = vblank_f * fields + int_bit - vsync - vback
    if vfront < 1 * fields:
        vfront = 1 * fields
    vblank = vfront + vsync + vback
    vtotal = vactive_frame + vblank
    div = _toast_vrate_divisor(fields, pclk_prec)
    actual_pclk = (vrate_mhz * htotal * vtotal) // div
    return hfront, hsync, hback, hblank, htotal, vfront, vsync, vback, vblank, vtotal, actual_pclk, True, False

def _toast_calc_gtf_pass(hactive: int, vactive_frame: int, vrate_mhz: int, interlaced: bool, pclk_prec: int = 100):
    fields = 2 if interlaced else 1
    int_bit = 1 if interlaced else 0
    vfront = 1 * fields
    vsync = 3 * fields
    denom = vactive_frame + vfront + int_bit
    hperiod = ((1_000_000_000_000_000 * fields) // max(1, vrate_mhz) - MIN_TIME_GTF * fields) // max(1, denom)
    if hperiod <= 0:
        hperiod = 1
    vsync_vback = ((MIN_TIME_GTF * 2) // hperiod + 1) // 2
    vback = vsync_vback * fields + int_bit - vsync
    if vback < 1 * fields + int_bit:
        vback = 1 * fields + int_bit

    ideal_duty = CPRIME * 1_000_000_000 - MPRIME * hperiod
    if ideal_duty < 20_000_000_000:
        ideal_duty = 20_000_000_000
    hblank = ((hactive * ideal_duty // (100_000_000_000 - ideal_duty)) + 8) // 16 * 16
    hblank = max(32, int(hblank))
    hsync = ((hactive + hblank + 50) // 100) * 8
    hback = hblank // 2
    hfront = hback - hsync
    if hfront < 1:
        hfront = 8
        hblank = (hfront + hsync) * 2
        hback = hblank - hfront - hsync

    htotal = hactive + hblank
    vblank = vfront + vsync + vback
    vtotal = vactive_frame + vblank
    div = _toast_vrate_divisor(fields, pclk_prec)
    actual_pclk = (vrate_mhz * htotal * vtotal + div // 2) // div
    return hfront, hsync, hback, hblank, htotal, vfront, vsync, vback, vblank, vtotal, actual_pclk, False, True


def _toast_two_pass_standard(pass_fn, hactive: int, vactive_frame: int, vrate_mhz: int, interlaced: bool, pclk_prec: int = 100):
    fields = 2 if interlaced else 1
    hfr, hsy, hbck, hblk, htot, vfr, vsy, vbck, vblk, vtot, _, hpol, vpol = pass_fn(
        hactive, vactive_frame, vrate_mhz, interlaced, pclk_prec
    )
    pclk1 = _toast_actual_pclk_from_vrate(vrate_mhz, htot, vtot, fields, pclk_prec)
    vrate1 = _toast_actual_vrate(pclk1, htot, vtot, fields, pclk_prec)
    hfr, hsy, hbck, hblk, htot, vfr, vsy, vbck, vblk, vtot, _, hpol, vpol = pass_fn(
        hactive, vactive_frame, max(1, vrate1), interlaced, pclk_prec
    )
    actual_pclk = _toast_actual_pclk_from_vrate(max(1, vrate1), htot, vtot, fields, pclk_prec)
    return hfr, hsy, hbck, hblk, htot, vfr, vsy, vbck, vblk, vtot, actual_pclk, hpol, vpol


def _toast_lookup_table(table, hactive: int, vactive_frame: int, interlaced: bool, vrate_mhz: int):
    for row in table:
        ha, va, il, min_vr, max_vr, hfr, hsy, hbck, vfr, vsy, vbck, hpol, vpol = row
        if ha == hactive and va == vactive_frame and bool(il) == bool(interlaced):
            if min_vr <= vrate_mhz <= max_vr:
                return hfr, hsy, hbck, vfr, vsy, vbck, bool(hpol), bool(vpol)
    return None


def _toast_lookup_native_vrate(hactive: int, vactive_frame: int, interlaced: bool) -> int:
    for ha, va, il, vr in TOASTYX_NATIVE:
        if ha == hactive and va == vactive_frame and bool(il) == bool(interlaced):
            return vr
    return 60000

def calculate_timings(preset_name: str, hactive: int, vactive: int, refresh_hz: float, interlaced: bool, pclk_prec: int = 100) -> dict:
    """
    Calculates timings using ToastyX CRU's exact formulas (DetailedResolutionClass).
    Preserves decimal points and ToastyX half-line (.5) interlaced reductions:
      - In ToastyX CRU, CVT Standard / CVT-RB / GTF interlaced timings reduce VBack and VBlank/VTotal
        by 0.5 lines (so VFront = VFront_field + 0.5, VBack = VBack_field - 0.5, and VBlank/VTotal
        are 0.5 lower in per-field view / 0.5 lower on two timing fields in full-frame view).
    """
    if preset_name == "CVT-RB":
        preset_name = "CVT-RB Standard"
    elif preset_name == "CVT-RB2":
        preset_name = "CVT-RB2 Standard"

    hactive = max(64, int(hactive))
    vactive_frame = max(64, int(vactive))
    if interlaced and vactive_frame % 2 != 0:
        vactive_frame += 1

    fields = 2 if interlaced else 1
    vrate_mhz = max(1000, int(round(float(refresh_hz) * 1000.0)))

    matched = None
    if preset_name == "Native PC":
        nat_vr = _toast_lookup_native_vrate(hactive, vactive_frame, interlaced)
        matched = _toast_lookup_table(TOASTYX_AUTO_PC, hactive, vactive_frame, interlaced, nat_vr)
        if matched is None:
            hfr, hsy, hbck, hblk, htot, vfr, vsy, vbck, vblk, vtot, _, hpol, vpol = _toast_two_pass_standard(
                _toast_calc_cvtrb_pass, hactive, vactive_frame, nat_vr, interlaced, pclk_prec
            )
            matched = (hfr, hsy, hbck, vfr, vsy, vbck, hpol, vpol)
        vrate_mhz = nat_vr

    elif preset_name == "Native HDTV":
        nat_vr = _toast_lookup_native_vrate(hactive, vactive_frame, interlaced)
        matched = _toast_lookup_table(TOASTYX_AUTO_HDTV, hactive, vactive_frame, interlaced, nat_vr)
        if matched is None:
            hfr, hsy, hbck, hblk, htot, vfr, vsy, vbck, vblk, vtot, _, hpol, vpol = _toast_two_pass_standard(
                _toast_calc_cvtrb_pass, hactive, vactive_frame, nat_vr, interlaced, pclk_prec
            )
            matched = (hfr, hsy, hbck, vfr, vsy, vbck, hpol, vpol)
        vrate_mhz = nat_vr

    elif preset_name == "Automatic PC":
        matched = _toast_lookup_table(TOASTYX_AUTO_PC, hactive, vactive_frame, interlaced, vrate_mhz)
        if matched is None:
            hfr, hsy, hbck, hblk, htot, vfr, vsy, vbck, vblk, vtot, actual_pclk, hpol, vpol = _toast_two_pass_standard(
                _toast_calc_cvtrb_pass, hactive, vactive_frame, vrate_mhz, interlaced, pclk_prec
            )

    elif preset_name == "Automatic HDTV":
        matched = _toast_lookup_table(TOASTYX_AUTO_HDTV, hactive, vactive_frame, interlaced, vrate_mhz)
        if matched is None:
            hfr, hsy, hbck, hblk, htot, vfr, vsy, vbck, vblk, vtot, actual_pclk, hpol, vpol = _toast_two_pass_standard(
                _toast_calc_cvtrb_pass, hactive, vactive_frame, vrate_mhz, interlaced, pclk_prec
            )

    elif preset_name == "Automatic CRT":
        matched = _toast_lookup_table(TOASTYX_AUTO_CRT, hactive, vactive_frame, interlaced, vrate_mhz)
        if matched is None:
            hfr, hsy, hbck, hblk, htot, vfr, vsy, vbck, vblk, vtot, actual_pclk, hpol, vpol = _toast_two_pass_standard(
                _toast_calc_cvt_pass, hactive, vactive_frame, vrate_mhz, interlaced, pclk_prec
            )

    elif preset_name == "CVT Standard":
        hfr, hsy, hbck, hblk, htot, vfr, vsy, vbck, vblk, vtot, actual_pclk, hpol, vpol = _toast_two_pass_standard(
            _toast_calc_cvt_pass, hactive, vactive_frame, vrate_mhz, interlaced, pclk_prec
        )

    elif preset_name == "CVT-RB Standard":
        hfr, hsy, hbck, hblk, htot, vfr, vsy, vbck, vblk, vtot, actual_pclk, hpol, vpol = _toast_two_pass_standard(
            _toast_calc_cvtrb_pass, hactive, vactive_frame, vrate_mhz, interlaced, pclk_prec
        )

    elif preset_name == "CVT-RB2 Standard":
        hfr, hsy, hbck, hblk, htot, vfr, vsy, vbck, vblk, vtot, actual_pclk, hpol, vpol = _toast_two_pass_standard(
            _toast_calc_cvtrb2_pass, hactive, vactive_frame, vrate_mhz, interlaced, pclk_prec
        )

    elif preset_name == "GTF Standard":
        hfr, hsy, hbck, hblk, htot, vfr, vsy, vbck, vblk, vtot, actual_pclk, hpol, vpol = _toast_two_pass_standard(
            _toast_calc_gtf_pass, hactive, vactive_frame, vrate_mhz, interlaced, pclk_prec
        )
    elif preset_name == "Exact":
        hpol, vpol = True, False
        hfr, hsy = 48, 32
        htot = ((hactive + hfr + hsy + 160) // 160 * 160) if interlaced else ((hactive + hfr + hsy + 80) // 80 * 80)
        hbck = htot - hactive - hfr - hsy
        hblk = hfr + hsy + hbck
        vfr = 3 * fields
        vsy = _toast_aspect_vsync(hactive, vactive_frame, fields)
        vtot = ((vactive_frame + vfr + vsy + 125) // 250 * 250 + 125) if interlaced else ((vactive_frame + vfr + vsy + 125) // 125 * 125)
        vbck = vtot - vactive_frame - vfr - vsy
        vblk = vfr + vsy + vbck
        actual_pclk = _toast_actual_pclk_from_vrate(vrate_mhz, htot, vtot, fields, pclk_prec)

    elif preset_name == "Exact CRT":
        hfr, hsy, hbck, hblk, htot, vfr, vsy, vbck, vblk, vtot, _, hpol, vpol = _toast_two_pass_standard(
            _toast_calc_cvt_pass, hactive, vactive_frame, vrate_mhz, interlaced, pclk_prec
        )
        if interlaced:
            htot = (htot + 159) // 160 * 160
            vtot = (vtot + 124) // 250 * 250 + 125
        else:
            htot = (htot + 79) // 80 * 80
            vtot = (vtot + 124) // 125 * 125
        hbck = htot - hactive - hfr - hsy
        hblk = hfr + hsy + hbck
        vbck = vtot - vactive_frame - vfr - vsy
        vblk = vfr + vsy + vbck
        actual_pclk = _toast_actual_pclk_from_vrate(vrate_mhz, htot, vtot, fields, pclk_prec)

    else:
        hfr, hsy, hbck, hblk, htot, vfr, vsy, vbck, vblk, vtot, actual_pclk, hpol, vpol = _toast_two_pass_standard(
            _toast_calc_cvt_pass, hactive, vactive_frame, vrate_mhz, interlaced, pclk_prec
        )

    if matched is not None:
        hfr, hsy, hbck, vfr, vsy, vbck, hpol, vpol = matched
        hblk = hfr + hsy + hbck
        htot = hactive + hblk
        vblk = vfr + vsy + vbck
        vtot = vactive_frame + vblk
        actual_pclk = _toast_actual_pclk_from_vrate(vrate_mhz, htot, vtot, fields, pclk_prec)

    actual_vrate_mhz = _toast_actual_vrate(actual_pclk, htot, vtot, fields, pclk_prec)
    actual_hrate_hz = _toast_actual_hrate(actual_pclk, htot, pclk_prec)
    pclk_mhz = round(actual_pclk / float(pclk_prec), 3 if pclk_prec == 1000 else 2)
    actual_vrate_hz = round(actual_vrate_mhz / 1000.0, 3)
    target_vrate_hz = round(vrate_mhz / 1000.0, 3)
    hscan_khz = round(actual_hrate_hz / 1000.0, 3)

    if interlaced:
        vfront_dec = float(vfr)
        vsync_dec = float(vsy)
        # Preserve the .5 reduction on VBack and VBlank/VTotal from CVT/GTF interlaced formula:
        vback_dec = round(float(vbck) - 0.5, 1)
        vblank_dec = round(float(vblk) - 0.5, 1)
        vtotal_dec = round(float(vtot) - 0.5, 1)
        vfront_int = max(2, (int(vfr) // 2) * 2)
        vsync_int = max(2, (int(vsy) // 2) * 2)
        vblank_int = max(vfront_int + vsync_int + 2, (int(vblk) // 2) * 2)
        vback_int = max(2, vblank_int - vfront_int - vsync_int)
        vtotal_int = vactive_frame + vblank_int
    else:
        vfront_dec = float(vfr)
        vsync_dec = float(vsy)
        vback_dec = float(vbck)
        vblank_dec = float(vblk)
        vtotal_dec = float(vtot)
        vfront_int = int(vfr)
        vsync_int = int(vsy)
        vback_int = int(vbck)
        vblank_int = int(vblk)
        vtotal_int = int(vtot)

    return {
        "type": "dtd",
        "preset": preset_name,
        "pclk_mhz": pclk_mhz,
        "hactive": int(hactive),
        "hblank": int(hblk),
        "hfront": int(hfr),
        "hsync": int(hsy),
        "hback": int(hbck),
        "htotal": int(htot),
        "vactive": int(vactive_frame),
        "vblank": int(vblank_int),
        "vfront": int(vfront_int),
        "vsync": int(vsync_int),
        "vback": int(vback_int),
        "vtotal": int(vtotal_int),
        "vfront_dec": vfront_dec,
        "vsync_dec": vsync_dec,
        "vback_dec": vback_dec,
        "vblank_dec": vblank_dec,
        "vtotal_dec": vtotal_dec,
        "toast_vfront": int(vfr),
        "toast_vsync": int(vsy),
        "toast_vback": int(vbck),
        "toast_vblank": int(vblk),
        "toast_vtotal": int(vtot),
        "interlaced": bool(interlaced),
        "hsync_pos": bool(hpol),
        "vsync_pos": bool(vpol),
        "vrefresh": target_vrate_hz,
        "actual_vrefresh": actual_vrate_hz,
        "hscan_khz": hscan_khz,
    }


def detect_timing_preset(d: dict) -> str:
    if d.get("type") != "dtd":
        return "Automatic CRT"
    if d.get("preset") in TIMING_PRESETS:
        return d["preset"]
    hz = round(float(d.get("vrefresh", 60.0)), 3)
    for p in (
        "Automatic CRT",
        "Automatic PC",
        "Automatic HDTV",
        "CVT Standard",
        "CVT-RB Standard",
        "CVT-RB2 Standard",
        "GTF Standard",
        "Exact",
        "Exact CRT",
    ):
        c = calculate_timings(p, d["hactive"], d["vactive"], hz, d["interlaced"])
        if all(
            c[k] == d.get(k)
            for k in ("hblank", "hfront", "hsync", "vblank", "vfront", "vsync", "hsync_pos", "vsync_pos")
        ):
            return p
    return "Manual"




def decode_std_timings(b):
    """Decodes the 8 Standard Resolution slots at EDID bytes 38..53."""
    slots = []
    for i in range(8):
        b0, b1 = b[38 + i*2], b[39 + i*2]
        if (b0 == 1 and b1 == 1) or b0 == 0:
            slots.append(None)
        else:
            w = (b0 + 31) * 8
            ar_idx = (b1 >> 6) & 0x03
            ar_name, num, den = ASPECT_MAP[ar_idx]
            h = (w * num) // den
            hz = (b1 & 0x3F) + 60
            slots.append({"w": w, "h": h, "hz": hz, "ar_idx": ar_idx, "ar_name": ar_name})
    return slots


def encode_std_timings(b, slots):
    for i in range(8):
        s = slots[i] if i < len(slots) else None
        if not s:
            b[38 + i*2] = 0x01
            b[39 + i*2] = 0x01
        else:
            b0 = max(1, min(255, (s["w"] // 8) - 31))
            b1 = ((s["ar_idx"] & 0x03) << 6) | max(0, min(63, s["hz"] - 60))
            b[38 + i*2] = b0
            b[39 + i*2] = b1


def decode_displayid_pclk_map(b):
    pclk_map = {}
    if len(b) < 256 or b[128] != 0x70:
        return pclk_map
    ext = b[128:256]
    if ext[5] == 0x03:
        count = ext[7] // 20
        for i in range(count):
            off = 8 + i * 20
            if off + 20 > 128:
                break
            t = ext[off:off+20]
            pclk_10khz = (t[0] | (t[1] << 8) | (t[2] << 16)) + 1
            interlaced = bool(t[3] & 0x10)
            hactive, hblank, _, _, vactive, vblank, _, _ = struct.unpack_from("<HHHHHHHH", t, 4)
            pclk_map[(hactive + 1, hblank + 1, vactive + 1, vblank + 1, interlaced)] = pclk_10khz / 100.0
    return pclk_map


def decode_dtd(block, full_edid=None):
    if block[0] == 0 and block[1] == 0:
        tag = block[3]
        if tag == 0xFC:
            return {"type": "monitor_name", "name": block[5:18].decode('ascii', errors='ignore').strip()}
        elif tag == 0xFD:
            return {
                "type": "range_limits",
                "v_min": block[5], "v_max": block[6],
                "h_min": block[7], "h_max": block[8], "max_pclk": block[9] * 10
            }
        return {"type": "empty", "tag": tag}

    pclk_raw_10khz = block[0] | (block[1] << 8)
    pclk_mhz = pclk_raw_10khz / 100.0
    hactive = block[2] | ((block[4] & 0xF0) << 4)
    hblank = block[3] | ((block[4] & 0x0F) << 8)
    vactive = block[5] | ((block[7] & 0xF0) << 4)
    vblank = block[6] | ((block[7] & 0x0F) << 8)
    hfront = block[8] | ((block[11] & 0xC0) << 2)
    hsync = block[9] | ((block[11] & 0x30) << 4)
    vfront = ((block[10] >> 4) & 0x0F) | ((block[11] & 0x0C) << 2)
    vsync = (block[10] & 0x0F) | ((block[11] & 0x03) << 4)

    flags = block[17]
    interlaced = bool(flags & 0x80)
    vsync_pos = bool(flags & 0x04)
    hsync_pos = bool(flags & 0x02)

    if full_edid is not None and pclk_raw_10khz == 65535:
        pclk_map = decode_displayid_pclk_map(full_edid)
        key = (hactive, hblank, vactive, vblank, interlaced)
        if key in pclk_map:
            pclk_mhz = pclk_map[key]

    htotal = hactive + hblank
    vtotal = vactive + vblank
    mult = 2.0 if interlaced else 1.0
    vrefresh = (pclk_mhz * 1_000_000.0 * mult) / (htotal * vtotal) if (htotal and vtotal) else 0.0
    hscan_khz = (pclk_mhz * 1000.0) / htotal if htotal else 0.0

    res = {
        "type": "dtd", "pclk_mhz": pclk_mhz,
        "hactive": hactive, "hblank": hblank, "hfront": hfront, "hsync": hsync,
        "vactive": vactive, "vblank": vblank, "vfront": vfront, "vsync": vsync,
        "interlaced": interlaced, "hsync_pos": hsync_pos, "vsync_pos": vsync_pos,
        "vrefresh": vrefresh, "hscan_khz": hscan_khz,
        "cru_field_bug": interlaced and (vactive <= hactive * 0.45)
    }
    preset_match = detect_timing_preset(res)
    if preset_match != "Manual":
        calc = calculate_timings(preset_match, hactive, vactive, round(vrefresh, 2), interlaced)
        res["preset"] = preset_match
        res["vfront_dec"] = calc["vfront_dec"]
        res["vsync_dec"] = calc["vsync_dec"]
        res["vback_dec"] = calc["vback_dec"]
        res["vblank_dec"] = calc["vblank_dec"]
        res["vtotal_dec"] = calc["vtotal_dec"]
    return res


def encode_dtd(d, existing_block=None):
    b = bytearray(18)
    if existing_block and len(existing_block) == 18 and (existing_block[0] or existing_block[1]):
        b[12:17] = existing_block[12:17]
    else:
        b[12], b[13], b[14] = 406 & 0xFF, 305 & 0xFF, (((406 >> 8) & 0x0F) << 4) | ((305 >> 8) & 0x0F)

    pclk_10khz = max(1, min(65535, int(round(d["pclk_mhz"] * 100.0))))
    b[0], b[1] = pclk_10khz & 0xFF, (pclk_10khz >> 8) & 0xFF

    hactive, hblank = max(1, min(4095, int(d["hactive"]))), max(1, min(4095, int(d["hblank"])))
    vactive, vblank = max(1, min(4095, int(d["vactive"]))), max(1, min(4095, int(d["vblank"])))
    hfront, hsync = max(1, min(1023, int(d["hfront"]))), max(1, min(1023, int(d["hsync"])))
    vfront, vsync = max(1, min(63, int(d["vfront"]))), max(1, min(63, int(d["vsync"])))

    b[2], b[3] = hactive & 0xFF, hblank & 0xFF
    b[4] = (((hactive >> 8) & 0x0F) << 4) | ((hblank >> 8) & 0x0F)
    b[5], b[6] = vactive & 0xFF, vblank & 0xFF
    b[7] = (((vactive >> 8) & 0x0F) << 4) | ((vblank >> 8) & 0x0F)
    b[8], b[9] = hfront & 0xFF, hsync & 0xFF
    b[10] = ((vfront & 0x0F) << 4) | (vsync & 0x0F)
    b[11] = ((((hfront >> 8) & 0x03) << 6) | (((hsync >> 8) & 0x03) << 4) |
             (((vfront >> 4) & 0x03) << 2) | ((vsync >> 4) & 0x03))
    flags = 0x18 | (0x80 if d["interlaced"] else 0) | (0x04 if d["vsync_pos"] else 0) | (0x02 if d["hsync_pos"] else 0)
    b[17] = flags
    return b


def sync_700mhz_and_displayid(b, high_clock_dtds, unlock_700=True):
    """Automatically manages the 0xFD 700 MHz range descriptor and optional DisplayID extension."""
    for off in DTD_OFFSETS:
        if b[off:off+4] == b'\x00\x00\x00\xfd' and unlock_700:
            b[off+8] = max(b[off+8], 200)
            b[off+9] = max(b[off+9], 70)

    if not high_clock_dtds:
        if len(b) > 128 and b[128] == 0x70:
            del b[128:]
        update_checksum(b)
        return

    if len(b) < 256:
        b.extend(bytearray(256 - len(b)))
    ext = bytearray(128)
    ext[0], ext[1] = 0x70, 0x12
    payload_len = 3 + 20 * len(high_clock_dtds)
    ext[2], ext[5], ext[7] = payload_len, 0x03, 20 * len(high_clock_dtds)
    for idx, d in enumerate(high_clock_dtds):
        t = bytearray(20)
        pclk_10khz = max(1, int(round(d["pclk_mhz"] * 100.0))) - 1
        t[0], t[1], t[2] = pclk_10khz & 0xFF, (pclk_10khz >> 8) & 0xFF, (pclk_10khz >> 16) & 0xFF
        t[3] = (0x10 if d["interlaced"] else 0x00) | 0x80
        hsync = ((max(1, int(d["hfront"])) - 1) & 0x7FFF) | (0x8000 if d["hsync_pos"] else 0)
        vsync = ((max(1, int(d["vfront"])) - 1) & 0x7FFF) | (0x8000 if d["vsync_pos"] else 0)
        struct.pack_into(
            "<HHHHHHHH", t, 4,
            int(d["hactive"]) - 1, int(d["hblank"]) - 1, hsync, int(d["hsync"]) - 1,
            int(d["vactive"]) - 1, int(d["vblank"]) - 1, vsync, int(d["vsync"]) - 1
        )
        ext[8 + idx*20 : 8 + (idx+1)*20] = t
    csum_idx = 5 + payload_len
    ext[csum_idx] = (256 - (sum(ext[1:csum_idx]) % 256)) % 256
    b[128:256] = ext
    update_checksum(b)


def create_blank_crt_edid():
    b = bytearray(128)
    b[0:8] = b'\x00\xff\xff\xff\xff\xff\xff\x00'
    b[8:12] = b'\x22\xf0\xd0\x09'
    b[18], b[19], b[20], b[21], b[22], b[23], b[24] = 1, 3, 0x0E, 41, 31, 120, 0xEA
    b[38:54] = b'\x01\x01' * 8
    for off in DTD_OFFSETS:
        b[off:off+18] = bytes([0, 0, 0, 0x10, 0] + [0] * 13)
    b[108:126] = bytes([
        0x00, 0x00, 0x00, 0xFD, 0x00,
        30, 200, 30, 200, 70, 0x00,
        0x0A, 0x20, 0x20, 0x20, 0x20, 0x20, 0x20
    ])
    update_checksum(b)
    return b


class StandardResDialog(QDialog):
    def __init__(self, parent, initial=None):
        super().__init__(parent)
        self.setWindowTitle("Standard Resolution")
        self.setMinimumSize(390, 310)
        self.resize(450, 355)
        self._updating = False

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer_layout.addWidget(scroll, 1)

        content = QWidget()
        content.setObjectName("dialogContent")
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        cfg_group = QGroupBox("Standard Resolution && Refresh Rate")
        grid = QGridLayout(cfg_group)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(1, 1)

        self.mode_combo = NoWheelComboBox()
        for label, _, _ in STD_PRESETS:
            self.mode_combo.addItem(label)
        self.mode_combo.addItem("Custom — By Aspect Ratio (Auto Height from Width)")
        self.mode_combo.addItem("Custom — Full Resolution (Set Width × Height)")

        self.width_sb = NoWheelSpinBox()
        self.width_sb.setRange(256, 2288)
        self.width_sb.setSingleStep(8)
        self.width_sb.setSuffix(" px")
        self.width_sb.setValue(initial["w"] if initial else 1600)

        self.ar_combo = NoWheelComboBox()
        self.ar_combo.addItems(["16:10", "4:3", "5:4", "16:9", "Custom (From Width × Height)"])
        init_ar_idx = initial["ar_idx"] if (initial and 0 <= initial.get("ar_idx", 1) <= 3) else 1
        self.ar_combo.setCurrentIndex(init_ar_idx)

        self.height_sb = NoWheelSpinBox()
        self.height_sb.setRange(160, 2048)
        self.height_sb.setSingleStep(2)
        self.height_sb.setSuffix(" px")
        init_h = initial["h"] if initial else (1600 * ASPECT_MAP[init_ar_idx][1]) // ASPECT_MAP[init_ar_idx][2]
        self.height_sb.setValue(init_h)

        self.hz_sb = NoWheelSpinBox()
        self.hz_sb.setRange(60, 123)
        self.hz_sb.setSuffix(" Hz")
        self.hz_sb.setValue(initial["hz"] if initial else 85)

        grid.addWidget(QLabel("<b>Mode / Preset:</b>"), 0, 0)
        grid.addWidget(self.mode_combo, 0, 1)
        grid.addWidget(QLabel("<b>Horizontal (Width):</b>"), 1, 0)
        grid.addWidget(self.width_sb, 1, 1)
        grid.addWidget(QLabel("<b>Aspect Ratio:</b>"), 2, 0)
        grid.addWidget(self.ar_combo, 2, 1)
        grid.addWidget(QLabel("<b>Vertical (Height):</b>"), 3, 0)
        grid.addWidget(self.height_sb, 3, 1)
        grid.addWidget(QLabel("<b>Refresh Rate:</b>"), 4, 0)
        grid.addWidget(self.hz_sb, 4, 1)
        layout.addWidget(cfg_group)

        self.preview_lbl = AutoWrapLabel()
        self.preview_lbl.setObjectName("summaryMono")
        layout.addWidget(self.preview_lbl)

        btn_bar = QFrame()
        btn_bar.setObjectName("dialogBtnBar")
        btns = QHBoxLayout(btn_bar)
        btns.setContentsMargins(14, 10, 14, 10)
        btns.setSpacing(8)
        ok_btn = QPushButton("✓ Save Resolution")
        ok_btn.setObjectName("primaryBtn")
        ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btns.addStretch()
        btns.addWidget(cancel_btn)
        btns.addWidget(ok_btn)
        outer_layout.addWidget(btn_bar, 0)

        self.mode_combo.currentIndexChanged.connect(self.on_preset_changed)
        self.width_sb.valueChanged.connect(self.on_width_or_ar_changed)
        self.ar_combo.currentIndexChanged.connect(self.on_ar_changed)
        self.height_sb.valueChanged.connect(self.on_height_changed)
        self.hz_sb.valueChanged.connect(self._update_preview)

        if initial:
            ar_i = initial.get("ar_idx", 1)
            _, num, den = ASPECT_MAP.get(ar_i, ("4:3", 3, 4))
            expected_h = (initial["w"] * num) // den
            if initial.get("h") and initial["h"] != expected_h:
                self.mode_combo.setCurrentIndex(len(STD_PRESETS) + 1)
            else:
                self.mode_combo.setCurrentIndex(len(STD_PRESETS))
        else:
            self.on_preset_changed()
        self._update_preview()

    def _match_aspect_idx(self, w: int, h: int) -> int:
        for ar_i, (_, num, den) in ASPECT_MAP.items():
            if (w * num) // den == h:
                return ar_i
        return -1

    def on_preset_changed(self):
        if self._updating:
            return
        self._updating = True
        idx = self.mode_combo.currentIndex()
        is_preset = idx < len(STD_PRESETS)
        is_by_ar = (idx == len(STD_PRESETS))
        is_full_custom = (idx == len(STD_PRESETS) + 1)

        self.width_sb.setEnabled(not is_preset)
        self.ar_combo.setEnabled(is_by_ar or is_full_custom)
        self.height_sb.setEnabled(is_full_custom)

        if is_preset:
            _, w, ar_idx = STD_PRESETS[idx]
            self.width_sb.setValue(w)
            self.ar_combo.setCurrentIndex(ar_idx)
            _, num, den = ASPECT_MAP[ar_idx]
            self.height_sb.setValue((w * num) // den)
        elif is_by_ar:
            if self.ar_combo.currentIndex() > 3:
                self.ar_combo.setCurrentIndex(1)
            ar_idx = self.ar_combo.currentIndex()
            w = (self.width_sb.value() // 8) * 8
            _, num, den = ASPECT_MAP[ar_idx]
            self.height_sb.setValue((w * num) // den)
        self._updating = False
        self._update_preview()

    def on_width_or_ar_changed(self):
        if self._updating:
            return
        self._updating = True
        w = (self.width_sb.value() // 8) * 8
        idx = self.mode_combo.currentIndex()
        if idx <= len(STD_PRESETS) and self.ar_combo.currentIndex() <= 3:
            ar_idx = self.ar_combo.currentIndex()
            _, num, den = ASPECT_MAP[ar_idx]
            self.height_sb.setValue((w * num) // den)
        else:
            matched_ar = self._match_aspect_idx(w, self.height_sb.value())
            self.ar_combo.setCurrentIndex(matched_ar if matched_ar >= 0 else 4)
        self._updating = False
        self._update_preview()

    def on_ar_changed(self):
        if self._updating:
            return
        ar_idx = self.ar_combo.currentIndex()
        if ar_idx <= 3:
            self._updating = True
            w = (self.width_sb.value() // 8) * 8
            _, num, den = ASPECT_MAP[ar_idx]
            self.height_sb.setValue((w * num) // den)
            self._updating = False
        else:
            if self.mode_combo.currentIndex() != len(STD_PRESETS) + 1:
                self.mode_combo.setCurrentIndex(len(STD_PRESETS) + 1)
        self._update_preview()

    def on_height_changed(self):
        if self._updating:
            return
        self._updating = True
        w = (self.width_sb.value() // 8) * 8
        h = self.height_sb.value()
        matched_ar = self._match_aspect_idx(w, h)
        self.ar_combo.setCurrentIndex(matched_ar if matched_ar >= 0 else 4)
        self._updating = False
        self._update_preview()

    def _update_preview(self):
        w = (self.width_sb.value() // 8) * 8
        h = self.height_sb.value()
        hz = self.hz_sb.value()
        matched_ar = self._match_aspect_idx(w, h)
        if matched_ar >= 0:
            ar_name = ASPECT_MAP[matched_ar][0]
            note = f"Standard EDID Slot: {w} × {h} ({ar_name}) @ {hz} Hz"
        else:
            best_ar = min(ASPECT_MAP.keys(), key=lambda k: abs((w * ASPECT_MAP[k][1]) // ASPECT_MAP[k][2] - h))
            ar_name, num, den = ASPECT_MAP[best_ar]
            std_h = (w * num) // den
            note = (
                f"Selected: {w} × {h} @ {hz} Hz (Custom Vertical Resolution)\n"
                f"Note: Standard 2-byte EDID slots only encode 4 aspect ratios (closest: {w}×{std_h} {ar_name}); "
                f"saving will also offer adding {w}×{h}@{hz}Hz to a Detailed Resolution slot."
            )
        self.preview_lbl.setText(note)

    def get_result(self):
        w = (self.width_sb.value() // 8) * 8
        h = int(self.height_sb.value())
        matched_ar = self._match_aspect_idx(w, h)
        if matched_ar >= 0:
            ar_idx = matched_ar
            ar_name = ASPECT_MAP[ar_idx][0]
            custom_h = False
        else:
            ar_idx = min(ASPECT_MAP.keys(), key=lambda k: abs((w * ASPECT_MAP[k][1]) // ASPECT_MAP[k][2] - h))
            ar_name = f"{ASPECT_MAP[ar_idx][0]}*"
            custom_h = True
        return {"w": w, "h": h, "hz": self.hz_sb.value(), "ar_idx": ar_idx, "ar_name": ar_name, "custom_h": custom_h}


class DTDEditorDialog(QDialog):
    def __init__(self, parent, initial_data):
        super().__init__(parent)
        self.setWindowTitle("Detailed Resolution — ToastyX Timing & Manual Editor")
        self.setMinimumSize(360, 420)
        self.resize(620, 680)
        self._updating = False
        self._resp_compact = None
        self._last_hv_anchor = 0   # 0 = Back Porch, 1 = Blanking, 2 = Total
        self._last_rate_anchor = 0 # 0 = Refresh Rate (VRate), 1 = H-Scan (HRate), 2 = Pixel Clock

        if initial_data.get("type") != "dtd":
            initial_data = calculate_timings("Automatic CRT", 1600, 1200, 85.0, False)
            initial_preset = "Automatic CRT"
        else:
            initial_preset = detect_timing_preset(initial_data)

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer_layout.addWidget(scroll, 1)

        content = QWidget()
        content.setObjectName("dialogContent")
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        top_group = QGroupBox("Timing Standard && Target Refresh")
        self.top_grid = QGridLayout(top_group)
        self.top_grid.setHorizontalSpacing(10)
        self.top_grid.setVerticalSpacing(8)
        self.top_grid.setColumnStretch(1, 1)

        self.preset_combo = NoWheelComboBox()
        self.preset_combo.addItems(TIMING_PRESETS)
        self.preset_combo.setCurrentText(initial_preset if initial_preset in TIMING_PRESETS else "Manual")
        self.preset_combo.setMinimumWidth(0)
        self.preset_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        self.switch_manual_btn = QPushButton("✎ Switch to Manual")
        self.switch_manual_btn.setObjectName("accentBtn")
        self.switch_manual_btn.setMinimumWidth(0)
        self.switch_manual_btn.setToolTip(
            "Immediately switch from the current timing preset (GTF, CVT, Automatic, etc.) to Manual mode "
            "while preserving every calculated timing field, decimal value, and frequency so you can fine-tune them."
        )
        self.switch_manual_btn.clicked.connect(self.switch_to_manual_preserving_values)

        self.refresh_sb = NoWheelDoubleSpinBox(trim_trailing_zeros=False)
        self.refresh_sb.setRange(10.0, 600.0)
        self.refresh_sb.setDecimals(3)
        self.refresh_sb.setSingleStep(1.0)
        self.refresh_sb.setSuffix(" Hz")
        self.refresh_sb.setMinimumWidth(0)
        self.refresh_sb.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.refresh_sb.setValue(float(initial_data.get("vrefresh", 85.0)))
        self._saved_refresh_hz = self.refresh_sb.value()
        self._was_native = ("Native" in initial_preset)

        self.interlaced_cb = QCheckBox("Interlaced")
        self.interlaced_cb.setChecked(bool(initial_data.get("interlaced", False)))
        self.interlaced_cb.setToolTip(
            "Enable Interlaced timing. In CVT/GTF/CVT-RB standards, vertical back porch and total/blanking "
            "preserve ToastyX's exact 0.5-line reduction."
        )

        self.lbl_timing = QLabel("<b>Timing:</b>")
        self.lbl_target_ref = QLabel("<b>Target Refresh:</b>")
        layout.addWidget(top_group)

        param_group = QGroupBox("Timing Parameters (Horizontal && Vertical)")
        pgrid = QGridLayout(param_group)
        pgrid.setHorizontalSpacing(8)
        pgrid.setVerticalSpacing(6)
        pgrid.setColumnStretch(1, 1)
        pgrid.setColumnStretch(2, 1)

        hdr_font = QFont()
        hdr_font.setBold(True)
        self.h_hdr = QLabel("Horizontal (px)")
        self.v_hdr = QLabel("Vertical (lines)")
        self.h_hdr.setFont(hdr_font)
        self.v_hdr.setFont(hdr_font)
        pgrid.addWidget(self.h_hdr, 0, 1)
        pgrid.addWidget(self.v_hdr, 0, 2)

        def make_h_sb(lo, hi, val, step=1):
            sb = NoWheelSpinBox()
            sb.setRange(lo, hi)
            sb.setSingleStep(step)
            sb.setSuffix(" px")
            sb.setMinimumWidth(0)
            sb.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            sb.setValue(max(lo, min(hi, int(val))))
            return sb

        def make_v_sb(lo, hi, val, step=0.5):
            sb = NoWheelDoubleSpinBox(trim_trailing_zeros=True)
            sb.setDecimals(1)
            sb.setRange(float(lo), float(hi))
            sb.setSingleStep(float(step))
            sb.setSuffix(" lines")
            sb.setMinimumWidth(0)
            sb.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            sb.setValue(max(float(lo), min(float(hi), float(val))))
            return sb

        hact = int(initial_data["hactive"])
        hblk = int(initial_data["hblank"])
        hfr = int(initial_data["hfront"])
        hsy = int(initial_data["hsync"])
        hbck = max(1, hblk - hfr - hsy)

        vact = int(initial_data["vactive"])
        vfr_dec = float(initial_data.get("vfront_dec", min(63, initial_data["vfront"])))
        vsy_dec = float(initial_data.get("vsync_dec", min(63, initial_data["vsync"])))
        vblk_dec = float(initial_data.get("vblank_dec", initial_data["vblank"]))
        vbck_dec = float(initial_data.get("vback_dec", max(0.5, vblk_dec - vfr_dec - vsy_dec)))
        vtot_dec = float(initial_data.get("vtotal_dec", vact + vblk_dec))

        self.hactive_sb = make_h_sb(64, 4095, hact, 8)
        self.vactive_sb = NoWheelSpinBox()
        self.vactive_sb.setRange(64, 4095)
        self.vactive_sb.setSingleStep(2 if initial_data.get("interlaced") else 1)
        self.vactive_sb.setSuffix(" lines")
        self.vactive_sb.setMinimumWidth(0)
        self.vactive_sb.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.vactive_sb.setValue(max(64, min(4095, vact)))

        self.hfront_sb = make_h_sb(1, 1023, hfr, 8)
        self.vfront_sb = make_v_sb(1.0, 63.5, vfr_dec, 0.5)
        self.hsync_sb = make_h_sb(1, 1023, hsy, 8)
        self.vsync_sb = make_v_sb(1.0, 63.5, vsy_dec, 0.5)
        self.hback_sb = make_h_sb(1, 4095, hbck, 8)
        self.vback_sb = make_v_sb(0.5, 4095.5, vbck_dec, 0.5)
        self.hblank_sb = make_h_sb(2, 4095, hblk, 8)
        self.vblank_sb = make_v_sb(2.0, 4095.5, vblk_dec, 0.5)
        self.htotal_sb = make_h_sb(66, 8190, hact + hblk, 8)
        self.vtotal_sb = make_v_sb(66.0, 8190.5, vtot_dec, 0.5)

        self.rb_anchor_back = QRadioButton("Back Porch:")
        self.rb_anchor_blank = QRadioButton("Blanking:")
        self.rb_anchor_total = QRadioButton("Total:")
        self.rb_anchor_back.setChecked(True)
        self.hv_anchor_group = QButtonGroup(self)
        self.hv_anchor_group.addButton(self.rb_anchor_back, 0)
        self.hv_anchor_group.addButton(self.rb_anchor_blank, 1)
        self.hv_anchor_group.addButton(self.rb_anchor_total, 2)
        self.hv_anchor_group.idToggled.connect(self._on_hv_anchor_changed)

        pgrid.addWidget(QLabel("Active:"), 1, 0)
        pgrid.addWidget(self.hactive_sb, 1, 1)
        pgrid.addWidget(self.vactive_sb, 1, 2)
        pgrid.addWidget(QLabel("Front Porch:"), 2, 0)
        pgrid.addWidget(self.hfront_sb, 2, 1)
        pgrid.addWidget(self.vfront_sb, 2, 2)
        pgrid.addWidget(QLabel("Sync Width:"), 3, 0)
        pgrid.addWidget(self.hsync_sb, 3, 1)
        pgrid.addWidget(self.vsync_sb, 3, 2)
        pgrid.addWidget(self.rb_anchor_back, 4, 0)
        pgrid.addWidget(self.hback_sb, 4, 1)
        pgrid.addWidget(self.vback_sb, 4, 2)
        pgrid.addWidget(self.rb_anchor_blank, 5, 0)
        pgrid.addWidget(self.hblank_sb, 5, 1)
        pgrid.addWidget(self.vblank_sb, 5, 2)
        pgrid.addWidget(self.rb_anchor_total, 6, 0)
        pgrid.addWidget(self.htotal_sb, 6, 1)
        pgrid.addWidget(self.vtotal_sb, 6, 2)

        self.hsync_pos_cb = QCheckBox("+HSync")
        self.hsync_pos_cb.setToolTip("Positive Horizontal Sync Polarity")
        self.hsync_pos_cb.setChecked(bool(initial_data.get("hsync_pos", False)))
        self.vsync_pos_cb = QCheckBox("+VSync")
        self.vsync_pos_cb.setToolTip("Positive Vertical Sync Polarity")
        self.vsync_pos_cb.setChecked(bool(initial_data.get("vsync_pos", True)))
        pgrid.addWidget(QLabel("Polarity:"), 7, 0)
        pgrid.addWidget(self.hsync_pos_cb, 7, 1)
        pgrid.addWidget(self.vsync_pos_cb, 7, 2)
        layout.addWidget(param_group)

        freq_group = QGroupBox("Frequency && Pixel Clock (Decimal Precision)")
        self.fgrid = QGridLayout(freq_group)
        self.fgrid.setHorizontalSpacing(10)
        self.fgrid.setVerticalSpacing(6)
        self.fgrid.setColumnStretch(1, 1)

        self.rb_rate_v = QRadioButton("Refresh Rate:")
        self.rb_rate_h = QRadioButton("H-Scan Rate:")
        self.rb_rate_pclk = QRadioButton("Pixel Clock:")
        self.rb_rate_v.setChecked(True)
        self.rate_anchor_group = QButtonGroup(self)
        self.rate_anchor_group.addButton(self.rb_rate_v, 0)
        self.rate_anchor_group.addButton(self.rb_rate_h, 1)
        self.rate_anchor_group.addButton(self.rb_rate_pclk, 2)
        self.rate_anchor_group.idToggled.connect(self._on_rate_anchor_changed)

        self.actual_vrate_lbl = AutoWrapLabel("Actual: - Hz")
        self.actual_hrate_lbl = AutoWrapLabel("Actual: - kHz")
        self.actual_pclk_lbl = AutoWrapLabel("Actual: - MHz")

        self.hscan_sb = NoWheelDoubleSpinBox(trim_trailing_zeros=False)
        self.hscan_sb.setRange(5.0, 500.0)
        self.hscan_sb.setDecimals(3)
        self.hscan_sb.setSingleStep(0.1)
        self.hscan_sb.setSuffix(" kHz")
        self.hscan_sb.setMinimumWidth(0)
        self.hscan_sb.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        htot_init = max(1, int(initial_data["hactive"]) + int(initial_data["hblank"]))
        hscan_init = float(initial_data.get("hscan_khz", (float(initial_data["pclk_mhz"]) * 1000.0) / htot_init))
        self.hscan_sb.setValue(max(5.0, min(500.0, hscan_init)))

        self.pclk_sb = NoWheelDoubleSpinBox(trim_trailing_zeros=False)
        self.pclk_sb.setRange(1.0, 2500.00)
        self.pclk_sb.setDecimals(2)
        self.pclk_sb.setSingleStep(0.01)
        self.pclk_sb.setSuffix(" MHz")
        self.pclk_sb.setMinimumWidth(0)
        self.pclk_sb.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.pclk_sb.setValue(float(initial_data["pclk_mhz"]))
        layout.addWidget(freq_group)

        calc_group = QGroupBox("Live Timing Summary && ToastyX Interlace Breakdown")
        calc_layout = QVBoxLayout(calc_group)
        self.stats_label = AutoWrapLabel()
        self.stats_label.setObjectName("summaryMono")
        self.stats_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        calc_layout.addWidget(self.stats_label)
        layout.addWidget(calc_group)

        btn_bar = QFrame()
        btn_bar.setObjectName("dialogBtnBar")
        btn_layout = QHBoxLayout(btn_bar)
        btn_layout.setContentsMargins(14, 10, 14, 10)
        btn_layout.setSpacing(8)

        self.ok_btn = QPushButton("✓ Save Resolution")
        self.ok_btn.setObjectName("primaryBtn")
        self.ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addStretch()
        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(self.ok_btn)
        outer_layout.addWidget(btn_bar, 0)

        self.preset_combo.currentIndexChanged.connect(self.on_mode_changed)
        self.hactive_sb.valueChanged.connect(self.on_active_or_target_changed)
        self.vactive_sb.valueChanged.connect(self.on_active_or_target_changed)
        self.refresh_sb.valueChanged.connect(self.on_refresh_changed)
        self.interlaced_cb.toggled.connect(self.on_interlaced_toggled)
        for sb in (self.hfront_sb, self.hsync_sb):
            sb.valueChanged.connect(self.on_h_front_or_sync_changed)
        self.hback_sb.valueChanged.connect(self.on_h_back_changed)
        self.hblank_sb.valueChanged.connect(self.on_h_blank_changed)
        self.htotal_sb.valueChanged.connect(self.on_h_total_changed)
        for sb in (self.vfront_sb, self.vsync_sb):
            sb.valueChanged.connect(self.on_v_front_or_sync_changed)
        self.vback_sb.valueChanged.connect(self.on_v_back_changed)
        self.vblank_sb.valueChanged.connect(self.on_v_blank_changed)
        self.vtotal_sb.valueChanged.connect(self.on_v_total_changed)
        self.hscan_sb.valueChanged.connect(self.on_hscan_changed)
        self.pclk_sb.valueChanged.connect(self.on_pclk_changed)
        self.hsync_pos_cb.toggled.connect(self.update_live_stats)
        self.vsync_pos_cb.toggled.connect(self.update_live_stats)

        self.on_mode_changed()
        self._reflow_dialog_layout()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reflow_dialog_layout()

    def _reflow_dialog_layout(self):
        if not hasattr(self, "top_grid") or not hasattr(self, "fgrid"):
            return
        compact = self.width() < 560
        if compact == self._resp_compact:
            return
        self._resp_compact = compact

        while self.top_grid.count():
            self.top_grid.takeAt(0)
        if compact:
            self.top_grid.addWidget(self.lbl_timing, 0, 0)
            self.top_grid.addWidget(self.preset_combo, 0, 1)
            self.top_grid.addWidget(self.switch_manual_btn, 1, 0, 1, 2)
            self.top_grid.addWidget(self.lbl_target_ref, 2, 0)
            self.top_grid.addWidget(self.refresh_sb, 2, 1)
            self.top_grid.addWidget(self.interlaced_cb, 3, 0, 1, 2)
            self.top_grid.setColumnStretch(1, 1)
            self.top_grid.setColumnStretch(2, 0)
        else:
            self.top_grid.addWidget(self.lbl_timing, 0, 0)
            self.top_grid.addWidget(self.preset_combo, 0, 1)
            self.top_grid.addWidget(self.switch_manual_btn, 0, 2)
            self.top_grid.addWidget(self.lbl_target_ref, 1, 0)
            self.top_grid.addWidget(self.refresh_sb, 1, 1)
            self.top_grid.addWidget(self.interlaced_cb, 1, 2)
            self.top_grid.setColumnStretch(1, 1)
            self.top_grid.setColumnStretch(2, 0)

        while self.fgrid.count():
            self.fgrid.takeAt(0)
        if compact:
            self.fgrid.addWidget(self.rb_rate_v, 0, 0)
            self.fgrid.addWidget(self.actual_vrate_lbl, 0, 1)
            self.fgrid.addWidget(self.rb_rate_h, 1, 0)
            self.fgrid.addWidget(self.hscan_sb, 1, 1)
            self.fgrid.addWidget(self.actual_hrate_lbl, 2, 1)
            self.fgrid.addWidget(self.rb_rate_pclk, 3, 0)
            self.fgrid.addWidget(self.pclk_sb, 3, 1)
            self.fgrid.addWidget(self.actual_pclk_lbl, 4, 1)
            self.fgrid.setColumnStretch(1, 1)
            self.fgrid.setColumnStretch(2, 0)
        else:
            self.fgrid.addWidget(self.rb_rate_v, 0, 0)
            self.fgrid.addWidget(self.actual_vrate_lbl, 0, 1, 1, 2)
            self.fgrid.addWidget(self.rb_rate_h, 1, 0)
            self.fgrid.addWidget(self.hscan_sb, 1, 1)
            self.fgrid.addWidget(self.actual_hrate_lbl, 1, 2)
            self.fgrid.addWidget(self.rb_rate_pclk, 2, 0)
            self.fgrid.addWidget(self.pclk_sb, 2, 1)
            self.fgrid.addWidget(self.actual_pclk_lbl, 2, 2)
            self.fgrid.setColumnStretch(1, 1)
            self.fgrid.setColumnStretch(2, 0)

    def _on_hv_anchor_changed(self, btn_id: int, checked: bool):
        if checked:
            self._last_hv_anchor = btn_id

    def _on_rate_anchor_changed(self, btn_id: int, checked: bool):
        if checked:
            self._last_rate_anchor = btn_id

    def switch_to_manual_preserving_values(self):
        """Immediately switches from any preset (GTF, CVT, Auto, etc.) to Manual while keeping every calculated field."""
        if self.preset_combo.currentText() == "Manual":
            return
        self._updating = True
        self.preset_combo.setCurrentText("Manual")
        self._updating = False
        self._apply_manual_enable_state()
        self.update_live_stats()

    def _apply_manual_enable_state(self):
        preset = self.preset_combo.currentText()
        is_manual = (preset == "Manual")
        is_native = ("Native" in preset)
        self.switch_manual_btn.setEnabled(not is_manual)
        self.switch_manual_btn.setText(
            "✓ Manual Active (Unlocked)" if is_manual else "✎ Switch to Manual (Keep Values)"
        )
        for w in (
            self.hfront_sb, self.hsync_sb, self.hback_sb, self.hblank_sb, self.htotal_sb,
            self.vfront_sb, self.vsync_sb, self.vback_sb, self.vblank_sb, self.vtotal_sb,
            self.hscan_sb, self.pclk_sb, self.hsync_pos_cb, self.vsync_pos_cb,
            self.rb_anchor_back, self.rb_anchor_blank, self.rb_anchor_total,
            self.rb_rate_v, self.rb_rate_h, self.rb_rate_pclk,
        ):
            w.setEnabled(is_manual)
        self.refresh_sb.setEnabled(not is_native)

    def _sync_rates_in_manual(self):
        htotal = max(1, int(self.hactive_sb.value() + self.hblank_sb.value()))
        vtotal = max(1.0, float(self.vactive_sb.value()) + float(self.vblank_sb.value()))
        fields = 2.0 if self.interlaced_cb.isChecked() else 1.0

        if self._last_rate_anchor == 0:
            vrate_hz = float(self.refresh_sb.value())
            frame_rate = vrate_hz / fields
            pclk_mhz = round((frame_rate * htotal * vtotal) / 1_000_000.0, 2)
            pclk_mhz = max(1.0, min(2500.0, pclk_mhz))
            self.pclk_sb.setValue(pclk_mhz)
            hscan_khz = (pclk_mhz * 1000.0) / htotal
            self.hscan_sb.setValue(round(max(5.0, min(500.0, hscan_khz)), 3))
        elif self._last_rate_anchor == 1:
            hscan_khz = float(self.hscan_sb.value())
            pclk_mhz = round((hscan_khz * htotal) / 1000.0, 2)
            pclk_mhz = max(1.0, min(2500.0, pclk_mhz))
            self.pclk_sb.setValue(pclk_mhz)
            actual_hz = (pclk_mhz * 1_000_000.0 * fields) / (htotal * vtotal)
            self.refresh_sb.setValue(round(max(10.0, min(600.0, actual_hz)), 3))
        else:
            pclk_mhz = float(self.pclk_sb.value())
            actual_hz = (pclk_mhz * 1_000_000.0 * fields) / (htotal * vtotal)
            hscan_khz = (pclk_mhz * 1000.0) / htotal
            self.refresh_sb.setValue(round(max(10.0, min(600.0, actual_hz)), 3))
            self.hscan_sb.setValue(round(max(5.0, min(500.0, hscan_khz)), 3))

    def on_mode_changed(self):
        if self._updating:
            return
        preset = self.preset_combo.currentText()
        is_manual = (preset == "Manual")
        is_native = ("Native" in preset)
        if is_native and not self._was_native:
            self._saved_refresh_hz = self.refresh_sb.value()
        elif not is_native and self._was_native:
            self._updating = True
            self.refresh_sb.setValue(self._saved_refresh_hz)
            self._updating = False
        self._was_native = is_native

        self._apply_manual_enable_state()
        if not is_manual:
            self.on_active_or_target_changed()
        else:
            self.update_live_stats()

    def on_interlaced_toggled(self):
        if self._updating:
            return
        il = self.interlaced_cb.isChecked()
        self.vactive_sb.setSingleStep(2 if il else 1)
        if self.preset_combo.currentText() != "Manual":
            self.on_active_or_target_changed()
            return
        self._updating = True
        if il and self.vactive_sb.value() % 2 != 0:
            self.vactive_sb.setValue(self.vactive_sb.value() + 1)
        self._updating = False
        self.update_live_stats()

    def on_refresh_changed(self):
        if self._updating:
            return
        if self.preset_combo.currentText() == "Manual":
            self._updating = True
            self.rb_rate_v.setChecked(True)
            self._last_rate_anchor = 0
            self._sync_rates_in_manual()
            self._updating = False
            self.update_live_stats()
        else:
            self.on_active_or_target_changed()

    def on_active_or_target_changed(self):
        if self._updating:
            return
        preset = self.preset_combo.currentText()
        if "Native" not in preset:
            self._saved_refresh_hz = self.refresh_sb.value()
        self._updating = True
        if self.interlaced_cb.isChecked() and self.vactive_sb.value() % 2 != 0:
            self.vactive_sb.setValue(self.vactive_sb.value() + 1)
        if preset != "Manual":
            res = calculate_timings(
                preset,
                self.hactive_sb.value(),
                self.vactive_sb.value(),
                self.refresh_sb.value(),
                self.interlaced_cb.isChecked(),
            )
            if "Native" in preset:
                self.refresh_sb.setValue(float(res["vrefresh"]))
            hfr, hsy, hbck, hblk, htot = res["hfront"], res["hsync"], res["hback"], res["hblank"], res["htotal"]
            vfr_d = min(63.5, float(res["vfront_dec"]))
            vsy_d = min(63.5, float(res["vsync_dec"]))
            vbck_d = float(res["vback_dec"])
            vblk_d = float(res["vblank_dec"])
            vtot_d = float(res["vtotal_dec"])

            self.hfront_sb.setValue(hfr)
            self.hsync_sb.setValue(hsy)
            self.hback_sb.setValue(max(1, hbck))
            self.hblank_sb.setValue(hblk)
            self.htotal_sb.setValue(htot)

            self.vfront_sb.setValue(vfr_d)
            self.vsync_sb.setValue(vsy_d)
            self.vback_sb.setValue(max(0.5, vbck_d))
            self.vblank_sb.setValue(vblk_d)
            self.vtotal_sb.setValue(vtot_d)

            self.pclk_sb.setValue(float(res["pclk_mhz"]))
            self.hscan_sb.setValue(float(res["hscan_khz"]))
            self.hsync_pos_cb.setChecked(bool(res["hsync_pos"]))
            self.vsync_pos_cb.setChecked(bool(res["vsync_pos"]))
        else:
            if self._last_hv_anchor == 2:
                hblk = max(2, self.htotal_sb.value() - self.hactive_sb.value())
                self.hblank_sb.setValue(hblk)
                self.hback_sb.setValue(max(1, hblk - self.hfront_sb.value() - self.hsync_sb.value()))
                vblk = max(2.0, self.vtotal_sb.value() - float(self.vactive_sb.value()))
                self.vblank_sb.setValue(vblk)
                self.vback_sb.setValue(max(0.5, vblk - self.vfront_sb.value() - self.vsync_sb.value()))
            else:
                self.htotal_sb.setValue(self.hactive_sb.value() + self.hblank_sb.value())
                self.vtotal_sb.setValue(float(self.vactive_sb.value()) + self.vblank_sb.value())
            self._sync_rates_in_manual()
        self._updating = False
        self.update_live_stats()

    def on_h_front_or_sync_changed(self):
        if self._updating:
            return
        self._updating = True
        if self._last_hv_anchor == 0:
            hblk = min(4095, self.hfront_sb.value() + self.hsync_sb.value() + self.hback_sb.value())
            self.hblank_sb.setValue(hblk)
            self.htotal_sb.setValue(self.hactive_sb.value() + hblk)
        elif self._last_hv_anchor == 1:
            self.hback_sb.setValue(max(1, self.hblank_sb.value() - self.hfront_sb.value() - self.hsync_sb.value()))
            self.htotal_sb.setValue(self.hactive_sb.value() + self.hblank_sb.value())
        else:
            hblk = max(2, self.htotal_sb.value() - self.hactive_sb.value())
            self.hblank_sb.setValue(hblk)
            self.hback_sb.setValue(max(1, hblk - self.hfront_sb.value() - self.hsync_sb.value()))
        self._sync_rates_in_manual()
        self._updating = False
        self.update_live_stats()

    def on_h_back_changed(self):
        if self._updating:
            return
        self._updating = True
        self.rb_anchor_back.setChecked(True)
        self._last_hv_anchor = 0
        hblk = min(4095, self.hfront_sb.value() + self.hsync_sb.value() + self.hback_sb.value())
        self.hblank_sb.setValue(hblk)
        self.htotal_sb.setValue(self.hactive_sb.value() + hblk)
        self._sync_rates_in_manual()
        self._updating = False
        self.update_live_stats()

    def on_h_blank_changed(self):
        if self._updating:
            return
        self._updating = True
        self.rb_anchor_blank.setChecked(True)
        self._last_hv_anchor = 1
        min_blk = self.hfront_sb.value() + self.hsync_sb.value() + 1
        if self.hblank_sb.value() < min_blk:
            self.hblank_sb.setValue(min_blk)
        self.hback_sb.setValue(self.hblank_sb.value() - self.hfront_sb.value() - self.hsync_sb.value())
        self.htotal_sb.setValue(self.hactive_sb.value() + self.hblank_sb.value())
        self._sync_rates_in_manual()
        self._updating = False
        self.update_live_stats()

    def on_h_total_changed(self):
        if self._updating:
            return
        self._updating = True
        self.rb_anchor_total.setChecked(True)
        self._last_hv_anchor = 2
        min_tot = self.hactive_sb.value() + self.hfront_sb.value() + self.hsync_sb.value() + 1
        if self.htotal_sb.value() < min_tot:
            self.htotal_sb.setValue(min_tot)
        hblk = self.htotal_sb.value() - self.hactive_sb.value()
        self.hblank_sb.setValue(hblk)
        self.hback_sb.setValue(hblk - self.hfront_sb.value() - self.hsync_sb.value())
        self._sync_rates_in_manual()
        self._updating = False
        self.update_live_stats()

    def on_v_front_or_sync_changed(self):
        if self._updating:
            return
        self._updating = True
        if self._last_hv_anchor == 0:
            vblk = self.vfront_sb.value() + self.vsync_sb.value() + self.vback_sb.value()
            self.vblank_sb.setValue(vblk)
            self.vtotal_sb.setValue(float(self.vactive_sb.value()) + vblk)
        elif self._last_hv_anchor == 1:
            self.vback_sb.setValue(max(0.5, self.vblank_sb.value() - self.vfront_sb.value() - self.vsync_sb.value()))
            self.vtotal_sb.setValue(float(self.vactive_sb.value()) + self.vblank_sb.value())
        else:
            vblk = max(2.0, self.vtotal_sb.value() - float(self.vactive_sb.value()))
            self.vblank_sb.setValue(vblk)
            self.vback_sb.setValue(max(0.5, vblk - self.vfront_sb.value() - self.vsync_sb.value()))
        self._sync_rates_in_manual()
        self._updating = False
        self.update_live_stats()

    def on_v_back_changed(self):
        if self._updating:
            return
        self._updating = True
        self.rb_anchor_back.setChecked(True)
        self._last_hv_anchor = 0
        vblk = self.vfront_sb.value() + self.vsync_sb.value() + self.vback_sb.value()
        self.vblank_sb.setValue(vblk)
        self.vtotal_sb.setValue(float(self.vactive_sb.value()) + vblk)
        self._sync_rates_in_manual()
        self._updating = False
        self.update_live_stats()

    def on_v_blank_changed(self):
        if self._updating:
            return
        self._updating = True
        self.rb_anchor_blank.setChecked(True)
        self._last_hv_anchor = 1
        min_blk = self.vfront_sb.value() + self.vsync_sb.value() + 0.5
        if self.vblank_sb.value() < min_blk:
            self.vblank_sb.setValue(min_blk)
        self.vback_sb.setValue(max(0.5, self.vblank_sb.value() - self.vfront_sb.value() - self.vsync_sb.value()))
        self.vtotal_sb.setValue(float(self.vactive_sb.value()) + self.vblank_sb.value())
        self._sync_rates_in_manual()
        self._updating = False
        self.update_live_stats()

    def on_v_total_changed(self):
        if self._updating:
            return
        self._updating = True
        self.rb_anchor_total.setChecked(True)
        self._last_hv_anchor = 2
        min_tot = float(self.vactive_sb.value()) + self.vfront_sb.value() + self.vsync_sb.value() + 0.5
        if self.vtotal_sb.value() < min_tot:
            self.vtotal_sb.setValue(min_tot)
        vblk = self.vtotal_sb.value() - float(self.vactive_sb.value())
        self.vblank_sb.setValue(vblk)
        self.vback_sb.setValue(max(0.5, vblk - self.vfront_sb.value() - self.vsync_sb.value()))
        self._sync_rates_in_manual()
        self._updating = False
        self.update_live_stats()

    def on_hscan_changed(self):
        if self._updating:
            return
        self._updating = True
        self.rb_rate_h.setChecked(True)
        self._last_rate_anchor = 1
        self._sync_rates_in_manual()
        self._updating = False
        self.update_live_stats()

    def on_pclk_changed(self):
        if self._updating:
            return
        self._updating = True
        self.rb_rate_pclk.setChecked(True)
        self._last_rate_anchor = 2
        self._sync_rates_in_manual()
        self._updating = False
        self.update_live_stats()

    def update_live_stats(self):
        if self._updating:
            return
        hact = int(self.hactive_sb.value())
        hfr = int(self.hfront_sb.value())
        hsy = int(self.hsync_sb.value())
        hblk = int(self.hblank_sb.value())
        hbck = hblk - hfr - hsy
        htotal = hact + hblk

        vact = int(self.vactive_sb.value())
        vfr_d = float(self.vfront_sb.value())
        vsy_d = float(self.vsync_sb.value())
        vblk_d = float(self.vblank_sb.value())
        vbck_d = vblk_d - vfr_d - vsy_d
        vtotal_d = float(vact) + vblk_d

        pclk = round(float(self.pclk_sb.value()), 2)
        interlaced = self.interlaced_cb.isChecked()
        fields = 2.0 if interlaced else 1.0

        frame_rate = (pclk * 1_000_000.0) / (htotal * vtotal_d) if (htotal and vtotal_d) else 0.0
        actual_hz = frame_rate * fields
        hscan_khz = (pclk * 1000.0) / htotal if htotal else 0.0
        line_us = (htotal / pclk) if pclk else 0.0

        self.actual_vrate_lbl.setText(f"Actual: {actual_hz:.3f} Hz")
        self.actual_hrate_lbl.setText(f"Actual: {hscan_khz:.3f} kHz")
        self.actual_pclk_lbl.setText(f"Actual: {pclk:.2f} MHz")

        scan_str = f"{actual_hz:.3f} Hz (Interlaced, {frame_rate:.3f} fps)" if interlaced else f"{actual_hz:.3f} Hz (Progressive)"
        enc_str = "DisplayID (>655 MHz)" if pclk > 655.35 else "Standard EDID DTD"

        def fmt_v(v: float) -> str:
            return str(int(round(v))) if abs(v - round(v)) < 1e-6 else f"{v:.1f}"

        if interlaced:
            v_field_line = (
                f"ToastyX Field:  VFront={vfr_d/2.0:.1f} | VSync={vsy_d/2.0:.1f} | "
                f"VBack={vbck_d/2.0:.2f} | VBlank={vblk_d/2.0:.2f} | VTotal={vtotal_d/2.0:.2f}\n"
            )
        else:
            v_field_line = ""

        warnings = []
        if htotal > 4095:
            warnings.append("HTotal > 4095!")
        if hbck < 1 or vbck_d < 0.5:
            warnings.append("Back Porch <= 0!")
        if hscan_khz > 140.0:
            warnings.append(">140 kHz H-Scan")
        if pclk > 700.0:
            warnings.append(">700 MHz Clock!")
        status_str = " | ".join(warnings) if warnings else f"Valid ({enc_str})"

        self.stats_label.setText(
            f"Actual Refresh: {scan_str}\n"
            f"H-Scan Rate:    {hscan_khz:.3f} kHz ({line_us:.2f} µs line)\n"
            f"Pixel Clock:    {pclk:.2f} MHz ({htotal} × {fmt_v(vtotal_d)} total)\n"
            f"{v_field_line}"
            f"Status:         {status_str}"
        )

    def get_result(self):
        interlaced = self.interlaced_cb.isChecked()
        vact = int(self.vactive_sb.value())
        if interlaced and vact % 2 != 0:
            vact += 1
        vfr_dec = float(self.vfront_sb.value())
        vsy_dec = float(self.vsync_sb.value())
        vbck_dec = float(self.vback_sb.value())
        vblk_dec = float(self.vblank_sb.value())
        vtot_dec = float(vact) + vblk_dec

        if interlaced:
            vfr_int = max(2, int(round(vfr_dec / 2.0)) * 2)
            vsy_int = max(2, int(round(vsy_dec / 2.0)) * 2)
            vblk_int = max(vfr_int + vsy_int + 2, int(math.floor((vblk_dec + 0.5) / 2.0)) * 2)
        else:
            vfr_int = max(1, int(round(vfr_dec)))
            vsy_int = max(1, int(round(vsy_dec)))
            vblk_int = max(vfr_int + vsy_int + 1, int(round(vblk_dec)))

        return {
            "type": "dtd",
            "preset": self.preset_combo.currentText(),
            "pclk_mhz": round(float(self.pclk_sb.value()), 2),
            "hactive": int(self.hactive_sb.value()),
            "hblank": int(self.hblank_sb.value()),
            "hfront": int(self.hfront_sb.value()),
            "hsync": int(self.hsync_sb.value()),
            "vactive": vact,
            "vblank": vblk_int,
            "vfront": vfr_int,
            "vsync": vsy_int,
            "vfront_dec": vfr_dec,
            "vsync_dec": vsy_dec,
            "vback_dec": vbck_dec,
            "vblank_dec": vblk_dec,
            "vtotal_dec": vtot_dec,
            "interlaced": interlaced,
            "hsync_pos": self.hsync_pos_cb.isChecked(),
            "vsync_pos": self.vsync_pos_cb.isChecked(),
            "vrefresh": round(float(self.refresh_sb.value()), 3),
            "hscan_khz": round(float(self.hscan_sb.value()), 3),
        }


def get_active_fw_map():
    """Parses /sys/module/drm/parameters/edid_firmware into {port: rel_fw_path}."""
    fw_map = {}
    param_path = "/sys/module/drm/parameters/edid_firmware"
    if os.path.exists(param_path):
        try:
            raw = open(param_path, "r").read().strip()
            for part in raw.split(","):
                part = part.strip()
                if ":" in part:
                    conn, rel = part.split(":", 1)
                    fw_map[conn.strip()] = rel.strip()
        except Exception:
            pass
    return fw_map


def scan_drm_ports():
    """Returns list of dicts for all DRM video ports plus offline DVI-I-1 if not present."""
    fw_map = get_active_fw_map()
    ports = []
    seen_names = set()
    for p in sorted(glob.glob("/sys/class/drm/card*-*")):
        base = os.path.basename(p)
        if not os.path.isdir(p) or "Writeback" in base or "-" not in base:
            continue
        card, port_name = base.split("-", 1)
        status_file = os.path.join(p, "status")
        edid_file = os.path.join(p, "edid")
        status = open(status_file).read().strip() if os.path.exists(status_file) else "unknown"
        has_edid = False
        if os.path.exists(edid_file):
            try:
                has_edid = len(open(edid_file, "rb").read()) >= 128
            except Exception:
                pass
        rel_fw = fw_map.get(port_name)
        if not rel_fw:
            if port_name == "VGA-1" and os.path.exists(DEFAULT_EDID_PATH):
                rel_fw = "edid/crufile.bin"
            else:
                rel_fw = f"edid/cru-{port_name.lower()}.bin"
        ports.append({
            "port": port_name,
            "card": card,
            "sysfs_dir": p,
            "edid_path": edid_file,
            "status": status,
            "has_edid": has_edid,
            "rel_fw": rel_fw,
            "fw_path": f"/usr/lib/firmware/{rel_fw}",
            "active_override": port_name in fw_map,
        })
        seen_names.add(port_name)

    for fallback_port in ("VGA-1", "DVI-I-1"):
        if fallback_port not in seen_names:
            rel_fw = fw_map.get(fallback_port, "edid/crufile.bin" if fallback_port == "VGA-1" else f"edid/cru-{fallback_port.lower()}.bin")
            ports.append({
                "port": fallback_port,
                "card": "offline",
                "sysfs_dir": "",
                "edid_path": "",
                "status": "offline profile",
                "has_edid": False,
                "rel_fw": rel_fw,
                "fw_path": f"/usr/lib/firmware/{rel_fw}",
                "active_override": fallback_port in fw_map,
            })

    ports.sort(key=lambda x: (
        not x["active_override"],
        x["status"] != "connected",
        not ("VGA" in x["port"] or "DVI" in x["port"]),
        x["port"]
    ))
    return ports


class LinuxCRUWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Linux CRU — Custom Resolution Utility")
        self.resize(740, 660)
        self.setMinimumSize(380, 420)
        os.makedirs(DOCS_PROFILES_DIR, exist_ok=True)
        os.makedirs(LEGACY_PROFILES_DIR, exist_ok=True)
        self._sync_initial_documents_profiles()

        self.ui_cfg = load_ui_config()
        self.ui_scale = float(self.ui_cfg.get("ui_scale", 1.0) or 1.0)
        self._resp_state = None
        self.dtd_dec_overrides = {}

        self.ports = scan_drm_ports()
        self.current_port_info = self.ports[0]
        self.current_path = ""
        self.high_clock_dtds = []
        self.edid_bytes = create_blank_crt_edid()
        self.std_slots = decode_std_timings(self.edid_bytes)
        self._switching_port = False

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setCentralWidget(scroll)

        central = QWidget()
        central.setObjectName("scrollContent")
        scroll.setWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(12)

        # Header Row (Title + Zoom button only — no subtitle description)
        hdr_row = QHBoxLayout()
        self.title_lbl = AutoWrapLabel("Linux CRU — Custom Resolution Utility")
        self.title_lbl.setObjectName("mainTitle")
        hdr_row.addWidget(self.title_lbl, 1, Qt.AlignmentFlag.AlignVCenter)

        self.zoom_btn = QPushButton(f"🔍 {int(round(self.ui_scale * 100))}%")
        self.zoom_btn.setToolTip("Hold Ctrl + Scroll Wheel (or Ctrl + / -) to zoom UI. Click to reset to 100%.")
        self.zoom_btn.clicked.connect(lambda: self.apply_ui_scale(1.0))
        hdr_row.addWidget(self.zoom_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(hdr_row)

        # Status Banner Card
        self.banner_card = QFrame()
        self.banner_card.setObjectName("bannerCard")
        banner_layout = QHBoxLayout(self.banner_card)
        banner_layout.setContentsMargins(14, 10, 14, 10)
        banner_layout.setSpacing(10)
        self.path_label = AutoWrapLabel("Source: New Blank Profile")
        self.path_label.setObjectName("bannerLabel")
        self.path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        banner_layout.addWidget(self.path_label, 1)

        self.port_badge = QLabel("Port Ready")
        self.port_badge.setObjectName("badgeOk")
        self.port_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        banner_layout.addWidget(self.port_badge, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.banner_card)

        # Top Port & Profile Selector
        top_group = QGroupBox("1. Video Port && EDID Profile")
        top_vbox = QVBoxLayout(top_group)
        top_vbox.setSpacing(10)

        sel_grid = QGridLayout()
        sel_grid.setHorizontalSpacing(10)
        sel_grid.setVerticalSpacing(8)
        self.port_combo = NoWheelComboBox()
        self._populate_port_combo()
        self.port_combo.currentIndexChanged.connect(self.on_port_changed)

        self.profile_combo = NoWheelComboBox()
        self.profile_combo.activated.connect(self.on_profile_selected)

        self.lbl_port = QLabel("<b>Target Port:</b>")
        self.lbl_prof = QLabel("<b>EDID Profile:</b>")
        sel_grid.addWidget(self.lbl_port, 0, 0)
        sel_grid.addWidget(self.port_combo, 0, 1)
        sel_grid.addWidget(self.lbl_prof, 1, 0)
        sel_grid.addWidget(self.profile_combo, 1, 1)
        sel_grid.setColumnStretch(1, 1)
        top_vbox.addLayout(sel_grid)

        self.top_btn_grid = QGridLayout()
        self.top_btn_grid.setSpacing(8)
        self.drm_btn = QPushButton("⬇ Pull Port EDID")
        self.drm_btn.setToolTip("Reads the live EDID from the currently selected video port.")
        self.drm_btn.clicked.connect(self.read_drm_edid)
        self.save_prof_btn = QPushButton("💾 Save Profile...")
        self.save_prof_btn.setToolTip("Saves current timings as a named .bin profile in ~/Documents/linux-cru/")
        self.save_prof_btn.clicked.connect(self.save_named_profile)
        self.open_btn = QPushButton("📂 Import .bin...")
        self.open_btn.clicked.connect(self.open_bin)
        self.new_btn = QPushButton("✨ New Blank")
        self.new_btn.clicked.connect(self.new_blank_edid)
        self.top_buttons = [self.drm_btn, self.save_prof_btn, self.open_btn, self.new_btn]
        for i, b in enumerate(self.top_buttons):
            b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            self.top_btn_grid.addWidget(b, 0, i)
        top_vbox.addLayout(self.top_btn_grid)
        layout.addWidget(top_group)

        # Detailed Resolutions Group (4 Slots)
        dtd_group = QGroupBox("2. Detailed Resolutions (4 Slots — Double-Click to Edit)")
        dtd_layout = QVBoxLayout(dtd_group)
        dtd_layout.setSpacing(8)
        self.table = QTableWidget(4, 6)
        self.table.setHorizontalHeaderLabels([
            "Slot", "Resolution", "Refresh Rate", "H-Scan", "Pixel Clock", "Timing / Sync"
        ])
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        for col in range(1, 6):
            hdr.setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setMinimumHeight(148)
        self.table.doubleClicked.connect(self.edit_selected_dtd)
        dtd_layout.addWidget(self.table)

        self.dtd_btn_grid = QGridLayout()
        self.dtd_btn_grid.setSpacing(8)
        self.edit_dtd_btn = QPushButton("✎ Add / Edit Detailed Resolution...")
        self.edit_dtd_btn.setObjectName("primaryBtn")
        self.edit_dtd_btn.clicked.connect(self.edit_selected_dtd)
        self.del_dtd_btn = QPushButton("Clear Slot")
        self.del_dtd_btn.clicked.connect(self.clear_selected_dtd)
        self.del_all_dtd_btn = QPushButton("Clear All")
        self.del_all_dtd_btn.clicked.connect(self.clear_all_dtds)
        self.dtd_buttons = [self.edit_dtd_btn, self.del_dtd_btn, self.del_all_dtd_btn]
        for i, b in enumerate(self.dtd_buttons):
            self.dtd_btn_grid.addWidget(b, 0, i)
        dtd_layout.addLayout(self.dtd_btn_grid)
        layout.addWidget(dtd_group)

        # Standard Resolutions Group (8 Slots)
        std_group = QGroupBox("3. Standard Resolutions (8 Slots)")
        self.std_box_layout = QVBoxLayout(std_group)
        self.std_box_layout.setSpacing(8)
        self.std_list = QListWidget()
        self.std_list.setMinimumHeight(96)
        self.std_list.doubleClicked.connect(self.edit_std_res)
        self.std_box_layout.addWidget(self.std_list)

        self.std_btn_grid = QGridLayout()
        self.std_btn_grid.setSpacing(8)
        self.add_std_btn = QPushButton("➕ Add...")
        self.add_std_btn.clicked.connect(self.add_std_res)
        self.edit_std_btn = QPushButton("✎ Edit...")
        self.edit_std_btn.clicked.connect(self.edit_std_res)
        self.del_std_btn = QPushButton("Delete")
        self.del_std_btn.clicked.connect(self.del_std_res)
        self.del_all_std_btn = QPushButton("Delete All")
        self.del_all_std_btn.clicked.connect(self.del_all_std_res)
        self.std_buttons = [self.add_std_btn, self.edit_std_btn, self.del_std_btn, self.del_all_std_btn]
        for i, b in enumerate(self.std_buttons):
            self.std_btn_grid.addWidget(b, 0, i)
        self.std_box_layout.addLayout(self.std_btn_grid)
        layout.addWidget(std_group)

        # Bottom Actions Card
        bot_card = QFrame()
        bot_card.setObjectName("actionCard")
        self.bot_btn_grid = QGridLayout(bot_card)
        self.bot_btn_grid.setContentsMargins(12, 10, 12, 10)
        self.bot_btn_grid.setSpacing(8)
        self.export_btn = QPushButton("📤 Export .bin...")
        self.export_btn.clicked.connect(self.save_bin_as)
        self.live_btn = QPushButton("⚡ Apply Live (No Reboot)")
        self.live_btn.setObjectName("accentBtn")
        self.live_btn.setToolTip("Loads the EDID into the kernel DRM driver and triggers a hotplug refresh without rebooting.")
        self.live_btn.clicked.connect(self.apply_live_no_reboot)
        self.install_btn = QPushButton("🚀 Install && Rebuild Initramfs")
        self.install_btn.setObjectName("primaryBtn")
        self.install_btn.setToolTip("Saves to /usr/lib/firmware/edid/, applies live, and rebuilds initramfs for boot persistence.")
        self.install_btn.clicked.connect(self.install_to_firmware)
        self.bot_buttons = [self.export_btn, self.live_btn, self.install_btn]
        for i, b in enumerate(self.bot_buttons):
            self.bot_btn_grid.addWidget(b, 0, i)
        layout.addWidget(bot_card)

        self._setup_zoom_shortcuts()
        self.apply_ui_scale(self.ui_scale, save=False)
        self.table.selectRow(0)
        self.on_port_changed(self.port_combo.currentIndex())
        self._reflow_responsive()

    def _sync_initial_documents_profiles(self):
        """Ensures ~/Documents/linux-cru exists and migrates/copies any existing user .bin profiles so they are selectable."""
        try:
            os.makedirs(DOCS_PROFILES_DIR, exist_ok=True)
            for src_dir in (LEGACY_PROFILES_DIR, os.path.expanduser("~/Documents")):
                if not os.path.isdir(src_dir):
                    continue
                for fn in sorted(os.listdir(src_dir)):
                    if not fn.lower().endswith(".bin"):
                        continue
                    src_p = os.path.join(src_dir, fn)
                    dst_p = os.path.join(DOCS_PROFILES_DIR, fn)
                    if os.path.isfile(src_p) and not os.path.exists(dst_p):
                        try:
                            with open(src_p, "rb") as fsrc:
                                data = fsrc.read()
                            if len(data) >= 128 and data[:8] == b"\x00\xff\xff\xff\xff\xff\xff\x00":
                                with open(dst_p, "wb") as fdst:
                                    fdst.write(data)
                        except Exception:
                            pass
        except Exception:
            pass

    def _populate_port_combo(self):
        """Populates Target Port dropdown with connected ports in an active segment and disconnected ports greyed out."""
        self.port_combo.blockSignals(True)
        self.port_combo.clear()

        hdr_font = QFont()
        hdr_font.setBold(True)

        connected = [info for info in self.ports if info.get("status") == "connected"]
        disconnected = [info for info in self.ports if info.get("status") != "connected"]
        seen_ports = set()
        first_selectable_idx = -1

        if connected:
            self.port_combo.addItem("── Connected Video Ports ──", None)
            h_item = self.port_combo.model().item(self.port_combo.count() - 1)
            if h_item is not None:
                h_item.setEnabled(False)
                h_item.setFont(hdr_font)
                h_item.setForeground(QBrush(QColor("#56d364")))
            for info in connected:
                seen_ports.add(info["port"])
                tag = f" [✓ EDID: {info['rel_fw']}]" if info.get("active_override") else ""
                label = f"● {info['port']} ({info['card']}, connected){tag}"
                self.port_combo.addItem(label, info)
                if first_selectable_idx < 0:
                    first_selectable_idx = self.port_combo.count() - 1

        if disconnected:
            self.port_combo.addItem("── Disconnected Video Ports ──", None)
            h_item = self.port_combo.model().item(self.port_combo.count() - 1)
            if h_item is not None:
                h_item.setEnabled(False)
                h_item.setFont(hdr_font)
                h_item.setForeground(QBrush(QColor("#8b949e")))
            for info in disconnected:
                seen_ports.add(info["port"])
                tag = f" [EDID: {info['rel_fw']}]" if info.get("active_override") else ""
                label = f"○ {info['port']} ({info['card']}, {info['status']}){tag}"
                self.port_combo.addItem(label, info)
                d_item = self.port_combo.model().item(self.port_combo.count() - 1)
                if d_item is not None:
                    if connected:
                        d_item.setEnabled(False)
                        d_item.setForeground(QBrush(QColor("#6e7681")))
                    elif first_selectable_idx < 0:
                        first_selectable_idx = self.port_combo.count() - 1

        missing_fallbacks = [
            fb for fb in ("DP-1", "DP-2", "DP-3", "HDMI-A-1", "HDMI-A-2", "VGA-1", "DVI-I-1")
            if fb not in seen_ports
        ]
        if missing_fallbacks:
            self.port_combo.addItem("── Pre-Configure / Unlisted Ports ──", None)
            h_item = self.port_combo.model().item(self.port_combo.count() - 1)
            if h_item is not None:
                h_item.setEnabled(False)
                h_item.setFont(hdr_font)
                h_item.setForeground(QBrush(QColor("#8b949e")))
            for fb in missing_fallbacks:
                rel_fw = "edid/crufile.bin" if fb == "VGA-1" else f"edid/cru-{fb.lower()}.bin"
                fb_info = {
                    "card": "none",
                    "port": fb,
                    "status": "unlisted",
                    "sysfs_dir": "",
                    "edid_path": "",
                    "has_edid": False,
                    "rel_fw": rel_fw,
                    "fw_path": f"/usr/lib/firmware/{rel_fw}",
                    "active_override": False,
                }
                self.port_combo.addItem(f"○ {fb} (Pre-configure / Not currently detected)", fb_info)
                f_item = self.port_combo.model().item(self.port_combo.count() - 1)
                if f_item is not None:
                    f_item.setEnabled(False)
                    f_item.setForeground(QBrush(QColor("#6e7681")))

        if first_selectable_idx >= 0:
            self.port_combo.setCurrentIndex(first_selectable_idx)
        self.port_combo.blockSignals(False)

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
        self.ui_scale = max(0.75, min(1.65, round(scale, 2)))
        if save:
            self.ui_cfg["ui_scale"] = self.ui_scale
            save_ui_config(self.ui_cfg)
        if hasattr(self, "zoom_btn"):
            self.zoom_btn.setText(f"🔍 {int(round(self.ui_scale * 100))}%")

        base_pt = round(10.0 * self.ui_scale, 1)
        small_pt = round(9.0 * self.ui_scale, 1)
        title_pt = round(14.5 * self.ui_scale, 1)
        grp_pt = round(10.8 * self.ui_scale, 1)
        row_h = max(26, int(round(31 * self.ui_scale)))

        for r in range(4):
            self.table.setRowHeight(r, row_h)
        self.table.setMinimumHeight(max(136, int(round(row_h * 4 + 34 * self.ui_scale))))

        QApplication.instance().setStyleSheet(f"""
            QMainWindow, QDialog, QWidget#scrollContent, QWidget#dialogContent {{
                background-color: #16181d; color: #e6edf3; font-size: {base_pt}pt;
            }}
            QScrollArea {{ border: none; background-color: #16181d; }}
            QLabel, QRadioButton, QCheckBox {{ color: #e6edf3; font-size: {base_pt}pt; }}
            QLabel#mainTitle {{ font-size: {title_pt}pt; font-weight: bold; color: #ffffff; }}
            QLabel#mainSubtitle {{ font-size: {small_pt}pt; color: #9da7b3; }}
            QLabel#bannerLabel {{ font-size: {base_pt}pt; font-weight: 600; color: #f0f6fc; }}
            QLabel#summaryMono {{
                background-color: #12161c; color: #e6edf3; padding: 8px 10px;
                border: 1px solid #30363d; border-radius: 6px;
                font-family: monospace; font-size: {small_pt}pt;
            }}
            QFrame#bannerCard {{
                background-color: #192332; border: 1px solid #315a8a; border-radius: 10px;
            }}
            QFrame#actionCard, QFrame#dialogBtnBar {{
                background-color: #1c2129; border: 1px solid #353e4d; border-radius: 10px;
            }}
            QLabel#badgeOk {{
                background-color: #153726; color: #56d364; border: 1px solid #2ea043;
                border-radius: 5px; padding: 3px 9px; font-size: {small_pt}pt; font-weight: bold;
            }}
            QLabel#badgeWarn {{
                background-color: #3a2d13; color: #e3b341; border: 1px solid #9e6a03;
                border-radius: 5px; padding: 3px 9px; font-size: {small_pt}pt; font-weight: bold;
            }}
            QGroupBox {{
                background-color: #1c2028; border: 1px solid #343c4a; border-radius: 10px;
                margin-top: 12px; padding: 12px 10px 10px 10px;
                font-size: {grp_pt}pt; font-weight: bold; color: #f0f6fc;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin; subcontrol-position: top left;
                left: 12px; padding: 0 6px; color: #79c0ff;
            }}
            QComboBox, QSpinBox, QDoubleSpinBox {{
                background-color: #252b35; color: #f0f6fc; border: 1px solid #414a58;
                border-radius: 6px; padding: 5px 8px; min-height: 22px; font-size: {base_pt}pt;
            }}
            QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{
                background-color: #1a1e25; color: #768390; border: 1px solid #2d333b;
            }}
            QTableWidget, QListWidget {{
                background-color: #14181f; color: #e6edf3; border: 1px solid #343c4a;
                border-radius: 6px; gridline-color: #282f3a; font-size: {base_pt}pt;
            }}
            QHeaderView::section {{
                background-color: #222731; color: #c9d1d9; border: none;
                border-bottom: 1px solid #384150; border-right: 1px solid #2d3440;
                padding: 5px 6px; font-size: {small_pt}pt; font-weight: bold;
            }}
            QPushButton {{
                background-color: #2b323d; color: #f0f6fc; border: 1px solid #485263;
                border-radius: 6px; padding: 6px 12px; font-size: {base_pt}pt; font-weight: 600;
            }}
            QPushButton:hover:enabled {{ background-color: #363f4e; border-color: #637085; }}
            QPushButton:disabled {{ background-color: #1c2027; color: #6e7681; border: 1px solid #2d333d; }}
            QPushButton#primaryBtn {{
                background-color: #1f6feb; color: #ffffff; border: 1px solid #388bfd;
            }}
            QPushButton#primaryBtn:hover:enabled {{ background-color: #2a7aef; }}
            QPushButton#accentBtn {{
                background-color: #1b4b36; color: #7ee787; border: 1px solid #2ea043;
            }}
            QPushButton#accentBtn:hover:enabled {{ background-color: #235d43; }}
        """)
        self._reflow_responsive()


    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reflow_responsive()

    def _reflow_grid_buttons(self, grid: QGridLayout, buttons: list, cols: int):
        while grid.count():
            grid.takeAt(0)
        for c in range(max(4, cols)):
            grid.setColumnStretch(c, 0)
        for idx, btn in enumerate(buttons):
            r, c = divmod(idx, cols)
            grid.addWidget(btn, r, c)
        for c in range(cols):
            grid.setColumnStretch(c, 1)

    def _reflow_responsive(self):
        if not hasattr(self, "top_btn_grid"):
            return
        eff_w = self.width() / max(0.75, self.ui_scale)
        compact = eff_w < 600
        narrow = eff_w < 460
        state = (compact, narrow)
        if state == self._resp_state:
            return
        self._resp_state = state

        top_cols = 1 if narrow else (2 if compact else 4)
        dtd_cols = 1 if narrow else (2 if compact else 3)
        std_cols = 1 if narrow else (2 if compact else 4)
        bot_cols = 1 if compact else 3

        self._reflow_grid_buttons(self.top_btn_grid, self.top_buttons, top_cols)
        self._reflow_grid_buttons(self.dtd_btn_grid, self.dtd_buttons, dtd_cols)
        self._reflow_grid_buttons(self.std_btn_grid, self.std_buttons, std_cols)
        self._reflow_grid_buttons(self.bot_btn_grid, self.bot_buttons, bot_cols)

        align = Qt.AlignmentFlag.AlignCenter if narrow else (Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.title_lbl.setAlignment(align)
        self.path_label.setAlignment(align)

    def _collect_high_clock_dtds(self):
        high = []
        for off in DTD_OFFSETS:
            d = decode_dtd(self.edid_bytes[off:off+18], self.edid_bytes)
            if d["type"] == "dtd" and d["pclk_mhz"] > 655.35:
                high.append(d)
        self.high_clock_dtds = high
        return high

    def auto_fix_cru_on_load(self):
        self.dtd_dec_overrides = {}
        for off in DTD_OFFSETS:
            block = self.edid_bytes[off:off+18]
            d = decode_dtd(block, self.edid_bytes)
            if d["type"] == "dtd" and d["cru_field_bug"]:
                d["vactive"] *= 2
                d["vblank"] *= 2
                d["vfront"] = min(63, d["vfront"] * 2)
                d["vsync"] = min(63, d["vsync"] * 2)
                self.edid_bytes[off:off+18] = encode_dtd(d, block)
        sync_700mhz_and_displayid(self.edid_bytes, self._collect_high_clock_dtds(), True)

    def refresh_ui(self):
        muted = QColor("#8b949e")
        info = self.current_port_info
        if hasattr(self, "port_badge"):
            is_conn = info.get("status") == "connected"
            has_ov = bool(info.get("active_override"))
            badge_txt = f"✓ {info['port']} (EDID Active)" if has_ov else f"● {info['port']} ({info.get('status', 'ready')})"
            self.port_badge.setText(badge_txt)
            self.port_badge.setObjectName("badgeOk" if (is_conn or has_ov) else "badgeWarn")
            self.port_badge.style().unpolish(self.port_badge)
            self.port_badge.style().polish(self.port_badge)

        for idx, off in enumerate(DTD_OFFSETS):
            d = decode_dtd(self.edid_bytes[off:off+18], self.edid_bytes)
            ov = self.dtd_dec_overrides.get(idx)
            if d["type"] == "dtd" and ov and ov.get("hactive") == d["hactive"] and ov.get("vactive") == d["vactive"]:
                d.update(ov)
            slot_lbl = f"Slot {idx+1}"
            if d["type"] == "dtd":
                scan_ch = "i" if d["interlaced"] else "p"
                res_str = f"{d['hactive']} × {d['vactive']}{scan_ch}"
                rate_str = f"{d['vrefresh']:.3f} Hz"
                hscan_str = f"{d['hscan_khz']:.3f} kHz"
                clk_str = f"{d['pclk_mhz']:.2f} MHz"
                pol = f"{'+' if d.get('hsync_pos') else '-'}H/{'+' if d.get('vsync_pos') else '-'}V"
                preset = detect_timing_preset(d)
                sync_str = f"{preset} [{pol}]"
                is_empty = False
            elif d["type"] == "range":
                res_str = d.get("summary", "Monitor Range Limits")
                rate_str = hscan_str = clk_str = sync_str = "Range Limits"
                is_empty = True
            else:
                res_str, rate_str, hscan_str, clk_str, sync_str = "(Empty)", "-", "-", "-", "-"
                is_empty = True

            for c_idx, text in enumerate([slot_lbl, res_str, rate_str, hscan_str, clk_str, sync_str]):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if is_empty and c_idx > 0:
                    item.setForeground(muted)
                elif d.get("type") == "dtd" and d.get("interlaced") and c_idx > 0:
                    item.setForeground(QColor("#56d364"))
                self.table.setItem(idx, c_idx, item)

        self.std_list.clear()
        active_std = [s for s in self.std_slots if s is not None]
        if not active_std:
            empty_item = QListWidgetItem("No Standard Resolutions configured")
            empty_item.setForeground(muted)
            self.std_list.addItem(empty_item)
        else:
            for idx, s in enumerate(active_std):
                self.std_list.addItem(f"Slot {idx+1}:  {s['w']} × {s['h']} ({s['ar_name']}) @ {s['hz']} Hz")

    def new_blank_edid(self):
        self.edid_bytes = create_blank_crt_edid()
        self.std_slots = decode_std_timings(self.edid_bytes)
        self.high_clock_dtds = []
        self.dtd_dec_overrides = {}
        self.current_path = ""
        self.path_label.setText("Source: New Blank Profile")
        self.refresh_ui()

    def edit_selected_dtd(self):
        row = max(0, self.table.currentRow())
        off = DTD_OFFSETS[row]
        block = self.edid_bytes[off:off+18]
        d = decode_dtd(block, self.edid_bytes)
        ov = self.dtd_dec_overrides.get(row)
        if d["type"] == "dtd" and ov and ov.get("hactive") == d["hactive"] and ov.get("vactive") == d["vactive"]:
            d.update(ov)
        dlg = DTDEditorDialog(self, d)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            res = dlg.get_result()
            self.dtd_dec_overrides[row] = dict(res)
            self.edid_bytes[off:off+18] = encode_dtd(res, block)
            high = []
            for idx, slot_off in enumerate(DTD_OFFSETS):
                if idx == row:
                    if res["pclk_mhz"] > 655.35:
                        high.append(res)
                else:
                    other = decode_dtd(self.edid_bytes[slot_off:slot_off+18], self.edid_bytes)
                    if other["type"] == "dtd" and other["pclk_mhz"] > 655.35:
                        high.append(other)
            self.high_clock_dtds = high
            sync_700mhz_and_displayid(self.edid_bytes, self.high_clock_dtds, True)
            self.refresh_ui()

    def clear_selected_dtd(self):
        row = max(0, self.table.currentRow())
        off = DTD_OFFSETS[row]
        self.dtd_dec_overrides.pop(row, None)
        self.edid_bytes[off:off+18] = bytes([0, 0, 0, 0x10, 0] + [0]*13)
        sync_700mhz_and_displayid(self.edid_bytes, self._collect_high_clock_dtds(), True)
        self.refresh_ui()

    def clear_all_dtds(self):
        self.dtd_dec_overrides.clear()
        for off in DTD_OFFSETS:
            self.edid_bytes[off:off+18] = bytes([0, 0, 0, 0x10, 0] + [0]*13)
        sync_700mhz_and_displayid(self.edid_bytes, [], True)
        self.refresh_ui()

    def _maybe_offer_dtd_for_custom_std(self, res: dict):
        if not res.get("custom_h"):
            return
        w, h, hz = res["w"], res["h"], res["hz"]
        empty_slot = -1
        for idx, off in enumerate(DTD_OFFSETS):
            d = decode_dtd(self.edid_bytes[off:off+18], self.edid_bytes)
            if d["type"] == "empty":
                empty_slot = idx
                break
        if empty_slot >= 0:
            ans = QMessageBox.question(
                self,
                "Add Custom Vertical Resolution to Detailed Slot?",
                f"EDID 2-byte Standard Resolution slots only store 4 fixed aspect ratios (16:10, 4:3, 5:4, 16:9).\n\n"
                f"Would you also like to add exact {w} × {h} @ {hz} Hz (CVT Standard) to Detailed Resolution Slot {empty_slot + 1}?",
            )
            if ans == QMessageBox.StandardButton.Yes:
                dtd_res = calculate_timings("CVT Standard", w, h, float(hz), False)
                off = DTD_OFFSETS[empty_slot]
                self.dtd_dec_overrides[empty_slot] = dict(dtd_res)
                self.edid_bytes[off:off+18] = encode_dtd(dtd_res, self.edid_bytes[off:off+18])
                sync_700mhz_and_displayid(self.edid_bytes, self._collect_high_clock_dtds(), True)

    def add_std_res(self):
        active = [s for s in self.std_slots if s is not None]
        if len(active) >= 8:
            QMessageBox.warning(self, "Full", "All 8 Standard Resolution slots are full.")
            return
        dlg = StandardResDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            res = dlg.get_result()
            active.append(res)
            self.std_slots = active + [None] * (8 - len(active))
            encode_std_timings(self.edid_bytes, self.std_slots)
            self._maybe_offer_dtd_for_custom_std(res)
            update_checksum(self.edid_bytes)
            self.refresh_ui()

    def edit_std_res(self):
        row = self.std_list.currentRow()
        active = [s for s in self.std_slots if s is not None]
        if row < 0 or row >= len(active):
            return
        dlg = StandardResDialog(self, active[row])
        if dlg.exec() == QDialog.DialogCode.Accepted:
            res = dlg.get_result()
            active[row] = res
            self.std_slots = active + [None] * (8 - len(active))
            encode_std_timings(self.edid_bytes, self.std_slots)
            self._maybe_offer_dtd_for_custom_std(res)
            update_checksum(self.edid_bytes)
            self.refresh_ui()

    def del_std_res(self):
        row = self.std_list.currentRow()
        active = [s for s in self.std_slots if s is not None]
        if 0 <= row < len(active):
            active.pop(row)
            self.std_slots = active + [None] * (8 - len(active))
            encode_std_timings(self.edid_bytes, self.std_slots)
            update_checksum(self.edid_bytes)
            self.refresh_ui()

    def del_all_std_res(self):
        self.std_slots = [None] * 8
        encode_std_timings(self.edid_bytes, self.std_slots)
        update_checksum(self.edid_bytes)
        self.refresh_ui()

    def _populate_profile_combo(self):
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        self.profile_sources = []
        info = self.current_port_info
        port = info["port"]

        if os.path.exists(info["fw_path"]) and os.path.getsize(info["fw_path"]) >= 128:
            self.profile_combo.addItem(f"Installed Custom EDID ({port})")
            self.profile_sources.append(("file", info["fw_path"]))

        if info["edid_path"] and os.path.exists(info["edid_path"]):
            try:
                if len(open(info["edid_path"], "rb").read()) >= 128:
                    self.profile_combo.addItem(f"Current Monitor EDID ({port})")
                    self.profile_sources.append(("drm", info["edid_path"]))
            except Exception:
                pass

        self.profile_combo.addItem("Blank Template (Start Fresh)")
        self.profile_sources.append(("blank", ""))

        seen_paths = set()
        seen_names = set()
        for search_dir in (DOCS_PROFILES_DIR, os.path.expanduser("~/Documents"), LEGACY_PROFILES_DIR):
            if not os.path.isdir(search_dir):
                continue
            for p in sorted(glob.glob(os.path.join(search_dir, "*.bin"))):
                real_p = os.path.realpath(p)
                if real_p in seen_paths or not os.path.isfile(p) or os.path.getsize(p) < 128:
                    continue
                try:
                    with open(p, "rb") as f:
                        hdr = f.read(8)
                    if hdr != b"\x00\xff\xff\xff\xff\xff\xff\x00":
                        continue
                except Exception:
                    continue
                seen_paths.add(real_p)
                name = os.path.splitext(os.path.basename(p))[0]
                if name.lower() in seen_names:
                    continue
                seen_names.add(name.lower())
                self.profile_combo.addItem(f"Saved Profile: {name} (Documents/linux-cru)")
                self.profile_sources.append(("file", p))

        self.profile_combo.blockSignals(False)

    def on_port_changed(self, idx):
        if idx < 0:
            return
        data = self.port_combo.itemData(idx)
        if not isinstance(data, dict):
            return
        self.current_port_info = data
        self._populate_profile_combo()
        if self.profile_sources:
            self.profile_combo.setCurrentIndex(0)
            self.on_profile_selected(0)

    def on_profile_selected(self, idx):
        if idx < 0 or idx >= len(self.profile_sources):
            return
        kind, path = self.profile_sources[idx]
        port = self.current_port_info["port"]
        if kind in ("file", "drm") and os.path.exists(path):
            try:
                data = bytearray(open(path, "rb").read())
                if len(data) >= 128:
                    self.edid_bytes = data
                    self.auto_fix_cru_on_load()
                    self.std_slots = decode_std_timings(self.edid_bytes)
                    self.current_path = path
                    prefix = "Live DRM" if kind == "drm" else "Loaded"
                    self.path_label.setText(f"[{port}] {prefix}: {path}")
                    self.refresh_ui()
                    return
            except Exception:
                pass
        self.new_blank_edid()

    def save_named_profile(self):
        self._prepare_edid_for_save()
        os.makedirs(DOCS_PROFILES_DIR, exist_ok=True)
        port = self.current_port_info["port"]
        default_file = os.path.join(DOCS_PROFILES_DIR, f"{port}.bin")
        path, _ = QFileDialog.getSaveFileName(self, "Save Profile to Documents/linux-cru", default_file, "EDID Profile (*.bin)")
        if path:
            if not path.endswith(".bin"):
                path += ".bin"
            open(path, "wb").write(self.edid_bytes)
            # Also mirror into ~/Documents/linux-cru if saved elsewhere so it always appears in the app dropdown
            try:
                doc_copy = os.path.join(DOCS_PROFILES_DIR, os.path.basename(path))
                if os.path.realpath(path) != os.path.realpath(doc_copy):
                    open(doc_copy, "wb").write(self.edid_bytes)
            except Exception:
                pass
            self.current_path = path
            self.path_label.setText(f"[{port}] Saved Profile: {path}")
            self._populate_profile_combo()
            for i, (kind, src_p) in enumerate(self.profile_sources):
                if kind == "file" and os.path.basename(src_p) == os.path.basename(path):
                    self.profile_combo.blockSignals(True)
                    self.profile_combo.setCurrentIndex(i)
                    self.profile_combo.blockSignals(False)
                    break

    def open_bin(self):
        os.makedirs(DOCS_PROFILES_DIR, exist_ok=True)
        path, _ = QFileDialog.getOpenFileName(self, "Import EDID .bin", DOCS_PROFILES_DIR, "EDID (*.bin);;All (*)")
        if path:
            data = bytearray(open(path, "rb").read())
            if len(data) >= 128:
                self.edid_bytes = data
                self.auto_fix_cru_on_load()
                self.std_slots = decode_std_timings(self.edid_bytes)
                self.current_path = path
                # Also copy imported .bin into ~/Documents/linux-cru so it is selectable as a profile
                try:
                    if path.lower().endswith(".bin") and self.edid_bytes[:8] == b"\x00\xff\xff\xff\xff\xff\xff\x00":
                        doc_copy = os.path.join(DOCS_PROFILES_DIR, os.path.basename(path))
                        if not os.path.exists(doc_copy):
                            open(doc_copy, "wb").write(self.edid_bytes)
                        self._populate_profile_combo()
                except Exception:
                    pass
                self.path_label.setText(f"[{self.current_port_info['port']}] Imported: {path}")
                self.refresh_ui()

    def read_drm_edid(self):
        info = self.current_port_info
        p = info["edid_path"]
        if p and os.path.exists(p):
            try:
                data = bytearray(open(p, "rb").read())
                if len(data) >= 128:
                    self.edid_bytes = data
                    self.auto_fix_cru_on_load()
                    self.std_slots = decode_std_timings(self.edid_bytes)
                    self.current_path = p
                    self.path_label.setText(f"[{info['port']}] Pulled DRM: {p}")
                    self.refresh_ui()
                    return
            except Exception:
                pass
        QMessageBox.warning(
            self, "No Live EDID on Port",
            f"Port {info['port']} ({info['card']}) does not currently report a live EDID in DRM.\n"
            f"You can still build a profile for {info['port']} or import a .bin file."
        )

    def _prepare_edid_for_save(self):
        has_fd = any(self.edid_bytes[off:off+4] == b'\x00\x00\x00\xfd' for off in DTD_OFFSETS)
        if not has_fd:
            for off in reversed(DTD_OFFSETS):
                if self.edid_bytes[off] == 0 and self.edid_bytes[off+1] == 0:
                    self.edid_bytes[off:off+18] = bytes([
                        0x00, 0x00, 0x00, 0xFD, 0x00,
                        30, 200, 30, 200, 70, 0x00,
                        0x0A, 0x20, 0x20, 0x20, 0x20, 0x20, 0x20
                    ])
                    break
        sync_700mhz_and_displayid(self.edid_bytes, self._collect_high_clock_dtds(), True)

    def save_bin_as(self):
        self._prepare_edid_for_save()
        os.makedirs(DOCS_PROFILES_DIR, exist_ok=True)
        port = self.current_port_info["port"].lower()
        default_export = os.path.join(DOCS_PROFILES_DIR, f"cru-{port}.bin")
        path, _ = QFileDialog.getSaveFileName(self, "Export .bin", default_export, "EDID (*.bin)")
        if path:
            if not path.endswith(".bin"):
                path += ".bin"
            open(path, "wb").write(self.edid_bytes)
            try:
                doc_copy = os.path.join(DOCS_PROFILES_DIR, os.path.basename(path))
                if os.path.realpath(path) != os.path.realpath(doc_copy):
                    open(doc_copy, "wb").write(self.edid_bytes)
            except Exception:
                pass
            self.current_path = path
            self.path_label.setText(f"[{self.current_port_info['port']}] Exported: {path}")
            self._populate_profile_combo()

    def _build_live_reload_shell_cmd(self, tmp_path):
        info = self.current_port_info
        port = info["port"]
        fw_path = info["fw_path"]
        rel_fw = info["rel_fw"]
        fw_map = get_active_fw_map()
        fw_map[port] = rel_fw
        new_param = ",".join(f"{k}:{v}" for k, v in fw_map.items())

        status_path = os.path.join(info["sysfs_dir"], "status") if info["sysfs_dir"] else ""
        reprobe_state = "on" if ("VGA" in port or "DVI-I" in port) else "detect"
        card_num = info["card"].replace("card", "") if info["card"].startswith("card") else ""
        dbg_override = f"/sys/kernel/debug/dri/{card_num}/{port}/edid_override" if card_num else ""

        cmds = [
            f"mkdir -p /usr/lib/firmware/edid && install -m 0644 {tmp_path} {fw_path}",
            f"echo -n '{new_param}' > /sys/module/drm/parameters/edid_firmware",
        ]
        if dbg_override:
            cmds.append(f"([ -w {dbg_override} ] && cat {tmp_path} > {dbg_override} || true)")
        if status_path and os.path.exists(status_path):
            cmds.append(f"(echo off > {status_path} && sleep 0.15 && echo {reprobe_state} > {status_path})")
        cmds.append("(udevadm trigger --action=change --subsystem-match=drm || true)")
        return " && ".join(cmds)

    def apply_live_no_reboot(self):
        self._prepare_edid_for_save()
        info = self.current_port_info
        port = info["port"]
        tmp_path = "/tmp/linux_cru_edid.bin"
        open(tmp_path, "wb").write(self.edid_bytes)
        cmd = self._build_live_reload_shell_cmd(tmp_path)
        if subprocess.call(["pkexec", "bash", "-c", cmd]) == 0:
            self.current_path = info["fw_path"]
            self.path_label.setText(f"[{port}] Live Applied: {info['fw_path']}")
            self._populate_profile_combo()
            QMessageBox.information(
                self, "Live EDID Reloaded",
                f"Applied EDID to {port} ({info['fw_path']}) and triggered DRM hotplug reprobe without rebooting."
            )

    def install_to_firmware(self):
        self._prepare_edid_for_save()
        info = self.current_port_info
        port = info["port"]
        fw_path = info["fw_path"]
        rel_fw = info["rel_fw"]
        tmp_path = "/tmp/linux_cru_edid.bin"
        open(tmp_path, "wb").write(self.edid_bytes)
        live_cmd = self._build_live_reload_shell_cmd(tmp_path)

        helper_py = "/tmp/linux_cru_boot_cfg.py"
        with open(helper_py, "w") as hf:
            hf.write(
                "import os, re, sys\n"
                "port, rel_fw, fw_path = sys.argv[1], sys.argv[2], sys.argv[3]\n"
                "mk = '/etc/mkinitcpio.conf'\n"
                "if os.path.exists(mk):\n"
                "    txt = open(mk).read()\n"
                "    if fw_path not in txt:\n"
                "        txt = re.sub(r'^FILES=\\(', f'FILES=({fw_path} ', txt, flags=re.M)\n"
                "        open(mk, 'w').write(txt)\n"
                "if os.path.isdir('/etc/dracut.conf.d'):\n"
                "    dc = '/etc/dracut.conf.d/99-crt-edid.conf'\n"
                "    cur = open(dc).read() if os.path.exists(dc) else ''\n"
                "    if fw_path not in cur:\n"
                "        open(dc, 'a').write(f'install_items+=\" {fw_path} \"\\n')\n"
                "def update_boot_file(path, key):\n"
                "    if not os.path.exists(path): return\n"
                "    lines = open(path).readlines()\n"
                "    out = []\n"
                "    for line in lines:\n"
                "        if line.lstrip().startswith(key):\n"
                "            fw_map = {}\n"
                "            for m in re.finditer(r'\\bdrm\\.edid_firmware=([^\\s\"\\']+)', line):\n"
                "                for item in m.group(1).split(','):\n"
                "                    if ':' in item:\n"
                "                        k, v = item.split(':', 1)\n"
                "                        fw_map[k] = v\n"
                "            fw_map[port] = rel_fw\n"
                "            fw_arg = 'drm.edid_firmware=' + ','.join(f'{k}:{v}' for k, v in fw_map.items())\n"
                "            vid_arg = f'video={port}:e'\n"
                "            line = re.sub(r'\\bdrm\\.edid_firmware=[^\\s\"\\']+', '', line)\n"
                "            line = re.sub(r'\\bvideo=' + re.escape(port) + r':[^\\s\"\\']+', '', line)\n"
                "            line = re.sub(r'  +', ' ', line)\n"
                "            q = line.rfind('\"')\n"
                "            if q != -1:\n"
                "                line = f'{line[:q].rstrip()} {fw_arg} {vid_arg}\"\\n'\n"
                "        out.append(line)\n"
                "    open(path, 'w').writelines(out)\n"
                "update_boot_file('/etc/default/limine', 'KERNEL_CMDLINE')\n"
                "update_boot_file('/etc/default/grub', 'GRUB_CMDLINE_LINUX_DEFAULT')\n"
            )

        cmd = (
            f"{live_cmd} && "
            f"python3 {helper_py} '{port}' '{rel_fw}' '{fw_path}' && "
            f"([ -f /etc/default/grub ] && (command -v update-grub >/dev/null && update-grub || "
            f"command -v grub-mkconfig >/dev/null && grub-mkconfig -o /boot/grub/grub.cfg) || true) && "
            f"(command -v limine-mkinitcpio >/dev/null && limine-mkinitcpio || "
            f"command -v mkinitcpio >/dev/null && mkinitcpio -P || "
            f"command -v dracut >/dev/null && dracut --regenerate-all --force || "
            f"update-initramfs -u -k all)"
        )
        if subprocess.call(["pkexec", "bash", "-c", cmd]) == 0:
            self.current_path = fw_path
            self.path_label.setText(f"[{port}] Installed: {fw_path}")
            self._populate_profile_combo()
            QMessageBox.information(
                self, "Success",
                f"Saved {fw_path}, updated bootloader CMDLINE & initramfs for {port}, and applied live."
            )


if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = LinuxCRUWindow()
    win.show()
    sys.exit(app.exec())
APP_EOF

mkdir -p "$HOME/.local/bin"
install -m 0755 "$TMP_APP" "$HOME/.local/bin/linux-cru"
if [ -d "$HOME/bin" ]; then
    install -m 0755 "$TMP_APP" "$HOME/bin/linux-cru"
fi
sudo install -m 0755 "$TMP_APP" /usr/local/bin/linux-cru || true

echo "==> [3/3] Creating Desktop Launcher Shortcut..."
mkdir -p "$HOME/.local/share/applications"
cat << DESKTOP_EOF > "$HOME/.local/share/applications/linux-cru.desktop"
[Desktop Entry]
Name=Linux CRU
Comment=ToastyX-Style Custom Resolution Utility for Linux
Exec=$HOME/.local/bin/linux-cru
Icon=video-display
Terminal=false
Type=Application
Categories=System;Settings;HardwareSettings;
DESKTOP_EOF
chmod +x "$HOME/.local/share/applications/linux-cru.desktop"
if [ -d "$HOME/Desktop" ]; then
    install -m 0755 "$HOME/.local/share/applications/linux-cru.desktop" "$HOME/Desktop/Linux CRU.desktop"
fi
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$HOME/.local/share/applications" >/dev/null 2>&1 || true
fi

echo "==> Linux CRU installed! Run 'linux-cru' or launch it from your application menu."
