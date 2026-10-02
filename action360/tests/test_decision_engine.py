"""Eligibility logic, NBA scoring, guardrails, tool contracts, action logging - incl. negative tests."""
import pytest

from conftest import ai, one, proc

C = "ACTION360_DB.CORE"
NBA = "CALL ACTION360_DB.AI.CALCULATE_NEXT_BEST_ACTION(%s, %s)"


@pytest.mark.parametrize("cid,action,offer", [
    ("C10238", "SERVICE_RECOVERY", "OFF_FEE_WAIVER"),
    ("C10417", "PAYMENT_PLAN_DISCUSSION", "OFF_HARDSHIP_PLAN"),
    ("C10555", "PRODUCT_UPGRADE", "OFF_CARD_UPGRADE"),
    ("C10789", "COVERAGE_REVIEW", "OFF_FAMILY_FLOATER"),
    ("C10901", "NO_ACTION_MONITOR", None),
    ("C11024", "CLAIM_FOLLOW_UP", None),
])
def test_persona_next_best_actions(cur, cid, action, offer):
    r = proc(cur, NBA, (cid, "test"))
    assert r["selected_action"] == action
    assert (r.get("offer") or {}).get("offer_id") == offer


def test_personas_get_distinct_actions(cur):
    acts = {r[0] for r in cur.execute(f"""SELECT RECOMMENDED_ACTION FROM {C}.CUSTOMER_360
             WHERE CUSTOMER_ID IN ('C10238','C10417','C10555','C10789','C10901','C11024')""").fetchall()}
    assert len(acts) == 6


def test_score_is_reproducible_from_weights(cur):
    """Engine score == BASE_SCORE + sum(weight x signal) recomputed independently."""
    eng, recomputed = one(cur, f"""
      WITH sig AS (SELECT CUSTOMER_ID, SIGNAL_NAME, SIGNAL_VALUE FROM {C}.CUSTOMER_SIGNAL WHERE CUSTOMER_ID='C10417'
                   UNION ALL SELECT 'C10417', 'PAYMENT_RISK', PAYMENT_RISK FROM {C}.CUSTOMER_RISK WHERE CUSTOMER_ID='C10417')
      SELECT (SELECT ACTION_SCORE FROM {C}.NBA_CANDIDATE WHERE CUSTOMER_ID='C10417' AND ACTION_CODE='PAYMENT_PLAN_DISCUSSION'),
             (SELECT BASE_SCORE FROM {C}.ACTION_CATALOG WHERE ACTION_CODE='PAYMENT_PLAN_DISCUSSION')
             + SUM(w.WEIGHT * s.SIGNAL_VALUE)
      FROM {C}.NBA_WEIGHT w JOIN sig s USING (SIGNAL_NAME) WHERE w.ACTION_CODE='PAYMENT_PLAN_DISCUSSION'""")
    assert abs(float(eng) - float(recomputed)) < 1e-3


def test_eligible_offer_passes_all_rules(cur):
    r = proc(cur, "CALL ACTION360_DB.AI.CHECK_OFFER_ELIGIBILITY(%s, %s)", ("C10417", "OFF_HARDSHIP_PLAN"))
    o = r["offers"][0]
    assert o["eligibility"] == "ELIGIBLE" and not [x for x in o["failed_rules"] if x]


# ---------------------------------------------------------------- negative tests
def test_neg_not_eligible_for_offer(cur):
    r = proc(cur, "CALL ACTION360_DB.AI.CHECK_OFFER_ELIGIBILITY(%s, %s)", ("C10417", "OFF_RETENTION_CASHBACK"))
    o = r["offers"][0]
    assert o["eligibility"] == "NOT ELIGIBLE"
    assert any("missed" in (x or "").lower() for x in o["failed_rules"])


def test_neg_conflicting_information_rules_win(cur):
    """Transcript: customer asks for loyalty discount. Rules: 2 claims in 12m -> not eligible."""
    said = one(cur, f"SELECT COUNT(*) FROM {C}.CALL_TRANSCRIPT WHERE CUSTOMER_ID='C11024' AND TRANSCRIPT_TEXT ILIKE '%loyalty discount%'")[0]
    assert said >= 1
    r = proc(cur, "CALL ACTION360_DB.AI.CHECK_OFFER_ELIGIBILITY(%s, %s)", ("C11024", "OFF_LOYALTY_RENEWAL"))
    assert r["offers"][0]["eligibility"] == "NOT ELIGIBLE"
    assert proc(cur, NBA, ("C11024", "apply loyalty discount"))["selected_action"] != "RETENTION_OFFER"


def test_neg_insufficient_evidence(cur):
    cid = one(cur, f"""SELECT c.CUSTOMER_ID FROM {C}.DIM_CUSTOMER c LEFT JOIN {C}.FACT_INTERACTION i USING (CUSTOMER_ID)
                       WHERE i.CUSTOMER_ID IS NULL ORDER BY 1 LIMIT 1""")[0]
    r = proc(cur, NBA, (cid, "why contact?"))
    assert r["found"] and not (r["evidence"]["interaction_evidence"] or [])


def test_neg_nonexistent_customer(cur):
    for call in ("CALL ACTION360_DB.AI.GET_CUSTOMER_360(%s)",):
        assert proc(cur, call, ("C99999",))["found"] is False
    assert proc(cur, NBA, ("C99999", "x"))["found"] is False
    assert proc(cur, "CALL ACTION360_DB.AI.CHECK_OFFER_ELIGIBILITY(%s, %s)", ("C99999", ""))["found"] is False


def test_neg_action_violating_eligibility_is_blocked(cur):
    # guardrail: no upsell during payment stress
    st = one(cur, f"SELECT CANDIDATE_STATUS FROM {C}.NBA_CANDIDATE WHERE CUSTOMER_ID='C10417' AND ACTION_CODE='PRODUCT_UPGRADE'")[0]
    assert st in ("BLOCKED_GUARDRAIL", "NOT_ELIGIBLE")
    # and the audit write path refuses an ineligible offer
    rec = proc(cur, NBA, ("C10417", "offer top-up"))
    res = proc(cur, "CALL ACTION360_DB.AI.LOG_ACTION(%s, 'APPROVED', 'OFF_TOPUP_LOAN', 'pytest')", (rec["recommendation_id"],))
    assert res["user_action"] == "BLOCKED_INELIGIBLE_OFFER" and res["logged"] is False


def test_no_selected_offer_is_ever_ineligible(cur):
    bad = one(cur, f"""SELECT COUNT(*) FROM {C}.CUSTOMER_360 c JOIN {C}.OFFER_ELIGIBILITY e
                      ON e.CUSTOMER_ID = c.CUSTOMER_ID AND e.OFFER_ID = c.RECOMMENDED_OFFER_ID WHERE NOT e.IS_ELIGIBLE""")[0]
    assert bad == 0


def test_no_blocked_action_is_selected(cur):
    assert one(cur, f"SELECT COUNT(*) FROM {C}.NBA_CANDIDATE WHERE ELIGIBLE_RANK IS NOT NULL AND CANDIDATE_STATUS <> 'ELIGIBLE'")[0] == 0


# ---------------------------------------------------------------- action logging
def test_log_action_writes_hash_chained_audit(cur):
    rec = proc(cur, NBA, ("C10238", "pytest"))
    res = proc(cur, "CALL ACTION360_DB.AI.LOG_ACTION(%s, 'DEFERRED', '', 'pytest')", (rec["recommendation_id"],))
    assert res["logged"] and res["execution_mode"] == "SIMULATED"
    row = one(cur, f"SELECT RECORD_HASH, PREV_HASH, ARRAY_SIZE(EVIDENCE_REFERENCES) FROM {C}.ACTION_AUDIT WHERE AUDIT_ID=%s",
              (res["audit_id"],))
    assert len(row[0]) == 64 and row[2] >= 2


def test_log_action_rejects_invalid_user_action(cur):
    rec = proc(cur, NBA, ("C10238", "pytest"))
    assert proc(cur, "CALL ACTION360_DB.AI.LOG_ACTION(%s, 'DELETE_EVERYTHING', '', '')", (rec["recommendation_id"],))["logged"] is False


def test_low_risk_outreach_skips_llm(cur):
    rec = proc(cur, NBA, ("C10901", "contact?"))
    out = proc(cur, "CALL ACTION360_DB.AI.GENERATE_PERSONALIZED_OUTREACH(%s, '', FALSE)", (rec["recommendation_id"],))
    assert out["llm_used"] is False


# ---------------------------------------------------------------- LLM / agent (opt-in)
@ai
def test_prompt_output_structure(cur):
    rec = proc(cur, NBA, ("C10417", "pytest"))
    out = proc(cur, "CALL ACTION360_DB.AI.GENERATE_PERSONALIZED_OUTREACH(%s, 'WHATSAPP', FALSE)", (rec["recommendation_id"],))
    for k in ("why_relevant", "why_now", "customer_message", "rm_talking_points", "evidence_gaps"):
        assert k in out and out[k] is not None
    assert out["guardrail_violation"] is False
    assert "cashback" not in out["customer_message"].lower()


@ai
def test_agent_orchestrates_tools_and_refuses_ineligible(cur):
    from ask_agent import ask, summarize
    r = summarize(ask(cur, "Can I give C10417 the INR 5000 retention cashback?"))
    assert "check_offer_eligibility" in r["tools"]
    assert "not eligible" in r["text"].lower() or "cannot" in r["text"].lower()
