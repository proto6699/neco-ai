#!/usr/bin/env python3
import hashlib
from contextlib import contextmanager
import json
import math
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

STOPWORDS = {
    "a","an","and","are","as","at","be","been","but","by","do","for","from","had","has","have",
    "he","her","him","his","how","i","if","in","is","it","its","me","my","of","on","or","our",
    "she","so","that","the","their","them","there","they","this","to","was","we","were","what",
    "when","where","which","who","why","will","with","you","your","about","just","like","not"
}


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def _tokens(text):
    return {
        t for t in re.findall(r"[a-z0-9][a-z0-9_'-]{1,}", (text or "").lower())
        if t not in STOPWORDS
    }


def _normalise_text(value):
    return " ".join(str(value or "").split()).strip()


def _fingerprint(kind, content):
    raw = (kind.strip().lower() + "\n" + _normalise_text(content).lower()).encode()
    return hashlib.sha256(raw).hexdigest()


class MemoryStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    @contextmanager
    def session(self):
        db = self.connect()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _init_db(self):
        with self.session() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    content TEXT NOT NULL,
                    importance REAL NOT NULL DEFAULT 0.5,
                    confidence REAL NOT NULL DEFAULT 0.7,
                    status TEXT NOT NULL DEFAULT 'active',
                    topics_json TEXT NOT NULL DEFAULT '[]',
                    source_chat_id TEXT,
                    source_message_id TEXT,
                    supersedes_id INTEGER,
                    fingerprint TEXT NOT NULL UNIQUE,
                    FOREIGN KEY(supersedes_id) REFERENCES memories(id)
                );
                CREATE INDEX IF NOT EXISTS idx_memories_status ON memories(status);
                CREATE INDEX IF NOT EXISTS idx_memories_kind ON memories(kind);
                CREATE INDEX IF NOT EXISTS idx_memories_created ON memories(created_at);

                CREATE TABLE IF NOT EXISTS state (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS processed_messages (
                    message_id TEXT PRIMARY KEY,
                    chat_id TEXT,
                    processed_at TEXT NOT NULL,
                    outcome TEXT NOT NULL DEFAULT 'seen'
                );
                """
            )

    def is_empty(self):
        with self.session() as db:
            return db.execute("SELECT COUNT(*) FROM processed_messages").fetchone()[0] == 0

    def is_processed(self, message_id):
        with self.session() as db:
            return db.execute(
                "SELECT 1 FROM processed_messages WHERE message_id=?", (message_id,)
            ).fetchone() is not None

    def mark_processed(self, message_id, chat_id=None, outcome="seen"):
        if not message_id:
            return
        with self.session() as db:
            db.execute(
                "INSERT OR REPLACE INTO processed_messages(message_id, chat_id, processed_at, outcome) VALUES(?,?,?,?)",
                (message_id, chat_id, utcnow(), outcome),
            )

    def add_memory(
        self,
        kind,
        content,
        importance=0.5,
        confidence=0.7,
        topics=None,
        source_chat_id=None,
        source_message_id=None,
        supersedes_id=None,
        status="active",
    ):
        content = _normalise_text(content)
        if not content:
            return None
        kind = _normalise_text(kind) or "event"
        importance = min(1.0, max(0.0, float(importance)))
        confidence = min(1.0, max(0.0, float(confidence)))
        topics = [str(x).strip() for x in (topics or []) if str(x).strip()][:12]
        fp = _fingerprint(kind, content)
        now = utcnow()
        with self.session() as db:
            row = db.execute("SELECT id, importance, confidence FROM memories WHERE fingerprint=?", (fp,)).fetchone()
            if row:
                db.execute(
                    "UPDATE memories SET updated_at=?, importance=?, confidence=? WHERE id=?",
                    (now, max(float(row["importance"]), importance), max(float(row["confidence"]), confidence), row["id"]),
                )
                return int(row["id"])
            cur = db.execute(
                """
                INSERT INTO memories(
                    created_at, updated_at, kind, content, importance, confidence, status,
                    topics_json, source_chat_id, source_message_id, supersedes_id, fingerprint
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    now, now, kind, content, importance, confidence, status,
                    json.dumps(topics, ensure_ascii=False), source_chat_id, source_message_id,
                    supersedes_id, fp,
                ),
            )
            return int(cur.lastrowid)

    def list_memories(self, limit=50, status="active"):
        with self.session() as db:
            if status == "all":
                rows = db.execute(
                    "SELECT * FROM memories ORDER BY id DESC LIMIT ?", (int(limit),)
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT * FROM memories WHERE status=? ORDER BY id DESC LIMIT ?",
                    (status, int(limit)),
                ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_memory(self, memory_id):
        with self.session() as db:
            row = db.execute("SELECT * FROM memories WHERE id=?", (int(memory_id),)).fetchone()
        return self._row_to_dict(row) if row else None

    def delete_memory(self, memory_id):
        with self.session() as db:
            cur = db.execute("DELETE FROM memories WHERE id=?", (int(memory_id),))
            return cur.rowcount > 0

    def archive_memory(self, memory_id):
        with self.session() as db:
            cur = db.execute(
                "UPDATE memories SET status='archived', updated_at=? WHERE id=?",
                (utcnow(), int(memory_id)),
            )
            return cur.rowcount > 0

    def set_state(self, key, value):
        with self.session() as db:
            db.execute(
                """
                INSERT INTO state(key, value_json, updated_at) VALUES(?,?,?)
                ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at
                """,
                (key, json.dumps(value, ensure_ascii=False), utcnow()),
            )

    def get_state(self):
        with self.session() as db:
            rows = db.execute("SELECT key, value_json, updated_at FROM state ORDER BY key").fetchall()
        result = {}
        for row in rows:
            try:
                value = json.loads(row["value_json"])
            except json.JSONDecodeError:
                value = row["value_json"]
            result[row["key"]] = value
        return result

    def retrieve(self, query, limit=6):
        q_tokens = _tokens(query)
        with self.session() as db:
            rows = db.execute(
                "SELECT * FROM memories WHERE status='active' ORDER BY id DESC LIMIT 750"
            ).fetchall()
        if not rows:
            return []
        now = datetime.now(timezone.utc)
        scored = []
        for row in rows:
            item = self._row_to_dict(row)
            haystack = item["content"] + " " + " ".join(item["topics"])
            m_tokens = _tokens(haystack)
            overlap = len(q_tokens & m_tokens)
            union = max(1, len(q_tokens | m_tokens))
            lexical = overlap / union
            try:
                age_days = max(0.0, (now - datetime.fromisoformat(item["created_at"])).total_seconds() / 86400)
            except Exception:
                age_days = 365.0
            recency = math.exp(-age_days / 45.0)
            kind_bonus = 0.20 if item["kind"] in ("open_question", "relationship", "preference", "belief") else 0.0
            score = lexical * 5.0 + item["importance"] * 1.5 + recency * 0.35 + kind_bonus
            if q_tokens and overlap == 0:
                continue
            scored.append((score, item))
        scored.sort(key=lambda x: (x[0], x[1]["id"]), reverse=True)
        return [item for _, item in scored[: max(1, min(int(limit), 12))]]

    def export(self):
        return {"memories": self.list_memories(limit=100000, status="all"), "state": self.get_state()}

    @staticmethod
    def _row_to_dict(row):
        try:
            topics = json.loads(row["topics_json"] or "[]")
        except json.JSONDecodeError:
            topics = []
        return {
            "id": int(row["id"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "kind": row["kind"],
            "content": row["content"],
            "importance": float(row["importance"]),
            "confidence": float(row["confidence"]),
            "status": row["status"],
            "topics": topics,
            "source_chat_id": row["source_chat_id"],
            "source_message_id": row["source_message_id"],
            "supersedes_id": row["supersedes_id"],
        }
