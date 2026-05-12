"""Glue between the FastAPI gateway and the Streamlit script.

The gateway puts a signed payload (user + data keys) on every proxied
request. We decode it on each rerun to reconstruct the user's Session
without persisting anything in the Streamlit process.
"""
from __future__ import annotations

import streamlit as st

from analytics import auth, session_payload


_FLASH_TEXT: dict[str, str] = {
    "password-changed": "Login password updated.",
    "app-pw-saved":     "Gmail App Password updated.",
    "pdf-pw-saved":     "CAS PDF password updated.",
    "unlinked":         "Account unlinked. Refresh to update the picker.",
}


def session_from_header() -> auth.Session | None:
    """Decode the signed X-Session-Payload header injected by the gateway.
    Returns None when the header is missing or its signature doesn't validate —
    that only happens when the user reaches Streamlit directly (bypassing
    the gateway), in which case the caller shows an error."""
    raw = (st.context.headers or {}).get("X-Session-Payload")
    if not raw:
        return None
    payload = session_payload.parse(raw)
    if not payload:
        return None
    # KEK isn't carried in the payload — operations that need it (change
    # password, delete account) live on gateway pages. Dashboard rendering
    # and CAS fetch only need data_keys, which we do have.
    return auth.Session(
        user_email=payload["user_email"],
        is_admin=payload["is_admin"],
        kek=b"",
        data_keys=payload["data_keys"],
    )


def consume_flash() -> None:
    """If the gateway redirected us back with ``?flash=...``, show a toast
    and strip the param so a manual refresh doesn't re-show the toast."""
    flash = st.query_params.get("flash")
    if not flash:
        return
    if flash.startswith("err-"):
        st.toast(flash[4:], icon="⚠️")
    elif flash.startswith("invited-"):
        st.toast(f"Invite created: /invite/{flash[len('invited-'):]}", icon="✉️")
    else:
        st.toast(_FLASH_TEXT.get(flash, flash), icon="✅")
    del st.query_params["flash"]


def active_slug(session: auth.Session) -> str | None:
    """Which CAS account is currently selected.

    Priority: ``?account=<slug>`` → ``st.session_state`` → the user's **own**
    slug (slugified login email) → first available slug.

    The own-slug fallback matters when linked accounts exist — without it,
    login would drop the user onto whichever linked slug sorts first."""
    slugs = session.slugs()
    if not slugs:
        return None
    from_url = st.query_params.get("account")
    if from_url and from_url in slugs:
        st.session_state["_active_slug"] = from_url
        return from_url
    chosen = st.session_state.get("_active_slug")
    if chosen not in slugs:
        own = auth.slugify(session.user_email)
        chosen = own if own in slugs else slugs[0]
    st.session_state["_active_slug"] = chosen
    return chosen
