"""URL / query-string helpers for in-Streamlit navigation.

The scheme cards and sort links are plain ``<a href>`` anchors, so clicking
one is a *full page reload* — Streamlit spins up a fresh session and wipes
``st.session_state``. Anything that must survive navigation therefore lives in
the query string, not session state. That's the active ``account`` slug and
the portfolio filters (``view``/``class``/``amc``/``plan``/``sub``); these are
the "persistent" keys carried across every internal link below.
"""
from __future__ import annotations

from urllib.parse import urlencode

import streamlit as st

# Query-string keys that must ride along on every internal navigation so a
# full-page reload (card click, sort click, back button) doesn't drop them.
# ``amc`` is repeatable (multiselect) — handled via get_all below.
PERSIST_KEYS = ("account", "view", "class", "amc", "plan", "sub")


def _persisted_pairs() -> list[tuple[str, str]]:
    """Current values of the persistent keys as ``(key, value)`` pairs,
    expanding repeated keys (e.g. multiple ``amc=``) into one pair each."""
    pairs: list[tuple[str, str]] = []
    for k in PERSIST_KEYS:
        for v in st.query_params.get_all(k):
            pairs.append((k, v))
    return pairs


def qs_link(**extra: str) -> str:
    """Build ``?...`` preserving the account slug + active filters. Used by
    internal nav links (cards, sort header) so a click doesn't drop the
    current account or reset the filters. ``extra`` (e.g. ``scheme=``,
    ``sort=``) is appended; None values are skipped."""
    params = _persisted_pairs()
    params.extend((k, v) for k, v in extra.items() if v is not None)
    return ("?" + urlencode(params)) if params else ""


def clear_query_keep_filters() -> None:
    """Drop transient params (``scheme``, ``sort``) while keeping the account
    slug and the active filters — so returning from a scheme-detail page lands
    back on the same filtered portfolio view instead of a reset one."""
    preserved: dict[str, str | list[str]] = {}
    for k in PERSIST_KEYS:
        vals = st.query_params.get_all(k)
        if vals:
            preserved[k] = vals if len(vals) > 1 else vals[0]
    st.query_params.from_dict(preserved)
