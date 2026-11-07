"""A mock PC whose files really change when the setup / rules code runs.

"Applying" runs the real ``interlace_setup`` / ``interlace_apply_rules`` against the sandbox and then writes what
the fake runner captured to disk, so a badge that turns green did so because the scripts' own output satisfied it.
"""

from pathlib import Path

import interlace_apply_rules
import interlace_setup
from interlace_selection import Resolved, Selection, resolve
from interlace_sysinfo import SystemInfo, collect_system_info
from interlace_verify import Verification, verify_all
from test_fixtures_layouts import setup_pc


class Machine:
    def __init__(self, pc, tmp_path):
        self.pc, self.root = pc, tmp_path
        self.host, self.runner, self.paths = setup_pc(pc, tmp_path)
        self.present = set(pc["which"])

    def write_installed(self) -> None:
        """Do on disk what the (recording) runner was asked to: install files, then ``rm -f`` removals."""
        for name, data in self.runner.installed.items():
            target = Path(name)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        self.runner.installed.clear()
        for argv in self.runner.executed:
            if "rm" in argv and "-f" in argv:
                Path(argv[-1]).unlink(missing_ok=True)
        self.runner.executed.clear()

    def info(self) -> SystemInfo:
        return collect_system_info(
            self.paths, self.pc["lspci"], lambda n: n if n in self.present else None, self.pc["uname_r"],
        )

    def look(self, sel: Selection) -> tuple[Resolved, Verification, SystemInfo]:
        info = self.info()
        res = resolve(sel, info)
        return res, verify_all(sel, res, info, self.paths), info

    def run_setup(self, sel: Selection) -> None:
        res, _, _ = self.look(sel)
        argv = ["--gpu-profile", res.profile, "--adapter-mode", res.adapter, "--connector", res.connector]
        if sel.custom_edid:
            argv += ["--edid", sel.custom_edid]
        assert interlace_setup.main(argv, host=self.host) == 0
        self.write_installed()

    def apply_rules(self, sel: Selection) -> None:
        res, _, info = self.look(sel)
        interlace_apply_rules.apply_profile(self.host, res.profile, list(info.gpus))
        self.write_installed()
