#!/usr/bin/env bash
# Standalone Installer for Linux CRU (Standardized ToastyX-Style Edition)
set -euo pipefail
umask 022

TMP_APP="$(mktemp)"
trap 'rm -f "$TMP_APP"' EXIT

echo "==> [1/3] Installing Python 3 & PyQt6..."
if command -v pacman >/dev/null 2>&1; then
    sudo pacman -S --needed --noconfirm python python-pyqt6
elif command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update && sudo apt-get install -y python3 python3-pyqt6
elif command -v dnf >/dev/null 2>&1; then
    sudo dnf install -y python3 python3-pyqt6
elif command -v zypper >/dev/null 2>&1; then
    sudo zypper install -y python3 python-PyQt6
fi

echo "==> [2/3] Installing /usr/local/bin/linux-cru..."
cat << 'APP_EOF' > "$TMP_APP"
#!/usr/bin/env python3
import sys
import os
import glob
import math
import struct
import subprocess
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QTableWidget, QTableWidgetItem, QPushButton, QLabel,
    QFileDialog, QDialog, QFormLayout, QSpinBox, QDoubleSpinBox,
    QCheckBox, QComboBox, QMessageBox, QGroupBox, QHeaderView,
    QListWidget, QListWidgetItem, QAbstractItemView
)
from PyQt6.QtGui import QColor, QFont

DEFAULT_EDID_PATH = "/usr/lib/firmware/edid/crufile.bin"
DTD_OFFSETS = (54, 72, 90, 108)
ASPECT_MAP = {0: ("16:10", 10, 16), 1: ("4:3", 3, 4), 2: ("5:4", 4, 5), 3: ("16:9", 9, 16)}

TIMING_PRESETS = [
    "Automatic CRT",
    "Automatic PC",
    "Automatic HDTV",
    "Native PC",
    "Native HDTV",
    "CVT Standard",
    "CVT-RB",
    "CVT-RB2",
    "GTF Standard",
    "Manual",
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


def _cvt_vsync_lines(hactive, vactive):
    if vactive <= 0:
        return 4
    r = hactive / float(vactive)
    for target, lines in ((4/3, 4), (16/9, 5), (16/10, 6), (5/4, 7), (15/9, 7)):
        if abs(r - target) < 0.03:
            return lines
    return 4


def calculate_timings(preset_name, hactive, vactive, refresh_hz, interlaced):
    hactive, vactive = max(64, int(hactive)), max(64, int(vactive))
    if interlaced and vactive % 2 != 0:
        vactive += 1
    refresh_hz = 60.0 if "Native" in preset_name else max(20.0, float(refresh_hz))
    frame_rate = (refresh_hz / 2.0) if interlaced else refresh_hz
    v_scale = 2 if interlaced else 1
    v_lines_field = (vactive / 2.0) if interlaced else float(vactive)

    if preset_name == "CVT-RB2":
        hfront, hsync, hblank = 8, 32, 80
        hsync_pos, vsync_pos = True, False
        vbi_f = int(math.ceil((refresh_hz * v_lines_field * 460e-6) / max(0.05, 1.0 - refresh_hz * 460e-6)))
        vfront, vsync = 1 * v_scale, 8 * v_scale
        vblank = max(15 * v_scale, vbi_f * v_scale)

    elif preset_name in ("CVT-RB", "Automatic PC", "Native PC"):
        hfront, hsync, hblank = 48, 32, 160
        hsync_pos, vsync_pos = True, False
        vsync_f = _cvt_vsync_lines(hactive, vactive) if preset_name == "CVT-RB" else 4
        vbi_f = int(math.ceil((refresh_hz * v_lines_field * 460e-6) / max(0.05, 1.0 - refresh_hz * 460e-6)))
        vfront, vsync = 3 * v_scale, vsync_f * v_scale
        vblank = max((3 + vsync_f + 6) * v_scale, vbi_f * v_scale)

    elif preset_name in ("Automatic HDTV", "Native HDTV"):
        hsync_pos, vsync_pos = True, True
        if hactive == 1920 and vactive == 1080:
            hfront, hsync, hblank = 88, 44, 280
            vfront, vsync, vblank = (4, 10, 44) if interlaced else (4, 5, 45)
        elif hactive == 1280 and vactive == 720 and not interlaced:
            hfront, hsync, hblank, vfront, vsync, vblank = 110, 40, 370, 5, 5, 30
        elif hactive == 3840 and vactive == 2160 and not interlaced:
            hfront, hsync, hblank, vfront, vsync, vblank = 176, 88, 560, 8, 10, 90
        elif hactive in (640, 720) and vactive == 480:
            hsync_pos, vsync_pos = False, False
            hfront, hsync, hblank = 16, (96 if hactive == 640 else 62), (160 if hactive == 640 else 138)
            vfront, vsync, vblank = (8, 6, 44) if interlaced else (10, 2, 45)
        else:
            vfront, vsync = 4 * v_scale, 5 * v_scale
            vblank = (45 if vactive >= 1080 else 30) * v_scale
            hfront = max(16, int(round(hactive * 0.045 / 8.0)) * 8)
            hsync = max(32, int(round(hactive * 0.023 / 8.0)) * 8)
            hblank = max(hfront + hsync + 48, int(round(hactive * 0.145 / 8.0)) * 8)

    elif preset_name in ("GTF Standard", "CVT Standard"):
        hsync_pos, vsync_pos = False, True
        is_cvt = (preset_name == "CVT Standard")
        vfront_f = 3 if is_cvt else 1
        vsync_f = _cvt_vsync_lines(hactive, vactive) if is_cvt else 3
        h_per = ((1.0 / refresh_hz) - 550e-6) / max(1.0, v_lines_field + vfront_f + (0.5 if interlaced else 0.0)) * 1e6
        v_sync_bp = (max(vsync_f + 6, int(math.floor(550.0 / max(1.0, h_per))) + 1) if is_cvt
                     else max(7, int(round(550.0 / max(1.0, h_per)))))
        vfront, vsync, vblank = vfront_f * v_scale, vsync_f * v_scale, (vfront_f + v_sync_bp) * v_scale
        duty = max(20.0, 30.0 - (300.0 * h_per / 1000.0))
        rnd_fn = math.floor if is_cvt else round
        hblank = max(32, int(rnd_fn(hactive * duty / (100.0 - duty) / 16.0)) * 16)
        htotal = hactive + hblank
        hsync = max(8, int(rnd_fn(htotal * 0.08 / 8.0)) * 8)
        hfront = max(8, (hblank // 2) - hsync)

    else:
        hsync_pos, vsync_pos = False, True
        if interlaced:
            vfront, vsync = 6, 8
            vblank = max(vfront + vsync + 20, int(round(vactive * 0.1015)))
        else:
            vfront, vsync = 3, 4
            vblank = max(vfront + vsync + 14, int(round(vactive * 0.05)))
        hblank = max(32, int(round(hactive * 0.35 / 16.0)) * 16)
        htotal = hactive + hblank
        hsync = max(8, int(round(htotal * 0.08 / 8.0)) * 8)
        hfront = max(8, (hblank // 2) - hsync)

    if interlaced and vblank % 2 != 0:
        vblank += 1
    htotal, vtotal = hactive + hblank, vactive + vblank
    pclk_mhz = round((frame_rate * htotal * vtotal) / 1_000_000.0, 2)
    return {
        "type": "dtd", "pclk_mhz": pclk_mhz,
        "hactive": hactive, "hblank": hblank, "hfront": hfront, "hsync": hsync,
        "vactive": vactive, "vblank": vblank, "vfront": vfront, "vsync": vsync,
        "interlaced": interlaced, "hsync_pos": hsync_pos, "vsync_pos": vsync_pos,
        "vrefresh": refresh_hz, "hscan_khz": (pclk_mhz * 1000.0) / htotal if htotal else 0.0,
    }


def detect_timing_preset(d):
    if d.get("type") != "dtd":
        return "Automatic CRT"
    hz = round(d.get("vrefresh", 60.0), 2)
    for p in ("Automatic CRT", "Automatic PC", "Automatic HDTV", "CVT Standard", "CVT-RB", "CVT-RB2", "GTF Standard"):
        c = calculate_timings(p, d["hactive"], d["vactive"], hz, d["interlaced"])
        if all(c[k] == d[k] for k in ("hblank", "hfront", "hsync", "vblank", "vfront", "vsync", "hsync_pos", "vsync_pos")):
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

    return {
        "type": "dtd", "pclk_mhz": pclk_mhz,
        "hactive": hactive, "hblank": hblank, "hfront": hfront, "hsync": hsync,
        "vactive": vactive, "vblank": vblank, "vfront": vfront, "vsync": vsync,
        "interlaced": interlaced, "hsync_pos": hsync_pos, "vsync_pos": vsync_pos,
        "vrefresh": vrefresh, "hscan_khz": hscan_khz,
        "cru_field_bug": interlaced and (vactive <= hactive * 0.45)
    }


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
        self.setMinimumWidth(340)
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.mode_combo = QComboBox()
        for label, _, _ in STD_PRESETS:
            self.mode_combo.addItem(label)
        self.mode_combo.addItem("Custom (Multiple of 8)")
        form.addRow("Resolution:", self.mode_combo)

        self.width_sb = QSpinBox()
        self.width_sb.setRange(256, 2288)
        self.width_sb.setSingleStep(8)
        self.width_sb.setValue(initial["w"] if initial else 1600)
        form.addRow("Width (px):", self.width_sb)

        self.ar_combo = QComboBox()
        self.ar_combo.addItems(["16:10", "4:3", "5:4", "16:9"])
        self.ar_combo.setCurrentIndex(initial["ar_idx"] if initial else 1)
        form.addRow("Aspect Ratio:", self.ar_combo)

        self.hz_sb = QSpinBox()
        self.hz_sb.setRange(60, 123)
        self.hz_sb.setSuffix(" Hz")
        self.hz_sb.setValue(initial["hz"] if initial else 85)
        form.addRow("Refresh Rate (60-123 Hz):", self.hz_sb)

        layout.addLayout(form)

        btns = QHBoxLayout()
        ok_btn = QPushButton("OK")
        ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btns.addStretch()
        btns.addWidget(cancel_btn)
        btns.addWidget(ok_btn)
        layout.addLayout(btns)

        self.mode_combo.currentIndexChanged.connect(self.on_preset_changed)
        if initial:
            self.mode_combo.setCurrentIndex(len(STD_PRESETS))
        else:
            self.on_preset_changed()

    def on_preset_changed(self):
        idx = self.mode_combo.currentIndex()
        is_custom = (idx == len(STD_PRESETS))
        self.width_sb.setEnabled(is_custom)
        self.ar_combo.setEnabled(is_custom)
        if not is_custom:
            _, w, ar_idx = STD_PRESETS[idx]
            self.width_sb.setValue(w)
            self.ar_combo.setCurrentIndex(ar_idx)

    def get_result(self):
        w = (self.width_sb.value() // 8) * 8
        ar_idx = self.ar_combo.currentIndex()
        ar_name, num, den = ASPECT_MAP[ar_idx]
        h = (w * num) // den
        return {"w": w, "h": h, "hz": self.hz_sb.value(), "ar_idx": ar_idx, "ar_name": ar_name}


class DTDEditorDialog(QDialog):
    def __init__(self, parent, initial_data):
        super().__init__(parent)
        self.setWindowTitle("Detailed Resolution")
        self.setMinimumWidth(400)
        self._updating = False

        if initial_data.get("type") != "dtd":
            initial_data = calculate_timings("Automatic CRT", 1600, 1200, 85.0, False)
            initial_preset = "Automatic CRT"
        else:
            initial_preset = detect_timing_preset(initial_data)

        layout = QVBoxLayout(self)
        top_group = QGroupBox("Timing & Target")
        top_grid = QGridLayout(top_group)

        self.preset_combo = QComboBox()
        self.preset_combo.addItems(TIMING_PRESETS)
        self.preset_combo.setCurrentText(initial_preset)
        top_grid.addWidget(QLabel("Timing:"), 0, 0)
        top_grid.addWidget(self.preset_combo, 0, 1, 1, 2)

        self.refresh_sb = QDoubleSpinBox()
        self.refresh_sb.setRange(20.0, 500.0)
        self.refresh_sb.setDecimals(2)
        self.refresh_sb.setSingleStep(1.0)
        self.refresh_sb.setSuffix(" Hz")
        self.refresh_sb.setValue(float(initial_data.get("vrefresh", 85.0)))
        self._saved_refresh_hz = self.refresh_sb.value()
        self._was_native = ("Native" in initial_preset)
        top_grid.addWidget(QLabel("Refresh Rate:"), 1, 0)
        top_grid.addWidget(self.refresh_sb, 1, 1)

        self.interlaced_cb = QCheckBox("Interlaced")
        self.interlaced_cb.setChecked(bool(initial_data.get("interlaced", False)))
        top_grid.addWidget(self.interlaced_cb, 1, 2)
        layout.addWidget(top_group)

        param_group = QGroupBox("Parameters")
        pgrid = QGridLayout(param_group)
        hdr_font = QFont()
        hdr_font.setBold(True)
        h_hdr, v_hdr = QLabel("Horizontal (px)"), QLabel("Vertical (lines)")
        h_hdr.setFont(hdr_font)
        v_hdr.setFont(hdr_font)
        pgrid.addWidget(h_hdr, 0, 1)
        pgrid.addWidget(v_hdr, 0, 2)

        def make_sb(lo, hi, val, step=1, sfx=""):
            sb = QSpinBox()
            sb.setRange(lo, hi)
            sb.setSingleStep(step)
            if sfx:
                sb.setSuffix(sfx)
            sb.setValue(max(lo, min(hi, int(val))))
            return sb

        hact, hblk, hfr, hsy = initial_data["hactive"], initial_data["hblank"], initial_data["hfront"], initial_data["hsync"]
        vact, vblk, vfr, vsy = initial_data["vactive"], initial_data["vblank"], min(63, initial_data["vfront"]), min(63, initial_data["vsync"])
        hbck, vbck = max(1, hblk - hfr - hsy), max(1, vblk - vfr - vsy)

        self.hactive_sb = make_sb(64, 4095, hact, 8)
        self.vactive_sb = make_sb(64, 4095, vact, 2)
        self.hfront_sb = make_sb(1, 1023, hfr, 8)
        self.vfront_sb = make_sb(1, 63, vfr, 1)
        self.hsync_sb = make_sb(1, 1023, hsy, 8)
        self.vsync_sb = make_sb(1, 63, vsy, 1)
        self.hback_sb = make_sb(1, 4095, hbck, 8)
        self.vback_sb = make_sb(1, 4095, vbck, 1)
        self.hblank_sb = make_sb(2, 4095, hblk, 8)
        self.vblank_sb = make_sb(2, 4095, vblk, 2)
        self.htotal_sb = make_sb(66, 8190, hact + hblk, 8)
        self.vtotal_sb = make_sb(66, 8190, vact + vblk, 2)

        for r_idx, (lbl, hw, vw) in enumerate([
            ("Active:", self.hactive_sb, self.vactive_sb),
            ("Front Porch:", self.hfront_sb, self.vfront_sb),
            ("Sync Width:", self.hsync_sb, self.vsync_sb),
            ("Back Porch:", self.hback_sb, self.vback_sb),
            ("Blanking:", self.hblank_sb, self.vblank_sb),
            ("Total:", self.htotal_sb, self.vtotal_sb),
        ], start=1):
            pgrid.addWidget(QLabel(lbl), r_idx, 0)
            pgrid.addWidget(hw, r_idx, 1)
            pgrid.addWidget(vw, r_idx, 2)

        self.hsync_pos_cb = QCheckBox("+HSync")
        self.hsync_pos_cb.setChecked(bool(initial_data.get("hsync_pos", False)))
        self.vsync_pos_cb = QCheckBox("+VSync")
        self.vsync_pos_cb.setChecked(bool(initial_data.get("vsync_pos", True)))
        pgrid.addWidget(QLabel("Polarity:"), 7, 0)
        pgrid.addWidget(self.hsync_pos_cb, 7, 1)
        pgrid.addWidget(self.vsync_pos_cb, 7, 2)

        self.pclk_sb = QDoubleSpinBox()
        self.pclk_sb.setRange(1.0, 2000.00)
        self.pclk_sb.setDecimals(2)
        self.pclk_sb.setSingleStep(0.25)
        self.pclk_sb.setSuffix(" MHz")
        self.pclk_sb.setValue(float(initial_data["pclk_mhz"]))
        pgrid.addWidget(QLabel("Pixel Clock:"), 8, 0)
        pgrid.addWidget(self.pclk_sb, 8, 1, 1, 2)
        layout.addWidget(param_group)

        calc_group = QGroupBox("Summary")
        calc_layout = QVBoxLayout(calc_group)
        self.stats_label = QLabel()
        self.stats_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.stats_label.setStyleSheet(
            "QLabel { background-color: #161b22; color: #e6edf3; padding: 8px 10px; "
            "border: 1px solid #30363d; border-radius: 5px; font-family: monospace; font-size: 12px; }"
        )
        calc_layout.addWidget(self.stats_label)
        layout.addWidget(calc_group)

        btn_layout = QHBoxLayout()
        self.ok_btn = QPushButton("OK")
        self.ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addStretch()
        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(self.ok_btn)
        layout.addLayout(btn_layout)

        self.preset_combo.currentIndexChanged.connect(self.on_mode_changed)
        for w in (self.hactive_sb, self.vactive_sb, self.refresh_sb):
            w.valueChanged.connect(self.on_active_or_target_changed)
        self.interlaced_cb.toggled.connect(self.on_active_or_target_changed)
        for sb in (self.hfront_sb, self.hsync_sb, self.hback_sb):
            sb.valueChanged.connect(self.on_h_porch_changed)
        self.hblank_sb.valueChanged.connect(self.on_h_blank_changed)
        self.htotal_sb.valueChanged.connect(self.on_h_total_changed)
        for sb in (self.vfront_sb, self.vsync_sb, self.vback_sb):
            sb.valueChanged.connect(self.on_v_porch_changed)
        self.vblank_sb.valueChanged.connect(self.on_v_blank_changed)
        self.vtotal_sb.valueChanged.connect(self.on_v_total_changed)
        self.pclk_sb.valueChanged.connect(self.on_pclk_changed)
        self.hsync_pos_cb.toggled.connect(self.update_live_stats)
        self.vsync_pos_cb.toggled.connect(self.update_live_stats)

        self.on_mode_changed()

    def _sync_pclk_from_target_refresh(self):
        htotal = self.hactive_sb.value() + self.hblank_sb.value()
        vtotal = self.vactive_sb.value() + self.vblank_sb.value()
        frame_rate = (self.refresh_sb.value() / 2.0) if self.interlaced_cb.isChecked() else self.refresh_sb.value()
        pclk_mhz = round((frame_rate * htotal * vtotal) / 1_000_000.0, 2)
        self.pclk_sb.setValue(max(1.0, min(2000.0, pclk_mhz)))

    def on_mode_changed(self):
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

        for sb in (self.hfront_sb, self.hsync_sb, self.hback_sb, self.hblank_sb, self.htotal_sb,
                   self.vfront_sb, self.vsync_sb, self.vback_sb, self.vblank_sb, self.vtotal_sb,
                   self.pclk_sb, self.hsync_pos_cb, self.vsync_pos_cb):
            sb.setEnabled(is_manual)
        self.refresh_sb.setEnabled(not is_native)
        if not is_manual:
            self.on_active_or_target_changed()
        else:
            self.update_live_stats()

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
            if "Native" in preset:
                self.refresh_sb.setValue(60.0)
            res = calculate_timings(
                preset,
                self.hactive_sb.value(), self.vactive_sb.value(),
                self.refresh_sb.value(), self.interlaced_cb.isChecked()
            )
            hfr, hsy, hblk = res["hfront"], res["hsync"], res["hblank"]
            vfr, vsy, vblk = min(63, res["vfront"]), min(63, res["vsync"]), res["vblank"]
            self.hfront_sb.setValue(hfr)
            self.hsync_sb.setValue(hsy)
            self.hback_sb.setValue(max(1, hblk - hfr - hsy))
            self.hblank_sb.setValue(hblk)
            self.htotal_sb.setValue(self.hactive_sb.value() + hblk)
            self.vfront_sb.setValue(vfr)
            self.vsync_sb.setValue(vsy)
            self.vback_sb.setValue(max(1, vblk - vfr - vsy))
            self.vblank_sb.setValue(vblk)
            self.vtotal_sb.setValue(self.vactive_sb.value() + vblk)
            self.pclk_sb.setValue(res["pclk_mhz"])
            self.hsync_pos_cb.setChecked(res["hsync_pos"])
            self.vsync_pos_cb.setChecked(res["vsync_pos"])
        else:
            if self.interlaced_cb.isChecked() and self.vblank_sb.value() % 2 != 0:
                self.vblank_sb.setValue(self.vblank_sb.value() + 1)
                self.vback_sb.setValue(max(1, self.vblank_sb.value() - self.vfront_sb.value() - self.vsync_sb.value()))
            self.htotal_sb.setValue(self.hactive_sb.value() + self.hblank_sb.value())
            self.vtotal_sb.setValue(self.vactive_sb.value() + self.vblank_sb.value())
            self._sync_pclk_from_target_refresh()
        self._updating = False
        self.update_live_stats()

    def on_h_porch_changed(self):
        if self._updating:
            return
        self._updating = True
        hblk = self.hfront_sb.value() + self.hsync_sb.value() + self.hback_sb.value()
        self.hblank_sb.setValue(hblk)
        self.htotal_sb.setValue(self.hactive_sb.value() + hblk)
        self._sync_pclk_from_target_refresh()
        self._updating = False
        self.update_live_stats()

    def on_h_blank_changed(self):
        if self._updating:
            return
        self._updating = True
        min_blk = self.hfront_sb.value() + self.hsync_sb.value() + 1
        if self.hblank_sb.value() < min_blk:
            self.hblank_sb.setValue(min_blk)
        self.hback_sb.setValue(self.hblank_sb.value() - self.hfront_sb.value() - self.hsync_sb.value())
        self.htotal_sb.setValue(self.hactive_sb.value() + self.hblank_sb.value())
        self._sync_pclk_from_target_refresh()
        self._updating = False
        self.update_live_stats()

    def on_h_total_changed(self):
        if self._updating:
            return
        self._updating = True
        min_tot = self.hactive_sb.value() + self.hfront_sb.value() + self.hsync_sb.value() + 1
        if self.htotal_sb.value() < min_tot:
            self.htotal_sb.setValue(min_tot)
        hblk = self.htotal_sb.value() - self.hactive_sb.value()
        self.hblank_sb.setValue(hblk)
        self.hback_sb.setValue(hblk - self.hfront_sb.value() - self.hsync_sb.value())
        self._sync_pclk_from_target_refresh()
        self._updating = False
        self.update_live_stats()

    def on_v_porch_changed(self):
        if self._updating:
            return
        self._updating = True
        vblk = self.vfront_sb.value() + self.vsync_sb.value() + self.vback_sb.value()
        if self.interlaced_cb.isChecked() and vblk % 2 != 0:
            vblk += 1
            self.vback_sb.setValue(vblk - self.vfront_sb.value() - self.vsync_sb.value())
        self.vblank_sb.setValue(vblk)
        self.vtotal_sb.setValue(self.vactive_sb.value() + vblk)
        self._sync_pclk_from_target_refresh()
        self._updating = False
        self.update_live_stats()

    def on_v_blank_changed(self):
        if self._updating:
            return
        self._updating = True
        min_blk = self.vfront_sb.value() + self.vsync_sb.value() + 1
        if self.vblank_sb.value() < min_blk:
            self.vblank_sb.setValue(min_blk)
        if self.interlaced_cb.isChecked() and self.vblank_sb.value() % 2 != 0:
            self.vblank_sb.setValue(self.vblank_sb.value() + 1)
        self.vback_sb.setValue(self.vblank_sb.value() - self.vfront_sb.value() - self.vsync_sb.value())
        self.vtotal_sb.setValue(self.vactive_sb.value() + self.vblank_sb.value())
        self._sync_pclk_from_target_refresh()
        self._updating = False
        self.update_live_stats()

    def on_v_total_changed(self):
        if self._updating:
            return
        self._updating = True
        min_tot = self.vactive_sb.value() + self.vfront_sb.value() + self.vsync_sb.value() + 1
        if self.vtotal_sb.value() < min_tot:
            self.vtotal_sb.setValue(min_tot)
        vblk = self.vtotal_sb.value() - self.vactive_sb.value()
        if self.interlaced_cb.isChecked() and vblk % 2 != 0:
            vblk += 1
            self.vtotal_sb.setValue(self.vactive_sb.value() + vblk)
        self.vblank_sb.setValue(vblk)
        self.vback_sb.setValue(vblk - self.vfront_sb.value() - self.vsync_sb.value())
        self._sync_pclk_from_target_refresh()
        self._updating = False
        self.update_live_stats()

    def on_pclk_changed(self):
        if self._updating:
            return
        self._updating = True
        htotal = self.hactive_sb.value() + self.hblank_sb.value()
        vtotal = self.vactive_sb.value() + self.vblank_sb.value()
        pclk = self.pclk_sb.value()
        mult = 2.0 if self.interlaced_cb.isChecked() else 1.0
        actual_hz = (pclk * 1_000_000.0 * mult) / (htotal * vtotal) if (htotal and vtotal) else 60.0
        self.refresh_sb.setValue(round(actual_hz, 2))
        self._updating = False
        self.update_live_stats()

    def update_live_stats(self):
        if self._updating:
            return
        hact, hfr, hsy, hblk = self.hactive_sb.value(), self.hfront_sb.value(), self.hsync_sb.value(), self.hblank_sb.value()
        vact, vfr, vsy, vblk = self.vactive_sb.value(), self.vfront_sb.value(), self.vsync_sb.value(), self.vblank_sb.value()
        hbck, vbck = hblk - hfr - hsy, vblk - vfr - vsy
        htotal, vtotal = hact + hblk, vact + vblk
        pclk = round(self.pclk_sb.value(), 2)
        interlaced = self.interlaced_cb.isChecked()

        frame_rate = (pclk * 1_000_000.0) / (htotal * vtotal) if (htotal and vtotal) else 0.0
        actual_hz = frame_rate * 2.0 if interlaced else frame_rate
        hscan_khz = (pclk * 1000.0) / htotal if htotal else 0.0
        line_us = (htotal / pclk) if pclk else 0.0
        scan_str = f"{actual_hz:.2f} Hz (Interlaced, {frame_rate:.2f} fps)" if interlaced else f"{actual_hz:.2f} Hz (Progressive)"
        enc_str = "DisplayID (>655 MHz)" if pclk > 655.35 else "Standard EDID DTD"

        warnings = []
        if htotal > 4095:
            warnings.append("HTotal > 4095!")
        if hbck < 1 or vbck < 1:
            warnings.append("Back Porch <= 0!")
        if hscan_khz > 140.0:
            warnings.append(">140 kHz H-Scan")
        if pclk > 700.0:
            warnings.append(">700 MHz Clock!")
        status_str = " | ".join(warnings) if warnings else f"Valid ({enc_str})"

        self.stats_label.setText(
            f"Actual Refresh: {scan_str}\n"
            f"H-Scan Rate:    {hscan_khz:.2f} kHz ({line_us:.2f} us line)\n"
            f"Pixel Clock:    {pclk:.2f} MHz ({htotal} x {vtotal} total)\n"
            f"Status:         {status_str}"
        )

    def get_result(self):
        return {
            "type": "dtd", "pclk_mhz": round(self.pclk_sb.value(), 2),
            "hactive": self.hactive_sb.value(), "hblank": self.hblank_sb.value(),
            "hfront": self.hfront_sb.value(), "hsync": self.hsync_sb.value(),
            "vactive": self.vactive_sb.value(), "vblank": self.vblank_sb.value(),
            "vfront": self.vfront_sb.value(), "vsync": self.vsync_sb.value(),
            "interlaced": self.interlaced_cb.isChecked(),
            "hsync_pos": self.hsync_pos_cb.isChecked(),
            "vsync_pos": self.vsync_pos_cb.isChecked()
        }


PROFILES_DIR = os.path.expanduser("~/.config/linux-cru/profiles")


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
        self.setWindowTitle("Linux CRU")
        self.resize(530, 500)
        self.setMinimumSize(380, 380)
        os.makedirs(PROFILES_DIR, exist_ok=True)

        self.ports = scan_drm_ports()
        self.current_port_info = self.ports[0]
        self.current_path = ""
        self.high_clock_dtds = []
        self.edid_bytes = create_blank_crt_edid()
        self.std_slots = decode_std_timings(self.edid_bytes)
        self._switching_port = False

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        # Top Port & Profile Selector
        top_group = QGroupBox("Video Port && Profile")
        top_vbox = QVBoxLayout(top_group)

        sel_grid = QGridLayout()
        self.port_combo = QComboBox()
        for info in self.ports:
            tag = " [Custom EDID Active]" if info["active_override"] else ""
            self.port_combo.addItem(f"{info['port']} ({info['card']}, {info['status']}){tag}")
        self.port_combo.currentIndexChanged.connect(self.on_port_changed)

        self.profile_combo = QComboBox()
        self.profile_combo.activated.connect(self.on_profile_selected)

        sel_grid.addWidget(QLabel("Port:"), 0, 0)
        sel_grid.addWidget(self.port_combo, 0, 1)
        sel_grid.addWidget(QLabel("Profile:"), 1, 0)
        sel_grid.addWidget(self.profile_combo, 1, 1)
        sel_grid.setColumnStretch(1, 1)
        top_vbox.addLayout(sel_grid)

        self.path_label = QLabel("Source: New Blank Profile")
        self.path_label.setMinimumWidth(100)
        font = QFont()
        font.setBold(True)
        self.path_label.setFont(font)
        top_vbox.addWidget(self.path_label)

        top_bar = QHBoxLayout()
        drm_btn = QPushButton("Pull Port EDID")
        drm_btn.setToolTip("Reads the live EDID from the currently selected video port.")
        drm_btn.clicked.connect(self.read_drm_edid)
        save_prof_btn = QPushButton("Save Profile...")
        save_prof_btn.setToolTip("Saves current timings as a named profile in ~/.config/linux-cru/profiles/")
        save_prof_btn.clicked.connect(self.save_named_profile)
        open_btn = QPushButton("Import...")
        open_btn.clicked.connect(self.open_bin)
        new_btn = QPushButton("New")
        new_btn.clicked.connect(self.new_blank_edid)
        top_bar.addWidget(drm_btn)
        top_bar.addWidget(save_prof_btn)
        top_bar.addWidget(open_btn)
        top_bar.addWidget(new_btn)
        top_bar.addStretch()
        top_vbox.addLayout(top_bar)
        layout.addWidget(top_group)

        # Detailed Resolutions Group (4 Slots)
        dtd_group = QGroupBox("Detailed Resolutions (4 Slots)")
        dtd_layout = QVBoxLayout(dtd_group)
        self.table = QTableWidget(4, 5)
        self.table.setHorizontalHeaderLabels([
            "Slot", "Resolution", "Refresh Rate", "H-Scan", "Pixel Clock"
        ])
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        for col in range(1, 5):
            hdr.setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.doubleClicked.connect(self.edit_selected_dtd)
        dtd_layout.addWidget(self.table)

        dtd_btns = QHBoxLayout()
        edit_dtd_btn = QPushButton("Add / Edit...")
        edit_dtd_btn.clicked.connect(self.edit_selected_dtd)
        del_dtd_btn = QPushButton("Clear Slot")
        del_dtd_btn.clicked.connect(self.clear_selected_dtd)
        del_all_dtd_btn = QPushButton("Clear All")
        del_all_dtd_btn.clicked.connect(self.clear_all_dtds)
        dtd_btns.addWidget(edit_dtd_btn)
        dtd_btns.addWidget(del_dtd_btn)
        dtd_btns.addWidget(del_all_dtd_btn)
        dtd_btns.addStretch()
        dtd_layout.addLayout(dtd_btns)
        layout.addWidget(dtd_group)

        # Standard Resolutions Group (8 Slots)
        std_group = QGroupBox("Standard Resolutions (8 Slots)")
        std_layout = QHBoxLayout(std_group)
        self.std_list = QListWidget()
        self.std_list.doubleClicked.connect(self.edit_std_res)
        std_layout.addWidget(self.std_list, 1)

        std_btns = QVBoxLayout()
        add_std_btn = QPushButton("Add...")
        add_std_btn.clicked.connect(self.add_std_res)
        edit_std_btn = QPushButton("Edit...")
        edit_std_btn.clicked.connect(self.edit_std_res)
        del_std_btn = QPushButton("Delete")
        del_std_btn.clicked.connect(self.del_std_res)
        del_all_std_btn = QPushButton("Delete All")
        del_all_std_btn.clicked.connect(self.del_all_std_res)
        std_btns.addWidget(add_std_btn)
        std_btns.addWidget(edit_std_btn)
        std_btns.addWidget(del_std_btn)
        std_btns.addWidget(del_all_std_btn)
        std_btns.addStretch()
        std_layout.addLayout(std_btns)
        layout.addWidget(std_group)

        # Bottom Actions
        bot_bar = QHBoxLayout()
        export_btn = QPushButton("Export .bin...")
        export_btn.clicked.connect(self.save_bin_as)
        live_btn = QPushButton("Apply Live (No Reboot)")
        live_btn.setToolTip("Loads the EDID into the kernel DRM driver and triggers a hotplug refresh without rebooting.")
        live_btn.clicked.connect(self.apply_live_no_reboot)
        install_btn = QPushButton("Install && Rebuild Initramfs")
        install_btn.setToolTip("Saves to /usr/lib/firmware/edid/, applies live, and rebuilds initramfs for boot persistence.")
        install_btn.clicked.connect(self.install_to_firmware)
        bot_bar.addWidget(export_btn)
        bot_bar.addStretch()
        bot_bar.addWidget(live_btn)
        bot_bar.addWidget(install_btn)
        layout.addLayout(bot_bar)

        self.table.selectRow(0)
        self.on_port_changed(0)

    def _collect_high_clock_dtds(self):
        high = []
        for off in DTD_OFFSETS:
            d = decode_dtd(self.edid_bytes[off:off+18], self.edid_bytes)
            if d["type"] == "dtd" and d["pclk_mhz"] > 655.35:
                high.append(d)
        self.high_clock_dtds = high
        return high

    def auto_fix_cru_on_load(self):
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
        for idx, off in enumerate(DTD_OFFSETS):
            d = decode_dtd(self.edid_bytes[off:off+18], self.edid_bytes)
            slot_lbl = f"Slot {idx+1}"
            if d["type"] == "dtd":
                scan_ch = "i" if d["interlaced"] else "p"
                res_str = f"{d['hactive']} x {d['vactive']}{scan_ch}"
                rate_str = f"{d['vrefresh']:.2f} Hz"
                hscan_str = f"{d['hscan_khz']:.2f} kHz"
                clk_str = f"{d['pclk_mhz']:.2f} MHz"
                is_empty = False
            else:
                res_str, rate_str, hscan_str, clk_str = "Empty", "-", "-", "-"
                is_empty = True

            for c_idx, text in enumerate([slot_lbl, res_str, rate_str, hscan_str, clk_str]):
                item = QTableWidgetItem(text)
                if is_empty and c_idx > 0:
                    item.setForeground(muted)
                self.table.setItem(idx, c_idx, item)

        self.std_list.clear()
        active_std = [s for s in self.std_slots if s is not None]
        if not active_std:
            empty_item = QListWidgetItem("No Standard Resolutions configured")
            empty_item.setForeground(muted)
            self.std_list.addItem(empty_item)
        else:
            for idx, s in enumerate(active_std):
                self.std_list.addItem(f"Slot {idx+1}:  {s['w']} x {s['h']} ({s['ar_name']}) @ {s['hz']} Hz")

    def new_blank_edid(self):
        self.edid_bytes = create_blank_crt_edid()
        self.std_slots = decode_std_timings(self.edid_bytes)
        self.high_clock_dtds = []
        self.current_path = ""
        self.path_label.setText("Source: New Blank Profile")
        self.refresh_ui()

    def edit_selected_dtd(self):
        row = max(0, self.table.currentRow())
        off = DTD_OFFSETS[row]
        block = self.edid_bytes[off:off+18]
        dlg = DTDEditorDialog(self, decode_dtd(block, self.edid_bytes))
        if dlg.exec() == QDialog.DialogCode.Accepted:
            res = dlg.get_result()
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
        self.edid_bytes[off:off+18] = bytes([0, 0, 0, 0x10, 0] + [0]*13)
        sync_700mhz_and_displayid(self.edid_bytes, self._collect_high_clock_dtds(), True)
        self.refresh_ui()

    def clear_all_dtds(self):
        for off in DTD_OFFSETS:
            self.edid_bytes[off:off+18] = bytes([0, 0, 0, 0x10, 0] + [0]*13)
        sync_700mhz_and_displayid(self.edid_bytes, [], True)
        self.refresh_ui()

    def add_std_res(self):
        active = [s for s in self.std_slots if s is not None]
        if len(active) >= 8:
            QMessageBox.warning(self, "Full", "All 8 Standard Resolution slots are full.")
            return
        dlg = StandardResDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            active.append(dlg.get_result())
            self.std_slots = active + [None] * (8 - len(active))
            encode_std_timings(self.edid_bytes, self.std_slots)
            update_checksum(self.edid_bytes)
            self.refresh_ui()

    def edit_std_res(self):
        row = self.std_list.currentRow()
        active = [s for s in self.std_slots if s is not None]
        if row < 0 or row >= len(active):
            return
        dlg = StandardResDialog(self, active[row])
        if dlg.exec() == QDialog.DialogCode.Accepted:
            active[row] = dlg.get_result()
            self.std_slots = active + [None] * (8 - len(active))
            encode_std_timings(self.edid_bytes, self.std_slots)
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

        for p in sorted(glob.glob(os.path.join(PROFILES_DIR, "*.bin"))):
            if os.path.getsize(p) >= 128:
                name = os.path.splitext(os.path.basename(p))[0]
                self.profile_combo.addItem(f"Saved Profile: {name}")
                self.profile_sources.append(("file", p))

        self.profile_combo.blockSignals(False)

    def on_port_changed(self, idx):
        if idx < 0 or idx >= len(self.ports):
            return
        self.current_port_info = self.ports[idx]
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
        port = self.current_port_info["port"]
        default_file = os.path.join(PROFILES_DIR, f"{port}.bin")
        path, _ = QFileDialog.getSaveFileName(self, "Save Profile", default_file, "EDID Profile (*.bin)")
        if path:
            if not path.endswith(".bin"):
                path += ".bin"
            open(path, "wb").write(self.edid_bytes)
            self.current_path = path
            self.path_label.setText(f"[{port}] Saved Profile: {path}")
            self._populate_profile_combo()

    def open_bin(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import EDID .bin", os.path.expanduser("~"), "EDID (*.bin);;All (*)")
        if path:
            data = bytearray(open(path, "rb").read())
            if len(data) >= 128:
                self.edid_bytes = data
                self.auto_fix_cru_on_load()
                self.std_slots = decode_std_timings(self.edid_bytes)
                self.current_path = path
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
        port = self.current_port_info["port"].lower()
        path, _ = QFileDialog.getSaveFileName(self, "Export .bin", os.path.expanduser(f"~/cru-{port}.bin"), "EDID (*.bin)")
        if path:
            open(path, "wb").write(self.edid_bytes)
            self.current_path = path
            self.path_label.setText(f"Exported: {path}")

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

sudo install -m 0755 "$TMP_APP" /usr/local/bin/linux-cru
cp "$TMP_APP" "$HOME/bin/linux-cru"
chmod +x "$HOME/bin/linux-cru"

echo "==> [3/3] Creating Desktop Launcher Shortcut..."
mkdir -p "$HOME/.local/share/applications"
cat << 'DESKTOP_EOF' > "$HOME/.local/share/applications/linux-cru.desktop"
[Desktop Entry]
Name=Linux CRU
Comment=ToastyX-Style Custom Resolution Utility for Linux
Exec=/usr/local/bin/linux-cru
Icon=video-display
Terminal=false
Type=Application
Categories=System;Settings;HardwareSettings;
DESKTOP_EOF

echo "==> Linux CRU installed! Run 'linux-cru' or launch it from your application menu."
