# Repository structure

[Experiment overview](../README.md) · [Continuity](continuity.md)

The source names describe the mechanisms. Each cat's starting character lives under
`characters/<cat>/`; accumulated records live in the local `.runtime/` directory.
There is no self-written character file yet.

| Area | Contents |
|---|---|
| Root | `install.sh`, `compose.yaml`, settings template, README, and licensing. |
| `characters/<cat>/` | `character.conf` (name, blurb), authored `identity.md`, `voice.md`, compact `lite.md`, optional local `avatar.png`. |
| `characters/_shared/` | `values.md` shared by every cat, and the placeholder avatar. |
| `neco/` | `heartbeat.py`, `wandering.py`, `machine.py`, prompt composition, and Python dependencies. |
| `neco/memory/` | SQLite storage in `store.py` and the conversation worker in `consolidation.py`. |
| `openwebui/functions/` | Read-only request filters: `recall.py` and `senses.py`. |
| `openwebui/overlay/` | Frontend entry file, avatar, music, fonts, and other static assets. |
| `scripts/` | Installation, model configuration, service management, diagnostics, and memory inspection. |
| `tests/` | Memory, machine-reading, and service-migration checks. |

## Data created during use

| Location | Purpose |
|---|---|
| `.env` | Actual local settings; excluded from Git. |
| `.runtime/neco_token` | API credential; excluded from Git. |
| `.runtime/memory/<cat>.sqlite3` | Each cat's memory records, evolving state, and processing markers. |
| `.runtime/neco-memory.sqlite3` | Link to the active cat's database (what the recall filter reads). |
| `.runtime/system-vitals.json` | Latest machine snapshot. |
| `.runtime/neco_state.json` | Idle reaction bookkeeping, separate from evolving memory state. |
| `neco/.venv/` | Local Python dependencies. |
| Docker volume `neco-ai-webui-data` | Open WebUI conversations and configuration. |

The systemd user unit (`neco-ai.service`) lives outside the checkout in `~/.config/systemd/user/`.
