"""Tiny JSON state file for the bot — persists `active_box` across restarts.

Lives next to bot.py by default; override with DIYVPN_BOT_STATE.
"""

from __future__ import annotations

import json
import os
import threading
from typing import Any

STATE_PATH = os.environ.get(
    "DIYVPN_BOT_STATE",
    os.path.join(os.getcwd(), ".bot-state.json"),
)

_lock = threading.Lock()


def load() -> dict[str, Any]:
    if not os.path.exists(STATE_PATH):
        return {}
    try:
        with open(STATE_PATH) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save(state: dict[str, Any]) -> None:
    """Atomic write: tmp + rename."""
    with _lock:
        tmp = STATE_PATH + ".tmp"
        with open(tmp, "w") as f:
            json.dump(state, f, indent=2)
        os.replace(tmp, STATE_PATH)


def update(**fields: Any) -> dict[str, Any]:
    """Merge `fields` into the state file and return the new dict."""
    s = load()
    s.update(fields)
    save(s)
    return s
