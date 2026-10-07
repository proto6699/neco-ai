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
    PORT="$(grep -E '^OPENWEBUI_PORT=' .env | cut -d= -f2 | tr -d "\"' ")"
    BASE="http://127.0.0.1:${PORT:-3300}"
    MODEL="$(grep -E '^NECO_MODEL=' .env | cut -d= -f2- | tr -d "\"'")"

    echo "[+] waiting for the Den to come back up"
    for _ in $(seq 1 60); do
        curl -fsS -m 3 "$BASE/health" >/dev/null 2>&1 && break
        sleep 2
    done

    # API-provider models (e.g. DeepSeek) can take a moment to be listed after a restart.
    echo "[+] waiting for $MODEL to be listed"
    listed=false
    for _ in $(seq 1 20); do
        if curl -fsS -m 10 -H "Authorization: Bearer $(cat .runtime/neco_token)" "$BASE/api/models" 2>/dev/null \
            | python3 -c 'import sys,json; ids={m["id"] for m in json.load(sys.stdin).get("data",[])}; sys.exit(0 if sys.argv[1] in ids else 1)' "$MODEL"; then
            listed=true; break
        fi
        sleep 3
    done

    if [[ "$listed" == true ]]; then
        python3 scripts/setup-persona.py
    else
        echo
        echo "[!] '$MODEL' is not in the Den's model list, so the persona was not applied."
        echo "    Models the Den can see right now:"
        curl -fsS -m 10 -H "Authorization: Bearer $(cat .runtime/neco_token)" "$BASE/api/models" 2>/dev/null \
            | python3 -c 'import sys,json; [print("      " + m["id"]) for m in json.load(sys.stdin).get("data",[])]' || echo "      (could not read the list)"
        echo "    Fix the model with ./scripts/change-cat.sh, or check the provider under"
        echo "    Admin Panel -> Settings -> Connections, then run: python3 scripts/setup-persona.py"
        exit 1
    fi
fi
systemctl --user restart neco-ai.service 2>/dev/null && echo "[+] daemon restarted" || echo "[i] daemon not installed yet; ./scripts/start-neco.sh"
