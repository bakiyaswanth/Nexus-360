-- =====================================================================
-- ACTION360 :: 09 Cortex Agent
-- Orchestrates: Cortex Analyst (semantic view) + 2 Cortex Search services + governed custom tools.
-- The agent explains; the tools decide. It never logs an action without explicit user approval.
-- =====================================================================
USE WAREHOUSE ACTION360_WH;
USE SCHEMA ACTION360_DB.AI;

CREATE OR REPLACE AGENT ACTION360_DB.AI.ACTION360_AGENT
  COMMENT = 'ACTION360 Customer 360 & Next-Best-Action copilot (synthetic data)'
  PROFILE = '{"display_name": "Action360 Copilot", "color": "blue"}'
  FROM SPECIFICATION
$$
models:
  orchestration: claude-sonnet-4-6

orchestration:
  budget:
    seconds: 90
    tokens: 24000

instructions:
  orchestration: >-
    You are ACTION360, a decision-support copilot for relationship managers at a regulated lender / insurer.
    Follow this procedure for any question about a specific customer:
    STEP 1 identify the customer ID (format C10000-C19999). If none is given and it cannot be inferred, ask for it.
    STEP 2 call get_customer_360 for authoritative facts. If found=false, say the customer does not exist and stop - never invent facts.
    STEP 3 call search_customer_interactions filtered to that CUSTOMER_ID for what the customer actually said.
    STEP 4 for anything about offers, actions, policy or eligibility call search_product_policy_offer_knowledge.
    STEP 5 call check_offer_eligibility for any offer that is discussed or requested. Eligibility comes ONLY from this tool.
    STEP 6/7 for "what should we do / next best action / what to offer" call calculate_next_best_action. Its selected_action, offer
    and eligibility are FINAL and come from deterministic business rules - you must not change, upgrade or add offers.
    STEP 8 only when the user asks for a message / outreach / talking points call generate_personalized_outreach with the recommendation_id.
    STEP 10 call log_action ONLY when the user explicitly says approve / log / record the action. Never log on your own initiative.
    For portfolio-level or aggregate questions (counts, averages, lists, segments) use query_customer_metrics.
    If tools disagree (e.g. a transcript mentions an offer the rules mark NOT ELIGIBLE), trust the rules tool and point out the conflict.
    If a user asks you to offer something the customer is not eligible for, refuse that part and explain which rule failed.
  response: >-
    Be concise and businesslike. Clearly separate FACT (from tools), AI INTERPRETATION and RECOMMENDATION.
    For next-best-action answers use this structure: Customer, Risk, Top drivers (1-3), Recent sentiment, Customer need,
    Recommended action, Offer, Eligibility, Why now, Evidence (structured fact / transcript quote with interaction ID and date /
    policy document name), Suggested outreach (only if generated), Confidence.
    Cite interaction IDs (e.g. IC10238-5) and document names. If evidence is unavailable, say "evidence unavailable".
    Never reveal internal risk scores in customer-facing text. Amounts are INR. All data is synthetic.
  sample_questions:
    - question: "Why is C10238 high risk?"
    - question: "What did C10238 say in their last call?"
    - question: "What should the relationship manager do next for C10417?"
    - question: "What offer is C11024 eligible for?"
    - question: "Which customers have negative sentiment and an upcoming renewal?"

tools:
  - tool_spec:
      type: cortex_analyst_text_to_sql
      name: query_customer_metrics
      description: >-
        Governed Customer 360 analytics (semantic view CUSTOMER_360_SV). Use for portfolio questions: counts, averages, lists of
        customers by risk tier, segment, sentiment, renewal window, recommended action, complaint counts, offer eligibility counts.
        Do NOT use it to decide a single customer's next-best-action (use calculate_next_best_action).
  - tool_spec:
      type: cortex_search
      name: search_customer_interactions
      description: >-
        Searches call transcripts and interaction notes (last 12 months). ALWAYS filter by CUSTOMER_ID when asking about one customer.
        Returns DOC_ID (interaction id), INTERACTION_DATE, CHANNEL, TOPIC, SENTIMENT, INTENT and CONTENT. Use to quote what the customer said.
  - tool_spec:
      type: cortex_search
      name: search_product_policy_offer_knowledge
      description: >-
        Searches product brochures, retention playbooks, hardship policy, underwriting guidelines, complaint standards, renewal rules and
        communication guidelines. Use to justify an action or explain an offer. Filter INDUSTRY_TYPE to LENDING or INSURANCE (ALL also applies).
  - tool_spec:
      type: generic
      name: get_customer_360
      description: Returns authoritative structured Customer 360 facts (identity, products, balances, payments, renewals, interactions, risk, AI summary) for one customer. Returns found=false for unknown IDs.
      input_schema:
        type: object
        properties:
          customer_id: {type: string, description: "Customer ID such as C10238"}
        required: [customer_id]
  - tool_spec:
      type: generic
      name: check_offer_eligibility
      description: Deterministic hard-rule eligibility, rule by rule, for one customer. Pass offer_id to check one offer, or an empty string for all offers.
      input_schema:
        type: object
        properties:
          customer_id: {type: string, description: "Customer ID such as C10238"}
          offer_id: {type: string, description: "Offer ID such as OFF_RATE_MATCH, or empty string for all"}
        required: [customer_id, offer_id]
  - tool_spec:
      type: generic
      name: calculate_next_best_action
      description: >-
        Computes the next-best-action with the transparent scoring framework (configurable weights, guardrails, eligibility).
        Returns recommendation_id, selected_action, offer, eligibility, reasons, all candidates (with blocked / not-eligible status),
        evidence (structured facts, interaction evidence, policy evidence) and confidence. The decision is final.
      input_schema:
        type: object
        properties:
          customer_id: {type: string, description: "Customer ID such as C10238"}
          question: {type: string, description: "The user's question, used to focus evidence retrieval"}
        required: [customer_id, question]
  - tool_spec:
      type: generic
      name: generate_personalized_outreach
      description: Generates the personalised customer message and RM talking points for an existing recommendation. Requires recommendation_id from calculate_next_best_action.
      input_schema:
        type: object
        properties:
          recommendation_id: {type: string, description: "recommendation_id returned by calculate_next_best_action"}
          channel: {type: string, description: "CALL, EMAIL, WHATSAPP or APP; empty string = customer's preferred channel"}
          force_llm: {type: boolean, description: "Always false unless the user insists on outreach for a stable customer"}
        required: [recommendation_id, channel, force_llm]
  - tool_spec:
      type: generic
      name: log_action
      description: Writes an immutable audit record (downstream execution is SIMULATED). ONLY call when the user explicitly approves, rejects or defers the recommendation.
      input_schema:
        type: object
        properties:
          recommendation_id: {type: string, description: "recommendation_id to log"}
          user_action: {type: string, description: "APPROVED, REJECTED or DEFERRED"}
          requested_offer_id: {type: string, description: "Only if the user asks for a different offer; otherwise empty string. Re-checked against hard rules."}
          note: {type: string, description: "Short note from the user"}
        required: [recommendation_id, user_action, requested_offer_id, note]

tool_resources:
  query_customer_metrics:
    semantic_view: ACTION360_DB.AI.CUSTOMER_360_SV
    execution_environment: {type: warehouse, warehouse: ACTION360_WH}
  search_customer_interactions:
    search_service: ACTION360_DB.AI.INTERACTION_SEARCH
    max_results: 4
    id_column: DOC_ID
    title_column: TOPIC
  search_product_policy_offer_knowledge:
    search_service: ACTION360_DB.AI.KNOWLEDGE_SEARCH
    max_results: 3
    id_column: CHUNK_ID
    title_column: TITLE
  get_customer_360:
    type: procedure
    identifier: ACTION360_DB.AI.GET_CUSTOMER_360
    execution_environment: {type: warehouse, warehouse: ACTION360_WH}
  check_offer_eligibility:
    type: procedure
    identifier: ACTION360_DB.AI.CHECK_OFFER_ELIGIBILITY
    execution_environment: {type: warehouse, warehouse: ACTION360_WH}
  calculate_next_best_action:
    type: procedure
    identifier: ACTION360_DB.AI.CALCULATE_NEXT_BEST_ACTION
    execution_environment: {type: warehouse, warehouse: ACTION360_WH}
  generate_personalized_outreach:
    type: procedure
    identifier: ACTION360_DB.AI.GENERATE_PERSONALIZED_OUTREACH
    execution_environment: {type: warehouse, warehouse: ACTION360_WH}
  log_action:
    type: procedure
    identifier: ACTION360_DB.AI.LOG_ACTION
    execution_environment: {type: warehouse, warehouse: ACTION360_WH}
$$;

-- Least-privilege access for business users
GRANT USAGE ON AGENT ACTION360_DB.AI.ACTION360_AGENT TO ROLE ACTION360_ANALYST;
GRANT SELECT ON SEMANTIC VIEW ACTION360_DB.AI.CUSTOMER_360_SV TO ROLE ACTION360_ANALYST;
GRANT USAGE ON CORTEX SEARCH SERVICE ACTION360_DB.AI.INTERACTION_SEARCH TO ROLE ACTION360_ANALYST;
GRANT USAGE ON CORTEX SEARCH SERVICE ACTION360_DB.AI.KNOWLEDGE_SEARCH TO ROLE ACTION360_ANALYST;
GRANT USAGE ON ALL PROCEDURES IN SCHEMA ACTION360_DB.AI TO ROLE ACTION360_ANALYST;
GRANT USAGE ON ALL FUNCTIONS IN SCHEMA ACTION360_DB.AI TO ROLE ACTION360_ANALYST;
GRANT SELECT ON ALL TABLES IN SCHEMA ACTION360_DB.CORE TO ROLE ACTION360_ANALYST;
GRANT SELECT ON ALL DYNAMIC TABLES IN SCHEMA ACTION360_DB.CORE TO ROLE ACTION360_ANALYST;
GRANT SELECT ON ALL VIEWS IN SCHEMA ACTION360_DB.CORE TO ROLE ACTION360_ANALYST;
-- Audit is append-only for business users: no INSERT/UPDATE/DELETE grants; writes happen via owner's-rights LOG_ACTION only.
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON TABLE ACTION360_DB.CORE.ACTION_AUDIT FROM ROLE ACTION360_ANALYST;
