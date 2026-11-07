"""Task running for the GUI: sudo askpass, the QProcess, live progress parsing and the output log.

Mixed into ``InterlaceSuiteWindow``. The window supplies ``log_view``, ``progress_bar``, ``progress_lbl``,
``task_state_lbl``, ``scripts_dir``, ``elapsed_timer``, ``sudo_keepalive_timer`` and the hooks
``set_busy`` / ``refresh_status``.
"""

import contextlib
import html
import os
import re
import signal
import subprocess
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

from PyQt6.QtCore import QProcess, QProcessEnvironment, QTimer
from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import QApplication, QInputDialog, QLineEdit, QMessageBox

PROC = Path("/proc")
Tree = list[tuple[int, int]]  # (pid, start time); children come before their parent


def _stat_fields(proc_root: Path, pid: int) -> tuple[int, int] | None:
    """``(ppid, starttime)`` from ``<proc>/<pid>/stat``. The command name may hold spaces and ')'."""
    try:
        text = (proc_root / str(pid) / "stat").read_text(encoding="utf-8", errors="replace")
        fields = text.rsplit(")", 1)[1].split()
        return int(fields[1]), int(fields[19])
    except (OSError, IndexError, ValueError):
        return None


def process_tree(root_pid: int, proc_root: Path = PROC) -> Tree:
    """``root_pid`` and every descendant, deepest first, each with its start time (to detect pid reuse)."""
    children: dict[int, list[int]] = {}
    starts: dict[int, int] = {}
    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        info = _stat_fields(proc_root, int(entry.name))
        if info is not None:
            starts[int(entry.name)] = info[1]
            children.setdefault(info[0], []).append(int(entry.name))
    if root_pid not in starts:
        return []
    order: Tree = []
    seen: set[int] = set()

    def walk(pid: int) -> None:
        seen.add(pid)
        for child in sorted(children.get(pid, [])):
            if child not in seen:
                walk(child)
        order.append((pid, starts[pid]))

    walk(root_pid)
    return order


def signal_tree(
    tree: Tree, sig: int, proc_root: Path = PROC, kill: Callable[[int, int], None] = os.kill,
) -> None:
    """Send ``sig`` to each process that is still the one that was listed (a reused pid is left alone)."""
    for pid, start in tree:
        info = _stat_fields(proc_root, pid)
        if info is None or info[1] != start:
            continue
        with contextlib.suppress(ProcessLookupError, PermissionError):
            kill(pid, sig)


class TaskMixin:
    _task_active = False  # explicit, so the buttons never depend on QProcess state timing
    _stopping = False

    def append_log(self, text: str):
        self.log_view.moveCursor(QTextCursor.MoveOperation.End)
        self.log_view.insertPlainText(text)
        self.log_view.moveCursor(QTextCursor.MoveOperation.End)

    def copy_log(self):
        QApplication.clipboard().setText(self.log_view.toPlainText())

    def _cleanup_askpass(self):
        self.sudo_keepalive_timer.stop()
        if self.askpass_dir is not None:
            with contextlib.suppress(OSError, ValueError):
                self.askpass_dir.cleanup()
            self.askpass_dir = None

    def _refresh_sudo_timestamp(self):
        if self.askpass_dir is None:
            return
        askpass_bin = Path(self.askpass_dir.name) / "askpass.sh"
        env = dict(os.environ)
        env["SUDO_ASKPASS"] = str(askpass_bin)
        subprocess.run(
            ["/usr/bin/sudo", "-A", "-v"],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
        )

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
                check=False,
            )
            if verify_cached.returncode == 0:
                need_prompt = False

        if need_prompt:
            while True:
                pw, ok = QInputDialog.getText(
                    self,
                    "Password",
                    "sudo password:",
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
                    check=False,
                )
                if verify.returncode == 0:
                    self._sudo_pw = pw
                    break
                QMessageBox.warning(self, "Wrong password", "Try again.")

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
            f"    [ \"$a\" = \"-k\" ] || [ \"$a\" = \"-A\" ] && continue\n"
            f"    args+=(\"$a\")\n"
            f"done\n"
            f"exec /usr/bin/sudo -A \"${{args[@]}}\"\n",
            encoding="utf-8",
        )
        os.chmod(sudo_wrap, 0o700)

        self.sudo_keepalive_timer.start()
        return str(tdir)

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
        self.progress_bar.setValue(pct)
        self.progress_bar.setFormat(bar_txt)
        self.progress_lbl.setText(f"{html.escape(stage)}  ·  {el}")

    def _reset_progress(self, status_msg: str = "Idle"):
        self.task_start_time = 0.0
        self.compiled_objects = 0
        self.current_stage_text = "Idle — Ready"
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("Ready")
        self.progress_lbl.setText(status_msg)

    def _update_elapsed_time(self):
        if self.proc is not None and self.proc.state() != QProcess.ProcessState.NotRunning:
            self._set_progress(self.progress_bar.value(), self.current_stage_text)

    def _parse_progress_from_output(self, data: str):
        cur = self.progress_bar.value()
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
                cur = self.progress_bar.value()
                continue

            if not self.is_kernel_build:
                continue

            if "Retrieving sources" in line or "Validating source" in line:
                self._set_progress(max(cur, 20), "Validating sources")
            elif "Extracting sources" in line:
                self._set_progress(max(cur, 23), "Extracting source")
            elif "Starting prepare()" in line or "Applying patch" in line:
                self._set_progress(max(cur, 26), line.lstrip('=> '))
            elif "Starting build()" in line:
                self._set_progress(max(cur, 28), "Compiling")
            elif re.match(r"^(CC|CC \[M\]|LD|LD \[M\]|AR|AS|HOSTCC|HOSTLD|OBJCOPY|BTF|GEN)\s+\S+", line):
                self.compiled_objects += 1
                parts = line.split(None, 2)
                target = parts[-1] if parts else ""
                if "vmlinux" in target:
                    self._set_progress(max(cur, 83), f"Linking {target}")
                else:
                    est = 28 + min(54, int(54 * self.compiled_objects / 4200))
                    short_t = target if len(target) <= 48 else "..." + target[-45:]
                    self._set_progress(
                        max(cur, est),
                        f"Compiling ({self.compiled_objects:,}): {short_t}",
                    )
            elif "MODPOST" in line:
                self._set_progress(max(cur, 85), "MODPOST")
            elif "Entering fakeroot" in line or "Starting package" in line:
                self._set_progress(max(cur, 88), "Packaging")
            elif "Creating package" in line:
                self._set_progress(max(cur, 92), line.lstrip('=> '))
            elif "Installing package" in line or "installing linux-cachyos" in line.lower():
                self._set_progress(max(cur, 95), "Installing packages")
            cur = self.progress_bar.value()

    def start_script_process(self, title: str, cmd: list[str]):
        if self._busy():
            QMessageBox.information(self, "Busy", "A task is already running.")
            return

        auth_dir = self._prepare_sudo_auth()
        if auth_dir is None:
            return

        self._stopping = False
        self.task_start_time = time.time()
        self.compiled_objects = 0
        self.is_kernel_build = ("fix-interlaced-kernel.sh" in " ".join(cmd)) and ("--config-only" not in cmd)
        self._set_progress(2, f"Starting {title}")
        self.elapsed_timer.start()

        self.append_log(f"\n{'=' * 72}\n>>> Starting: {title}\n>>> Command : {' '.join(cmd)}\n{'=' * 72}\n")
        self.task_state_lbl.setText(f"Running: {title}")
        self.set_busy(True)

        self.proc = QProcess(self)
        self.proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.proc.setWorkingDirectory(str(self.scripts_dir))

        env = QProcessEnvironment.systemEnvironment()
        env.insert("SUDO_ASKPASS", str(Path(auth_dir) / "askpass.sh"))
        env.insert("PATH", f"{auth_dir}:{os.environ.get('PATH', '/usr/local/bin:/usr/bin:/bin')}")
        self.proc.setProcessEnvironment(env)

        self.proc.readyReadStandardOutput.connect(self._on_proc_output)
        self.proc.finished.connect(lambda code, status: self._on_proc_finished(title, code, status))
        self.proc.errorOccurred.connect(lambda error: self._on_proc_error(title, error))
        self.proc.start(cmd[0], cmd[1:])
        # Nothing is ever typed into a task: close its stdin so a stray prompt gets EOF instead of
        # leaving the GUI waiting forever on a question nobody can answer.
        self.proc.closeWriteChannel()

    def _on_proc_output(self):
        if self.proc is None:
            return
        data = bytes(self.proc.readAllStandardOutput()).decode("utf-8", errors="replace")
        if data:
            self.append_log(data)
            self._parse_progress_from_output(data)

    def _end_task(self) -> str:
        """Common clean-up once a task is over; returns the elapsed time text."""
        self.elapsed_timer.stop()
        elapsed = self._format_elapsed()
        self._cleanup_askpass()
        self.set_busy(False)
        self.refresh_status()
        return elapsed

    def _on_proc_finished(self, title: str, code: int, _status):
        elapsed = self._end_task()
        if self._stopping:
            self._stopping = False
            self._reset_progress("Stopped")
            self.task_state_lbl.setText(f"Stopped: {title}")
            self.append_log(f"\n>>> [STOPPED] {title}\n")
        elif code == 0:
            self._reset_progress(f"Done in {elapsed}")
            self.task_state_lbl.setText(f"Done: {title}")
            self.append_log(f"\n>>> [SUCCESS] {title} finished (exit code 0).\n")
        else:
            self._reset_progress(f"Failed (exit {code})")
            self.task_state_lbl.setText(f"Failed: {title} (exit {code})")
            self.append_log(f"\n>>> [FAILED] {title} exited with code {code}.\n")
            QMessageBox.warning(self, "Task failed", f"{title} exited with code {code}.\nSee the output log.")

    def _on_proc_error(self, title: str, error) -> None:
        """A task that never started emits no ``finished``: without this the window would stay locked."""
        if error != QProcess.ProcessError.FailedToStart:
            return
        reason = self.proc.errorString() if self.proc is not None else "unknown error"
        self._end_task()
        self._reset_progress("Failed")
        self.task_state_lbl.setText(f"Failed: {title}")
        self.append_log(f"\n>>> [FAILED] {title}: could not start ({reason}).\n")
        QMessageBox.warning(self, "Task failed", f"{title} could not start:\n{reason}")

    def stop_current_task(self):
        """Stop the task and everything it spawned (makepkg, compilers...), not just the top-level shell."""
        if not self._busy() or self.proc is None or self.proc.state() == QProcess.ProcessState.NotRunning:
            return
        self._stopping = True
        self.append_log("\n>>> Stopping...\n")
        pid = int(self.proc.processId())
        tree = process_tree(pid)
        signal_tree(tree, signal.SIGTERM)
        QTimer.singleShot(3000, lambda: self._force_stop(pid, tree))

    def _force_stop(self, pid: int, tree: Tree) -> None:
        """Whatever ignored SIGTERM gets SIGKILL (children first). Does nothing if the task already ended."""
        proc = self.proc
        if proc is None or proc.state() == QProcess.ProcessState.NotRunning or int(proc.processId()) != pid:
            return
        signal_tree(tree + [t for t in process_tree(pid) if t not in tree], signal.SIGKILL)
        proc.kill()
