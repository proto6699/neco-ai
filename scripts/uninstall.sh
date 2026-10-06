#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
systemctl --user disable --now neco-ai.service 2>/dev/null || true
rm -f "$HOME/.config/systemd/user/neco-ai.service"
systemctl --user daemon-reload
cd "$ROOT"
docker compose down
echo "Stopped. Data volume and local config were kept."
