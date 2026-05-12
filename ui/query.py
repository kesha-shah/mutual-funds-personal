"""URL / query-string helpers for in-Streamlit navigation."""
from __future__ import annotations

from urllib.parse import urlencode

import streamlit as st


def qs_link(**extra: str) -> str:
    """Build ``?...`` preserving the active ``account`` slug. Used by internal
    nav links so a click doesn't drop the currently-selected account."""
    params = {}
    acc = st.query_params.get("account")
    if acc:
        params["account"] = acc
    params.update({k: v for k, v in extra.items() if v is not None})
    return ("?" + urlencode(params)) if params else ""


def clear_query_keep_account() -> None:
    """In-place equivalent of ``st.query_params.clear()`` that keeps the
    ``account`` slug — without this, the user would jump to the
    alphabetically-first account."""
    acc = st.query_params.get("account")
    st.query_params.clear()
    if acc:
        st.query_params["account"] = acc
