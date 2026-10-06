#!/usr/bin/env python3
"""Read-only host telemetry for Neco's experimental system-vitals feature."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SNAPSHOT = ROOT / ".runtime" / "system-vitals.json"


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text().strip()
    except (OSError, UnicodeError):
        return None


def _read_int(path: Path) -> int | None:
    value = _read_text(path)
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def _temp_c(path: Path) -> float | None:
    value = _read_int(path)
    if value is None:
        return None
    if abs(value) >= 1000:
        value = value / 1000
    if -20 <= value <= 150:
        return round(float(value), 1)
    return None


def _memory() -> dict[str, float] | None:
    values: dict[str, int] = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, _, rest = line.partition(":")
            if not rest:
                continue
            parts = rest.strip().split()
            if parts and parts[0].isdigit():
                values[key] = int(parts[0]) * 1024
    except OSError:
        return None

    total = values.get("MemTotal")
    available = values.get("MemAvailable")
    if not total or available is None:
        return None

    used = max(0, total - available)
    gib = 1024 ** 3
    return {
        "used_gib": round(used / gib, 2),
        "total_gib": round(total / gib, 2),
        "used_percent": round((used / total) * 100, 1),
    }


def _cpu_temp() -> float | None:
    preferred = ("k10temp", "coretemp", "zenpower", "cpu_thermal", "acpitz")

    candidates: list[tuple[int, Path]] = []
    for hwmon in Path("/sys/class/hwmon").glob("hwmon*"):
        name = (_read_text(hwmon / "name") or "").lower()
        score = 0 if name in preferred else 1
        for sensor in hwmon.glob("temp*_input"):
            candidates.append((score, sensor))

    for _, sensor in sorted(candidates, key=lambda item: item[0]):
        value = _temp_c(sensor)
        if value is not None:
            return value

    for zone in Path("/sys/class/thermal").glob("thermal_zone*"):
        value = _temp_c(zone / "temp")
        if value is not None:
            return value
    return None


def _gpu_stats() -> dict[str, Any] | None:
    for card in sorted(Path("/sys/class/drm").glob("card[0-9]*")):
        device = card / "device"
        if not device.exists():
            continue

        vendor = (_read_text(device / "vendor") or "").lower()
        # 0x1002 = AMD. Other vendors simply report unavailable for now.
        if vendor != "0x1002":
            continue

        result: dict[str, Any] = {"card": card.name, "vendor": "amd"}

        busy = _read_int(device / "gpu_busy_percent")
        if busy is not None:
            result["load_percent"] = max(0, min(100, busy))

        vram_used = _read_int(device / "mem_info_vram_used")
        vram_total = _read_int(device / "mem_info_vram_total")
        gib = 1024 ** 3
        if vram_used is not None:
            result["vram_used_gib"] = round(vram_used / gib, 2)
        if vram_total:
            result["vram_total_gib"] = round(vram_total / gib, 2)
            if vram_used is not None:
                result["vram_used_percent"] = round((vram_used / vram_total) * 100, 1)

        for hwmon in device.glob("hwmon/hwmon*"):
            value = _temp_c(hwmon / "temp1_input")
            if value is not None:
                result["temp_c"] = value
                break

        return result
    return None


def _battery(root: Path = Path("/sys/class/power_supply")) -> dict[str, Any] | None:
    """Read available Linux batteries without privileges; no battery means None."""
    batteries = []
    for device in sorted(root.glob("*")):
        if _read_text(device / "type") != "Battery":
            continue
        percent = _read_int(device / "capacity")
        if percent is not None and not 0 <= percent <= 100:
            percent = None
        batteries.append({"name": device.name, "percent": percent,
                          "status": _read_text(device / "status")})
    return {"batteries": batteries} if batteries else None


def collect_vitals() -> dict[str, Any]:
    try:
        uptime_seconds = float(Path("/proc/uptime").read_text().split()[0])
        uptime_hours = round(uptime_seconds / 3600, 1)
    except (OSError, ValueError, IndexError):
        uptime_hours = None

    try:
        load_1m, load_5m, load_15m = os.getloadavg()
        load = {
            "1m": round(load_1m, 2),
            "5m": round(load_5m, 2),
            "15m": round(load_15m, 2),
        }
    except OSError:
        load = None

    return {
        "sampled_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "uptime_hours": uptime_hours,
        "load_average": load,
        "memory": _memory(),
        "cpu_temp_c": _cpu_temp(),
        "gpu": _gpu_stats(),
        "battery": _battery(),
    }


def write_snapshot(path: Path = DEFAULT_SNAPSHOT) -> dict[str, Any]:
    data = collect_vitals()
    path.parent.mkdir(parents=True, exist_ok=True)

    fd, temp_name = tempfile.mkstemp(prefix=".system-vitals.", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(data, handle, separators=(",", ":"))
            handle.write("\n")
        os.replace(temp_name, path)
        path.chmod(0o600)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass

    return data


if __name__ == "__main__":
    print(json.dumps(collect_vitals(), indent=2))
