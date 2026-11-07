"""Fixtures for the offscreen Qt window tests: no script ever runs and the machine is a mock PC."""

import importlib.util
import os
import sys
from pathlib import Path

import pytest

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
