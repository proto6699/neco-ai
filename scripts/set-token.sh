#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "$ROOT/.runtime"
chmod 700 "$ROOT/.runtime"
printf 'Open WebUI API key: '
IFS= read -r -s TOKEN
printf '\n'
[[ -n "$TOKEN" ]] || { echo "No token entered."; exit 1; }
printf '%s' "$TOKEN" > "$ROOT/.runtime/neco_token"
chmod 600 "$ROOT/.runtime/neco_token"
echo "Token saved."
python3 "$ROOT/scripts/setup-persona.py"
