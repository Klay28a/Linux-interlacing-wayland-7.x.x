"""interlace_patches: choose the 15kHz patch set that really applies, using a mock patch repository."""

from pathlib import Path

import pytest

import interlace_patches as ip

NUMS = ("01", "02", "03", "04", "05", "06", "07", "08", "09")
FULL = {s: NUMS for s in ("linux-6.12", "linux-7.2", "linux-7.3", "linux-next")}


def make_repo(tmp_path: Path, layout: dict[str, tuple[str, ...]]) -> Path:
    repo = tmp_path / "linux_kernel_15khz"
    for series, numbers in layout.items():
        for n in numbers:
            f = repo / series / f"{n}_{series}.patch"
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(f"--- a/f{n}\n+++ b/dir/f{n}\n", encoding="utf-8")
    return repo


def test_candidate_series_orders_exact_then_older_then_newer() -> None:
    avail = ["linux-6.1", "linux-6.6", "linux-6.12", "linux-6.18", "linux-7.2", "linux-7.3", "linux-next"]
    assert ip.candidate_series(avail, "linux-6.12", "6.12") == [
        "linux-6.12", "linux-6.6", "linux-6.1", "linux-6.18", "linux-7.2", "linux-7.3",
    ]
    # linux-next is preferred when asked for, and is never offered as a numeric fallback for another series
    order = ip.candidate_series(avail, "linux-next", "99.99")
    assert order[:2] == ["linux-next", "linux-7.3"]
    assert "linux-next" not in ip.candidate_series(avail, "linux-7.3", "7.3")[1:]
    # sorted by version, not lexically: 6.6 sits below 6.12
    assert ip.candidate_series(["linux-6.6", "linux-6.12"], "linux-8.0", "8.0") == ["linux-6.12", "linux-6.6"]


def test_pick_unverified_uses_only_the_preferred_series(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, {"linux-6.1": ("01", "02", "03", "04", "05"), "linux-7.3": NUMS})
    got = ip.pick_unverified(repo, ["linux-6.1", "linux-7.3"])
    assert [c.number for c in got.chosen] == ["01", "02", "03", "04", "05"], "6.1 has no 07/08/09: not borrowed"
    assert {c.series for c in got.chosen} == {"linux-6.1"}


def test_preferred_series_is_used_when_everything_applies(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, FULL)
    applied: list[str] = []
    got = ip.resolve_patch_set(repo, ["linux-7.3", "linux-7.2"], lambda _p: True, lambda p: applied.append(p.name))
    assert [c.number for c in got.chosen] == ["01", "02", "03", "04", "05", "07", "08", "09"]
    assert all(c.preferred for c in got.chosen)
    assert applied == [c.path.name for c in got.chosen], "applied in order so later patches see earlier ones"


def test_a_patch_that_does_not_apply_falls_back_to_the_next_series(tmp_path: Path) -> None:
    """The linux-next/7.4-rc1 case: next's 03 is broken but 7.3's still applies."""
    repo = make_repo(tmp_path, FULL)
    msgs: list[str] = []
    got = ip.resolve_patch_set(
        repo, ["linux-next", "linux-7.3"], lambda p: not (p.parent.name == "linux-next" and p.name.startswith("03_")),
        lambda _p: None, msgs.append,
    )
    by_number = {c.number: c for c in got.chosen}
    assert by_number["03"].series == "linux-7.3"
    assert by_number["01"].series == "linux-next"
    assert any("03_linux-next.patch" in m and "does not apply" in m for m in msgs)
    assert any("Using 03_linux-7.3.patch from linux-7.3" in m for m in msgs)


def test_failing_optional_patch_is_dropped_not_fatal(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, FULL)
    msgs: list[str] = []
    got = ip.resolve_patch_set(repo, ["linux-7.3"], lambda p: not p.name.startswith("09_"), lambda _p: None, msgs.append)
    assert got.dropped == ["09"]
    assert "09" not in {c.number for c in got.chosen}
    assert any("optional patch 09" in m for m in msgs)


def test_failing_required_patch_names_the_patch_and_stops(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, FULL)
    with pytest.raises(ip.PatchError, match=r"03_\* patch that applies"):
        ip.resolve_patch_set(repo, ["linux-7.3", "linux-7.2"], lambda p: not p.name.startswith("03_"), lambda _p: None)


def test_a_series_missing_a_patch_never_borrows_it(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, {"linux-6.1": ("01", "02"), "linux-7.3": NUMS})
    got = ip.resolve_patch_set(repo, ["linux-6.1", "linux-7.3"], lambda _p: True, lambda _p: None)
    assert [c.number for c in got.chosen] == ["01", "02"]
