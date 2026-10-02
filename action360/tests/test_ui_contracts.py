"""UI contract + customer-context tests (pure Python, no Snowflake): offer validation/formatting, NBA and agent
response parsing, selected-customer state, stale-data protection and navigation state."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import contracts as k  # noqa: E402
import state  # noqa: E402


def offer(oid, status="ELIGIBLE", rec=False, prio=50, **kw):
    return {"offer_id": oid, "offer_name": f"Offer {oid}", "description": "d", "category": "RETENTION", "priority": prio,
            "eligibility_status": status, "is_recommended": rec, "reason": f"reason {oid}",
            "passed_rules": ["r1"] if status == "ELIGIBLE" else [], "failed_rules": ["f1"] if status == "NOT_ELIGIBLE" else [], **kw}


def contract(cid="C10238", status="RECOMMENDED", rec="A", offers=None, reason="ok"):
    offers = offers if offers is not None else [offer("A", rec=True), offer("B"), offer("C", "NOT_ELIGIBLE")]
    return {"found": True, "customer_id": cid, "recommended_action": "SERVICE_RECOVERY", "action_name": "Service recovery",
            "offer_status": status, "offer_status_reason": reason,
            "offer": next((o for o in offers if o["offer_id"] == rec), None) if rec else None, "candidate_offers": offers}


# ------------------------------------------------------------------ offer contract
def test_recommended_offer_and_ordering():
    c = k.validate_offer_contract(contract(), "C10238")
    assert c["ok"] and c["offer"]["offer_id"] == "A" and c["offer"]["is_recommended"]
    assert [o["offer_id"] for o in c["candidate_offers"]] == ["A", "B", "C"]
    assert [o["offer_id"] for o in c["alternatives"]] == ["B"]          # TEST C: alternatives exclude the recommended one
    assert [o["offer_id"] for o in c["not_eligible"]] == ["C"]
    assert sum(o["is_recommended"] for o in c["candidate_offers"]) == 1


def test_json_string_and_case_whitespace_customer_id():
    c = k.validate_offer_contract(json.dumps(contract(cid="C10238")), "  c10238 ")
    assert c["ok"] and c["customer_id"] == "C10238"


def test_customer_mismatch_is_rejected():
    c = k.validate_offer_contract(contract(cid="C10417"), "C10238")
    assert not c["ok"] and c["error_code"] == "CUSTOMER_MISMATCH" and c["offer"] is None


def test_not_found_and_bad_format():
    assert k.validate_offer_contract({"found": False, "message": "Customer X does not exist."}, "X")["error_code"] == "NOT_FOUND"
    assert k.validate_offer_contract("not json", "C1")["error_code"] == "BAD_FORMAT"
    assert k.validate_offer_contract(None, "C1")["error_code"] == "BAD_FORMAT"


def test_no_eligible_offer_has_explanation_and_no_card():  # TEST B
    c = k.validate_offer_contract(contract(status="NO_ELIGIBLE_OFFER", rec=None, offers=[offer("C", "NOT_ELIGIBLE")],
                                           reason="All 1 SERVICE RECOVERY offer(s) failed"), "C10238")
    assert c["offer"] is None and c["offer_status"] == "NO_ELIGIBLE_OFFER"
    assert k.headline_for_no_offer(c) == "No eligible offer found" and "failed" in c["offer_status_reason"]
    assert k.format_offer_for_ui(c["offer"]) is None


def test_no_offer_reason_filled_when_missing():
    c = k.validate_offer_contract(contract(status="NO_OFFER_REQUIRED", rec=None, offers=[], reason=""), "C10238")
    assert c["offer_status_reason"] and k.headline_for_no_offer(c) == "No offer needed for this action"


def test_ineligible_offer_is_never_recommended():  # TEST F
    bad = offer("H", "NOT_ELIGIBLE", rec=True)
    c = k.validate_offer_contract(contract(rec="H", offers=[bad, offer("B")]), "C10238")
    assert c["offer"] is None and c["offer_status"] == k.NEEDS_REVIEW
    assert not any(o["is_recommended"] for o in c["candidate_offers"])
    assert k.headline_for_no_offer(c) == k.UNKNOWN_ELIGIBILITY
    assert k.format_offer_for_ui(c["candidate_offers"][0])["status_label"] in ("Not eligible", "Eligible")


def test_unknown_eligibility_is_needs_review_not_eligible():
    o, issues = k.validate_offer({**offer("X"), "eligibility_status": None, "reason": ""})
    assert o["eligibility_status"] == k.NEEDS_REVIEW and o["reason"] == k.UNKNOWN_ELIGIBILITY and issues
    assert k.format_offer_for_ui(o)["status_label"] == "Needs review"


def test_recommended_status_without_offer_details_is_needs_review():
    c = k.validate_offer_contract({**contract(), "offer": None}, "C10238")
    assert c["offer"] is None and c["offer_status"] == k.NEEDS_REVIEW


def test_invalid_offers_dropped_and_duplicates_removed():
    offers = [offer("A", rec=True), {"offer_id": "", "offer_name": "x"}, {"offer_id": "Z"}, offer("B"), offer("B"), "junk"]
    c = k.validate_offer_contract(contract(offers=offers), "C10238")
    assert [o["offer_id"] for o in c["candidate_offers"]] == ["A", "B"]
    assert any("duplicate" in i for i in c["issues"]) and any("offer_name" in i for i in c["issues"])


def test_non_numeric_priority_is_flagged():
    o, issues = k.validate_offer({**offer("A"), "priority": "high"})
    assert o["priority"] is None and any("priority" in i for i in issues)
    assert k.format_offer_for_ui(o)["priority"] == "-"


def test_format_offer_for_ui_eligible_and_not_eligible():
    f = k.format_offer_for_ui(k.validate_offer(offer("A"))[0])
    assert f["status_text"] == "✓ Eligible" and f["why_title"] == "Why eligible" and f["rules"] == ["r1"]
    g = k.format_offer_for_ui(k.validate_offer(offer("C", "NOT_ELIGIBLE"))[0])
    assert g["status_text"] == "✕ Not eligible" and g["why_title"] == "Why not eligible" and g["rules"] == ["f1"]
    # every status has a text label + icon, not only a colour
    assert all(label and icon for label, icon, _ in k.STATUS_META.values())


def test_parse_eligibility_check():
    raw = {"found": True, "customer_id": "C1", "offers": [{"offer_id": "A", "eligibility": "NOT ELIGIBLE", "failed_rules": ["x"]}]}
    assert k.parse_eligibility_check(raw, "c1", "a")["status"] == k.NOT_ELIGIBLE
    assert k.parse_eligibility_check({"found": True, "eligibility": "NOT ELIGIBLE", "reason": "n/a", "offers": None}, "C1", "Q")["status"] == k.NOT_ELIGIBLE
    assert k.parse_eligibility_check({"found": False, "message": "no"}, "C1", "A")["status"] == k.NEEDS_REVIEW


# ------------------------------------------------------------------ NBA + agent parsing
NBA = {"found": True, "customer_id": "C10238", "recommendation_id": "r1", "selected_action": "SERVICE_RECOVERY",
       "action_name": "Service recovery call (RM)", "action_score": "0.809", "confidence": "MEDIUM",
       "offer": {"offer_id": "off_fee_waiver"}, "reasons": [{"signal": "SERVICE_RISK", "value": 0.79, "weight": 0.4, "contribution": 0.32}, None],
       "evidence": {"structured_facts": ["a", None, "b"], "interaction_evidence": [{"DOC_ID": "I1"}, "x"], "policy_evidence": {}}}


def test_parse_nba_response():
    n = k.parse_nba_response(json.dumps(NBA), "c10238")
    assert n["ok"] and n["offer_id"] == "OFF_FEE_WAIVER" and n["action_score"] == pytest.approx(0.809)
    assert len(n["reasons"]) == 1 and n["facts"] == ["a", "b"] and n["interaction_evidence"] == [{"DOC_ID": "I1"}]
    assert n["policy_evidence"] == []


def test_parse_nba_rejects_other_customer_and_incomplete():
    assert not k.parse_nba_response(NBA, "C10417")["ok"]
    assert not k.parse_nba_response({**NBA, "recommendation_id": None}, "C10238")["ok"]
    assert not k.parse_nba_response({"found": False, "message": "nope"}, "C10238")["ok"]
    assert k.parse_nba_response({**NBA, "confidence": "weird"}, "C10238")["confidence"] == "UNKNOWN"


def test_parse_agent_response():
    resp = {"content": [{"type": "text", "text": "Hello"}, {"type": "tool_use", "tool_use": {"name": "nba"}},
                        {"type": "tool_result", "tool_result": {"x": 1}}, {"type": "text", "text": "world"}, "junk"]}
    r = k.parse_agent_response(json.dumps(resp))
    assert r["text"] == "Hello\nworld" and r["tools"] == ["nba"] and r["tool_results"] == [{"x": 1}]
    assert k.parse_agent_response("plain text")["text"] == "plain text"
    assert k.parse_agent_response({"content": None})["text"] == ""


# ------------------------------------------------------------------ customer context state
def test_selection_and_persistence_across_reruns():
    ss = {}
    state.init_state(ss)
    assert state.get_selected_customer_id(ss) is None
    assert state.select_customer(ss, " c10238 ", {"customer_id": "C10238", "name": "R"})
    state.init_state(ss)                                    # TEST E: a rerun re-runs init - selection survives
    assert state.get_selected_customer_id(ss) == "C10238" and state.get_selected_customer(ss)["name"] == "R"
    assert not state.select_customer(ss, "C10238")          # re-selecting the same customer is a no-op


def test_restore_from_url_only_when_empty():
    ss = {}
    state.init_state(ss, "c10417")
    assert state.get_selected_customer_id(ss) == "C10417"
    state.init_state(ss, "C99999")                          # an existing selection is not overwritten by the URL
    assert state.get_selected_customer_id(ss) == "C10417"


def test_switching_customer_clears_scoped_results():  # TEST D
    ss = {}
    state.init_state(ss)
    state.select_customer(ss, "C10238", {"customer_id": "C10238"})
    state.set_scoped(ss, "nba", {"recommendation_id": "r1"})
    state.set_scoped(ss, "outreach", {"customer_message": "hi A"})
    assert state.get_scoped(ss, "nba")["recommendation_id"] == "r1"
    nonce = ss[state.NONCE]
    state.select_customer(ss, "C10417", {"customer_id": "C10417"})
    assert state.get_scoped(ss, "nba") is None and state.get_scoped(ss, "outreach") is None
    assert state.get_selected_customer(ss)["customer_id"] == "C10417"
    assert ss[state.NONCE] == nonce + 1                     # list widgets reset -> no stale row re-selects customer A


def test_scoped_value_from_other_customer_is_never_returned():
    ss = {}
    state.init_state(ss)
    state.select_customer(ss, "C10238")
    state.set_scoped(ss, "nba", {"x": 1})
    ss[state.SELECTED_ID] = "C10417"                        # simulate a bypass of select_customer
    assert state.get_scoped(ss, "nba") is None


def test_header_for_other_customer_is_ignored():
    ss = {}
    state.init_state(ss)
    state.select_customer(ss, "C10238", {"customer_id": "C10417"})
    assert state.get_selected_customer(ss) is None


def test_list_selection_does_not_bump_nonce_and_clear_selection():
    ss = {}
    state.init_state(ss)
    state.select_customer(ss, "C1", from_list=True)
    assert ss[state.NONCE] == 0
    state.clear_selection(ss)
    assert state.get_selected_customer_id(ss) is None and state.get_selected_customer(ss) is None
