"""
title: Neco Grounding
description: Always-on host facts (distro, kernel, CPU, terminals...) and the cat's own session config (model, where it runs, memory) so replies start from true facts.
version: 0.1.0
"""

from datetime import datetime, timezone
from pathlib import Path

# Rendered by the host daemon (neco/hostfacts.py) and refreshed every ~30 s.
GROUNDING = Path("/host-runtime/grounding.txt")
MAX_AGE_SECONDS = 600


def _context():
    try:
        text = GROUNDING.read_text().strip()
        age = datetime.now(timezone.utc).timestamp() - GROUNDING.stat().st_mtime
    except OSError:
        return None
    if not text:
        return None
    if age > MAX_AGE_SECONDS:
        # Static facts are still true; only the clock and memory count may be old.
        text += "\n(The background service has not refreshed this recently; the local time above may be out of date.)"
    return text


class Filter:
    async def inlet(self, body: dict) -> dict:
        context = _context()
        if not context:
            return body
        messages = body.get("messages") or []
        for message in messages:
            if message.get("role") == "system" and isinstance(message.get("content"), str):
                message["content"] += "\n\n" + context
                break
        else:
            messages.insert(0, {"role": "system", "content": context})
        body["messages"] = messages
        return body
