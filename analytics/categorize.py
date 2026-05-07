"""
Classify mutual-fund schemes into top-level types and sub-categories from
their name. Heuristic — overrides casparser's bucket when the name disagrees.
"""
from __future__ import annotations


def adjusted_type(scheme_name: str, casparser_type: str) -> str:
    """Override casparser's classification. Returns one of:
    EQUITY, DEBT, MULTI_ASSET, FOREIGN, OTHER. (HYBRID rolls into EQUITY.)"""
    n = (scheme_name or "").lower()

    if "multi asset" in n or "multi-asset" in n or "multiasset" in n:
        return "MULTI_ASSET"

    # FoFs into foreign markets get their own top-level bucket.
    is_fof = any(k in n for k in ("fund of fund", "fund of funds", " fof", "fof "))
    foreign_market = any(k in n for k in (
        "u.s.", "us ", "nasdaq", "s&p 500", "s & p 500",
        "international", "global", "world", "overseas", "emerging market",
    ))
    if is_fof and foreign_market:
        return "FOREIGN"
    # Direct foreign equity funds (no FoF wrapper) also count.
    if foreign_market and (casparser_type or "").upper() in ("EQUITY", "DEBT"):
        return "FOREIGN"

    t = (casparser_type or "OTHER").upper()
    # All hybrid (including aggressive) folds into Equity.
    if t == "HYBRID":
        return "EQUITY"
    return t


def equity_subcategory(scheme_name: str) -> str:
    n = scheme_name.lower()

    # Hybrid schemes that now live under Equity
    if "aggressive hybrid" in n:
        return "Aggressive Hybrid"
    if "balanced" in n and "advantage" in n:
        return "Balanced Advantage"
    if "balanced" in n:
        return "Balanced Hybrid"
    if "conservative" in n and ("hybrid" in n or "fund" in n):
        return "Conservative Hybrid"
    if "arbitrage" in n:
        return "Arbitrage"
    if "equity savings" in n:
        return "Equity Savings"

    # Most-specific cap combinations first
    if any(k in n for k in (
        "large and mid", "large & mid", "largemidcap",
        "large & midcap", "nifty large midcap", "nifty largemidcap",
    )):
        return "Large & Mid Cap"

    if any(k in n for k in ("small cap", "smallcap")) or "nifty smallcap" in n:
        return "Small Cap"

    if any(k in n for k in ("mid cap", "midcap")) or "nifty midcap" in n:
        return "Mid Cap"

    if any(k in n for k in ("large cap", "largecap", "bluechip")):
        return "Large Cap"

    if any(k in n for k in ("multi cap", "multicap")):
        return "Multi Cap"

    if any(k in n for k in ("flexi cap", "flexicap")):
        return "Flexi Cap"

    if "elss" in n or "tax saver" in n:
        return "ELSS"

    if "focused" in n:
        return "Focused"

    if "contra" in n:
        return "Contra"

    if "value fund" in n or " value " in f" {n} ":
        return "Value"

    if any(k in n for k in ("nifty 50", "nifty next 50", "sensex", "nifty 100")):
        return "Large Cap"

    if "nifty 500" in n:
        return "Multi Cap"

    if any(k in n for k in (
        "sector", "thematic", "consumption", "infrastructure", "banking",
        "pharma", "technology", "energy", "manufacturing", "psu", "fmcg",
    )):
        return "Sectoral/Thematic"

    if "etf" in n or "index" in n:
        return "Index Fund"

    # Per user's instruction: no "Other Equity" fallback
    return "Diversified Equity"


def debt_subcategory(scheme_name: str) -> str:
    n = scheme_name.lower()
    # Order matters: most specific first.
    if "overnight" in n:
        return "Debt - Overnight"
    if "liquid" in n:
        return "Debt - Liquid"
    if "ultra short" in n or "ultrashort" in n:
        return "Debt - Ultra Short"
    if "low duration" in n or "savings" in n or "treasury advantage" in n or "treasury adv" in n:
        return "Debt - Low Duration"
    if "money market" in n:
        return "Debt - Money Market"
    if "short duration" in n or "short term" in n:
        return "Debt - Short Term"
    if "medium duration" in n or "medium term" in n:
        return "Debt - Medium Term"
    if "long duration" in n or "long term" in n:
        return "Debt - Long Term"
    if "gilt" in n:
        return "Debt - Gilt"
    if "banking" in n and "psu" in n:
        return "Debt - Banking & PSU"
    if "corporate bond" in n:
        return "Debt - Corporate Bond"
    if "credit risk" in n or " credit " in f" {n} ":
        return "Debt - Credit Risk"
    if "all seasons" in n or "dynamic bond" in n or "dynamic" in n:
        return "Debt - All Seasons"
    if "income" in n:
        return "Debt - Income"
    if "fixed maturity" in n or " fmp" in n:
        return "Debt - FMP"
    return "Debt - Other"


def subcategory(scheme_name: str, scheme_type: str) -> str:
    t = (scheme_type or "").upper()
    if t == "EQUITY":
        return equity_subcategory(scheme_name)
    if t == "DEBT":
        return debt_subcategory(scheme_name)
    if t == "MULTI_ASSET":
        return "Multi Asset"
    if t == "FOREIGN":
        return "Foreign Equity"
    return scheme_type or "Other"
