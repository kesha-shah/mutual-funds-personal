"""Display formatters and shared display constants for the dashboard."""
from __future__ import annotations

import pandas as pd

# Asset-class top-level labels. Lives here (not in analytics/categorize) because
# it's purely a display concern — the analytics layer uses raw enum strings.
TYPE_DISPLAY = {
    "EQUITY": "Equity",
    "DEBT": "Debt",
    "MULTI_ASSET": "Multi Asset",
    "FOREIGN": "Foreign Funds",
    "HYBRID": "Hybrid",
    "OTHER": "Other",
}


def fmt_inr(amount: float | None) -> str:
    """Indian-locale formatting: 25974239 → '₹2,59,74,239'."""
    if amount is None or pd.isna(amount):
        return "—"
    n = abs(int(round(amount)))
    sign = "-" if amount < 0 else ""
    s = str(n)
    if len(s) <= 3:
        return f"{sign}₹{s}"
    last3 = s[-3:]
    rest = s[:-3]
    groups: list[str] = []
    while len(rest) > 2:
        groups.append(rest[-2:])
        rest = rest[:-2]
    if rest:
        groups.append(rest)
    groups.reverse()
    return f"{sign}₹{','.join(groups)},{last3}"


def fmt_pct(x: float | None) -> str:
    return f"{x*100:.2f}%" if x is not None else "—"


def color_signed(val) -> str:
    """pandas Styler cell colour: green for positive, red for negative."""
    if val is None or pd.isna(val):
        return ""
    return "color: #16a34a; font-weight: 600" if val > 0 else "color: #dc2626; font-weight: 600"
