# ACTION360: 5-minute demo script

Before you start, open Snowsight → Projects → Streamlit → **ACTION360_APP**. The sidebar holds the Customer ID box and the "Demo personas" list.

```
QUESTION ↓ CUSTOMER 360 ↓ EVIDENCE ↓ NEXT BEST ACTION ↓ PERSONALIZED OUTREACH ↓ AUDIT
```
The breadcrumb at the top of each page shows where you are in this flow.

| Time | Step | What to click / say |
|---|---|---|
| 0:00 | **1. Executive overview** | "10,000 customers across lending and insurance. 1.3k are high risk and 5.3k need action." Point to the risk-by-segment and action-mix charts and the cost-aware routing panel: "87% of customers never touch an LLM." |
| 0:40 | **2. Select a high-risk customer** | In the worklist, filter HIGH and click a row, or type **C10238** (Arjun Mehta, Premier). |
| 0:55 | **3. Customer 360** | Show the profile, the 3 products, the INR 1.1 Cr home loan, the rate reset in 21 days, 3 complaints with all unresolved, and negative sentiment. Point out the **FACT** vs **AI INTERPRETATION** tags and the top drivers with their weight contributions. |
| 1:30 | **4. Ask ACTION360** | Click "Why is C10238 high risk?" The agent calls get_customer_360 → search_customer_interactions → knowledge search. |
| 2:00 | **5. Structured evidence** | Read the facts in the answer: complaints, competitor mention, reset date. |
| 2:10 | **6. Transcript evidence** | Interaction timeline → click IC10238-5 or IC10238-6 to show the transcript. IC10238-6 was **transcribed from audio by AI_TRANSCRIBE** with speaker labels. |
| 2:40 | **7. "What should we do next?"** | Next best action → **Calculate next best action**. |
| 2:55 | **8. Candidate actions** | Expand "All candidate actions". Point out RETENTION_OFFER ranked lower (the "service before price" weight of -0.30) and PRODUCT_UPGRADE blocked by a guardrail. |
| 3:15 | **9. Recommendation and rationale** | **Service recovery**, OFF_FEE_WAIVER, ELIGIBLE, with the hard rules listed. WHY shows signal × weight; WHY NOW shows the reset date and competitor mention. "The LLM did not make this decision." |
| 3:40 | **10. Generate outreach** | Click **Generate outreach**. The call script opens with an apology, cites SR-48211 and the 23-Oct reset, and flags evidence gaps. |
| 4:05 | **11. Approve & log** | Approve & log action → APPROVED → Confirm. The status reads "SIMULATED: task queued for Relationship Manager". Optional: request OFF_RETENTION_CASHBACK for C10417 to show it **BLOCKED**. |
| 4:20 | **12. Audit trail** | Action history: an immutable record with evidence references, user, role and hash chain. |
| 4:35 | **13. AI & cost** | Calls made vs calls avoided, tokens, latency, metered credits (about 6.6 credits total). |
| 4:50 | **14. Low-risk routing** | Select persona **C10901** → Next best action. The result is "No action - monitor" with RULES_ONLY routing. Generate outreach shows **LLM skipped**. |

If you have spare time, show these:

* C10417: payment-plan discussion, with the retention cashback shown as not eligible.
* C10789: newborn → coverage review → family floater.
* The Evaluation page: 11/11.

**Fallback:** if the agent is slow (it takes 30–55 s), the Next best action page does not depend on it. It calls the same governed tools directly, in about 3 s.
