#!/usr/bin/env bash
# Standalone Installer for Linux CRU (CRT EDID Studio)
# Supports: Arch/CachyOS, Debian/Ubuntu, Fedora, openSUSE
set -euo pipefail
umask 022

TMP_APP="$(mktemp)"
trap 'rm -f "$TMP_APP"' EXIT

echo "==> [1/3] Installing Python 3 & PyQt6 dependencies..."
if command -v pacman >/dev/null 2>&1; then
    sudo pacman -S --needed --noconfirm python python-pyqt6
elif command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update && sudo apt-get install -y python3 python3-pyqt6
elif command -v dnf >/dev/null 2>&1; then
    sudo dnf install -y python3 python3-pyqt6
elif command -v zypper >/dev/null 2>&1; then
    sudo zypper install -y python3 python-PyQt6
else
    echo "WARNING: Package manager not recognized. Ensure Python 3 and PyQt6 are installed."
fi

echo "==> [2/3] Installing linux-cru to /usr/local/bin/linux-cru..."
cat << 'APP_EOF' > "$TMP_APP"
#!/usr/bin/env python3
import sys
import os
import glob
import subprocess
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTableWidget, QTableWidgetItem, QPushButton, QLabel, QFileDialog,
    QDialog, QFormLayout, QSpinBox, QDoubleSpinBox, QCheckBox,
    QComboBox, QMessageBox, QGroupBox, QHeaderView
)
from PyQt6.QtGui import QColor, QFont

DEFAULT_EDID_PATH = "/usr/lib/firmware/edid/crufile.bin"
DTD_OFFSETS = (54, 72, 90, 108)


def create_blank_crt_edid():
    b = bytearray(128)
    b[0:8] = b'\x00\xff\xff\xff\xff\xff\xff\x00'
    b[8:10] = b'\x22\xf0'
    b[10:12] = b'\xd0\x09'
    b[18] = 1
    b[19] = 3
    b[20] = 0x0E
    b[21] = 41
    b[22] = 31
    b[23] = 120
    b[24] = 0xEA
    # Default Slot 1: 2048x1536i @ 160Hz (Linux Full-Frame Format)
    d = calculate_crt_timings(2048, 1536, 160.0, True)
    b[54:72] = encode_dtd(d)
    # Default Slot 4: Monitor Range Limits (30-160 Hz, 30-140 kHz, 400 MHz max clock)
    b[108:126] = bytes([
        0x00, 0x00, 0x00, 0xFD, 0x00,
        30, 160, 30, 140, 40, 0x00,
        0x0A, 0x20, 0x20, 0x20, 0x20, 0x20, 0x20
    ])
    update_checksum(b)
    return b


def update_checksum(b):
    b[127] = (256 - (sum(b[:127]) % 256)) % 256


def decode_dtd(block):
    if block[0] == 0 and block[1] == 0:
        tag = block[3]
        if tag == 0xFC:
            name = block[5:18].decode('ascii', errors='ignore').strip()
            return {"type": "monitor_name", "name": name}
        elif tag == 0xFD:
            return {
                "type": "range_limits",
                "v_min": block[5], "v_max": block[6],
                "h_min": block[7], "h_max": block[8],
                "max_pclk": block[9] * 10
            }
        return {"type": "empty", "tag": tag}

    pclk_mhz = (block[0] | (block[1] << 8)) / 100.0
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

    htotal = hactive + hblank
    vtotal = vactive + vblank
    if htotal > 0 and vtotal > 0:
        mult = 2.0 if interlaced else 1.0
        vrefresh = (pclk_mhz * 1_000_000.0 * mult) / (htotal * vtotal)
        hscan_khz = (pclk_mhz * 1000.0) / htotal
    else:
        vrefresh, hscan_khz = 0.0, 0.0

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
    if existing_block and len(existing_block) == 18:
        b[12:17] = existing_block[12:17]
    else:
        b[12] = 406 & 0xFF
        b[13] = 305 & 0xFF
        b[14] = (((406 >> 8) & 0x0F) << 4) | ((305 >> 8) & 0x0F)

    pclk_10khz = max(1, min(65535, int(round(d["pclk_mhz"] * 100.0))))
    b[0] = pclk_10khz & 0xFF
    b[1] = (pclk_10khz >> 8) & 0xFF

    hactive = max(1, min(4095, int(d["hactive"])))
    hblank = max(1, min(4095, int(d["hblank"])))
    vactive = max(1, min(4095, int(d["vactive"])))
    vblank = max(1, min(4095, int(d["vblank"])))
    hfront = max(1, min(1023, int(d["hfront"])))
    hsync = max(1, min(1023, int(d["hsync"])))
    vfront = max(1, min(63, int(d["vfront"])))
    vsync = max(1, min(63, int(d["vsync"])))

    b[2] = hactive & 0xFF
    b[3] = hblank & 0xFF
    b[4] = (((hactive >> 8) & 0x0F) << 4) | ((hblank >> 8) & 0x0F)
    b[5] = vactive & 0xFF
    b[6] = vblank & 0xFF
    b[7] = (((vactive >> 8) & 0x0F) << 4) | ((vblank >> 8) & 0x0F)
    b[8] = hfront & 0xFF
    b[9] = hsync & 0xFF
    b[10] = ((vfront & 0x0F) << 4) | (vsync & 0x0F)
    b[11] = (
        (((hfront >> 8) & 0x03) << 6) |
        (((hsync >> 8) & 0x03) << 4) |
        (((vfront >> 4) & 0x03) << 2) |
        ((vsync >> 4) & 0x03)
    )
    flags = 0x18
    if d["interlaced"]:
        flags |= 0x80
    if d["vsync_pos"]:
        flags |= 0x04
    if d["hsync_pos"]:
        flags |= 0x02
    b[17] = flags
    return b


def calculate_crt_timings(hactive, vactive, refresh_hz, interlaced):
    frame_rate = (refresh_hz / 2.0) if interlaced else refresh_hz
    if interlaced:
        vfront, vsync = 6, 8
        vblank = max(vfront + vsync + 20, int(round(vactive * 0.1015)))
        if vblank % 2 != 0:
            vblank += 1
    else:
        vfront, vsync = 1, 3
        vblank = max(vfront + vsync + 14, int(round(vactive * 0.05)))

    vtotal = vactive + vblank
    hscan_khz = (frame_rate * vtotal) / 1000.0
    hblank = int(round(hactive * 0.3828 / 8.0)) * 8
    hfront = int(round(hactive * 0.082 / 8.0)) * 8
    hsync = int(round(hactive * 0.109 / 8.0)) * 8
    if hfront + hsync >= hblank:
        hblank = hfront + hsync + 64

    htotal = hactive + hblank
    pclk_mhz = round((hscan_khz * htotal) / 1000.0, 2)
    return {
        "type": "dtd", "pclk_mhz": pclk_mhz,
        "hactive": hactive, "hblank": hblank, "hfront": hfront, "hsync": hsync,
        "vactive": vactive, "vblank": vblank, "vfront": vfront, "vsync": vsync,
        "interlaced": interlaced, "hsync_pos": False, "vsync_pos": True
    }


class DTDEditorDialog(QDialog):
    def __init__(self, parent, initial_data):
        super().__init__(parent)
        self.setWindowTitle("Detailed Resolution Calculator (Linux DRM Format)")
        self.setMinimumWidth(480)
        self._updating = False
        if initial_data.get("type") != "dtd":
            initial_data = calculate_crt_timings(2048, 1536, 160.0, True)

        layout = QVBoxLayout(self)
        mode_group = QGroupBox("Timing Mode & Target Resolution")
        mode_form = QFormLayout(mode_group)

        self.preset_combo = QComboBox()
        self.preset_combo.addItems(["Automatic CRT (Linux Full-Frame)", "Manual Timings"])
        mode_form.addRow("Timing Mode:", self.preset_combo)

        self.interlaced_cb = QCheckBox("Interlaced (Linux Full-Frame Height Format)")
        self.interlaced_cb.setChecked(initial_data.get("interlaced", False))
        mode_form.addRow("", self.interlaced_cb)

        self.hactive_sb = QSpinBox()
        self.hactive_sb.setRange(64, 4095)
        self.hactive_sb.setValue(initial_data["hactive"])
        mode_form.addRow("Horizontal Active (px):", self.hactive_sb)

        self.vactive_sb = QSpinBox()
        self.vactive_sb.setRange(64, 4095)
        self.vactive_sb.setValue(initial_data["vactive"])
        mode_form.addRow("Vertical Active (Full Frame px):", self.vactive_sb)

        self.refresh_sb = QDoubleSpinBox()
        self.refresh_sb.setRange(20.0, 500.0)
        self.refresh_sb.setDecimals(2)
        self.refresh_sb.setSuffix(" Hz")
        self.refresh_sb.setValue(initial_data.get("vrefresh", 160.0))
        mode_form.addRow("Target Refresh Rate:", self.refresh_sb)
        layout.addWidget(mode_group)

        timing_group = QGroupBox("Detailed CRT Blanking & Sync Parameters")
        timing_form = QFormLayout(timing_group)

        self.hfront_sb = QSpinBox()
        self.hfront_sb.setRange(1, 1023)
        self.hfront_sb.setValue(initial_data["hfront"])
        timing_form.addRow("H Front Porch:", self.hfront_sb)

        self.hsync_sb = QSpinBox()
        self.hsync_sb.setRange(1, 1023)
        self.hsync_sb.setValue(initial_data["hsync"])
        timing_form.addRow("H Sync Width:", self.hsync_sb)

        self.hblank_sb = QSpinBox()
        self.hblank_sb.setRange(2, 4095)
        self.hblank_sb.setValue(initial_data["hblank"])
        timing_form.addRow("H Blanking:", self.hblank_sb)

        self.vfront_sb = QSpinBox()
        self.vfront_sb.setRange(1, 63)
        self.vfront_sb.setValue(min(63, initial_data["vfront"]))
        timing_form.addRow("V Front Porch (Max 63):", self.vfront_sb)

        self.vsync_sb = QSpinBox()
        self.vsync_sb.setRange(1, 63)
        self.vsync_sb.setValue(min(63, initial_data["vsync"]))
        timing_form.addRow("V Sync Width (Max 63):", self.vsync_sb)

        self.vblank_sb = QSpinBox()
        self.vblank_sb.setRange(2, 4095)
        self.vblank_sb.setValue(initial_data["vblank"])
        timing_form.addRow("V Blanking (Full Frame):", self.vblank_sb)

        self.pclk_sb = QDoubleSpinBox()
        self.pclk_sb.setRange(1.0, 655.35)
        self.pclk_sb.setDecimals(2)
        self.pclk_sb.setSingleStep(0.10)
        self.pclk_sb.setSuffix(" MHz")
        self.pclk_sb.setValue(initial_data["pclk_mhz"])
        timing_form.addRow("Pixel Clock:", self.pclk_sb)

        pol_layout = QHBoxLayout()
        self.hsync_pos_cb = QCheckBox("+HSync")
        self.hsync_pos_cb.setChecked(initial_data.get("hsync_pos", False))
        self.vsync_pos_cb = QCheckBox("+VSync")
        self.vsync_pos_cb.setChecked(initial_data.get("vsync_pos", True))
        pol_layout.addWidget(self.hsync_pos_cb)
        pol_layout.addWidget(self.vsync_pos_cb)
        timing_form.addRow("Sync Polarity:", pol_layout)
        layout.addWidget(timing_group)

        self.stats_label = QLabel()
        self.stats_label.setWordWrap(True)
        font = QFont()
        font.setBold(True)
        self.stats_label.setFont(font)
        layout.addWidget(self.stats_label)

        btn_layout = QHBoxLayout()
        ok_btn = QPushButton("Save Slot")
        ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addStretch()
        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(ok_btn)
        layout.addLayout(btn_layout)

        self.preset_combo.currentIndexChanged.connect(self.on_mode_changed)
        self.hactive_sb.valueChanged.connect(self.recalculate)
        self.vactive_sb.valueChanged.connect(self.recalculate)
        self.refresh_sb.valueChanged.connect(self.recalculate)
        self.interlaced_cb.toggled.connect(self.recalculate)
        for sb in (self.hfront_sb, self.hsync_sb, self.hblank_sb,
                   self.vfront_sb, self.vsync_sb, self.vblank_sb, self.pclk_sb):
            sb.valueChanged.connect(self.update_live_stats)

        self.preset_combo.setCurrentIndex(1)
        self.on_mode_changed()
        self.update_live_stats()

    def on_mode_changed(self):
        is_auto = (self.preset_combo.currentIndex() == 0)
        for sb in (self.hfront_sb, self.hsync_sb, self.hblank_sb,
                   self.vfront_sb, self.vsync_sb, self.vblank_sb, self.pclk_sb):
            sb.setEnabled(not is_auto)
        self.refresh_sb.setEnabled(is_auto)
        if is_auto:
            self.recalculate()

    def recalculate(self):
        if self._updating:
            return
        if self.preset_combo.currentIndex() == 0:
            self._updating = True
            res = calculate_crt_timings(
                self.hactive_sb.value(), self.vactive_sb.value(),
                self.refresh_sb.value(), self.interlaced_cb.isChecked()
            )
            self.hfront_sb.setValue(res["hfront"])
            self.hsync_sb.setValue(res["hsync"])
            self.hblank_sb.setValue(res["hblank"])
            self.vfront_sb.setValue(res["vfront"])
            self.vsync_sb.setValue(res["vsync"])
            self.vblank_sb.setValue(res["vblank"])
            self.pclk_sb.setValue(res["pclk_mhz"])
            self._updating = False
        self.update_live_stats()

    def update_live_stats(self):
        if self._updating:
            return
        htotal = self.hactive_sb.value() + self.hblank_sb.value()
        vtotal = self.vactive_sb.value() + self.vblank_sb.value()
        pclk = self.pclk_sb.value()
        interlaced = self.interlaced_cb.isChecked()
        mult = 2.0 if interlaced else 1.0
        actual_hz = (pclk * 1_000_000.0 * mult) / (htotal * vtotal)
        hscan_khz = (pclk * 1000.0) / htotal
        if self.preset_combo.currentIndex() == 1:
            self._updating = True
            self.refresh_sb.setValue(actual_hz)
            self._updating = False
        warn = "  [WARNING: >140 kHz!]" if hscan_khz > 140.0 else ""
        self.stats_label.setText(
            f"Totals: {htotal}x{vtotal} | H-Scan: {hscan_khz:.2f} kHz | "
            f"Refresh: {actual_hz:.2f} Hz | Clock: {pclk:.2f} MHz{warn}"
        )

    def get_result(self):
        return {
            "type": "dtd", "pclk_mhz": self.pclk_sb.value(),
            "hactive": self.hactive_sb.value(), "hblank": self.hblank_sb.value(),
            "hfront": self.hfront_sb.value(), "hsync": self.hsync_sb.value(),
            "vactive": self.vactive_sb.value(), "vblank": self.vblank_sb.value(),
            "vfront": self.vfront_sb.value(), "vsync": self.vsync_sb.value(),
            "interlaced": self.interlaced_cb.isChecked(),
            "hsync_pos": self.hsync_pos_cb.isChecked(),
            "vsync_pos": self.vsync_pos_cb.isChecked()
        }


class LinuxCRUWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Linux CRU — CRT EDID Studio (Linux Frame-Height Format)")
        self.resize(820, 460)
        self.current_path = DEFAULT_EDID_PATH if os.path.exists(DEFAULT_EDID_PATH) else ""
        if self.current_path:
            self.edid_bytes = bytearray(open(self.current_path, "rb").read())
        else:
            self.edid_bytes = create_blank_crt_edid()

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        top_bar = QHBoxLayout()
        self.path_label = QLabel(f"Loaded EDID: {self.current_path or '(Default CRT 2048x1536i Template)'}")
        new_btn = QPushButton("New Template")
        new_btn.clicked.connect(self.new_template)
        open_btn = QPushButton("Open .bin File...")
        open_btn.clicked.connect(self.open_bin)
        drm_btn = QPushButton("Read Active DRM EDID...")
        drm_btn.clicked.connect(self.read_drm_edid)
        top_bar.addWidget(self.path_label, 1)
        top_bar.addWidget(new_btn)
        top_bar.addWidget(open_btn)
        top_bar.addWidget(drm_btn)
        layout.addLayout(top_bar)

        self.table = QTableWidget(4, 5)
        self.table.setHorizontalHeaderLabels([
            "Slot", "Resolution & Mode", "Refresh / Scan Rate", "Pixel Clock & Totals", "Linux Status"
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.doubleClicked.connect(self.edit_selected_slot)
        layout.addWidget(self.table)

        mid_bar = QHBoxLayout()
        edit_btn = QPushButton("Edit / Calculate Resolution in Selected Slot")
        edit_btn.clicked.connect(self.edit_selected_slot)
        fix_cru_btn = QPushButton("Auto-Fix Windows CRU Field-Height (768i -> 1536i)")
        fix_cru_btn.clicked.connect(self.fix_all_cru_slots)
        mid_bar.addWidget(edit_btn)
        mid_bar.addWidget(fix_cru_btn)
        layout.addLayout(mid_bar)

        bot_bar = QHBoxLayout()
        save_as_btn = QPushButton("Export .bin File...")
        save_as_btn.clicked.connect(self.save_bin_as)
        install_btn = QPushButton("Install to /usr/lib/firmware/edid/crufile.bin & Rebuild Initramfs")
        install_btn.clicked.connect(self.install_to_firmware)
        bot_bar.addStretch()
        bot_bar.addWidget(save_as_btn)
        bot_bar.addWidget(install_btn)
        layout.addLayout(bot_bar)

        self.refresh_table()

    def new_template(self):
        self.edid_bytes = create_blank_crt_edid()
        self.current_path = ""
        self.path_label.setText("Loaded EDID: (New Blank CRT Template)")
        self.refresh_table()

    def refresh_table(self):
        for idx, off in enumerate(DTD_OFFSETS):
            block = self.edid_bytes[off:off+18]
            d = decode_dtd(block)
            self.table.setItem(idx, 0, QTableWidgetItem(f"Detailed Slot {idx+1} (@{off})"))
            if d["type"] == "dtd":
                mode_str = f"{d['hactive']}x{d['vactive']}{'i' if d['interlaced'] else 'p'}"
                rate_str = f"{d['vrefresh']:.2f} Hz  ({d['hscan_khz']:.2f} kHz)"
                clk_str = f"{d['pclk_mhz']:.2f} MHz  ({d['hactive']+d['hblank']}x{d['vactive']+d['vblank']})"
                if d["cru_field_bug"]:
                    status_str = "WARNING: Windows CRU Field-Height! Click Auto-Fix"
                elif d["interlaced"]:
                    status_str = "OK (Linux Interlaced Full-Frame)"
                else:
                    status_str = "OK (Progressive)"
            elif d["type"] == "monitor_name":
                mode_str, rate_str, clk_str, status_str = f"[Monitor Name: {d['name']}]", "-", "-", "Descriptor (0xFC)"
            elif d["type"] == "range_limits":
                mode_str = "[Monitor Range Limits]"
                rate_str = f"{d['v_min']}-{d['v_max']} Hz / {d['h_min']}-{d['h_max']} kHz"
                clk_str = f"Max {d['max_pclk']} MHz"
                status_str = "Descriptor (0xFD)"
            else:
                mode_str, rate_str, clk_str, status_str = "[Empty / Unused Slot]", "-", "-", "Unused"

            self.table.setItem(idx, 1, QTableWidgetItem(mode_str))
            self.table.setItem(idx, 2, QTableWidgetItem(rate_str))
            self.table.setItem(idx, 3, QTableWidgetItem(clk_str))
            status_item = QTableWidgetItem(status_str)
            if "WARNING" in status_str:
                status_item.setForeground(QColor("#ff5555"))
            self.table.setItem(idx, 4, status_item)

    def edit_selected_slot(self):
        row = max(0, self.table.currentRow())
        off = DTD_OFFSETS[row]
        block = self.edid_bytes[off:off+18]
        dlg = DTDEditorDialog(self, decode_dtd(block))
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.edid_bytes[off:off+18] = encode_dtd(dlg.get_result(), block)
            update_checksum(self.edid_bytes)
            self.refresh_table()

    def fix_all_cru_slots(self):
        fixed_count = 0
        for off in DTD_OFFSETS:
            block = self.edid_bytes[off:off+18]
            d = decode_dtd(block)
            if d["type"] == "dtd" and d["interlaced"] and d["vactive"] < 1000:
                d["vactive"] *= 2
                d["vblank"] *= 2
                d["vfront"] = min(63, d["vfront"] * 2)
                d["vsync"] = min(63, d["vsync"] * 2)
                self.edid_bytes[off:off+18] = encode_dtd(d, block)
                fixed_count += 1
        update_checksum(self.edid_bytes)
        self.refresh_table()
        QMessageBox.information(self, "CRU Fix", f"Converted {fixed_count} slot(s) to Linux Full-Frame height.")

    def open_bin(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open EDID .bin", os.path.expanduser("~"), "EDID (*.bin);;All (*)")
        if path:
            data = bytearray(open(path, "rb").read())
            if len(data) < 128:
                QMessageBox.critical(self, "Error", "File is smaller than 128 bytes!")
                return
            self.edid_bytes = data
            self.current_path = path
            self.path_label.setText(f"Loaded EDID: {path}")
            self.refresh_table()

    def read_drm_edid(self):
        paths = sorted(glob.glob("/sys/class/drm/card*-*/edid"))
        valid = [p for p in paths if os.path.exists(p) and len(open(p, "rb").read()) >= 128]
        if not valid:
            QMessageBox.warning(self, "No DRM EDID", "No active DRM connector EDIDs found.")
            return
        p = next((c for c in valid if "VGA" in c or "DVI" in c), valid[-1])
        self.edid_bytes = bytearray(open(p, "rb").read())
        self.current_path = p
        self.path_label.setText(f"Loaded from DRM: {p}")
        self.refresh_table()

    def save_bin_as(self):
        update_checksum(self.edid_bytes)
        path, _ = QFileDialog.getSaveFileName(self, "Export .bin", os.path.expanduser("~/crufile.bin"), "EDID (*.bin)")
        if path:
            open(path, "wb").write(self.edid_bytes)
            self.current_path = path
            self.path_label.setText(f"Saved EDID: {path}")
            QMessageBox.information(self, "Saved", f"Saved Linux-formatted EDID to:\n{path}")

    def install_to_firmware(self):
        update_checksum(self.edid_bytes)
        tmp_path = "/tmp/linux_cru_edid.bin"
        open(tmp_path, "wb").write(self.edid_bytes)
        cmd = (
            f"mkdir -p /usr/lib/firmware/edid && cp {tmp_path} {DEFAULT_EDID_PATH} && "
            f"(command -v limine-mkinitcpio >/dev/null && limine-mkinitcpio || "
            f"command -v mkinitcpio >/dev/null && mkinitcpio -P || "
            f"command -v dracut >/dev/null && dracut --regenerate-all --force || "
            f"update-initramfs -u -k all)"
        )
        if subprocess.call(["pkexec", "bash", "-c", cmd]) == 0:
            self.current_path = DEFAULT_EDID_PATH
            self.path_label.setText(f"Installed to: {DEFAULT_EDID_PATH}")
            QMessageBox.information(self, "Success", f"Installed to {DEFAULT_EDID_PATH} and rebuilt initramfs.")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = LinuxCRUWindow()
    win.show()
    sys.exit(app.exec())
APP_EOF

sudo install -m 0755 "$TMP_APP" /usr/local/bin/linux-cru

echo "==> [3/3] Creating Desktop Launcher Shortcut..."
mkdir -p "$HOME/.local/share/applications"
cat << 'DESKTOP_EOF' > "$HOME/.local/share/applications/linux-cru.desktop"
[Desktop Entry]
Name=Linux CRU (CRT EDID Studio)
Comment=Create and edit Linux-formatted CRT progressive & interlaced EDID .bin files
Exec=/usr/local/bin/linux-cru
Icon=video-display
Terminal=false
Type=Application
Categories=System;Settings;HardwareSettings;
DESKTOP_EOF

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$HOME/.local/share/applications" || true
fi

echo "==> Done! Launch 'Linux CRU' from your application launcher or by running: linux-cru"
