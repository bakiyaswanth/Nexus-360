# ACTION360 Architecture

## Layers

```
RAW            DOCS_STAGE (policy docs) · AUDIO_STAGE (call recordings) · CUSTOMER_ARCHETYPE (hidden ground truth)
  │            AI_TRANSCRIBE (speaker diarization) ──► CALL_TRANSCRIPT
CURATED        DIM_CUSTOMER · DIM_PRODUCT · FACT_ACCOUNT · FACT_PRODUCT_HOLDING · FACT_PAYMENT · FACT_TRANSACTION
  │            FACT_CLAIM_OR_LOAN_EVENT · FACT_INTERACTION · CALL_TRANSCRIPT · KNOWLEDGE_DOCUMENT/_CHUNK
AI SIGNALS     ENRICH_TRANSCRIPTS (AI_SENTIMENT + AI_CLASSIFY, cost-routed) · stream + task for new transcripts
  │
SIGNALS (DT)   CUSTOMER_FEATURES ─► CUSTOMER_SIGNAL (25 normalised signals) ─► CUSTOMER_RISK (weights in RISK_MODEL_WEIGHT)
DECISION (DT)  OFFER_ELIGIBILITY (41 hard rules) ─► NBA_CANDIDATE (NBA_WEIGHT × signals, NBA_GUARDRAIL) 
CUSTOMER 360   CUSTOMER_360 (DT, 12h lag) + CUSTOMER_AI_INSIGHT (LLM summary, FULL_AGENT only)
SEMANTIC       CUSTOMER_360_SV (semantic view, verified queries) ─► Cortex Analyst
SEARCH         INTERACTION_SEARCH (filter by CUSTOMER_ID, sentiment, intent…) · KNOWLEDGE_SEARCH (doc type, industry, offer)
TOOLS          AI.GET_CUSTOMER_360 · AI.CHECK_OFFER_ELIGIBILITY · AI.CALCULATE_NEXT_BEST_ACTION
               AI.GENERATE_PERSONALIZED_OUTREACH · AI.LOG_ACTION · AI.SEARCH_SERVICE
AGENT          ACTION360_AGENT (claude-sonnet-4-6 orchestration; Analyst + 2 Search + 5 custom tools)
APP            ACTION360_APP (Streamlit in Snowflake, container runtime)
AUDIT          NBA_RECOMMENDATION · ACTION_AUDIT (append-only, SHA-256 hash chain) · AI_USAGE_METRICS · EVALUATION_RESULT
```

## Why Snowflake is more than the database here

Every step runs inside the Snowflake governance boundary:

* transcription
* sentiment and intent extraction
* semantic search
* text-to-SQL over governed definitions
* LLM generation
* rule evaluation
* agent orchestration
* the UI
* the audit trail

No data leaves the account, and no external LLM API is used. RBAC governs both data and AI: the `ACTION360_ANALYST` role can read and call tools, but it cannot write to the audit table directly.

## Decision separation

| Layer | Who decides | Labelled in UI |
|---|---|---|
| Facts (balances, payments, eligibility, events) | Tables / rules | `FACT` |
| Interpretation (need, pain points, sentiment, intent) | AI_SENTIMENT / AI_CLASSIFY / claude-haiku | `AI INTERPRETATION` |
| Recommendation (action, offer, eligibility) | NBA engine (weights, guardrails, rules) | `RECOMMENDATION · deterministic` |
| Personalised message and talking points | claude-sonnet-4-6, given the locked decision | `AI-GENERATED PERSONALISATION` |

The LLM cannot change the decision, and two checks enforce that:

1. The prompt receives the decision as FINAL, plus a list of the offers the customer is **not** eligible for.
2. A post-generation guardrail withholds any message that names an ineligible offer.
3. `LOG_ACTION` re-checks eligibility at write time. A requested ineligible offer is recorded as `BLOCKED_INELIGIBLE_OFFER`.

## Agent orchestration (instructions enforce this order)

1. Identify the customer, then call `get_customer_360` (stop if `found=false`).
2. Call `search_customer_interactions`, filtered by `CUSTOMER_ID`.
3. Call `search_product_policy_offer_knowledge`.
4. Call `check_offer_eligibility` for any offer that is discussed.
5. Call `calculate_next_best_action`. The decision it returns is final.
6. Call `generate_personalized_outreach` only when the user asks for a message.
7. Call `log_action` only on explicit approval.

Portfolio questions go to `query_customer_metrics` (Cortex Analyst on the semantic view).

## Production-readiness features

* **Declarative pipeline:** dynamic tables (`DOWNSTREAM` lag) and a single scheduled refresh point on CUSTOMER_360.
* **Event-driven enrichment:** a stream on CALL_TRANSCRIPT feeds a task with a `SYSTEM$STREAM_HAS_DATA` guard. The task costs nothing when there is no new data.
* **Configuration, not code:** all thresholds, models and weights live in tables (APP_CONFIG, RISK_MODEL_WEIGHT, NBA_WEIGHT, NBA_GUARDRAIL, OFFER_ELIGIBILITY_RULE).
* **Error handling:** `found=false` contracts, a whitelisted search wrapper, a single retry on transient errors in the app, and a deterministic fallback when the agent is unavailable.
* **Cost limits:** an XS warehouse with 60 s auto-suspend and a 60-credit resource monitor.
* **Testing:** 34 automated tests and an 11-case evaluation benchmark.

## Feature availability (verified in this account, Azure Central India)

| Feature | Status |
|---|---|
| AI_COMPLETE, AI_SENTIMENT, AI_CLASSIFY, AI_EXTRACT, AI_COUNT_TOKENS | available (cross-region inference ANY_REGION) |
| AI_TRANSCRIBE | not listed for this region in the docs, but **works via cross-region inference**. It was tested with speaker diarization. |
| CREATE AI FUNCTION (AI Function Studio) | available. Built in Studio "Direct" mode by hand-writing the DDL, because the Studio builder script and `uv` are not installed locally. |
| Cortex Search, semantic views, Cortex Agents (DATA_AGENT_RUN) | available |
| Streamlit container runtime | available (SYSTEM_COMPUTE_POOL_CPU) |
| `snow` / `cortex` CLI | not installed. Deployment uses the Python connector and SQL instead. |
