"""
One-shot migration from the legacy config.yaml-based setup to the new
sqlite + encrypted-PDF setup.

Before:
  config.yaml stores accounts (email, pdf_password, app_password, from_date)
  data/accounts/<slug>/cas/*.pdf  (CAMS-password-protected, not AES-encrypted)
  data/accounts/<slug>/parsed_cache.pkl  (plaintext pickle)

After:
  data/app.db with users + cas_accounts + account_access rows
  data/accounts/<slug>/cas/*.pdf.enc  (AES-GCM on top of the CAMS password)
  data/accounts/<slug>/parsed_cache.pkl.enc

The admin (configured via config.yaml admin_email) becomes the owner of every
pre-existing CAS account. Future invitees can be added through the regular
invite flow.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import yaml

from analytics import crypto, db
from analytics.accounts import ACCOUNTS_DIR
from analytics.auth import (
    admin_email,
    any_admin_exists,
    slugify,
)

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.yaml"


def needs_migration() -> bool:
    """True if config.yaml still carries an accounts: block AND we haven't
    yet built the admin user in sqlite."""
    if not CONFIG_PATH.exists():
        return False
    cfg = yaml.safe_load(CONFIG_PATH.read_text()) or {}
    has_accounts_in_yaml = bool(cfg.get("accounts"))
    db.init_schema()
    return has_accounts_in_yaml and not any_admin_exists()


def _legacy_accounts() -> list[dict]:
    cfg = yaml.safe_load(CONFIG_PATH.read_text()) or {}
    out = []
    for slug, info in (cfg.get("accounts") or {}).items():
        info = dict(info)
        info["_slug"] = slug
        out.append(info)
    return out


def _encrypt_files_in_place(slug: str, data_key: bytes) -> tuple[int, int]:
    """Rewrite each *.pdf as *.pdf.enc and re-encrypt parsed_cache.pkl.
    Returns (pdfs_encrypted, caches_encrypted)."""
    acc_dir = ACCOUNTS_DIR / slug
    cas_dir = acc_dir / "cas"
    pdfs = 0
    caches = 0

    if cas_dir.exists():
        for pdf in cas_dir.glob("*.pdf"):
            if pdf.name.endswith(".pdf.enc"):
                continue
            target = pdf.with_suffix(".pdf.enc")
            if target.exists():
                pdf.unlink()
                continue
            target.write_bytes(crypto.encrypt_bytes(pdf.read_bytes(), data_key))
            pdf.unlink()
            pdfs += 1

    old_cache = acc_dir / "parsed_cache.pkl"
    new_cache = acc_dir / "parsed_cache.pkl.enc"
    if old_cache.exists() and not new_cache.exists():
        new_cache.write_bytes(crypto.encrypt_bytes(old_cache.read_bytes(), data_key))
        old_cache.unlink()
        caches += 1

    return pdfs, caches


def _strip_secrets_from_config() -> None:
    """Remove the per-account credential block from config.yaml. Keeps the
    file readable and committable. The non-secret app settings stay."""
    cfg = yaml.safe_load(CONFIG_PATH.read_text()) or {}
    cfg.pop("accounts", None)
    cfg.pop("active_account", None)
    cams = cfg.get("cams") or {}
    for k in ("email", "pdf_password", "from_date", "to_date", "dry_run"):
        cams.pop(k, None)
    if cams:
        cfg["cams"] = cams
    else:
        cfg.pop("cams", None)
    gmail = cfg.get("gmail") or {}
    for k in ("email", "app_password"):
        gmail.pop(k, None)
    if gmail:
        cfg["gmail"] = gmail
    else:
        cfg.pop("gmail", None)
    CONFIG_PATH.write_text(yaml.safe_dump(cfg, sort_keys=False))


def run_migration(admin_password: str) -> dict:
    """Build the sqlite store from the legacy config.yaml + encrypt existing
    data files in place. Returns a summary the UI can display."""
    db.init_schema()
    if any_admin_exists():
        raise RuntimeError("Migration already ran (admin exists).")

    target_admin = admin_email()
    if not target_admin:
        raise RuntimeError("admin_email is not set in config.yaml.")

    accounts = _legacy_accounts()
    if not accounts:
        raise RuntimeError("No accounts block in config.yaml — nothing to migrate.")

    pwd_hash = crypto.hash_password(admin_password)
    kek_salt = crypto.new_kek_salt()
    kek = crypto.derive_kek(admin_password, kek_salt)
    now = datetime.utcnow().isoformat()

    summary = {"admin_email": target_admin, "accounts": []}

    with db.connect() as c:
        c.execute(
            "INSERT INTO users (email, password_hash, kek_salt, is_admin, created_at) "
            "VALUES (?, ?, ?, 1, ?)",
            (target_admin, pwd_hash, kek_salt, now),
        )

        for acc in accounts:
            email = (acc.get("email") or "").strip().lower()
            slug = slugify(email) if email else (acc.get("_slug") or "unknown")
            pdf_pw = acc.get("pdf_password") or email
            app_pw = (acc.get("app_password") or "").replace(" ", "")
            from_date = acc.get("from_date") or "2014-01-01"

            data_key = crypto.new_data_key()
            wrapped = crypto.wrap_key(data_key, kek)
            enc_pdf = crypto.encrypt_str(pdf_pw, data_key)
            enc_app = crypto.encrypt_str(app_pw, data_key)

            c.execute(
                "INSERT INTO cas_accounts (slug, email, from_date, enc_pdf_password, enc_app_password, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (slug, email, from_date, enc_pdf, enc_app, now),
            )
            c.execute(
                "INSERT INTO account_access (user_email, account_slug, wrapped_data_key, is_owner, granted_at) "
                "VALUES (?, ?, ?, 1, ?)",
                (target_admin, slug, wrapped, now),
            )

            pdfs_enc, caches_enc = _encrypt_files_in_place(slug, data_key)
            summary["accounts"].append({
                "slug": slug,
                "email": email,
                "pdfs_encrypted": pdfs_enc,
                "cache_encrypted": caches_enc,
            })

    _strip_secrets_from_config()
    return summary
