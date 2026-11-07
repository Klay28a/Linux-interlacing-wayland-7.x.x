#!/usr/bin/env python3
"""
Linux CRT Interlacing Suite: one window for the three scripts.

  setup-interlace-env.sh     EDID, initramfs and bootloader
  fix-interlaced-kernel.sh   15kHz kernel build and GPU rules
  install-linux-cru.sh       standalone Linux CRU editor

Every dropdown feeds ``interlace_selection`` (what each button passes to its script) and
``interlace_verify`` (the badges), so what a badge checks is exactly what the button applies.
"""

import contextlib
import html
import importlib
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PyQt6.QtCore import QEvent, Qt, QTimer
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
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

logger = logging.getLogger("linux_interlace_suite")

APP_TITLE = "Linux CRT Interlacing Suite"
CONFIG_DIR = Path.home() / ".config" / "linux-interlace-suite"
CONFIG_FILE = CONFIG_DIR / "config.json"

# Modules the window itself needs; a suite directory only qualifies if all of them import.
_GUI_MODULES = (
    "interlace_manifest", "interlace_gui_tasks", "interlace_selection", "interlace_sysinfo", "interlace_verify",
)


def _bootstrap_suite() -> Path:
    """Put the first *working* suite directory on ``sys.path`` (this file may be a lone copy in ~/.local/bin)."""
    here = Path(__file__).resolve().parent
    for cand in (
        here,
        Path.home() / ".local" / "share" / "linux-interlace-suite",
        Path("/usr/local/share/linux-interlace-suite"),
        Path("/usr/share/linux-interlace-suite"),
    ):
        if not cand.is_dir():
            continue
        sys.path.insert(0, str(cand))
        try:
            for name in _GUI_MODULES:
                importlib.import_module(name)
        except ImportError:
            sys.path.remove(str(cand))
            for loaded in [m for m in sys.modules if m.startswith("interlace_")]:
                del sys.modules[loaded]
            continue
        return cand
    raise SystemExit(
        "Linux CRT Interlacing Suite: no complete install found next to the app or in ~/.local/share, "
        "/usr/local/share or /usr/share. Reinstall the suite.",
    )


SUITE_DIR = _bootstrap_suite()

import interlace_manifest as manifest
from interlace_gui_tasks import TaskMixin
from interlace_runner import SystemPaths
from interlace_selection import (
    Resolved,
    Selection,
    SelectionError,
    kernel_args,
    resolve,
    setup_args,
)
from interlace_sysinfo import SystemInfo, collect_system_info
from interlace_verify import Check, Verification, verify_all

GPU_PROFILES = [
    ("auto", "Auto-detect"),
    ("rdna-single", "AMD RDNA, single GPU"),
    ("gcn-single", "AMD GCN, single GPU"),
    ("nvidia-single", "NVIDIA, single GPU"),
    ("dual-nvidia-amd", "NVIDIA + AMD, dual GPU"),
    ("dual-amd-amd", "AMD + AMD, dual GPU"),
]
ADAPTER_MODES = [
    ("auto", "Auto-detect"),
    ("dp-dac", "DisplayPort DAC"),
    ("hdmi-dac", "HDMI DAC"),
    ("analog-native", "Native analog (VGA / DVI-I)"),
]
KERNEL_VERSIONS = [
    ("auto", "Auto (running kernel)"),
    ("7.3", "Linux 7.3"),
    ("7.2", "Linux 7.2"),
    ("6.18", "Linux 6.18 LTS"),
    ("6.12", "Linux 6.12 LTS"),
    ("6.6", "Linux 6.6 LTS"),
    ("6.1", "Linux 6.1 LTS"),
    ("linux-next", "Linux-next (RC)"),
]
FALLBACK_PORTS = ("DP-1", "DP-2", "HDMI-A-1", "HDMI-A-2", "VGA-1", "DVI-I-1")

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


def resolve_scripts_dir(saved_dir: str = "") -> Path:
    """The suite directory to run scripts from: a *complete* one (see interlace_manifest), never a stale path."""
    return manifest.resolve_suite_dir(saved_dir, Path(__file__).resolve().parent, Path.home())


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_FILE.exists():
        with contextlib.suppress(OSError, ValueError):
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                cfg.update(data)
    return cfg


def save_config(cfg: dict) -> None:
    with contextlib.suppress(OSError, ValueError):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def probe_system(paths: SystemPaths | None = None) -> SystemInfo:
    """Read the live machine (lspci, /sys, /proc). Tests replace this with the mock PC fixtures."""
    paths = paths or SystemPaths()
    try:
        out = subprocess.run(
            ["lspci", "-D", "-nn"], check=True, text=True, capture_output=True, stdin=subprocess.DEVNULL,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        logger.debug("lspci failed; continuing without GPU info", exc_info=True)
        out = ""
    return collect_system_info(paths, out, shutil.which, os.uname().release)


class AutoWrapLabel(QLabel):
    """Word-wrapping label whose height follows its width (never forces the window wider)."""

    def __init__(self, text: str = "", parent: QWidget | None = None):
        super().__init__(text, parent)
        self.setWordWrap(True)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    def _fit(self, hint):
        hint.setWidth(min(hint.width(), 200))
        if self.width() > 60 and (h := self.heightForWidth(self.width())) > 0:
            hint.setHeight(h)
        return hint

    def minimumSizeHint(self):
        return self._fit(super().minimumSizeHint())

    def sizeHint(self):
        return self._fit(super().sizeHint())

    def setText(self, text: str):
        super().setText(text)
        self.updateGeometry()


class NoWheelComboBox(QComboBox):
    """Scrolling the window must never change a dropdown."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.setMinimumContentsLength(18)

    def wheelEvent(self, event):
        event.ignore()


def stylesheet(scale: float) -> str:
    base, small, title = round(10.0 * scale, 1), round(9.0 * scale, 1), round(15.0 * scale, 1)
    section = round(12.5 * scale, 1)
    return f"""
        QMainWindow, QWidget#scrollContent {{ background-color: #16181d; color: #e6edf3; font-size: {base}pt; }}
        QScrollArea {{ border: none; background-color: #16181d; }}
        QLabel {{ color: #e6edf3; font-size: {base}pt; }}
        QLabel#title {{ font-size: {title}pt; font-weight: bold; color: #ffffff; }}
        QLabel#muted {{ font-size: {small}pt; color: #9da7b3; }}
        QLabel#section {{ font-size: {section}pt; font-weight: bold; color: #f0f6fc; padding-top: 4px; }}
        QLabel#cellTitle {{ font-size: {small}pt; font-weight: bold; color: #8b949e; }}
        QLabel#cellValue {{ font-weight: 600; color: #f0f6fc; }}
        QFrame#card {{ background-color: #1c2028; border: 1px solid #353d4b; border-radius: 10px; }}
        QFrame#cell {{ background-color: #242933; border: 1px solid #363f4f; border-radius: 8px; }}
        QFrame#step {{ background-color: #222831; border: 1px solid #384352; border-radius: 8px; }}
        QLabel#badgeOk {{
            background-color: #153726; color: #56d364; border: 1px solid #2ea043;
            border-radius: 5px; padding: 2px 8px; font-size: {small}pt; font-weight: bold;
        }}
        QLabel#badgeWarn {{
            background-color: #3a2d13; color: #e3b341; border: 1px solid #9e6a03;
            border-radius: 5px; padding: 2px 8px; font-size: {small}pt; font-weight: bold;
        }}
        QComboBox, QLineEdit {{
            background-color: #262c36; color: #f0f6fc; border: 1px solid #424b59;
            border-radius: 6px; padding: 5px 9px; min-height: 20px;
        }}
        QComboBox:focus, QLineEdit:focus {{ border: 1px solid #58a6ff; }}
        QPushButton {{
            background-color: #2b323d; color: #f0f6fc; border: 1px solid #485263;
            border-radius: 6px; padding: 5px 12px; font-weight: 600;
        }}
        QPushButton:hover:enabled {{ background-color: #353e4c; border-color: #637085; }}
        QPushButton:disabled {{ background-color: #1d2229; color: #6e7681; border: 1px solid #2f3540; }}
        QPushButton#scriptBtn {{
            background-color: #1f6feb; color: #ffffff; border: 1px solid #388bfd;
            padding: 8px 16px; font-weight: bold; font-family: monospace;
        }}
        QPushButton#scriptBtn:hover:enabled {{ background-color: #388bfd; }}
        QPushButton#scriptBtn:disabled {{ background-color: #17315a; color: #7d93b8; border: 1px solid #1f3f73; }}
        QPushButton#subBtn {{ font-size: {small}pt; font-weight: normal; padding: 4px 10px; }}
        QPushButton#stopBtn {{ font-size: {small}pt; padding: 4px 14px; }}
        QPushButton#stopBtn:enabled {{
            background-color: #b62324; color: #ffffff; border: 1px solid #f85149; font-weight: bold;
        }}
        QPushButton#stopBtn:hover:enabled {{ background-color: #da3633; }}
        QProgressBar {{
            background-color: #141820; color: #f0f6fc; border: 1px solid #384352; border-radius: 6px;
            text-align: center; font-weight: bold; min-height: 18px; font-size: {small}pt;
        }}
        QProgressBar::chunk {{ background-color: #238636; border-radius: 5px; }}
        QCheckBox {{ spacing: 8px; color: #e6edf3; }}
    """


class InterlaceSuiteWindow(TaskMixin, QMainWindow):
    def __init__(self, probe=probe_system):
        super().__init__()
        self._probe = probe
        self.cfg = load_config()
        self.scripts_dir = resolve_scripts_dir(self.cfg.get("scripts_dir", ""))
        self._sync_installed_scripts()
        self.info: SystemInfo = self._probe()
        self.paths = SystemPaths()
        self.verification: Verification | None = None

        self.proc = None
        self.askpass_dir: tempfile.TemporaryDirectory | None = None
        self._sudo_pw = ""
        self.ui_scale = max(0.85, min(1.45, float(self.cfg.get("ui_scale", 1.0))))
        self.sudo_keepalive_timer = QTimer(self)
        self.sudo_keepalive_timer.setInterval(45000)
        self.sudo_keepalive_timer.timeout.connect(self._refresh_sudo_timestamp)
        self.task_start_time = 0.0
        self.compiled_objects = 0
        self.current_stage_text = "Idle"
        self.is_kernel_build = False
        self.elapsed_timer = QTimer(self)
        self.elapsed_timer.setInterval(1000)
        self.elapsed_timer.timeout.connect(self._update_elapsed_time)

        self.setWindowTitle(APP_TITLE)
        self.resize(900, 820)
        self.setMinimumSize(620, 480)
        self._build_ui()
        self._restore_selection()
        self._setup_zoom_shortcuts()
        self.apply_ui_scale(self.ui_scale, save=False)
        self.refresh_status()

    # ---- zoom -------------------------------------------------------------------------------
    def _setup_zoom_shortcuts(self):
        for seq in ("Ctrl++", "Ctrl+="):
            QShortcut(QKeySequence(seq), self).activated.connect(lambda: self.apply_ui_scale(self.ui_scale + 0.05))
        QShortcut(QKeySequence("Ctrl+-"), self).activated.connect(lambda: self.apply_ui_scale(self.ui_scale - 0.05))
        QShortcut(QKeySequence("Ctrl+0"), self).activated.connect(lambda: self.apply_ui_scale(1.0))
        self.installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Wheel and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta:
                self.apply_ui_scale(self.ui_scale + (0.05 if delta > 0 else -0.05))
            return True
        return super().eventFilter(obj, event)

    def apply_ui_scale(self, scale: float, save: bool = True):
        self.ui_scale = max(0.85, min(1.45, round(scale, 2)))
        if save:
            self.cfg["ui_scale"] = self.ui_scale
            save_config(self.cfg)
        self.setStyleSheet(stylesheet(self.ui_scale))

    # ---- building blocks (every section is made from these, so the layout cannot drift) -----------
    @staticmethod
    def _card() -> tuple[QFrame, QVBoxLayout]:
        frame = QFrame()
        frame.setObjectName("card")
        frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        box = QVBoxLayout(frame)
        box.setContentsMargins(12, 10, 12, 12)
        box.setSpacing(8)
        return frame, box

    @staticmethod
    def _badge() -> QLabel:
        badge = QLabel()
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        return badge

    @staticmethod
    def _section(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("section")
        return label

    @staticmethod
    def _script_button(script: str, slot) -> QPushButton:
        """The one big button of a step. Its text is the script name, always; its look never changes."""
        btn = QPushButton(script)
        btn.setObjectName("scriptBtn")
        btn.setMinimumHeight(38)
        btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        btn.clicked.connect(slot)
        return btn

    @staticmethod
    def _sub_button(text: str, slot, tip: str) -> QPushButton:
        """The small helper beside a script button: 1-5 words, neutral colour, always to its right."""
        btn = QPushButton(text)
        btn.setObjectName("subBtn")
        btn.setToolTip(tip)
        btn.setMinimumHeight(30)
        btn.clicked.connect(slot)
        return btn

    def _step(
        self, title: str, script_btn: QPushButton, sub_btn: QPushButton, *badges: QLabel,
    ) -> tuple[QFrame, QVBoxLayout]:
        """A step: [title ...... badges] / [ SCRIPT BUTTON | small helper ]. Extra rows go below."""
        frame = QFrame()
        frame.setObjectName("step")
        box = QVBoxLayout(frame)
        box.setContentsMargins(10, 8, 10, 10)
        box.setSpacing(8)
        head = QHBoxLayout()
        head.addWidget(QLabel(f"<b>{title}</b>"), 1)
        for badge in badges:
            head.addWidget(badge, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        box.addLayout(head)
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(script_btn, 3)
        row.addWidget(sub_btn, 1)
        box.addLayout(row)
        return frame, box

    def _make_cell(self, title: str) -> tuple[QFrame, QLabel, QLabel]:
        cell = QFrame()
        cell.setObjectName("cell")
        box = QVBoxLayout(cell)
        box.setContentsMargins(10, 6, 10, 8)
        box.setSpacing(2)
        top = QHBoxLayout()
        label = QLabel(title)
        label.setObjectName("cellTitle")
        badge = self._badge()
        top.addWidget(label, 1)
        top.addWidget(badge, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        box.addLayout(top)
        value = AutoWrapLabel("-")
        value.setObjectName("cellValue")
        value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        box.addWidget(value)
        return cell, value, badge

    @staticmethod
    def _set_badge(badge: QLabel, check: Check, text: str | None = None):
        shown = text or check.short
        badge.setText(f"✓ {shown}" if check.ok else f"⚠ {shown}")
        badge.setToolTip(check.detail)
        badge.setObjectName("badgeOk" if check.ok else "badgeWarn")
        badge.style().unpolish(badge)
        badge.style().polish(badge)

    @staticmethod
    def _fill_combo(combo: QComboBox, options: list[tuple[str, str]]):
        for key, label in options:
            combo.addItem(label, key)

    def _build_ui(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setCentralWidget(scroll)
        content = QWidget()
        content.setObjectName("scrollContent")
        scroll.setWidget(content)
        page = QVBoxLayout(content)
        page.setContentsMargins(14, 12, 14, 14)
        page.setSpacing(10)

        head = QHBoxLayout()
        title = QLabel(APP_TITLE)
        title.setObjectName("title")
        self.zoom_btn = QPushButton("100%")
        self.zoom_btn.setObjectName("subBtn")
        self.zoom_btn.setToolTip("Ctrl+scroll or Ctrl +/- to zoom. Click to reset.")
        self.zoom_btn.clicked.connect(lambda: self.apply_ui_scale(1.0))
        self.refresh_btn = QPushButton("Re-check")
        self.refresh_btn.setObjectName("subBtn")
        self.refresh_btn.clicked.connect(self.refresh_status)
        head.addWidget(title, 1)
        head.addWidget(self.refresh_btn)
        head.addWidget(self.zoom_btn)
        page.addLayout(head)
        self.banner_lbl = AutoWrapLabel()
        page.addWidget(self.banner_lbl)

        self._build_status(page)
        self._build_config(page)
        self._build_actions(page)
        self._build_log(page)

    # ---- 1. System ----------------------------------------------------------------------------
    def _build_status(self, page: QVBoxLayout):
        page.addWidget(self._section("1. System"))
        card, box = self._card()
        self.gpu_grid = QGridLayout()
        self.gpu_grid.setHorizontalSpacing(14)
        self.gpu_grid.setVerticalSpacing(4)
        self.gpu_grid.setColumnStretch(2, 1)
        box.addLayout(self.gpu_grid)
        grid = QGridLayout()
        grid.setSpacing(8)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        # same order as Section 3: EDID, rules, kernel, CRU
        self.cell_profile = self._make_cell("GPU profile")
        self.cell_boot = self._make_cell("Bootloader")
        self.cell_edid = self._make_cell("EDID")
        self.cell_rules = self._make_cell("GPU rules")
        self.cell_kernel = self._make_cell("Kernel")
        self.cell_cru = self._make_cell("Linux CRU")
        cells = (self.cell_profile, self.cell_boot, self.cell_edid, self.cell_rules, self.cell_kernel, self.cell_cru)
        for i, cell in enumerate(cells):
            grid.addWidget(cell[0], i // 2, i % 2)
        box.addLayout(grid)
        page.addWidget(card)

    # ---- 2. Configuration ---------------------------------------------------------------------
    def _build_config(self, page: QVBoxLayout):
        page.addWidget(self._section("2. Configuration"))
        card, box = self._card()
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        grid.setColumnStretch(1, 1)

        self.gpu_combo = NoWheelComboBox()
        self._fill_combo(self.gpu_combo, GPU_PROFILES)
        self.adapter_combo = NoWheelComboBox()
        self._fill_combo(self.adapter_combo, ADAPTER_MODES)
        self.conn_combo = NoWheelComboBox()
        self.edid_edit = QLineEdit()
        self.edid_edit.setPlaceholderText("Default CRT EDID")
        self.edid_edit.setClearButtonEnabled(True)
        browse = QPushButton("Browse")
        browse.setObjectName("subBtn")
        browse.clicked.connect(self.browse_edid)
        edid_row = QHBoxLayout()
        edid_row.setSpacing(6)
        edid_row.addWidget(self.edid_edit, 1)
        edid_row.addWidget(browse)

        for row, (label, widget) in enumerate((
            ("GPU profile", self.gpu_combo), ("Adapter", self.adapter_combo), ("Port", self.conn_combo),
        )):
            grid.addWidget(QLabel(label), row, 0)
            grid.addWidget(widget, row, 1)
        grid.addWidget(QLabel("Custom EDID"), 3, 0)
        grid.addLayout(edid_row, 3, 1)
        box.addLayout(grid)

        self.resolved_lbl = AutoWrapLabel()
        self.resolved_lbl.setObjectName("muted")
        box.addWidget(self.resolved_lbl)
        page.addWidget(card)

    # ---- 3. Actions ---------------------------------------------------------------------------
    def _build_actions(self, page: QVBoxLayout):
        page.addWidget(self._section("3. Actions"))
        card, box = self._card()
        box.setSpacing(10)

        self.step_edid_badge = self._badge()
        self.run_setup_btn = self._script_button("setup-interlace-env.sh", lambda: self.run_setup_env(False))
        self.reload_btn = self._sub_button(
            "Reload EDID", lambda: self.run_setup_env(True), "Reload the EDID into the running kernel (no reboot).",
        )
        step, _ = self._step("EDID & bootloader", self.run_setup_btn, self.reload_btn, self.step_edid_badge)
        box.addWidget(step)

        self.step_rules_badge = self._badge()
        self.step_kernel_badge = self._badge()
        self.run_kernel_btn = self._script_button("fix-interlaced-kernel.sh", lambda: self.run_fix_kernel(False))
        self.rules_btn = self._sub_button(
            "Apply GPU rules", lambda: self.run_fix_kernel(True), "Write the GPU rules for the selected profile only.",
        )
        step, step_box = self._step(
            "Kernel & GPU rules", self.run_kernel_btn, self.rules_btn, self.step_rules_badge, self.step_kernel_badge,
        )
        opts = QHBoxLayout()
        opts.setSpacing(8)
        opts.addWidget(QLabel("Target"))
        self.kernel_combo = NoWheelComboBox()
        self._fill_combo(self.kernel_combo, KERNEL_VERSIONS)
        opts.addWidget(self.kernel_combo, 1)
        self.rdna_chk = QCheckBox("RDNA unlock")
        self.rdna_chk.setToolTip("Patch the AMDGPU driver so RDNA cards can drive DP/HDMI DAC adapters.")
        opts.addWidget(self.rdna_chk)
        step_box.addLayout(opts)
        self.progress_lbl = AutoWrapLabel("Idle")
        self.progress_lbl.setObjectName("muted")
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setFormat("Ready")
        self.progress_bar.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        step_box.addWidget(self.progress_lbl)
        step_box.addWidget(self.progress_bar)
        box.addWidget(step)

        self.step_cru_badge = self._badge()
        self.install_cru_btn = self._script_button("install-linux-cru.sh", self.run_install_cru)
        self.launch_cru_btn = self._sub_button("Launch CRU", self.launch_linux_cru, "Open the Linux CRU editor.")
        step, _ = self._step("Linux CRU", self.install_cru_btn, self.launch_cru_btn, self.step_cru_badge)
        box.addWidget(step)
        page.addWidget(card)

        for widget in (self.gpu_combo, self.adapter_combo, self.conn_combo, self.kernel_combo):
            widget.currentIndexChanged.connect(self.on_selection_changed)
        self.edid_edit.textChanged.connect(self.on_selection_changed)
        self.rdna_chk.stateChanged.connect(self.on_selection_changed)

    # ---- 4. Output ----------------------------------------------------------------------------
    def _build_log(self, page: QVBoxLayout):
        page.addWidget(self._section("4. Output"))
        card, box = self._card()
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(140)
        self.log_view.setStyleSheet(
            "QPlainTextEdit { background-color: #111318; color: #e6edf3; border: 1px solid #2d3440;"
            " border-radius: 6px; padding: 6px; font-family: monospace; }",
        )
        box.addWidget(self.log_view, 1)
        bar = QHBoxLayout()
        self.task_state_lbl = AutoWrapLabel("Idle")
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setObjectName("stopBtn")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_current_task)
        copy_btn = QPushButton("Copy")
        copy_btn.setObjectName("subBtn")
        copy_btn.clicked.connect(self.copy_log)
        clear_btn = QPushButton("Clear")
        clear_btn.setObjectName("subBtn")
        clear_btn.clicked.connect(self.log_view.clear)
        bar.addWidget(self.task_state_lbl, 1)
        for btn in (self.stop_btn, copy_btn, clear_btn):
            bar.addWidget(btn)
        box.addLayout(bar)
        page.addWidget(card, 1)

    # ---- selection ----------------------------------------------------------------------------
    def selection(self) -> Selection:
        return Selection(
            gpu_profile=self.gpu_combo.currentData() or "auto",
            adapter_mode=self.adapter_combo.currentData() or "auto",
            connector=self.conn_combo.currentData() or "auto",
            kernel_version=self.kernel_combo.currentData() or "auto",
            custom_edid=self.edid_edit.text().strip(),
            rdna_patch=self.rdna_chk.isChecked(),
        )

    def _restore_selection(self):
        """Put the saved choices back (the old code reset every dropdown to index 0 on each launch)."""
        self._rebuild_ports()
        for combo, key in (
            (self.gpu_combo, "gpu_profile"), (self.adapter_combo, "adapter_mode"),
            (self.conn_combo, "connector"), (self.kernel_combo, "kernel_version"),
        ):
            idx = combo.findData(self.cfg.get(key, "auto"))
            combo.blockSignals(True)
            combo.setCurrentIndex(max(idx, 0))
            combo.blockSignals(False)
        self.edid_edit.blockSignals(True)
        self.edid_edit.setText(self.cfg.get("edid_path", ""))
        self.edid_edit.blockSignals(False)
        self.rdna_chk.blockSignals(True)
        self.rdna_chk.setChecked(bool(self.cfg.get("include_rdna_patch", True)))
        self.rdna_chk.blockSignals(False)

    def _rebuild_ports(self):
        """Every port is selectable, connected or not, so any adapter/port mix can be applied."""
        previous = self.conn_combo.currentData() or self.cfg.get("connector", "auto")
        self.conn_combo.blockSignals(True)
        self.conn_combo.clear()
        self.conn_combo.addItem("Auto-detect", "auto")
        seen: set[str] = set()
        for port in sorted(self.info.ports, key=lambda p: (p.status != "connected", p.name)):
            seen.add(port.name)
            dot = "●" if port.status == "connected" else "○"
            note = f" · EDID {port.override}" if port.override else ""
            self.conn_combo.addItem(f"{dot} {port.name} ({port.status}){note}", port.name)
        for name in FALLBACK_PORTS:
            if name not in seen:
                self.conn_combo.addItem(f"○ {name} (not detected)", name)
        self.conn_combo.setCurrentIndex(max(self.conn_combo.findData(previous), 0))
        self.conn_combo.blockSignals(False)

    def on_selection_changed(self, *_):
        sel = self.selection()
        self.cfg.update(
            gpu_profile=sel.gpu_profile, adapter_mode=sel.adapter_mode, connector=sel.connector,
            kernel_version=sel.kernel_version, edid_path=sel.custom_edid, include_rdna_patch=sel.rdna_patch,
            scripts_dir=str(self.scripts_dir),
        )
        save_config(self.cfg)
        self.update_view()

    def browse_edid(self):
        path, _ = QFileDialog.getOpenFileName(self, "Custom EDID", str(Path.home()), "EDID (*.bin);;All files (*)")
        if path:
            self.edid_edit.setText(path)

    # ---- view ---------------------------------------------------------------------------------
    def refresh_status(self):
        """Re-read the machine, then redraw everything from it."""
        self.info = self._probe()
        self._fill_gpu_table()
        self._rebuild_ports()
        self.update_view()

    def _fill_gpu_table(self):
        while self.gpu_grid.count():
            item = self.gpu_grid.takeAt(0)
            if (w := item.widget()) is not None:
                w.setParent(None)
                w.deleteLater()
        for col, text in enumerate(("Slot", "ID", "Adapter", "Type")):
            head = QLabel(f"<b>{text}</b>")
            head.setObjectName("muted")
            self.gpu_grid.addWidget(head, 0, col)
        if not self.info.rows:
            self.gpu_grid.addWidget(QLabel("<i>No display controller found</i>"), 1, 0, 1, 4)
        for row, gpu in enumerate(self.info.rows, start=1):
            self.gpu_grid.addWidget(QLabel(f"<code>{html.escape(gpu.slot)}</code>"), row, 0)
            self.gpu_grid.addWidget(QLabel(f"<code>{html.escape(gpu.vendor_dev)}</code>"), row, 1)
            self.gpu_grid.addWidget(AutoWrapLabel(html.escape(gpu.model)), row, 2)
            self.gpu_grid.addWidget(QLabel(f"<b>{html.escape(gpu.arch)}</b>"), row, 3)

    def current(self) -> tuple[Selection, Resolved]:
        sel = self.selection()
        return sel, resolve(sel, self.info)

    def _show_cell(self, cell, check: Check, value: str):
        cell[1].setText(html.escape(value))
        self._set_badge(cell[2], check)

    def update_view(self):
        sel, res = self.current()
        self.verification = ver = verify_all(sel, res, self.info, self.paths)
        port = res.connector or "no port"
        self._show_cell(self.cell_profile, Check(True, "Detected"), f"{res.profile} · {res.adapter} · {port}")
        self._show_cell(self.cell_boot, ver.boot, ver.boot.detail)
        self._show_cell(self.cell_edid, ver.edid, ver.edid.detail or ver.edid.short)
        self._show_cell(self.cell_rules, ver.rules, res.profile)
        self._show_cell(self.cell_kernel, ver.kernel, self.info.kernel)
        self._show_cell(self.cell_cru, ver.cru, "linux-cru" if ver.cru.ok else "not installed")
        self._set_badge(self.step_edid_badge, ver.edid)
        self._set_badge(self.step_rules_badge, ver.rules, "Rules" if ver.rules.ok else "Rules pending")
        self._set_badge(self.step_kernel_badge, ver.kernel)
        self._set_badge(self.step_cru_badge, ver.cru)
        self.resolved_lbl.setText(
            f"Will use: {res.profile} · {res.adapter} · {port} · RDNA unlock {'on' if sel.rdna_patch else 'off'}",
        )
        pending = ver.pending
        self.banner_lbl.setText(
            "<span style='color:#56d364'>✓ All verified</span>" if not pending
            else f"<span style='color:#e3b341'>⚠ Pending: {', '.join(pending)}</span>",
        )
        self._set_button_state()

    def _busy(self) -> bool:
        return self._task_active

    def _set_button_state(self):
        idle = not self._busy()
        for btn in (
            self.run_setup_btn, self.reload_btn, self.run_kernel_btn, self.rules_btn,
            self.install_cru_btn, self.launch_cru_btn,
        ):
            btn.setEnabled(idle)
        self.stop_btn.setEnabled(not idle)

    def set_busy(self, busy: bool):
        """Lock the action buttons and enable Stop for exactly as long as a task runs."""
        self._task_active = busy
        self._set_button_state()
        if not busy:
            self.update_view()

    # ---- the three scripts --------------------------------------------------------------------
    def _sync_installed_scripts(self) -> list[str]:
        """Heal ~/.local/share/linux-interlace-suite from every known suite directory (see interlace_manifest)."""
        home = Path.home()
        user_share = home / ".local" / "share" / "linux-interlace-suite"
        user_bin = home / ".local" / "bin" / "linux-interlace-suite"
        copied: list[str] = []
        try:
            sources = manifest.search_dirs(Path(__file__).resolve().parent, home)
            sources.insert(0, self.scripts_dir)
            copied = manifest.sync_suite(user_share, sources)
            src_py = self.scripts_dir / "linux-interlace-suite.py"
            if src_py.is_file() and src_py.resolve() != user_bin.resolve():
                user_bin.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src_py, user_bin)
                user_bin.chmod(0o755)
        except OSError:
            logger.warning("could not sync the suite into %s", user_share, exc_info=True)
        return copied

    def _ensure_suite_complete(self) -> bool:
        self._sync_installed_scripts()
        self.scripts_dir = resolve_scripts_dir(str(self.scripts_dir))
        missing = manifest.missing_files(self.scripts_dir)
        if not missing:
            return True
        QMessageBox.critical(
            self, "Incomplete install",
            f"{self.scripts_dir} is missing:\n  " + "\n  ".join(missing) + "\n\nReinstall the suite.",
        )
        return False

    def command_for(self, script: str, args: list[str]) -> list[str]:
        return ["bash", str(self.scripts_dir / script), *args]

    def _launch(self, title: str, script: str, args: list[str]):
        if not self._ensure_suite_complete():
            return
        self.start_script_process(title, self.command_for(script, args))

    def run_setup_env(self, live_only: bool = False):
        sel, res = self.current()
        try:
            args = setup_args(sel, res, live_only=live_only)
        except SelectionError as exc:
            QMessageBox.warning(self, "Cannot run", str(exc))
            return
        self._launch("setup-interlace-env.sh --live-only" if live_only else "setup-interlace-env.sh",
                     "setup-interlace-env.sh", args)

    def run_fix_kernel(self, config_only: bool = False):
        sel, res = self.current()
        args = kernel_args(sel, res, config_only=config_only)
        self._launch("fix-interlaced-kernel.sh --config-only" if config_only else "fix-interlaced-kernel.sh",
                     "fix-interlaced-kernel.sh", args)

    def run_install_cru(self):
        self._launch("install-linux-cru.sh", "install-linux-cru.sh", [])

    def launch_linux_cru(self):
        for candidate in (
            Path.home() / ".local" / "bin" / "linux-cru", Path("/usr/local/bin/linux-cru"),
            shutil.which("linux-cru"),
        ):
            if candidate and Path(candidate).exists():
                subprocess.Popen([str(candidate)], start_new_session=True)
                self.append_log(f"\n>>> Launched {candidate}\n")
                return
        if QMessageBox.question(self, "Linux CRU", "Linux CRU is not installed. Install it now?") == (
            QMessageBox.StandardButton.Yes
        ):
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
