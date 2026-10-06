#!/usr/bin/env bash
# Re-run the setup questions (cat, model, idle rhythm) and apply them:
# rebuild the Den with the new avatar, re-apply the persona, restart the daemon.
# Each cat keeps its own memory; switching back later finds the old memories.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
[[ -f .env && -x neco/.venv/bin/python ]] || { echo 'Run ./install.sh first.' >&2; exit 1; }

./scripts/configure.sh

if docker info >/dev/null 2>&1; then DOCKER=(docker); else DOCKER=(sudo docker); fi
echo "[+] rebuilding the Den with the new avatar"
"${DOCKER[@]}" compose up -d --build

if [[ -s .runtime/neco_token ]]; then
    echo "[+] applying the persona (waiting for the Den to answer)"
    for _ in $(seq 1 30); do
        python3 scripts/setup-persona.py && break
        sleep 3
    done
fi
systemctl --user restart neco-ai.service 2>/dev/null && echo "[+] daemon restarted" || echo "[i] daemon not installed yet; ./scripts/start-neco.sh"
