"""Fixtures for the offscreen Qt window tests: no script ever runs and the machine is a mock PC."""

import importlib.util
import os
import sys
from pathlib import Path

import pytest
from PyQt6.QtCore import QEvent

from conftest import make_paths, materialize_fixture
from interlace_sysinfo import collect_system_info

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
SCRIPT_NAMES = ("setup-interlace-env.sh", "fix-interlaced-kernel.sh", "install-linux-cru.sh")


@pytest.fixture(scope="session")
def gui_module():
    pytest.importorskip("PyQt6.QtWidgets")
    spec = importlib.util.spec_from_file_location("suite_gui", ROOT / "linux-interlace-suite.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["suite_gui"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def qapp(gui_module):
    return gui_module.QApplication.instance() or gui_module.QApplication([])


@pytest.fixture(scope="session")
def cru():
    """The Linux CRU module, loaded by path (it is a script, not a package)."""
    pytest.importorskip("PyQt6.QtWidgets")
    spec = importlib.util.spec_from_file_location("linux_cru_under_test", ROOT / "linux_cru.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["linux_cru_under_test"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def app(cru):
    from PyQt6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture
def make_dialog(cru, app):
    """Factory for the Detailed Resolution dialog (Manual mode by default); every dialog is closed afterwards."""
    made = []

    def make(width=1600, height=1200, hz=85.0, interlaced=False, preset="Manual", parent=None):
        base = cru.calculate_timings("CVT Standard", width, height, hz, interlaced)
        dlg = cru.DTDEditorDialog(parent, base)
        dlg.preset_combo.setCurrentText(preset)
        dlg.show()
        app.processEvents()
        made.append(dlg)
        return dlg

    yield make
    for dlg in made:
        discard(app, dlg)


def discard(app, widget):
    """Close a top-level widget and really delete it, so a later global restyle never walks a dead one."""
    widget.close()
    widget.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def type_into(app, widget, text, then_tab=True):
    """Type ``text`` into a spin box with real key events, then Tab away (commit) unless ``then_tab`` is False."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest

    widget.setFocus()
    widget.selectAll()
    app.processEvents()
    QTest.keyClicks(widget, text)
    if then_tab:
        QTest.keyClick(widget, Qt.Key.Key_Tab)
    app.processEvents()


def click_radio(app, radio):
    radio.click()
    app.processEvents()


def make_window(gui_module, pc, tmp_path, monkeypatch):
    """The real window on a mock PC, with its config and HOME inside ``tmp_path``. Scripts are NOT stubbed here."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(gui_module, "CONFIG_DIR", home / ".config" / "suite")
    monkeypatch.setattr(gui_module, "CONFIG_FILE", home / ".config" / "suite" / "config.json")
    paths = make_paths(tmp_path)
    materialize_fixture(pc, tmp_path)
    present = set(pc["which"])

    def probe():
        return collect_system_info(paths, pc["lspci"], lambda n: n if n in present else None, pc["uname_r"])

    win = gui_module.InterlaceSuiteWindow(probe=probe)
    win.paths = paths
    win.scripts_dir = ROOT
    monkeypatch.setattr(win, "_ensure_suite_complete", lambda: True)
    win.refresh_status()
    return win


@pytest.fixture
def window(gui_module, qapp, pc, tmp_path, monkeypatch):
    """Window whose scripts are replaced by a recorder: ``window.launched`` lists (title, command)."""
    win = make_window(gui_module, pc, tmp_path, monkeypatch)
    win.launched = []
    monkeypatch.setattr(win, "start_script_process", lambda title, cmd: win.launched.append((title, cmd)))
    yield win
    win.close()


@pytest.fixture
def live_window(gui_module, qapp, pc, tmp_path, monkeypatch):
    """Window with the REAL task runner (no password prompt, no modal dialogs); children are killed at teardown."""
    win = make_window(gui_module, pc, tmp_path, monkeypatch)
    auth = tmp_path / "auth"
    auth.mkdir()
    monkeypatch.setattr(win, "_prepare_sudo_auth", lambda: str(auth))
    win.dialogs = []
    for name in ("warning", "information"):
        monkeypatch.setattr(gui_module.QMessageBox, name, staticmethod(lambda *a, **_k: win.dialogs.append(a[1:])))
    yield win
    if win.proc is not None and win.proc.state() != win.proc.ProcessState.NotRunning:
        win.proc.kill()
        win.proc.waitForFinished(3000)
    win.close()
