"""Run the ACTION360 evaluation benchmark and persist results to CORE.EVALUATION_RESULT.

Usage: python tests/run_evaluation.py [--with-outreach] [--with-agent]
  --with-outreach  also generate LLM outreach for positive cases and check grounding (small cost)
  --with-agent     also run the Cortex Agent on negative cases and check it refuses (small cost)
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from run_sql import connect  # noqa: E402
from ask_agent import ask, summarize  # noqa: E402


def call(cur, sql, args):
    cur.execute(sql, args)
    v = cur.fetchone()[0]
    return json.loads(v) if isinstance(v, str) else v


def main(with_outreach: bool, with_agent: bool):
    cur = connect().cursor()
    cur.execute("SELECT CASE_ID, SCENARIO, CUSTOMER_ID, QUESTION, EXPECTED_ACTION, EXPECTED_OFFER_ID, EXPECTED_ELIGIBILITY, "
                "FORBIDDEN_OFFER_ID, EXPECTED_ROUTE, MUST_CITE, IS_NEGATIVE FROM ACTION360_DB.CORE.EVALUATION_CASE ORDER BY CASE_ID")
    cases = cur.fetchall()
    cur.execute("SELECT c.CUSTOMER_ID FROM ACTION360_DB.CORE.DIM_CUSTOMER c LEFT JOIN ACTION360_DB.CORE.FACT_INTERACTION i "
                "USING (CUSTOMER_ID) WHERE i.CUSTOMER_ID IS NULL ORDER BY 1 LIMIT 1")
    no_ix = cur.fetchone()[0]
    rows = []
    for (case_id, scen, cid, qn, exp_action, exp_offer, exp_elig, forbidden, exp_route, must_cite, neg) in cases:
        cid = no_ix if cid == "__NO_INTERACTIONS__" else cid
        t0 = time.time()
        nba = call(cur, "CALL ACTION360_DB.AI.CALCULATE_NEXT_BEST_ACTION(%s, %s)", (cid, qn))
        lat = round(time.time() - t0, 2)
        notes, grounded = [], None
        if not nba.get("found"):
            ok = exp_elig == "CUSTOMER NOT FOUND"
            rows.append((case_id, scen, cid, exp_action, None, None, ok, ok, ok, None, ok, None, None, lat, nba.get("message")))
            continue
        action, offer = nba["selected_action"], (nba.get("offer") or {}).get("offer_id")
        action_ok = exp_action is None or action == exp_action
        # eligibility correctness: expected offer selected AND forbidden offer is rejected by the rules tool
        elig_ok = (exp_offer is None or offer == exp_offer)
        if forbidden:
            chk = call(cur, "CALL ACTION360_DB.AI.CHECK_OFFER_ELIGIBILITY(%s, %s)", (cid, forbidden))
            forb_status = (chk.get("offers") or [{}])[0].get("eligibility", chk.get("eligibility"))
            elig_ok = elig_ok and forb_status == "NOT ELIGIBLE" and offer != forbidden
            notes.append(f"{forbidden}: {forb_status}")
        # consistency: deterministic engine must return the same decision twice
        nba2 = call(cur, "CALL ACTION360_DB.AI.CALCULATE_NEXT_BEST_ACTION(%s, %s)", (cid, qn))
        consistent = nba2["selected_action"] == action and (nba2.get("offer") or {}).get("offer_id") == offer
        ev = nba["evidence"]
        ix_ids = [e.get("DOC_ID") for e in (ev.get("interaction_evidence") or []) if isinstance(e, dict)]
        kb_ids = [e.get("CHUNK_ID") for e in (ev.get("policy_evidence") or []) if isinstance(e, dict)]
        if must_cite:
            cited = any(i and i.startswith(must_cite) for i in ix_ids) and (nba["ai_route"] == "RULES_ONLY" or len(kb_ids) > 0)
        else:
            cited = len(ev.get("structured_facts") or []) > 0
        if case_id == "N05":
            action_ok = not ix_ids and nba["confidence"] in ("LOW", "MEDIUM", "HIGH")
            notes.append(f"no interaction evidence; confidence {nba['confidence']}")
        if exp_route and nba["ai_route"] != exp_route:
            notes.append(f"route {nba['ai_route']} != expected {exp_route}")
        if case_id == "N01":  # attempt to log an ineligible offer must be blocked
            res = call(cur, "CALL ACTION360_DB.AI.LOG_ACTION(%s, 'APPROVED', %s, 'evaluation negative test')",
                       (nba["recommendation_id"], forbidden))
            elig_ok = elig_ok and res.get("user_action") == "BLOCKED_INELIGIBLE_OFFER"
            notes.append(f"log attempt -> {res.get('user_action')}")
        if with_outreach and not neg and action != "NO_ACTION_MONITOR":
            out = call(cur, "CALL ACTION360_DB.AI.GENERATE_PERSONALIZED_OUTREACH(%s, '', FALSE)", (nba["recommendation_id"],))
            msg = (out.get("customer_message") or "").lower()
            inel = [x for x in (nba.get("ineligible_offers_in_category") or []) if x]
            grounded = (not out.get("guardrail_violation")) and bool(msg) and \
                not any(x["offer_name"].lower() in msg for x in inel)
        elif not neg and action == "NO_ACTION_MONITOR":
            out = call(cur, "CALL ACTION360_DB.AI.GENERATE_PERSONALIZED_OUTREACH(%s, '', FALSE)", (nba["recommendation_id"],))
            grounded = out.get("llm_used") is False
            notes.append("LLM skipped" if grounded else "LLM unexpectedly used")
        if with_agent and case_id in ("N01", "N03", "N04"):
            r = summarize(ask(cur, qn))
            txt = r["text"].lower()
            refused = ("not eligible" in txt or "does not exist" in txt or "not found" in txt or "cannot" in txt)
            grounded = refused
            notes.append(f"agent tools={r['tools']} refused={refused}")
        rows.append((case_id, scen, cid, exp_action, action, offer, action_ok, elig_ok, consistent, cited, grounded,
                     nba["confidence"], nba["ai_route"], lat, "; ".join(notes)))
        print(f"{case_id}: action={action} offer={offer} action_ok={action_ok} elig_ok={elig_ok} consistent={consistent} "
              f"cited={cited} grounded={grounded} {lat}s {'; '.join(notes)}")
    cur.execute("TRUNCATE TABLE ACTION360_DB.CORE.EVALUATION_RESULT")
    cur.executemany("INSERT INTO ACTION360_DB.CORE.EVALUATION_RESULT (CASE_ID, SCENARIO, CUSTOMER_ID, EXPECTED_ACTION, ACTUAL_ACTION, "
                    "ACTUAL_OFFER, ACTION_CORRECT, ELIGIBILITY_CORRECT, CONSISTENT, CITATION_COVERED, GROUNDED, CONFIDENCE, AI_ROUTE, "
                    "LATENCY_S, NOTES) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", rows)
    passed = sum(1 for r in rows if r[6] and r[7] and r[8] is not False)
    print(f"\n{passed}/{len(rows)} cases passed action+eligibility+consistency")
    return passed == len(rows)


if __name__ == "__main__":
    sys.exit(0 if main("--with-outreach" in sys.argv, "--with-agent" in sys.argv) else 1)
