"""Inflow planner tab: pick funds you already hold, enter how much you're
putting in (daily / weekly / monthly), and see the combined monthly inflow
grouped by category as a donut.

Entries are saved per account in ``state.json`` (keyed by slug) so they're
still there next time you log in — edit freely, every change is persisted.
The demo account is read-only, so there the planner stays session-only."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from analytics.portfolio import SchemeRow
from analytics.state import load_state, update_state
from ui.donut import render_donut
from ui.format import fmt_inr

# Monthly-equivalent multipliers: daily SIPs run on ~22 business days/month,
# weekly SIPs fire 52/12 ≈ 4.33 times a month.
FREQ_MULT = {"Monthly": 1.0, "Weekly": 52 / 12, "Daily": 22.0}
FREQ_OPTS = list(FREQ_MULT)
# Fresh money (SIP) vs money moved between funds (STP). Both are inflow into
# the target fund, but only SIP is new capital leaving your bank account.
KIND_OPTS = ["SIP", "STP"]

_STATE_KEY = "inflow_planner"


def _k(name: str, slug: str) -> str:
    """Session-state key for the active account.

    Every planner widget key MUST go through this. Streamlit stores a
    multiselect's state as *indices into the options list*, not as values, so
    a key shared between two linked accounts makes account A's indices
    deserialize into account B's fund list on a switch — silently selecting
    the wrong funds at ₹0 and then persisting that over B's saved plan.
    Per-slug keys also give a free re-seed from disk when you switch back."""
    return f"planner_{name}__{slug}"


def _fund_id(r: SchemeRow) -> str:
    """Stable id for a scheme — matches app.py's (isin or scheme) convention."""
    return r.isin or r.scheme


def _load_saved(slug: str) -> dict:
    """{fund_id: {"amount": float, "freq": str, "kind": str}} from disk,
    defensively typed. Entries written before the SIP/STP split have no
    ``kind`` (and a short-lived build wrote it as ``type``) — both read back
    as SIP rather than being dropped."""
    raw = load_state(slug).get(_STATE_KEY, {})
    out: dict[str, dict] = {}
    if isinstance(raw, dict):
        for fid, v in raw.items():
            if isinstance(v, dict):
                freq = v.get("freq")
                kind = v.get("kind") or v.get("type")
                out[fid] = {
                    "amount": float(v.get("amount") or 0.0),
                    "freq": freq if freq in FREQ_MULT else "Monthly",
                    "kind": kind if kind in KIND_OPTS else "SIP",
                }
    return out


def render_inflow_planner(rows: list[SchemeRow], slug: str, is_demo: bool) -> None:
    st.subheader("Plan monthly inflow")
    st.caption(
        "Pick funds you hold, enter how much you invest and how often — daily, "
        "weekly or monthly — and see the combined **monthly** inflow grouped by "
        "category. Daily is converted at 22 business days/month, weekly at "
        "≈4.33 weeks/month. "
        + ("Changes are not saved on the demo account."
           if is_demo else "Your entries are saved and reload next time you log in.")
    )

    if not rows:
        st.info("No funds to plan with yet — load a CAS first.")
        return

    # One row per scheme, sorted by name; keep the first SchemeRow per id for
    # its category (sub_type) and display name.
    by_id: dict[str, SchemeRow] = {}
    for r in sorted(rows, key=lambda r: r.scheme.lower()):
        by_id.setdefault(_fund_id(r), r)

    saved = _load_saved(slug)

    # Seed widget state from the saved plan on first render this session. Once
    # the keys exist, Streamlit drives them and we read the live values back.
    if _k("funds", slug) not in st.session_state:
        st.session_state[_k("funds", slug)] = [fid for fid in saved if fid in by_id]
    for fid, v in saved.items():
        st.session_state.setdefault(_k(f"amt_{fid}", slug), v["amount"])
        st.session_state.setdefault(_k(f"freq_{fid}", slug), v["freq"])
        st.session_state.setdefault(_k(f"kind_{fid}", slug), v["kind"])

    selected = st.multiselect(
        "Funds",
        options=list(by_id),
        format_func=lambda fid: f"{by_id[fid].scheme}  ·  {by_id[fid].sub_type}",
        key=_k("funds", slug),
        placeholder="Select one or more funds you hold…",
        help="Only funds in your CAS appear here.",
    )

    if not selected:
        # Only persist an explicit "clear everything" — never on the first
        # render of a session. On a fresh login the multiselect can briefly
        # report empty before Streamlit hydrates its widget state; treating
        # that as a real clear would wipe the saved plan off disk (which is
        # exactly what made the planner look reset after every deploy).
        if st.session_state.get(_k("touched", slug)):
            _persist(slug, is_demo, {}, set(by_id))
        st.info("Select at least one fund above to start planning.")
        return
    st.session_state[_k("touched", slug)] = True

    # Per-fund entry rows: name | amount | frequency | kind | monthly equivalent.
    hdr = st.columns([4, 2, 2, 1.5, 2])
    hdr[0].markdown("**Fund**")
    hdr[1].markdown("**Amount (₹)**")
    hdr[2].markdown("**Frequency**")
    hdr[3].markdown("**Kind**")
    hdr[4].markdown("**Monthly ≈**")

    plan: list[dict] = []
    to_save: dict[str, dict] = {}
    for fid in selected:
        r = by_id[fid]
        st.session_state.setdefault(_k(f"amt_{fid}", slug), 0.0)
        st.session_state.setdefault(_k(f"freq_{fid}", slug), "Monthly")
        st.session_state.setdefault(_k(f"kind_{fid}", slug), "SIP")
        c = st.columns([4, 2, 2, 1.5, 2])
        c[0].markdown(f"{r.scheme}  \n_{r.sub_type}_")
        amount = c[1].number_input(
            "Amount", min_value=0.0, step=500.0,
            key=_k(f"amt_{fid}", slug), label_visibility="collapsed",
        )
        freq = c[2].selectbox(
            "Frequency", FREQ_OPTS, key=_k(f"freq_{fid}", slug),
            label_visibility="collapsed",
        )
        kind = c[3].selectbox(
            "Kind", KIND_OPTS, key=_k(f"kind_{fid}", slug),
            label_visibility="collapsed",
        )
        monthly = amount * FREQ_MULT[freq]
        c[4].markdown(fmt_inr(monthly) if monthly else "—")
        to_save[fid] = {"amount": amount, "freq": freq, "kind": kind}
        if monthly > 0:
            plan.append({"Category": r.sub_type, "Fund": r.scheme,
                         "Kind": kind, "Monthly": monthly})

    _persist(slug, is_demo, to_save, set(by_id))

    if not plan:
        st.info("Enter an amount for at least one fund to see the chart.")
        return

    fund_df = pd.DataFrame(plan, columns=["Category", "Fund", "Kind", "Monthly"])
    total = fund_df["Monthly"].sum()
    # Split the headline figure: SIP is new money leaving your bank each month,
    # STP is capital already invested being shifted, so only the SIP number is
    # what you actually need to fund.
    sip_total = fund_df.loc[fund_df["Kind"] == "SIP", "Monthly"].sum()
    stp_total = fund_df.loc[fund_df["Kind"] == "STP", "Monthly"].sum()
    st.divider()
    m = st.columns(3)
    m[0].metric("Total monthly inflow", fmt_inr(total))
    m[1].metric("SIP — new money", fmt_inr(sip_total))
    m[2].metric("STP — switched", fmt_inr(stp_total))

    # The original category donut, unchanged.
    cat_order = (
        fund_df.groupby("Category", as_index=False)["Monthly"].sum()
        .sort_values("Monthly", ascending=False)
    )
    cat_labels = cat_order["Category"].tolist()
    cat_df = cat_order.rename(columns={"Category": "Bucket", "Monthly": "Current"})

    st.subheader("Planned inflow by category")
    render_donut(cat_df, "Planned inflow by category", show_value=True,
                 key=_k("cat_donut", slug))

    # Drill-down via pills, not slice clicks: Streamlit only forwards Plotly
    # box/lasso selections, which a pie has none of, so a category click can't
    # be captured — a row of category buttons drives the breakdown instead.
    st.caption("Tap a category to break it down by fund:")
    selected_cat = st.pills(
        "Break down category", options=cat_labels, selection_mode="single",
        key=_k("drill_cat", slug), label_visibility="collapsed",
    )
    if selected_cat:
        sub = (
            fund_df[fund_df["Category"] == selected_cat]
            .rename(columns={"Fund": "Bucket", "Monthly": "Current"})
            [["Bucket", "Current"]]
        )
        st.subheader(f"{selected_cat} — by fund")
        render_donut(sub, f"{selected_cat} by fund", show_value=True,
                     key=_k("fund_donut", slug))

    # Category summary table.
    table = cat_order.copy()
    table["Share"] = (table["Monthly"] / total * 100).round(2).astype(str) + "%"
    st.dataframe(
        table.style.format({"Monthly": fmt_inr}),
        use_container_width=True, hide_index=True,
    )


def _persist(slug: str, is_demo: bool, plan: dict, known_ids: set[str]) -> None:
    """Merge ``plan`` into the saved plan and write it out, but only when
    something actually changed (avoids a disk write on every rerun). No-op on
    the read-only demo account.

    ``known_ids`` is every fund id present in the current CAS. Saved entries
    outside that set are carried over untouched instead of being dropped: a
    scheme that vanishes from the CAS for a run — a re-parse that changes an
    ISIN, a merger, a partial statement — must not silently delete the amount
    you typed for it. Only funds you can actually see and deselect get
    removed."""
    if is_demo:
        return
    current = load_state(slug).get(_STATE_KEY, {})
    if not isinstance(current, dict):
        current = {}
    merged = {fid: v for fid, v in current.items() if fid not in known_ids}
    merged.update(plan)
    if current != merged:
        update_state(slug, **{_STATE_KEY: merged})
