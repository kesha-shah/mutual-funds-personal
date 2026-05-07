"""
Fetch the latest CAS PDF from Gmail via IMAP.

Connects with an App Password, finds the most recent message matching the
configured CAMS sender + subject, and writes the PDF attachment to data/cas/.
"""
from __future__ import annotations

import email
import imaplib
import re
from email import policy
from pathlib import Path

from analytics.accounts import account_data_dir, load_config as _load_config

ROOT = Path(__file__).resolve().parent.parent


def cas_dir() -> Path:
    return account_data_dir() / "cas"


def load_config() -> dict:
    return _load_config()


def _safe_filename(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)[:120]


class NoNewCasError(RuntimeError):
    """Raised when no matching CAMS email is found."""


def peek_latest_uid(cfg: dict) -> str | None:
    """Return the IMAP UID of the latest matching CAMS email, without downloading.

    Used to detect a fresh CAS arrival: capture the UID before submitting a
    request, then poll until peek_latest_uid returns a different value.
    """
    g = cfg["gmail"]
    host = g.get("imap_host", "imap.gmail.com")
    port = int(g.get("imap_port", 993))
    user = g["email"]
    password = g["app_password"].replace(" ", "")
    sender = g.get("cams_sender", "donotreply@camsonline.com")
    subject = g.get("cams_subject", "CAMS Mailback Request")

    with imaplib.IMAP4_SSL(host, port) as imap:
        imap.login(user, password)
        imap.select("INBOX")
        criteria = f'(FROM "{sender}" SUBJECT "{subject}")'
        status, data = imap.search(None, criteria)
        if status != "OK":
            return None
        ids = data[0].split()
        if not ids:
            return None
        return ids[-1].decode()


def fetch_latest_cas(cfg: dict) -> Path:
    g = cfg["gmail"]
    host = g.get("imap_host", "imap.gmail.com")
    port = int(g.get("imap_port", 993))
    user = g["email"]
    password = g["app_password"].replace(" ", "")
    sender = g.get("cams_sender", "donotreply@camsonline.com")
    subject = g.get("cams_subject", "CAMS Mailback Request")

    print(f"-> connecting to {host}:{port} as {user}")
    with imaplib.IMAP4_SSL(host, port) as imap:
        imap.login(user, password)
        imap.select("INBOX")

        criteria = f'(FROM "{sender}" SUBJECT "{subject}")'
        print(f"-> searching: {criteria}")
        status, data = imap.search(None, criteria)
        if status != "OK":
            raise RuntimeError(f"IMAP search failed: {status}")

        ids = data[0].split()
        if not ids:
            raise NoNewCasError("No matching CAMS emails found in INBOX.")

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
        out_name = f"{latest_id.decode()}_{_safe_filename(attachment_name)}"
        target_dir = cas_dir()
        target_dir.mkdir(parents=True, exist_ok=True)
        out_path = target_dir / out_name
        if out_path.exists():
            print(f"-> already on disk: {out_path}")
            return out_path
        out_path.write_bytes(pdf_part.get_payload(decode=True))
        print(f"-> saved {out_path} ({out_path.stat().st_size:,} bytes)")
        return out_path


def main() -> None:
    cfg = load_config()
    fetch_latest_cas(cfg)


if __name__ == "__main__":
    main()
