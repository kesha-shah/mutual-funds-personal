"""
Signed session payload exchanged between the FastAPI auth gateway and the
Streamlit dashboard process.

Auth server holds the full ``auth.Session`` (with KEK + data keys) in memory.
Streamlit runs in a separate process and doesn't share that dict. So the
auth server builds a payload — user_email, is_admin, and the per-account
data keys — signs it with the shared server secret, and forwards it to
Streamlit as an HTTP header. Streamlit verifies the signature and
reconstructs what it needs.

The KEK never leaves auth_server. Operations that need the KEK (link
account, change creds, delete account) are auth_server pages.
"""
from __future__ import annotations

import base64

from itsdangerous import BadSignature, URLSafeSerializer

from analytics.secrets import server_secret

_serializer = URLSafeSerializer(server_secret(), salt="mf-session-payload")


def build(user_email: str, is_admin: bool, data_keys: dict[str, bytes]) -> str:
    return _serializer.dumps({
        "u": user_email,
        "a": bool(is_admin),
        "k": {slug: base64.b64encode(key).decode() for slug, key in data_keys.items()},
    })


def parse(signed: str) -> dict | None:
    """Reverse of build(). Returns None on tampering. The result is a dict
    with keys ``user_email``, ``is_admin``, ``data_keys`` (bytes values)."""
    try:
        data = _serializer.loads(signed)
    except BadSignature:
        return None
    return {
        "user_email": data["u"],
        "is_admin": bool(data.get("a", False)),
        "data_keys": {slug: base64.b64decode(k) for slug, k in (data.get("k") or {}).items()},
    }
