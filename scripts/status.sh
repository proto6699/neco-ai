#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
echo "== the den =="
docker compose ps || true
echo
echo "== neco =="
systemctl --user --no-pager --full status neco-ai.service || true
