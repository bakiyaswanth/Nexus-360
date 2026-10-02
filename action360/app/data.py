"""Data access layer for the ACTION360 Streamlit app.

All business logic lives in Snowflake (dynamic tables, rules, procedures, agent).
This module only reads governed objects and calls governed procedures.
"""
from __future__ import annotations

import json
import time

import pandas as pd
import streamlit as st

DB = "ACTION360_DB"
AGENT = f"{DB}.AI.ACTION360_AGENT"


@st.cache_resource
def conn():
    """DB-API connection: Snowpark session inside Streamlit-in-Snowflake, st.connection locally."""
    try:
        from snowflake.snowpark.context import get_active_session
        return get_active_session().connection
    except Exception:  # noqa: BLE001 - not running inside Snowflake
        return st.connection("snowflake").raw_connection


def _cursor():
    return conn().cursor()


def _sql(sql: str) -> str:
    # queries are written with qmark (?) binds; adapt to connections using pyformat (%s)
    return sql if getattr(conn(), "_paramstyle", "qmark") == "qmark" else sql.replace("?", "%s")


def q(sql: str, params: tuple | None = None) -> pd.DataFrame:
    """Parameterised read returning a DataFrame with upper-case columns."""
    cur = _cursor()
    try:
        cur.execute(_sql(sql), params or ())
        cols = [c[0].upper() for c in cur.description]
        return pd.DataFrame(cur.fetchall(), columns=cols)
    finally:
        cur.close()


def call(proc: str, *args) -> dict:
    """CALL a VARIANT-returning procedure and decode JSON (with one retry for transient errors)."""
    placeholders = ", ".join(["?"] * len(args))
    for attempt in range(2):
        cur = _cursor()
        try:
            cur.execute(_sql(f"CALL {proc}({placeholders})"), args)
            val = cur.fetchone()[0]
            return json.loads(val) if isinstance(val, str) else val
        except Exception:  # noqa: BLE001 - retry once, then surface
            if attempt == 1:
                raise
            time.sleep(1.5)
        finally:
            cur.close()
    return {}


def as_json(v):
    if isinstance(v, str):
        try:
            return json.loads(v)
        except ValueError:
            return v
    return v


# ------------------------------------------------------------------ overview
@st.cache_data(ttl=300, show_spinner=False)
def kpis() -> dict:
    df = q(f"""
      SELECT COUNT(*) TOTAL, COUNT_IF(RISK_TIER='HIGH') HIGH, COUNT_IF(RISK_TIER='MEDIUM') MEDIUM, COUNT_IF(RISK_TIER='LOW') LOW,
             COUNT_IF(SENTIMENT_LABEL='NEGATIVE') NEG, COUNT_IF(NEEDS_ACTION) NEEDS_ACTION,
             COUNT_IF(AI_ROUTE='FULL_AGENT') R_FULL, COUNT_IF(AI_ROUTE='SELECTIVE_AI') R_SEL, COUNT_IF(AI_ROUTE='RULES_ONLY') R_RULES,
             COUNT_IF(CUSTOMER_NEED IS NOT NULL) ENRICHED
      FROM {DB}.CORE.CUSTOMER_360""")
    out = df.iloc[0].to_dict()
    a = q(f"""SELECT (SELECT COUNT(*) FROM {DB}.CORE.NBA_RECOMMENDATION) GEN,
                     (SELECT COUNT_IF(USER_ACTION='APPROVED') FROM {DB}.CORE.ACTION_AUDIT) DONE""").iloc[0]
    out.update(GENERATED=int(a["GEN"]), COMPLETED=int(a["DONE"]))
    return out


@st.cache_data(ttl=300, show_spinner=False)
def risk_by_segment() -> pd.DataFrame:
    return q(f"""SELECT SEGMENT, RISK_TIER, COUNT(*) CUSTOMERS FROM {DB}.CORE.CUSTOMER_360 GROUP BY 1, 2 ORDER BY 1, 2""")


@st.cache_data(ttl=300, show_spinner=False)
def action_mix() -> pd.DataFrame:
    return q(f"""SELECT RECOMMENDED_ACTION ACTION, COUNT(*) CUSTOMERS FROM {DB}.CORE.CUSTOMER_360
                 GROUP BY 1 ORDER BY 2 DESC""")


@st.cache_data(ttl=120, show_spinner=False)
def worklist(tier: str, action: str, limit: int = 200) -> pd.DataFrame:
    return q(f"""
      SELECT CUSTOMER_ID, FULL_NAME, SEGMENT, INDUSTRY_TYPE, RISK_TIER, PRIMARY_RISK_TYPE, ROUND(RISK_SCORE, 2) RISK,
             SENTIMENT_LABEL SENTIMENT, DAYS_TO_RENEWAL, UNRESOLVED_COUNT UNRESOLVED, RECOMMENDED_ACTION, RECOMMENDED_OFFER_ID OFFER,
             AI_ROUTE, ANNUAL_VALUE_INR VALUE_INR
      FROM {DB}.CORE.CUSTOMER_360
      WHERE (? = 'ALL' OR RISK_TIER = ?) AND (? = 'ALL' OR RECOMMENDED_ACTION = ?) AND NEEDS_ACTION
      ORDER BY RISK_SCORE * (0.5 + VALUE_PERCENTILE) DESC LIMIT {int(limit)}""", (tier, tier, action, action))


@st.cache_data(ttl=600, show_spinner=False)
def personas() -> pd.DataFrame:
    return q(f"""SELECT c.CUSTOMER_ID, c.FULL_NAME, c.RISK_TIER, c.RECOMMENDED_ACTION, c.AI_ROUTE
                 FROM {DB}.CORE.CUSTOMER_360 c JOIN {DB}.RAW.CUSTOMER_ARCHETYPE a USING (CUSTOMER_ID)
                 WHERE a.IS_DEMO_PERSONA ORDER BY c.RISK_SCORE DESC""")


# ------------------------------------------------------------------ customer
@st.cache_data(ttl=120, show_spinner=False)
def customer_360(cid: str) -> dict:
    return as_json(call(f"{DB}.AI.GET_CUSTOMER_360", cid))


@st.cache_data(ttl=120, show_spinner=False)
def accounts(cid: str) -> pd.DataFrame:
    return q(f"""SELECT a.ACCOUNT_ID, p.PRODUCT_NAME, a.STATUS, a.OPEN_DATE, a.PRINCIPAL_OR_SUM_ASSURED PRINCIPAL_OR_COVER,
                        a.OUTSTANDING_BALANCE, a.INTEREST_RATE, a.MONTHLY_INSTALMENT, a.RENEWAL_OR_RESET_DATE
                 FROM {DB}.CORE.FACT_ACCOUNT a JOIN {DB}.CORE.DIM_PRODUCT p USING (PRODUCT_CODE)
                 WHERE a.CUSTOMER_ID = ? ORDER BY a.ACCOUNT_ID""", (cid,))


@st.cache_data(ttl=120, show_spinner=False)
def signals(cid: str) -> pd.DataFrame:
    return q(f"""SELECT DISPLAY_NAME SIGNAL, SIGNAL_VALUE VALUE, SIGNAL_SOURCE SOURCE FROM {DB}.CORE.CUSTOMER_SIGNAL
                 WHERE CUSTOMER_ID = ? AND SIGNAL_VALUE > 0 ORDER BY SIGNAL_VALUE DESC""", (cid,))


@st.cache_data(ttl=120, show_spinner=False)
def timeline(cid: str) -> pd.DataFrame:
    return q(f"""
      SELECT INTERACTION_TS::TIMESTAMP_NTZ TS, 'INTERACTION' KIND, CHANNEL || ' - ' || TOPIC TITLE,
             RESOLUTION_STATUS STATUS, NOTE DETAIL, INTERACTION_ID REF, HAS_TRANSCRIPT, IS_COMPLAINT
      FROM {DB}.CORE.FACT_INTERACTION WHERE CUSTOMER_ID = ?
      UNION ALL
      SELECT DUE_DATE::TIMESTAMP_NTZ, 'PAYMENT', 'Instalment / premium ' || PAYMENT_STATUS, PAYMENT_STATUS,
             'Due ' || AMOUNT_DUE || ', paid ' || AMOUNT_PAID || ', days late ' || DAYS_LATE, PAYMENT_ID, FALSE, FALSE
      FROM {DB}.CORE.FACT_PAYMENT WHERE CUSTOMER_ID = ? AND (PAYMENT_STATUS <> 'ON_TIME' OR DUE_DATE >= DATEADD(month, -3, '2026-10-02'::DATE))
      UNION ALL
      SELECT EVENT_DATE::TIMESTAMP_NTZ, 'ACCOUNT EVENT', EVENT_TYPE, EVENT_STATUS, DETAILS, EVENT_ID, FALSE, FALSE
      FROM {DB}.CORE.FACT_CLAIM_OR_LOAN_EVENT WHERE CUSTOMER_ID = ?
      UNION ALL
      SELECT RENEWAL_OR_RESET_DATE::TIMESTAMP_NTZ, 'RENEWAL', PRODUCT_CODE || ' renewal / rate reset', 'UPCOMING',
             'Account ' || ACCOUNT_ID, ACCOUNT_ID, FALSE, FALSE
      FROM {DB}.CORE.FACT_ACCOUNT WHERE CUSTOMER_ID = ? AND RENEWAL_OR_RESET_DATE <= DATEADD(day, 120, '2026-10-02'::DATE)
      ORDER BY TS DESC""", (cid, cid, cid, cid))


@st.cache_data(ttl=600, show_spinner=False)
def transcript(interaction_id: str) -> pd.DataFrame:
    return q(f"""SELECT TRANSCRIPT_ID, SOURCE_TYPE, SOURCE_FILE, CALL_TS, DURATION_SEC, TRANSCRIPT_TEXT, AI_SENTIMENT_SCORE,
                        AI_INTENT, AI_COMPLAINT_CATEGORY
                 FROM {DB}.CORE.CALL_TRANSCRIPT WHERE INTERACTION_ID = ?""", (interaction_id,))


@st.cache_data(ttl=120, show_spinner=False)
def candidates(cid: str) -> pd.DataFrame:
    return q(f"""SELECT ACTION_NAME, ACTION_CODE, ROUND(ACTION_SCORE, 3) SCORE, CANDIDATE_STATUS STATUS, ELIGIBLE_RANK RANK,
                        SELECTED_OFFER:offer_id::STRING OFFER, ARRAY_TO_STRING(BLOCK_REASONS, '; ') BLOCKED_BY, TOP_CONTRIBUTIONS
                 FROM {DB}.CORE.NBA_CANDIDATE WHERE CUSTOMER_ID = ?
                 ORDER BY IFF(CANDIDATE_STATUS = 'ELIGIBLE', 0, 1), ACTION_SCORE DESC""", (cid,))


@st.cache_data(ttl=120, show_spinner=False)
def eligibility(cid: str) -> pd.DataFrame:
    return q(f"""SELECT OFFER_ID, OFFER_NAME, OFFER_CATEGORY, IFF(IS_ELIGIBLE, 'ELIGIBLE', 'NOT ELIGIBLE') ELIGIBILITY,
                        ARRAY_TO_STRING(FAILED_RULES, '; ') FAILED_RULES, ARRAY_TO_STRING(PASSED_RULES, '; ') PASSED_RULES
                 FROM {DB}.CORE.OFFER_ELIGIBILITY WHERE CUSTOMER_ID = ? ORDER BY IS_ELIGIBLE DESC, PRIORITY DESC""", (cid,))


def customer_exists(cid: str) -> bool:
    return not q(f"SELECT 1 FROM {DB}.CORE.DIM_CUSTOMER WHERE CUSTOMER_ID = ?", (cid,)).empty


# ------------------------------------------------------------------ decisions
def next_best_action(cid: str, question: str) -> dict:
    return as_json(call(f"{DB}.AI.CALCULATE_NEXT_BEST_ACTION", cid, question))


def outreach(rec_id: str, channel: str, force: bool = False) -> dict:
    return as_json(call(f"{DB}.AI.GENERATE_PERSONALIZED_OUTREACH", rec_id, channel, force))


def log_action(rec_id: str, user_action: str, requested_offer: str, note: str) -> dict:
    res = as_json(call(f"{DB}.AI.LOG_ACTION", rec_id, user_action, requested_offer, note))
    kpis.clear()
    return res


def knowledge(query_text: str, industry: str) -> list:
    req = {"query": query_text, "columns": ["CHUNK_ID", "TITLE", "SECTION", "DOC_TYPE", "CHUNK_TEXT"], "limit": 4,
           "filter": {"@or": [{"@eq": {"INDUSTRY_TYPE": industry}}, {"@eq": {"INDUSTRY_TYPE": "ALL"}}]}}
    cur = _cursor()
    try:
        cur.execute(_sql(f"CALL {DB}.AI.SEARCH_SERVICE('KNOWLEDGE_SEARCH', PARSE_JSON(?))"), (json.dumps(req),))
        return as_json(cur.fetchone()[0]) or []
    finally:
        cur.close()


# ------------------------------------------------------------------ agent
def ask_agent(history: list[dict]) -> dict:
    """Run the Cortex Agent with conversation history. Returns text, tool trace, citations, latency."""
    messages = [{"role": m["role"], "content": [{"type": "text", "text": m["content"]}]} for m in history]
    t0 = time.time()
    cur = _cursor()
    try:
        cur.execute(_sql("SELECT SNOWFLAKE.CORTEX.DATA_AGENT_RUN(?, ?)"), (AGENT, json.dumps({"messages": messages})))
        resp = json.loads(cur.fetchone()[0])
    finally:
        cur.close()
    latency = round(time.time() - t0, 1)
    text, tools, results = [], [], []
    for c in resp.get("content", []):
        if c.get("type") == "text":
            text.append(c.get("text", ""))
        elif c.get("type") == "tool_use":
            tools.append(c["tool_use"].get("name"))
        elif c.get("type") == "tool_result":
            results.append(c.get("tool_result", {}))
    cur = _cursor()
    try:
        cur.execute(_sql(f"""INSERT INTO {DB}.CORE.AI_USAGE_METRICS (COMPONENT, AI_ROUTE, AI_FUNCTION, MODEL, CALLS, LATENCY_MS, DETAILS)
                        SELECT 'CORTEX_AGENT', 'FULL_AGENT', 'DATA_AGENT_RUN', 'claude-sonnet-4-6', 1, ?, PARSE_JSON(?)"""),
                    (int(latency * 1000), json.dumps({"tools": tools})))
    finally:
        cur.close()
    return {"text": "\n".join(text).strip(), "tools": tools, "tool_results": results, "latency_s": latency,
            "warnings": resp.get("warnings")}


# ------------------------------------------------------------------ audit / cost / eval
@st.cache_data(ttl=30, show_spinner=False)
def audit() -> pd.DataFrame:
    return q(f"""SELECT ACTED_AT, CUSTOMER_ID, RECOMMENDATION, OFFER_ID, ELIGIBILITY_STATUS, USER_ACTION, EXECUTION_MODE,
                        DOWNSTREAM_STATUS, ACTED_BY, ACTED_ROLE, ARRAY_TO_STRING(EVIDENCE_REFERENCES, ', ') EVIDENCE,
                        LEFT(RECORD_HASH, 16) || '...' RECORD_HASH, AUDIT_ID
                 FROM {DB}.CORE.ACTION_AUDIT ORDER BY ACTED_AT DESC LIMIT 500""")


@st.cache_data(ttl=60, show_spinner=False)
def ai_usage() -> pd.DataFrame:
    return q(f"""SELECT COMPONENT, AI_FUNCTION, MODEL, SKIPPED, SUM(CALLS) CALLS, SUM(EST_TOKENS) EST_TOKENS,
                        ROUND(AVG(NULLIF(LATENCY_MS, 0))) AVG_LATENCY_MS, COUNT(*) EVENTS
                 FROM {DB}.CORE.AI_USAGE_METRICS GROUP BY 1, 2, 3, 4 ORDER BY CALLS DESC""")


@st.cache_data(ttl=600, show_spinner=False)
def account_usage() -> dict:
    """Actual metered credits from ACCOUNT_USAGE (may lag up to ~3h; requires access)."""
    out = {}
    try:
        out["warehouse"] = q("""SELECT DATE_TRUNC('day', START_TIME)::DATE DAY, ROUND(SUM(CREDITS_USED), 3) CREDITS
                                FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
                                WHERE WAREHOUSE_NAME = 'ACTION360_WH' AND START_TIME >= DATEADD(day, -14, CURRENT_TIMESTAMP())
                                GROUP BY 1 ORDER BY 1""")
        out["services"] = q("""SELECT SERVICE_TYPE, ROUND(SUM(CREDITS_USED), 3) CREDITS
                               FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_DAILY_HISTORY
                               WHERE USAGE_DATE >= DATEADD(day, -14, CURRENT_DATE()) GROUP BY 1 ORDER BY 2 DESC""")
    except Exception as e:  # noqa: BLE001
        out["error"] = str(e)
    return out


@st.cache_data(ttl=60, show_spinner=False)
def evaluation() -> pd.DataFrame:
    try:
        return q(f"SELECT * FROM {DB}.CORE.EVALUATION_RESULT ORDER BY CASE_ID")
    except Exception:  # noqa: BLE001
        return pd.DataFrame()


@st.cache_data(ttl=600, show_spinner=False)
def config() -> pd.DataFrame:
    return q(f"SELECT CONFIG_KEY, CONFIG_VALUE, DESCRIPTION FROM {DB}.CORE.APP_CONFIG ORDER BY 1")
