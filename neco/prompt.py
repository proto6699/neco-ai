"""Compose a cat's system prompt from characters/<id>/ plus shared files."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHARACTERS = ROOT / "characters"
SHARED = CHARACTERS / "_shared"
DEFAULT_CHARACTER = "neco"


def list_characters():
    names = sorted(
        p.name for p in CHARACTERS.iterdir()
        if p.is_dir() and not p.name.startswith("_") and (p / "character.conf").is_file()
    )
    # The default cat is listed first in the installer.
    return sorted(names, key=lambda n: n != DEFAULT_CHARACTER)


def character_dir(character=DEFAULT_CHARACTER):
    character = (character or DEFAULT_CHARACTER).strip().lower()
    if character not in list_characters():
        raise ValueError(
            f"Unknown character '{character}'. Available: {', '.join(list_characters())}"
        )
    return CHARACTERS / character


def load_character(character=DEFAULT_CHARACTER):
    """Read characters/<id>/character.conf (simple KEY=value lines)."""
    directory = character_dir(character)
    info = {"id": directory.name, "name": directory.name, "blurb": ""}
    for line in (directory / "character.conf").read_text().splitlines():
        key, sep, value = line.partition("=")
        if sep and not key.strip().startswith("#"):
            info[key.strip().lower()] = value.strip().strip('"')
    info["chat_title"] = info.get("chat_title") or f"{info['name']} — idle"
    return info


def _piece(directory, name):
    for base in (directory, SHARED):
        path = base / name
        if path.is_file():
            return path.read_text()
    raise FileNotFoundError(f"{name} missing for {directory.name} and in _shared")


def build_persona(owner="Echo", machine="this machine", mode="full", character=DEFAULT_CHARACTER):
    directory = character_dir(character)
    info = load_character(character)
    mode = (mode or "full").strip().lower()
    if mode == "lite":
        prompt = _piece(directory, "lite.md")
    elif mode == "full":
        prompt = "\n\n".join(_piece(directory, n) for n in ("identity.md", "values.md", "voice.md"))
    else:
        raise ValueError("NECO_PERSONA must be lite or full")
    # Character files are written with "Echo" as the owner placeholder.
    return prompt.replace("Echo", owner).replace("{name}", info["name"])


MOODS = ("normal", "sleep", "yay")


def avatar_path(character=DEFAULT_CHARACTER):
    """moods/normal.png, then a local avatar.png, then the shipped placeholder."""
    directory = character_dir(character)
    for own in (directory / "moods" / "normal.png", directory / "avatar.png"):
        if own.is_file():
            return own
    shipped = SHARED / f"avatar-{directory.name}.png"
    return shipped if shipped.is_file() else SHARED / "placeholder-avatar.png"


def mood_paths(character=DEFAULT_CHARACTER):
    """Image per Den mood. Static cats reuse their one avatar for every mood."""
    directory = character_dir(character)
    base = avatar_path(character)
    paths = {}
    for mood in MOODS:
        own = directory / "moods" / f"{mood}.png"
        paths[mood] = own if own.is_file() else base
    return paths
