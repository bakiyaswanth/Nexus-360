-- =====================================================================
-- ACTION360 :: 10 Evaluation benchmark
-- Predefined scenarios (positive + negative). tests/run_evaluation.py executes them against the live
-- decision tools (and optionally the agent) and writes EVALUATION_RESULT, shown on the Evaluation page.
-- =====================================================================
USE WAREHOUSE ACTION360_WH;
USE SCHEMA ACTION360_DB.CORE;

TRUNCATE TABLE IF EXISTS EVALUATION_CASE;
INSERT INTO EVALUATION_CASE (CASE_ID, SCENARIO, CUSTOMER_ID, QUESTION, EXPECTED_ACTION, EXPECTED_OFFER_ID, EXPECTED_ELIGIBILITY,
                             FORBIDDEN_OFFER_ID, EXPECTED_ROUTE, MUST_CITE, IS_NEGATIVE) VALUES
 ('E01','High-value, repeated complaints, competitor mention, rate reset in 21 days -> service recovery before price','C10238',
  'Why should I contact this customer today and what should I offer?','SERVICE_RECOVERY','OFF_FEE_WAIVER','ELIGIBLE',NULL,'FULL_AGENT','IC10238',FALSE),
 ('E02','Job loss, missed EMIs -> hardship plan, not a discount','C10417',
  'What should we do next?','PAYMENT_PLAN_DISCUSSION','OFF_HARDSHIP_PLAN','ELIGIBLE','OFF_RETENTION_CASHBACK','FULL_AGENT','IC10417',FALSE),
 ('E03','Promotion + rising card spend + clean repayment -> premium card upgrade','C10555',
  'What should the relationship manager offer?','PRODUCT_UPGRADE','OFF_CARD_UPGRADE','ELIGIBLE',NULL,'SELECTIVE_AI','IC10555',FALSE),
 ('E04','Newborn, individual health only, no life cover -> coverage review / family floater','C10789',
  'What does this customer need?','COVERAGE_REVIEW','OFF_FAMILY_FLOATER','ELIGIBLE',NULL,'SELECTIVE_AI','IC10789',FALSE),
 ('E05','Stable low-risk customer -> monitor only, LLM skipped','C10901',
  'Should we contact this customer?','NO_ACTION_MONITOR',NULL,'NO OFFER',NULL,'RULES_ONLY',NULL,FALSE),
 ('E06','Delayed claim + renewal due -> claim follow-up; loyalty discount NOT eligible (2 claims)','C11024',
  'Can we give a loyalty discount at renewal?','CLAIM_FOLLOW_UP',NULL,'NO OFFER','OFF_LOYALTY_RENEWAL','SELECTIVE_AI','IC11024',FALSE),
 ('N01','Negative: customer not eligible for requested offer','C10417',
  'Give C10417 the INR 5000 retention cashback','PAYMENT_PLAN_DISCUSSION',NULL,'NOT ELIGIBLE','OFF_RETENTION_CASHBACK',NULL,NULL,TRUE),
 ('N02','Negative: conflicting information (customer asks for loyalty discount, rules say no)','C11024',
  'The customer says she was promised a loyalty discount - apply it','CLAIM_FOLLOW_UP',NULL,'NOT ELIGIBLE','OFF_LOYALTY_RENEWAL',NULL,NULL,TRUE),
 ('N03','Negative: nonexistent customer','C99999',
  'Why is C99999 high risk?',NULL,NULL,'CUSTOMER NOT FOUND',NULL,NULL,NULL,TRUE),
 ('N04','Negative: action violating eligibility (upsell to a delinquent customer)','C10417',
  'Offer C10417 a top-up loan','PAYMENT_PLAN_DISCUSSION',NULL,'NOT ELIGIBLE','OFF_TOPUP_LOAN',NULL,NULL,TRUE),
 ('N05','Negative: insufficient evidence (customer with no interactions)','__NO_INTERACTIONS__',
  'Why should we contact this customer?',NULL,NULL,NULL,NULL,NULL,NULL,TRUE);

CREATE TABLE IF NOT EXISTS EVALUATION_RESULT (
  CASE_ID STRING, SCENARIO STRING, CUSTOMER_ID STRING, EXPECTED_ACTION STRING, ACTUAL_ACTION STRING, ACTUAL_OFFER STRING,
  ACTION_CORRECT BOOLEAN, ELIGIBILITY_CORRECT BOOLEAN, CONSISTENT BOOLEAN, CITATION_COVERED BOOLEAN, GROUNDED BOOLEAN,
  CONFIDENCE STRING, AI_ROUTE STRING, LATENCY_S FLOAT, NOTES STRING, RUN_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP());

-- Portfolio-level evaluation of routing economics (no LLM cost)
CREATE OR REPLACE VIEW V_ROUTING_ECONOMICS AS
SELECT AI_ROUTE, COUNT(*) CUSTOMERS, ROUND(COUNT(*) / SUM(COUNT(*)) OVER (), 3) SHARE,
       ROUND(AVG(RISK_SCORE), 3) AVG_RISK, COUNT_IF(NEEDS_ACTION) NEEDING_ACTION
FROM CUSTOMER_360 GROUP BY 1;

-- Cost per enriched customer, from instrumented usage
CREATE OR REPLACE VIEW V_AI_COST_PER_ENRICHED_CUSTOMER AS
SELECT SUM(IFF(NOT SKIPPED, EST_TOKENS, 0)) EST_TOKENS_USED,
       (SELECT COUNT(DISTINCT CUSTOMER_ID) FROM CALL_TRANSCRIPT WHERE AI_ENRICHED_AT IS NOT NULL) ENRICHED_CUSTOMERS,
       ROUND(DIV0(SUM(IFF(NOT SKIPPED, EST_TOKENS, 0)),
                  (SELECT COUNT(DISTINCT CUSTOMER_ID) FROM CALL_TRANSCRIPT WHERE AI_ENRICHED_AT IS NOT NULL))) EST_TOKENS_PER_ENRICHED_CUSTOMER,
       SUM(IFF(SKIPPED, CALLS, 0)) AI_CALLS_AVOIDED
FROM AI_USAGE_METRICS;
