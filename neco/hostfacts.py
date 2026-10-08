#!/usr/bin/env python3
"""Fastfetch-style host facts and the cat's own session config.

Taken once when the daemon starts and written to .runtime/host-facts.json.
These are slow-changing facts (distro, kernel, CPU, which model she runs on),
kept separate from machine.py's live vitals (load, temperature, battery),
which are re-sampled every few seconds.

Everything here is read-only: files under /etc, /proc and /sys, plus a few
harmless commands with short timeouts. A missing fact is left out, never guessed.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import socket
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FACTS = ROOT / ".runtime" / "host-facts.json"

# Terminals worth knowing about when suggesting "open X and run Y".
TERMINALS = ("kitty", "alacritty", "wezterm", "foot", "ghostty", "konsole",
             "gnome-terminal", "kgx", "xfce4-terminal", "tilix", "xterm")

# Desktop sessions recognised from running processes when the daemon's own
# environment (a systemd user service) has no XDG_CURRENT_DESKTOP.
SESSION_PROCESSES = {
    "plasmashell": "KDE Plasma", "gnome-shell": "GNOME", "Hyprland": "Hyprland",
    "sway": "Sway", "xfce4-session": "Xfce", "cinnamon": "Cinnamon",
    "mate-session": "MATE", "niri": "niri", "river": "river", "labwc": "labwc",
    "cosmic-comp": "COSMIC", "budgie-wm": "Budgie", "i3": "i3",
}

# GPU vendor IDs from /sys/class/drm/card*/device/vendor.
GPU_VENDORS = {"0x1002": "AMD", "0x10de": "NVIDIA", "0x8086": "Intel"}


def _run(args: list[str], timeout: float = 3.0) -> str | None:
    if not shutil.which(args[0]):
        return None
    try:
        result = subprocess.run(args, capture_output=True, text=True,
                                timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def _read(path: Path) -> str | None:
    try:
        return path.read_text().strip()
    except (OSError, UnicodeError):
        return None


def os_release(path: Path = Path("/etc/os-release")) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in (_read(path) or "").splitlines():
        key, sep, value = line.partition("=")
        if sep:
            values[key.strip()] = value.strip().strip('"')
    return values


def cpu_model(path: Path = Path("/proc/cpuinfo")) -> str | None:
    for line in (_read(path) or "").splitlines():
        key, _, value = line.partition(":")
        if key.strip() in ("model name", "Model", "Hardware") and value.strip():
            return " ".join(value.split())
    return None


def cpu_threads() -> int | None:
    return os.cpu_count()


def gpus() -> list[str]:
    names: list[str] = []
    lspci = _run(["lspci"])
    if lspci:
        for line in lspci.splitlines():
            if any(tag in line for tag in ("VGA compatible", "3D controller", "Display controller")):
                names.append(line.split(": ", 1)[-1].strip())
    if names:
        return names
    seen = set()
    for card in sorted(Path("/sys/class/drm").glob("card[0-9]*")):
        vendor = (_read(card / "device" / "vendor") or "").lower()
        if vendor and vendor not in seen:
            seen.add(vendor)
            names.append(GPU_VENDORS.get(vendor, f"vendor {vendor}") + " GPU")
    return names


def ram_total_gib() -> float | None:
    for line in (_read(Path("/proc/meminfo")) or "").splitlines():
        if line.startswith("MemTotal:"):
            try:
                return round(int(line.split()[1]) * 1024 / 1024 ** 3, 1)
            except (IndexError, ValueError):
                return None
    return None


def packages() -> dict[str, Any] | None:
    """Count installed packages with whichever native manager exists."""
    counters = (
        ("pacman", ["pacman", "-Qq"]),
        ("dpkg", ["dpkg-query", "-f", ".\n", "-W"]),
        ("rpm", ["rpm", "-qa"]),
        ("xbps", ["xbps-query", "-l"]),
        ("apk", ["apk", "info"]),
    )
    for name, args in counters:
        output = _run(args, timeout=8.0)
        if output:
            result: dict[str, Any] = {"manager": name, "count": len(output.splitlines())}
            if name == "pacman" and shutil.which("paru"):
                result["aur_helper"] = "paru"
            elif name == "pacman" and shutil.which("yay"):
                result["aur_helper"] = "yay"
            flatpaks = _run(["flatpak", "list", "--app"], timeout=8.0)
            if flatpaks:
                result["flatpak_apps"] = len(flatpaks.splitlines())
            return result
    return None


def desktop_session(proc: Path = Path("/proc")) -> str | None:
    for key in ("XDG_CURRENT_DESKTOP", "DESKTOP_SESSION"):
        if os.getenv(key):
            return os.environ[key].replace(":", " / ")
    try:
        for entry in proc.iterdir():
            if entry.name.isdigit():
                name = _read(entry / "comm")
                if name in SESSION_PROCESSES:
                    return SESSION_PROCESSES[name]
    except OSError:
        pass
    return None


def session_type() -> str | None:
    if os.getenv("WAYLAND_DISPLAY") or os.getenv("XDG_SESSION_TYPE") == "wayland":
        return "wayland"
    if os.getenv("DISPLAY") or os.getenv("XDG_SESSION_TYPE") == "x11":
        return "x11"
    return os.getenv("XDG_SESSION_TYPE") or None


def terminals() -> list[str]:
    return [name for name in TERMINALS if shutil.which(name)]


def timezone_name() -> str | None:
    if os.getenv("TZ"):
        return os.environ["TZ"].lstrip(":")
    link = Path("/etc/localtime")
    try:
        target = os.readlink(link)
        if "zoneinfo/" in target:
            return target.split("zoneinfo/", 1)[1]
    except OSError:
        pass
    return _read(Path("/etc/timezone"))


def collect_host() -> dict[str, Any]:
    release = os_release()
    shell = os.getenv("SHELL")
    host = {
        "distro": release.get("PRETTY_NAME") or release.get("NAME"),
        "distro_id": release.get("ID"),
        "kernel": platform.release() or None,
        "arch": platform.machine() or None,
        "hostname": socket.gethostname() or None,
        "desktop": desktop_session(),
        "session_type": session_type(),
        "shell": Path(shell).name if shell else None,
        "terminals": terminals(),
        "cpu": cpu_model(),
        "cpu_threads": cpu_threads(),
        "gpus": gpus(),
        "ram_total_gib": ram_total_gib(),
        "packages": packages(),
        "timezone": timezone_name(),
        "utc_offset_minutes": round(time.localtime().tm_gmtoff / 60),
    }
    return {key: value for key, value in host.items() if value not in (None, [], {})}


def model_location(model: str, provider: str | None = None) -> str:
    """Local (Ollama) or external API. NECO_MODEL_PROVIDER overrides the guess."""
    if provider:
        return provider
    if shutil.which("ollama"):
        listed = _run(["ollama", "list"], timeout=5.0) or ""
        names = {line.split()[0] for line in listed.splitlines()[1:] if line.split()}
        if model in names or f"{model}:latest" in names:
            return "local (Ollama on this machine)"
    return "external API (inference runs on the provider's servers, not this machine)"


def collect_self(env: dict[str, str] | None = None) -> dict[str, Any]:
    env = dict(os.environ if env is None else env)
    model = env.get("NECO_MODEL", "").strip() or "unknown"
    reflection = env.get("NECO_REFLECTION_MODEL", "").strip()
    info: dict[str, Any] = {
        "model": model,
        "model_location": model_location(model, env.get("NECO_MODEL_PROVIDER", "").strip() or None),
        "reflection_model": reflection or model,
        "character": env.get("NECO_CHARACTER", "neco").strip() or "neco",
        "persona_mode": env.get("NECO_PERSONA", "lite").strip() or "lite",
        "idle_interval_minutes": [
            round(int(env.get("NECO_MIN_INTERVAL", "1200")) / 60),
            round(int(env.get("NECO_MAX_INTERVAL", "2700")) / 60),
        ],
        "memory_enabled": env.get("NECO_MEMORY_ENABLED", "1").strip().lower()
                          not in ("0", "false", "no", "off", ""),
        "memories_recalled_per_reply": 6,
        "idle_reply_token_budget": int(env.get("NECO_MAX_TOKENS", "1500") or 1500),
    }
    context = env.get("NECO_CONTEXT_TOKENS", "").strip()
    if context.isdigit():
        info["context_window_tokens"] = int(context)
    return info


def collect_facts(env: dict[str, str] | None = None) -> dict[str, Any]:
    return {
        "taken_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "host": collect_host(),
        "self": collect_self(env),
    }


def write_facts(path: Path = DEFAULT_FACTS, env: dict[str, str] | None = None) -> dict[str, Any]:
    data = collect_facts(env)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=".host-facts.", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(data, handle, indent=1)
            handle.write("\n")
        os.replace(temp_name, path)
        path.chmod(0o600)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
    return data


def describe(facts: dict[str, Any], memory_count: int | None = None,
             now: datetime | None = None) -> str:
    """Plain-text grounding block shared by the chat filter and idle thoughts."""
    host = facts.get("host") or {}
    me = facts.get("self") or {}
    lines = ["[Grounding — true facts about this machine and about you]"]

    def add(label, value):
        if value not in (None, "", [], {}):
            lines.append(f"{label}: {value}")

    add("distro", host.get("distro"))
    add("kernel", host.get("kernel"))
    add("hostname", host.get("hostname"))
    desktop = host.get("desktop")
    if desktop and host.get("session_type"):
        desktop = f"{desktop} ({host['session_type']})"
    add("desktop", desktop)
    add("shell", host.get("shell"))
    add("terminals installed", ", ".join(host.get("terminals") or []))
    cpu = host.get("cpu")
    if cpu and host.get("cpu_threads"):
        cpu = f"{cpu}, {host['cpu_threads']} threads"
    add("cpu", cpu)
    add("gpu", "; ".join(host.get("gpus") or []))
    if host.get("ram_total_gib"):
        add("ram total", f"{host['ram_total_gib']} GiB")
    pkgs = host.get("packages")
    if isinstance(pkgs, dict):
        text = f"{pkgs.get('count')} ({pkgs.get('manager')})"
        if pkgs.get("aur_helper"):
            text += f", AUR helper {pkgs['aur_helper']}"
        if pkgs.get("flatpak_apps"):
            text += f", {pkgs['flatpak_apps']} flatpak apps"
        add("packages", text)

    now = now or datetime.now(timezone.utc)
    offset = host.get("utc_offset_minutes")
    if isinstance(offset, (int, float)):
        local = now.astimezone(timezone.utc).timestamp() + offset * 60
        stamp = datetime.fromtimestamp(local, timezone.utc).strftime("%A %H:%M")
        add("local time", f"{stamp} ({host.get('timezone') or 'host timezone'})")

    lines.append("")
    add("you are running on model", me.get("model"))
    add("where that model runs", me.get("model_location"))
    if me.get("reflection_model") and me.get("reflection_model") != me.get("model"):
        add("memory consolidation model", me.get("reflection_model"))
    add("persona mode", me.get("persona_mode"))
    if me.get("context_window_tokens"):
        add("context window", f"{me['context_window_tokens']} tokens")
    if me.get("memory_enabled"):
        stored = f"{memory_count} active records" if memory_count is not None else "enabled"
        add("long-term memory", f"{stored}; up to {me.get('memories_recalled_per_reply', 6)} recalled per reply")
    else:
        add("long-term memory", "disabled")
    idle = me.get("idle_interval_minutes")
    if isinstance(idle, list) and len(idle) == 2:
        add("idle thoughts", f"every {idle[0]}-{idle[1]} minutes")

    lines.append(
        "Use these when they genuinely help (e.g. suggest commands for this distro and an installed "
        "terminal). Don't recite them unprompted. If asked what you run on, answer from here plainly. "
        "Anything not listed is unknown: say so rather than guess."
    )
    return "\n".join(lines)


def memory_count(db_path: Path | str) -> int | None:
    import sqlite3
    path = Path(db_path)
    if not path.exists():
        return None
    try:
        db = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=1)
        try:
            return db.execute("SELECT count(*) FROM memories WHERE status='active'").fetchone()[0]
        finally:
            db.close()
    except sqlite3.Error:
        return None


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=".grounding.", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(text + "\n")
        os.replace(temp_name, path)
        path.chmod(0o600)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


if __name__ == "__main__":
    facts = collect_facts()
    print(json.dumps(facts, indent=2))
    print()
    print(describe(facts))
