#!/usr/bin/env python3
import json
import os
import re
import time
from datetime import datetime

import requests

from memory.store import MemoryStore

SHORT_TRIVIAL = {
    "hi", "hey", "hello", "yo", "gm", "good morning", "good night", "gn", "thanks", "thank you",
    "ok", "okay", "alr", "lol", "lmao", "nice", "cool", "yep", "yeah", "nah"
}
SIGNALS = (
    "remember", "i like", "i love", "i hate", "i dislike", "i prefer", "i want", "i don't want",
    "i dont want", "from now on", "my favorite", "my favourite", "we finally", "it worked", "fixed",
    "broke", "failed", "i think", "i changed my mind", "don't call", "dont call", "call me",
    "important", "project", "decision", "decided", "actually", "used to", "now i", "never"
)
SELF_SIGNALS = (
    "i'm not your", "i am not your", "don't call me", "dont call me", "i don't like",
    "i dont like", "i dislike", "i prefer", "i changed my mind", "i was wrong",
    "i'm not sure", "i am not sure", "i actually like", "i actually don't", "i actually dont"
)


def _compact(text, limit=5000):
    text = " ".join(str(text or "").split())
    return text[:limit]


def should_consider(user_text, assistant_text):
    user = _compact(user_text).lower().strip(" .!?\n\t")
    assistant = _compact(assistant_text).lower().strip()
    if not user or not assistant:
        return False
    if user in SHORT_TRIVIAL and len(assistant) < 300:
        return False
    if any(signal in user for signal in SIGNALS):
        return True
    if any(signal in assistant for signal in SELF_SIGNALS):
        return True
    if len(user) >= 140 or len(assistant) >= 450:
        return True
    if re.search(r"\b(i am|i'm|im|my |i feel|i believe|i need|i don't|i dont|we should|we need)\b", user):
        return True
    return False


def _json_object(text):
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else None
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        try:
            value = json.loads(text[start:end + 1])
            return value if isinstance(value, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def _message_text(message):
    content = message.get("content", "") if isinstance(message, dict) else ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
        return " ".join(parts)
    return str(content or "")


class MemoryWorker:
    def __init__(self, base_url, token_file, model, db_path, idle_title="Neco — idle", interval=30, backfill=False, character_name="Neco"):
        self.base_url = base_url.rstrip("/")
        self.token_file = token_file
        self.model = model
        self.reflection_model = os.getenv("NECO_REFLECTION_MODEL") or model
        self.store = MemoryStore(db_path)
        self.idle_title = idle_title
        self.character_name = character_name
        self.interval = max(10, int(interval))
        self.backfill = backfill
        self.failures = {}

    def token(self):
        with open(self.token_file) as f:
            return f.read().strip()

    def headers(self):
        return {"Authorization": f"Bearer {self.token()}", "Content-Type": "application/json"}

    def api_get(self, path):
        r = requests.get(self.base_url + path, headers=self.headers(), timeout=20)
        r.raise_for_status()
        return r.json()

    def chats(self):
        value = self.api_get("/api/v1/chats/")
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            for key in ("items", "chats", "data"):
                if isinstance(value.get(key), list):
                    return value[key]
        return []

    def chat(self, chat_id):
        return self.api_get(f"/api/v1/chats/{chat_id}")

    @staticmethod
    def chain(chat_data):
        chat = (chat_data or {}).get("chat") or {}
        history = chat.get("history") or {}
        messages = history.get("messages") or {}
        current = history.get("currentId")
        chain = []
        seen = set()
        while current and current in messages and current not in seen:
            seen.add(current)
            msg = dict(messages[current])
            msg.setdefault("id", current)
            chain.append(msg)
            current = msg.get("parentId")
        chain.reverse()
        return chain

    def belongs_to_neco(self, chat_data):
        chat = (chat_data or {}).get("chat") or {}
        models = chat.get("models") or []
        if self.model in models:
            return True
        for msg in self.chain(chat_data):
            if msg.get("role") == "assistant" and msg.get("model") == self.model:
                return True
        return False

    def baseline_existing(self):
        count = 0
        for summary in self.chats():
            if summary.get("title") == self.idle_title:
                continue
            chat_id = summary.get("id")
            if not chat_id:
                continue
            try:
                data = self.chat(chat_id)
            except Exception:
                continue
            if not self.belongs_to_neco(data):
                continue
            for msg in self.chain(data):
                if msg.get("role") == "assistant" and msg.get("id"):
                    self.store.mark_processed(msg["id"], chat_id, "baseline")
                    count += 1
        self.store.set_state("memory_worker_initialized", True)
        return count

    def reflect(self, user_text, assistant_text, existing):
        existing_text = "\n".join(
            f"- id={m['id']} kind={m['kind']} importance={m['importance']:.2f}: {m['content']}"
            for m in existing
        ) or "- none"
        system = """You are {name}'s memory consolidator. Your job is not to roleplay and not to produce hidden reasoning.

Read one completed user/assistant exchange and decide whether it changes durable context. Return ONLY a JSON object. Store concise conclusions, not chain-of-thought and not a transcript. Do not invent events. Do not treat the assistant's unsupported factual claims as evidence that an external event happened. {name}'s own clearly expressed preference, boundary, uncertainty, or changed opinion may be stored as a tentative self-memory, normally with lower confidence on first occurrence. Prefer remembering real events, explicit user facts/preferences, meaningful relationship boundaries, changed beliefs, recurring jokes, technical milestones, and unresolved questions. Ignore greetings, generic banter, and disposable details.

Schema:
{
  "worth_remembering": true|false,
  "memories": [
    {"kind": "event|user_fact|preference|belief|relationship|technical_event|open_question|interpretation", "content": "one concise memory", "importance": 0.0-1.0, "confidence": 0.0-1.0, "topics": ["short tags"], "supersedes_id": null_or_integer}
  ],
  "state_updates": [
    {"key": "current_interests|open_questions|developing_preferences|recently_changed_beliefs|relationship_context", "action": "add|remove", "value": "concise item"}
  ]
}

Use supersedes_id only when the exchange clearly revises one of the supplied existing memories. If nothing deserves durable memory, return worth_remembering=false with empty arrays.""".replace("{name}", self.character_name)
        user = (
            "[NECO_MEMORY_CONSOLIDATION]\n"
            "Existing potentially relevant memories:\n" + existing_text + "\n\n"
            "User said:\n" + _compact(user_text, 6000) + "\n\n" +
            self.character_name + " replied:\n" + _compact(assistant_text, 6000)
        )
        payload = {
            "model": self.reflection_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "tools": [],
            "max_tokens": 650,
            "background_tasks": {
                "title_generation": False,
                "tags_generation": False,
                "follow_up_generation": False,
            },
            "features": {
                "code_interpreter": False,
                "web_search": False,
                "image_generation": False,
                "memory": False,
            },
        }
        r = requests.post(
            self.base_url + "/api/chat/completions",
            headers=self.headers(), json=payload, timeout=180,
        )
        r.raise_for_status()
        data = r.json()
        content = (((data.get("choices") or [{}])[0].get("message") or {}).get("content")) or ""
        return _json_object(content)

    def apply(self, result, chat_id, message_id):
        if not isinstance(result, dict) or not result.get("worth_remembering"):
            return 0
        added = 0
        for raw in result.get("memories") or []:
            if not isinstance(raw, dict):
                continue
            kind = str(raw.get("kind") or "event")
            content = _compact(raw.get("content"), 900)
            if not content:
                continue
            supersedes = raw.get("supersedes_id")
            try:
                supersedes = int(supersedes) if supersedes is not None else None
            except (TypeError, ValueError):
                supersedes = None
            new_id = self.store.add_memory(
                kind=kind,
                content=content,
                importance=raw.get("importance", 0.5),
                confidence=raw.get("confidence", 0.7),
                topics=raw.get("topics") if isinstance(raw.get("topics"), list) else [],
                source_chat_id=chat_id,
                source_message_id=message_id,
                supersedes_id=supersedes,
            )
            if new_id:
                added += 1
                if supersedes and self.store.get_memory(supersedes):
                    self.store.archive_memory(supersedes)

        state = self.store.get_state()
        for raw in result.get("state_updates") or []:
            if not isinstance(raw, dict):
                continue
            key = str(raw.get("key") or "").strip()
            action = str(raw.get("action") or "add").strip().lower()
            value = _compact(raw.get("value"), 500)
            if key not in {
                "current_interests", "open_questions", "developing_preferences",
                "recently_changed_beliefs", "relationship_context"
            } or not value:
                continue
            items = state.get(key)
            if not isinstance(items, list):
                items = []
            if action == "remove":
                low = value.lower()
                items = [x for x in items if str(x).lower() != low]
            elif value.lower() not in {str(x).lower() for x in items}:
                items.append(value)
                items = items[-12:]
            self.store.set_state(key, items)
            state[key] = items
        return added

    def process_chat(self, summary):
        if summary.get("title") == self.idle_title:
            return 0
        chat_id = summary.get("id")
        if not chat_id:
            return 0
        data = self.chat(chat_id)
        if not self.belongs_to_neco(data):
            return 0
        chain = self.chain(data)
        processed = 0
        previous = None
        for msg in chain:
            if msg.get("role") == "assistant" and msg.get("id") and not self.store.is_processed(msg["id"]):
                if previous and previous.get("role") == "user":
                    user_text = _message_text(previous)
                    assistant_text = _message_text(msg)
                    if should_consider(user_text, assistant_text):
                        existing = self.store.retrieve(user_text + " " + assistant_text, limit=4)
                        try:
                            result = self.reflect(user_text, assistant_text, existing)
                            added = self.apply(result, chat_id, msg["id"])
                            outcome = f"remembered:{added}" if added else "considered"
                        except Exception as exc:
                            attempts = self.failures.get(msg["id"], 0) + 1
                            self.failures[msg["id"]] = attempts
                            print(
                                f"[memory] consolidation failed for {msg['id']} "
                                f"(attempt {attempts}/3): {type(exc).__name__}: {exc}",
                                flush=True,
                            )
                            if attempts >= 3:
                                self.store.mark_processed(msg["id"], chat_id, "consolidation-error")
                                self.failures.pop(msg["id"], None)
                                processed += 1
                            previous = msg
                            continue
                    else:
                        outcome = "trivial"
                    self.store.mark_processed(msg["id"], chat_id, outcome)
                    processed += 1
                else:
                    self.store.mark_processed(msg["id"], chat_id, "no-user-parent")
                    processed += 1
            previous = msg
        return processed

    def tick(self):
        state = self.store.get_state()
        if not state.get("memory_worker_initialized") and not self.backfill:
            count = self.baseline_existing()
            print(f"[memory] baseline complete; {count} existing assistant messages marked without backfill", flush=True)
            return
        total = 0
        for summary in self.chats():
            try:
                total += self.process_chat(summary)
            except Exception as exc:
                print(f"[memory] chat scan failed: {type(exc).__name__}: {exc}", flush=True)
        if total:
            print(f"[memory] processed {total} new exchange(s) at {datetime.now().isoformat(timespec='seconds')}", flush=True)

    def loop(self):
        while True:
            try:
                self.tick()
            except Exception as exc:
                print(f"[memory] worker error: {type(exc).__name__}: {exc}", flush=True)
            time.sleep(self.interval)
