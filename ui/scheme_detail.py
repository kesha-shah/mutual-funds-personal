"""Per-scheme detail page: header metrics, folios table, redemption tax
calculator, and the raw transactions log.
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from analytics.portfolio import SchemeRow
from analytics.tax import (
    DEBT_LTCG, DEBT_SLAB, EQ_LTCG, EQ_STCG, EQUITY_LTCG_EXEMPTION,
    build_open_lots, current_fy_window, realized_ltcg_in_window,
    simulate_redemption,
)
from ui.format import color_signed, fmt_inr, fmt_pct
from ui.query import clear_query_keep_account


def fy_realized_equity_ltcg(all_rows: list[SchemeRow]) -> tuple[float, date, date]:
    """Sum equity LTCG already realized in the current FY across all schemes."""
    fy_start, fy_end = current_fy_window()
    total = 0.0
    for sch in all_rows:
        if sch.type != "EQUITY":
            continue
        for f in sch.folio_details:
            total += realized_ltcg_in_window(f.transactions, fy_start, fy_end)
    return total, fy_start, fy_end


def _render_redemption_calculator(r: SchemeRow, all_rows: list[SchemeRow]) -> None:
    """Inline LTCG/STCG split for a hypothetical redemption — FIFO across all
    folios of this scheme."""
    st.markdown("### 💰 Redemption gain breakdown")

    all_tx: list[dict] = []
    for f in r.folio_details:
        all_tx.extend(f.transactions)
    open_lots = build_open_lots(all_tx)
    available_units = sum(l.units for l in open_lots)

    if available_units <= 0 or r.nav <= 0:
        st.info("No open units to redeem (or NAV unavailable).")
        return

    available_value = available_units * r.nav

    # Long-term threshold differs: equity = 12 months, debt = 24 months.
    default_treat = "Equity" if r.type in ("EQUITY", "MULTI_ASSET") else "Debt"
    treat_options = ["Equity", "Debt"]
    treat_choice = st.radio(
        "Long-term threshold",
        options=treat_options,
        index=treat_options.index(default_treat),
        horizontal=True,
        key=f"tax_treat_{r.isin or r.scheme}",
        help="Equity = 12 months, Debt = 24 months. Pick based on the fund's "
             "actual equity composition (≥65% Indian equity → Equity).",
    )
    is_equity = treat_choice == "Equity"

    cols = st.columns([2, 1])
    with cols[0]:
        amount = st.number_input(
            "Amount to redeem (₹)",
            min_value=0.0,
            max_value=float(available_value),
            value=float(available_value),
            step=10000.0,
            format="%.0f",
            key=f"redeem_amt_{r.isin or r.scheme}",
            help=f"Max: {fmt_inr(available_value)} ({available_units:,.4f} units @ ₹{r.nav:,.4f})",
        )
    with cols[1]:
        st.metric("Available", fmt_inr(available_value))

    res = simulate_redemption(
        open_lots,
        redeem_units=amount / r.nav,
        current_nav=r.nav,
        is_equity=is_equity,
    )

    ltcg_total = res.bucket_gain.get(EQ_LTCG, 0.0) + res.bucket_gain.get(DEBT_LTCG, 0.0)
    stcg_total = res.bucket_gain.get(EQ_STCG, 0.0) + res.bucket_gain.get(DEBT_SLAB, 0.0)
    threshold_label = "12 months" if is_equity else "24 months"

    st.markdown(
        f"""
- Sale value &nbsp; **{fmt_inr(res.sale_value)}**
- Amount invested (FIFO) &nbsp; **{fmt_inr(res.cost_basis)}**
- Total gain &nbsp; **{fmt_inr(res.total_gain)}**
    - LTCG (held >{threshold_label}) &nbsp; **{fmt_inr(ltcg_total)}**
    - STCG (held ≤{threshold_label}) &nbsp; **{fmt_inr(stcg_total)}**
"""
    )

    # FY exemption tracker (only meaningful for equity LTCG).
    if is_equity:
        realized, fy_start, fy_end = fy_realized_equity_ltcg(all_rows)
        ltcg_after = realized + max(0.0, ltcg_total)
        remaining_now = max(0.0, EQUITY_LTCG_EXEMPTION - realized)
        remaining_after = max(0.0, EQUITY_LTCG_EXEMPTION - ltcg_after)
        excess = max(0.0, ltcg_after - EQUITY_LTCG_EXEMPTION)

        st.markdown(
            f"""
**Equity LTCG exemption — FY {fy_start.strftime('%b %Y')} → {fy_end.strftime('%d %b %Y')}** &nbsp;(₹{EQUITY_LTCG_EXEMPTION:,}/yr cap)
- Already realized this FY (across all your equity funds) &nbsp; **{fmt_inr(realized)}**
- LTCG room remaining today &nbsp; **{fmt_inr(remaining_now)}**
- If you proceed with this redemption &nbsp; **{fmt_inr(remaining_after)}** room left
"""
        )
        if excess > 0:
            st.caption(
                f"⚠️ This redemption would push you ₹{excess:,.0f} over the "
                f"₹{EQUITY_LTCG_EXEMPTION:,} exemption — that excess is taxable LTCG."
            )

    with st.expander(f"📋 Lot-by-lot breakdown ({len(res.breakdown)} lots)", expanded=False):
        lot_rows = [{
            "Purchase date": b.lot_date,
            "Units": b.units,
            "Cost": b.cost,
            "Sale": b.sale,
            "Gain": b.gain,
            "Days held": b.days_held,
            "Type": "LTCG" if b.bucket in (EQ_LTCG, DEBT_LTCG) else "STCG",
        } for b in res.breakdown]
        if lot_rows:
            ldf = pd.DataFrame(lot_rows)
            styled = (
                ldf.style
                .format({
                    "Cost": fmt_inr, "Sale": fmt_inr, "Gain": fmt_inr,
                    "Units": "{:,.4f}",
                })
                .map(color_signed, subset=["Gain"])
            )
            st.dataframe(styled, use_container_width=True, hide_index=True)


def _render_folios_table(r: SchemeRow) -> None:
    folio_df = pd.DataFrame([{
        "Folio": f.folio,
        "Name": f.holder_name or "—",
        "Invested": f.invested,
        "Current": f.current_value,
        "Units": f.units,
        "Gain (₹)": f.gain,
        "Gain %": f.gain_pct * 100,
        "XIRR %": (f.xirr * 100) if f.xirr is not None else None,
        "Txns": len(f.transactions),
    } for f in r.folio_details])

    styled = (
        folio_df.style
        .format({
            "Invested": fmt_inr,
            "Current": fmt_inr,
            "Gain (₹)": fmt_inr,
            "Units": "{:,.4f}",
            "Gain %": "{:.2f}%",
            "XIRR %": lambda v: "—" if pd.isna(v) else f"{v:.2f}%",
        })
        .map(color_signed, subset=["Gain (₹)", "Gain %", "XIRR %"])
    )
    st.dataframe(styled, use_container_width=True, hide_index=True)


def _render_transactions(r: SchemeRow) -> None:
    total_tx = sum(len(f.transactions) for f in r.folio_details)
    with st.expander(f"📜 Transactions ({total_tx})", expanded=False):
        rows_tx = []
        for f in r.folio_details:
            for t in f.transactions:
                rows_tx.append({
                    "Date": t["date"],
                    "Folio": f.folio,
                    "Type": t["type"],
                    "Amount (₹)": t.get("amount"),
                    "Units": t.get("units"),
                    "NAV": t.get("nav"),
                    "Balance units": t.get("balance"),
                    "Description": t.get("description") or "",
                })
        if not rows_tx:
            st.caption("No transactions on file.")
            return
        tx_df = pd.DataFrame(rows_tx).sort_values("Date", ascending=False)

        def _num(v):
            return f"{v:,.4f}" if v is not None and not pd.isna(v) else "—"
        styled = (
            tx_df.style
            .format({
                "Amount (₹)": lambda v: fmt_inr(v) if v is not None and not pd.isna(v) else "—",
                "Units": _num, "NAV": _num, "Balance units": _num,
            })
            .map(color_signed, subset=["Amount (₹)"])
        )
        st.dataframe(styled, use_container_width=True, hide_index=True)


def render_scheme_detail(r: SchemeRow, all_rows: list[SchemeRow]) -> None:
    """Drawer-style detail panel shown when the user clicks a scheme card."""
    st.divider()
    header_cols = st.columns([6, 1])
    with header_cols[0]:
        st.subheader(r.scheme)
        st.caption(f"{r.amc} · {r.sub_type} · ISIN {r.isin or '—'}")
    with header_cols[1]:
        if st.button("Close", use_container_width=True, key=f"close_detail_{r.isin or r.scheme}"):
            clear_query_keep_account()
            st.rerun()

    cols = st.columns(4)
    cols[0].metric("Invested", fmt_inr(r.invested))
    cols[1].metric("Current", fmt_inr(r.current_value))
    gain_color = "🟢" if r.gain >= 0 else "🔴"
    cols[2].metric("Gain", f"{gain_color} {fmt_inr(r.gain)}", f"{r.gain_pct*100:.2f}%")
    xirr_color = "🟢" if (r.xirr or 0) >= 0 else "🔴"
    cols[3].metric("XIRR", f"{xirr_color} {fmt_pct(r.xirr)}")

    nav_str = f"₹{r.nav:.4f}" if r.nav else "—"
    st.caption(f"Units held: {r.units:,.4f}  ·  NAV {nav_str} ({r.nav_source}, {r.nav_date})")

    st.markdown(f"**Folios ({len(r.folio_details)})**")
    _render_folios_table(r)

    # Redemption tax calculator (toggle).
    tax_open_key = f"tax_open_{r.isin or r.scheme}"
    if st.button(
        "💰 Calculate gain on redemption",
        key=f"tax_btn_{r.isin or r.scheme}",
        help="Show LTCG/STCG split of the gain if you redeem this scheme.",
    ):
        st.session_state[tax_open_key] = not st.session_state.get(tax_open_key, False)
    if st.session_state.get(tax_open_key, False):
        _render_redemption_calculator(r, all_rows)

    _render_transactions(r)
