"""
Fetch the latest CAS PDF from Gmail via IMAP.

Connects with the account's Gmail App Password, finds the most recent message
matching CAMS sender + subject, and writes the (still-password-protected)
PDF attachment to data/accounts/<slug>/cas/*.pdf.enc — AES-encrypted with
the account's data key so the bytes can't be cat'd off disk without a login.
"""
from __future__ import annotations

import email
import imaplib
import re
from email import policy
from pathlib import Path

from analytics import crypto
from analytics.accounts import AccountContext, app_config

ROOT = Path(__file__).resolve().parent.parent


def _safe_filename(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)[:120]


class NoNewCasError(RuntimeError):
    """Raised when no matching CAMS email is found."""


def _imap_params(ctx: AccountContext) -> tuple[str, int, str, str, str]:
    cfg = app_config()
    return (
        cfg["imap_host"],
        cfg["imap_port"],
        ctx.email,
        ctx.app_password,
        f'(FROM "{cfg["cams_sender"]}" SUBJECT "{cfg["cams_subject"]}")',
    )


def peek_latest_uid(ctx: AccountContext) -> str | None:
    """Latest matching IMAP UID without downloading — used to detect new arrivals."""
    host, port, user, password, criteria = _imap_params(ctx)
    with imaplib.IMAP4_SSL(host, port) as imap:
        imap.login(user, password)
        imap.select("INBOX")
        status, data = imap.search(None, criteria)
        if status != "OK":
            return None
        ids = data[0].split()
        if not ids:
            return None
        return ids[-1].decode()


def fetch_latest_cas(ctx: AccountContext, since_uid: str | None = None) -> Path:
    """Download the latest CAMS PDF and write it encrypted to ctx.cas_dir.
    Returns the on-disk .pdf.enc path.

    If ``since_uid`` is provided, only emails whose IMAP UID is strictly greater
    than this baseline are eligible — guards against picking up an older CAMS
    email (from a previous run or a different sender's old request) that
    happens to still sit in the inbox encrypted with a different password.
    """
    host, port, user, password, criteria = _imap_params(ctx)
    print(f"-> connecting to {host}:{port} as {user}")
    with imaplib.IMAP4_SSL(host, port) as imap:
        imap.login(user, password)
        imap.select("INBOX")

        print(f"-> searching: {criteria}")
        status, data = imap.search(None, criteria)
        if status != "OK":
            raise RuntimeError(f"IMAP search failed: {status}")

        ids = data[0].split()
        if not ids:
            raise NoNewCasError("No matching CAMS emails found in INBOX.")

        if since_uid is not None:
            try:
                baseline = int(since_uid)
                ids = [i for i in ids if int(i) > baseline]
            except ValueError:
                pass
            if not ids:
                raise NoNewCasError(
                    f"No CAMS emails newer than UID {since_uid} — "
                    "the most recent request may still be in transit."
                )

        latest_id = ids[-1]
        print(f"-> {len(ids)} match(es); using latest UID {latest_id.decode()}")

        status, msg_data = imap.fetch(latest_id, "(RFC822)")
        if status != "OK":
            raise RuntimeError(f"IMAP fetch failed: {status}")

        msg = email.message_from_bytes(msg_data[0][1], policy=policy.default)
        print(f"   email date:    {msg['Date']}")
        print(f"   email subject: {msg['Subject']}")

        pdf_part = None
        for part in msg.walk():
            ctype = part.get_content_type()
            fname = part.get_filename() or ""
            if ctype == "application/pdf" or fname.lower().endswith(".pdf"):
                pdf_part = part
                break

        if pdf_part is None:
            raise RuntimeError("No PDF attachment found in the latest CAMS email.")

        attachment_name = pdf_part.get_filename() or f"cas_{latest_id.decode()}.pdf"
        out_name = f"{latest_id.decode()}_{_safe_filename(attachment_name)}.enc"
        target_dir = ctx.cas_dir
        out_path = target_dir / out_name
        if out_path.exists():
            print(f"-> already on disk: {out_path}")
            return out_path
        pdf_bytes = pdf_part.get_payload(decode=True)
        encrypted = crypto.encrypt_bytes(pdf_bytes, ctx.data_key)
        out_path.write_bytes(encrypted)
        print(f"-> saved {out_path} ({out_path.stat().st_size:,} bytes encrypted)")
        return out_path
