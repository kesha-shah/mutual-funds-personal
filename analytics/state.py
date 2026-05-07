"""
Persistent UI state — tracks the last CAS fetch so we don't re-submit or
re-parse unnecessarily.
"""
from __future__ import annotations

import json
from pathlib import Path

from analytics.accounts import account_data_dir


def state_file() -> Path:
    return account_data_dir() / "state.json"


def load_state() -> dict:
    p = state_file()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def save_state(state: dict) -> None:
    p = state_file()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=2, default=str))


def update_state(**kwargs) -> dict:
    state = load_state()
    state.update(kwargs)
    save_state(state)
    return state
