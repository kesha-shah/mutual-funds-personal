"""
Server-side session cookies for the FastAPI auth layer.

The actual ``auth.Session`` (with the user's KEK + unwrapped data keys)
lives in ``analytics.auth._SESSIONS``, keyed by an opaque token. The cookie
carries just that token, signed with the shared server secret so a tampered
cookie won't validate. The signed value is what the browser stores.
"""
from __future__ import annotations

from fastapi import Request, Response
from itsdangerous import BadSignature, URLSafeSerializer

from analytics import auth
from analytics.secrets import server_secret

COOKIE_NAME = "mf_auth"
COOKIE_MAX_AGE = int(auth.SESSION_TTL.total_seconds())

_serializer = URLSafeSerializer(server_secret(), salt="mf-session")


def attach(response: Response, token: str) -> None:
    response.set_cookie(
        key=COOKIE_NAME,
        value=_serializer.dumps(token),
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        # secure=True is enabled in production behind HTTPS — left off here
        # so local development over http://localhost works.
    )


def detach(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME)


def token_from_request(request: Request) -> str | None:
    raw = request.cookies.get(COOKIE_NAME)
    if not raw:
        return None
    try:
        return _serializer.loads(raw)
    except BadSignature:
        return None


def session_from_request(request: Request) -> auth.Session | None:
    tok = token_from_request(request)
    if not tok:
        return None
    return auth.get_session(tok)


def token_from_cookie_value(raw: str | None) -> str | None:
    """Same as token_from_request but for WebSocket scopes where we only
    have the raw cookie string."""
    if not raw:
        return None
    try:
        return _serializer.loads(raw)
    except BadSignature:
        return None
