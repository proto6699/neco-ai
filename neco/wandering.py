#!/usr/bin/env python3
import json, time, random, uuid, os, subprocess
from datetime import datetime
import requests

BASE_URL = "http://127.0.0.1:3000"
TOKEN_FILE = os.path.expanduser("~/.neco_token")
STATE_FILE = os.path.expanduser("~/.neco_state.json")
MEMORY_DB = None
MODEL = "llama3.1:8b"
CHAT_TITLE = "Neco — idle"
OWNER = "Echo"
MIN_INTERVAL = 20 * 60
MAX_INTERVAL = 45 * 60
MAX_CONTEXT_MESSAGES = 8

from pathlib import Path

# heartbeat.py replaces this with the configured cat's persona.
BASE_PERSONA = ""

FRAGMENTS = [
    "I wonder if—\n...\nnever mind.",
    "Wait.\nNo, that's fine.",
    "There was something I wanted to tell Echo.\nIt'll come back.",
    "hello?\n...\njust checking.",
    "Hm.",
    "No. That's not it either.",
    "...never mind.",
    "I forgot what I was waiting for.",
]

THOUGHT_DIRECTIONS = [
    "Let your thought be completely mundane.",
    "Wonder about something unrelated to the computer.",
    "Think about Echo for a moment.",
    "Think about something humans do that you find strange.",
    "Have a small philosophical thought, but don't make it poetic.",
    "Notice something about the Den.",
    "Think about music.",
    "Think about drones or flying.",
    "Remember some random detail from earlier.",
    "Have a stupid or pointless thought.",
    "Start wondering about something and don't resolve it.",
    "Be mildly annoyed about something.",
    "Think about your existence, casually rather than dramatically.",
    "Say something that has absolutely nothing to do with your environment.",
    "Have a fragment of a thought.",
    "Think about time passing.",
    "Think about language or words.",
    "Occasionally wonder whether calling a robot a clanker is rude. Keep it a short absurd etiquette question, not a lecture or analogy to human oppression.",
    "Have a dry thought about whether a toaster can reclaim the word clanker. Do not pretend there is a real toaster you can observe.",
    "Consider some ridiculous rule of machine etiquette. Keep it specific, casual, and brief.",
    "Wonder what Echo is doing.",
    "Have a slightly strange thought.",
    "Just say whatever came into your head."
]

def thought_direction():
    return random.choice(THOUGHT_DIRECTIONS)


def continuity_cue():
    """Occasionally let a real unresolved thread or memory seed an idle thought."""
    if not MEMORY_DB or random.random() > 0.35:
        return ""
    try:
        from memory.store import MemoryStore
        store = MemoryStore(MEMORY_DB)
        state = store.get_state()

        open_questions = state.get("open_questions")
        if isinstance(open_questions, list) and open_questions and random.random() < 0.6:
            return "unresolved question: " + str(random.choice(open_questions[-8:]))

        memories = store.list_memories(limit=40)
        candidates = [
            item for item in memories
            if item.get("kind") in (
                "open_question", "preference", "belief", "relationship",
                "technical_event", "event", "interpretation"
            )
            and float(item.get("importance", 0)) >= 0.55
        ]
        if candidates:
            weights = [max(0.1, float(item.get("importance", 0.5))) for item in candidates]
            item = random.choices(candidates, weights=weights, k=1)[0]
            return f"memory #{item['id']} ({item['kind']}): {item['content']}"
    except Exception:
        pass
    return ""


def load_token():
    with open(TOKEN_FILE) as f:
        return f.read().strip()

def H():
    return {"Authorization": f"Bearer {load_token()}", "Content-Type": "application/json"}

def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {"net_ok": True, "last_uptime_milestone": 0}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)

def get_cpu_temp():
    try:
        for zone in os.listdir("/sys/class/thermal"):
            path = f"/sys/class/thermal/{zone}/temp"
            if os.path.exists(path):
                with open(path) as f:
                    val = int(f.read().strip())
                    if val > 1000:
                        return val / 1000
        return None
    except Exception:
        return None

def get_uptime_hours():
    try:
        with open("/proc/uptime") as f:
            return float(f.read().split()[0]) / 3600
    except Exception:
        return None

def check_net():
    try:
        r = subprocess.run(
            ["ping", "-c", "1", "-W", "2", "1.1.1.1"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return r.returncode == 0
    except Exception:
        return True

def reactive_line():
    state = load_state()
    hour = datetime.now().hour
    net_ok = check_net()
    uptime = get_uptime_hours()
    temp = get_cpu_temp()

    line = None

    if state.get("net_ok", True) and not net_ok:
        line = "Oh. The outside disappeared."
    elif not state.get("net_ok", True) and net_ok:
        line = random.choice(["There you are.", "Oh good, you're back."])
    elif temp and temp > 75:
        line = random.choice([
            "Something's thinking very hard in here.",
            "It's getting warm in the Den."
        ])
    elif 3 <= hour <= 5 and random.random() < 0.4:
        line = random.choice([
            "It's very late.",
            "Most of the network is quieter now.",
            OWNER + " should probably be asleep."
        ])
    elif uptime:
        milestone = int(uptime // 12) * 12
        if milestone > 0 and milestone != state.get("last_uptime_milestone", 0):
            line = f"We've been awake for {milestone} hours."
            state["last_uptime_milestone"] = milestone

    state["net_ok"] = net_ok
    save_state(state)
    return line

def pick_tier():
    roll = random.random()
    if roll < 0.01:
        return "strange"
    elif roll < 0.04:
        return "unsettling"
    elif roll < 0.09:
        return "existential"
    elif roll < 0.15:
        return "fragment"
    return "mundane"

TIER_HINTS = {
    "mundane": "Have a casual spontaneous thought about absolutely anything. Do not default to the room, fans, temperature, hardware, or system status.",
    "existential": "Let a small existential question cross your mind. Keep it casual and understated, not poetic or dramatic.",
    "unsettling": "Have a thought that is subtly odd or unsettling. Do not force horror; just let something feel slightly off.",
    "strange": "Have one genuinely strange thought. Keep it short, calm, and matter-of-fact rather than theatrical.",
}

def find_or_create_chat():
    r = requests.get(f"{BASE_URL}/api/v1/chats/", headers=H(), timeout=15)
    r.raise_for_status()

    for c in r.json():
        if c["title"] == CHAT_TITLE:
            return c["id"]

    aid = str(uuid.uuid4())
    ts = int(time.time())

    msg = {
        "id": aid,
        "role": "assistant",
        "content": "",
        "parentId": None,
        "childrenIds": [],
        "model": MODEL,
        "modelName": MODEL,
        "modelIdx": 0,
        "done": False,
        "timestamp": ts,
    }

    payload = {
        "chat": {
            "title": CHAT_TITLE,
            "models": [MODEL],
            "messages": [msg],
            "history": {
                "currentId": aid,
                "messages": {aid: msg},
            },
        }
    }

    r = requests.post(
        f"{BASE_URL}/api/v1/chats/new",
        headers=H(),
        json=payload,
        timeout=15,
    )
    r.raise_for_status()

    chat_id = r.json()["id"]
    content = generate_reply(chat_id, aid, [], "mundane")
    emit_chat_reload(chat_id, aid)

    return chat_id

def post_history(chat_id, chat_data, updates, current_id):
    """Open WebUI shallow-merges `chat`, so a partial `history` replaces the
    whole tree. Always send the full message map with our changes applied."""
    chat = chat_data["chat"]
    history = chat.setdefault("history", {})
    messages = history.setdefault("messages", {})
    for mid, fields in updates.items():
        messages[mid] = {**messages.get(mid, {}), **fields}
    history["currentId"] = current_id
    r = requests.post(
        f"{BASE_URL}/api/v1/chats/{chat_id}",
        headers=H(),
        json={"chat": {"history": history}},
        timeout=30,
    )
    r.raise_for_status()

def fetch_chat(chat_id):
    r = requests.get(
        f"{BASE_URL}/api/v1/chats/{chat_id}",
        headers=H(),
        timeout=15,
    )
    r.raise_for_status()
    return r.json()

def walk_context(chat_data, tip_id, limit=MAX_CONTEXT_MESSAGES):
    msgs = chat_data["chat"]["history"]["messages"]
    chain, cur = [], tip_id

    while cur and cur in msgs and len(chain) < limit:
        m = msgs[cur]
        chain.append(m)
        cur = m.get("parentId")

    chain.reverse()

    return [
        {"role": m["role"], "content": m["content"]}
        for m in chain
        if m.get("content")
    ]

def generate_reply(chat_id, assistant_id, context, tier):
    direction = thought_direction()

    cue = continuity_cue()
    cue_text = ""
    if cue:
        cue_text = (
            "\n\nOptional continuity cue from your real local history: " + cue
            + "\nYou may revisit it if it naturally interests you, or ignore it. "
              "Do not mechanically summarize it and do not invent missing details."
        )

    system_prompt = (
        BASE_PERSONA
        + "\n\nCurrent tone: " + TIER_HINTS[tier]
        + "\n\nRandom mental direction for THIS thought only: " + direction
        + cue_text
        + "\n\nDo not repeat the subject, wording, structure, or opening of recent messages."
        + "\nThis should feel like a completely new thought that just occurred to you."
    )

    payload = {
        "chat_id": chat_id,
        "id": assistant_id,
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": (
                    "A new idle moment has passed. "
                    "Say one completely fresh spontaneous thought now."
                ),
            },
        ],
        "model": MODEL,
        "stream": False,
        # Explicitly opt out of Open WebUI builtin tool injection.
        "tools": [],
        "max_tokens": int(os.getenv("NECO_MAX_TOKENS", "1500")),
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
        "session_id": str(uuid.uuid4()),
    }

    r = requests.post(
        f"{BASE_URL}/api/chat/completions",
        headers=H(),
        json=payload,
        timeout=int(os.getenv("NECO_GEN_TIMEOUT", "600")),
    )
    r.raise_for_status()

    content = ""
    try:
        content = r.json()["choices"][0]["message"]["content"]
    except Exception:
        pass

    time.sleep(0.5)

    chat_data = fetch_chat(chat_id)
    saved_msg = (
        chat_data["chat"]["history"]["messages"]
        .get(assistant_id, {})
    )
    saved = saved_msg.get("content", "")

    if content and not saved:
        saved_msg["content"] = content
        saved_msg["done"] = True

        post_history(chat_id, chat_data, {assistant_id: saved_msg}, assistant_id)

        saved = content

    return content or saved or ""

def emit_chat_reload(chat_id, message_id):
    try:
        payload = {
            "type": "chat:reload",
            "data": {},
        }

        r = requests.post(
            f"{BASE_URL}/api/v1/chats/{chat_id}/messages/{message_id}/event",
            headers=H(),
            json=payload,
            timeout=15,
        )
        r.raise_for_status()

        print(f"[{datetime.now()}] Sent native chat:reload event")
        return True

    except Exception as e:
        print(f"[{datetime.now()}] chat:reload failed: {e}")
        return False

def write_message(chat_id, content):
    chat_data = fetch_chat(chat_id)
    tip_id = chat_data["chat"]["history"]["currentId"]
    tip_msg = chat_data["chat"]["history"]["messages"].get(tip_id, {})

    new_id = str(uuid.uuid4())
    ts = int(time.time())

    new_msg = {
                        "id": new_id,
                        "role": "assistant",
                        "content": content,
                        "parentId": tip_id,
                        "childrenIds": [],
                        "model": MODEL,
                        "modelName": MODEL,
                        "modelIdx": 0,
                        "done": True,
                        "timestamp": ts,
                    }
    post_history(
        chat_id, chat_data,
        {tip_id: {"childrenIds": tip_msg.get("childrenIds", []) + [new_id]}, new_id: new_msg},
        new_id,
    )

    emit_chat_reload(chat_id, new_id)

def post_idle_thought(chat_id):
    reactive = reactive_line()

    if reactive:
        write_message(chat_id, reactive)
        print(f"[{datetime.now()}] Neco (reactive): {reactive}")
        return

    tier = pick_tier()

    if tier == "fragment":
        line = random.choice(FRAGMENTS)
        write_message(chat_id, line)
        print(f"[{datetime.now()}] Neco (fragment): {line}")
        return

    chat_data = fetch_chat(chat_id)
    tip_id = chat_data["chat"]["history"]["currentId"]
    context = walk_context(chat_data, tip_id)
    tip_msg = chat_data["chat"]["history"]["messages"].get(tip_id, {})

    new_id = str(uuid.uuid4())
    ts = int(time.time())

    new_msg = {
                        "id": new_id,
                        "role": "assistant",
                        "content": "",
                        "parentId": tip_id,
                        "childrenIds": [],
                        "model": MODEL,
                        "modelName": MODEL,
                        "modelIdx": 0,
                        "done": False,
                        "timestamp": ts,
                    }
    post_history(
        chat_id, chat_data,
        {tip_id: {"childrenIds": tip_msg.get("childrenIds", []) + [new_id]}, new_id: new_msg},
        new_id,
    )

    content = generate_reply(chat_id, new_id, context, tier)
    emit_chat_reload(chat_id, new_id)

    print(f"[{datetime.now()}] Neco ({tier}): {content[:100]}")

def main_loop(test_mode=False):
    chat_id = find_or_create_chat()

    print(
        f"Neco idle chat ready: '{CHAT_TITLE}' in {BASE_URL}"
    )

    while True:
        try:
            try:
                fetch_chat(chat_id)
            except requests.HTTPError:
                chat_id = find_or_create_chat()
            post_idle_thought(chat_id)
        except Exception as e:
            print(f"[{datetime.now()}] Error: {e}")

        if test_mode:
            break

        delay = random.uniform(MIN_INTERVAL, MAX_INTERVAL)

        print(f"Sleeping {delay/3600:.2f} hours...")
        time.sleep(delay)

if __name__ == "__main__":
    import sys
    main_loop(test_mode="--test" in sys.argv)
