"""ACTION360 - Customer 360 & Next Best Action Copilot (Streamlit in Snowflake).

Dashboard -> select customer -> context bar -> Customer 360 / Next best action / Offers / Interactions.
Business logic lives in Snowflake (rules, procedures, agent); this file only renders validated contracts.
All data is synthetic. Downstream execution is SIMULATED.
"""
from __future__ import annotations

import html
import logging

import altair as alt
import pandas as pd
import streamlit as st

import contracts as k
import data as d
import state

log = logging.getLogger("action360.app")

st.set_page_config(page_title="ACTION360 Copilot", page_icon=":material/hub:", layout="wide")

st.markdown("""
<style>
  .block-container {padding-top: 1.4rem; padding-bottom: 3rem; max-width: 1440px;}
  h1 {font-size: 1.65rem !important; font-weight: 700 !important; margin-bottom: .1rem !important;}
  h3 {font-size: 1.05rem !important;}
  .a360-sub {color:#5b6b7f; font-size:.9rem; margin:-.2rem 0 1rem 0;}
  .a360-eyebrow {font-size:.72rem; font-weight:700; letter-spacing:.08em; color:#5b6b7f; text-transform:uppercase; margin-bottom:.15rem;}
  .a360-hero {font-size:1.6rem; font-weight:700; color:#0b2b4c; line-height:1.25; margin:.1rem 0 .25rem 0;}
  .a360-name {font-size:1.15rem; font-weight:700; color:#0b2b4c;}
  .a360-id {font-size:.85rem; color:#5b6b7f; font-weight:500; margin-left:.4rem;}
  .a360-chip {display:inline-block; padding:2px 10px; border-radius:999px; font-size:.75rem; font-weight:600;
              margin:.25rem .35rem 0 0; border:1px solid #dde5ee; background:#f4f7fb; color:#0b2b4c;}
  .c-HIGH, .s-bad {background:#fdecec; color:#a8261d; border-color:#f5c2be;}
  .c-MEDIUM, .s-warn {background:#fff5e5; color:#8a5300; border-color:#f3d7a6;}
  .c-LOW, .s-ok {background:#e8f5ec; color:#1b6b34; border-color:#b9e0c4;}
  .c-NEGATIVE {background:#fdecec; color:#a8261d; border-color:#f5c2be;}
  .c-POSITIVE {background:#e8f5ec; color:#1b6b34; border-color:#b9e0c4;}
  .s-muted {background:#f1f3f5; color:#5b6b7f;}
  .s-info {background:#e7f1fb; color:#0b5cad; border-color:#c3dbf3;}
  .s-ai {background:#f3ecfb; color:#6a2fa6; border-color:#dcc9f1;}
  .a360-k {font-size:.78rem; color:#5b6b7f; font-weight:600; margin-top:.55rem;}
  .a360-v {font-size:.92rem; color:#0b2b4c;}
  .a360-rule {font-size:.86rem; color:#0b2b4c; margin:.12rem 0;}
  .a360-muted {color:#5b6b7f; font-size:.84rem;}
  div[data-testid="stMetricValue"] {font-size:1.35rem;}
</style>""", unsafe_allow_html=True)

ACTION_LABEL = {
    "SERVICE_RECOVERY": "Service recovery", "COMPLAINT_ESCALATION": "Complaint escalation",
    "PAYMENT_PLAN_DISCUSSION": "Payment-plan discussion", "RETENTION_OFFER": "Retention offer",
    "RENEWAL_REMINDER": "Renewal reminder", "PRODUCT_UPGRADE": "Product upgrade", "CROSS_SELL": "Cross-sell",
    "COVERAGE_REVIEW": "Coverage review", "PROACTIVE_SERVICE_CALL": "Proactive service call",
    "MISSING_DOCUMENT_REQUEST": "Missing-document request", "UNDERWRITING_FOLLOW_UP": "Underwriting follow-up",
    "CLAIM_FOLLOW_UP": "Claim follow-up", "NO_ACTION_MONITOR": "No action - monitor",
}
SIGNAL_LABEL = {"NEG_SENTIMENT": "Negative sentiment", "UNRESOLVED": "Unresolved complaints", "CUSTOMER_VALUE": "Customer value",
                "COMPETITOR_MENTION": "Competitor mention", "RENEWAL_PROXIMITY": "Renewal approaching",
                "MISSED_PAYMENTS": "Missed payments", "RESTRUCTURE_REQ": "Restructure request", "DOC_PENDING": "Pending document"}
ss = st.session_state


# ------------------------------------------------------------------ small helpers
def esc(v) -> str:
    return html.escape(k.text(v))


def chip(text_, css="") -> str:
    return f'<span class="a360-chip {css}">{esc(text_)}</span>'


def status_chip(status: str) -> str:
    label, icon, css = k.STATUS_META.get(status, k.STATUS_META[k.NEEDS_REVIEW])
    return chip(f"{icon} {label}", css)


def inr(v) -> str:
    n = k.num(v)
    return "-" if n is None else f"INR {n:,.0f}"


def inr_short(v) -> str:
    """Compact Indian notation for metric tiles (INR 4.69 L, INR 1.20 Cr)."""
    n = k.num(v)
    if n is None:
        return "-"
    if abs(n) >= 1e7:
        return f"INR {n / 1e7:.2f} Cr"
    if abs(n) >= 1e5:
        return f"INR {n / 1e5:.2f} L"
    return f"INR {n:,.0f}"


def action_label(code, fallback="") -> str:
    return ACTION_LABEL.get(code, fallback or k.text(code).replace("_", " ").capitalize())


def signal_label(code) -> str:
    return SIGNAL_LABEL.get(code, k.text(code).replace("_", " ").capitalize())


def renewal_text(h: dict) -> str:
    days = h.get("days_to_renewal")
    if days is None or days < 0:
        return "No upcoming renewal"
    return f"Renewal in {days:.0f} days"


def subtitle(text_):
    st.markdown(f'<div class="a360-sub">{esc(text_)}</div>', unsafe_allow_html=True)


def kv(key, value):
    st.markdown(f'<div class="a360-k">{esc(key)}</div><div class="a360-v">{esc(value) or "-"}</div>', unsafe_allow_html=True)


def friendly_error(message: str, exc: Exception | None = None, retry_key: str | None = None):
    """User-facing error (no stack trace); details go to the server log."""
    if exc is not None:
        log.exception("%s", message)
    st.error(message, icon=":material/error:")
    if retry_key and st.button("Retry", key=retry_key, icon=":material/refresh:"):
        st.cache_data.clear()
        st.rerun()


# ------------------------------------------------------------------ customer context (single source of truth)
def _url_customer():
    try:
        return st.query_params.get("customer")
    except Exception:  # noqa: BLE001 - query params unavailable in some hosts
        return None


state.init_state(ss, _url_customer())


def set_customer(cid, *, from_list=False):
    cid = k.normalize_customer_id(cid)
    header = d.customer_header(cid) if cid else None
    state.select_customer(ss, cid, header, from_list=from_list)


def current_customer() -> dict | None:
    """Header of the selected customer, loading it if needed. Clears an invalid selection."""
    cid = state.get_selected_customer_id(ss)
    if not cid:
        return None
    h = state.get_selected_customer(ss)
    if h is None:
        try:
            h = d.customer_header(cid)
        except Exception as e:  # noqa: BLE001
            friendly_error("Unable to load the selected customer. Check the Snowflake connection.", e, "retry_hdr")
            st.stop()
        if h is None:
            st.warning(f"Customer **{cid}** was not found. Please select another customer.", icon=":material/person_off:")
            state.clear_selection(ss)
            return None
        state.select_customer(ss, cid, h)
    return h


def _sync_url(cid):
    try:
        if cid and st.query_params.get("customer") != cid:
            st.query_params["customer"] = cid
        elif not cid and "customer" in st.query_params:
            del st.query_params["customer"]
    except Exception:  # noqa: BLE001
        pass


def require_customer() -> dict:
    h = current_customer()
    if h is None:
        with st.container(border=True):
            st.markdown("#### Select a customer to continue")
            st.markdown('<div class="a360-muted">Customer 360, Next best action, Offers and Interactions work on one '
                        'selected customer. Pick one from the dashboard worklist or a demo persona.</div>', unsafe_allow_html=True)
            c1, c2 = st.columns([1, 3])
            if c1.button("Go to dashboard", type="primary", icon=":material/dashboard:"):
                st.switch_page(PAGES["dashboard"])
            persona_picker(c2, key_prefix="empty")
        st.stop()
    return h


def persona_picker(container, key_prefix: str):
    try:
        p = d.personas()
    except Exception as e:  # noqa: BLE001
        log.exception("personas failed: %s", e)
        return
    ids = list(p.CUSTOMER_ID)
    labels = {r.CUSTOMER_ID: f"{r.CUSTOMER_ID} · {action_label(r.RECOMMENDED_ACTION)}" for r in p.itertuples()}
    cur = state.get_selected_customer_id(ss)
    key = f"{key_prefix}_pp_{cur}"

    def _pick():
        v = ss.get(key)
        if v:
            set_customer(v)

    container.pills("Demo personas", ids, format_func=lambda x: labels.get(x, x), key=key, on_change=_pick,
                    default=cur if cur in ids else None)


def context_bar(h: dict, active: str):
    """Persistent selected-customer header with contextual navigation."""
    with st.container(border=True):
        st.markdown(
            f'<div class="a360-eyebrow">Selected customer</div>'
            f'<span class="a360-name">{esc(h["name"])}</span><span class="a360-id">{esc(h["customer_id"])}</span><br>'
            + chip(h["segment"]) + chip(h["industry"].title())
            + chip(f'{h["risk_tier"].title()} risk', f'c-{h["risk_tier"]}')
            + chip(f'{h["sentiment"].title()} sentiment', f'c-{h["sentiment"]}')
            + chip(h["value_tier"]) + chip(renewal_text(h))
            + (chip(f'{h["unresolved"]} open complaint{"s" if h["unresolved"] != 1 else ""}', "c-HIGH") if h["unresolved"] else ""),
            unsafe_allow_html=True)
        # buttons on their own row so labels never wrap letter-by-letter at medium widths
        cols = st.columns([1.1, 1.3, .8, 1.1, .45, .45, 2.2])
        for col, (key, label, icon) in zip(cols, [("c360", "Customer 360", ":material/person:"),
                                                  ("nba", "Next best action", ":material/bolt:"),
                                                  ("offers", "Offers", ":material/redeem:"),
                                                  ("interactions", "Interactions", ":material/forum:")]):
            if col.button(label, icon=icon, key=f"cb_{key}", use_container_width=True,
                          type="primary" if key == active else "secondary"):
                st.switch_page(PAGES[key])
        if cols[4].button("", icon=":material/swap_horiz:", key="cb_switch", help="Switch customer (back to dashboard)",
                          use_container_width=True):
            st.switch_page(PAGES["dashboard"])
        if cols[5].button("", icon=":material/close:", key="cb_clear", help="Clear selected customer", use_container_width=True):
            state.clear_selection(ss)
            st.switch_page(PAGES["dashboard"])


# ------------------------------------------------------------------ offer components (shared by C360, NBA, Offers)
def load_offers(cid: str) -> dict | None:
    with st.spinner("Finding the best offer..."):
        try:
            c = d.get_customer_offers(cid)
        except Exception as e:  # noqa: BLE001
            friendly_error("Unable to retrieve offers for this customer.", e, f"retry_offers_{cid}")
            return None
    if not c["ok"]:
        friendly_error(f"Unable to retrieve offers for this customer ({c['error']}).", None, f"retry_offers2_{cid}")
        return None
    return c


def offer_card(offer: dict, *, dominant: bool, confidence: str | None = None, evidence: list[str] | None = None):
    f = k.format_offer_for_ui(offer)
    with st.container(border=True):
        top = st.columns([3, 1], vertical_alignment="top")
        top[0].markdown(
            ('<div class="a360-eyebrow">Recommended offer</div>' if dominant else "")
            + f'<div class="{"a360-hero" if dominant else "a360-name"}">{esc(f["title"])}</div>'
            + f'<div class="a360-muted">{esc(f["description"])}' + (f' · <b>{esc(f["value"])}</b>' if f["value"] else "") + "</div>",
            unsafe_allow_html=True)
        top[1].markdown('<div style="text-align:right">' + status_chip(f["status"]) + "</div>", unsafe_allow_html=True)
        if dominant:
            a, b, c = st.columns(3)
            with a:
                st.markdown(f'<div class="a360-k">{esc(f["why_title"])}</div>', unsafe_allow_html=True)
                for r in f["rules"] or [f["reason"]]:
                    mark = "✓" if f["status"] == k.ELIGIBLE else "✕"
                    st.markdown(f'<div class="a360-rule">{mark} {esc(r)}</div>', unsafe_allow_html=True)
            with b:
                kv("Business purpose", f["purpose"])
                if f["outcome"]:
                    kv("Expected outcome", f["outcome"])
            with c:
                if confidence:
                    kv("Confidence", confidence.title())
                kv("Offer ID · priority", f'{f["offer_id"]} · {f["priority"]}')
                if evidence:
                    kv("Supporting evidence", "; ".join(evidence[:2]))
        else:
            st.markdown(f'<div class="a360-rule">{esc(f["reason"])}</div>', unsafe_allow_html=True)


def no_offer_card(contract: dict):
    with st.container(border=True):
        st.markdown('<div class="a360-eyebrow">Recommended offer</div>'
                    f'<div class="a360-name">{esc(k.headline_for_no_offer(contract))}</div>'
                    f'<div class="a360-v" style="margin-top:.3rem">{esc(contract["offer_status_reason"])}</div>',
                    unsafe_allow_html=True)
        if contract["alternatives"]:
            st.markdown(f'<div class="a360-muted" style="margin-top:.4rem">{len(contract["alternatives"])} other offer(s) pass '
                        'their eligibility rules but are not attached to this action.</div>', unsafe_allow_html=True)


def offer_section(contract: dict, *, confidence=None, evidence=None, max_alternatives=3, show_ineligible=True):
    if contract["offer"]:
        offer_card(contract["offer"], dominant=True, confidence=confidence, evidence=evidence)
    else:
        no_offer_card(contract)
    alts = contract["alternatives"]
    if alts:
        st.markdown('<div class="a360-eyebrow" style="margin-top:.6rem">'
                    + ("Other eligible options" if contract["offer"] else "Eligible offers (not attached to this action)")
                    + "</div>", unsafe_allow_html=True)
        cols = st.columns(min(len(alts), max_alternatives))
        for col, o in zip(cols, alts[:max_alternatives]):
            with col:
                offer_card(o, dominant=False)
        if len(alts) > max_alternatives:
            st.caption(f"+{len(alts) - max_alternatives} more on the Offers page.")
    if show_ineligible and contract["not_eligible"]:
        with st.expander(f"Not eligible ({len(contract['not_eligible'])})"):
            for o in contract["not_eligible"]:
                st.markdown(status_chip(o["eligibility_status"]) + f' <b>{esc(o["offer_name"])}</b> · {esc(o["reason"])}',
                            unsafe_allow_html=True)


# ================================================================== DASHBOARD
def page_dashboard():
    st.title("Portfolio dashboard")
    subtitle("Find the customers that need action today, then open their 360 view or next best action.")
    try:
        kp = d.kpis()
    except Exception as e:  # noqa: BLE001
        friendly_error("Unable to load portfolio metrics from Snowflake.", e, "retry_kpis")
        return
    c = st.columns(6)
    c[0].metric("Customers", f"{kp['TOTAL']:,}")
    c[1].metric("High risk", f"{kp['HIGH']:,}", f"{kp['HIGH'] / kp['TOTAL']:.0%} of book", delta_color="off")
    c[2].metric("Negative sentiment", f"{kp['NEG']:,}")
    c[3].metric("Need action", f"{kp['NEEDS_ACTION']:,}")
    c[4].metric("Recommendations", f"{kp['GENERATED']:,}")
    c[5].metric("Approved actions", f"{kp['COMPLETED']:,}")

    with st.container(border=True):
        st.markdown("**Find a customer**")
        s1, s2 = st.columns([1, 2.2])
        nonce = ss[state.NONCE]
        term = s1.text_input("Customer ID or name", key=f"find_{nonce}", placeholder="e.g. C10238 or Kumar",
                             label_visibility="collapsed")
        persona_picker(s2, key_prefix="dash")
        if k.text(term):
            res = d.find_customers(term)
            if res.empty:
                st.caption(f"No customer matches '{term}'.")
            rc = st.columns(4)
            for i, r in enumerate(res.itertuples()):
                if rc[i % 4].button(f"{r.CUSTOMER_ID} · {r.FULL_NAME}", key=f"fr_{nonce}_{r.CUSTOMER_ID}",
                                    help=f"{r.SEGMENT} · {r.RISK_TIER} risk", use_container_width=True):
                    set_customer(r.CUSTOMER_ID)
                    st.rerun()

    st.subheader("Action worklist")
    f1, f2, _ = st.columns([1, 1.5, 2])
    tier = f1.selectbox("Risk tier", ["ALL", "HIGH", "MEDIUM", "LOW"], index=1)
    action = f2.selectbox("Recommended action", ["ALL"] + [a for a in ACTION_LABEL if a != "NO_ACTION_MONITOR"],
                          format_func=lambda a: "All actions" if a == "ALL" else action_label(a))
    try:
        wl = d.worklist(tier, action)
    except Exception as e:  # noqa: BLE001
        friendly_error("Unable to load the worklist.", e, "retry_wl")
        return
    ids = list(wl.CUSTOMER_ID)
    view = wl.assign(RECOMMENDED_ACTION=wl.RECOMMENDED_ACTION.map(action_label))
    key = f"wl_{tier}_{action}_{ss[state.NONCE]}"

    def _on_select():
        rows = ss[key]["selection"]["rows"]
        if rows:
            set_customer(ids[rows[0]], from_list=True)

    st.caption("Select a row to set the customer context. Ranked by risk x value.")
    st.dataframe(view, hide_index=True, use_container_width=True, on_select=_on_select, selection_mode="single-row", key=key,
                 height=360,
                 column_config={"CUSTOMER_ID": "Customer", "FULL_NAME": "Name", "SEGMENT": "Segment", "INDUSTRY_TYPE": "Line",
                                "RISK_TIER": "Risk tier", "PRIMARY_RISK_TYPE": "Primary risk",
                                "RISK": st.column_config.ProgressColumn("Risk", min_value=0, max_value=1, format="%.2f"),
                                "SENTIMENT": "Sentiment", "DAYS_TO_RENEWAL": "Renewal (days)", "UNRESOLVED": "Open complaints",
                                "RECOMMENDED_ACTION": "Recommended action", "OFFER": "Offer", "AI_ROUTE": "AI route",
                                "VALUE_INR": st.column_config.NumberColumn("Value (INR)", format="%d")})

    left, right = st.columns([1.1, 1])
    with left, st.container(border=True):
        st.markdown("**Risk tier by segment**")
        df = d.risk_by_segment()
        st.altair_chart(alt.Chart(df).mark_bar().encode(
            x=alt.X("SEGMENT:N", title=None), y=alt.Y("CUSTOMERS:Q", title="Customers"),
            color=alt.Color("RISK_TIER:N", scale=alt.Scale(domain=["HIGH", "MEDIUM", "LOW"], range=["#c5372c", "#e0a030", "#3b8f57"]),
                            title="Risk tier"), tooltip=["SEGMENT", "RISK_TIER", "CUSTOMERS"]).properties(height=250),
            use_container_width=True)
    with right, st.container(border=True):
        st.markdown("**Recommended action mix**")
        df = d.action_mix()
        df["ACTION"] = df["ACTION"].map(action_label)
        st.altair_chart(alt.Chart(df).mark_bar(color="#0b5cad").encode(
            y=alt.Y("ACTION:N", sort="-x", title=None), x=alt.X("CUSTOMERS:Q", title="Customers"),
            tooltip=["ACTION", "CUSTOMERS"]).properties(height=250), use_container_width=True)
    with st.container(border=True):
        st.markdown("**Cost-aware AI routing** · LLM enrichment only where it changes the decision")
        r = st.columns(4)
        r[0].metric("Rules only (no LLM)", f"{kp['R_RULES']:,}")
        r[1].metric("Selective AI", f"{kp['R_SEL']:,}")
        r[2].metric("Full agent", f"{kp['R_FULL']:,}")
        r[3].metric("LLM calls avoided", f"{kp['R_RULES'] + kp['R_SEL']:,}",
                    f"{(kp['R_RULES'] + kp['R_SEL']) / kp['TOTAL']:.0%} of customers", delta_color="off")


# ================================================================== CUSTOMER 360
def page_customer():
    h = require_customer()
    cid = h["customer_id"]
    st.title("Customer 360")
    subtitle("Who the customer is, what is going wrong and what to do next.")
    with st.spinner("Loading customer..."):
        try:
            c = d.customer_360(cid)
        except Exception as e:  # noqa: BLE001
            friendly_error("Unable to load the Customer 360 profile.", e, "retry_c360")
            return
    if not isinstance(c, dict) or not c.get("found", True) or "identity" not in c:
        st.warning(f"Customer **{cid}** was not found.")
        return
    idn, fin, inter, risk, ai = c["identity"], c["financial"], c["interactions"], c["risk"], c["ai_interpretation"]

    m = st.columns(5)
    m[0].metric("Customer value", inr_short(fin.get("annual_value_inr")), f"{h['value_tier']} (p{(fin.get('value_percentile') or 0) * 100:.0f})",
                delta_color="off")
    m[1].metric("Risk", f"{risk['risk_tier'].title()}", f"primary: {k.text(risk.get('primary_risk_type')).lower() or '-'}",
                delta_color="off")
    m[2].metric("Sentiment (90d)", k.text(inter.get("sentiment")).title() or "-")
    days = fin.get("days_to_renewal")
    m[3].metric("Renewal", str(fin.get("next_renewal_date") or "-"),
                f"in {days} days" if days is not None and days >= 0 else "none upcoming", delta_color="off")
    m[4].metric("Open issues", inter.get("unresolved_complaints", 0), f"{inter.get('complaints_90d', 0)} complaints in 90d",
                delta_color="off")

    a, b = st.columns([1.25, 1])
    with a, st.container(border=True):
        st.markdown("**Account & product summary**")
        s = st.columns(4)
        s[0].metric("Outstanding", inr_short(fin.get("total_outstanding_inr")))
        s[1].metric("Payment status", k.text(fin.get("payment_status")).replace("_", " ").title() or "-")
        s[2].metric("Credit score", fin.get("credit_score") or "-")
        s[3].metric("Tenure", f"{idn.get('tenure_months')} mo")
        try:
            st.dataframe(d.accounts(cid), hide_index=True, use_container_width=True, height=180)
        except Exception as e:  # noqa: BLE001
            friendly_error("Unable to load accounts.", e)
        for e in c.get("open_events") or []:
            st.markdown(f'<div class="a360-rule">● <b>{esc(e.get("event"))}</b> ({esc(e.get("date"))}): {esc(e.get("details"))}</div>',
                        unsafe_allow_html=True)
    with b, st.container(border=True):
        st.markdown("**Key drivers**")
        rd = pd.DataFrame({"Risk": ["Churn", "Payment", "Service"],
                           "Score": [risk.get("churn_risk") or 0, risk.get("payment_risk") or 0, risk.get("service_risk") or 0]})
        st.altair_chart(alt.Chart(rd).mark_bar(cornerRadiusEnd=3).encode(
            x=alt.X("Score:Q", scale=alt.Scale(domain=[0, 1]), title=None), y=alt.Y("Risk:N", title=None),
            color=alt.condition(alt.datum.Score >= 0.6, alt.value("#c5372c"), alt.value("#0b5cad"))).properties(height=110),
            use_container_width=True)
        drivers = risk.get("top_drivers") or []
        for i, drv in enumerate(drivers, 1):
            st.markdown(f'<div class="a360-rule">{i}. <b>{esc(drv.get("label"))}</b> '
                        f'<span class="a360-muted">({esc(k.text(drv.get("model")).lower())} model, +{k.num(drv.get("contribution")) or 0:.2f})</span></div>',
                        unsafe_allow_html=True)
        if not drivers:
            st.caption("No material risk drivers.")

    a, b = st.columns([1.25, 1])
    with a, st.container(border=True):
        hdr = st.columns([3, 1])
        hdr[0].markdown("**Recent interactions**")
        if hdr[1].button("All interactions", key="c360_tl", use_container_width=True):
            st.switch_page(PAGES["interactions"])
        try:
            tl = d.timeline(cid)
            tl = tl[tl.KIND == "INTERACTION"][["TS", "TITLE", "STATUS", "DETAIL"]].head(6)
            if tl.empty:
                st.caption("No interactions recorded.")
            else:
                st.dataframe(tl, hide_index=True, use_container_width=True,
                             column_config={"TS": st.column_config.DatetimeColumn("When", format="DD MMM YYYY"),
                                            "TITLE": "Channel · topic", "STATUS": "Status", "DETAIL": "Note"})
        except Exception as e:  # noqa: BLE001
            friendly_error("Unable to load interactions.", e)
    with b, st.container(border=True):
        st.markdown("**AI summary** " + chip("AI interpretation", "s-ai"), unsafe_allow_html=True)
        if ai.get("customer_need"):
            st.write(ai["customer_need"])
            for p in ai.get("pain_points") or []:
                st.markdown(f'<div class="a360-rule">● {esc(p)}</div>', unsafe_allow_html=True)
            st.caption(f"claude-haiku-4-5 · generated {ai.get('generated_at')}")
        elif risk.get("ai_route") == "RULES_ONLY":
            st.caption("LLM summary skipped by cost-aware routing (low risk). Structured facts are sufficient.")
        else:
            if st.button("Generate AI summary", icon=":material/auto_awesome:"):
                with st.spinner("Summarising with claude-haiku-4-5..."):
                    try:
                        d.call(f"{d.DB}.CORE.GENERATE_CUSTOMER_INSIGHTS", 1, cid)
                        d.customer_360.clear()
                    except Exception as e:  # noqa: BLE001
                        friendly_error("AI summary is unavailable right now. The deterministic profile above is unaffected.", e)
                        return
                st.rerun()

    # NBA preview: same governed offer contract as the NBA and Offers pages
    st.markdown('<div class="a360-eyebrow" style="margin-top:.8rem">Next best action preview</div>', unsafe_allow_html=True)
    contract = load_offers(cid)
    if contract:
        with st.container(border=True):
            p1, p2 = st.columns([2.2, 1], vertical_alignment="center")
            p1.markdown(f'<div class="a360-name">{esc(action_label(contract["recommended_action"], contract["action_name"]))}</div>'
                        f'<div class="a360-muted">{esc(contract["business_purpose"])}</div>', unsafe_allow_html=True)
            if p2.button("View full next best action", type="primary", icon=":material/bolt:", use_container_width=True):
                st.switch_page(PAGES["nba"])
            if contract["offer"]:
                f = k.format_offer_for_ui(contract["offer"])
                st.markdown("Offer: <b>" + esc(f["title"]) + "</b> " + status_chip(f["status"])
                            + f' <span class="a360-muted">· {esc(f["purpose"])}</span>', unsafe_allow_html=True)
            else:
                st.markdown(f"<b>{esc(k.headline_for_no_offer(contract))}</b> "
                            f'<span class="a360-muted">· {esc(contract["offer_status_reason"])}</span>', unsafe_allow_html=True)
    with st.expander("All signals"):
        st.dataframe(d.signals(cid), hide_index=True, use_container_width=True,
                     column_config={"VALUE": st.column_config.ProgressColumn(min_value=0, max_value=1, format="%.2f")})


# ================================================================== NEXT BEST ACTION
def _run_nba(cid: str):
    with st.spinner("Scoring actions, checking eligibility and retrieving evidence..."):
        try:
            n = d.next_best_action(cid, "Why should I contact this customer today and what should I offer?")
        except Exception as e:  # noqa: BLE001
            log.exception("NBA failed for %s: %s", cid, e)
            state.set_scoped(ss, "nba_error", {"message": "The decision engine could not be reached. Please retry."})
            return
    if n.get("ok"):
        state.set_scoped(ss, "nba", n)
        state.set_scoped(ss, "nba_error", None)
        state.set_scoped(ss, "outreach", None)
    else:
        state.set_scoped(ss, "nba_error", {"message": f"No recommendation could be produced: {n.get('error')}"})


def page_nba():
    h = require_customer()
    cid = h["customer_id"]
    st.title("Next best action")
    if state.get_scoped(ss, "nba") is None and state.get_scoped(ss, "nba_error") is None:
        _run_nba(cid)
    err = state.get_scoped(ss, "nba_error")
    if err:
        st.error(err["message"], icon=":material/error:")
        if st.button("Retry", icon=":material/refresh:", type="primary"):
            state.set_scoped(ss, "nba_error", None)
            st.rerun()
        return
    n = state.get_scoped(ss, "nba")
    contract = load_offers(cid)
    if contract is None:
        return
    if contract["offer"] and n["offer_id"] and n["offer_id"] != contract["offer"]["offer_id"]:
        st.warning("The recommendation changed since it was calculated. Recalculate to refresh.", icon=":material/sync_problem:")

    # 1. action - immediately visible, with the actions next to it
    with st.container(border=True):
        left, right = st.columns([2.3, 1], vertical_alignment="top")
        with left:
            st.markdown('<div class="a360-eyebrow">Recommended action</div>'
                        f'<div class="a360-hero">{esc(action_label(n["selected_action"], n["action_name"]))}</div>'
                        f'<div class="a360-muted">{esc(n["business_purpose"])}</div>'
                        + chip(f'Confidence: {n["confidence"].title()}',
                               {"HIGH": "s-ok", "MEDIUM": "s-warn", "LOW": "s-bad"}.get(n["confidence"], "s-muted"))
                        + chip(f'Score {n["action_score"]:.2f}' if n["action_score"] is not None else "Score -")
                        + chip("Deterministic decision", "s-info") + chip(f'AI route: {n["ai_route"]}', "s-ai"),
                        unsafe_allow_html=True)
        with right:
            channel = st.selectbox("Outreach channel", ["", "CALL", "EMAIL", "WHATSAPP", "APP"],
                                   format_func=lambda x: x.title() if x else "Preferred channel", key=f"ch_{cid}")
            if st.button("Generate outreach", icon=":material/edit_note:", type="primary", use_container_width=True):
                with st.spinner("Personalising with claude-sonnet-4-6 (decision is locked)..."):
                    try:
                        state.set_scoped(ss, "outreach", d.outreach(n["recommendation_id"], channel))
                        state.set_scoped(ss, "outreach_error", None)
                    except Exception as e:  # noqa: BLE001
                        log.exception("outreach failed: %s", e)
                        state.set_scoped(ss, "outreach_error", {"message": "Outreach generation is unavailable right now. "
                                                                          "The recommendation is unaffected - retry shortly."})
            approve_popover(n, contract)
            show_ev = st.toggle("View evidence", value=False, key=f"ev_{cid}")

    res = state.get_scoped(ss, "last_log_result")
    if res:
        (st.success if res.get("logged") else st.error)(res["message"])

    # 2/3. why this action, why now
    w1, w2 = st.columns(2)
    with w1, st.container(border=True):
        st.markdown("**Why this action**")
        total = sum(r["contribution"] for r in n["reasons"]) or 1
        for r in n["reasons"]:
            st.markdown(f'<div class="a360-rule"><b>{esc(signal_label(r["signal"]))}</b> '
                        f'<span class="a360-muted">signal {r["value"]:.2f} × weight {r["weight"]:+.2f} = {r["contribution"]:+.3f}</span></div>',
                        unsafe_allow_html=True)
        if not n["reasons"]:
            st.caption("Base score only (no contributing signals).")
        st.caption(n["provenance"])
    with w2, st.container(border=True):
        st.markdown("**Why now**")
        for f in n["facts"]:
            st.markdown(f'<div class="a360-rule">● {esc(f)}</div>', unsafe_allow_html=True)

    # 4-7. eligibility + offer + evidence + confidence
    ev_refs = [f'{x.get("DOC_ID")} ({x.get("INTERACTION_DATE")})' for x in n["interaction_evidence"] if x.get("DOC_ID")]
    offer_section(contract, confidence=n["confidence"], evidence=ev_refs)

    # 8. outreach
    oerr = state.get_scoped(ss, "outreach_error")
    if oerr:
        st.error(oerr["message"], icon=":material/error:")
    o = state.get_scoped(ss, "outreach")
    if o:
        with st.container(border=True):
            st.markdown("**Suggested outreach** " + chip("AI-generated personalisation", "s-ai") + chip(o.get("model", "no LLM")),
                        unsafe_allow_html=True)
            if not o.get("llm_used"):
                st.info("LLM skipped - stable customer, no outreach needed (cost saved).")
            o1, o2 = st.columns([1.3, 1])
            with o1:
                st.text_area("message", o.get("customer_message") or "-", height=240, label_visibility="collapsed")
            with o2:
                kv("Why relevant", o.get("why_relevant"))
                kv("Why now", o.get("why_now"))
                st.markdown('<div class="a360-k">RM talking points</div>', unsafe_allow_html=True)
                for tp in o.get("rm_talking_points") or []:
                    st.markdown(f'<div class="a360-rule">● {esc(tp)}</div>', unsafe_allow_html=True)
                if o.get("evidence_gaps"):
                    st.warning(f"Evidence gaps: {o['evidence_gaps']}")
            if o.get("guardrail_violation"):
                st.error("Post-generation guardrail withheld a message that referenced an ineligible offer.")

    if show_ev:
        e1, e2 = st.columns(2)
        with e1, st.container(border=True):
            st.markdown("**Interaction evidence** " + chip("Cortex Search · this customer only", "s-info"), unsafe_allow_html=True)
            if not n["interaction_evidence"]:
                st.caption("No interaction evidence retrieved.")
            for x in n["interaction_evidence"]:
                st.markdown(f"**{x.get('DOC_ID')}** · {x.get('INTERACTION_DATE')} · {x.get('CHANNEL', '')} · {x.get('SOURCE_TYPE', '')}")
                st.caption((x.get("CONTENT") or "")[:600])
        with e2, st.container(border=True):
            st.markdown("**Policy / offer evidence** " + chip("Cortex Search", "s-info"), unsafe_allow_html=True)
            if not n["policy_evidence"]:
                st.caption("Not retrieved (rules-only route) or unavailable.")
            for x in n["policy_evidence"]:
                st.markdown(f"**{x.get('TITLE')}** - {x.get('SECTION')}")
                st.caption((x.get("CHUNK_TEXT") or "")[:600])

    with st.expander("All candidate actions (scored, gated, ranked)"):
        st.dataframe(d.candidates(cid).drop(columns=["TOP_CONTRIBUTIONS"]), hide_index=True, use_container_width=True)
    if st.button("Recalculate", icon=":material/refresh:"):
        state.clear_customer_scoped(ss)
        d.candidates.clear()
        d._offer_contract_raw.clear()
        st.rerun()


def approve_popover(n: dict, contract: dict):
    with st.popover("Approve & log action", icon=":material/task_alt:", use_container_width=True):
        st.caption("Writes an immutable, hash-chained ACTION_AUDIT record. Downstream execution is SIMULATED.")
        ua = st.radio("Decision", ["APPROVED", "DEFERRED", "REJECTED"], horizontal=True, key=f"ua_{n['recommendation_id']}")
        rec_id = contract["offer"]["offer_id"] if contract["offer"] else ""
        opts = [""] + [o["offer_id"] for o in contract["candidate_offers"] if o["offer_id"] != rec_id]
        names = {o["offer_id"]: f'{o["offer_name"]} ({k.STATUS_META[o["eligibility_status"]][0].lower()})'
                 for o in contract["candidate_offers"]}
        req = st.selectbox("Offer", opts, key=f"req_{n['recommendation_id']}",
                           format_func=lambda x: f"Keep recommended ({names.get(rec_id, 'no offer')})" if not x else names.get(x, x),
                           help="Choosing a different offer re-checks eligibility at write time; ineligible offers are blocked.")
        note = st.text_input("Note", key=f"note_{n['recommendation_id']}")
        if st.button("Confirm", type="primary", key=f"conf_{n['recommendation_id']}"):
            try:
                res = d.log_action(n["recommendation_id"], ua, req, note)
            except Exception as e:  # noqa: BLE001
                log.exception("log_action failed: %s", e)
                state.set_scoped(ss, "last_log_result", {"logged": False, "message": "Unable to log the action. Please retry."})
                st.rerun()
            d.audit.clear()
            if res.get("logged"):
                msg = f"Logged {res.get('user_action')} · {res.get('downstream_status')}"
            else:
                msg = (f"Blocked: {res.get('downstream_status') or res.get('error')} "
                       + "; ".join(r for r in (res.get("failed_rules") or []) if r))
            state.set_scoped(ss, "last_log_result", {"logged": bool(res.get("logged")), "message": msg})
            st.rerun()


# ================================================================== OFFERS
def page_offers():
    h = require_customer()
    cid = h["customer_id"]
    st.title("Offers")
    subtitle("Every catalogue offer for this customer's line of business, checked against hard eligibility rules.")
    contract = load_offers(cid)
    if contract is None:
        return
    offer_section(contract, max_alternatives=3, show_ineligible=False)
    st.markdown('<div class="a360-eyebrow" style="margin-top:1rem">All offers</div>', unsafe_allow_html=True)
    rows = [{"Status": k.format_offer_for_ui(o)["status_text"], "Offer": o["offer_name"], "Offer ID": o["offer_id"],
             "Purpose": o["business_purpose"], "Priority": o["priority"], "Recommended": "Yes" if o["is_recommended"] else "",
             "Reason": o["reason"]} for o in contract["candidate_offers"]]
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True,
                     column_config={"Priority": st.column_config.NumberColumn(format="%d"), "Reason": st.column_config.TextColumn(width="large")})
    else:
        st.info("No offers exist in the catalogue for this customer's line of business.")
    with st.container(border=True):
        st.markdown("**Live eligibility check**")
        c1, c2 = st.columns([2, 1], vertical_alignment="bottom")
        oid = c1.selectbox("Offer", [o["offer_id"] for o in contract["candidate_offers"]], key=f"chk_{cid}",
                           format_func=lambda x: next((o["offer_name"] for o in contract["candidate_offers"] if o["offer_id"] == x), x))
        if c2.button("Check now", use_container_width=True) and oid:
            try:
                r = d.check_offer_eligibility(cid, oid)
                st.markdown(status_chip(r["status"]) + f' {esc(r["reason"])}', unsafe_allow_html=True)
            except Exception as e:  # noqa: BLE001
                friendly_error("Unable to check eligibility right now.", e)


# ================================================================== INTERACTIONS
@st.dialog("Call transcript", width="large")
def show_transcript(ref):
    t = d.transcript(ref)
    if t.empty:
        st.info("No transcript for this interaction (note only).")
        return
    r = t.iloc[0]
    st.markdown(chip(r.SOURCE_TYPE, "s-info") + chip(f"AI sentiment {r.AI_SENTIMENT_SCORE}", "s-ai")
                + chip(f"intent {r.AI_INTENT}", "s-ai"), unsafe_allow_html=True)
    st.caption(f"{r.SOURCE_FILE} · {r.CALL_TS} · {r.DURATION_SEC}s")
    for line in (r.TRANSCRIPT_TEXT or "").splitlines():
        who, _, said = line.partition(":")
        st.chat_message("user" if who.strip() == "CUSTOMER" else "assistant").write(said.strip() or line)


def page_interactions():
    h = require_customer()
    cid = h["customer_id"]
    st.title("Interactions")
    subtitle("Calls, notes, payments, account events and renewals. Select an interaction to read its transcript.")
    try:
        tl = d.timeline(cid)
    except Exception as e:  # noqa: BLE001
        friendly_error("Unable to load the interaction timeline.", e, "retry_tl")
        return
    if tl.empty:
        st.info("No interactions or events recorded for this customer.")
        return
    kinds = st.multiselect("Show", sorted(tl.KIND.unique()), default=sorted(tl.KIND.unique()))
    tl = tl[tl.KIND.isin(kinds)].reset_index(drop=True)
    st.altair_chart(alt.Chart(tl).mark_circle(size=120).encode(
        x=alt.X("TS:T", title=None), y=alt.Y("KIND:N", title=None),
        color=alt.Color("STATUS:N"), tooltip=["TS", "KIND", "TITLE", "STATUS", "DETAIL"]).properties(height=200),
        use_container_width=True)
    ev = st.dataframe(tl[["TS", "KIND", "TITLE", "STATUS", "DETAIL", "REF", "HAS_TRANSCRIPT"]], hide_index=True,
                      use_container_width=True, on_select="rerun", selection_mode="single-row", key=f"tl_{cid}",
                      column_config={"TS": st.column_config.DatetimeColumn("When", format="DD MMM YYYY"),
                                     "HAS_TRANSCRIPT": st.column_config.CheckboxColumn("Transcript")})
    if ev.selection.rows:
        row = tl.iloc[ev.selection.rows[0]]
        if row.KIND == "INTERACTION":
            show_transcript(row.REF)


# ================================================================== ASK ACTION360
def page_ask():
    st.title("Ask ACTION360")
    subtitle("Cortex Agent: Cortex Analyst (semantic view) + 2 Cortex Search services + governed decision tools. "
             "Decisions come from rules; the LLM explains.")
    cid = state.get_selected_customer_id(ss) or "C10238"
    samples = [f"Why is {cid} high risk?", f"What did {cid} say in their last call?",
               f"What are the main reasons {cid} may leave?", f"What offer is {cid} eligible for?",
               f"What should the relationship manager do next for {cid}?", "Which customers have negative sentiment and an upcoming renewal?"]
    ss.setdefault("chat", [])
    cols = st.columns(3)
    clicked = None
    for i, s in enumerate(samples):
        if cols[i % 3].button(s, key=f"s{i}", use_container_width=True):
            clicked = s
    for m in ss.chat:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])
            if m.get("tools"):
                st.caption("Tools: " + " → ".join(m["tools"]) + f" · {m.get('latency')}s")
    prompt = st.chat_input("Ask about a customer or the portfolio...") or clicked
    if prompt:
        ss.chat.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)
        with st.chat_message("assistant"):
            with st.status("Agent orchestrating tools...", expanded=False) as status:
                history = [{"role": m["role"], "content": m["content"]} for m in ss.chat[-6:]]
                try:
                    r = d.ask_agent(history)
                    status.update(label=f"Done in {r['latency_s']}s · tools: {', '.join(r['tools']) or 'none'}", state="complete")
                except Exception as e:  # noqa: BLE001
                    log.exception("agent failed: %s", e)
                    r = {"text": "The Cortex Agent is unavailable right now. The **Next best action** page works without "
                                 "the agent (deterministic engine).", "tools": [], "latency_s": 0}
                    status.update(label="Agent unavailable", state="error")
            st.markdown(r["text"] or "_No answer returned._")
            if r.get("warnings"):
                st.warning(r["warnings"])
        ss.chat.append({"role": "assistant", "content": r["text"], "tools": r["tools"], "latency": r["latency_s"]})
    if ss.chat and st.button("Clear conversation", icon=":material/delete:"):
        ss.chat = []
        st.rerun()


# ================================================================== KNOWLEDGE
def page_knowledge():
    st.title("Knowledge & evidence")
    subtitle("Product, policy, offer and underwriting guidance via Cortex Search.")
    h = current_customer()
    industry = h["industry"] if h else "LENDING"
    qtext = st.text_input("Search knowledge", "When can we offer a retention discount if the customer has an open complaint?")
    ind = st.segmented_control("Line of business", ["LENDING", "INSURANCE"], default=industry)
    if qtext:
        with st.spinner("Searching knowledge..."):
            try:
                hits = d.knowledge(qtext, ind or industry)
            except Exception as e:  # noqa: BLE001
                friendly_error("Knowledge search is unavailable right now.", e, "retry_kb")
                return
        if not hits:
            st.info("No matching guidance found.")
        for x in hits:
            with st.container(border=True):
                st.markdown(f"**{esc(x.get('TITLE'))}** · {esc(x.get('SECTION'))} " + chip(x.get("DOC_TYPE", ""), "s-info"),
                            unsafe_allow_html=True)
                st.write(x.get("CHUNK_TEXT"))
                st.caption(f"Source: {x.get('CHUNK_ID')}")


# ================================================================== AUDIT
def page_audit():
    st.title("Actions & audit")
    st.markdown(chip("Simulated downstream execution", "s-warn") + chip("Append-only, hash-chained", "s-info"), unsafe_allow_html=True)
    try:
        a = d.audit()
    except Exception as e:  # noqa: BLE001
        friendly_error("Unable to load the audit trail.", e, "retry_audit")
        return
    cid = state.get_selected_customer_id(ss)
    if cid and st.toggle(f"Only {cid}", value=False):
        a = a[a.CUSTOMER_ID == cid]
    c = st.columns(4)
    c[0].metric("Records", len(a))
    c[1].metric("Approved", int((a.USER_ACTION == "APPROVED").sum()) if len(a) else 0)
    c[2].metric("Blocked (ineligible offer)", int((a.USER_ACTION == "BLOCKED_INELIGIBLE_OFFER").sum()) if len(a) else 0)
    c[3].metric("Customers actioned", a.CUSTOMER_ID.nunique() if len(a) else 0)
    st.dataframe(a, hide_index=True, use_container_width=True)


# ================================================================== AI & COST
def page_cost():
    st.title("AI & cost")
    kp = d.kpis()
    u = d.ai_usage()
    used = u[~u.SKIPPED]
    skipped = u[u.SKIPPED]
    cfg = d.config().set_index("CONFIG_KEY")["CONFIG_VALUE"]
    m = st.columns(5)
    m[0].metric("Cortex AI calls", f"{int(used.CALLS.sum()):,}")
    m[1].metric("AI calls avoided by routing", f"{int(skipped.CALLS.sum()):,}")
    m[2].metric("Agent calls", f"{int(u[u.COMPONENT == 'CORTEX_AGENT'].CALLS.sum()):,}")
    m[3].metric("Est. tokens processed", f"{int(used.EST_TOKENS.sum()):,}")
    m[4].metric("Customers LLM-summarised", f"{kp['ENRICHED']:,}", f"of {kp['R_FULL']:,} full-agent", delta_color="off")
    st.caption(f"Routing thresholds: FULL ≥ {cfg.get('LLM_ENRICHMENT_THRESHOLD')} · SELECTIVE ≥ {cfg.get('SELECTIVE_ENRICHMENT_THRESHOLD')} "
               f"· models: {cfg.get('LIGHT_MODEL')} (summaries), {cfg.get('PERSONALIZATION_MODEL')} (outreach/agent)")
    st.dataframe(u, hide_index=True, use_container_width=True)
    lat = u[u.AVG_LATENCY_MS.notna()][["COMPONENT", "AVG_LATENCY_MS"]]
    if len(lat):
        st.altair_chart(alt.Chart(lat).mark_bar(color="#6a2fa6").encode(
            y=alt.Y("COMPONENT:N", sort="-x", title=None), x=alt.X("AVG_LATENCY_MS:Q", title="Avg latency (ms)")).properties(height=200),
            use_container_width=True)
    st.subheader("Metered credits (ACCOUNT_USAGE, lags up to ~3h)")
    au = d.account_usage()
    if "error" in au:
        st.info("ACCOUNT_USAGE is not accessible for this role.")
    else:
        c1, c2 = st.columns(2)
        c1.markdown("**ACTION360_WH credits / day**")
        c1.bar_chart(au["warehouse"], x="DAY", y="CREDITS")
        c2.markdown("**Credits by service (account, 14d)**")
        c2.dataframe(au["services"], hide_index=True, use_container_width=True)
        st.caption(f"Total metered (14d): {au['services'].CREDITS.sum():.2f} credits · warehouse XS, auto-suspend 60s, resource monitor 60 credits.")


# ================================================================== EVALUATION
def page_eval():
    st.title("Evaluation")
    ev = d.evaluation()
    if ev.empty:
        st.info("No evaluation results yet. Run `python tests/run_evaluation.py`.")
        return
    c = st.columns(6)
    pct = lambda col: f"{ev[col].mean():.0%}" if col in ev and ev[col].notna().any() else "-"  # noqa: E731
    c[0].metric("Action correctness", pct("ACTION_CORRECT"))
    c[1].metric("Correct eligibility", pct("ELIGIBILITY_CORRECT"))
    c[2].metric("Recommendation consistency", pct("CONSISTENT"))
    c[3].metric("Citation coverage", pct("CITATION_COVERED"))
    c[4].metric("Grounding", pct("GROUNDED"))
    c[5].metric("Avg response (s)", f"{ev['LATENCY_S'].mean():.1f}" if "LATENCY_S" in ev else "-")
    st.dataframe(ev, hide_index=True, use_container_width=True)


# ================================================================== navigation
PAGES = {
    "dashboard": st.Page(page_dashboard, title="Dashboard", icon=":material/dashboard:", url_path="dashboard", default=True),
    "c360": st.Page(page_customer, title="Customer 360", icon=":material/person:", url_path="customer-360"),
    "nba": st.Page(page_nba, title="Next best action", icon=":material/bolt:", url_path="next-best-action"),
    "interactions": st.Page(page_interactions, title="Interactions", icon=":material/forum:", url_path="interactions"),
    "offers": st.Page(page_offers, title="Offers", icon=":material/redeem:", url_path="offers"),
    "audit": st.Page(page_audit, title="Actions & audit", icon=":material/fact_check:", url_path="audit"),
    "cost": st.Page(page_cost, title="AI & cost", icon=":material/monitoring:", url_path="ai-cost"),
    "ask": st.Page(page_ask, title="Ask ACTION360", icon=":material/chat:", url_path="ask"),
    "knowledge": st.Page(page_knowledge, title="Knowledge", icon=":material/menu_book:", url_path="knowledge"),
    "eval": st.Page(page_eval, title="Evaluation", icon=":material/science:", url_path="evaluation"),
}
CUSTOMER_PAGES = ("c360", "nba", "interactions", "offers")

pg = st.navigation({
    "Workspace": [PAGES["dashboard"]],
    "Customer": [PAGES[p] for p in CUSTOMER_PAGES],
    "Operations": [PAGES["audit"], PAGES["cost"]],
    "Copilot": [PAGES["ask"], PAGES["knowledge"], PAGES["eval"]],
})
active = next((key for key, p in PAGES.items() if p.url_path == pg.url_path), "dashboard")

hdr = current_customer()
_sync_url(state.get_selected_customer_id(ss))
with st.sidebar:
    st.markdown("### :material/hub: ACTION360")
    st.caption("Customer 360 & Next Best Action")
    if hdr:
        st.markdown(f"**{hdr['name']}**  \n{hdr['customer_id']} · {hdr['risk_tier'].title()} risk")
    else:
        st.caption("No customer selected")
    st.caption("Synthetic, de-identified data. Actions are SIMULATED.")
if hdr:
    context_bar(hdr, active)
pg.run()
