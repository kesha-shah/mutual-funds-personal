"""
Extract folio holder names from the raw CAS PDF text.

casparser doesn't capture holder names — only folio number, AMC, PAN, KYC.
The PDF prints the name on the line directly below "Folio No: <number>".
"""
from __future__ import annotations

import re
from pathlib import Path

from pdfminer.high_level import extract_text

_FOLIO_RE = re.compile(r"^Folio No:\s*(\S.*)$")


def extract_folio_names(pdf_path: Path, password: str) -> dict[str, str]:
    """Return {folio_number: holder_name} parsed from the CAS PDF.
    Uses the first occurrence; later pages repeat the same header."""
    text = extract_text(str(pdf_path), password=password)
    out: dict[str, str] = {}
    lines = text.split("\n")
    for i, line in enumerate(lines):
        m = _FOLIO_RE.match(line.strip())
        if not m:
            continue
        folio = m.group(1).strip()
        if folio in out:
            continue
        for j in range(i + 1, min(i + 5, len(lines))):
            cand = lines[j].strip()
            if cand:
                out[folio] = cand
                break
    return out
