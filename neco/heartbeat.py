#!/usr/bin/env python3
import os
import sys
import threading
import time
from pathlib import Path

import wandering as neco
from memory.consolidation import MemoryWorker
from prompt import build_persona, load_character
from machine import write_snapshot
import hostfacts

ROOT = Path(__file__).resolve().parent.parent


def env_int(name, default):
    value = os.getenv(name)
    return int(value) if value not in (None, "") else default


def env_bool(name, default=True):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in ("0", "false", "no", "off", "")


port = os.getenv("OPENWEBUI_PORT", "3300")
base_url = os.getenv("OPENWEBUI_URL", f"http://127.0.0.1:{port}")

neco.BASE_URL = base_url
neco.MODEL = os.getenv("NECO_MODEL", getattr(neco, "MODEL", "llama3.1:8b"))
CHARACTER_ID = os.getenv("NECO_CHARACTER", "neco").strip().lower() or "neco"
try:
    CHARACTER = load_character(CHARACTER_ID)
except ValueError as error:
    raise SystemExit(str(error)) from error
neco.CHAT_TITLE = os.getenv("NECO_CHAT_TITLE") or CHARACTER["chat_title"]
neco.MIN_INTERVAL = env_int("NECO_MIN_INTERVAL", getattr(neco, "MIN_INTERVAL", 1200))
neco.MAX_INTERVAL = env_int("NECO_MAX_INTERVAL", getattr(neco, "MAX_INTERVAL", 2700))

if neco.MIN_INTERVAL > neco.MAX_INTERVAL:
    raise SystemExit("NECO_MIN_INTERVAL cannot be greater than NECO_MAX_INTERVAL")

neco.TOKEN_FILE = os.getenv("NECO_TOKEN_FILE", str(ROOT / ".runtime" / "neco_token"))
neco.STATE_FILE = os.getenv("NECO_STATE_FILE", str(ROOT / ".runtime" / "neco_state.json"))

owner = os.getenv("OWNER_NAME") or "friend"
neco.OWNER = owner
neco.FRAGMENTS = [line.replace("Echo", owner) for line in neco.FRAGMENTS]
neco.THOUGHT_DIRECTIONS = [line.replace("Echo", owner) for line in neco.THOUGHT_DIRECTIONS]
machine = os.getenv("NECO_MACHINE", "this machine")
persona_mode = os.getenv("NECO_PERSONA", "lite").strip().lower()
try:
    neco.BASE_PERSONA = build_persona(owner=owner, machine=machine, mode=persona_mode, character=CHARACTER_ID)
except ValueError as error:
    raise SystemExit(str(error)) from error

MEMORY_ENABLED = env_bool("NECO_MEMORY_ENABLED", True)
# Each cat keeps its own memory. The Open WebUI recall filter always reads
# .runtime/neco-memory.sqlite3, so that name is a relative symlink to the
# active cat's database (relative, so it resolves inside the container too).
MEMORY_DB = os.getenv("NECO_MEMORY_DB", str(ROOT / ".runtime" / "memory" / f"{CHARACTER_ID}.sqlite3"))


def link_active_memory(runtime=ROOT / ".runtime", target=None):
    runtime = Path(runtime)
    target = Path(target or MEMORY_DB)
    if target.parent.parent != runtime:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    legacy = runtime / "neco-memory.sqlite3"
    # One-time migration: an existing real database becomes Neco's memory.
    if legacy.is_file() and not legacy.is_symlink():
        neco_db = runtime / "memory" / "neco.sqlite3"
        if not neco_db.exists():
            legacy.rename(neco_db)
        else:
            return
    if legacy.is_symlink() or not legacy.exists():
        relative = f"memory/{target.name}"
        if legacy.is_symlink() and os.readlink(legacy) == relative:
            return
        temporary = runtime / ".neco-memory.link"
        if temporary.is_symlink():
            temporary.unlink()
        temporary.symlink_to(relative)
        os.replace(temporary, legacy)
neco.MEMORY_DB = MEMORY_DB
MEMORY_INTERVAL = env_int("NECO_MEMORY_INTERVAL", 30)
MEMORY_BACKFILL = env_bool("NECO_MEMORY_BACKFILL", False)


GROUNDING_FILE = ROOT / ".runtime" / "grounding.txt"
HOST_FACTS = {}


def take_host_facts():
    """Fastfetch-style snapshot, once per daemon start (distro, CPU, own model...)."""
    global HOST_FACTS
    try:
        HOST_FACTS = hostfacts.write_facts()
        host = HOST_FACTS.get("host", {})
        print(f"[grounding] {host.get('distro', '?')} / {host.get('kernel', '?')} / "
              f"model {HOST_FACTS['self']['model']} ({HOST_FACTS['self']['model_location']})", flush=True)
    except Exception as error:
        print(f"[grounding] host facts unavailable: {type(error).__name__}: {error}", flush=True)
        HOST_FACTS = {}


def refresh_grounding():
    """Re-render the grounding text: static facts + live time and memory count."""
    if not HOST_FACTS:
        return
    count = hostfacts.memory_count(MEMORY_DB) if MEMORY_ENABLED else None
    text = hostfacts.describe(HOST_FACTS, memory_count=count)
    hostfacts.write_text(GROUNDING_FILE, text)
    neco.GROUNDING = text


def vitals_loop():
    """Keep a small read-only host snapshot fresh for the Open WebUI filter."""
    last_error = None
    ticks = 0
    while True:
        try:
            write_snapshot()
            if ticks % 6 == 0:  # every ~30 s
                refresh_grounding()
            last_error = None
        except Exception as error:
            message = f"{type(error).__name__}: {error}"
            if message != last_error:
                print(f"[vitals] snapshot unavailable: {message}", flush=True)
                last_error = message
        ticks += 1
        time.sleep(5)


def memory_loop():
    worker = MemoryWorker(
        base_url=base_url,
        token_file=neco.TOKEN_FILE,
        model=neco.MODEL,
        db_path=MEMORY_DB,
        idle_title=neco.CHAT_TITLE,
        interval=MEMORY_INTERVAL,
        backfill=MEMORY_BACKFILL,
        character_name=CHARACTER["name"],
    )
    print(f"[memory] continuity worker enabled ({MEMORY_DB})", flush=True)
    worker.loop()


if __name__ == "__main__":
    link_active_memory()
    print(f"[character] {CHARACTER['name']} ({CHARACTER_ID})", flush=True)
    take_host_facts()
    refresh_grounding()
    threading.Thread(target=vitals_loop, name="neco-vitals", daemon=True).start()
    if MEMORY_ENABLED:
        threading.Thread(target=memory_loop, name="neco-memory", daemon=True).start()
    neco.main_loop(test_mode="--test" in sys.argv)
