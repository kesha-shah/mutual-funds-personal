"""
Persistent UI state — tracks the last CAS fetch so we don't re-submit or
re-parse unnecessarily, plus the inflow planner's saved entries. Keyed by
slug so each account has its own state.

``update_state`` writes atomically (temp file + os.replace) so a Streamlit
rerun that collides with a process restart can't leave a truncated
state.json behind — which would otherwise silently read back as empty and
look like the plan was wiped.
"""
from __future__ import annotations

import json
import os
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
    tmp = p.with_suffix(p.suffix + ".tmp")
    # fsync before the rename: os.replace is atomic w.r.t. other processes,
    # but without the flush a crash can leave the *renamed* file zero-length
    # on disk — the bytes were only ever in the page cache.
    with tmp.open("w") as fh:
        json.dump(state, fh, indent=2, default=str)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, p)
    return state
