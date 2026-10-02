-- =====================================================================
-- ACTION360 :: post-deploy steps (idempotent; run by every deploy, local or CI)
-- =====================================================================
USE WAREHOUSE ACTION360_WH;
USE SCHEMA ACTION360_DB.CORE;
-- dynamic tables were (re)created; make sure the 360 view reflects current rules and AI enrichment
ALTER DYNAMIC TABLE ACTION360_DB.CORE.CUSTOMER_360 REFRESH;
-- the stream/task are recreated by cortex_functions.sql in a suspended state
ALTER TASK ACTION360_DB.CORE.ACTION360_ENRICH_TASK RESUME;
