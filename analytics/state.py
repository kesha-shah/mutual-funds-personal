"""
Persistent UI state — tracks the last CAS fetch so we don't re-submit or
re-parse unnecessarily. Keyed by slug so each account has its own state.
"""
from __future__ import annotations

import json
from pathlib import Path

from analytics.accounts import ACCOUNTS_DIR


def _state_path(slug: str) -> Path:
    return ACCOUNTS_DIR / slug / "state.json"


def load_state(slug: str) -> dict:
    p = _state_path(slug)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def update_state(slug: str, **kwargs) -> dict:
    state = load_state(slug)
    state.update(kwargs)
    p = _state_path(slug)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=2, default=str))
    return state
