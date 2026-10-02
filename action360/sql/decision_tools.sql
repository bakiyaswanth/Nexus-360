-- =====================================================================
-- ACTION360 :: 08 Decision tools (used by the Cortex Agent AND the Streamlit app)
--   AI.SEARCH_SERVICE                 whitelisted Cortex Search wrapper (SEARCH_PREVIEW needs literals)
--   AI.GET_CUSTOMER_360               authoritative structured facts
--   AI.CHECK_OFFER_ELIGIBILITY        hard rule evaluation, rule-by-rule
--   AI.CALCULATE_NEXT_BEST_ACTION     deterministic NBA + evidence + confidence, persisted (no LLM)
--   AI.GENERATE_PERSONALIZED_OUTREACH LLM explains/personalises the *already selected* action (route-aware)
--   AI.LOG_ACTION                     append-only, hash-chained audit; re-checks eligibility at write time
-- =====================================================================
USE WAREHOUSE ACTION360_WH;
USE SCHEMA ACTION360_DB.AI;

-- ---------------------------------------------------------------------
CREATE OR REPLACE PROCEDURE AI.SEARCH_SERVICE(SERVICE_NAME VARCHAR, REQUEST VARIANT)
RETURNS VARIANT
LANGUAGE SQL
EXECUTE AS OWNER
AS
$$
DECLARE
  out VARIANT;
  svc VARCHAR;
  rs RESULTSET;
BEGIN
  svc := CASE UPPER(:SERVICE_NAME)
           WHEN 'INTERACTION_SEARCH' THEN 'ACTION360_DB.AI.INTERACTION_SEARCH'
           WHEN 'KNOWLEDGE_SEARCH' THEN 'ACTION360_DB.AI.KNOWLEDGE_SEARCH' END;
  IF (svc IS NULL) THEN
    RETURN OBJECT_CONSTRUCT('error', 'unknown search service');
  END IF;
  LET dd VARCHAR := CHR(36) || CHR(36);
  LET q VARCHAR := 'SELECT PARSE_JSON(SNOWFLAKE.CORTEX.SEARCH_PREVIEW(''' || svc || ''', ' || dd || REPLACE(TO_JSON(:REQUEST), dd, '') || dd || ')):results AS R';
  rs := (EXECUTE IMMEDIATE :q);
  LET c CURSOR FOR rs;
  OPEN c;
  FETCH c INTO out;
  CLOSE c;
  RETURN COALESCE(out, ARRAY_CONSTRUCT());
EXCEPTION
  WHEN OTHER THEN
    RETURN OBJECT_CONSTRUCT('error', SQLERRM);
END;
$$;

-- ---------------------------------------------------------------------
CREATE OR REPLACE PROCEDURE AI.GET_CUSTOMER_360(CUSTOMER_ID VARCHAR)
RETURNS VARIANT
LANGUAGE SQL
COMMENT = 'Agent tool: authoritative Customer 360 facts for one customer'
AS
$$
DECLARE
  out VARIANT;
  ev VARIANT;
  cid VARCHAR DEFAULT UPPER(TRIM(:CUSTOMER_ID));
BEGIN
  SELECT ARRAY_AGG(OBJECT_CONSTRUCT('event', EVENT_TYPE, 'date', EVENT_DATE, 'details', DETAILS)) INTO :ev
  FROM ACTION360_DB.CORE.FACT_CLAIM_OR_LOAN_EVENT WHERE CUSTOMER_ID = :cid AND EVENT_STATUS = 'OPEN';
  SELECT OBJECT_CONSTRUCT(
      'found', TRUE, 'data_classification', 'FACT (system of record, synthetic)',
      'identity', OBJECT_CONSTRUCT('customer_id', c.CUSTOMER_ID, 'name', c.FULL_NAME, 'segment', c.SEGMENT, 'business_type', c.INDUSTRY_TYPE,
                                   'city', c.CITY, 'tenure_months', c.TENURE_MONTHS, 'preferred_channel', c.PREFERRED_CHANNEL, 'age', c.AGE),
      'financial', OBJECT_CONSTRUCT('products', c.PRODUCTS, 'product_count', c.PRODUCT_COUNT, 'total_outstanding_inr', c.TOTAL_OUTSTANDING,
                                    'exposure_or_cover_inr', c.TOTAL_EXPOSURE_OR_COVER, 'monthly_obligation_inr', c.MONTHLY_OBLIGATION,
                                    'overdue_amount_inr', c.OVERDUE_AMOUNT, 'payment_status', c.PAYMENT_STATUS, 'missed_or_partial_6m', c.MISSED_6M,
                                    'late_6m', c.LATE_6M, 'max_days_late_90d', c.MAX_DAYS_LATE_90D, 'on_time_rate_12m', c.ON_TIME_RATE_12M,
                                    'credit_score', c.CREDIT_SCORE, 'next_renewal_date', c.NEXT_RENEWAL_DATE, 'next_renewal_product', c.NEXT_RENEWAL_PRODUCT,
                                    'days_to_renewal', c.DAYS_TO_RENEWAL, 'annual_value_inr', c.ANNUAL_VALUE_INR, 'value_percentile', c.VALUE_PERCENTILE),
      'interactions', OBJECT_CONSTRUCT('total', c.TOTAL_INTERACTIONS, 'last_90d', c.INTERACTIONS_90D, 'complaints_90d', c.COMPLAINTS_90D,
                                       'unresolved_complaints', c.UNRESOLVED_COUNT, 'open_requests', c.OPEN_REQUESTS, 'escalated', c.ESCALATED_COUNT,
                                       'negative_interactions_90d', c.NEGATIVE_INTERACTIONS_90D, 'sentiment', c.SENTIMENT_LABEL,
                                       'avg_sentiment_90d', c.AVG_SENTIMENT_90D, 'dominant_topic', c.DOMINANT_TOPIC,
                                       'days_since_last_interaction', c.DAYS_SINCE_LAST_INTERACTION, 'competitor_mention', c.COMPETITOR_MENTION = 1,
                                       'life_event', c.LIFE_EVENT = 1, 'hardship_stated', c.HARDSHIP_MENTION = 1),
      'risk', OBJECT_CONSTRUCT('risk_tier', c.RISK_TIER, 'risk_score', c.RISK_SCORE, 'primary_risk_type', c.PRIMARY_RISK_TYPE,
                               'churn_risk', c.CHURN_RISK, 'payment_risk', c.PAYMENT_RISK, 'service_risk', c.SERVICE_RISK,
                               'opportunity_score', c.OPPORTUNITY_SCORE, 'top_drivers', c.TOP_DRIVERS, 'ai_route', c.AI_ROUTE),
      'ai_interpretation', OBJECT_CONSTRUCT('label', 'AI INTERPRETATION (LLM summary of facts above)', 'customer_need', c.CUSTOMER_NEED,
                               'key_drivers', c.AI_KEY_DRIVERS, 'pain_points', c.AI_PAIN_POINTS, 'generated_at', c.AI_GENERATED_AT),
      'recommendation_preview', OBJECT_CONSTRUCT('action', c.RECOMMENDED_ACTION, 'action_name', c.RECOMMENDED_ACTION_NAME,
                               'offer_id', c.RECOMMENDED_OFFER_ID, 'secondary_action', c.SECONDARY_ACTION),
      'open_events', :ev)
    INTO :out
  FROM ACTION360_DB.CORE.CUSTOMER_360 c WHERE c.CUSTOMER_ID = :cid;
  RETURN COALESCE(out, OBJECT_CONSTRUCT('found', FALSE, 'customer_id', :cid,
         'message', 'No customer with this ID exists. Customer IDs look like C10238. Do not invent customer facts.'));
END;
$$;

-- ---------------------------------------------------------------------
CREATE OR REPLACE PROCEDURE AI.CHECK_OFFER_ELIGIBILITY(CUSTOMER_ID VARCHAR, OFFER_ID VARCHAR)
RETURNS VARIANT
LANGUAGE SQL
COMMENT = 'Agent tool: deterministic hard-rule eligibility. OFFER_ID optional (empty = all offers for the customer).'
AS
$$
DECLARE
  out VARIANT;
  cid VARCHAR DEFAULT UPPER(TRIM(:CUSTOMER_ID));
  oid VARCHAR DEFAULT NULLIF(UPPER(TRIM(COALESCE(:OFFER_ID, ''))), '');
  n INT;
BEGIN
  SELECT COUNT(*) INTO :n FROM ACTION360_DB.CORE.DIM_CUSTOMER WHERE CUSTOMER_ID = :cid;
  IF (n = 0) THEN
    RETURN OBJECT_CONSTRUCT('found', FALSE, 'message', 'Customer ' || :cid || ' does not exist.');
  END IF;
  SELECT ARRAY_AGG(OBJECT_CONSTRUCT('offer_id', e.OFFER_ID, 'offer_name', e.OFFER_NAME, 'category', e.OFFER_CATEGORY,
           'eligibility', IFF(e.IS_ELIGIBLE, 'ELIGIBLE', 'NOT ELIGIBLE'), 'passed_rules', e.PASSED_RULES, 'failed_rules', e.FAILED_RULES,
           'policy_doc', e.POLICY_DOC_ID)) WITHIN GROUP (ORDER BY e.IS_ELIGIBLE DESC, e.PRIORITY DESC)
    INTO :out
  FROM ACTION360_DB.CORE.OFFER_ELIGIBILITY e
  WHERE e.CUSTOMER_ID = :cid AND (:oid IS NULL OR e.OFFER_ID = :oid);
  IF (out IS NULL AND oid IS NOT NULL) THEN
    RETURN OBJECT_CONSTRUCT('found', TRUE, 'customer_id', :cid, 'offer_id', :oid, 'eligibility', 'NOT ELIGIBLE',
           'reason', 'Offer does not exist or does not apply to this customer''s line of business.');
  END IF;
  RETURN OBJECT_CONSTRUCT('found', TRUE, 'customer_id', :cid, 'source', 'OFFER_ELIGIBILITY_RULE (deterministic, authoritative)', 'offers', :out);
END;
$$;

-- ---------------------------------------------------------------------
CREATE OR REPLACE PROCEDURE AI.CALCULATE_NEXT_BEST_ACTION(CUSTOMER_ID VARCHAR, QUESTION VARCHAR)
RETURNS VARIANT
LANGUAGE SQL
COMMENT = 'Agent tool: deterministic next-best-action with candidates, reasons, evidence and confidence. Persists NBA_RECOMMENDATION. No LLM.'
AS
$$
DECLARE
  cid VARCHAR DEFAULT UPPER(TRIM(:CUSTOMER_ID));
  t0 TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP();
  n INT;
  route VARCHAR; ind VARCHAR; sel_action VARCHAR; sel_name VARCHAR; sel_score FLOAT; sel_offer VARIANT; sel_purpose VARCHAR;
  second_score FLOAT; candidates VARIANT; reasons VARIANT; facts VARIANT; ineligible VARIANT;
  tx_evidence VARIANT DEFAULT ARRAY_CONSTRUCT(); kb_evidence VARIANT DEFAULT ARRAY_CONSTRUCT();
  n_tx INT DEFAULT 0; confidence VARCHAR; rec_id VARCHAR DEFAULT UUID_STRING(); out VARIANT;
BEGIN
  SELECT COUNT(*) INTO :n FROM ACTION360_DB.CORE.CUSTOMER_360 WHERE CUSTOMER_ID = :cid;
  IF (n = 0) THEN
    RETURN OBJECT_CONSTRUCT('found', FALSE, 'message', 'Customer ' || :cid || ' does not exist - no recommendation can be made.');
  END IF;

  SELECT AI_ROUTE, INDUSTRY_TYPE,
         ARRAY_CONSTRUCT_COMPACT(
           'Segment ' || SEGMENT || ', tenure ' || TENURE_MONTHS || ' months, products: ' || ARRAY_TO_STRING(PRODUCTS, ', '),
           'Payment status ' || PAYMENT_STATUS || ' (missed/partial 6m: ' || MISSED_6M || ', max days late 90d: ' || MAX_DAYS_LATE_90D || ')',
           IFF(DAYS_TO_RENEWAL BETWEEN 0 AND 90, NEXT_RENEWAL_PRODUCT || ' renewal/reset on ' || NEXT_RENEWAL_DATE || ' (in ' || DAYS_TO_RENEWAL || ' days)', NULL),
           'Complaints 90d: ' || COMPLAINTS_90D || ', unresolved complaints: ' || UNRESOLVED_COUNT || ', escalated: ' || ESCALATED_COUNT,
           'Recent sentiment: ' || SENTIMENT_LABEL,
           'Risk tier ' || RISK_TIER || ' (churn ' || CHURN_RISK || ', payment ' || PAYMENT_RISK || ', service ' || SERVICE_RISK || ')',
           IFF(COMPETITOR_MENTION = 1, 'Customer mentioned switching / a competitor in the last 120 days', NULL),
           IFF(LIFE_EVENT = 1, 'Life event mentioned (newborn / marriage / new home)', NULL),
           IFF(HARDSHIP_MENTION = 1, 'Customer stated financial hardship', NULL),
           IFF(CLAIM_DELAYED_FLAG = 1, 'Open claim beyond SLA', NULL))
    INTO :route, :ind, :facts
  FROM ACTION360_DB.CORE.CUSTOMER_360 WHERE CUSTOMER_ID = :cid;

  SELECT ARRAY_AGG(OBJECT_CONSTRUCT('action', ACTION_CODE, 'action_name', ACTION_NAME, 'score', ACTION_SCORE, 'status', CANDIDATE_STATUS,
            'rank', ELIGIBLE_RANK, 'offer', SELECTED_OFFER, 'blocked_by', BLOCK_REASONS, 'top_contributions', TOP_CONTRIBUTIONS))
         WITHIN GROUP (ORDER BY IFF(CANDIDATE_STATUS = 'ELIGIBLE', 0, 1), ACTION_SCORE DESC)
    INTO :candidates
  FROM ACTION360_DB.CORE.NBA_CANDIDATE WHERE CUSTOMER_ID = :cid;

  SELECT ACTION_CODE, ACTION_NAME, ACTION_SCORE, SELECTED_OFFER, BUSINESS_PURPOSE, TOP_CONTRIBUTIONS, INELIGIBLE_OFFERS
    INTO :sel_action, :sel_name, :sel_score, :sel_offer, :sel_purpose, :reasons, :ineligible
  FROM ACTION360_DB.CORE.NBA_CANDIDATE WHERE CUSTOMER_ID = :cid AND ELIGIBLE_RANK = 1;

  SELECT COALESCE(MAX(ACTION_SCORE), 0) INTO :second_score
  FROM ACTION360_DB.CORE.NBA_CANDIDATE WHERE CUSTOMER_ID = :cid AND ELIGIBLE_RANK = 2;

  -- Evidence retrieval is route-aware: RULES_ONLY customers get structured evidence only (no search / LLM spend)
  IF (route <> 'RULES_ONLY') THEN
    CALL AI.SEARCH_SERVICE('INTERACTION_SEARCH', OBJECT_CONSTRUCT(
      'query', COALESCE(NULLIF(:QUESTION, ''), 'customer problem and intent') || ' ' || :sel_name,
      'columns', ARRAY_CONSTRUCT('DOC_ID', 'INTERACTION_DATE', 'CHANNEL', 'TOPIC', 'SENTIMENT', 'SOURCE_TYPE', 'CONTENT'),
      'filter', OBJECT_CONSTRUCT('@eq', OBJECT_CONSTRUCT('CUSTOMER_ID', :cid)), 'limit', 3)) INTO :tx_evidence;
    CALL AI.SEARCH_SERVICE('KNOWLEDGE_SEARCH', OBJECT_CONSTRUCT(
      'query', :sel_name || ' ' || COALESCE(GET(:sel_offer, 'offer_name')::STRING, '') || ' ' || :sel_purpose,
      'columns', ARRAY_CONSTRUCT('CHUNK_ID', 'TITLE', 'SECTION', 'DOC_TYPE', 'CHUNK_TEXT'),
      'filter', OBJECT_CONSTRUCT('@or', ARRAY_CONSTRUCT(OBJECT_CONSTRUCT('@eq', OBJECT_CONSTRUCT('INDUSTRY_TYPE', :ind)),
                                                       OBJECT_CONSTRUCT('@eq', OBJECT_CONSTRUCT('INDUSTRY_TYPE', 'ALL')))),
      'limit', 2)) INTO :kb_evidence;
  ELSE
    SELECT ARRAY_AGG(OBJECT_CONSTRUCT('DOC_ID', INTERACTION_ID, 'INTERACTION_DATE', INTERACTION_TS::DATE, 'CHANNEL', CHANNEL,
                                      'TOPIC', TOPIC, 'CONTENT', NOTE, 'SOURCE_TYPE', 'INTERACTION_NOTE')) INTO :tx_evidence
    FROM (SELECT * FROM ACTION360_DB.CORE.FACT_INTERACTION WHERE CUSTOMER_ID = :cid ORDER BY INTERACTION_TS DESC LIMIT 2);
  END IF;
  n_tx := COALESCE(ARRAY_SIZE(:tx_evidence), 0);

  confidence := CASE
    WHEN sel_action = 'NO_ACTION_MONITOR' AND route = 'RULES_ONLY' THEN 'HIGH'
    WHEN sel_score - second_score >= 0.15 AND n_tx >= 1 THEN 'HIGH'
    WHEN sel_score - second_score >= 0.05 OR n_tx >= 1 THEN 'MEDIUM'
    ELSE 'LOW' END;

  out := OBJECT_CONSTRUCT(
    'found', TRUE, 'recommendation_id', :rec_id, 'customer_id', :cid, 'ai_route', :route,
    'selected_action', :sel_action, 'action_name', :sel_name, 'action_score', ROUND(:sel_score, 3),
    'business_purpose', :sel_purpose,
    'offer', :sel_offer,
    'eligibility', IFF(:sel_offer IS NULL, 'NO OFFER ATTACHED', 'ELIGIBLE (all hard rules passed)'),
    'ineligible_offers_in_category', :ineligible,
    'reasons', :reasons,
    'candidates', :candidates,
    'confidence', :confidence,
    'evidence', OBJECT_CONSTRUCT('structured_facts', :facts, 'interaction_evidence', :tx_evidence, 'policy_evidence', :kb_evidence),
    'decision_provenance', 'Deterministic: NBA_WEIGHT x CUSTOMER_SIGNAL, NBA_GUARDRAIL, OFFER_ELIGIBILITY_RULE. LLM not used for the decision.');

  INSERT INTO ACTION360_DB.CORE.NBA_RECOMMENDATION (RECOMMENDATION_ID, CUSTOMER_ID, QUESTION, SELECTED_ACTION, CANDIDATE_ACTIONS, ACTION_SCORE,
      REASONS, SUPPORTING_EVIDENCE, OFFER_ID, ELIGIBILITY_RESULT, CONFIDENCE, AI_ROUTE, MODEL, LATENCY_MS)
  SELECT :rec_id, :cid, :QUESTION, :sel_action, :candidates, :sel_score, :reasons, GET(:out, 'evidence'), GET(:sel_offer, 'offer_id')::STRING,
         OBJECT_CONSTRUCT('selected_offer', :sel_offer, 'ineligible_offers', :ineligible), :confidence, :route, 'deterministic',
         DATEDIFF(ms, :t0, CURRENT_TIMESTAMP());

  INSERT INTO ACTION360_DB.CORE.AI_USAGE_METRICS (COMPONENT, CUSTOMER_ID, AI_ROUTE, AI_FUNCTION, MODEL, CALLS, EST_TOKENS, LATENCY_MS, SKIPPED, DETAILS)
  SELECT 'CALCULATE_NEXT_BEST_ACTION', :cid, :route, IFF(:route = 'RULES_ONLY', 'none', 'CORTEX_SEARCH'), 'deterministic',
         IFF(:route = 'RULES_ONLY', 0, 2), 0, DATEDIFF(ms, :t0, CURRENT_TIMESTAMP()), :route = 'RULES_ONLY',
         OBJECT_CONSTRUCT('selected_action', :sel_action);
  RETURN out;
END;
$$;

-- ---------------------------------------------------------------------
CREATE OR REPLACE PROCEDURE AI.GENERATE_PERSONALIZED_OUTREACH(RECOMMENDATION_ID VARCHAR, CHANNEL VARCHAR, FORCE_LLM BOOLEAN)
RETURNS VARIANT
LANGUAGE SQL
COMMENT = 'Agent tool: personalise and explain an existing recommendation. Cannot change action/offer. Skips the LLM for RULES_ONLY monitor cases.'
AS
$$
DECLARE
  rid VARCHAR DEFAULT TRIM(:RECOMMENDATION_ID);
  t0 TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP();
  cid VARCHAR; action VARCHAR; route VARCHAR; offer VARIANT; elig VARIANT; reasons VARIANT; evidence VARIANT; ctx VARCHAR;
  ch VARCHAR; res VARIANT; violation BOOLEAN DEFAULT FALSE; msg VARCHAR; n INT; inel VARIANT;
BEGIN
  SELECT COUNT(*) INTO :n FROM ACTION360_DB.CORE.NBA_RECOMMENDATION WHERE RECOMMENDATION_ID = :rid;
  IF (n = 0) THEN
    RETURN OBJECT_CONSTRUCT('error', 'Unknown recommendation_id. Call calculate_next_best_action first.');
  END IF;
  SELECT r.CUSTOMER_ID, r.SELECTED_ACTION, r.AI_ROUTE, r.ELIGIBILITY_RESULT:selected_offer, r.ELIGIBILITY_RESULT, r.REASONS, r.SUPPORTING_EVIDENCE,
         COALESCE(NULLIF(UPPER(:CHANNEL), ''), c.PREFERRED_CHANNEL), x.CTX
    INTO :cid, :action, :route, :offer, :elig, :reasons, :evidence, :ch, :ctx
  FROM ACTION360_DB.CORE.NBA_RECOMMENDATION r
  JOIN ACTION360_DB.CORE.CUSTOMER_360 c USING (CUSTOMER_ID)
  JOIN ACTION360_DB.CORE.V_CUSTOMER_CONTEXT x USING (CUSTOMER_ID)
  WHERE r.RECOMMENDATION_ID = :rid;

  IF (action = 'NO_ACTION_MONITOR' AND NOT COALESCE(:FORCE_LLM, FALSE)) THEN
    INSERT INTO ACTION360_DB.CORE.AI_USAGE_METRICS (COMPONENT, CUSTOMER_ID, AI_ROUTE, AI_FUNCTION, MODEL, CALLS, EST_TOKENS, LATENCY_MS, SKIPPED, DETAILS)
    SELECT 'GENERATE_PERSONALIZED_OUTREACH', :cid, :route, 'AI.GENERATE_PERSONALIZED_ACTION', 'skipped', 1, 0, 0, TRUE,
           OBJECT_CONSTRUCT('reason', 'Stable customer - no outreach needed; LLM call avoided');
    RETURN OBJECT_CONSTRUCT('recommendation_id', :rid, 'llm_used', FALSE,
           'customer_message', NULL, 'why_relevant', 'Customer is stable (low risk, no open issues). Recommended action is to monitor only.',
           'why_now', 'No trigger present.', 'rm_talking_points', ARRAY_CONSTRUCT('No contact required - avoid unnecessary outreach.'),
           'evidence_gaps', '');
  END IF;

  inel := COALESCE(elig:ineligible_offers, ARRAY_CONSTRUCT());
  LET decision VARCHAR := TO_JSON(OBJECT_CONSTRUCT('selected_action', action, 'eligible_offer', offer,
                            'eligibility_result', 'ELIGIBLE for the offer shown; nothing else',
                            'offers_customer_is_NOT_eligible_for', inel, 'scoring_reasons', reasons));
  LET ev_json VARCHAR := TO_JSON(evidence);
  SELECT ACTION360_DB.AI.GENERATE_PERSONALIZED_ACTION(:ctx, :decision, :ev_json, :ch) INTO :res;

  -- Post-generation guardrail: generated text may not reference any offer the customer is NOT eligible for
  SELECT COUNT(*) > 0 INTO :violation
  FROM TABLE(FLATTEN(INPUT => :inel)) f
  WHERE CONTAINS(LOWER(GET(:res, 'customer_message')::STRING), LOWER(f.VALUE:offer_name::STRING))
     OR CONTAINS(GET(:res, 'customer_message')::STRING, f.VALUE:offer_id::STRING);
  msg := IFF(violation, 'Message withheld: generated text referenced an offer the customer is not eligible for. Please regenerate.',
             GET(res, 'customer_message')::STRING);

  UPDATE ACTION360_DB.CORE.NBA_RECOMMENDATION
     SET GENERATED_MESSAGE = :msg, GENERATED_EXPLANATION = TO_JSON(:res), MODEL = 'claude-sonnet-4-6', LATENCY_MS = DATEDIFF(ms, :t0, CURRENT_TIMESTAMP())
   WHERE RECOMMENDATION_ID = :rid;

  INSERT INTO ACTION360_DB.CORE.AI_USAGE_METRICS (COMPONENT, CUSTOMER_ID, AI_ROUTE, AI_FUNCTION, MODEL, CALLS, EST_TOKENS, LATENCY_MS, SKIPPED, DETAILS)
  SELECT 'GENERATE_PERSONALIZED_OUTREACH', :cid, :route, 'AI.GENERATE_PERSONALIZED_ACTION', 'claude-sonnet-4-6', 1,
         AI_COUNT_TOKENS('ai_complete', 'claude-sonnet-4-6', :ctx || TO_JSON(:evidence)) + 700, DATEDIFF(ms, :t0, CURRENT_TIMESTAMP()), FALSE,
         OBJECT_CONSTRUCT('guardrail_violation', :violation, 'channel', :ch);

  RETURN OBJECT_CONSTRUCT('recommendation_id', :rid, 'llm_used', TRUE, 'model', 'claude-sonnet-4-6', 'channel', :ch,
         'label', 'AI-GENERATED PERSONALISATION (decision itself is deterministic)', 'guardrail_violation', :violation,
         'why_relevant', GET(res, 'why_relevant'), 'why_now', GET(res, 'why_now'), 'customer_pain_point', GET(res, 'customer_pain_point'),
         'customer_message', msg, 'rm_talking_points', GET(res, 'rm_talking_points'), 'evidence_gaps', GET(res, 'evidence_gaps'));
END;
$$;

-- ---------------------------------------------------------------------
CREATE OR REPLACE PROCEDURE AI.LOG_ACTION(RECOMMENDATION_ID VARCHAR, USER_ACTION VARCHAR, REQUESTED_OFFER_ID VARCHAR, NOTE VARCHAR)
RETURNS VARIANT
LANGUAGE SQL
COMMENT = 'Agent/app tool: append an immutable, hash-chained audit record. Only call after explicit user approval. Downstream execution is SIMULATED.'
AS
$$
DECLARE
  rid VARCHAR DEFAULT TRIM(:RECOMMENDATION_ID);
  ua VARCHAR DEFAULT UPPER(TRIM(COALESCE(:USER_ACTION, '')));
  req_offer VARCHAR DEFAULT NULLIF(UPPER(TRIM(COALESCE(:REQUESTED_OFFER_ID, ''))), '');
  cid VARCHAR; action VARCHAR; offer_id VARCHAR; question VARCHAR; reason VARCHAR; evidence VARIANT; msg VARCHAR; owner VARCHAR;
  eligible BOOLEAN; failed VARIANT; prev VARCHAR; audit_id VARCHAR DEFAULT UUID_STRING(); status VARCHAR; n INT; ev_refs VARIANT;
BEGIN
  IF (ua NOT IN ('APPROVED', 'REJECTED', 'DEFERRED')) THEN
    RETURN OBJECT_CONSTRUCT('logged', FALSE, 'error', 'USER_ACTION must be APPROVED, REJECTED or DEFERRED');
  END IF;
  SELECT COUNT(*) INTO :n FROM ACTION360_DB.CORE.NBA_RECOMMENDATION WHERE RECOMMENDATION_ID = :rid;
  IF (n = 0) THEN
    RETURN OBJECT_CONSTRUCT('logged', FALSE, 'error', 'Unknown recommendation_id');
  END IF;
  SELECT r.CUSTOMER_ID, r.SELECTED_ACTION, r.OFFER_ID, r.QUESTION, TO_JSON(r.REASONS), r.GENERATED_MESSAGE, a.OWNER_ROLE,
         ARRAY_CONSTRUCT_COMPACT('CUSTOMER_360:' || r.CUSTOMER_ID, 'NBA_RECOMMENDATION:' || r.RECOMMENDATION_ID,
                                 IFF(r.OFFER_ID IS NULL, NULL, 'OFFER_ELIGIBILITY:' || r.CUSTOMER_ID || '/' || r.OFFER_ID))
    INTO :cid, :action, :offer_id, :question, :reason, :msg, :owner, :evidence
  FROM ACTION360_DB.CORE.NBA_RECOMMENDATION r JOIN ACTION360_DB.CORE.ACTION_CATALOG a ON a.ACTION_CODE = r.SELECTED_ACTION
  WHERE r.RECOMMENDATION_ID = :rid;
  SELECT COALESCE(ARRAY_AGG(COALESCE('INTERACTION:' || f.VALUE:DOC_ID::STRING, 'KNOWLEDGE:' || f.VALUE:CHUNK_ID::STRING)), ARRAY_CONSTRUCT())
    INTO :ev_refs
  FROM ACTION360_DB.CORE.NBA_RECOMMENDATION r,
       LATERAL FLATTEN(INPUT => ARRAY_CAT(IFF(IS_ARRAY(r.SUPPORTING_EVIDENCE:interaction_evidence), r.SUPPORTING_EVIDENCE:interaction_evidence, ARRAY_CONSTRUCT()),
                                          IFF(IS_ARRAY(r.SUPPORTING_EVIDENCE:policy_evidence), r.SUPPORTING_EVIDENCE:policy_evidence, ARRAY_CONSTRUCT()))) f
  WHERE r.RECOMMENDATION_ID = :rid;
  evidence := ARRAY_CAT(evidence, ev_refs);

  -- Hard rule re-check at write time: a user cannot approve an offer the customer is not eligible for
  IF (req_offer IS NOT NULL AND req_offer <> COALESCE(offer_id, '')) THEN
    SELECT MAX(IS_ELIGIBLE), ANY_VALUE(FAILED_RULES) INTO :eligible, :failed
    FROM ACTION360_DB.CORE.OFFER_ELIGIBILITY WHERE CUSTOMER_ID = :cid AND OFFER_ID = :req_offer;
    IF (NOT COALESCE(eligible, FALSE)) THEN
      ua := 'BLOCKED_INELIGIBLE_OFFER';
      offer_id := req_offer;
    ELSE
      offer_id := req_offer;
    END IF;
  END IF;

  SELECT RECORD_HASH INTO :prev FROM ACTION360_DB.CORE.ACTION_AUDIT ORDER BY ACTED_AT DESC, AUDIT_ID LIMIT 1;
  status := CASE ua WHEN 'APPROVED' THEN 'SIMULATED: task queued for ' || :owner || ' (no external system called)'
                    WHEN 'BLOCKED_INELIGIBLE_OFFER' THEN 'BLOCKED: requested offer failed hard eligibility rules'
                    ELSE 'NO DOWNSTREAM ACTION' END;

  INSERT INTO ACTION360_DB.CORE.ACTION_AUDIT (AUDIT_ID, RECOMMENDATION_ID, CUSTOMER_ID, QUESTION, RECOMMENDATION, RECOMMENDATION_REASON, OFFER_ID,
      ELIGIBILITY_STATUS, EVIDENCE_REFERENCES, USER_ACTION, OUTREACH_MESSAGE, EXECUTION_MODE, DOWNSTREAM_STATUS, PREV_HASH, RECORD_HASH)
  SELECT :audit_id, :rid, :cid, :question, :action, :reason, :offer_id,
         CASE WHEN :ua = 'BLOCKED_INELIGIBLE_OFFER' THEN 'NOT ELIGIBLE: ' || ARRAY_TO_STRING(ARRAY_COMPACT(:failed), '; ')
              WHEN :offer_id IS NULL THEN 'NO OFFER' ELSE 'ELIGIBLE' END,
         :evidence, :ua, :msg, 'SIMULATED', :status, :prev,
         SHA2(COALESCE(:prev, 'GENESIS') || '|' || :audit_id || '|' || :rid || '|' || :cid || '|' || :action || '|' || COALESCE(:offer_id, '') || '|' || :ua, 256);

  RETURN OBJECT_CONSTRUCT('logged', :ua <> 'BLOCKED_INELIGIBLE_OFFER', 'audit_id', :audit_id, 'user_action', :ua,
         'downstream_status', :status, 'failed_rules', :failed, 'execution_mode', 'SIMULATED');
END;
$$;
