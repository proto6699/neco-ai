#!/usr/bin/env bash
# Replace the bundled soundtrack locally, then bake it into the Den image.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[[ $# == 1 && -f "$1" && -s "$1" && -r "$1" ]] || {
    echo 'Usage: ./scripts/set-music.sh "/full/path/to/your-song.mp3"' >&2
    echo 'Choose a readable, nonempty MP3 file.' >&2
    exit 1
}
case "${1,,}" in
    *.mp3) ;;
    *) echo 'Please supply an MP3 file (renaming another format does not convert it).' >&2; exit 1 ;;
esac
[[ -f "$ROOT/.env" ]] || { echo 'Run ./install.sh first.' >&2; exit 1; }
command -v docker >/dev/null || { echo 'Docker is required; run ./install.sh first.' >&2; exit 1; }
DOCKER=(docker)
if ! docker info >/dev/null 2>&1; then
    DOCKER=(sudo docker)
fi
if "${DOCKER[@]}" compose version >/dev/null 2>&1; then
    COMPOSE=("${DOCKER[@]}" compose)
elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE=(docker-compose)
    [[ "${DOCKER[0]}" != sudo ]] || COMPOSE=(sudo docker-compose)
else
    echo 'Docker Compose is required; run ./install.sh first.' >&2
    exit 1
fi
DEST="$ROOT/openwebui/overlay/static/den-music.mp3"
if [[ ! "$1" -ef "$DEST" ]]; then
    cp -- "$1" "$DEST"
fi
chmod 644 "$DEST"
cd "$ROOT"
echo 'Music saved locally. Rebuilding the Den (cached image layers are reused)…'
"${COMPOSE[@]}" up -d --build openwebui
echo 'Refresh the Den (Ctrl+Shift+R), then click DEN MUSIC.'
echo 'If it is unavailable, check /static/den-music.mp3 on your Den URL.'
