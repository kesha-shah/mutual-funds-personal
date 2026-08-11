"""
Persistent UI state, keyed by slug so each account has its own files.

Two files per account, deliberately separate:

* ``state.json``   — CAS fetch bookkeeping (last request, last parsed PDF, …),
                     written by the ingest/refresh path.
* ``planner.json`` — the inflow planner's saved entries, written by the UI as
                     you type.

They used to share ``state.json``, but every write here is a whole-file
read-modify-write: a CAS refresh saving ``last_fetched_at`` in the same instant
you edited an amount would drop one of the two changes. Different writers,
different files, no lost update. ``load_planner`` migrates the old embedded
copy across on first read, so nothing needs to be moved by hand.

Both writes are atomic (temp file + fsync + ``os.replace``) so a Streamlit
rerun that collides with a process restart can't leave a truncated file
behind — which would otherwise silently read back as empty and look like the
plan was wiped.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from analytics.accounts import ACCOUNTS_DIR

# Key the planner used while it still lived inside state.json.
_LEGACY_PLANNER_KEY = "inflow_planner"


def _state_path(slug: str) -> Path:
    return ACCOUNTS_DIR / slug / "state.json"


def _planner_path(slug: str) -> Path:
    return ACCOUNTS_DIR / slug / "planner.json"


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    # fsync before the rename: os.replace is atomic w.r.t. other processes,
    # but without the flush a crash can leave the *renamed* file zero-length
    # on disk — the bytes were only ever in the page cache.
    with tmp.open("w") as fh:
        json.dump(data, fh, indent=2, default=str)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def load_state(slug: str) -> dict:
    return _read_json(_state_path(slug))


def update_state(slug: str, **kwargs) -> dict:
    state = load_state(slug)
    state.update(kwargs)
    _write_json(_state_path(slug), state)
    return state


def load_planner(slug: str) -> dict:
    """The account's saved inflow plan, ``{fund_id: {...}}``.

    Migrates a pre-split plan out of ``state.json`` on first read: the entries
    are copied to ``planner.json`` and the old key dropped. Ordering matters —
    write the new file first, so an interruption between the two steps leaves a
    harmless duplicate rather than no plan at all. The legacy key is ignored
    once ``planner.json`` exists, so a stale copy can never resurrect."""
    path = _planner_path(slug)
    if path.exists():
        return _read_json(path)

    state = load_state(slug)
    legacy = state.get(_LEGACY_PLANNER_KEY)
    if not isinstance(legacy, dict) or not legacy:
        return {}
    _write_json(path, legacy)
    state.pop(_LEGACY_PLANNER_KEY, None)
    _write_json(_state_path(slug), state)
    return legacy


def save_planner(slug: str, plan: dict) -> None:
    """Replace the saved inflow plan wholesale. Callers merge first — this is
    the last word on what the file contains."""
    _write_json(_planner_path(slug), plan)
