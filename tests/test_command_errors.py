"""A failing required command must give a short message and a distinct exit code, never a traceback."""

import sys
from pathlib import Path

import pytest

import interlace_apply_rules
import interlace_runner
from conftest import LSPCI_GCN_ONLY, build_host
from interlace_runner import CommandError, Runner


def test_failed_required_command_raises_commanderror_with_last_stderr_line():
    r = Runner(is_root=True, interactive=False)
    with pytest.raises(CommandError, match=r"exit 3.*boom"):
        r.run([sys.executable, "-c", "import sys; sys.stderr.write('x\\nboom\\n'); sys.exit(3)"])


def test_missing_required_command_raises_commanderror():
    with pytest.raises(CommandError, match="command not found: definitely-not-a-real-command"):
        Runner(is_root=True, interactive=False).run(["definitely-not-a-real-command"])


def test_ok_to_fail_returns_the_result_instead_of_raising():
    r = Runner(is_root=True, interactive=False)
    assert r.run([sys.executable, "-c", "import sys; sys.exit(4)"], ok_to_fail=True).returncode == 4
    assert r.run(["definitely-not-a-real-command"], ok_to_fail=True).returncode == 127


def test_cli_reports_command_failure_with_exit_3(sandbox, capsys, monkeypatch):
    root, paths = sandbox
    host, _ = build_host(root, paths, lspci=LSPCI_GCN_ONLY, tools=("dracut",))

    def fail(*_a, **_k):
        raise CommandError("command failed (exit 1): sudo dracut --regenerate-all --force")

    monkeypatch.setattr(interlace_apply_rules, "rebuild_initramfs", fail)
    assert interlace_apply_rules.main(["--gpu-profile", "gcn-single"], host=host) == 3
    err = capsys.readouterr().err
    assert err.startswith("ERROR: command failed")
    assert "Traceback" not in err


def test_runner_has_a_single_subprocess_entry_point():
    """Within interlace_runner, subprocesses are only created in Runner._exec (so dry-run/tests can intercept)."""
    source = Path(interlace_runner.__file__).read_text(encoding="utf-8")
    assert source.count("subprocess.run(") == 1
    assert "subprocess.Popen" not in source
