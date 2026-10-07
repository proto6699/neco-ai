#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

die() {
    echo "error: $*" >&2
    exit 1
}

say() {
    echo "$*"
}

install_host_deps() {
    # Already good? Don't touch the package manager.
    if command -v docker >/dev/null 2>&1        && (docker compose version >/dev/null 2>&1 || command -v docker-compose >/dev/null 2>&1)        && command -v python3 >/dev/null 2>&1        && python3 -m venv --help >/dev/null 2>&1; then
        return
    fi

    [[ -r /etc/os-release ]] || die "Can't identify this Linux distribution."
    # shellcheck disable=SC1091
    source /etc/os-release

    local family="${ID:-} ${ID_LIKE:-}"

    echo
    echo "some host dependencies are missing."
    printf "install Docker / Compose / Python bits now? [Y/n] "
    read -r answer
    answer="${answer:-Y}"

    case "$answer" in
        y|Y|yes|YES) ;;
        *) die "Install cancelled." ;;
    esac

    if [[ "$family" == *"arch"* ]]; then
        sudo pacman -Syu --needed docker docker-compose python
    elif [[ "$family" == *"ubuntu"* ]]; then
        sudo apt-get update
        sudo apt-get install -y docker.io docker-compose-v2 python3 python3-venv
    elif [[ "$family" == *"debian"* ]]; then
        sudo apt-get update
        # Debian versions differ on the Compose package name.
        if ! sudo apt-get install -y docker.io docker-compose-v2 python3 python3-venv; then
            sudo apt-get install -y docker.io docker-compose python3 python3-venv
        fi
    else
        die "Automatic dependency install currently supports Arch/CachyOS/EndeavourOS and Debian/Ubuntu. Install Docker, Compose, Python 3 + venv, then rerun ./install.sh."
    fi
}

install_host_deps

command -v docker >/dev/null 2>&1 || die "Docker is still unavailable."
command -v python3 >/dev/null 2>&1 || die "Python 3 is still unavailable."
command -v systemctl >/dev/null 2>&1 || die "systemd/systemctl is required."

RUNNING_KERNEL="$(uname -r)"
if [[ ! -d "/lib/modules/$RUNNING_KERNEL" ]]; then
    echo
    echo "kernel/module mismatch detected."
    echo "running kernel:  $RUNNING_KERNEL"
    echo "modules for that kernel are missing from /lib/modules."
    echo
    die "The kernel was probably upgraded while this system was still running. Reboot, then rerun ./install.sh."
fi

[[ -f neco/heartbeat.py ]] || die "Missing Neco entry point: neco/heartbeat.py."
[[ -f neco/wandering.py ]] || die "Missing Neco module: neco/wandering.py."
[[ -f neco/prompt.py ]] || die "Missing Neco prompt composer: neco/prompt.py."
[[ -f neco/memory/store.py ]] || die "Missing Neco memory store: neco/memory/store.py."
[[ -f neco/memory/consolidation.py ]] || die "Missing Neco memory worker: neco/memory/consolidation.py."
[[ -f neco/requirements.txt ]] || die "Missing neco/requirements.txt."
[[ -f openwebui/functions/recall.py ]] || die "Missing Neco memory filter."
[[ -f openwebui/overlay/index.html ]] || die "Missing Den UI."

# Docker's daemon may exist but not be running yet.
if ! sudo systemctl is-active --quiet docker; then
    say "[+] starting Docker"
    sudo systemctl reset-failed docker 2>/dev/null || true

    if ! sudo systemctl enable --now docker; then
        echo
        echo "Docker failed to start. Recent daemon errors:"
        echo "---------------------------------------------"
        sudo journalctl -u docker.service -n 80 --no-pager 2>/dev/null \
            | grep -Ei 'error|failed|fatal|daemon|iptables|nft|overlay|bridge|network' \
            | tail -40 || true
        echo "---------------------------------------------"
        echo
        die "Docker daemon failed to start. The log above contains the real cause."
    fi
fi

# Enable boot startup even when Docker was already running.
sudo systemctl enable docker

# Use Docker directly when the current user already has permission.
# Otherwise use sudo for this installation instead of forcing a logout/login.
if docker info >/dev/null 2>&1; then
    DOCKER=(docker)
else
    DOCKER=(sudo docker)
    say "[i] using sudo for Docker during this install"
    say "[i] optional later: sudo usermod -aG docker \$USER  (then log out/in)"
fi

if "${DOCKER[@]}" compose version >/dev/null 2>&1; then
    compose() {
        "${DOCKER[@]}" compose "$@"
    }
elif command -v docker-compose >/dev/null 2>&1; then
    if [[ "${DOCKER[0]}" == "sudo" ]]; then
        compose() {
            sudo docker-compose "$@"
        }
    else
        compose() {
            docker-compose "$@"
        }
    fi
else
    die "Docker Compose is still unavailable."
fi

# Questions first, so nothing heavy downloads before the choices are made.
# Rerun later with ./scripts/change-cat.sh.
if [[ ! -f .env || "${1:-}" == --reconfigure ]]; then
    ./scripts/configure.sh
elif [[ ! -f openwebui/overlay/static/den-neco.png ]]; then
    ./scripts/configure.sh --defaults
fi

python3 - .env <<'PY'
from pathlib import Path
import secrets
import sys

p = Path(sys.argv[1])
lines = p.read_text().splitlines()
out = []
found = False

for line in lines:
    if line.startswith("WEBUI_SECRET_KEY="):
        found = True
        if not line.split("=", 1)[1].strip():
            line = "WEBUI_SECRET_KEY=" + secrets.token_hex(32)
    out.append(line)

if not found:
    out.append("WEBUI_SECRET_KEY=" + secrets.token_hex(32))

p.write_text("\n".join(out) + "\n")
PY

chmod 600 .env
mkdir -p .runtime
chmod 700 .runtime

say "[+] creating Neco Python environment"
python3 -m venv neco/.venv
neco/.venv/bin/python -m pip install --upgrade pip
neco/.venv/bin/pip install -r neco/requirements.txt

say "[i] data warning: the Open WebUI base image is several GB."
say "[i] first boot also downloads an embedding model; Ollama models are separate."
say "[i] on metered data, press Ctrl-C now and rerun later; completed image layers are kept."
# Read the pinned image from the Dockerfile so retries follow future version bumps.
BASE_IMAGE="$(awk 'toupper($1) == "FROM" {print $2; exit}' openwebui/Dockerfile)"
[[ -n "$BASE_IMAGE" ]] || die "No base image found in openwebui/Dockerfile."
for attempt in 1 2 3; do
    say "[+] pulling $BASE_IMAGE (attempt $attempt/3)"
    if "${DOCKER[@]}" pull "$BASE_IMAGE"; then
        break
    fi
    if [[ "$attempt" == 3 ]]; then
        die "Base image pull failed after 3 attempts. Rerun ./install.sh on a stable connection; completed layers are cached. See README troubleshooting."
    fi
    say "[i] pull failed; retrying in 5 seconds"
    sleep 5
done

say "[+] building the Den"
compose up -d --build

mkdir -p "$HOME/.config/systemd/user"

cat > "$HOME/.config/systemd/user/neco-ai.service" <<EOF
[Unit]
Description=neco-ai idle daemon
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$ROOT/neco
EnvironmentFile=$ROOT/.env
Environment=NECO_TOKEN_FILE=$ROOT/.runtime/neco_token
Environment=NECO_STATE_FILE=$ROOT/.runtime/neco_state.json
ExecStart=$ROOT/neco/.venv/bin/python -u $ROOT/neco/heartbeat.py
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
EOF

if [[ -s .runtime/neco_token ]]; then
    say "[+] applying Neco personality to the configured model"
    if ! python3 scripts/setup-persona.py; then
        say "[i] once the Den is ready, retry: python3 scripts/setup-persona.py"
    fi
fi

systemctl --user daemon-reload
systemctl --user stop neco-ai.service 2>/dev/null || true

PORT="$(python3 - .env <<'PY'
from pathlib import Path
port = "3300"
for line in Path(".env").read_text().splitlines():
    if line.startswith("OPENWEBUI_PORT="):
        port = line.split("=", 1)[1].strip().strip('"').strip("'") or "3300"
print(port)
PY
)"

echo
echo "========================================"
echo " the Den container has started"
echo "========================================"
echo
echo "open:"
echo "  http://localhost:$PORT"
echo
echo "then:"
echo "  1. ./scripts/setup-ollama.sh  (local Ollama; installation help: docs/setup.md)"
echo "  2. open the Den, create your account, and verify a normal chat"
echo "     Ollama URL: http://host.docker.internal:11434"
echo "  3. create an API key in Settings > Account > API keys"
echo "  4. ./scripts/finish-setup.sh"
echo
echo "First boot can be unhealthy while the embedding model downloads."
echo "Neco is not running yet; finish-setup applies her identity, continuity filters, tests, and starts her."
