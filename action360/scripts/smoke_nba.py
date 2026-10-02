"""Quick end-to-end smoke test of the decision tools for one customer."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from run_sql import connect  # noqa: E402

cid = sys.argv[1] if len(sys.argv) > 1 else "C10238"
cur = connect().cursor()
cur.execute("CALL ACTION360_DB.AI.CALCULATE_NEXT_BEST_ACTION(%s, %s)", (cid, "What should we do next?"))
nba = json.loads(cur.fetchone()[0])
print(json.dumps({k: nba.get(k) for k in ("selected_action", "offer", "confidence", "ai_route", "eligibility")}, indent=1)[:1500])
print("evidence ids:", [e.get("DOC_ID") for e in nba["evidence"]["interaction_evidence"] or []],
      [e.get("CHUNK_ID") for e in nba["evidence"]["policy_evidence"] or []])
cur.execute("CALL ACTION360_DB.AI.GENERATE_PERSONALIZED_OUTREACH(%s, %s, FALSE)", (nba["recommendation_id"], ""))
out = json.loads(cur.fetchone()[0])
print(json.dumps(out, indent=1)[:2500])
cur.execute("CALL ACTION360_DB.AI.LOG_ACTION(%s, 'APPROVED', NULL, 'smoke test')", (nba["recommendation_id"],))
print(cur.fetchone()[0])
