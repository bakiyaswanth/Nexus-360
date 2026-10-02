"""ACTION360 - Customer 360 & Next Best Action Copilot (Streamlit in Snowflake).

QUESTION -> CUSTOMER 360 -> EVIDENCE -> NEXT BEST ACTION -> PERSONALISED OUTREACH -> AUDIT
All data is synthetic. Downstream execution is SIMULATED.
"""
import json

import altair as alt
import pandas as pd
import streamlit as st

import data as d

st.set_page_config(page_title="ACTION360 Copilot", page_icon=":material/hub:", layout="wide")

st.markdown("""
<style>
  .block-container {padding-top: 1.2rem;}
  .a360-flow {font-size:.82rem; letter-spacing:.04em; color:#5b6b7f; margin:-.3rem 0 .8rem 0;}
  .a360-flow b {color:#0b5cad;}
  .a360-tag {display:inline-block; padding:2px 9px; border-radius:10px; font-size:.72rem; font-weight:600; margin-right:4px;}
  .t-fact {background:#e7f1fb; color:#0b5cad;} .t-ai {background:#f3e8fd; color:#7b2cbf;}
  .t-rec {background:#e6f6ec; color:#137333;} .t-sim {background:#fff4e0; color:#a15c00;}
  .t-HIGH {background:#fde7e9; color:#b3261e;} .t-MEDIUM {background:#fff4e0; color:#a15c00;} .t-LOW {background:#e6f6ec; color:#137333;}
  .a360-big {font-size:1.55rem; font-weight:700; color:#0b2b4c; margin:.2rem 0;}
</style>""", unsafe_allow_html=True)

ACTION_LABEL = {
    "SERVICE_RECOVERY": "Service recovery", "COMPLAINT_ESCALATION": "Complaint escalation",
    "PAYMENT_PLAN_DISCUSSION": "Payment-plan discussion", "RETENTION_OFFER": "Retention offer",
    "RENEWAL_REMINDER": "Renewal reminder", "PRODUCT_UPGRADE": "Product upgrade", "CROSS_SELL": "Cross-sell",
    "COVERAGE_REVIEW": "Coverage review", "PROACTIVE_SERVICE_CALL": "Proactive service call",
    "MISSING_DOCUMENT_REQUEST": "Missing-document request", "UNDERWRITING_FOLLOW_UP": "Underwriting follow-up",
    "CLAIM_FOLLOW_UP": "Claim follow-up", "NO_ACTION_MONITOR": "No action - monitor",
}


def tag(text, cls):
    return f'<span class="a360-tag {cls}">{text}</span>'


def inr(v):
    try:
        return f"INR {float(v):,.0f}"
    except (TypeError, ValueError):
        return "-"


def flow(active):
    steps = ["QUESTION", "CUSTOMER 360", "EVIDENCE", "NEXT BEST ACTION", "OUTREACH", "AUDIT"]
    st.markdown('<div class="a360-flow">' + "  &rarr;  ".join(f"<b>{s}</b>" if s in active else s for s in steps)
                + "</div>", unsafe_allow_html=True)


# ------------------------------------------------------------------ state
ss = st.session_state
ss.setdefault("cid", "C10238")
ss.setdefault("nba", None)
ss.setdefault("outreach", None)
ss.setdefault("chat", [])


def select_customer(cid):
    cid = (cid or "").strip().upper()
    if cid != ss.cid:
        ss.cid, ss.nba, ss.outreach = cid, None, None


# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.markdown("### :material/hub: ACTION360")
    st.caption("Customer 360 & Next-Best-Action Copilot")
    page = st.radio("Navigate", [
        ":material/dashboard: Executive overview", ":material/person_search: Customer 360",
        ":material/forum: Ask ACTION360", ":material/bolt: Next best action",
        ":material/timeline: Interaction timeline", ":material/menu_book: Knowledge & evidence",
        ":material/fact_check: Action history", ":material/monitoring: AI & cost observability",
        ":material/science: Evaluation"], label_visibility="collapsed")
    st.divider()
    cid_in = st.text_input("Customer ID", value=ss.cid, help="e.g. C10238")
    select_customer(cid_in)
    with st.expander("Demo personas", expanded=False):
        for _, r in d.personas().iterrows():
            if st.button(f"{r.CUSTOMER_ID} - {ACTION_LABEL.get(r.RECOMMENDED_ACTION, r.RECOMMENDED_ACTION)}",
                         key=f"p_{r.CUSTOMER_ID}", use_container_width=True):
                select_customer(r.CUSTOMER_ID)
                st.rerun()
    st.caption("Synthetic, de-identified data. Actions are SIMULATED.")


def need_customer():
    if not d.customer_exists(ss.cid):
        st.error(f"Customer **{ss.cid}** does not exist. No facts will be shown or invented. Try C10238.")
        st.stop()


# ================================================================== 1. EXECUTIVE OVERVIEW
def page_overview():
    st.title("Executive overview")
    flow({"CUSTOMER 360", "NEXT BEST ACTION"})
    k = d.kpis()
    c = st.columns(6)
    c[0].metric("Total customers", f"{k['TOTAL']:,}")
    c[1].metric("High-risk customers", f"{k['HIGH']:,}", f"{k['HIGH'] / k['TOTAL']:.0%} of book", delta_color="off")
    c[2].metric("Negative sentiment", f"{k['NEG']:,}")
    c[3].metric("Customers needing action", f"{k['NEEDS_ACTION']:,}")
    c[4].metric("Actions generated", f"{k['GENERATED']:,}")
    c[5].metric("Actions approved", f"{k['COMPLETED']:,}")

    left, right = st.columns([1.1, 1])
    with left, st.container(border=True):
        st.markdown("**Risk tier by segment**")
        df = d.risk_by_segment()
        st.altair_chart(alt.Chart(df).mark_bar().encode(
            x=alt.X("SEGMENT:N", title=None), y=alt.Y("CUSTOMERS:Q", title="Customers"),
            color=alt.Color("RISK_TIER:N", scale=alt.Scale(domain=["HIGH", "MEDIUM", "LOW"], range=["#d93025", "#f29900", "#1e8e3e"]),
                            title="Risk tier"), tooltip=["SEGMENT", "RISK_TIER", "CUSTOMERS"]).properties(height=280),
            use_container_width=True)
    with right, st.container(border=True):
        st.markdown("**Recommended action mix (deterministic engine)**")
        df = d.action_mix()
        df["ACTION"] = df["ACTION"].map(lambda a: ACTION_LABEL.get(a, a))
        st.altair_chart(alt.Chart(df).mark_bar(color="#0b5cad").encode(
            y=alt.Y("ACTION:N", sort="-x", title=None), x=alt.X("CUSTOMERS:Q", title="Customers"),
            tooltip=["ACTION", "CUSTOMERS"]).properties(height=280), use_container_width=True)

    with st.container(border=True):
        st.markdown("**Cost-aware AI routing** - expensive LLM enrichment only where it changes the decision")
        r = st.columns(4)
        r[0].metric("RULES_ONLY (no LLM)", f"{k['R_RULES']:,}")
        r[1].metric("SELECTIVE_AI", f"{k['R_SEL']:,}")
        r[2].metric("FULL_AGENT", f"{k['R_FULL']:,}")
        r[3].metric("LLM calls avoided vs. enrich-all", f"{k['R_RULES'] + k['R_SEL']:,}",
                    f"{(k['R_RULES'] + k['R_SEL']) / k['TOTAL']:.0%} of customers", delta_color="off")

    st.subheader("Action worklist")
    f1, f2, _ = st.columns([1, 1.5, 2])
    tier = f1.selectbox("Risk tier", ["ALL", "HIGH", "MEDIUM", "LOW"], index=1)
    action = f2.selectbox("Recommended action", ["ALL"] + [a for a in ACTION_LABEL if a != "NO_ACTION_MONITOR"])
    wl = d.worklist(tier, action)
    ev = st.dataframe(wl, hide_index=True, use_container_width=True, on_select="rerun", selection_mode="single-row",
                      column_config={"VALUE_INR": st.column_config.NumberColumn("Value (INR)", format="%d"),
                                     "RISK": st.column_config.ProgressColumn("Risk", min_value=0, max_value=1, format="%.2f")})
    if ev.selection.rows:
        select_customer(wl.iloc[ev.selection.rows[0]]["CUSTOMER_ID"])
        st.success(f"Selected {ss.cid} - open **Customer 360** or **Next best action**.")


# ================================================================== 2. CUSTOMER 360
def page_customer():
    need_customer()
    c = d.customer_360(ss.cid)
    idn, fin, inter, risk, ai = c["identity"], c["financial"], c["interactions"], c["risk"], c["ai_interpretation"]
    st.title(f"{idn['name']}  ·  {idn['customer_id']}")
    flow({"CUSTOMER 360"})
    st.markdown(tag(f"{risk['risk_tier']} RISK", f"t-{risk['risk_tier']}") + tag(idn["segment"], "t-fact")
                + tag(idn["business_type"], "t-fact") + tag(f"AI route: {risk['ai_route']}", "t-ai"), unsafe_allow_html=True)

    m = st.columns(6)
    m[0].metric("Tenure", f"{idn['tenure_months']} mo")
    m[1].metric("Outstanding", inr(fin["total_outstanding_inr"]))
    m[2].metric("Payment status", fin["payment_status"])
    m[3].metric("Next renewal", str(fin.get("next_renewal_date") or "-"), f"in {fin.get('days_to_renewal')} days", delta_color="off")
    m[4].metric("Complaints (90d)", inter["complaints_90d"], f"{inter['unresolved_complaints']} unresolved", delta_color="inverse")
    m[5].metric("Sentiment (90d)", inter["sentiment"])

    a, b, cc = st.columns([1, 1, 1.2])
    with a, st.container(border=True):
        st.markdown(tag("FACT", "t-fact") + "**Profile**", unsafe_allow_html=True)
        st.write(f"City: {idn['city']} · Age {idn['age']} · Preferred channel: **{idn['preferred_channel']}**")
        st.write(f"Products: {', '.join(fin['products'])}")
        st.write(f"Credit score {fin['credit_score']} · On-time rate (12m) {fin.get('on_time_rate_12m')}")
        st.write(f"Missed/partial (6m): {fin['missed_or_partial_6m']} · Max days late (90d): {fin['max_days_late_90d']}")
        st.write(f"Annual value: {inr(fin['annual_value_inr'])} (percentile {fin['value_percentile']:.0%})")
        if c.get("open_events"):
            st.markdown("**Open servicing events**")
            for e in c["open_events"]:
                st.write(f"- {e['event']} ({e['date']}): {e['details']}")
    with b, st.container(border=True):
        st.markdown(tag("FACT", "t-fact") + "**Risk & top drivers**", unsafe_allow_html=True)
        rd = pd.DataFrame({"Risk": ["Churn", "Payment", "Service"],
                           "Score": [risk["churn_risk"], risk["payment_risk"], risk["service_risk"]]})
        st.altair_chart(alt.Chart(rd).mark_bar().encode(
            x=alt.X("Score:Q", scale=alt.Scale(domain=[0, 1])), y=alt.Y("Risk:N", title=None),
            color=alt.condition(alt.datum.Score >= 0.6, alt.value("#d93025"), alt.value("#0b5cad"))).properties(height=120),
            use_container_width=True)
        for i, drv in enumerate(risk.get("top_drivers") or [], 1):
            st.write(f"{i}. **{drv['label']}** ({drv['model'].lower()} model, +{drv['contribution']:.2f})")
        if not risk.get("top_drivers"):
            st.caption("No material risk drivers.")
    with cc, st.container(border=True):
        st.markdown(tag("AI INTERPRETATION", "t-ai") + "**Customer need & pain points**", unsafe_allow_html=True)
        if ai.get("customer_need"):
            st.write(ai["customer_need"])
            for p in ai.get("pain_points") or []:
                st.write(f"- {p}")
            st.caption(f"claude-haiku-4-5 · generated {ai.get('generated_at')}")
        elif risk["ai_route"] == "RULES_ONLY":
            st.info("LLM summary skipped by cost-aware routing (low risk). Structured insights are sufficient.")
        else:
            if st.button("Generate AI summary", icon=":material/auto_awesome:"):
                with st.spinner("Summarising with claude-haiku-4-5..."):
                    d.call(f"{d.DB}.CORE.GENERATE_CUSTOMER_INSIGHTS", 1, ss.cid)
                    d.customer_360.clear()
                st.rerun()

    t1, t2, t3 = st.tabs(["Products & accounts", "Signals", "Recent interactions"])
    with t1:
        st.dataframe(d.accounts(ss.cid), hide_index=True, use_container_width=True)
    with t2:
        st.dataframe(d.signals(ss.cid), hide_index=True, use_container_width=True,
                     column_config={"VALUE": st.column_config.ProgressColumn(min_value=0, max_value=1, format="%.2f")})
    with t3:
        tl = d.timeline(ss.cid)
        st.dataframe(tl[tl.KIND == "INTERACTION"][["TS", "TITLE", "STATUS", "DETAIL", "REF"]].head(8), hide_index=True,
                     use_container_width=True)
    pv = c["recommendation_preview"]
    st.info(f"**Recommended action:** {ACTION_LABEL.get(pv['action'], pv['action'])}"
            + (f" · offer `{pv['offer_id']}`" if pv.get("offer_id") else "") + " - open **Next best action** for evidence.")


# ================================================================== 3. ASK ACTION360
def page_ask():
    st.title("Ask ACTION360")
    flow({"QUESTION", "CUSTOMER 360", "EVIDENCE", "NEXT BEST ACTION"})
    st.caption("Cortex Agent: Cortex Analyst (semantic view) + 2 Cortex Search services + governed decision tools. "
               "Decisions come from rules; the LLM explains.")
    samples = [f"Why is {ss.cid} high risk?", f"What did {ss.cid} say in their last call?",
               f"What are the main reasons {ss.cid} may leave?", f"What offer is {ss.cid} eligible for?",
               f"What should the relationship manager do next for {ss.cid}?", "Which customers have negative sentiment and an upcoming renewal?"]
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
                    r = {"text": f"Agent unavailable ({e}). Use **Next best action** - the deterministic engine works without the agent.",
                         "tools": [], "latency_s": 0}
                    status.update(label="Agent error", state="error")
            st.markdown(r["text"] or "_No answer returned._")
            if r.get("warnings"):
                st.warning(r["warnings"])
        ss.chat.append({"role": "assistant", "content": r["text"], "tools": r["tools"], "latency": r["latency_s"]})
    if ss.chat and st.button("Clear conversation", icon=":material/delete:"):
        ss.chat = []
        st.rerun()


# ================================================================== 4. NEXT BEST ACTION
def page_nba():
    need_customer()
    c = d.customer_360(ss.cid)
    st.title(f"Next best action · {c['identity']['name']} ({ss.cid})")
    flow({"CUSTOMER 360", "EVIDENCE", "NEXT BEST ACTION", "OUTREACH", "AUDIT"})
    question = st.text_input("Business question", "Why should I contact this customer today and what should I offer?")
    if ss.nba is None or ss.nba.get("customer_id") != ss.cid:
        if st.button("Calculate next best action", type="primary", icon=":material/bolt:"):
            with st.spinner("Scoring candidates, checking eligibility, retrieving evidence..."):
                ss.nba, ss.outreach = d.next_best_action(ss.cid, question), None
            st.rerun()
        st.dataframe(d.candidates(ss.cid).drop(columns=["TOP_CONTRIBUTIONS"]), hide_index=True, use_container_width=True)
        return
    n = ss.nba
    risk = c["risk"]
    with st.container(border=True):
        top = st.columns([2, 1, 1, 1])
        top[0].markdown(tag("RECOMMENDATION", "t-rec") + tag("deterministic", "t-fact"), unsafe_allow_html=True)
        top[0].markdown(f'<div class="a360-big">{ACTION_LABEL.get(n["selected_action"], n["action_name"])}</div>',
                        unsafe_allow_html=True)
        top[0].caption(n.get("business_purpose") or "")
        offer = n.get("offer") or {}
        top[1].metric("Offer", offer.get("offer_id", "None"))
        top[2].metric("Eligibility", "ELIGIBLE" if offer else "N/A")
        top[3].metric("Confidence", n["confidence"])

        w1, w2 = st.columns(2)
        with w1:
            st.markdown("**WHY** - transparent score contributions")
            for r_ in n.get("reasons") or []:
                if r_:
                    st.write(f"- `{r_['signal']}` value {r_['value']:.2f} × weight {r_['weight']:+.2f} = **{r_['contribution']:+.3f}**")
            st.markdown("**Risk context**")
            st.write(f"{risk['risk_tier']} · primary {risk['primary_risk_type']} · drivers: "
                     + ", ".join(x["label"] for x in risk.get("top_drivers") or []) or "none")
        with w2:
            st.markdown("**WHY NOW**")
            for f in n["evidence"]["structured_facts"]:
                st.write(f"- {f}")
            if offer:
                st.markdown("**Eligibility (hard rules passed)**")
                for pr in offer.get("passed_rules") or []:
                    st.write(f":green[✔] {pr}")
            inel = [x for x in (n.get("ineligible_offers_in_category") or []) if x]
            for x in inel:
                st.write(f":red[✘] **{x['offer_name']}** not eligible: " + "; ".join(r for r in x["failed_rules"] if r))

    b1, b2, b3, b4 = st.columns([1.2, 1, 1, 1.2])
    channel = b2.selectbox("Channel", ["", "CALL", "EMAIL", "WHATSAPP", "APP"], format_func=lambda x: x or "Preferred",
                           label_visibility="collapsed")
    if b1.button("Generate outreach", icon=":material/edit_note:", use_container_width=True):
        with st.spinner("Personalising with claude-sonnet-4-6 (decision is locked)..."):
            ss.outreach = d.outreach(n["recommendation_id"], channel)
    show_ev = b3.toggle("View evidence", value=True)
    with b4.popover("Approve & log action", icon=":material/task_alt:", use_container_width=True):
        st.caption("Writes an immutable, hash-chained ACTION_AUDIT record. Downstream execution is SIMULATED.")
        ua = st.radio("Decision", ["APPROVED", "DEFERRED", "REJECTED"], horizontal=True)
        req = st.text_input("Request a different offer (optional)", placeholder="e.g. OFF_RETENTION_CASHBACK")
        note = st.text_input("Note")
        if st.button("Confirm", type="primary"):
            res = d.log_action(n["recommendation_id"], ua, req, note)
            d.audit.clear()
            if res.get("logged"):
                st.success(f"Logged {res['user_action']} · {res['downstream_status']}")
            else:
                st.error(f"Blocked: {res.get('downstream_status') or res.get('error')} "
                         + ("; ".join(r for r in (res.get("failed_rules") or []) if r)))

    if ss.outreach:
        o = ss.outreach
        with st.container(border=True):
            st.markdown(tag("AI-GENERATED PERSONALISATION", "t-ai") + tag(o.get("model", "no LLM"), "t-fact"), unsafe_allow_html=True)
            if not o.get("llm_used"):
                st.info("LLM skipped - stable customer, no outreach needed (cost saved).")
            o1, o2 = st.columns([1.3, 1])
            with o1:
                st.markdown("**Suggested outreach**")
                st.text_area("message", o.get("customer_message") or "-", height=260, label_visibility="collapsed")
            with o2:
                st.markdown("**Why relevant**")
                st.write(o.get("why_relevant"))
                st.markdown("**Why now**")
                st.write(o.get("why_now"))
                st.markdown("**RM talking points**")
                for tp in o.get("rm_talking_points") or []:
                    st.write(f"- {tp}")
                if o.get("evidence_gaps"):
                    st.warning(f"Evidence gaps: {o['evidence_gaps']}")
            if o.get("guardrail_violation"):
                st.error("Post-generation guardrail withheld a message that referenced an ineligible offer.")

    if show_ev:
        e1, e2 = st.columns(2)
        with e1, st.container(border=True):
            st.markdown(tag("FACT", "t-fact") + "**Interaction evidence** (Cortex Search, filtered to customer)", unsafe_allow_html=True)
            ev = n["evidence"]["interaction_evidence"] or []
            if isinstance(ev, dict) or not ev:
                st.caption("Evidence unavailable.")
            for x in ev if isinstance(ev, list) else []:
                st.markdown(f"**{x.get('DOC_ID')}** · {x.get('INTERACTION_DATE')} · {x.get('CHANNEL', '')} · {x.get('SOURCE_TYPE', '')}")
                st.caption((x.get("CONTENT") or "")[:600])
        with e2, st.container(border=True):
            st.markdown(tag("FACT", "t-fact") + "**Policy / offer evidence** (Cortex Search)", unsafe_allow_html=True)
            kb = n["evidence"]["policy_evidence"] or []
            if not kb:
                st.caption("Not retrieved (RULES_ONLY route) or unavailable.")
            for x in kb if isinstance(kb, list) else []:
                st.markdown(f"**{x.get('TITLE')}** - {x.get('SECTION')}")
                st.caption((x.get("CHUNK_TEXT") or "")[:600])
    with st.expander("All candidate actions (scored, gated, ranked)"):
        st.dataframe(d.candidates(ss.cid).drop(columns=["TOP_CONTRIBUTIONS"]), hide_index=True, use_container_width=True)
    if st.button("Recalculate", icon=":material/refresh:"):
        ss.nba, ss.outreach = None, None
        st.rerun()


# ================================================================== 5. TIMELINE
@st.dialog("Call transcript", width="large")
def show_transcript(ref):
    t = d.transcript(ref)
    if t.empty:
        st.info("No transcript for this interaction (note only).")
        return
    r = t.iloc[0]
    st.markdown(tag(r.SOURCE_TYPE, "t-fact") + tag(f"AI sentiment {r.AI_SENTIMENT_SCORE}", "t-ai")
                + tag(f"intent {r.AI_INTENT}", "t-ai"), unsafe_allow_html=True)
    st.caption(f"{r.SOURCE_FILE} · {r.CALL_TS} · {r.DURATION_SEC}s")
    for line in (r.TRANSCRIPT_TEXT or "").splitlines():
        who, _, said = line.partition(":")
        st.chat_message("user" if who.strip() == "CUSTOMER" else "assistant").write(said.strip() or line)


def page_timeline():
    need_customer()
    st.title(f"Interaction timeline · {ss.cid}")
    flow({"CUSTOMER 360", "EVIDENCE"})
    tl = d.timeline(ss.cid)
    kinds = st.multiselect("Show", sorted(tl.KIND.unique()), default=sorted(tl.KIND.unique()))
    tl = tl[tl.KIND.isin(kinds)]
    st.altair_chart(alt.Chart(tl).mark_circle(size=140).encode(
        x=alt.X("TS:T", title=None), y=alt.Y("KIND:N", title=None),
        color=alt.Color("STATUS:N"), tooltip=["TS", "KIND", "TITLE", "STATUS", "DETAIL"]).properties(height=220),
        use_container_width=True)
    ev = st.dataframe(tl[["TS", "KIND", "TITLE", "STATUS", "DETAIL", "REF", "HAS_TRANSCRIPT"]], hide_index=True,
                      use_container_width=True, on_select="rerun", selection_mode="single-row")
    if ev.selection.rows:
        row = tl.iloc[ev.selection.rows[0]]
        if row.KIND == "INTERACTION":
            show_transcript(row.REF)


# ================================================================== 6. KNOWLEDGE
def page_knowledge():
    st.title("Knowledge & evidence")
    flow({"EVIDENCE"})
    industry = "LENDING"
    if d.customer_exists(ss.cid):
        industry = d.customer_360(ss.cid)["identity"]["business_type"]
    qtext = st.text_input("Search product / policy / offer / underwriting knowledge",
                          "When can we offer a retention discount if the customer has an open complaint?")
    ind = st.segmented_control("Line of business", ["LENDING", "INSURANCE"], default=industry)
    if qtext:
        for x in d.knowledge(qtext, ind or industry):
            with st.container(border=True):
                st.markdown(f"**{x.get('TITLE')}** · {x.get('SECTION')} " + tag(x.get("DOC_TYPE", ""), "t-fact"), unsafe_allow_html=True)
                st.write(x.get("CHUNK_TEXT"))
                st.caption(f"Source: {x.get('CHUNK_ID')}")
    if ss.nba and ss.nba.get("customer_id") == ss.cid:
        st.subheader("Evidence behind the current recommendation")
        st.json(ss.nba["evidence"], expanded=False)


# ================================================================== 7. ACTION HISTORY
def page_audit():
    st.title("Action history (ACTION_AUDIT)")
    flow({"AUDIT"})
    st.markdown(tag("SIMULATED downstream execution", "t-sim") + tag("append-only, hash-chained", "t-fact"), unsafe_allow_html=True)
    a = d.audit()
    c = st.columns(4)
    c[0].metric("Records", len(a))
    c[1].metric("Approved", int((a.USER_ACTION == "APPROVED").sum()) if len(a) else 0)
    c[2].metric("Blocked (ineligible offer)", int((a.USER_ACTION == "BLOCKED_INELIGIBLE_OFFER").sum()) if len(a) else 0)
    c[3].metric("Customers actioned", a.CUSTOMER_ID.nunique() if len(a) else 0)
    st.dataframe(a, hide_index=True, use_container_width=True)


# ================================================================== 8. AI & COST
def page_cost():
    st.title("AI & cost observability")
    flow(set())
    k = d.kpis()
    u = d.ai_usage()
    used = u[~u.SKIPPED]
    skipped = u[u.SKIPPED]
    cfg = d.config().set_index("CONFIG_KEY")["CONFIG_VALUE"]
    m = st.columns(5)
    m[0].metric("Cortex AI calls", f"{int(used.CALLS.sum()):,}")
    m[1].metric("AI calls avoided by routing", f"{int(skipped.CALLS.sum()):,}")
    m[2].metric("Agent calls", f"{int(u[u.COMPONENT == 'CORTEX_AGENT'].CALLS.sum()):,}")
    m[3].metric("Est. tokens processed", f"{int(used.EST_TOKENS.sum()):,}")
    m[4].metric("Customers LLM-summarised", f"{k['ENRICHED']:,}", f"of {k['R_FULL']:,} FULL_AGENT", delta_color="off")
    st.caption(f"Routing thresholds: FULL ≥ {cfg.get('LLM_ENRICHMENT_THRESHOLD')} · SELECTIVE ≥ {cfg.get('SELECTIVE_ENRICHMENT_THRESHOLD')} "
               f"· models: {cfg.get('LIGHT_MODEL')} (summaries), {cfg.get('PERSONALIZATION_MODEL')} (outreach/agent)")
    st.dataframe(u, hide_index=True, use_container_width=True)
    lat = u[u.AVG_LATENCY_MS.notna()][["COMPONENT", "AVG_LATENCY_MS"]]
    if len(lat):
        st.altair_chart(alt.Chart(lat).mark_bar(color="#7b2cbf").encode(
            y=alt.Y("COMPONENT:N", sort="-x", title=None), x=alt.X("AVG_LATENCY_MS:Q", title="Avg latency (ms)")).properties(height=200),
            use_container_width=True)
    st.subheader("Metered credits (ACCOUNT_USAGE, lags up to ~3h)")
    au = d.account_usage()
    if "error" in au:
        st.info(f"ACCOUNT_USAGE not accessible for this role: {au['error'][:160]}")
    else:
        c1, c2 = st.columns(2)
        c1.markdown("**ACTION360_WH credits / day**")
        c1.bar_chart(au["warehouse"], x="DAY", y="CREDITS")
        c2.markdown("**Credits by service (account, 14d)**")
        c2.dataframe(au["services"], hide_index=True, use_container_width=True)
        st.caption(f"Total metered (14d): {au['services'].CREDITS.sum():.2f} credits · warehouse XS, auto-suspend 60s, resource monitor 60 credits.")


# ================================================================== 9. EVALUATION
def page_eval():
    st.title("Evaluation")
    flow(set())
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


PAGES = {"Executive": page_overview, "Customer 360": page_customer, "Ask": page_ask, "Next best": page_nba,
         "Interaction": page_timeline, "Knowledge": page_knowledge, "Action history": page_audit,
         "AI & cost": page_cost, "Evaluation": page_eval}
next(fn for key, fn in PAGES.items() if key in page)()
