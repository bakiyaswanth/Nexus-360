"""Data generation, Customer 360 joins, risk routing and search retrieval."""
from conftest import one, proc

C = "ACTION360_DB.CORE"


def test_data_volumes(cur):
    assert one(cur, f"SELECT COUNT(*) FROM {C}.DIM_CUSTOMER")[0] == 10000
    assert one(cur, f"SELECT COUNT(*) FROM {C}.FACT_ACCOUNT")[0] > 10000
    assert one(cur, f"SELECT COUNT(*) FROM {C}.CALL_TRANSCRIPT")[0] > 5000
    assert one(cur, f"SELECT COUNT(*) FROM {C}.KNOWLEDGE_CHUNK")[0] >= 30


def test_data_is_synthetic_and_deidentified(cur):
    assert one(cur, f"SELECT COUNT_IF(NOT IS_SYNTHETIC) FROM {C}.DIM_CUSTOMER")[0] == 0
    assert one(cur, f"SELECT COUNT_IF(EMAIL_MASKED NOT LIKE '%@example.invalid') FROM {C}.DIM_CUSTOMER")[0] == 0


def test_referential_integrity(cur):
    for t in ("FACT_ACCOUNT", "FACT_PAYMENT", "FACT_INTERACTION", "CALL_TRANSCRIPT", "FACT_CLAIM_OR_LOAN_EVENT"):
        orphans = one(cur, f"SELECT COUNT(*) FROM {C}.{t} x LEFT JOIN {C}.DIM_CUSTOMER c USING (CUSTOMER_ID) WHERE c.CUSTOMER_ID IS NULL")[0]
        assert orphans == 0, t


def test_customer_360_one_row_per_customer(cur):
    n, d = one(cur, f"SELECT COUNT(*), COUNT(DISTINCT CUSTOMER_ID) FROM {C}.CUSTOMER_360")
    assert n == d == 10000


def test_customer_360_matches_source_facts(cur):
    a, b = one(cur, f"""SELECT c.TOTAL_OUTSTANDING, (SELECT SUM(OUTSTANDING_BALANCE) FROM {C}.FACT_ACCOUNT WHERE CUSTOMER_ID='C10238')
                        FROM {C}.CUSTOMER_360 c WHERE CUSTOMER_ID='C10238'""")
    assert float(a) == float(b)


def test_risk_scores_bounded_and_tiers_follow_thresholds(cur):
    lo, hi = one(cur, f"SELECT MIN(RISK_SCORE), MAX(RISK_SCORE) FROM {C}.CUSTOMER_RISK")
    assert 0 <= lo and hi <= 1
    bad = one(cur, f"""SELECT COUNT(*) FROM {C}.CUSTOMER_RISK r, (SELECT
             MAX(IFF(CONFIG_KEY='LLM_ENRICHMENT_THRESHOLD', CONFIG_VALUE::FLOAT, NULL)) F,
             MAX(IFF(CONFIG_KEY='SELECTIVE_ENRICHMENT_THRESHOLD', CONFIG_VALUE::FLOAT, NULL)) S FROM {C}.APP_CONFIG) t
             WHERE (RISK_SCORE >= F AND AI_ROUTE <> 'FULL_AGENT') OR (RISK_SCORE < S AND OPPORTUNITY_SCORE < 0.6 AND AI_ROUTE <> 'RULES_ONLY')""")[0]
    assert bad == 0


def test_majority_routed_away_from_llm(cur):
    share = one(cur, f"SELECT COUNT_IF(AI_ROUTE='RULES_ONLY')/COUNT(*) FROM {C}.CUSTOMER_360")[0]
    assert share > 0.5


def test_rules_only_transcripts_not_enriched(cur):
    n = one(cur, f"""SELECT COUNT(*) FROM {C}.CALL_TRANSCRIPT t JOIN {C}.CUSTOMER_RISK r USING (CUSTOMER_ID)
                    WHERE t.AI_ENRICHED_AT IS NOT NULL AND r.AI_ROUTE='RULES_ONLY' AND r.RISK_SCORE < 0.2""")[0]
    assert n == 0


def test_persona_routes(cur):
    routes = dict(cur.execute(f"""SELECT CUSTOMER_ID, AI_ROUTE FROM {C}.CUSTOMER_360
                   WHERE CUSTOMER_ID IN ('C10238','C10417','C10901')""").fetchall())
    assert routes == {"C10238": "FULL_AGENT", "C10417": "FULL_AGENT", "C10901": "RULES_ONLY"}


def test_audio_transcribed(cur):
    assert one(cur, f"SELECT COUNT(*) FROM {C}.CALL_TRANSCRIPT WHERE SOURCE_TYPE='AI_TRANSCRIBE' AND ARRAY_SIZE(SEGMENTS) > 0")[0] >= 1


def test_interaction_search_filters_by_customer(cur):
    res = proc(cur, """CALL ACTION360_DB.AI.SEARCH_SERVICE('INTERACTION_SEARCH',
              PARSE_JSON('{"query":"fee reversal competitor","columns":["DOC_ID","CUSTOMER_ID"],"filter":{"@eq":{"CUSTOMER_ID":"C10238"}},"limit":5}'))""")
    assert res and all(r["CUSTOMER_ID"] == "C10238" for r in res)


def test_knowledge_search_returns_policy(cur):
    res = proc(cur, """CALL ACTION360_DB.AI.SEARCH_SERVICE('KNOWLEDGE_SEARCH',
              PARSE_JSON('{"query":"hardship payment holiday job loss","columns":["CHUNK_ID","TITLE"],"limit":3}'))""")
    assert any("hardship" in r["CHUNK_ID"] for r in res)


def test_search_service_rejects_unknown_service(cur):
    assert "error" in proc(cur, "CALL ACTION360_DB.AI.SEARCH_SERVICE('SOMETHING_ELSE', PARSE_JSON('{}'))")
