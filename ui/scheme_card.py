"""Scheme list: card layout + sortable header.

Each scheme in the portfolio renders as a card showing AMC icon, name,
value, invested, and XIRR. The header above lets the user re-sort. Mobile
uses a stacked layout — CSS media queries swap between the two.
"""
from __future__ import annotations

import streamlit as st

from analytics.portfolio import SchemeRow
from ui.format import fmt_inr
from ui.query import qs_link


_AMC_PALETTE = [
    "#3b82f6", "#10b981", "#f59e0b", "#ef4444",
    "#8b5cf6", "#06b6d4", "#ec4899", "#84cc16",
    "#f97316", "#14b8a6", "#a855f7", "#0ea5e9",
]


def _amc_initials(name: str) -> str:
    parts = (name or "?").strip().split()
    if len(parts) >= 2:
        return (parts[0][0] + parts[1][0]).upper()
    return (name[:2] if len(name) >= 2 else name or "?").upper()


def _amc_color(name: str) -> str:
    if not name:
        return _AMC_PALETTE[0]
    return _AMC_PALETTE[sum(ord(c) for c in name) % len(_AMC_PALETTE)]


CARD_CSS = """
<style>
.mf-card, .mf-sort-header { max-width: 1400px; }
.mf-card {
  border: 1px solid rgba(128,128,128,0.25);
  border-radius: 10px;
  padding: 12px 16px;
  margin-bottom: 8px;
}
.mf-card-row { display: flex; flex-direction: row; align-items: center; gap: 16px; }
.mf-card-icon {
  width: 36px; height: 36px; border-radius: 8px;
  display: flex; align-items: center; justify-content: center;
  color: white; font-weight: 700; font-size: 13px; flex-shrink: 0;
}
.mf-card-name { flex: 1; min-width: 0; }
.mf-card-name-line { font-weight: 600; line-height: 1.3; }
.mf-card-meta { font-size: 0.78em; opacity: 0.7; margin-top: 3px; }
.mf-card-numbers { flex: 3; display: flex; flex-direction: row; gap: 16px; }
.mf-card-cell { flex: 1; min-width: 0; text-align: right; }
.mf-card-label { font-size: 0.72em; opacity: 0.6; margin-top: 2px; }
.mf-sort-header { padding: 6px 16px; margin-bottom: 4px; }
.mf-sort-header .mf-card-icon { background: none !important; visibility: hidden; }
.mf-sort-link {
  text-decoration: none !important;
  color: inherit !important;
  font-size: 0.95em;
  opacity: 0.85;
  font-weight: 600;
}
.mf-sort-link.active { opacity: 1; font-weight: 700; }
.mf-sort-chips { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; margin: 4px 0 12px; }
@media (max-width: 700px) {
  .mf-sort-header { display: none !important; }
  .mf-card-row { flex-direction: column; align-items: stretch; gap: 10px; }
  .mf-card-icon { display: none; }
  .mf-card-numbers { justify-content: space-between; gap: 12px; }
  .mf-card-cell { min-width: 0; text-align: left; }
  .mf-card-cell.mid { text-align: center; }
  .mf-card-cell.right { text-align: right; }
}
@media (min-width: 701px) { .mf-sort-chips { display: none !important; } }
</style>
"""


SORT_KEYS = {
    "name":     lambda r: (r.scheme or "").lower(),
    "value":    lambda r: r.current_value,
    "invested": lambda r: r.invested,
    "xirr":     lambda r: float("-inf") if r.xirr is None else r.xirr,
}
SORT_DEFAULT_ASC = {"name": True, "value": False, "invested": False, "xirr": False}


def render_scheme_card(r: SchemeRow, allocation_pct: float) -> None:
    """Responsive card: single row + icon on desktop; name + numbers stacked on mobile."""
    folio_word = "folio" if len(r.folios) == 1 else "folios"
    xirr_str = f"{r.xirr*100:.2f}%" if r.xirr is not None else "—"
    xirr_color = "#22c55e" if (r.xirr or 0) >= 0 else "#ef4444"
    gain_color = "#22c55e" if r.gain >= 0 else "#ef4444"
    href = qs_link(scheme=r.isin or r.scheme)
    icon_letter = _amc_initials(r.amc or r.scheme)
    icon_color = _amc_color(r.amc or r.scheme)

    st.markdown(
        f"""
        <a href="{href}" target="_self"
           style="text-decoration:none;color:inherit;display:block;">
          <div class="mf-card">
            <div class="mf-card-row">
              <div class="mf-card-icon" style="background:{icon_color};">{icon_letter}</div>
              <div class="mf-card-name">
                <div class="mf-card-name-line">{r.scheme}</div>
                <div class="mf-card-meta">
                  {r.sub_type} · {len(r.folios)} {folio_word} · NAV ₹{r.nav:,.2f}
                </div>
              </div>
              <div class="mf-card-numbers">
                <div class="mf-card-cell">
                  <div style="font-weight:600;">{fmt_inr(r.current_value)}</div>
                  <div class="mf-card-label">{allocation_pct:.1f}% of MF</div>
                </div>
                <div class="mf-card-cell mid">
                  <div>{fmt_inr(r.invested)}</div>
                  <div class="mf-card-label">Invested</div>
                </div>
                <div class="mf-card-cell right">
                  <div style="color:{xirr_color};font-weight:600;">{xirr_str}</div>
                  <div class="mf-card-label" style="color:{gain_color};opacity:1;">
                    {r.gain_pct*100:+.1f}%
                  </div>
                </div>
              </div>
            </div>
          </div>
        </a>
        """,
        unsafe_allow_html=True,
    )


def render_sort_header() -> None:
    """Desktop column-aligned header + mobile pill chips, both rendered;
    CSS media queries hide whichever doesn't apply for the viewport."""
    sort_key = st.session_state.get("_sort_key", "value")
    sort_asc = st.session_state.get("_sort_asc", SORT_DEFAULT_ASC["value"])

    def link(label: str, key: str) -> str:
        is_active = sort_key == key
        arrow = (" ↑" if sort_asc else " ↓") if is_active else ""
        cls = "mf-sort-link active" if is_active else "mf-sort-link"
        return f'<a href="{qs_link(sort=key)}" target="_self" class="{cls}">{label}{arrow}</a>'

    st.markdown(
        f"""
        <div class="mf-sort-header">
          <div class="mf-card-row">
            <div class="mf-card-icon"></div>
            <div class="mf-card-name">{link("Name", "name")}</div>
            <div class="mf-card-numbers">
              <div class="mf-card-cell">{link("Value", "value")}</div>
              <div class="mf-card-cell mid">{link("Invested", "invested")}</div>
              <div class="mf-card-cell right">{link("XIRR", "xirr")}</div>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    chips = []
    for key, label in [("name", "Name"), ("value", "Value"),
                       ("invested", "Invested"), ("xirr", "XIRR")]:
        is_active = sort_key == key
        arrow = (" ↑" if sort_asc else " ↓") if is_active else ""
        bg = "rgba(245,158,11,0.18)" if is_active else "rgba(128,128,128,0.12)"
        weight = "600" if is_active else "400"
        chips.append(
            f'<a href="{qs_link(sort=key)}" target="_self" '
            f'style="text-decoration:none;color:inherit;background:{bg};'
            f'padding:4px 12px;border-radius:14px;font-weight:{weight};'
            f'font-size:0.85em;display:inline-block;">{label}{arrow}</a>'
        )
    st.markdown(
        f'<div class="mf-sort-chips"><span style="opacity:0.65;font-size:0.85em;">'
        f'Sort by:</span>{"".join(chips)}</div>',
        unsafe_allow_html=True,
    )
