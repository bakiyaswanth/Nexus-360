-- =====================================================================
-- ACTION360 :: 06 Cortex AI functions & cost-aware enrichment pipeline
--   AI.SUMMARIZE_CUSTOMER_RISK       custom AI FUNCTION (AI Function Studio, Direct mode)
--   AI.GENERATE_PERSONALIZED_ACTION  custom AI FUNCTION (AI Function Studio, Direct mode)
--   CORE.INGEST_CALL_AUDIO()         AI_TRANSCRIBE staged audio -> FACT_INTERACTION + CALL_TRANSCRIPT
--   CORE.ENRICH_TRANSCRIPTS()        AI_SENTIMENT + AI_CLASSIFY, *only* for routed customers
--   CORE.GENERATE_CUSTOMER_INSIGHTS() LLM summary only for FULL_AGENT customers
--   Stream + Task                    incremental enrichment of new transcripts
-- =====================================================================
USE WAREHOUSE ACTION360_WH;
USE SCHEMA ACTION360_DB.CORE;

UPDATE APP_CONFIG SET CONFIG_VALUE = 'claude-sonnet-4-6', UPDATED_AT = CURRENT_TIMESTAMP() WHERE CONFIG_KEY = 'PERSONALIZATION_MODEL';
UPDATE APP_CONFIG SET CONFIG_VALUE = 'claude-haiku-4-5', UPDATED_AT = CURRENT_TIMESTAMP() WHERE CONFIG_KEY = 'LIGHT_MODEL';
MERGE INTO APP_CONFIG t USING (SELECT * FROM VALUES
  ('MAX_TRANSCRIPTS_SELECTIVE','1','Latest N transcripts enriched for SELECTIVE_AI customers'),
  ('MAX_TRANSCRIPTS_FULL','2','Latest N transcripts enriched for FULL_AGENT customers'),
  ('ENRICH_LOOKBACK_DAYS','120','Only transcripts newer than this are enriched')) s(k, v, d)
ON t.CONFIG_KEY = s.k WHEN NOT MATCHED THEN INSERT (CONFIG_KEY, CONFIG_VALUE, DESCRIPTION) VALUES (s.k, s.v, s.d);

DROP FUNCTION IF EXISTS ACTION360_DB.AI.ZZ_PROBE(VARCHAR);

-- ---------------------------------------------------------------------
-- Custom AI functions (structured JSON output via response_format)
-- ---------------------------------------------------------------------
CREATE OR REPLACE AI FUNCTION ACTION360_DB.AI.SUMMARIZE_CUSTOMER_RISK(CUSTOMER_CONTEXT VARCHAR)
RETURNS VARIANT
COMMENT = 'Summarise a customer''s need, risk drivers and pain points from governed facts + interaction evidence. Grounded: facts only.'
AS
$$
SELECT AI_COMPLETE(
  model => 'claude-haiku-4-5',
  messages => ARRAY_CONSTRUCT(
    OBJECT_CONSTRUCT('role', 'system', 'content',
      'You are a customer-experience analyst at a regulated bank / insurer. Summarise ONLY what is supported by the supplied FACTS and EVIDENCE. '
      || 'Never invent balances, eligibility, coverage, statements or events. If something is not in the input, do not mention it. '
      || 'Do not mention risk scores. Write concise, professional English. Pain points must be phrased from the customer''s perspective.'),
    OBJECT_CONSTRUCT('role', 'user', 'content', 'Summarise this customer.\n\n' || CUSTOMER_CONTEXT)),
  response_format => PARSE_JSON('{"type":"json","schema":{"type":"object","properties":{
     "customer_need":{"type":"string","description":"One sentence: what the customer needs right now"},
     "key_drivers":{"type":"array","items":{"type":"string"},"description":"Up to 3 evidence-backed reasons behind the current risk or opportunity"},
     "pain_points":{"type":"array","items":{"type":"string"},"description":"Up to 3 customer pain points"},
     "latest_important_interaction":{"type":"string","description":"One sentence describing the most important recent interaction"}},
     "required":["customer_need","key_drivers","pain_points","latest_important_interaction"]}}'),
  model_parameters => OBJECT_CONSTRUCT('temperature', 0, 'max_tokens', 500))
$$;

CREATE OR REPLACE AI FUNCTION ACTION360_DB.AI.GENERATE_PERSONALIZED_ACTION(
  CUSTOMER_FACTS VARCHAR, DECISION VARCHAR, EVIDENCE VARCHAR, CHANNEL VARCHAR)
RETURNS VARIANT
COMMENT = 'Explain and personalise a DETERMINISTICALLY selected next-best-action. Cannot change the action or offer.'
AS
$$
SELECT AI_COMPLETE(
  model => 'claude-sonnet-4-6',
  messages => ARRAY_CONSTRUCT(
    OBJECT_CONSTRUCT('role', 'system', 'content',
      'You write next-best-action briefs for relationship managers at a regulated lender / insurer. '
      || 'The DECISION (action, offer, eligibility) was made by an auditable rules engine and is FINAL: never change it, never add another offer, '
      || 'never imply eligibility for anything not listed as eligible. Use ONLY the FACTS and EVIDENCE provided; if evidence is missing say so. '
      || 'Customer-facing messages: warm, specific, no account numbers, no balances, no risk scores, no competitor names, acknowledge any open problem first, '
      || 'end with a clear next step. Match the requested channel (CALL = call opener script, EMAIL = subject + short email, WHATSAPP/APP = under 60 words).'),
    OBJECT_CONSTRUCT('role', 'user', 'content',
      'FACTS:\n' || CUSTOMER_FACTS || '\n\nDECISION:\n' || DECISION || '\n\nEVIDENCE:\n' || EVIDENCE || '\n\nCHANNEL: ' || CHANNEL)),
  response_format => PARSE_JSON('{"type":"json","schema":{"type":"object","properties":{
     "why_relevant":{"type":"string","description":"Why this action fits this customer, citing facts"},
     "why_now":{"type":"string","description":"Why act now (timing trigger)"},
     "customer_pain_point":{"type":"string"},
     "customer_message":{"type":"string","description":"Personalised outreach in the requested channel"},
     "rm_talking_points":{"type":"array","items":{"type":"string"},"description":"3-4 internal talking points"},
     "evidence_gaps":{"type":"string","description":"What evidence was missing, or empty"}},
     "required":["why_relevant","why_now","customer_pain_point","customer_message","rm_talking_points","evidence_gaps"]}}'),
  model_parameters => OBJECT_CONSTRUCT('temperature', 0.2, 'max_tokens', 2500))
$$;

-- ---------------------------------------------------------------------
-- AI_TRANSCRIBE ingestion: @RAW.AUDIO_STAGE/<CUSTOMER_ID>_<INTERACTION_ID>.wav
-- ---------------------------------------------------------------------
CREATE OR REPLACE PROCEDURE CORE.INGEST_CALL_AUDIO()
RETURNS VARIANT
LANGUAGE SQL
EXECUTE AS OWNER
AS
$$
DECLARE
  n_files INT DEFAULT 0;
  t0 TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP();
BEGIN
  ALTER STAGE ACTION360_DB.RAW.AUDIO_STAGE REFRESH;
  CREATE OR REPLACE TEMPORARY TABLE TMP_TRANSCRIBED AS
  SELECT RELATIVE_PATH,
         SPLIT_PART(RELATIVE_PATH, '_', 1) AS CUSTOMER_ID,
         SPLIT_PART(SPLIT_PART(RELATIVE_PATH, '_', 2), '.', 1) AS INTERACTION_ID,
         LAST_MODIFIED,
         AI_TRANSCRIBE(TO_FILE('@ACTION360_DB.RAW.AUDIO_STAGE', RELATIVE_PATH), {'timestamp_granularity': 'speaker'}) AS T
  FROM DIRECTORY(@ACTION360_DB.RAW.AUDIO_STAGE)
  WHERE RELATIVE_PATH ILIKE ANY ('%.wav', '%.mp3', '%.m4a', '%.flac', '%.ogg')
    AND SPLIT_PART(SPLIT_PART(RELATIVE_PATH, '_', 2), '.', 1) NOT IN (SELECT INTERACTION_ID FROM CORE.CALL_TRANSCRIPT)
    AND SPLIT_PART(RELATIVE_PATH, '_', 1) IN (SELECT CUSTOMER_ID FROM CORE.DIM_CUSTOMER);

  -- Speaker mapping: the first detected speaker on an inbound/outbound service call is the agent.
  CREATE OR REPLACE TEMPORARY TABLE TMP_SEGMENTS AS
  SELECT x.RELATIVE_PATH, x.CUSTOMER_ID, x.INTERACTION_ID, x.LAST_MODIFIED, x.T:audio_duration::FLOAT AS DURATION,
         ARRAY_AGG(OBJECT_CONSTRUCT(
            'speaker', IFF(s.VALUE:speaker_label::STRING = x.T:segments[0]:speaker_label::STRING, 'AGENT', 'CUSTOMER'),
            'start', s.VALUE:start::FLOAT, 'end', s.VALUE:end::FLOAT, 'text', s.VALUE:text::STRING))
           WITHIN GROUP (ORDER BY s.VALUE:start::FLOAT) AS SEGMENTS,
         LISTAGG(IFF(s.VALUE:speaker_label::STRING = x.T:segments[0]:speaker_label::STRING, 'AGENT: ', 'CUSTOMER: ') || s.VALUE:text::STRING, '\n')
           WITHIN GROUP (ORDER BY s.VALUE:start::FLOAT) AS TRANSCRIPT_TEXT
  FROM TMP_TRANSCRIBED x, LATERAL FLATTEN(INPUT => x.T:segments) s
  WHERE x.T IS NOT NULL
  GROUP BY 1, 2, 3, 4, 5;

  INSERT INTO CORE.FACT_INTERACTION (INTERACTION_ID, CUSTOMER_ID, INDUSTRY_TYPE, INTERACTION_TS, CHANNEL, TOPIC, IS_COMPLAINT,
                                     RESOLUTION_STATUS, RULE_SENTIMENT, NOTE, HAS_TRANSCRIPT, TEMPLATE_ID)
  SELECT s.INTERACTION_ID, s.CUSTOMER_ID, c.INDUSTRY_TYPE, '2026-10-01 16:00:00'::TIMESTAMP_NTZ, 'CALL', 'Call recording (transcribed)',
         FALSE, 'OPEN', 0, LEFT(s.TRANSCRIPT_TEXT, 240), TRUE, 'AI_TRANSCRIBE'
  FROM TMP_SEGMENTS s JOIN CORE.DIM_CUSTOMER c USING (CUSTOMER_ID)
  WHERE s.INTERACTION_ID NOT IN (SELECT INTERACTION_ID FROM CORE.FACT_INTERACTION);

  INSERT INTO CORE.CALL_TRANSCRIPT (TRANSCRIPT_ID, INTERACTION_ID, CUSTOMER_ID, CALL_TS, DURATION_SEC, SOURCE_TYPE, SOURCE_FILE, TRANSCRIPT_TEXT, SEGMENTS)
  SELECT 'TR-' || INTERACTION_ID, INTERACTION_ID, CUSTOMER_ID, '2026-10-01 16:00:00'::TIMESTAMP_NTZ, ROUND(DURATION), 'AI_TRANSCRIBE',
         '@ACTION360_DB.RAW.AUDIO_STAGE/' || RELATIVE_PATH, TRANSCRIPT_TEXT, SEGMENTS
  FROM TMP_SEGMENTS;

  SELECT COUNT(*) INTO :n_files FROM TMP_SEGMENTS;
  INSERT INTO CORE.AI_USAGE_METRICS (COMPONENT, AI_ROUTE, AI_FUNCTION, MODEL, CALLS, EST_TOKENS, LATENCY_MS, DETAILS)
  SELECT 'INGEST_CALL_AUDIO', 'PIPELINE', 'AI_TRANSCRIBE', 'managed', :n_files, ROUND(SUM(GREATEST(DURATION, 10)) * 50),
         DATEDIFF(ms, :t0, CURRENT_TIMESTAMP()), OBJECT_CONSTRUCT('files', ARRAY_AGG(RELATIVE_PATH))
  FROM TMP_SEGMENTS;
  RETURN OBJECT_CONSTRUCT('files_transcribed', :n_files);
END;
$$;

-- ---------------------------------------------------------------------
-- Cost-aware transcript enrichment
--   RULES_ONLY   -> skipped (deterministic RULE_SENTIMENT + keyword signals are used)
--   SELECTIVE_AI -> latest N1 transcripts: AI_SENTIMENT + AI_CLASSIFY
--   FULL_AGENT   -> latest N2 transcripts: AI_SENTIMENT + AI_CLASSIFY (+ insight summary separately)
-- ---------------------------------------------------------------------
CREATE OR REPLACE PROCEDURE CORE.ENRICH_TRANSCRIPTS(MAX_ROWS INT)
RETURNS VARIANT
LANGUAGE SQL
EXECUTE AS OWNER
AS
$$
DECLARE
  n_enriched INT DEFAULT 0;
  n_skipped INT DEFAULT 0;
  t0 TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP();
BEGIN
  CREATE OR REPLACE TEMPORARY TABLE TMP_ENRICH_SCOPE AS
  WITH cfg AS (
    SELECT MAX(IFF(CONFIG_KEY = 'MAX_TRANSCRIPTS_SELECTIVE', CONFIG_VALUE::INT, NULL)) N_SEL,
           MAX(IFF(CONFIG_KEY = 'MAX_TRANSCRIPTS_FULL', CONFIG_VALUE::INT, NULL)) N_FULL,
           MAX(IFF(CONFIG_KEY = 'ENRICH_LOOKBACK_DAYS', CONFIG_VALUE::INT, NULL)) LB,
           MAX(IFF(CONFIG_KEY = 'AS_OF_DATE', TO_DATE(CONFIG_VALUE), NULL)) AS_OF FROM CORE.APP_CONFIG)
  SELECT t.TRANSCRIPT_ID, t.CUSTOMER_ID, r.AI_ROUTE, i.IS_COMPLAINT,
         ROW_NUMBER() OVER (PARTITION BY t.CUSTOMER_ID ORDER BY t.CALL_TS DESC) RN,
         IFF(r.AI_ROUTE = 'FULL_AGENT', cfg.N_FULL, IFF(r.AI_ROUTE = 'SELECTIVE_AI', cfg.N_SEL, 0)) QUOTA
  FROM CORE.CALL_TRANSCRIPT t JOIN CORE.CUSTOMER_RISK r USING (CUSTOMER_ID)
  JOIN CORE.FACT_INTERACTION i USING (INTERACTION_ID), cfg
  WHERE t.AI_ENRICHED_AT IS NULL AND t.CALL_TS >= DATEADD(day, -cfg.LB, cfg.AS_OF);

  SELECT COUNT_IF(RN > QUOTA) INTO :n_skipped FROM TMP_ENRICH_SCOPE;

  MERGE INTO CORE.CALL_TRANSCRIPT t USING (
    SELECT s.TRANSCRIPT_ID,
      DECODE(AI_SENTIMENT(c.TRANSCRIPT_TEXT):categories[0]:sentiment::STRING,
             'positive', 0.6, 'neutral', 0.0, 'mixed', -0.3, 'negative', -0.7, NULL) AS SENT,
      AI_CLASSIFY(c.TRANSCRIPT_TEXT, ['churn_or_switch_intent', 'payment_hardship', 'complaint_or_grievance',
                  'product_interest_upgrade', 'coverage_or_life_event', 'routine_service'],
                  {'task_description': 'Primary intent of the CUSTOMER in this bank / insurance service call'}):labels[0]::STRING AS INTENT,
      IFF(s.IS_COMPLAINT, AI_CLASSIFY(c.TRANSCRIPT_TEXT, ['FEES_AND_CHARGES', 'DIGITAL_SERVICE', 'STAFF_BEHAVIOUR', 'CLAIMS_PROCESSING',
                  'COLLECTIONS_PRACTICE', 'PRODUCT_INFORMATION']):labels[0]::STRING, NULL) AS CATEGORY
    FROM TMP_ENRICH_SCOPE s JOIN CORE.CALL_TRANSCRIPT c USING (TRANSCRIPT_ID)
    WHERE s.RN <= s.QUOTA
    ORDER BY s.AI_ROUTE, s.RN
    LIMIT :MAX_ROWS) e
  ON t.TRANSCRIPT_ID = e.TRANSCRIPT_ID
  WHEN MATCHED THEN UPDATE SET AI_SENTIMENT_SCORE = e.SENT, AI_INTENT = e.INTENT, AI_COMPLAINT_CATEGORY = e.CATEGORY,
                               AI_ENRICHED_AT = CURRENT_TIMESTAMP();
  n_enriched := SQLROWCOUNT;

  INSERT INTO CORE.AI_USAGE_METRICS (COMPONENT, AI_ROUTE, AI_FUNCTION, MODEL, CALLS, EST_TOKENS, LATENCY_MS, SKIPPED, DETAILS)
  SELECT 'ENRICH_TRANSCRIPTS', 'SELECTIVE_AI+FULL_AGENT', 'AI_SENTIMENT+AI_CLASSIFY', 'managed', :n_enriched * 2, :n_enriched * 2 * 260,
         DATEDIFF(ms, :t0, CURRENT_TIMESTAMP()), FALSE, OBJECT_CONSTRUCT('transcripts_enriched', :n_enriched)
  UNION ALL
  SELECT 'ENRICH_TRANSCRIPTS', 'RULES_ONLY', 'AI_SENTIMENT+AI_CLASSIFY', 'skipped', :n_skipped * 2, 0, 0, TRUE,
         OBJECT_CONSTRUCT('transcripts_skipped', :n_skipped, 'reason', 'below enrichment threshold or outside per-customer quota');
  RETURN OBJECT_CONSTRUCT('enriched', :n_enriched, 'skipped_by_routing', :n_skipped);
END;
$$;

-- ---------------------------------------------------------------------
-- Customer context builder (shared by the insight batch, NBA procedure and agent tools)
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW CORE.V_CUSTOMER_CONTEXT AS
WITH ev AS (
  SELECT i.CUSTOMER_ID,
    LISTAGG('- [' || TO_VARCHAR(i.INTERACTION_TS, 'YYYY-MM-DD') || ' ' || i.CHANNEL || ' | ' || i.TOPIC || ' | ' || i.RESOLUTION_STATUS || '] '
            || COALESCE(LEFT(t.TRANSCRIPT_TEXT, 900), i.NOTE), '\n') WITHIN GROUP (ORDER BY i.INTERACTION_TS DESC) EVIDENCE
  FROM (SELECT * FROM CORE.FACT_INTERACTION QUALIFY ROW_NUMBER() OVER (PARTITION BY CUSTOMER_ID ORDER BY INTERACTION_TS DESC) <= 4) i
  LEFT JOIN CORE.CALL_TRANSCRIPT t ON t.INTERACTION_ID = i.INTERACTION_ID
  GROUP BY 1)
SELECT c.CUSTOMER_ID,
  'FACTS:\n' ||
    'Customer ' || c.CUSTOMER_ID || ' (' || c.FULL_NAME || '), segment ' || c.SEGMENT || ', ' || c.INDUSTRY_TYPE || ', tenure ' || c.TENURE_MONTHS || ' months, city ' || c.CITY || '.\n' ||
    'Products: ' || ARRAY_TO_STRING(c.PRODUCTS, ', ') || '. Payment status: ' || c.PAYMENT_STATUS || ' (missed/partial 6m: ' || c.MISSED_6M ||
    ', max days late 90d: ' || c.MAX_DAYS_LATE_90D || ').\n' ||
    'Next renewal/reset: ' || COALESCE(TO_VARCHAR(c.NEXT_RENEWAL_DATE), 'none') || ' (' || COALESCE(c.NEXT_RENEWAL_PRODUCT, '-') || ', in ' || COALESCE(TO_VARCHAR(c.DAYS_TO_RENEWAL), '-') || ' days).\n' ||
    'Interactions 90d: ' || c.INTERACTIONS_90D || ', complaints 90d: ' || c.COMPLAINTS_90D || ', unresolved complaints: ' || c.UNRESOLVED_COUNT ||
    ', escalated: ' || c.ESCALATED_COUNT || ', sentiment: ' || c.SENTIMENT_LABEL || '. Competitor mention: ' || IFF(c.COMPETITOR_MENTION = 1, 'yes', 'no') ||
    '. Life event: ' || IFF(c.LIFE_EVENT = 1, 'yes', 'no') || '. Hardship stated: ' || IFF(c.HARDSHIP_MENTION = 1, 'yes', 'no') || '.\n' ||
    'Primary risk type: ' || c.PRIMARY_RISK_TYPE || ', risk tier ' || c.RISK_TIER || '.\n\nEVIDENCE (most recent interactions):\n' ||
    COALESCE(ev.EVIDENCE, 'No interactions on record.') AS CTX
FROM CORE.CUSTOMER_360 c LEFT JOIN ev USING (CUSTOMER_ID);

-- ---------------------------------------------------------------------
-- LLM insight batch: FULL_AGENT customers only (or a forced single customer)
-- ---------------------------------------------------------------------
CREATE OR REPLACE PROCEDURE CORE.GENERATE_CUSTOMER_INSIGHTS(MAX_CUSTOMERS INT, P_CUSTOMER_ID VARCHAR)
RETURNS VARIANT
LANGUAGE SQL
EXECUTE AS OWNER
AS
$$
DECLARE
  n INT DEFAULT 0;
  t0 TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP();
BEGIN
  CREATE OR REPLACE TEMPORARY TABLE TMP_INSIGHT_SCOPE AS
  SELECT CUSTOMER_ID, CTX FROM CORE.V_CUSTOMER_CONTEXT WHERE CUSTOMER_ID IN (
    SELECT c.CUSTOMER_ID FROM CORE.CUSTOMER_360 c
    LEFT JOIN CORE.CUSTOMER_AI_INSIGHT a USING (CUSTOMER_ID)
    WHERE (:P_CUSTOMER_ID IS NOT NULL AND c.CUSTOMER_ID = :P_CUSTOMER_ID)
       OR (:P_CUSTOMER_ID IS NULL AND c.AI_ROUTE = 'FULL_AGENT' AND a.CUSTOMER_ID IS NULL)
    ORDER BY c.ANNUAL_VALUE_INR DESC LIMIT :MAX_CUSTOMERS);

  MERGE INTO CORE.CUSTOMER_AI_INSIGHT t USING (
    SELECT CUSTOMER_ID, ACTION360_DB.AI.SUMMARIZE_CUSTOMER_RISK(CTX) R FROM TMP_INSIGHT_SCOPE) s
  ON t.CUSTOMER_ID = s.CUSTOMER_ID
  WHEN MATCHED THEN UPDATE SET CUSTOMER_NEED = s.R:customer_need::STRING, KEY_DRIVERS = s.R:key_drivers, PAIN_POINTS = s.R:pain_points,
       LATEST_IMPORTANT_INTERACTION = s.R:latest_important_interaction::STRING, MODEL = 'claude-haiku-4-5', GENERATED_AT = CURRENT_TIMESTAMP()
  WHEN NOT MATCHED THEN INSERT (CUSTOMER_ID, CUSTOMER_NEED, KEY_DRIVERS, PAIN_POINTS, LATEST_IMPORTANT_INTERACTION, MODEL, GENERATED_AT)
       VALUES (s.CUSTOMER_ID, s.R:customer_need::STRING, s.R:key_drivers, s.R:pain_points, s.R:latest_important_interaction::STRING, 'claude-haiku-4-5', CURRENT_TIMESTAMP());
  n := SQLROWCOUNT;

  INSERT INTO CORE.AI_USAGE_METRICS (COMPONENT, AI_ROUTE, AI_FUNCTION, MODEL, CALLS, EST_TOKENS, LATENCY_MS, DETAILS)
  SELECT 'GENERATE_CUSTOMER_INSIGHTS', 'FULL_AGENT', 'AI.SUMMARIZE_CUSTOMER_RISK', 'claude-haiku-4-5', :n,
         COALESCE(SUM(AI_COUNT_TOKENS('ai_complete', 'claude-haiku-4-5', CTX)), 0) + :n * 350, DATEDIFF(ms, :t0, CURRENT_TIMESTAMP()),
         OBJECT_CONSTRUCT('customers', :n)
  FROM TMP_INSIGHT_SCOPE;
  RETURN OBJECT_CONSTRUCT('customers_summarised', :n);
END;
$$;

-- ---------------------------------------------------------------------
-- Incremental, event-driven enrichment: new transcripts -> enrich -> refresh 360
-- ---------------------------------------------------------------------
CREATE OR REPLACE STREAM CORE.CALL_TRANSCRIPT_STREAM ON TABLE CORE.CALL_TRANSCRIPT APPEND_ONLY = TRUE;

CREATE OR REPLACE TASK CORE.ACTION360_ENRICH_TASK
  WAREHOUSE = ACTION360_WH
  SCHEDULE = '60 MINUTE'
  COMMENT = 'Enrich newly landed transcripts (cost-routed) and refresh Customer 360. Skips entirely when no new data.'
  WHEN SYSTEM$STREAM_HAS_DATA('ACTION360_DB.CORE.CALL_TRANSCRIPT_STREAM')
AS
EXECUTE IMMEDIATE $$
BEGIN
  CALL CORE.ENRICH_TRANSCRIPTS(500);
  -- consume the stream offset (DML advances it) so the task only wakes up for genuinely new transcripts
  INSERT INTO CORE.AI_USAGE_METRICS (COMPONENT, AI_ROUTE, CALLS, SKIPPED, DETAILS)
    SELECT 'ENRICH_TASK_STREAM', 'PIPELINE', COUNT(*), FALSE, OBJECT_CONSTRUCT('new_transcripts', COUNT(*)) FROM CORE.CALL_TRANSCRIPT_STREAM;
  ALTER DYNAMIC TABLE CORE.CUSTOMER_360 REFRESH;
END;
$$;
