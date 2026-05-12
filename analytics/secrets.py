"""
Per-deployment server secret.

A stable random key used to sign cookies and the cross-process session
payload. Generated on first read, then persisted at ``data/.server_secret``
with 0600 permissions. Gitignored, never leaves the machine.

Lives in ``analytics/`` rather than ``auth_server/`` because both the
FastAPI gateway and the Streamlit dashboard need to verify signatures
produced by the other.
"""
from __future__ import annotations

import os
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SECRET_FILE = ROOT / "data" / ".server_secret"


def server_secret() -> bytes:
    if SECRET_FILE.exists():
        return SECRET_FILE.read_bytes()
    SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
    secret = secrets.token_bytes(32)
    SECRET_FILE.write_bytes(secret)
    os.chmod(SECRET_FILE, 0o600)
    return secret
