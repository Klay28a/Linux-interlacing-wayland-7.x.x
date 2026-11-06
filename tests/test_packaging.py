"""Packaging consistency: every shipped file is listed, checksummed, installed and present."""

import ast
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PKGBUILD = ROOT / "PKGBUILD"


def _bash_array(name: str) -> list[str]:
    """Evaluate a PKGBUILD array with bash (real parsing, no regex guessing)."""
    script = f'source "{PKGBUILD}" >/dev/null 2>&1; printf "%s\\n" "${{{name}[@]}}"'
    res = subprocess.run(["bash", "-c", script], check=True, text=True, capture_output=True)
    return [line for line in res.stdout.splitlines() if line]


def test_one_checksum_per_source():
    assert len(_bash_array("sha256sums")) == len(_bash_array("source"))


def test_every_source_exists_in_repo():
    missing = [s for s in _bash_array("source") if not (ROOT / s).is_file()]
    assert missing == []


def test_every_python_module_is_installed_by_package():
    text = PKGBUILD.read_text(encoding="utf-8")
    sources = [s for s in _bash_array("source") if s.endswith(".py")]
    for src in sources:
        stem = src[:-3]
        assert src in text
        installed_explicitly = f'"$srcdir/{src}"' in text
        installed_in_loop = re.search(r"for mod in[^;]*\b" + re.escape(stem) + r"\b", text, re.DOTALL) is not None
        assert installed_explicitly or installed_in_loop, f"{src} is a source but package() never installs it"


def test_installer_and_gui_sync_lists_cover_all_modules():
    modules = sorted(p.name for p in ROOT.glob("interlace_*.py")) + ["linux_cru.py"]
    installer = (ROOT / "install-interlace-suite.sh").read_text(encoding="utf-8")
    gui = (ROOT / "linux-interlace-suite.py").read_text(encoding="utf-8")
    for mod in modules:
        assert mod in installer, f"install-interlace-suite.sh does not install {mod}"
        assert f'"{mod}"' in gui, f"GUI _sync_installed_scripts does not copy {mod}"
        assert f"'{mod}'" in PKGBUILD.read_text(encoding="utf-8"), f"PKGBUILD source=() lacks {mod}"


def _import_closure(module: str) -> set[str]:
    """Every interlace_* module that ``module`` imports, directly or transitively."""
    seen: set[str] = set()
    todo = [module]
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        tree = ast.parse((ROOT / f"{name}.py").read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("interlace_"):
                todo.append(node.module)
            elif isinstance(node, ast.Import):
                todo += [a.name for a in node.names if a.name.startswith("interlace_")]
    return seen


def test_standalone_cru_installer_ships_everything_the_apply_buttons_need():
    """Regression: installing only linux-cru left its Apply buttons without interlace_apply_edid.py."""
    installer = (ROOT / "install-linux-cru.sh").read_text(encoding="utf-8")
    missing = [f"{m}.py" for m in sorted(_import_closure("interlace_apply_edid")) if f"{m}.py" not in installer]
    assert missing == []


def test_every_module_imported_by_a_script_entry_point_is_packaged():
    packaged = PKGBUILD.read_text(encoding="utf-8")
    entry_points = ("interlace_setup", "interlace_apply_rules", "interlace_apply_edid", "interlace_pkgbuild")
    needed = set().union(*(_import_closure(e) for e in entry_points))
    assert [m for m in sorted(needed) if f"'{m}.py'" not in packaged] == []


@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="shellcheck not installed")
def test_all_shell_scripts_pass_shellcheck():
    scripts = sorted(str(p) for p in ROOT.glob("*.sh"))
    subprocess.run(["shellcheck", *scripts], check=True, text=True, capture_output=True)
