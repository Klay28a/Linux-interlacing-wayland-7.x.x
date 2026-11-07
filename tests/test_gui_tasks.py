"""The window's task runner with REAL QProcess children (harmless shell commands).

Covers the reported bug (Stop greyed out while a task runs) plus Stop ending the whole process tree,
a user Stop not being reported as a failure, and a task that cannot start not locking the window.
"""

import contextlib
import os
import time
from pathlib import Path

import pytest

pytest.importorskip("PyQt6.QtWidgets")


def wait_for(qapp, condition, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        qapp.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return False


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    try:  # a zombie still answers kill(0) but is finished
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0] != "Z"
    except OSError:
        return False


def action_buttons(w):
    return (w.run_setup_btn, w.reload_btn, w.run_kernel_btn, w.rules_btn, w.install_cru_btn, w.launch_cru_btn)


@pytest.fixture
def live(live_window):
    return live_window


def test_stop_is_enabled_and_actions_are_locked_while_a_task_runs(live, qapp):
    live.start_script_process("t", ["bash", "-c", "sleep 30"])
    assert live.stop_btn.isEnabled(), "Stop must be usable the moment a task starts"
    assert not any(b.isEnabled() for b in action_buttons(live))
    live.stop_btn.click()
    assert wait_for(qapp, lambda: not live._busy())
    assert wait_for(qapp, lambda: live.run_setup_btn.isEnabled())
    assert all(b.isEnabled() for b in action_buttons(live))
    assert not live.stop_btn.isEnabled()


def test_stop_stays_enabled_across_a_dropdown_change_during_a_run(live, qapp):
    live.start_script_process("t", ["bash", "-c", "sleep 30"])
    live.adapter_combo.setCurrentIndex(1)
    assert live.stop_btn.isEnabled()
    assert not live.run_kernel_btn.isEnabled()


def test_stop_ends_the_whole_process_tree(live, qapp, tmp_path):
    """Terminating only the top-level bash used to leave makepkg/compilers running."""
    pidfile = tmp_path / "child.pid"
    live.start_script_process("t", ["bash", "-c", f"sleep 300 & echo $! > {pidfile}; wait"])
    assert wait_for(qapp, lambda: pidfile.exists() and pidfile.read_text().strip())
    child = int(pidfile.read_text())
    try:
        assert alive(child)
        live.stop_btn.click()
        assert wait_for(qapp, lambda: not alive(child), 8), "the child process survived Stop"
    finally:
        with contextlib.suppress(OSError):
            os.kill(child, 9)


def test_a_user_stop_is_not_reported_as_a_failure(live, qapp):
    live.start_script_process("my task", ["bash", "-c", "sleep 30"])
    live.stop_btn.click()
    assert wait_for(qapp, lambda: live.task_state_lbl.text().startswith("Stopped"))
    assert live.dialogs == []
    assert "[STOPPED]" in live.log_view.toPlainText()
    assert "[FAILED]" not in live.log_view.toPlainText()


def test_a_failing_task_is_reported_and_unlocks_the_window(live, qapp):
    live.start_script_process("boom", ["bash", "-c", "echo oops; exit 3"])
    assert wait_for(qapp, lambda: live.task_state_lbl.text().startswith("Failed"))
    assert "exit 3" in live.task_state_lbl.text()
    assert len(live.dialogs) == 1
    assert "oops" in live.log_view.toPlainText()
    assert all(b.isEnabled() for b in action_buttons(live))


def test_a_task_that_cannot_start_does_not_lock_the_window(live, qapp):
    live.start_script_process("missing", ["/nonexistent/definitely-not-here"])
    assert wait_for(qapp, lambda: live.run_setup_btn.isEnabled())
    assert not live.stop_btn.isEnabled()
    assert live.task_state_lbl.text().startswith("Failed")
    assert "could not start" in live.log_view.toPlainText()


def test_a_successful_task_streams_output_and_unlocks_the_window(live, qapp):
    live.start_script_process("ok", ["bash", "-c", "echo '==> [1/2] first'; echo '==> [2/2] second'"])
    assert wait_for(qapp, lambda: live.task_state_lbl.text().startswith("Done"))
    text = live.log_view.toPlainText()
    assert "==> [1/2] first" in text
    assert "[SUCCESS]" in text
    assert live.dialogs == []
    assert all(b.isEnabled() for b in action_buttons(live))


def test_progress_markers_move_the_bar(live):
    live.is_kernel_build = False
    live._parse_progress_from_output("==> [2/4] halfway\n")
    assert live.progress_bar.value() == 45
    live.is_kernel_build = True
    live._parse_progress_from_output("==> [6/6] sync\n")
    assert live.progress_bar.value() == 97
