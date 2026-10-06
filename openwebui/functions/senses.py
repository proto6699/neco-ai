"""
title: Neco System Vitals
description: Experimental read-only host telemetry context for Neco.
version: 0.1.1
"""

import json
from pathlib import Path

SNAPSHOT = Path("/host-runtime/system-vitals.json")

TRIGGERS = (
    "temp", "temperature", "hot", "heat",
    "cpu", "gpu", "ram", "memory", "vram",
    "load", "uptime", "vitals", "system status",
    "battery", "charge", "charging", "power level",
    "system health", "machine status", "hardware",
    "how are you", "how're you", "how are u",
    "how you feeling", "how are you feeling",
)


def _latest_user_text(messages):
    for message in reversed(messages or []):
        if message.get("role") != "user":
            continue
        content = message.get("content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    parts.append(str(item.get("text", "")))
            return " ".join(parts)
    return ""


def _format_vitals(data):
    lines = [
        "[Experimental system vitals — live read-only host data]",
        f"sampled_at: {data.get('sampled_at', 'unavailable')}",
    ]

    if data.get("uptime_hours") is not None:
        lines.append(f"uptime_hours: {data['uptime_hours']}")

    load = data.get("load_average")
    if isinstance(load, dict):
        lines.append(
            "load_average: "
            f"{load.get('1m', '?')} / {load.get('5m', '?')} / {load.get('15m', '?')}"
        )

    memory = data.get("memory")
    if isinstance(memory, dict):
        lines.append(
            "ram: "
            f"{memory.get('used_gib', '?')} / {memory.get('total_gib', '?')} GiB "
            f"({memory.get('used_percent', '?')}%)"
        )

    if data.get("cpu_temp_c") is not None:
        lines.append(f"cpu_temp_c: {data['cpu_temp_c']}")

    battery = data.get("battery")
    if isinstance(battery, dict):
        for item in battery.get("batteries", []):
            percent = item.get("percent")
            level = f"{percent}%" if percent is not None else "percentage unavailable"
            lines.append(f"battery {item.get('name', '?')}: {level}; {item.get('status') or 'status unavailable'}")
    else:
        lines.append("battery: unavailable (no readable battery sensor)")

    gpu = data.get("gpu")
    if isinstance(gpu, dict):
        parts = [gpu.get("vendor", "gpu")]
        if gpu.get("temp_c") is not None:
            parts.append(f"{gpu['temp_c']} C")
        if gpu.get("load_percent") is not None:
            parts.append(f"{gpu['load_percent']}% load")
        if gpu.get("vram_total_gib") is not None:
            parts.append(
                f"{gpu.get('vram_used_gib', '?')} / {gpu['vram_total_gib']} GiB VRAM"
            )
        lines.append("gpu: " + ", ".join(str(part) for part in parts))

    lines.append(
        "These readings describe the host machine, not a physical body. When asked, report actual values plainly before character commentary. Missing fields mean the sensor "
        "is unavailable; never invent a value."
    )
    return "\n".join(lines)


class Filter:
    async def inlet(self, body: dict) -> dict:
        messages = body.get("messages") or []
        user_text = _latest_user_text(messages).lower()

        if not user_text or not any(trigger in user_text for trigger in TRIGGERS):
            return body

        try:
            data = json.loads(SNAPSHOT.read_text())
        except (OSError, json.JSONDecodeError):
            data = None

        context = "Host vitals unavailable: the daemon has not supplied a readable snapshot. Do not invent readings."
        if isinstance(data, dict):
            from datetime import datetime, timezone
            try:
                age = (datetime.now(timezone.utc) - datetime.fromisoformat(data['sampled_at'])).total_seconds()
                if -10 <= age <= 60:
                    context = _format_vitals(data)
                else:
                    context = "Host vitals snapshot is stale. Current readings unavailable; do not report old values as live."
            except (KeyError, TypeError, ValueError):
                context = "Host vitals timestamp unavailable; do not report readings as live."
        for message in messages:
            if message.get("role") == "system" and isinstance(message.get("content"), str):
                message["content"] += "\n\n" + context
                break
        else:
            messages.insert(0, {"role": "system", "content": context})

        body["messages"] = messages
        return body
