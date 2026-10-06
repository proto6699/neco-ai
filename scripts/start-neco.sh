#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[[ $# -eq 0 || ( $# -eq 1 && "$1" == --configure-only ) ]] || {
  echo 'Usage: start-neco.sh [--configure-only]' >&2
  exit 1
}
[[ -f "$ROOT/.runtime/neco_token" ]] || { echo "Run ./scripts/set-token.sh first."; exit 1; }
[[ -f "$ROOT/neco/heartbeat.py" && -x "$ROOT/neco/.venv/bin/python" ]] || {
  echo 'Run ./install.sh first; the heartbeat and Python environment are required.' >&2
  exit 1
}
SERVICE=neco-ai.service
systemctl --user daemon-reload
# Older installations still point to runtime.py. Keep the unit name and settings,
# but override its entry point after checking that it belongs to this checkout.
WORKDIR="$(systemctl --user show "$SERVICE" --property=WorkingDirectory --value)"
[[ "$WORKDIR" == "$ROOT/neco" ]] || {
  echo 'Neco service is missing or belongs to another directory. Run this installation’s ./install.sh.' >&2
  exit 1
}
python3 - "$ROOT" <<'PY'
import os
from pathlib import Path
import sys
import tempfile

root = Path(sys.argv[1])
config = Path(os.getenv('XDG_CONFIG_HOME') or Path.home() / '.config')
directory = config / 'systemd/user/neco-ai.service.d'
directory.mkdir(parents=True, exist_ok=True)

def quoted(path):
    return '"' + str(path).replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%') + '"'

content = ('[Service]\nExecStart=\nExecStart='
           + quoted(root / 'neco/.venv/bin/python') + ' -u '
           + quoted(root / 'neco/heartbeat.py') + '\n')
fd, temporary = tempfile.mkstemp(dir=directory, prefix='.heartbeat-')
try:
    with os.fdopen(fd, 'w') as handle:
        handle.write(content)
    os.replace(temporary, directory / 'heartbeat.conf')
finally:
    if os.path.exists(temporary):
        os.unlink(temporary)
PY
systemctl --user daemon-reload
[[ "${1:-}" != --configure-only ]] || exit 0
systemctl --user enable "$SERVICE"
systemctl --user restart "$SERVICE"
systemctl --user --no-pager --full status "$SERVICE" || true
