# Full installation walkthrough

[Back to the Den](../README.md) · [Troubleshooting](setup.md)

## install

Linux with systemd. The installer can add Docker, Compose, and Python on Arch/CachyOS or Debian/Ubuntu. **Ollama must be installed separately**; Compose starts the Den, not Ollama.

First download: several GB for Open WebUI, about **1.3 GB for the default model**, plus an embedding model on first boot.

Run each step as your normal user, and wait for it to finish before continuing. The scripts ask for sudo when needed. They are Bash scripts; `bash script-name` also works when your terminal uses fish. Do not run the whole installer with sudo.

### 1. Download the repo

```bash
git clone https://github.com/proto6699/neco-ai.git
cd neco-ai
```

Already cloned it? Start with `cd ~/neco-ai`. Keep running the following commands from that folder.

### 2. Install and start Ollama

On **Arch/CachyOS**:

```bash
sudo pacman -Syu ollama
sudo systemctl enable --now ollama
```

For GPU backend options or Debian/Ubuntu installation, see [setup notes](setup.md). Installing a GPU backend does not prove GPU acceleration is active.

If a command fails, stop and fix the reported error before continuing.

### 3. Install the Den and Neco dependencies

```bash
bash ./install.sh
```

This creates `.env` if missing, generates the WebUI secret, creates Neco's Python environment, builds the Den, and registers Neco's user service. Existing `.env` settings are preserved.

Wait for **“the Den container has started.”** A Buildx warning can be ignored if the build succeeds. Docker permission messages are handled by the installer using sudo.

### 4. Configure Ollama and download the model

```bash
bash ./scripts/setup-ollama.sh
```

This reads `NECO_MODEL` from `.env`, configures Ollama for Docker access, enables/restarts its service, and downloads the selected model. It binds Ollama to all interfaces; restrict port 11434 to trusted clients and Docker using your firewall. See [setup notes](setup.md).

Verify the local backend before activating Neco:

```bash
OLLAMA_HOST=127.0.0.1:11434 ollama list
curl -sS -m 5 http://localhost:11434/api/tags
```

Both should list **`llama3.1:8b`** on a fresh install, or the model selected in your existing `.env`.

### 5. Create your account and test a chat

Open **http://localhost:3000**:

1. Create your account; the first account is admin.
2. Select **llama3.1:8b** (or your configured model), send `hey`, and wait for a reply.
3. Create an API key under **Settings → Account → API keys**.

First boot may take a few minutes while the embedding model downloads. If no model appears, go to **Admin Settings → Connections → Ollama**, enable the API, and save `http://host.docker.internal:11434`. Then refresh. If it still fails, follow [connection troubleshooting](setup.md).

### 6. Apply Neco's persona and start her

```bash
bash ./scripts/finish-setup.sh
```

Paste the API key into the terminal when asked; do not post it publicly. An existing saved key is reused.

This applies Neco's identity/orientation/voice prompt, avatar, read-only vitals filter, and continuity-memory filter; then it generates a test thought, enables startup after logout/reboot, and runs diagnostics. The host daemon also starts the local SQLite memory worker. It stops if a step fails. Once the problem is fixed, rerun the same command.

The default uses `NECO_PERSONA=full`. If you switch to a tiny model such as `llama3.2:1b`, set `NECO_PERSONA=lite` in `.env` before this step.

Refresh the Den and start a **new chat** with Neco (or the existing model name). Click **DEN MUSIC** for the bundled soundtrack. No manual prompt pasting, image uploads, or music copying.

Persistent continuity starts with new exchanges by default; old chats are deliberately not imported as memories. See [Neco continuity](continuity.md) for how retrieval, consolidation, inspection, and correction work.

### 7. Check everything

```bash
bash ./scripts/doctor.sh
```

If persona setup says **“NECO_MODEL is not available to this account”**, verify Ollama first:

```bash
sudo systemctl enable --now ollama
bash ./scripts/setup-ollama.sh
```

Then verify a normal chat in the Den and rerun `bash ./scripts/finish-setup.sh`. If Ollama cannot start, inspect `sudo journalctl -u ollama --no-pager -n 80`. Do not delete/reclone the repo to fix a stopped service.

For manual Docker checks, use `sudo docker compose ps` if your user cannot access Docker. [More troubleshooting →](setup.md)
