"""Offer retrieval -> eligibility -> recommendation flow against live Snowflake objects (deterministic, no LLM)."""
import sys
from pathlib import Path

import pytest

from conftest import one, proc

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import contracts as k  # noqa: E402

OFFERS = "CALL ACTION360_DB.AI.GET_CUSTOMER_OFFERS(%s)"


def offers(cur, cid):
    return k.validate_offer_contract(proc(cur, OFFERS, (cid,)), cid)


def test_a_high_risk_customer_gets_populated_eligible_offer(cur):
    c = offers(cur, "C10238")
    assert c["ok"] and not c["issues"], c["issues"]
    assert c["recommended_action"] == "SERVICE_RECOVERY" and c["offer_status"] == k.RECOMMENDED
    o = c["offer"]
    assert o["offer_id"] == "OFF_FEE_WAIVER" and o["offer_name"] and o["description"]
    assert o["eligibility_status"] == k.ELIGIBLE and o["passed_rules"] and "hard rules passed" in o["reason"]
    assert o["business_purpose"] and o["expected_business_outcome"]


def test_contract_matches_engine_and_customer_360(cur):
    for cid in ("C10238", "C10417", "C10555", "C10789", "C10901", "C11024"):
        c = offers(cur, cid)
        row = one(cur, "SELECT RECOMMENDED_ACTION, RECOMMENDED_OFFER_ID FROM ACTION360_DB.CORE.CUSTOMER_360 WHERE CUSTOMER_ID=%s", (cid,))
        assert c["recommended_action"] == row[0], cid
        assert (c["offer"] or {}).get("offer_id") == row[1], cid


def test_contract_matches_calculate_next_best_action(cur):
    n = k.parse_nba_response(proc(cur, "CALL ACTION360_DB.AI.CALCULATE_NEXT_BEST_ACTION(%s, 'pytest offer flow')", ("C10555",)), "C10555")
    c = offers(cur, "C10555")
    assert n["ok"] and n["selected_action"] == c["recommended_action"] and n["offer_id"] == c["offer"]["offer_id"]


@pytest.mark.parametrize("has_failed_in_category", [True, False])
def test_b_no_eligible_offer_explains_why(cur, has_failed_in_category):
    cid = one(cur, """SELECT MIN(n.CUSTOMER_ID) FROM ACTION360_DB.CORE.NBA_CANDIDATE n
                      WHERE n.ELIGIBLE_RANK = 1 AND n.OFFER_MODE = 'OPTIONAL' AND n.SELECTED_OFFER IS NULL
                        AND (ARRAY_SIZE(n.INELIGIBLE_OFFERS) > 0) = %s""", (has_failed_in_category,))[0]
    assert cid, "expected at least one such customer in the synthetic book"
    c = offers(cur, cid)
    assert c["offer"] is None and c["offer_status"] == k.NO_ELIGIBLE_OFFER
    assert k.headline_for_no_offer(c) == "No eligible offer found"
    assert ("failed hard eligibility rules" if has_failed_in_category else "catalogue has no") in c["offer_status_reason"]


def test_servicing_action_has_no_offer_required(cur):
    c = offers(cur, "C11024")
    assert c["recommended_action"] == "CLAIM_FOLLOW_UP" and c["offer"] is None and c["offer_status"] == k.NO_OFFER_REQUIRED
    assert c["offer_status_reason"]


def test_c_multiple_offers_one_recommended_ordered_no_duplicates(cur):
    c = offers(cur, "C10238")
    ids = [o["offer_id"] for o in c["candidate_offers"]]
    assert len(ids) == len(set(ids))
    assert sum(o["is_recommended"] for o in c["candidate_offers"]) == 1 and c["candidate_offers"][0]["is_recommended"]
    assert len(c["alternatives"]) >= 2 and all(o["eligibility_status"] == k.ELIGIBLE for o in c["alternatives"])
    prios = [o["priority"] for o in c["alternatives"]]
    assert prios == sorted(prios, reverse=True)
    order = [o["eligibility_status"] for o in c["candidate_offers"][1:]]
    assert order == sorted(order, key=[k.ELIGIBLE, k.NEEDS_REVIEW, k.NOT_ELIGIBLE, k.UNAVAILABLE].index)


def test_f_ineligible_offer_shown_with_reason_never_recommended(cur):
    c = offers(cur, "C10238")
    h = next(o for o in c["candidate_offers"] if o["offer_id"] == "OFF_HARDSHIP_PLAN")
    assert h["eligibility_status"] == k.NOT_ELIGIBLE and not h["is_recommended"] and h["failed_rules"]
    assert k.format_offer_for_ui(h)["status_text"] == "✕ Not eligible"


def test_recommended_offer_is_eligible_for_every_customer(cur):
    bad = one(cur, """SELECT COUNT(*) FROM ACTION360_DB.CORE.NBA_CANDIDATE n
                      LEFT JOIN ACTION360_DB.CORE.OFFER_ELIGIBILITY e
                        ON e.CUSTOMER_ID = n.CUSTOMER_ID AND e.OFFER_ID = n.SELECTED_OFFER:offer_id::STRING
                      WHERE n.ELIGIBLE_RANK = 1 AND n.SELECTED_OFFER IS NOT NULL AND COALESCE(e.IS_ELIGIBLE, FALSE) = FALSE""")[0]
    assert bad == 0


def test_contract_valid_for_random_sample(cur):
    cur.execute("SELECT CUSTOMER_ID FROM ACTION360_DB.CORE.CUSTOMER_360 ORDER BY HASH(CUSTOMER_ID, 7) LIMIT 25")
    for (cid,) in cur.fetchall():
        c = offers(cur, cid)
        assert c["ok"] and c["offer_status"] in k.OFFER_STATUSES and c["offer_status"] != k.NEEDS_REVIEW, (cid, c["issues"])
        assert c["offer_status_reason"], cid
        assert not [i for i in c["issues"] if "duplicate" in i or "dropped" in i], (cid, c["issues"])


def test_unknown_and_messy_customer_ids(cur):
    assert offers(cur, "C99999")["error_code"] == "NOT_FOUND"
    assert offers(cur, "  c10238 ")["offer"]["offer_id"] == "OFF_FEE_WAIVER"


def test_check_offer_eligibility_helper(cur):
    r = k.parse_eligibility_check(proc(cur, "CALL ACTION360_DB.AI.CHECK_OFFER_ELIGIBILITY(%s, %s)", ("C10238", "OFF_TOPUP_LOAN")),
                                  "C10238", "OFF_TOPUP_LOAN")
    assert r["status"] == k.NOT_ELIGIBLE and "complaint" in r["reason"].lower()
    r = k.parse_eligibility_check(proc(cur, "CALL ACTION360_DB.AI.CHECK_OFFER_ELIGIBILITY(%s, %s)", ("C10238", "OFF_RATE_MATCH")),
                                  "C10238", "OFF_RATE_MATCH")
    assert r["status"] == k.ELIGIBLE


def test_audit_logs_eligible_alternative_and_blocks_ineligible(cur):
    rec = proc(cur, "CALL ACTION360_DB.AI.CALCULATE_NEXT_BEST_ACTION('C10238', 'pytest offer audit')")
    ok = proc(cur, "CALL ACTION360_DB.AI.LOG_ACTION(%s, 'DEFERRED', 'OFF_RATE_MATCH', 'pytest alt offer')", (rec["recommendation_id"],))
    assert ok["logged"] is True
    row = one(cur, "SELECT OFFER_ID, ELIGIBILITY_STATUS FROM ACTION360_DB.CORE.ACTION_AUDIT WHERE RECOMMENDATION_ID=%s "
                   "ORDER BY ACTED_AT DESC LIMIT 1", (rec["recommendation_id"],))
    assert row == ("OFF_RATE_MATCH", "ELIGIBLE")
    blocked = proc(cur, "CALL ACTION360_DB.AI.LOG_ACTION(%s, 'APPROVED', 'OFF_HARDSHIP_PLAN', 'pytest')", (rec["recommendation_id"],))
    assert blocked["logged"] is False
