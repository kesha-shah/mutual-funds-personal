"""
Fetch the latest NAVs published by AMFI (https://www.amfiindia.com).

The endpoint is a free, unauthenticated pipe-separated daily file. Cached
locally per-day so we hit it at most once per session per day.

Besides NAVs, the file is also our source of truth for which AMC a scheme
belongs to: it is laid out as section headers ("Zerodha Mutual Fund") followed
by that fund house's schemes. The CAS can't be trusted for this — casparser
only recognises an AMC heading that ends in "MF"/"Mutual Fund", so a house
printed as e.g. "Zerodha Fund House" silently inherits the previous AMC's
name and its schemes get filed under the wrong house.
"""
from __future__ import annotations

import json
import urllib.request
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAV_CACHE = ROOT / "data" / "nav_cache.json"
AMFI_URL = "https://portal.amfiindia.com/spages/NAVAll.txt"

# Section headers that group schemes but aren't fund houses.
_SCHEME_TYPE_PREFIXES = ("open ended", "close ended", "interval fund")


def _fetch_amfi() -> tuple[dict[str, tuple[float, str]], dict[str, str]]:
    """Returns (ISIN → (NAV, ISO date string), ISIN → AMC). Pure HTTP, no auth."""
    req = urllib.request.Request(AMFI_URL, headers={"User-Agent": "mfportfolio/0.1"})
    text = urllib.request.urlopen(req, timeout=60).read().decode("utf-8", errors="ignore")
    nav: dict[str, tuple[float, str]] = {}
    amc_by_isin: dict[str, str] = {}
    current_amc = ""
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if ";" not in line:
            # Either a scheme-type header or a fund-house name. Only the
            # latter is an AMC.
            if not line.lower().startswith(_SCHEME_TYPE_PREFIXES):
                current_amc = line
            continue
        if line.startswith("Scheme Code"):
            continue
        parts = line.split(";")
        # AMFI has grown columns over time (a Plan and an Option column were
        # inserted before NAV in 2026), so index NAV and date from the end
        # rather than from a fixed position.
        if len(parts) < 6:
            continue
        isin_div, isin_growth = parts[1], parts[2]
        nav_str, nav_date_str = parts[-2].strip(), parts[-1].strip()
        if not nav_str or nav_str.upper() in {"N.A.", "NA", "-"}:
            continue
        try:
            nav_val = float(nav_str)
            d = datetime.strptime(nav_date_str, "%d-%b-%Y").date()
        except ValueError:
            continue
        for isin in (isin_div.strip(), isin_growth.strip()):
            if isin and isin != "-":
                nav[isin] = (nav_val, d.isoformat())
                if current_amc:
                    amc_by_isin[isin] = current_amc
    return nav, amc_by_isin


def _load(force_refresh: bool = False) -> tuple[dict[str, tuple[float, date]], dict[str, str]]:
    """Day-cached AMFI data: (ISIN → (NAV, date), ISIN → AMC)."""
    if not force_refresh and NAV_CACHE.exists():
        try:
            cached = json.loads(NAV_CACHE.read_text())
            # "amc" missing = cache written before AMC mapping existed; refetch.
            if cached.get("fetched_on") == date.today().isoformat() and "amc" in cached:
                return (
                    {k: (float(v[0]), date.fromisoformat(v[1]))
                     for k, v in cached["nav"].items()},
                    dict(cached["amc"]),
                )
        except Exception:
            pass

    raw, amc = _fetch_amfi()
    if not raw:
        # A layout change we don't understand — keep whatever the cache holds
        # rather than overwriting it with nothing.
        raise ValueError("AMFI NAV file parsed to zero schemes — layout changed?")
    NAV_CACHE.parent.mkdir(parents=True, exist_ok=True)
    NAV_CACHE.write_text(
        json.dumps({"fetched_on": date.today().isoformat(), "nav": raw, "amc": amc})
    )
    return (
        {k: (float(v[0]), date.fromisoformat(v[1])) for k, v in raw.items()},
        amc,
    )


def get_latest_nav(force_refresh: bool = False) -> dict[str, tuple[float, date]]:
    """ISIN → (latest NAV, NAV date). Cached for the calendar day."""
    return _load(force_refresh)[0]


def get_amc_by_isin(force_refresh: bool = False) -> dict[str, str]:
    """ISIN → AMC name, as AMFI groups them. Cached for the calendar day."""
    return _load(force_refresh)[1]
