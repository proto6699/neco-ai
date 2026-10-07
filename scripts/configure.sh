#!/usr/bin/env bash
# Interactive setup: pick a cat, a model size, persona mode and idle rhythm.
# Writes the answers into .env. Safe to rerun; only these keys are touched.
#   ./scripts/configure.sh            ask questions
#   ./scripts/configure.sh --defaults  write defaults without asking
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

DEFAULTS=0
[[ "${1:-}" == --defaults ]] && DEFAULTS=1
[[ -t 0 ]] || DEFAULTS=1   # no terminal (piped/CI): don't hang on read

[[ -f .env ]] || cp .env.example .env

current() {  # current .env value for a key, unquoted
    python3 - "$1" <<'PY'
import shlex, sys
from pathlib import Path
for line in Path(".env").read_text().splitlines():
    key, sep, value = line.partition("=")
    if sep and key.strip() == sys.argv[1]:
        words = shlex.split(value, comments=True)
        print(words[0] if words else "")
        break
PY
}

ask() {  # ask "prompt" default -> echoes answer
    local prompt="$1" default="$2" answer
    if (( DEFAULTS )); then echo "$default"; return; fi
    printf '%s [%s]: ' "$prompt" "$default" >&2
    IFS= read -r answer
    echo "${answer:-$default}"
}

choose() {  # choose "title" default_index option... -> echoes chosen index (1-based)
    local title="$1" default="$2"; shift 2
    if (( DEFAULTS )); then echo "$default"; return; fi
    echo >&2
    echo "$title" >&2
    local i=1
    for option in "$@"; do
        printf '  %d) %s\n' "$i" "$option" >&2
        i=$((i + 1))
    done
    local pick
    while true; do
        printf 'choose 1-%d [%d]: ' "$#" "$default" >&2
        IFS= read -r pick
        pick="${pick:-$default}"
        [[ "$pick" =~ ^[0-9]+$ ]] && (( pick >= 1 && pick <= $# )) && { echo "$pick"; return; }
        echo "  not an option." >&2
    done
}

echo "== cat setup =="
(( DEFAULTS )) && echo "(using defaults; rerun ./scripts/configure.sh in a terminal to choose)"

# --- owner -------------------------------------------------------------
OWNER_DEFAULT="$(current OWNER_NAME)"
OWNER_DEFAULT="${OWNER_DEFAULT:-${USER:-friend}}"
OWNER="$(ask "what should the cat call you?" "$OWNER_DEFAULT")"

# --- character ---------------------------------------------------------
mapfile -t IDS < <(python3 -c 'import sys; sys.path.insert(0,"neco"); from prompt import list_characters; print("\n".join(list_characters()))')
LABELS=()
DEFAULT_CAT=1
CURRENT_CAT="$(current NECO_CHARACTER)"
for idx in "${!IDS[@]}"; do
    id="${IDS[$idx]}"
    label="$(python3 -c 'import sys; sys.path.insert(0,"neco"); from prompt import load_character as l; c=l(sys.argv[1]); print(c["name"] + " — " + c["blurb"])' "$id")"
    LABELS+=("$label")
    [[ "$id" == "${CURRENT_CAT:-neco}" ]] && DEFAULT_CAT=$((idx + 1))
done
CAT="${IDS[$(( $(choose "which cat lives here?" "$DEFAULT_CAT" "${LABELS[@]}") - 1 ))]}"

# --- model -------------------------------------------------------------
MODEL_PICK="$(choose "which model? (local models run through Ollama)" 1 \
    "llama3.1:8b  — recommended. ~5 GB, fits most 8 GB GPUs (RTX 3060/3070 class)" \
    "llama3.2:3b  — lighter. ~2 GB, 4-6 GB GPUs or a decent CPU" \
    "llama3.2:1b  — tiny. runs almost anywhere, noticeably simpler replies" \
    "something else — another Ollama tag, or an API model already set up in Open WebUI")"
case "$MODEL_PICK" in
    1) MODEL=llama3.1:8b; PERSONA=full ;;
    2) MODEL=llama3.2:3b; PERSONA=lite ;;
    3) MODEL=llama3.2:1b; PERSONA=lite ;;
    4)
        MODEL="$(ask "exact model ID (as shown in Open WebUI / ollama list)" "$(current NECO_MODEL)")"
        [[ -n "$MODEL" ]] || { echo "a model ID is required." >&2; exit 1; }
        P="$(choose "persona size for $MODEL?" 1 \
            "full — richer character, for 7B+ or API models" \
            "lite — compact prompt, for small models")"
        PERSONA=$([[ "$P" == 1 ]] && echo full || echo lite)
        ;;
esac

# --- idle rhythm -------------------------------------------------------
IDLE_PICK="$(choose "how often should the cat think out loud?" 2 \
    "chatty — every 10-20 min" \
    "normal — every 20-45 min" \
    "quiet  — every 1-2 hours" \
    "custom")"
case "$IDLE_PICK" in
    1) MIN=600;  MAX=1200 ;;
    2) MIN=1200; MAX=2700 ;;
    3) MIN=3600; MAX=7200 ;;
    4)
        MIN=$(( $(ask "minimum minutes between thoughts" 20) * 60 ))
        MAX=$(( $(ask "maximum minutes between thoughts" 45) * 60 ))
        (( MIN <= MAX )) || { echo "minimum must not exceed maximum." >&2; exit 1; }
        ;;
esac

python3 - "$OWNER" "$CAT" "$MODEL" "$PERSONA" "$MIN" "$MAX" <<'PY'
import shlex, sys
from pathlib import Path
owner, cat, model, persona, lo, hi = sys.argv[1:]
values = {
    "OWNER_NAME": owner, "NECO_CHARACTER": cat, "NECO_MODEL": model,
    "NECO_PERSONA": persona, "NECO_MIN_INTERVAL": lo, "NECO_MAX_INTERVAL": hi,
}
path = Path(".env")
out, seen = [], set()
for line in path.read_text().splitlines():
    key = line.partition("=")[0].strip()
    if key in values and "=" in line:
        out.append(f"{key}={shlex.quote(values[key])}")
        seen.add(key)
    else:
        out.append(line)
out += [f"{k}={shlex.quote(v)}" for k, v in values.items() if k not in seen]
path.write_text("\n".join(out) + "\n")
PY
chmod 600 .env

# Copy the chosen cat's images into the Den build (generated, never committed).
# den-neco.png is the everyday image; -sleep / -yay are used for night and rare moments.
AVATAR="$(python3 - "$CAT" <<'PY'
import shutil, sys
sys.path.insert(0, "neco")
from prompt import avatar_path, mood_paths
static = "openwebui/overlay/static/"
for mood, path in mood_paths(sys.argv[1]).items():
    shutil.copyfile(path, static + ("den-neco.png" if mood == "normal" else f"den-neco-{mood}.png"))
print(avatar_path(sys.argv[1]))
PY
)"

echo
echo "saved to .env:"
echo "  cat      $CAT"
echo "  model    $MODEL ($PERSONA persona)"
echo "  idle     $((MIN / 60))-$((MAX / 60)) min"
echo "  owner    $OWNER"
if [[ "$AVATAR" == */_shared/* ]]; then
    echo "  avatar   placeholder (add characters/$CAT/avatar.png for your own)"
fi
