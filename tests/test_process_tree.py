"""process_tree / signal_tree: find and signal a task's descendants (tested on a fake /proc, no real processes)."""

import signal
from pathlib import Path

import pytest

pytest.importorskip("PyQt6.QtWidgets")

from interlace_gui_tasks import process_tree, signal_tree


def fake_proc(root: Path, procs: dict[int, tuple[int, int]]) -> Path:
    """``procs`` maps pid -> (ppid, starttime). The comm field deliberately contains spaces and a ')'."""
    for pid, (ppid, start) in procs.items():
        d = root / str(pid)
        d.mkdir(parents=True)
        rest = ["S", str(ppid), *["0"] * 17, str(start), *["0"] * 3]
        (d / "stat").write_text(f"{pid} (odd name) x) {' '.join(rest)}\n")
    (root / "self").mkdir()
    (root / "cpuinfo").write_text("not a process\n")
    return root


TREE = {10: (1, 100), 11: (10, 101), 12: (11, 102), 13: (10, 103), 20: (1, 200)}


def test_process_tree_lists_descendants_deepest_first_and_skips_unrelated(tmp_path):
    proc = fake_proc(tmp_path / "proc", TREE)
    tree = process_tree(10, proc)
    assert [pid for pid, _ in tree] == [12, 11, 13, 10]
    assert 20 not in [pid for pid, _ in tree]


def test_process_tree_of_a_missing_process_is_empty(tmp_path):
    assert process_tree(999, fake_proc(tmp_path / "proc", TREE)) == []


def test_signal_tree_signals_each_process_once_and_children_first(tmp_path):
    proc = fake_proc(tmp_path / "proc", TREE)
    sent: list[tuple[int, int]] = []
    signal_tree(process_tree(10, proc), signal.SIGTERM, proc, kill=lambda pid, sig: sent.append((pid, sig)))
    assert sent == [(12, signal.SIGTERM), (11, signal.SIGTERM), (13, signal.SIGTERM), (10, signal.SIGTERM)]


def test_signal_tree_skips_a_pid_that_was_reused_by_another_process(tmp_path):
    proc = fake_proc(tmp_path / "proc", TREE)
    tree = process_tree(10, proc)
    fake_proc(tmp_path / "later", {**TREE, 12: (1, 9999)})  # same pid, different start time
    sent: list[int] = []
    signal_tree(tree, signal.SIGKILL, tmp_path / "later", kill=lambda pid, _sig: sent.append(pid))
    assert 12 not in sent
    assert {11, 13, 10} <= set(sent)


def test_signal_tree_ignores_processes_it_may_not_signal(tmp_path):
    proc = fake_proc(tmp_path / "proc", TREE)

    def deny(_pid, _sig):
        raise PermissionError

    signal_tree(process_tree(10, proc), signal.SIGTERM, proc, kill=deny)  # must not raise
