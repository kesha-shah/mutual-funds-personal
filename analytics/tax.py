"""
Capital-gains tax estimator for a hypothetical mutual-fund redemption.

Indian rules applied (post-July-2024 budget, as of FY 2025-26):
- EQUITY (or hybrid ≥65% equity): STCG 20% (<12 mo), LTCG 12.5% (>12 mo) with
  ₹1,25,000 per-FY exemption across all equity LTCG.
- DEBT / specified MF: gains at slab rate. Lots PURCHASED before 1-Apr-2023 and
  held >24 months get LTCG @ 12.5% (no indexation post-July-2024).
- FIFO unit accounting (per scheme, aggregating all folios for v1).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

UNIT_ADDING_TX = {"PURCHASE", "PURCHASE_SIP", "SWITCH_IN", "DIVIDEND_REINVEST"}
UNIT_REMOVING_TX = {"REDEMPTION", "SWITCH_OUT"}

DEBT_REGIME_CUTOFF = date(2023, 4, 1)
EQUITY_HOLDING_DAYS = 365   # >12 months
DEBT_HOLDING_DAYS = 730     # >24 months
EQUITY_LTCG_EXEMPTION = 125_000   # per FY

# Tax buckets each lot's gain falls into.
EQ_STCG = "EQ_STCG"
EQ_LTCG = "EQ_LTCG"
DEBT_SLAB = "DEBT_SLAB"
DEBT_LTCG = "DEBT_LTCG"


@dataclass
class Lot:
    date: date
    units: float
    nav: float          # cost per unit


@dataclass
class GainEntry:
    lot_date: date
    units: float
    cost: float
    sale: float
    gain: float
    days_held: int
    bucket: str


@dataclass
class TaxResult:
    sale_value: float
    cost_basis: float
    total_gain: float
    bucket_gain: dict[str, float] = field(default_factory=dict)
    breakdown: list[GainEntry] = field(default_factory=list)


def current_fy_window(today: date | None = None) -> tuple[date, date]:
    """Indian FY = Apr 1 → Mar 31. Returns (fy_start, today)."""
    today = today or date.today()
    fy_start_year = today.year if today.month >= 4 else today.year - 1
    return date(fy_start_year, 4, 1), today


def realized_ltcg_in_window(
    transactions: list[dict],
    window_start: date,
    window_end: date,
    long_term_days: int = EQUITY_HOLDING_DAYS,
) -> float:
    """FIFO-replay tx history; sum LTCG-eligible gain realized inside the window.
    For redemption tx in window, classifies each consumed lot by holding period
    at the time of that tx and accumulates only the long-term portion."""
    sorted_tx = sorted(
        transactions,
        key=lambda t: (
            t.get("date") or date.min,
            0 if (t.get("type") or "") in UNIT_ADDING_TX else 1,
        ),
    )
    lots: list[Lot] = []
    total = 0.0
    for tx in sorted_tx:
        ttype = tx.get("type") or ""
        units = tx.get("units")
        d = tx.get("date")
        if not units or not d:
            continue
        if ttype in UNIT_ADDING_TX:
            u = float(units)
            if u <= 0:
                continue
            lots.append(Lot(date=d, units=u, nav=float(tx.get("nav") or 0)))
        elif ttype in UNIT_REMOVING_TX:
            to_remove = abs(float(units))
            in_window = window_start <= d <= window_end
            sale_nav = float(tx.get("nav") or 0)
            while to_remove > 1e-6 and lots:
                lot = lots[0]
                sell = min(lot.units, to_remove)
                if in_window and (d - lot.date).days >= long_term_days:
                    total += sell * (sale_nav - lot.nav)
                lot.units -= sell
                to_remove -= sell
                if lot.units <= 1e-6:
                    lots.pop(0)
    return total


def build_open_lots(transactions: list[dict]) -> list[Lot]:
    """Replay tx history FIFO; return remaining open lots."""
    # Stable sort by date; on the same date, adders come before removers so
    # a same-day buy-then-redeem doesn't accidentally exhaust an older lot.
    sorted_tx = sorted(
        transactions,
        key=lambda t: (
            t.get("date") or date.min,
            0 if (t.get("type") or "") in UNIT_ADDING_TX else 1,
        ),
    )
    lots: list[Lot] = []
    for tx in sorted_tx:
        ttype = tx.get("type") or ""
        units = tx.get("units")
        d = tx.get("date")
        if not units or not d:
            continue
        if ttype in UNIT_ADDING_TX:
            u = float(units)
            if u <= 0:
                continue
            lots.append(Lot(date=d, units=u, nav=float(tx.get("nav") or 0)))
        elif ttype in UNIT_REMOVING_TX:
            to_remove = abs(float(units))
            while to_remove > 1e-6 and lots:
                if lots[0].units <= to_remove + 1e-6:
                    to_remove -= lots[0].units
                    lots.pop(0)
                else:
                    lots[0].units -= to_remove
                    to_remove = 0
    return lots


def _classify(lot_date: date, today: date, is_equity: bool) -> str:
    days = (today - lot_date).days
    if is_equity:
        return EQ_LTCG if days >= EQUITY_HOLDING_DAYS else EQ_STCG
    if lot_date >= DEBT_REGIME_CUTOFF:
        return DEBT_SLAB
    return DEBT_LTCG if days >= DEBT_HOLDING_DAYS else DEBT_SLAB


def simulate_redemption(
    open_lots: list[Lot],
    redeem_units: float,
    current_nav: float,
    is_equity: bool,
    today: date | None = None,
) -> TaxResult:
    """FIFO-consume up to ``redeem_units`` from ``open_lots`` at ``current_nav``,
    classify each consumed slice into a tax bucket, return per-lot breakdown
    + totals. UI handles tax-rate math separately — this function only sorts
    the gains into LTCG/STCG buckets."""
    today = today or date.today()
    available = sum(l.units for l in open_lots)
    redeem_units = min(redeem_units, available)

    breakdown: list[GainEntry] = []
    units_left = redeem_units
    for lot in open_lots:
        if units_left <= 1e-6:
            break
        sell = min(lot.units, units_left)
        sale = sell * current_nav
        cost = sell * lot.nav
        breakdown.append(GainEntry(
            lot_date=lot.date,
            units=sell, cost=cost, sale=sale, gain=sale - cost,
            days_held=(today - lot.date).days,
            bucket=_classify(lot.date, today, is_equity),
        ))
        units_left -= sell

    bucket_gain = {EQ_STCG: 0.0, EQ_LTCG: 0.0, DEBT_SLAB: 0.0, DEBT_LTCG: 0.0}
    for b in breakdown:
        bucket_gain[b.bucket] += b.gain

    sale_value = sum(b.sale for b in breakdown)
    cost_basis = sum(b.cost for b in breakdown)
    return TaxResult(
        sale_value=sale_value,
        cost_basis=cost_basis,
        total_gain=sale_value - cost_basis,
        bucket_gain=bucket_gain,
        breakdown=breakdown,
    )
