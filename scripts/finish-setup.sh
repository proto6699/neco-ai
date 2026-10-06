#!/usr/bin/env bash
# Finish authenticated setup only after the owner creates the Open WebUI account.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
[[ -f .env && -x neco/.venv/bin/python ]] || { echo 'Run ./install.sh first.' >&2; exit 1; }
if [[ -s .runtime/neco_token ]]; then
    python3 scripts/setup-persona.py
else
    ./scripts/set-token.sh
fi
./scripts/test-neco.sh
loginctl enable-linger "$(id -un)"
./scripts/start-neco.sh
./scripts/doctor.sh
