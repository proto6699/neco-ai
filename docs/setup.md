# setup notes

## install Ollama

Arch/CachyOS:

```bash
sudo pacman -Syu ollama
```

For the Vulkan backend used in the original laptop test, install `ollama-vulkan` too. A package being installed does not prove the GPU is active: check `ollama ps` during generation. Pick the backend appropriate for your GPU.

Debian/Ubuntu, using the [upstream installer](https://docs.ollama.com/linux):

```bash
sudo apt-get update
sudo apt-get install -y curl
curl -fsSL https://ollama.com/install.sh -o /tmp/ollama-install.sh
sh /tmp/ollama-install.sh
```

Then run `./scripts/setup-ollama.sh` from the repo. It reads `NECO_MODEL` from `.env`, writes a dedicated systemd drop-in, restarts Ollama, waits for readiness, and pulls the selected model. It does not overwrite your existing `override.conf`. Review other drop-ins if they override `OLLAMA_HOST`.

The service binds to all interfaces so Docker can reach it. Restrict the unauthenticated port 11434 to trusted sources using your firewall. The Den itself binds only to localhost by default; `OPENWEBUI_BIND=0.0.0.0` deliberately enables LAN listening.

## no models in the Den

In **Admin Settings → Connections → Ollama**, enable the API and verify/save `http://host.docker.internal:11434`. Compose supplies this URL for new installations; existing database settings may override it.

```bash
curl -sS -m 5 http://localhost:11434/api/tags
./scripts/doctor.sh
```

If the host works but the container times out, inspect its subnet:

```bash
sudo docker inspect neco-ai-webui --format '{{range $name, $net := .NetworkSettings.Networks}}{{$name}}{{"\n"}}{{end}}'
# Substitute the printed network name:
sudo docker network inspect NETWORK_NAME --format '{{range .IPAM.Config}}{{.Subnet}}{{"\n"}}{{end}}'
```

With active ufw, substitute that subnet below (the example is a common Docker subnet, not a universal value):

```bash
sudo ufw allow from 172.18.0.0/16 to any port 11434 proto tcp
sudo ufw reload
```

For firewalld, use a port-scoped rich rule in the zone handling this traffic; do not trust all ports unnecessarily. This alternative is untested here:

```bash
sudo firewall-cmd --get-active-zones
sudo firewall-cmd --permanent --zone=public --add-rich-rule='rule family="ipv4" source address="172.18.0.0/16" port port="11434" protocol="tcp" accept'
sudo firewall-cmd --reload
```

Replace the zone and subnet with your actual values.

## downloads and first boot

The installer retries the base-image pull three times. Completed layers are cached; rerun `./install.sh` after a timeout. For persistent trouble, try `sudo docker pull ghcr.io/open-webui/open-webui:v0.11.4` separately.

First boot downloads the `sentence-transformers/all-MiniLM-L6-v2` embedding model. A temporarily unhealthy container can be normal; persistent errors need investigation:

```bash
sudo docker compose logs --tail=100 openwebui
curl -sS -m 5 http://localhost:3300/health
```

Use your configured port if different. A healthy endpoint does not prove model generation works.

## other common failures

- **Docker permission denied:** use `sudo docker compose ...`; do not run the whole installer as root.
- **CachyOS package 404/signature errors:** refresh mirrors with `sudo cachyos-rate-mirrors`, then do a full `sudo pacman -Syu`. Do not disable signature checks.
- **Buildx warning:** ignorable only if the build succeeds. If it fails, install your distribution's Buildx plugin.
- **Invalid API key:** create a key for the admin account and rerun `./scripts/set-token.sh`. Model setup needs model read/create/update access. Never paste the key into an issue.
- **Wrong model:** `NECO_MODEL` must match `ollama list` and be accessible to the key's Open WebUI account. Pulling the repo does not migrate an existing `.env`.
- **Generic personality:** start a new chat after applying the prompt. Saving the system prompt verifies storage, not instruction-following quality. A tiny model may fail a long prompt.
- **Slow replies:** check `ollama ps` while generating and `journalctl -u ollama --no-pager -n 50`. Model size, CPU/GPU placement, prompt length, and memory pressure all matter. Do not assume a larger model will be faster.
- **Neco stops after logout:** `loginctl enable-linger "$USER"`, then `./scripts/start-neco.sh`. Suspend still pauses execution.
- **Music/icon/font missing:** rebuild, then hard-refresh. The files are bundled. For the avatar, rerun `python3 scripts/setup-persona.py`.

## continuity memory

Neco's persistent memory is host-side and local. The daemon writes `.runtime/neco-memory.sqlite3`; the Open WebUI container only receives read-only access through the existing `.runtime` mount.

Useful settings:

```bash
NECO_MEMORY_ENABLED=1
NECO_MEMORY_INTERVAL=30
NECO_MEMORY_BACKFILL=0
NECO_REFLECTION_MODEL=
```

Leave `NECO_MEMORY_BACKFILL=0` for normal upgrades. It prevents existing generated chats from being treated as historical fact. A blank `NECO_REFLECTION_MODEL` uses the current Neco model for consolidation. If a stronger local or API-backed model is already connected to Open WebUI, its model ID can be used instead.

Inspect the local record with:

```bash
python3 scripts/neco-memory.py list
python3 scripts/neco-memory.py state
python3 scripts/neco-memory.py search "project name"
```

If the database contains a bad interpretation, archive or delete that specific memory instead of adding a compensating personality rule. More detail: [Neco continuity](continuity.md).

## alternative backends and customization

LM Studio or llama.cpp can be connected manually as an OpenAI-compatible provider in Open WebUI. Skip `setup-ollama.sh`, set `NECO_MODEL` to the ID exposed by that provider, and verify normal chat before finishing setup. `doctor.sh` currently assumes local Ollama, so its backend checks will fail for alternatives.

`finish-setup.sh` applies the identity/orientation/voice prompt, avatar, vitals + continuity filters, runs a live one-message test, enables linger, starts the daemon, and diagnoses it. It stops on failure rather than announcing success; fix the reported step and rerun. A test may add a message on each run.

The music replacement helper is `./scripts/set-music.sh /path/to/song.mp3`. The bundled track is tracked in Git; a local replacement appears as a modification.

## verification scope

The owner confirmed the CachyOS laptop could chat using the tiny Qwen test model and save its Neco configuration. The new default's full persona quality and speed, clean-machine setup helpers, GPU acceleration, firewalld, Debian/Ubuntu, and reboot survival still need real-machine verification. Automated checks do not substitute for those tests.
