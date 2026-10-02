-- =====================================================================
-- ACTION360 :: 02 Synthetic data model + generator
-- 100% synthetic, deterministic (hash-seeded) so every run is identical.
-- Behaviour is driven by hidden archetypes (RAW.CUSTOMER_ARCHETYPE) that are
-- used ONLY for generation and evaluation ground truth - never by the engine.
-- =====================================================================
USE WAREHOUSE ACTION360_WH;
USE SCHEMA ACTION360_DB.CORE;

-- As-of date for the whole synthetic universe (keeps dynamic tables deterministic)
MERGE INTO APP_CONFIG t USING (SELECT 'AS_OF_DATE' k, '2026-10-02' v, 'Business date of the synthetic dataset' d) s
ON t.CONFIG_KEY = s.k WHEN NOT MATCHED THEN INSERT (CONFIG_KEY, CONFIG_VALUE, DESCRIPTION) VALUES (s.k, s.v, s.d);

-- Deterministic pseudo-random in [0,1) from a string key
CREATE OR REPLACE FUNCTION CORE.RND(K STRING) RETURNS FLOAT
  AS $$ ((ABS(HASH(K)) % 1000003) / 1000003.0)::FLOAT $$;

-- ---------------------------------------------------------------------
-- Archetypes (hidden ground truth) + personas
-- ---------------------------------------------------------------------
CREATE OR REPLACE TABLE ACTION360_DB.RAW.CUSTOMER_ARCHETYPE AS
WITH g AS (SELECT 'C' || (9999 + ROW_NUMBER() OVER (ORDER BY SEQ4())) AS CID FROM TABLE(GENERATOR(ROWCOUNT => 10000)))
SELECT CID AS CUSTOMER_ID,
  CASE CID WHEN 'C10238' THEN 'SERVICE_DISSATISFIED' WHEN 'C10417' THEN 'PAYMENT_STRESS'
           WHEN 'C10555' THEN 'UPGRADE_READY' WHEN 'C10789' THEN 'COVERAGE_GAP'
           WHEN 'C10901' THEN 'STABLE' WHEN 'C11024' THEN 'RENEWAL_DUE'
  ELSE CASE WHEN r < 0.55 THEN 'STABLE' WHEN r < 0.65 THEN 'PAYMENT_STRESS' WHEN r < 0.75 THEN 'SERVICE_DISSATISFIED'
            WHEN r < 0.83 THEN 'RENEWAL_DUE' WHEN r < 0.92 THEN 'UPGRADE_READY' WHEN r < 0.97 THEN 'COVERAGE_GAP'
            ELSE 'CHURN_SHOPPING' END END AS ARCHETYPE,
  IFF(CID IN ('C10238','C10417','C10555','C10789','C10901','C11024'), TRUE, FALSE) AS IS_DEMO_PERSONA
FROM (SELECT CID, CORE.RND(CID || 'arch') r FROM g);

-- ---------------------------------------------------------------------
-- DIM_CUSTOMER
-- ---------------------------------------------------------------------
CREATE OR REPLACE TABLE DIM_CUSTOMER (
  CUSTOMER_ID STRING PRIMARY KEY, FULL_NAME STRING, GENDER STRING, AGE INT, CITY STRING, STATE STRING,
  SEGMENT STRING, INDUSTRY_TYPE STRING, CUSTOMER_SINCE DATE, TENURE_MONTHS INT, PREFERRED_CHANNEL STRING,
  INCOME_BAND STRING, MONTHLY_INCOME NUMBER(12,0), CREDIT_SCORE INT, EMAIL_MASKED STRING, PHONE_MASKED STRING,
  IS_SYNTHETIC BOOLEAN DEFAULT TRUE) COMMENT = 'Synthetic customer master (de-identified)';

INSERT INTO DIM_CUSTOMER
WITH a AS (SELECT a.*, CORE.RND(CUSTOMER_ID||'r1') r1, CORE.RND(CUSTOMER_ID||'r2') r2, CORE.RND(CUSTOMER_ID||'r3') r3,
                  CORE.RND(CUSTOMER_ID||'r4') r4, CORE.RND(CUSTOMER_ID||'r5') r5, CORE.RND(CUSTOMER_ID||'r6') r6
           FROM ACTION360_DB.RAW.CUSTOMER_ARCHETYPE a),
fn AS (SELECT ['Aarav','Vivaan','Aditya','Arjun','Sai','Reyansh','Krishna','Ishaan','Rohan','Karthik','Rahul','Vikram','Nikhil','Pranav','Harsha',
               'Ananya','Diya','Saanvi','Aadhya','Kavya','Priya','Meera','Sneha','Divya','Lakshmi','Pooja','Nandini','Riya','Shreya','Keerthi'] f,
              ['Sharma','Reddy','Iyer','Nair','Patel','Gupta','Rao','Menon','Kumar','Singh','Das','Joshi','Pillai','Verma','Naidu',
               'Shetty','Kulkarni','Bose','Mehta','Chopra'] l,
              ['Bengaluru','Hyderabad','Chennai','Pune','Mumbai','Gurugram','Kolkata','Ahmedabad','Kochi','Jaipur','Lucknow','Coimbatore'] c,
              ['Karnataka','Telangana','Tamil Nadu','Maharashtra','Maharashtra','Haryana','West Bengal','Gujarat','Kerala','Rajasthan','Uttar Pradesh','Tamil Nadu'] s),
b AS (
  SELECT a.*, fn.*,
    CASE CUSTOMER_ID WHEN 'C10789' THEN 'INSURANCE' WHEN 'C11024' THEN 'INSURANCE'
      WHEN 'C10238' THEN 'LENDING' WHEN 'C10417' THEN 'LENDING' WHEN 'C10555' THEN 'LENDING' WHEN 'C10901' THEN 'LENDING'
      ELSE IFF(ARCHETYPE = 'COVERAGE_GAP', IFF(r1 < 0.8, 'INSURANCE', 'LENDING'), IFF(r1 < 0.7, 'LENDING', 'INSURANCE')) END AS IND,
    CASE CUSTOMER_ID WHEN 'C10238' THEN 'PREMIER' WHEN 'C10417' THEN 'MASS' WHEN 'C10555' THEN 'AFFLUENT'
      WHEN 'C10789' THEN 'AFFLUENT' WHEN 'C10901' THEN 'MASS' WHEN 'C11024' THEN 'AFFLUENT'
      ELSE CASE WHEN r2 < 0.50 THEN 'MASS' WHEN r2 < 0.80 THEN 'AFFLUENT' WHEN r2 < 0.92 THEN 'PREMIER' ELSE 'SME' END END AS SEG
  FROM a, fn)
SELECT CUSTOMER_ID,
  IFF(r3 < 0.5, f[FLOOR(r4*15)::INT], f[15 + FLOOR(r4*15)::INT])::STRING || ' ' || l[FLOOR(r5*20)::INT]::STRING,
  IFF(r3 < 0.5, 'M', 'F'),
  CASE CUSTOMER_ID WHEN 'C10238' THEN 46 WHEN 'C10417' THEN 31 WHEN 'C10555' THEN 36 WHEN 'C10789' THEN 33 WHEN 'C10901' THEN 52 WHEN 'C11024' THEN 44
       ELSE 22 + FLOOR(r6 * 46)::INT END,
  c[FLOOR(r5*12)::INT]::STRING, s[FLOOR(r5*12)::INT]::STRING,
  SEG, IND,
  DATEADD(month, -TEN, '2026-10-02'::DATE), TEN,
  CASE FLOOR(r4*5)::INT WHEN 0 THEN 'APP' WHEN 1 THEN 'EMAIL' WHEN 2 THEN 'CALL' WHEN 3 THEN 'WHATSAPP' ELSE 'BRANCH' END,
  CASE SEG WHEN 'MASS' THEN 'INR 3-10L' WHEN 'AFFLUENT' THEN 'INR 10-30L' WHEN 'PREMIER' THEN 'INR 30L+' ELSE 'SME' END,
  ROUND(CASE SEG WHEN 'MASS' THEN 30000 + r6*50000 WHEN 'AFFLUENT' THEN 90000 + r6*140000 WHEN 'PREMIER' THEN 260000 + r6*300000 ELSE 150000 + r6*250000 END, -2),
  CASE CUSTOMER_ID WHEN 'C10417' THEN 612 WHEN 'C10555' THEN 802 WHEN 'C10238' THEN 781
       ELSE CASE ARCHETYPE WHEN 'PAYMENT_STRESS' THEN 560 + FLOOR(r3*120)::INT WHEN 'UPGRADE_READY' THEN 752 + FLOOR(r3*88)::INT ELSE 650 + FLOOR(r3*170)::INT END END,
  'user' || SUBSTR(CUSTOMER_ID, 2) || '@example.invalid', '+91-XXXXXX' || SUBSTR(CUSTOMER_ID, 3), TRUE
FROM (SELECT b.*, CASE CUSTOMER_ID WHEN 'C10238' THEN 96 WHEN 'C10417' THEN 20 WHEN 'C10555' THEN 54 WHEN 'C10789' THEN 30 WHEN 'C10901' THEN 120 WHEN 'C11024' THEN 72
                     ELSE 3 + FLOOR(CORE.RND(CUSTOMER_ID||'ten') * 177)::INT END AS TEN FROM b);

-- ---------------------------------------------------------------------
-- Product catalog (shared lender / insurer model)
-- ---------------------------------------------------------------------
CREATE OR REPLACE TABLE DIM_PRODUCT (PRODUCT_CODE STRING PRIMARY KEY, PRODUCT_NAME STRING, INDUSTRY_TYPE STRING, PRODUCT_FAMILY STRING, IS_SECURED BOOLEAN);
INSERT INTO DIM_PRODUCT VALUES
 ('HL','Home Loan','LENDING','LOAN',TRUE),('PL','Personal Loan','LENDING','LOAN',FALSE),('AL','Auto Loan','LENDING','LOAN',TRUE),
 ('CC','Credit Card','LENDING','CARD',FALSE),
 ('MOTOR','Motor Insurance','INSURANCE','GENERAL',FALSE),('HEALTH','Individual Health Insurance','INSURANCE','HEALTH',FALSE),
 ('FAMILY_FLOATER','Family Floater Health Insurance','INSURANCE','HEALTH',FALSE),('TERM_LIFE','Term Life Insurance','INSURANCE','LIFE',FALSE),
 ('HOME_INS','Home Insurance','INSURANCE','GENERAL',FALSE);

-- ---------------------------------------------------------------------
-- FACT_ACCOUNT  (loan / card / policy contracts)
-- ---------------------------------------------------------------------
CREATE OR REPLACE TABLE FACT_ACCOUNT (
  ACCOUNT_ID STRING PRIMARY KEY, CUSTOMER_ID STRING, INDUSTRY_TYPE STRING, PRODUCT_CODE STRING, OPEN_DATE DATE, STATUS STRING,
  PRINCIPAL_OR_SUM_ASSURED NUMBER(14,0), OUTSTANDING_BALANCE NUMBER(14,0), INTEREST_RATE NUMBER(5,2),
  MONTHLY_INSTALMENT NUMBER(12,0), RENEWAL_OR_RESET_DATE DATE) COMMENT = 'Loan / card / policy contracts. RENEWAL_OR_RESET_DATE = policy renewal, card renewal or loan rate-reset date';

INSERT INTO FACT_ACCOUNT
WITH slots AS (
  SELECT c.CUSTOMER_ID, c.INDUSTRY_TYPE, c.SEGMENT, c.TENURE_MONTHS, a.ARCHETYPE, s.n AS SLOT,
         CORE.RND(c.CUSTOMER_ID||'p'||s.n) rp, CORE.RND(c.CUSTOMER_ID||'amt'||s.n) ra, CORE.RND(c.CUSTOMER_ID||'ren'||s.n) rr,
         CORE.RND(c.CUSTOMER_ID||'np') rn
  FROM DIM_CUSTOMER c JOIN ACTION360_DB.RAW.CUSTOMER_ARCHETYPE a USING (CUSTOMER_ID)
  CROSS JOIN (SELECT 1 n UNION ALL SELECT 2 UNION ALL SELECT 3) s),
picked AS (
  SELECT *,
    CASE CUSTOMER_ID WHEN 'C10238' THEN 3 WHEN 'C10417' THEN 1 WHEN 'C10555' THEN 2 WHEN 'C10789' THEN 1 WHEN 'C10901' THEN 1 WHEN 'C11024' THEN 2
      ELSE IFF(ARCHETYPE = 'COVERAGE_GAP', 1, 1 + IFF(rn < IFF(SEGMENT IN ('AFFLUENT','PREMIER'), 0.55, 0.25), 1, 0) + IFF(SEGMENT = 'PREMIER' AND rn < 0.30, 1, 0)) END AS NPROD,
    CASE
      WHEN CUSTOMER_ID = 'C10238' THEN DECODE(SLOT, 1, 'HL', 2, 'PL', 'CC')
      WHEN CUSTOMER_ID = 'C10417' THEN 'PL'
      WHEN CUSTOMER_ID = 'C10555' THEN DECODE(SLOT, 1, 'CC', 'PL')
      WHEN CUSTOMER_ID = 'C10789' THEN 'HEALTH'
      WHEN CUSTOMER_ID = 'C10901' THEN 'AL'
      WHEN CUSTOMER_ID = 'C11024' THEN DECODE(SLOT, 1, 'MOTOR', 'HOME_INS')
      WHEN INDUSTRY_TYPE = 'LENDING' THEN
        CASE SLOT WHEN 1 THEN CASE WHEN ARCHETYPE = 'UPGRADE_READY' THEN IFF(rp < 0.6, 'CC', 'PL') WHEN rp < 0.30 THEN 'HL' WHEN rp < 0.65 THEN 'PL' WHEN rp < 0.80 THEN 'AL' ELSE 'CC' END
                  WHEN 2 THEN 'CC' ELSE 'HL' END
      ELSE
        CASE SLOT WHEN 1 THEN CASE WHEN ARCHETYPE = 'COVERAGE_GAP' THEN IFF(rp < 0.6, 'HEALTH', 'MOTOR') WHEN rp < 0.35 THEN 'MOTOR' WHEN rp < 0.65 THEN 'HEALTH' WHEN rp < 0.85 THEN 'TERM_LIFE' ELSE 'HOME_INS' END
                  WHEN 2 THEN 'HEALTH' ELSE 'TERM_LIFE' END
    END AS P
  FROM slots),
dedup AS (SELECT * FROM picked WHERE SLOT <= NPROD QUALIFY ROW_NUMBER() OVER (PARTITION BY CUSTOMER_ID, P ORDER BY SLOT) = 1),
amt AS (
  SELECT *, IFF(SEGMENT = 'PREMIER', 1.8, IFF(SEGMENT = 'MASS', 0.7, 1.0)) AS M,
    CASE P WHEN 'HL' THEN 2500000 + ra*6500000 WHEN 'PL' THEN 150000 + ra*1350000 WHEN 'AL' THEN 400000 + ra*1200000 WHEN 'CC' THEN 50000 + ra*550000
           WHEN 'MOTOR' THEN 500000 + ra*1500000 WHEN 'HEALTH' THEN 500000 + ra*1000000 WHEN 'TERM_LIFE' THEN 5000000 + ra*15000000 ELSE 2000000 + ra*6000000 END AS BASE_AMT
  FROM dedup)
SELECT 'A' || CUSTOMER_ID || '-' || SLOT, CUSTOMER_ID, INDUSTRY_TYPE, P,
  DATEADD(day, -FLOOR(TENURE_MONTHS * 30 * (0.3 + 0.7*ra))::INT, '2026-10-02'::DATE), 'ACTIVE',
  ROUND(BASE_AMT * M, -3),
  ROUND(CASE WHEN P IN ('HL','PL','AL') THEN BASE_AMT * M * (0.35 + 0.55*rr) WHEN P = 'CC' THEN BASE_AMT * M * (0.05 + 0.55*rr) ELSE 0 END, -2),
  CASE P WHEN 'HL' THEN 8.40 + ROUND(rr*1.2, 2) WHEN 'PL' THEN 11.50 + ROUND(rr*5, 2) WHEN 'AL' THEN 9.10 + ROUND(rr*2, 2) WHEN 'CC' THEN 36.00 ELSE NULL END,
  ROUND(CASE P WHEN 'HL' THEN BASE_AMT*M*0.0085 WHEN 'PL' THEN BASE_AMT*M*0.03 WHEN 'AL' THEN BASE_AMT*M*0.022 WHEN 'CC' THEN BASE_AMT*M*0.05*(0.05+0.55*rr)
               WHEN 'MOTOR' THEN 1500 + ra*2000 WHEN 'HEALTH' THEN 1200 + ra*2800 WHEN 'TERM_LIFE' THEN 1000 + ra*2000 ELSE 600 + ra*900 END, -1),
  CASE
    WHEN CUSTOMER_ID = 'C10238' AND P = 'HL' THEN '2026-10-23'::DATE
    WHEN CUSTOMER_ID = 'C11024' AND P = 'MOTOR' THEN '2026-10-30'::DATE
    WHEN ARCHETYPE = 'RENEWAL_DUE' AND SLOT = 1 THEN DATEADD(day, 7 + FLOOR(rr*48)::INT, '2026-10-02'::DATE)
    ELSE DATEADD(day, 60 + FLOOR(rr*305)::INT, '2026-10-02'::DATE) END
FROM amt;

-- Product holdings (one row per customer x product family; convenience for Customer 360 / gaps)
CREATE OR REPLACE TABLE FACT_PRODUCT_HOLDING AS
SELECT a.CUSTOMER_ID, a.PRODUCT_CODE, p.PRODUCT_NAME, p.PRODUCT_FAMILY, a.INDUSTRY_TYPE, a.ACCOUNT_ID, a.OPEN_DATE, a.STATUS
FROM FACT_ACCOUNT a JOIN DIM_PRODUCT p USING (PRODUCT_CODE);

-- ---------------------------------------------------------------------
-- FACT_PAYMENT  (12 monthly instalments / premiums per account)
-- ---------------------------------------------------------------------
CREATE OR REPLACE TABLE FACT_PAYMENT (
  PAYMENT_ID STRING, ACCOUNT_ID STRING, CUSTOMER_ID STRING, DUE_DATE DATE, PAID_DATE DATE,
  AMOUNT_DUE NUMBER(12,0), AMOUNT_PAID NUMBER(12,0), DAYS_LATE INT, PAYMENT_STATUS STRING);

INSERT INTO FACT_PAYMENT
WITH m AS (SELECT ROW_NUMBER() OVER (ORDER BY SEQ4()) AS MAGO FROM TABLE(GENERATOR(ROWCOUNT => 12))),
x AS (
  SELECT f.ACCOUNT_ID, f.CUSTOMER_ID, f.MONTHLY_INSTALMENT, ar.ARCHETYPE, m.MAGO,
         DATE_FROM_PARTS(YEAR(DATEADD(month, -m.MAGO, '2026-10-02'::DATE)), MONTH(DATEADD(month, -m.MAGO, '2026-10-02'::DATE)), 5) AS DUE,
         CORE.RND(f.ACCOUNT_ID||'pay'||m.MAGO) r, CORE.RND(f.ACCOUNT_ID||'late'||m.MAGO) r2
  FROM FACT_ACCOUNT f JOIN ACTION360_DB.RAW.CUSTOMER_ARCHETYPE ar USING (CUSTOMER_ID) CROSS JOIN m),
y AS (
  SELECT *, CASE
     WHEN CUSTOMER_ID = 'C10417' AND MAGO <= 2 THEN 'MISSED'
     WHEN CUSTOMER_ID = 'C10417' AND MAGO = 3 THEN 'LATE'
     WHEN CUSTOMER_ID IN ('C10238','C10555','C10901','C10789','C11024') THEN 'ON_TIME'
     WHEN ARCHETYPE = 'PAYMENT_STRESS' AND MAGO <= 3 THEN CASE WHEN r < 0.30 THEN 'MISSED' WHEN r < 0.55 THEN 'PARTIAL' WHEN r < 0.85 THEN 'LATE' ELSE 'ON_TIME' END
     WHEN ARCHETYPE = 'PAYMENT_STRESS' THEN IFF(r < 0.15, 'LATE', 'ON_TIME')
     ELSE IFF(r < 0.04, 'LATE', 'ON_TIME') END AS ST
  FROM x)
SELECT ACCOUNT_ID || '-P' || MAGO, ACCOUNT_ID, CUSTOMER_ID, DUE,
  CASE ST WHEN 'MISSED' THEN NULL WHEN 'LATE' THEN DATEADD(day, IFF(ARCHETYPE = 'PAYMENT_STRESS', 8 + FLOOR(r2*40)::INT, 1 + FLOOR(r2*5)::INT), DUE) ELSE DUE END,
  MONTHLY_INSTALMENT,
  CASE ST WHEN 'MISSED' THEN 0 WHEN 'PARTIAL' THEN ROUND(MONTHLY_INSTALMENT * (0.3 + 0.4*r2), -1) ELSE MONTHLY_INSTALMENT END,
  CASE ST WHEN 'MISSED' THEN DATEDIFF(day, DUE, '2026-10-02'::DATE) WHEN 'LATE' THEN IFF(ARCHETYPE = 'PAYMENT_STRESS', 8 + FLOOR(r2*40)::INT, 1 + FLOOR(r2*5)::INT)
          WHEN 'PARTIAL' THEN DATEDIFF(day, DUE, '2026-10-02'::DATE) ELSE 0 END,
  ST
FROM y;

-- ---------------------------------------------------------------------
-- FACT_TRANSACTION  (6 months of linked-account activity, lending customers)
-- ---------------------------------------------------------------------
CREATE OR REPLACE TABLE FACT_TRANSACTION (
  TXN_ID STRING, CUSTOMER_ID STRING, TXN_DATE DATE, TXN_TYPE STRING, CATEGORY STRING, AMOUNT NUMBER(12,0), CHANNEL STRING);

INSERT INTO FACT_TRANSACTION
WITH m AS (SELECT ROW_NUMBER() OVER (ORDER BY SEQ4()) - 1 AS MAGO FROM TABLE(GENERATOR(ROWCOUNT => 6))),
k AS (SELECT 1 KIND UNION ALL SELECT 2 UNION ALL SELECT 3 UNION ALL SELECT 4),
x AS (
  SELECT c.CUSTOMER_ID, c.MONTHLY_INCOME, a.ARCHETYPE, m.MAGO, k.KIND, CORE.RND(c.CUSTOMER_ID||'t'||m.MAGO||k.KIND) r
  FROM DIM_CUSTOMER c JOIN ACTION360_DB.RAW.CUSTOMER_ARCHETYPE a USING (CUSTOMER_ID) CROSS JOIN m CROSS JOIN k
  WHERE c.INDUSTRY_TYPE = 'LENDING')
SELECT 'T' || CUSTOMER_ID || '-' || MAGO || '-' || KIND, CUSTOMER_ID,
  DATEADD(day, -(MAGO*30 + KIND*6), '2026-10-01'::DATE),
  IFF(KIND = 1, 'CREDIT', 'DEBIT'),
  DECODE(KIND, 1, 'SALARY_CREDIT', 2, 'CARD_SPEND', 3, 'UPI_SPEND', 'TRANSFER_TO_OTHER_BANK'),
  ROUND(CASE KIND
    WHEN 1 THEN MONTHLY_INCOME * IFF(ARCHETYPE = 'UPGRADE_READY', 1 - 0.04*MAGO, 1)
    WHEN 2 THEN MONTHLY_INCOME * (0.10 + 0.10*r) * IFF(ARCHETYPE = 'UPGRADE_READY', 1.6 - 0.1*MAGO, 1)
    WHEN 3 THEN MONTHLY_INCOME * (0.05 + 0.08*r)
    ELSE MONTHLY_INCOME * IFF(ARCHETYPE IN ('CHURN_SHOPPING','SERVICE_DISSATISFIED') AND MAGO <= 2, 0.35 + 0.25*r, 0.02 + 0.05*r) END, -1),
  DECODE(KIND, 1, 'NEFT', 2, 'CARD', 3, 'UPI', 'IMPS')
FROM x
-- payment-stressed customers lost salary credits in the last two months (job loss)
WHERE NOT (KIND = 1 AND ARCHETYPE = 'PAYMENT_STRESS' AND MAGO <= 1 AND (CUSTOMER_ID = 'C10417' OR r < 0.6));

-- ---------------------------------------------------------------------
-- FACT_CLAIM_OR_LOAN_EVENT  (servicing / claims lifecycle)
-- ---------------------------------------------------------------------
CREATE OR REPLACE TABLE FACT_CLAIM_OR_LOAN_EVENT (
  EVENT_ID STRING, CUSTOMER_ID STRING, ACCOUNT_ID STRING, INDUSTRY_TYPE STRING, EVENT_TYPE STRING, EVENT_DATE DATE,
  EVENT_STATUS STRING, AMOUNT NUMBER(12,0), DETAILS STRING);

INSERT INTO FACT_CLAIM_OR_LOAN_EVENT
WITH acc AS (SELECT CUSTOMER_ID, MIN(ACCOUNT_ID) ACCOUNT_ID, MAX(OUTSTANDING_BALANCE) BAL FROM FACT_ACCOUNT GROUP BY 1),
ev AS (
  SELECT * FROM (VALUES
   ('PAYMENT_STRESS','LENDING','RESTRUCTURE_REQUEST','OPEN',0.55,'Customer requested EMI restructuring / moratorium'),
   ('PAYMENT_STRESS','INSURANCE','PREMIUM_DEFERRAL_REQUEST','OPEN',0.45,'Customer asked to defer premium'),
   ('SERVICE_DISSATISFIED','LENDING','FEE_DISPUTE','OPEN',0.60,'Disputed processing / late fee charge'),
   ('SERVICE_DISSATISFIED','INSURANCE','CLAIM_DELAYED','OPEN',0.55,'Claim pending beyond SLA'),
   ('CHURN_SHOPPING','LENDING','FORECLOSURE_ENQUIRY','OPEN',0.80,'Asked for foreclosure statement / balance transfer letter'),
   ('CHURN_SHOPPING','INSURANCE','CANCELLATION_ENQUIRY','OPEN',0.75,'Asked about policy cancellation and refund'),
   ('UPGRADE_READY','LENDING','TOPUP_ENQUIRY','OPEN',0.50,'Enquired about top-up loan / limit increase'),
   ('RENEWAL_DUE','INSURANCE','CLAIM_DELAYED','OPEN',0.30,'Claim settlement pending'),
   ('RENEWAL_DUE','LENDING','DOCUMENT_PENDING','OPEN',0.30,'Income proof pending for rate reset'),
   ('COVERAGE_GAP','INSURANCE','ENDORSEMENT_REQUEST','OPEN',0.40,'Asked to add a family member'),
   ('STABLE','LENDING','PREPAYMENT','CLOSED',0.10,'Part prepayment made'),
   ('STABLE','INSURANCE','CLAIM_SETTLED','CLOSED',0.10,'Claim settled within SLA')
  ) v(ARCH, IND, ETYPE, ESTATUS, PROB, DETAILS))
SELECT 'E' || c.CUSTOMER_ID || '-' || ev.ETYPE, c.CUSTOMER_ID, acc.ACCOUNT_ID, c.INDUSTRY_TYPE, ev.ETYPE,
  DATEADD(day, -(3 + FLOOR(CORE.RND(c.CUSTOMER_ID||ev.ETYPE||'d')*60)::INT), '2026-10-02'::DATE), ev.ESTATUS,
  ROUND(IFF(ev.ETYPE LIKE 'CLAIM%', 20000 + CORE.RND(c.CUSTOMER_ID||'cl')*180000, acc.BAL * 0.1), -2), ev.DETAILS
FROM DIM_CUSTOMER c JOIN ACTION360_DB.RAW.CUSTOMER_ARCHETYPE a USING (CUSTOMER_ID) JOIN acc USING (CUSTOMER_ID)
JOIN ev ON ev.ARCH = a.ARCHETYPE AND ev.IND = c.INDUSTRY_TYPE
WHERE NOT a.IS_DEMO_PERSONA AND CORE.RND(c.CUSTOMER_ID||ev.ETYPE) < ev.PROB;

-- ---------------------------------------------------------------------
-- Interaction templates (realistic, archetype-specific language)
-- {NAME} {PRODUCT} are substituted at generation time.
-- ---------------------------------------------------------------------
CREATE OR REPLACE TABLE ACTION360_DB.RAW.INTERACTION_TEMPLATE (
  TEMPLATE_ID STRING, ARCHETYPE STRING, INDUSTRY_TYPE STRING, CHANNEL STRING, TOPIC STRING, IS_COMPLAINT BOOLEAN,
  RESOLUTION_STATUS STRING, RULE_SENTIMENT FLOAT, NOTE STRING, TRANSCRIPT STRING);

INSERT INTO ACTION360_DB.RAW.INTERACTION_TEMPLATE VALUES
-- STABLE
('ST-L1','STABLE','LENDING','APP','Statement request',FALSE,'RESOLVED',0.3,'Downloaded annual interest certificate via app.',NULL),
('ST-L2','STABLE','LENDING','CALL','Address update',FALSE,'RESOLVED',0.5,'Updated communication address. Customer satisfied.',
 'AGENT: Thank you for calling, how can I help you today?\nCUSTOMER: Hi, I moved recently and want to update my address on the {PRODUCT}.\nAGENT: Sure, I have sent a verification link to your registered mobile.\nCUSTOMER: Got it, done. That was quick, thanks.\nAGENT: Your address is updated. Anything else?\nCUSTOMER: No, that is all. Great service as always.'),
('ST-L3','STABLE','LENDING','EMAIL','Interest rate query',FALSE,'RESOLVED',0.1,'Asked about current rate on {PRODUCT}; explained.',NULL),
('ST-I1','STABLE','INSURANCE','APP','Policy document download',FALSE,'RESOLVED',0.3,'Downloaded policy schedule.',NULL),
('ST-I2','STABLE','INSURANCE','CALL','Nominee update',FALSE,'RESOLVED',0.5,'Nominee updated on {PRODUCT}.',
 'AGENT: Good morning, thank you for calling.\nCUSTOMER: Hello, I want to change the nominee on my {PRODUCT} to my spouse.\nAGENT: Certainly. I have raised the request and you will get an e-sign link.\nCUSTOMER: Perfect. Your app has been really easy to use.\nAGENT: Glad to hear that. The update will reflect in 24 hours.\nCUSTOMER: Thanks, have a good day.'),
('ST-I3','STABLE','INSURANCE','EMAIL','Tax certificate',FALSE,'RESOLVED',0.2,'Requested premium paid certificate for tax.',NULL),
-- PAYMENT_STRESS
('PS-L1','PAYMENT_STRESS','LENDING','CALL','Payment difficulty',FALSE,'OPEN',-0.5,'Customer reports income disruption, cannot pay EMI this month.',
 'AGENT: Hello, this is a courtesy call about the EMI on your {PRODUCT} that is overdue.\nCUSTOMER: Yes, I know. I lost my job last month and my salary has stopped.\nAGENT: I am sorry to hear that. Are you able to make a partial payment?\nCUSTOMER: Honestly not right now. I do not want to default, I have always paid on time before.\nCUSTOMER: Is there any way to reduce the EMI or get a few months break until I find a new job?\nAGENT: Let me note this and check what restructuring options are available.\nCUSTOMER: Please do. I am really stressed about the late fees and my credit score.'),
('PS-L2','PAYMENT_STRESS','LENDING','CALL','Late fee complaint',TRUE,'OPEN',-0.6,'Disputes late payment fee and collection calls frequency.',
 'AGENT: Thank you for calling, how may I help?\nCUSTOMER: I am getting collection calls three times a day about my {PRODUCT}. It is embarrassing.\nAGENT: I understand. I can see two instalments are pending.\nCUSTOMER: I already told your team I am between jobs. Charging late fees on top makes it worse.\nCUSTOMER: I want a payment plan, not more penalties.\nAGENT: I will raise a hardship review request for you.\nCUSTOMER: Please, and stop the repeated calls.'),
('PS-L3','PAYMENT_STRESS','LENDING','APP','Payment failed',FALSE,'RESOLVED',-0.2,'Auto-debit bounced due to insufficient funds.',NULL),
('PS-I1','PAYMENT_STRESS','INSURANCE','CALL','Premium deferral',FALSE,'OPEN',-0.4,'Asked to defer premium due to medical expenses.',
 'AGENT: Hello, your premium for {PRODUCT} is past the due date.\nCUSTOMER: Yes, we had big hospital bills this quarter and money is tight.\nCUSTOMER: I do not want the policy to lapse. Can I pay in instalments?\nAGENT: There is a grace period and we may be able to switch you to monthly mode.\nCUSTOMER: That would really help. Please do not cancel the cover.'),
('PS-I2','PAYMENT_STRESS','INSURANCE','EMAIL','Grace period query',FALSE,'RESOLVED',-0.2,'Asked about grace period before lapse.',NULL),
-- SERVICE_DISSATISFIED
('SD-L1','SERVICE_DISSATISFIED','LENDING','CALL','Fee dispute',TRUE,'OPEN',-0.7,'Disputes processing fee charged without consent; reversal promised but not done.',
 'AGENT: Thank you for calling, how can I help you?\nCUSTOMER: This is the third time I am calling about a fee charged on my {PRODUCT} that I never agreed to.\nAGENT: I can see the earlier complaint. A reversal was requested.\nCUSTOMER: Requested two weeks ago and nothing has happened. Nobody calls back.\nCUSTOMER: I have been a customer for years and I am honestly thinking of moving my loan to another bank.\nAGENT: I apologise. I will escalate this to my supervisor today.\nCUSTOMER: I have heard that before. I want it fixed this week.'),
('SD-L2','SERVICE_DISSATISFIED','LENDING','CHAT','App outage',TRUE,'RESOLVED',-0.5,'Could not access app for 2 days; EMI auto-debit status unclear.',NULL),
('SD-L3','SERVICE_DISSATISFIED','LENDING','CALL','Agent behaviour complaint',TRUE,'ESCALATED',-0.8,'Complained that a branch executive was rude and dismissive.',
 'AGENT: Hello, I understand you want to raise a complaint.\nCUSTOMER: Yes. I visited the branch about my {PRODUCT} statement and the executive was rude and dismissive.\nCUSTOMER: He told me to just check the app, which was not even working.\nAGENT: I am very sorry. I am registering a formal complaint.\nCUSTOMER: I expect better service for the amount of business I do with you.\nAGENT: This has been escalated to the branch manager.'),
('SD-I1','SERVICE_DISSATISFIED','INSURANCE','CALL','Claim delay',TRUE,'OPEN',-0.7,'Claim pending for 5 weeks; repeated document requests.',
 'AGENT: Thank you for calling, how can I help?\nCUSTOMER: My claim on {PRODUCT} has been pending for five weeks.\nCUSTOMER: Every time I call I am asked for the same documents again.\nAGENT: I can see the claim is under review with the surveyor.\nCUSTOMER: This is unacceptable. I pay my premium on time and when I need you nobody helps.\nCUSTOMER: If this is not settled I will not renew and I will tell my friends too.\nAGENT: I will escalate this to the claims manager.'),
('SD-I2','SERVICE_DISSATISFIED','INSURANCE','EMAIL','Repeated document request',TRUE,'OPEN',-0.5,'Asked again for documents already submitted.',NULL),
-- RENEWAL_DUE
('RD-L1','RENEWAL_DUE','LENDING','CALL','Rate reset query',FALSE,'RESOLVED',-0.1,'Asked what new rate will apply after fixed period on {PRODUCT} ends.',
 'AGENT: Hello, how can I help?\nCUSTOMER: My fixed rate period on the {PRODUCT} ends soon. What rate will apply after that?\nAGENT: It will move to the floating benchmark plus your spread.\nCUSTOMER: That will increase my EMI. Other lenders are advertising lower rates right now.\nAGENT: I will share the details and check if any retention pricing is available.\nCUSTOMER: Please do, I need to decide before the reset.'),
('RD-L2','RENEWAL_DUE','LENDING','EMAIL','Document pending',FALSE,'OPEN',0.0,'Income proof requested for rate reset review.',NULL),
('RD-I1','RENEWAL_DUE','INSURANCE','CALL','Renewal premium query',FALSE,'RESOLVED',-0.2,'Asked why renewal premium on {PRODUCT} increased.',
 'AGENT: Thank you for calling.\nCUSTOMER: I got the renewal notice for my {PRODUCT}. The premium has gone up quite a bit.\nAGENT: The increase reflects claims during the year and the updated vehicle value.\nCUSTOMER: I am still waiting on my last claim to be settled and now I have to pay more?\nCUSTOMER: Is there any loyalty discount? I have been with you for years.\nAGENT: Let me check what options are available before your renewal date.'),
('RD-I2','RENEWAL_DUE','INSURANCE','APP','Renewal reminder viewed',FALSE,'RESOLVED',0.0,'Viewed renewal quote in app, did not complete.',NULL),
-- UPGRADE_READY
('UR-L1','UPGRADE_READY','LENDING','CALL','Limit increase',FALSE,'RESOLVED',0.5,'Asked about increasing card limit and premium card benefits.',
 'AGENT: Hello, thank you for calling.\nCUSTOMER: Hi, I have been using my {PRODUCT} a lot more for travel and I keep hitting the limit.\nCUSTOMER: Do you have a card with better travel rewards and lounge access?\nAGENT: You may qualify for our premium travel card based on your history.\nCUSTOMER: That sounds great. I also got a promotion recently so my income has gone up.\nAGENT: Wonderful, I will note your interest.'),
('UR-L2','UPGRADE_READY','LENDING','APP','Top-up loan enquiry',FALSE,'RESOLVED',0.4,'Viewed pre-approved top-up loan page twice.',NULL),
('UR-I1','UPGRADE_READY','INSURANCE','CALL','Sum insured increase',FALSE,'RESOLVED',0.4,'Asked about increasing sum insured on {PRODUCT}.',
 'AGENT: Good afternoon.\nCUSTOMER: I want to understand if I can increase the cover on my {PRODUCT}. My income has gone up.\nAGENT: Yes, you can increase the sum insured at renewal or now with a short form.\nCUSTOMER: Great, please send me the options.'),
-- COVERAGE_GAP
('CG-I1','COVERAGE_GAP','INSURANCE','CALL','Add family member',FALSE,'OPEN',0.3,'Asked to add newborn to individual health policy.',
 'AGENT: Hello, how can I help you today?\nCUSTOMER: We just had a baby last month and I want to make sure she is covered.\nCUSTOMER: Right now I only have an individual {PRODUCT}. Can I add my wife and daughter?\nAGENT: An individual policy cannot add members, but a family floater plan can cover all of you.\nCUSTOMER: I also do not have any life cover. With a child now I think I need it.\nAGENT: I will arrange for an advisor to walk you through family options.\nCUSTOMER: Yes please, I want this sorted soon.'),
('CG-I2','COVERAGE_GAP','INSURANCE','EMAIL','Coverage question',FALSE,'RESOLVED',0.1,'Asked whether maternity and newborn expenses are covered.',NULL),
('CG-L1','COVERAGE_GAP','LENDING','CALL','Loan protection query',FALSE,'RESOLVED',0.1,'Asked what happens to {PRODUCT} if something happens to them; no protection cover.',
 'AGENT: Hello, thank you for calling.\nCUSTOMER: I recently got married and I was wondering what happens to my {PRODUCT} if something happens to me.\nAGENT: Currently there is no credit protection cover linked to your loan.\nCUSTOMER: I would not want my family to be burdened. What options are there?\nAGENT: I can share our loan protection and term cover options.'),
-- CHURN_SHOPPING
('CS-L1','CHURN_SHOPPING','LENDING','CALL','Foreclosure enquiry',FALSE,'OPEN',-0.4,'Requested foreclosure statement; mentioned balance transfer offer from competitor.',
 'AGENT: Hello, how may I help you?\nCUSTOMER: I need the foreclosure statement for my {PRODUCT}.\nAGENT: May I ask the reason for closing?\nCUSTOMER: Another bank has offered me a balance transfer at almost one percent lower.\nCUSTOMER: Unless you can match it I will move this month.\nAGENT: I will share the statement and check with the retention team.'),
('CS-I1','CHURN_SHOPPING','INSURANCE','CALL','Cancellation enquiry',FALSE,'OPEN',-0.4,'Asked about cancellation; has cheaper quote from competitor.',
 'AGENT: Thank you for calling.\nCUSTOMER: I want to know the refund if I cancel my {PRODUCT} now.\nCUSTOMER: I got a quote from another insurer that is twenty percent cheaper.\nAGENT: I can check if there are any benefits you would lose by moving.\nCUSTOMER: Please check quickly, I plan to switch next week.');

-- ---------------------------------------------------------------------
-- FACT_INTERACTION  (archetype-driven touchpoints over the last 12 months)
-- ---------------------------------------------------------------------
CREATE OR REPLACE TABLE FACT_INTERACTION (
  INTERACTION_ID STRING PRIMARY KEY, CUSTOMER_ID STRING, INDUSTRY_TYPE STRING, INTERACTION_TS TIMESTAMP_NTZ, CHANNEL STRING,
  TOPIC STRING, IS_COMPLAINT BOOLEAN, RESOLUTION_STATUS STRING, RULE_SENTIMENT FLOAT, NOTE STRING, HAS_TRANSCRIPT BOOLEAN,
  TEMPLATE_ID STRING) COMMENT = 'All customer touchpoints. RULE_SENTIMENT is a deterministic baseline; AI sentiment lives in CALL_TRANSCRIPT';

INSERT INTO FACT_INTERACTION
WITH t AS (SELECT t.*, COUNT(*) OVER (PARTITION BY ARCHETYPE, INDUSTRY_TYPE) CNT,
                  ROW_NUMBER() OVER (PARTITION BY ARCHETYPE, INDUSTRY_TYPE ORDER BY TEMPLATE_ID) IDX
           FROM ACTION360_DB.RAW.INTERACTION_TEMPLATE t),
n AS (SELECT ROW_NUMBER() OVER (ORDER BY SEQ4()) K FROM TABLE(GENERATOR(ROWCOUNT => 6))),
c AS (SELECT c.CUSTOMER_ID, c.FULL_NAME, c.INDUSTRY_TYPE, a.ARCHETYPE,
             IFF(a.ARCHETYPE = 'STABLE', FLOOR(CORE.RND(c.CUSTOMER_ID||'ni')*3)::INT, 2 + FLOOR(CORE.RND(c.CUSTOMER_ID||'ni')*4)::INT) NI
      FROM DIM_CUSTOMER c JOIN ACTION360_DB.RAW.CUSTOMER_ARCHETYPE a USING (CUSTOMER_ID) WHERE NOT a.IS_DEMO_PERSONA),
p AS (SELECT c.*, n.K,
        -- 75% of touchpoints come from the customer's archetype, the rest are routine (STABLE) contacts
        IFF(CORE.RND(c.CUSTOMER_ID||'mix'||n.K) < 0.75 OR c.ARCHETYPE = 'STABLE', c.ARCHETYPE, 'STABLE') TARCH,
        CORE.RND(c.CUSTOMER_ID||'tp'||n.K) RT, CORE.RND(c.CUSTOMER_ID||'dt'||n.K) RD
      FROM c JOIN n ON n.K <= c.NI)
SELECT 'I' || p.CUSTOMER_ID || '-' || p.K, p.CUSTOMER_ID, p.INDUSTRY_TYPE,
  DATEADD(minute, FLOOR(p.RD*600)::INT, DATEADD(day, -IFF(p.TARCH = 'STABLE', 5 + FLOOR(p.RD*355)::INT, 1 + FLOOR(p.RD*85)::INT), '2026-10-02 09:00:00'::TIMESTAMP_NTZ)),
  t.CHANNEL, t.TOPIC, t.IS_COMPLAINT, t.RESOLUTION_STATUS, t.RULE_SENTIMENT,
  REPLACE(t.NOTE, '{PRODUCT}', 'account'), t.TRANSCRIPT IS NOT NULL, t.TEMPLATE_ID
FROM p JOIN t ON t.ARCHETYPE = p.TARCH AND t.INDUSTRY_TYPE = p.INDUSTRY_TYPE AND t.IDX = 1 + FLOOR(p.RT * t.CNT)::INT;

-- ---------------------------------------------------------------------
-- CALL_TRANSCRIPT  (text transcripts; AI_TRANSCRIBE output lands here too)
-- ---------------------------------------------------------------------
CREATE OR REPLACE TABLE CALL_TRANSCRIPT (
  TRANSCRIPT_ID STRING PRIMARY KEY, INTERACTION_ID STRING, CUSTOMER_ID STRING, CALL_TS TIMESTAMP_NTZ,
  DURATION_SEC INT, SOURCE_TYPE STRING, SOURCE_FILE STRING, TRANSCRIPT_TEXT STRING, SEGMENTS VARIANT,
  -- AI enrichment columns (populated selectively by the cost-aware enrichment task)
  AI_SENTIMENT_SCORE FLOAT, AI_INTENT STRING, AI_COMPLAINT_CATEGORY STRING, AI_SUMMARY STRING, AI_ENRICHED_AT TIMESTAMP_NTZ)
  COMMENT = 'Call transcripts. SOURCE_TYPE = SYNTHETIC_TEXT | AI_TRANSCRIBE';

INSERT INTO CALL_TRANSCRIPT (TRANSCRIPT_ID, INTERACTION_ID, CUSTOMER_ID, CALL_TS, DURATION_SEC, SOURCE_TYPE, SOURCE_FILE, TRANSCRIPT_TEXT)
SELECT 'TR-' || i.INTERACTION_ID, i.INTERACTION_ID, i.CUSTOMER_ID, i.INTERACTION_TS,
  120 + FLOOR(CORE.RND(i.INTERACTION_ID)*480)::INT, 'SYNTHETIC_TEXT', 'synthetic://transcripts/' || i.INTERACTION_ID || '.txt',
  REPLACE(REPLACE(t.TRANSCRIPT, '{PRODUCT}', LOWER(p.PRODUCT_NAME)), '\\n', '\n')
FROM FACT_INTERACTION i JOIN ACTION360_DB.RAW.INTERACTION_TEMPLATE t USING (TEMPLATE_ID)
JOIN (SELECT CUSTOMER_ID, ANY_VALUE(PRODUCT_NAME) PRODUCT_NAME FROM FACT_PRODUCT_HOLDING GROUP BY 1) p USING (CUSTOMER_ID)
WHERE t.TRANSCRIPT IS NOT NULL;
