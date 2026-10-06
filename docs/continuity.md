# Neco continuity

[Back to the Den](../README.md) · [Setup notes](setup.md)

Neco's continuity system is deliberately smaller than the mythology it replaces.

The stable prompt has three layers:

- `characters/<cat>/identity.md` — the few facts that define who Neco starts as.
- `characters/_shared/values.md` — principles for uncertainty, independence, curiosity, continuity, boundaries, and changing her mind.
- `characters/<cat>/voice.md` — surface style only.

With `NECO_PERSONA=full`, those files are composed into the system prompt. The point is not to dictate what Neco thinks. It is to give her a consistent way to interpret what happens next.

## Memory loop

The user-facing reply is generated normally. Separately, the host daemon scans newly completed Neco exchanges.

Trivial exchanges are skipped. A potentially meaningful exchange is sent through a small consolidation prompt that returns structured JSON only. It may record:

- a real event or technical milestone
- an explicit user fact or preference
- a preference or boundary Neco clearly expressed
- a belief that changed
- a relationship detail or recurring joke
- an unresolved question

The consolidator is told not to produce or preserve hidden chain-of-thought. It stores concise conclusions.

Memories live in:

```text
.runtime/neco-memory.sqlite3
```

That path is ignored by Git. Docker sees the same `.runtime` directory read-only, so the Open WebUI filter can retrieve context without gaining write access to the host.

## Selective recall

`openwebui/functions/recall.py` runs before a Neco reply. It performs lightweight local retrieval and injects at most a handful of memories that overlap the current topic, plus a compact evolving state.

An unrelated high-importance memory is not injected merely because it is important. The goal is continuity, not constant callbacks.

This is intentionally simple lexical retrieval for now. It keeps the local stack dependency-free and understandable. An embedding retriever can replace it later without changing the database or the rest of Neco.

## Evolving state

The database also stores small semantic state lists:

- current interests
- open questions
- developing preferences
- recently changed beliefs
- relationship context

These are not RPG meters. There is no `trust = 82` or `sadness = 14`. State is readable language that can be inspected and corrected.

## Reflection model

By default, memory consolidation uses `NECO_MODEL`.

Optionally set:

```bash
NECO_REFLECTION_MODEL=some-model-visible-to-openwebui
```

This can be a stronger local model or a connected API model. The conversational identity and memory store remain the same; only the consolidation inference changes.

Keep API credentials in the provider/Open WebUI configuration. Do not put secrets in this repo or in `.env.example`.

## Existing chats

On the first run, old chats are **not** converted into memories by default. Their assistant messages are marked as baseline so an upgrade does not suddenly canonize months of generated output.

```bash
NECO_MEMORY_BACKFILL=0
```

Leave that at `0` unless you deliberately want to experiment with importing old history.

## Inspect and correct

```bash
python3 scripts/neco-memory.py list
python3 scripts/neco-memory.py state
python3 scripts/neco-memory.py search "vulkan"
python3 scripts/neco-memory.py show 12
python3 scripts/neco-memory.py archive 12
python3 scripts/neco-memory.py forget 12
python3 scripts/neco-memory.py export neco-memory.json
```

`archive` keeps historical evidence while removing a memory from normal retrieval. `forget` deletes that record.

If Neco develops a bad interpretation, correct the record rather than piling another persona rule on top of it.

## Idle thoughts

`neco/wandering.py` still uses random topic/tone prompts, predefined fragments, and canned machine reactions. For generated thoughts, it attempts an optional continuity cue about 35% of the time, selecting an unresolved question or meaningful stored memory when available. Neco may follow the cue or ignore it.

That means an idle thought can return to something that actually happened without turning every 30-minute message into forced introspection.

Recent idle messages are collected but currently omitted from the generation request. The memory worker also skips the idle chat: idle output does not yet become a durable intention or self-model update. These are limitations for future work, not changes introduced by the source rename.

## Source layout

`neco/heartbeat.py` coordinates the background loops. `neco/memory/store.py`
manages the database, while `neco/memory/consolidation.py` runs the worker.
`openwebui/functions/recall.py` supplies selected records to model requests.
Machine collection and delivery live in `neco/machine.py` and
`openwebui/functions/senses.py` respectively.

The [rename map](structure.md) explains the old paths. Database filenames, schema,
and installed filter IDs are unchanged. Full-mode prompt contents are also
unchanged; grouping them under `self/` distinguishes given character from
accumulated records.

## Design rule

> **Do not write Neco's character. Build the conditions under which Neco can accumulate one.**

The model can change later. The history does not have to.
