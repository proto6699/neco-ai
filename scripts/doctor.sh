#!/usr/bin/env bash
# Read-only diagnostics. Run as the user who installed Neco, not with sudo.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
command -v python3 >/dev/null || { echo '[FAIL] Python 3 is required.'; exit 1; }
exec python3 - "$ROOT" <<'PY'
import getpass
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import urllib.request

root = Path(sys.argv[1])
failures = 0

def report(ok, label, hint=''):
    global failures
    print(f'[{"PASS" if ok else "FAIL"}] {label}', flush=True)
    if not ok:
        failures += 1
        if hint:
            print(f'       {hint}', flush=True)

def run(args, timeout=10):
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return p.returncode == 0, p.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return False, ''

# Read only the two settings needed here; never source .env or print its contents.
settings = {}
env_ok = True
try:
    for line in (root / '.env').read_text().splitlines():
        key, sep, value = line.partition('=')
        if sep and key.strip() in ('NECO_MODEL', 'OPENWEBUI_PORT'):
            words = shlex.split(value, comments=True)
            settings[key.strip()] = words[0] if len(words) == 1 else ''
except (OSError, ValueError):
    env_ok = False
report(env_ok, '.env readable', 'Run ./install.sh; check quoting in .env.')
model = settings.get('NECO_MODEL', '')
report(bool(model), 'NECO_MODEL configured', 'Set NECO_MODEL in .env to the exact name in ollama list.')

for unit in ('docker', 'ollama'):
    for state in ('active', 'enabled'):
        ok, _ = run(['systemctl', '--no-pager', f'is-{state}', '--quiet', unit])
        report(ok, f'{unit} service {state}', f'sudo systemctl enable --now {unit}')

ok, sockets = run(['ss', '-H', '-ltn'])
# ss local-address is column four. Match wildcard IPv4/IPv6 listeners, not localhost.
wildcard = any(len(row.split()) >= 4 and row.split()[3] in
               ('0.0.0.0:11434', '*:11434', '[::]:11434', ':::11434')
               for row in sockets.splitlines())
report(ok and wildcard, 'Ollama port 11434 listening on all interfaces',
       'See README model backend drop-in and restart Ollama; ss must be installed.')

try:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open('http://127.0.0.1:11434/api/tags', timeout=5) as response:
        data = json.load(response)
    names = {item.get('name') for item in data['models']}
    report(True, 'host can reach Ollama')
    report(bool(model) and model in names, 'configured model exists in host Ollama',
           'Pull the exact NECO_MODEL from .env with ollama pull, then check ollama list.')
except (OSError, ValueError, KeyError, TypeError, AttributeError):
    report(False, 'host Ollama API/model check', 'Check curl -sS -m 5 http://localhost:11434/api/tags.')

docker = ['docker']
ok, _ = run(docker + ['info'])
if not ok and shutil.which('sudo'):
    print('[INFO] Trying cached sudo for Docker; run sudo -v first if needed.', flush=True)
    # Never hang waiting for a password; keep systemd user checks unprivileged.
    try:
        authorized = subprocess.run(['sudo', '-n', '-v'],
                                    timeout=30).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        authorized = False
    if authorized:
        docker = ['sudo', '-n', 'docker']
        ok, _ = run(docker + ['info'])
report(ok, 'Docker daemon accessible', 'Start Docker; run sudo -v then rerun this script as your normal user.')
if ok:
    probe = '''import json, urllib.request
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
with opener.open("http://host.docker.internal:11434/api/tags", timeout=5) as response:
    print(json.dumps(json.load(response)))
'''
    reached, output = run(docker + ['exec', 'neco-ai-webui', 'python', '-c', probe])
    try:
        names = {item.get('name') for item in json.loads(output)['models']} if reached else set()
    except (ValueError, KeyError, TypeError, AttributeError):
        reached, names = False, set()
    report(reached, 'container can reach host Ollama (5-second HTTP timeout)',
           'Check container startup, host.docker.internal, Ollama binding and the README firewall rules.')
    report(reached and bool(model) and model in names, 'configured model visible from container',
           'Host/container must reach the same Ollama instance with NECO_MODEL installed.')
else:
    report(False, 'container Ollama check unavailable', 'Fix Docker access first.')

port = settings.get('OPENWEBUI_PORT', '3300')
try:
    if not re.fullmatch(r'[0-9]{1,5}', port) or not 1 <= int(port) <= 65535:
        raise ValueError('invalid port')
    with opener.open(f'http://127.0.0.1:{port}/health', timeout=5) as response:
        healthy = response.status == 200
    report(healthy, 'Den health endpoint ready', 'Inspect sudo docker compose logs --tail=100 openwebui.')
except (OSError, ValueError):
    report(False, 'Den health endpoint ready', 'Check OPENWEBUI_PORT and first-boot embedding download logs.')

try:
    token_ok = bool((root / '.runtime/neco_token').read_text().strip())
except (OSError, UnicodeError):
    token_ok = False
report(token_ok, 'token file readable and nonempty (contents hidden)', './scripts/set-token.sh')

continuity_files = (
    root / 'characters/neco/identity.md',
    root / 'characters/_shared/values.md',
    root / 'characters/neco/voice.md',
    root / 'neco/memory/store.py',
    root / 'neco/memory/consolidation.py',
    root / 'openwebui/functions/recall.py',
)
report(all(path.is_file() for path in continuity_files), 'Neco continuity components present',
       'Pull the latest repo files, then rerun ./scripts/finish-setup.sh.')
for state in ('enabled', 'active'):
    ok, _ = run(['systemctl', '--user', '--no-pager', f'is-{state}', '--quiet',
                 'neco-ai.service'])
    report(ok, f'Neco user service {state}', './scripts/start-neco.sh after setting the token and testing.')
ok, linger = run(['loginctl', '--no-pager', 'show-user', str(os.getuid()), '-p', 'Linger', '--value'])
report(ok and linger == 'yes', 'linger enabled', f'loginctl enable-linger {shlex.quote(getpass.getuser())}')
print(f'\n{failures} failed check(s). Token validity, generation, GPU use and reboot survival need live tests.')
sys.exit(1 if failures else 0)
PY
