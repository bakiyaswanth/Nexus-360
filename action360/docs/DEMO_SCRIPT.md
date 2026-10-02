# ACTION360: 5-minute demo script

Before you start, open Snowsight → Projects → Streamlit → **ACTION360_APP**. The sidebar holds the page navigation: Workspace / Customer / Operations / Copilot. Once a customer is selected, a **context bar** sits at the top of every page with that customer's name, ID, risk, sentiment, value and renewal, plus buttons for Customer 360 · Next best action · Offers · Interactions · switch · clear.

```
DASHBOARD → SELECT CUSTOMER → CUSTOMER 360 → NEXT BEST ACTION (+ OFFER) → OUTREACH → APPROVE & LOG → AUDIT
```

| Time | Step | What to click / say |
|---|---|---|
| 0:00 | **1. Dashboard** | "10,000 customers across lending and insurance. 1.3k are high risk and 5.3k need action." Point to the risk-by-segment and action-mix charts and the cost-aware routing panel: "87% of customers never touch an LLM." |
| 0:40 | **2. Select a high-risk customer** | Click the worklist row, the **C10238** persona pill, or search "C10238" (Arjun Mehta, Premier). The context bar appears. |
| 0:55 | **3. Customer 360** | Context bar → **Customer 360**. Show the KPI row (INR 4.69 L value, high risk, negative sentiment, renewal in 21 days, 3 open issues), the 3 accounts, the key drivers, recent interactions and the AI summary. At the bottom, the NBA preview already shows the fee-waiver offer as **✓ Eligible**. |
| 1:30 | **4. Ask ACTION360** | Click "Why is C10238 high risk?" The agent calls get_customer_360 → search_customer_interactions → knowledge search. |
| 2:00 | **5. Structured evidence** | Read the facts in the answer: complaints, competitor mention, reset date. |
| 2:10 | **6. Transcript evidence** | Context bar → **Interactions** → click IC10238-5 or IC10238-6 to show the transcript. IC10238-6 was **transcribed from audio by AI_TRANSCRIBE** with speaker labels. |
| 2:40 | **7. "What should we do next?"** | Context bar → **Next best action**. The engine runs automatically and the action, offer and buttons appear in about 3 s. |
| 2:55 | **8. Candidate actions** | Expand "All candidate actions". Point out RETENTION_OFFER ranked lower (the "service before price" weight of -0.30) and PRODUCT_UPGRADE blocked by a guardrail. |
| 3:15 | **9. Recommendation and offer** | **Service recovery** (confidence, score). The dominant offer card shows **Annual card fee waiver (goodwill) · ✓ Eligible**: why eligible (hard rules), business purpose, expected outcome and evidence. Below it are three other eligible options, and "Not eligible (3)" with the failed rule for each. "The LLM did not make this decision." |
| 3:40 | **10. Generate outreach** | Click **Generate outreach**. The call script opens with an apology, cites SR-48211 and the 23-Oct reset, and flags evidence gaps. |
| 4:05 | **11. Approve & log** | Approve & log action → APPROVED → Confirm. The status reads "SIMULATED: task queued for Relationship Manager". Optional: pick an ineligible offer (e.g. Pre-approved top-up loan) in the Offer box to show it **BLOCKED**. |
| 4:20 | **12. Audit trail** | Actions & audit: an immutable record with evidence references, user, role and hash chain. Toggle "Only C10238". |
| 4:35 | **13. AI & cost** | Calls made vs calls avoided, tokens, latency, metered credits (about 6.6 credits total). |
| 4:50 | **14. Low-risk routing and no-offer state** | Switch (⇄) → persona **C10901** → Next best action. The result is "No action - monitor" with RULES_ONLY routing; the offer card says **"No offer needed for this action"** and why. Generate outreach shows **LLM skipped**. |

If you have spare time, show these:

* C10417: payment-plan discussion with the hardship plan; switching customers clears every result from C10238.
* C10789: newborn → coverage review → family floater.
* C10027: service recovery where the fee waiver failed its hard rules, so the page reads "No eligible offer found" plus the failed rules.
* The **Offers** page: every catalogue offer with ✓ / ✕ / ? status, its reason, and a live eligibility check.
* The Evaluation page: 11/11.

**Fallback:** if the agent is slow (it takes 30–55 s), the Next best action page does not depend on it. It calls the same governed tools directly, in about 3 s.
