"""Suite state file (``.interlace-suite-state.json``) read by the GUI for its verification badges."""

from __future__ import annotations

import json
from typing import Any


def kernel_record(srcinfo: str, series: str, rdna: bool, patches: list[str], now: int) -> str:
    """JSON describing a kernel this suite just built (read back by the GUI to verify the running kernel).

    ``srcinfo`` is ``makepkg --printsrcinfo`` output; ``pkgbase`` identifies the flavour (``linux-cachyos``,
    ``linux-cachyos-lts``, ``linux-cachyos-rc``) and ``pkgver``/``pkgrel`` the exact build.
    """
    fields: dict[str, str] = {}
    for line in srcinfo.splitlines():
        key, _, value = line.strip().partition(" = ")
        if key in ("pkgbase", "pkgver", "pkgrel") and key not in fields:
            fields[key] = value.strip()
    data = {
        "series": series, "pkgbase": fields.get("pkgbase", ""), "pkgver": fields.get("pkgver", ""),
        "pkgrel": fields.get("pkgrel", ""), "rdna": rdna, "patches": patches, "built_at": now,
    }
    return json.dumps(data, indent=2) + "\n"


def parse_kernel_record(text: str) -> dict[str, Any] | None:
    try:
        data = json.loads(text) if text.strip() else None
    except ValueError:
        return None
    return data if isinstance(data, dict) and data.get("series") else None


def update_state(
    existing_json: str, conn: str, rel_fw: str, profile: str, adapter: str,
    src_edid: str, live_only: bool, now: int,
) -> str:
    """Merge one connector's record into the existing state JSON text and return the new text."""
    data: dict[str, Any] = {"connectors": {}, "gpu_profile": profile, "adapter_mode": adapter}
    if existing_json.strip():
        try:
            old = json.loads(existing_json)
        except ValueError:
            old = None
        if isinstance(old, dict):
            data.update(old)
            if not isinstance(data.get("connectors"), dict):
                data["connectors"] = {}
    data["gpu_profile"] = profile
    data["adapter_mode"] = adapter
    data["last_connector"] = conn
    data["connectors"][conn] = {
        "edid_file": rel_fw,
        "gpu_profile": profile,
        "adapter_mode": adapter,
        "source_edid": src_edid,
        "live_only": live_only,
        "updated_at": now,
    }
    return json.dumps(data, indent=2) + "\n"
