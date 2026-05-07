"""
Multi-account config management.

The config.yaml stores per-account credentials in an `accounts` dict and
points `active_account` at one of them. Account-specific data (CAS PDFs,
parse cache, fetch state) lives under data/accounts/<slug>/.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.yaml"
ACCOUNTS_DIR = ROOT / "data" / "accounts"

# Legacy paths from the pre-multi-account layout — migrated automatically.
LEGACY_CAS_DIR = ROOT / "data" / "cas"
LEGACY_STATE = ROOT / "data" / "state.json"
LEGACY_PARSE_CACHE = ROOT / "data" / "parsed_cache.pkl"


def _read() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    return yaml.safe_load(CONFIG_PATH.read_text()) or {}


def _write(cfg: dict) -> None:
    CONFIG_PATH.write_text(yaml.safe_dump(cfg, sort_keys=False))


def slugify(name: str) -> str:
    """Filesystem-safe slug for an account display name (typically email)."""
    return re.sub(r"[^A-Za-z0-9_-]+", "_", name).strip("_") or "account"


def _migrate_if_needed(cfg: dict) -> dict:
    """Wrap the legacy flat config (cams.email, gmail.app_password, …) into
    a single account so the rest of the code can rely on the new structure.
    Also moves the legacy data/ folders under data/accounts/<slug>/."""
    if cfg.get("accounts") and cfg.get("active_account"):
        return cfg
    cams = cfg.get("cams") or {}
    gmail = cfg.get("gmail") or {}
    email = cams.get("email") or gmail.get("email") or "default"
    slug = slugify(email)
    cfg["accounts"] = {
        slug: {
            "email": email,
            "pdf_password": cams.get("pdf_password"),
            "app_password": (gmail.get("app_password") or "").replace(" ", ""),
            "from_date": cams.get("from_date") or "2014-01-01",
        }
    }
    cfg["active_account"] = slug
    _write(cfg)

    target = ACCOUNTS_DIR / slug
    target.mkdir(parents=True, exist_ok=True)
    if LEGACY_CAS_DIR.exists() and not (target / "cas").exists():
        shutil.move(str(LEGACY_CAS_DIR), str(target / "cas"))
    if LEGACY_STATE.exists() and not (target / "state.json").exists():
        shutil.move(str(LEGACY_STATE), str(target / "state.json"))
    if LEGACY_PARSE_CACHE.exists() and not (target / "parsed_cache.pkl").exists():
        shutil.move(str(LEGACY_PARSE_CACHE), str(target / "parsed_cache.pkl"))
    return cfg


def load_config() -> dict:
    """Load config.yaml and merge the active account's credentials into the
    top-level cams + gmail sections that the rest of the codebase expects."""
    cfg = _read()
    cfg = _migrate_if_needed(cfg)
    name = cfg["active_account"]
    acc = cfg["accounts"][name]
    cams = cfg.setdefault("cams", {})
    gmail = cfg.setdefault("gmail", {})
    cams["email"] = acc.get("email")
    cams["pdf_password"] = acc.get("pdf_password")
    cams["from_date"] = acc.get("from_date") or "2014-01-01"
    cams.setdefault("to_date", "today")
    cams.setdefault("dry_run", False)
    gmail["email"] = acc.get("email")
    gmail["app_password"] = (acc.get("app_password") or "").replace(" ", "")
    gmail.setdefault("imap_host", "imap.gmail.com")
    gmail.setdefault("imap_port", 993)
    gmail.setdefault("cams_sender", "donotreply@camsonline.com")
    gmail.setdefault("cams_subject", "CAMS Mailback Request")
    cfg["_active_account"] = name
    return cfg


def list_accounts() -> list[tuple[str, str]]:
    """Return [(slug, email)] for every account."""
    cfg = _read()
    return [(slug, info.get("email", slug)) for slug, info in (cfg.get("accounts") or {}).items()]


def active_account_slug() -> str:
    cfg = load_config()
    return cfg["_active_account"]


def set_active(slug: str) -> None:
    cfg = _read()
    if slug not in (cfg.get("accounts") or {}):
        raise KeyError(f"unknown account: {slug}")
    cfg["active_account"] = slug
    _write(cfg)


def get_account(slug: str) -> dict:
    cfg = _read()
    return (cfg.get("accounts") or {}).get(slug, {})


def upsert_account(slug: str, **fields) -> None:
    cfg = _read()
    cfg.setdefault("accounts", {})
    cfg["accounts"].setdefault(slug, {})
    cfg["accounts"][slug].update({k: v for k, v in fields.items() if v is not None})
    if "active_account" not in cfg:
        cfg["active_account"] = slug
    _write(cfg)
    (ACCOUNTS_DIR / slug).mkdir(parents=True, exist_ok=True)


def delete_account(slug: str) -> None:
    cfg = _read()
    if slug not in (cfg.get("accounts") or {}):
        return
    del cfg["accounts"][slug]
    if cfg.get("active_account") == slug:
        remaining = list(cfg["accounts"].keys())
        cfg["active_account"] = remaining[0] if remaining else None
    _write(cfg)
    # We deliberately do NOT delete the data folder — the user can clean it
    # up manually if they want; auto-deletion would silently destroy data.


def account_data_dir(slug: str | None = None) -> Path:
    if slug is None:
        slug = active_account_slug()
    p = ACCOUNTS_DIR / slug
    p.mkdir(parents=True, exist_ok=True)
    return p
