#!/usr/bin/env bash
# Configure the local systemd Ollama backend and pull the model selected in .env.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
[[ -f .env ]] || { echo 'Run ./install.sh first.' >&2; exit 1; }
if ! command -v ollama >/dev/null; then
    echo 'Ollama is missing. Install it using docs/setup.md, then rerun this command.' >&2
    exit 1
fi
MODEL="$(python3 - <<'PY'
from pathlib import Path
import shlex
for line in Path('.env').read_text().splitlines():
    if line.startswith('NECO_MODEL='):
        value = shlex.split(line.split('=', 1)[1], comments=True)
        if len(value) == 1 and value[0] and not value[0].startswith('-'):
            print(value[0])
            break
else:
    raise SystemExit('Set NECO_MODEL in .env first.')
PY
)"
[[ -n "$MODEL" ]] || { echo 'NECO_MODEL is empty or invalid.' >&2; exit 1; }
echo "Configuring local Ollama for Docker. Default model download: about 2 GB. Selected: $MODEL"
echo 'Ollama will listen on all interfaces; keep port 11434 restricted to trusted clients/Docker.'
sudo mkdir -p /etc/systemd/system/ollama.service.d
printf '[Service]\nEnvironment="OLLAMA_HOST=0.0.0.0:11434"\n' | sudo tee /etc/systemd/system/ollama.service.d/neco-ai.conf >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable --now ollama
sudo systemctl restart ollama
# Target the same local service as the Den, even if the shell has a remote OLLAMA_HOST.
ready=false
for attempt in {1..15}; do
    if OLLAMA_HOST=127.0.0.1:11434 ollama list >/dev/null 2>&1; then ready=true; break; fi
    sleep 1
done
[[ "$ready" == true ]] || { echo 'Ollama did not become ready. Check journalctl -u ollama --no-pager.' >&2; exit 1; }
if ! OLLAMA_HOST=127.0.0.1:11434 ollama pull "$MODEL"; then
    echo
    echo "'$MODEL' is not an Ollama model."
    echo "If it's an API model (e.g. DeepSeek), you don't need this step: add the provider under"
    echo "Admin Panel -> Settings -> Connections in the Den, then run ./scripts/finish-setup.sh."
    echo "If you meant a local model, fix the name with ./scripts/change-cat.sh and rerun this."
    exit 1
fi
echo 'Model ready. Open the Den and verify one normal chat.'
echo 'If the Den cannot see it, check docs/setup.md (firewall / connection).'
