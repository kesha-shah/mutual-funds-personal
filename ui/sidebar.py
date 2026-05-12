"""Sidebar: account picker, admin invite, settings dropdown.

Settings UI is a tight expander. Each cred-update collapses into a button
by default — clicking it reveals the input + Save / Cancel. Keeps the menu
visually quiet when the user is just glancing at it.

Routing recap:
  - Gmail / PDF update → ``auth.update_account_creds`` in-process.
  - Change login password → its own gateway page (needs KEK).
  - Unlink → gateway endpoint so auth_server prunes its session too.
  - Logout → gateway ``/logout``.
  - Delete account → its own gateway page.
"""
from __future__ import annotations

from typing import Callable

import streamlit as st

from analytics import auth
from ui.auth_glue import active_slug


def render_account_picker(session: auth.Session, on_account_change: Callable[[], None]) -> str | None:
    accounts = auth.accounts_for_session(session)
    if not accounts:
        st.info("No CAS accounts yet.")
        return None

    options = [slug for slug, _ in accounts]
    label_for = {slug: email for slug, email in accounts}
    active = active_slug(session)
    idx = options.index(active) if active in options else 0

    chosen = st.selectbox(
        "Account",
        options=options,
        index=idx,
        format_func=lambda s: label_for.get(s, s),
        key="acc_picker",
    )
    if chosen != active:
        st.session_state["_active_slug"] = chosen
        st.query_params["account"] = chosen
        if "scheme" in st.query_params:
            del st.query_params["scheme"]
        on_account_change()
        st.rerun()

    if session.is_admin:
        _render_invite_expander(session)

    own_slug = auth.slugify(session.user_email)
    _render_settings_expander(session, chosen, is_owner=chosen == own_slug)
    return chosen


def _render_invite_expander(session: auth.Session) -> None:
    with st.expander("👥 Invite a user"):
        st.caption("Generates a one-time invite link. Share it out-of-band — "
                   "they pick their own password on first visit. Expires in 7 days.")
        with st.form("invite_form", clear_on_submit=True):
            invitee = st.text_input("Email to invite")
            submit = st.form_submit_button("Generate invite", type="primary", use_container_width=True)
        if submit and invitee.strip():
            try:
                token = auth.create_invite(session.user_email, invitee.strip())
            except (ValueError, PermissionError) as e:
                st.error(str(e))
                return
            st.success("Invite link:")
            st.code(f"/invite/{token}", language=None)


def _render_settings_expander(session: auth.Session, slug: str, *, is_owner: bool) -> None:
    with st.expander("⚙️ Settings"):
        st.caption(f"Logged in as **{session.user_email}**"
                   + (" (admin)" if session.is_admin else ""))

        st.markdown(
            "<a href='/account/password' target='_self'>🔒 Change login password</a>",
            unsafe_allow_html=True,
        )
        st.divider()

        if is_owner:
            _render_inline_password_setter(
                session, slug,
                form_key="gmail_pw",
                label="✉️ Set new Gmail App Password",
                input_label="Gmail App Password",
                input_help=None,
                cred_field="app_password",
                success_msg="Gmail App Password saved",
            )
            _render_inline_password_setter(
                session, slug,
                form_key="pdf_pw",
                label="🔑 Set new CAS PDF password",
                input_label="CAS PDF password",
                input_help="6–15 chars: one upper, one lower, one digit.",
                cred_field="pdf_password",
                success_msg="CAS PDF password saved",
                validator=auth.validate_cams_pdf_password,
            )
        else:
            st.caption("This account belongs to another user. Their creds "
                       "aren't editable from here.")
            st.link_button("🔗 Unlink this account", f"/account/{slug}/unlink",
                           use_container_width=True)

        st.divider()
        st.link_button("🚪 Log out", "/logout", type="primary", use_container_width=True)

        st.markdown(
            "<a href='/account/delete' target='_self' "
            "style='color:#f87171;font-size:0.9em;'>🗑️ Delete my account</a>",
            unsafe_allow_html=True,
        )


def _render_inline_password_setter(
    session: auth.Session,
    slug: str,
    *,
    form_key: str,
    label: str,
    input_label: str,
    input_help: str | None,
    cred_field: str,
    success_msg: str,
    validator: Callable[[str], str | None] | None = None,
) -> None:
    """Disclosure pattern: a button by default; click reveals input + Save / Cancel.
    State lives in session_state so the form stays open across reruns until
    explicitly closed."""
    open_key = f"_open_{form_key}_{slug}"

    if not st.session_state.get(open_key):
        if st.button(label, key=f"_btn_{form_key}_{slug}", use_container_width=True):
            st.session_state[open_key] = True
            st.rerun()
        return

    with st.form(f"_form_{form_key}_{slug}", clear_on_submit=True):
        new_value = st.text_input(input_label, type="password", help=input_help)
        cols = st.columns([1, 1])
        with cols[0]:
            save = st.form_submit_button("Save", type="primary", use_container_width=True)
        with cols[1]:
            cancel = st.form_submit_button("Cancel", use_container_width=True)

    if cancel:
        st.session_state[open_key] = False
        st.rerun()
    if save:
        if validator:
            err = validator(new_value)
            if err:
                st.error(err)
                return
        elif not new_value.strip():
            st.error(f"{input_label} is required.")
            return
        auth.update_account_creds(session, slug, **{cred_field: new_value.strip()})
        st.toast(success_msg, icon="✅")
        st.session_state[open_key] = False
        st.rerun()
