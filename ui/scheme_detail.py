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
    redemption_amount_for_target_ltcg, simulate_redemption,
)
from ui.format import color_signed, fmt_inr, fmt_pct
from ui.query import clear_query_keep_filters


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


ALL_FOLIOS = "All folios (combined)"


def _folio_label(f) -> str:
    return f"{f.folio} · {f.holder_name or '—'}"


def _render_redemption_calculator(r: SchemeRow, all_rows: list[SchemeRow]) -> None:
    """Inline LTCG/STCG split for a hypothetical redemption.

    A real redemption is placed against one folio, and the AMC applies FIFO
    *within that folio* — so the folio picker isn't cosmetic: the lot set (and
    therefore the LTCG/STCG split) genuinely differs per folio.
    """
    st.markdown("### 💰 Redemption gain breakdown")

    scheme_key = r.isin or r.scheme

    # --- Scope: which folio are we redeeming from? -------------------------
    by_label = {_folio_label(f): f for f in r.folio_details}
    if len(r.folio_details) > 1:
        scope = st.selectbox(
            "Redeem from",
            options=[ALL_FOLIOS] + list(by_label),
            key=f"redeem_folio_{scheme_key}",
            help="Redemptions are placed per folio and the AMC runs FIFO within "
                 "that folio, so the tax split differs by folio. Pick the folio "
                 "you'll actually redeem from.",
        )
    else:
        scope = ALL_FOLIOS

    # A stale session value (folio renamed between reruns) falls back to "all".
    sel_folio = by_label.get(scope)
    if sel_folio is None:
        scope, scope_tx = ALL_FOLIOS, [t for f in r.folio_details for t in f.transactions]
    else:
        scope_tx = sel_folio.transactions
    # Widget state is per (scheme, folio) so switching folios re-derives the
    # smart default instead of carrying over an amount the folio can't cover.
    scope_key = f"{scheme_key}_{sel_folio.folio if sel_folio else 'ALL'}"

    open_lots = build_open_lots(scope_tx)
    available_units = sum(l.units for l in open_lots)

    if r.nav <= 0:
        st.info("NAV unavailable — can't value a redemption right now.")
        return
    if available_units <= 0:
        st.info("No open units to redeem in this folio.")
        return

    available_value = available_units * r.nav

    # Long-term threshold differs: equity = 12 months, debt = 24 months.
    # Keyed on the scheme, not the folio — it's a property of the fund.
    default_treat = "Equity" if r.type in ("EQUITY", "MULTI_ASSET") else "Debt"
    treat_options = ["Equity", "Debt"]
    treat_choice = st.radio(
        "Long-term threshold",
        options=treat_options,
        index=treat_options.index(default_treat),
        horizontal=True,
        key=f"tax_treat_{scheme_key}",
        help="Equity = 12 months, Debt = 24 months. Pick based on the fund's "
             "actual equity composition (≥65% Indian equity → Equity).",
    )
    is_equity = treat_choice == "Equity"

    # Compute the FY equity-LTCG exemption status ONCE (it scans every scheme
    # and folio) and reuse it for both the smart default and the metric row.
    realized = 0.0
    ltcg_room = 0.0
    harvest_amount = 0.0
    if is_equity:
        realized, _, _ = fy_realized_equity_ltcg(all_rows)
        ltcg_room = max(0.0, EQUITY_LTCG_EXEMPTION - realized)
        if ltcg_room > 0:
            harvest_amount = redemption_amount_for_target_ltcg(
                open_lots, r.nav, ltcg_room, is_equity=True
            )
    default_amount = (
        min(harvest_amount, available_value)
        if harvest_amount > 0
        else float(available_value)
    )

    # Pre-fill the widget with the smart default only the first time it
    # renders; afterwards the user's own edits win (widget state persists).
    amount_key = f"redeem_amt_{scope_key}"
    if amount_key not in st.session_state:
        st.session_state[amount_key] = default_amount

    cols = st.columns([2, 1])
    with cols[0]:
        amount = st.number_input(
            "Amount to redeem (₹)",
            min_value=0.0,
            max_value=float(available_value),
            step=10000.0,
            format="%.0f",
            key=amount_key,
            help=f"Max: {fmt_inr(available_value)} ({available_units:,.4f} units @ ₹{r.nav:,.4f})",
        )
    with cols[1]:
        st.metric(
            "Available" if scope == ALL_FOLIOS else "Available in folio",
            fmt_inr(available_value),
        )

    # One-line note about why the box is pre-filled the way it is.
    if is_equity and ltcg_room > 0:
        if harvest_amount > 0:
            full_holding_ltcg = simulate_redemption(
                open_lots, available_units, r.nav, is_equity=True
            ).bucket_gain.get(EQ_LTCG, 0.0)
            holding_word = "holding" if scope == ALL_FOLIOS else "folio"
            if full_holding_ltcg <= ltcg_room:
                st.caption(
                    f"💡 Pre-filled with your entire {holding_word} — redeeming it all yields "
                    f"only {fmt_inr(full_holding_ltcg)} LTCG, within your {fmt_inr(ltcg_room)} room."
                )
            else:
                st.caption(f"💡 Pre-filled to use up your remaining {fmt_inr(ltcg_room)} tax-free room.")
        else:
            st.caption("💡 No long-term lots yet — nothing to harvest tax-free right now.")

    res = simulate_redemption(
        open_lots,
        redeem_units=amount / r.nav,
        current_nav=r.nav,
        is_equity=is_equity,
    )

    ltcg_total = res.bucket_gain.get(EQ_LTCG, 0.0) + res.bucket_gain.get(DEBT_LTCG, 0.0)
    stcg_total = res.bucket_gain.get(EQ_STCG, 0.0) + res.bucket_gain.get(DEBT_SLAB, 0.0)
    threshold_label = "12 months" if is_equity else "24 months"

    # --- Headline answer: the 3-4 numbers the user actually cares about. ---
    if is_equity:
        ltcg_after = realized + max(0.0, ltcg_total)
        excess = max(0.0, ltcg_after - EQUITY_LTCG_EXEMPTION)

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("You redeem", fmt_inr(res.sale_value))
        m2.metric("LTCG (this redemption)", fmt_inr(ltcg_total))
        m3.metric("STCG (taxable)", fmt_inr(stcg_total))
        m4.metric(
            "Tax-Free LTCG Available",
            fmt_inr(ltcg_room),
            help="Equity-LTCG room still available tax-free this FY "
                 f"(₹{EQUITY_LTCG_EXEMPTION:,} cap minus {fmt_inr(realized)} already realized).",
        )

        if excess > 0:
            st.warning(
                f"⚠️ LTCG of {fmt_inr(ltcg_total)} exceeds your tax-free room by "
                f"{fmt_inr(excess)} — that excess is taxable."
            )
        elif ltcg_total > 0:
            st.success(
                f"✅ Entire {fmt_inr(ltcg_total)} LTCG fits within your tax-free room."
            )
    else:
        m1, m2, m3 = st.columns(3)
        m1.metric("You redeem", fmt_inr(res.sale_value))
        m2.metric("LTCG", fmt_inr(ltcg_total))
        m3.metric("STCG / slab", fmt_inr(stcg_total))

    # --- The rest is detail; tuck it away. ---
    with st.expander("How is this calculated?", expanded=False):
        st.markdown(
            f"""
- Amount invested (FIFO cost) &nbsp; **{fmt_inr(res.cost_basis)}**
- Total gain &nbsp; **{fmt_inr(res.total_gain)}**
    - LTCG (held >{threshold_label}) &nbsp; **{fmt_inr(ltcg_total)}**
    - STCG (held ≤{threshold_label}) &nbsp; **{fmt_inr(stcg_total)}**
"""
        )
        if is_equity:
            st.caption(
                f"Equity LTCG exemption ₹{EQUITY_LTCG_EXEMPTION:,}/FY · "
                f"already used {fmt_inr(realized)} across all your equity funds this FY."
            )

    if len(r.folio_details) > 1:
        _render_folio_comparison(r, is_equity, ltcg_room)

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


def _render_folio_comparison(r: SchemeRow, is_equity: bool, ltcg_room: float) -> None:
    """Side-by-side 'if I emptied this folio' tax picture, so the user can see
    which folio is the cheapest one to redeem from before placing the order."""
    rows = []
    for f in r.folio_details:
        lots = build_open_lots(f.transactions)
        units = sum(l.units for l in lots)
        if units <= 0:
            continue
        res = simulate_redemption(lots, units, r.nav, is_equity=is_equity)
        ltcg = res.bucket_gain.get(EQ_LTCG, 0.0) + res.bucket_gain.get(DEBT_LTCG, 0.0)
        stcg = res.bucket_gain.get(EQ_STCG, 0.0) + res.bucket_gain.get(DEBT_SLAB, 0.0)
        rows.append({
            "Folio": f.folio,
            "Name": f.holder_name or "—",
            "Units": units,
            "Value": units * r.nav,
            "LTCG if fully redeemed": ltcg,
            "STCG if fully redeemed": stcg,
            "Tax-free harvest": (
                min(
                    redemption_amount_for_target_ltcg(lots, r.nav, ltcg_room, is_equity=True),
                    units * r.nav,
                )
                if is_equity and ltcg_room > 0
                else None
            ),
        })

    if not rows:
        return

    with st.expander(f"⚖️ Compare folios ({len(rows)})", expanded=False):
        cdf = pd.DataFrame(rows)
        if cdf["Tax-free harvest"].isna().all():
            cdf = cdf.drop(columns=["Tax-free harvest"])
        money = [c for c in cdf.columns if c not in ("Folio", "Name", "Units")]
        styled = (
            cdf.style
            .format({
                **{c: (lambda v: "—" if pd.isna(v) else fmt_inr(v)) for c in money},
                "Units": "{:,.4f}",
            })
            .map(color_signed, subset=["LTCG if fully redeemed", "STCG if fully redeemed"])
        )
        st.dataframe(styled, use_container_width=True, hide_index=True)
        st.caption(
            "Each row assumes you empty *that folio alone* — FIFO restarts per "
            "folio, which is why the split differs."
            + (
                "  \n⚠️ The tax-free room is shared across every folio and scheme, "
                "so these harvest amounts are alternatives, not a total you can add up."
                if is_equity and ltcg_room > 0
                else ""
            )
        )


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
            clear_query_keep_filters()
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
