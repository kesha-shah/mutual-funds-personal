"""
Per-account context + non-secret app config.

This module used to own credential storage in config.yaml. That moved to a
local sqlite DB (analytics/db.py) so config.yaml could be safely committed.
What stays here:
  - Resolving paths under data/accounts/<slug>/
  - Building an AccountContext (decrypted creds + data key + paths) from
    a logged-in Session — the rest of the codebase consumes this dataclass
    instead of reaching into auth/db directly.
  - Reading the non-secret app config (playwright, cams sender/subject) from
    config.yaml.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from analytics import auth
from analytics.auth import Session, slugify  # re-export

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.yaml"
ACCOUNTS_DIR = ROOT / "data" / "accounts"


@dataclass
class AccountContext:
    """Everything CAS ingest / portfolio parsing needs for one account.
    Build via account_context(session, slug)."""
    slug: str
    email: str
    from_date: str
    pdf_password: str
    app_password: str
    data_key: bytes

    @property
    def data_dir(self) -> Path:
        p = ACCOUNTS_DIR / self.slug
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def cas_dir(self) -> Path:
        p = self.data_dir / "cas"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def parse_cache_path(self) -> Path:
        return self.data_dir / "parsed_cache.pkl.enc"


def account_context(session: Session, slug: str) -> AccountContext:
    creds = auth.get_account_creds(session, slug)
    return AccountContext(
        slug=slug,
        email=creds["email"],
        from_date=creds["from_date"],
        pdf_password=creds["pdf_password"],
        app_password=creds["app_password"],
        data_key=session.data_key(slug),
    )


def app_config() -> dict:
    """Non-secret config: playwright + CAMS sender/subject + defaults."""
    if not CONFIG_PATH.exists():
        return {}
    cfg = yaml.safe_load(CONFIG_PATH.read_text()) or {}
    return {
        "playwright": cfg.get("playwright") or {"headless": True, "slow_mo_ms": 0},
        "cams_sender": (cfg.get("cams") or {}).get("cams_sender", "donotreply@camsonline.com"),
        "cams_subject": (cfg.get("cams") or {}).get("cams_subject", "CAMS Mailback Request"),
        "imap_host": (cfg.get("gmail") or {}).get("imap_host", "imap.gmail.com"),
        "imap_port": int((cfg.get("gmail") or {}).get("imap_port", 993)),
        "admin_email": cfg.get("admin_email"),
    }


__all__ = [
    "ACCOUNTS_DIR",
    "AccountContext",
    "account_context",
    "app_config",
    "slugify",
]
