# ACTION360: Customer 360 & Next Best Action Copilot

**Snowflake CoCo CLI Hackathon (GCC Edition 2026).** This is a decision-support and action system for lenders and insurers. It is not a RAG chatbot.

```
QUESTION → CUSTOMER 360 → SIGNALS → EVIDENCE → ELIGIBILITY RULES → NEXT BEST ACTION → PERSONALISATION → AUDIT
```

All data is synthetic and de-identified. Downstream actions are **simulated** and labelled as such.

## What it does

* Joins structured data (customers, loans, cards, policies, payments, transactions, servicing and claim events) with unstructured data (call transcripts, AI_TRANSCRIBE output, policy and offer documents) into one governed **Customer 360**.
* Derives explainable **signals** and **churn, payment and service risk** with configurable weights.
* Picks the **next-best-action** deterministically: weighted signals, hard guardrails and rule-by-rule offer eligibility.
* Uses LLMs only to *explain and personalise* a decision that is already locked in, and only for customers where the AI route justifies the cost.
* Lets a relationship manager go from a natural-language question to an approved, hash-chained audit record in one Streamlit app.

## Repository layout

```
action360/
  app/            Streamlit-in-Snowflake app (streamlit_app.py, data.py, .streamlit/config.toml)
  sql/            all Snowflake DDL/DML, in run order (see scripts/deploy_all.py)
  scripts/        deploy + utility scripts (run_sql, load_unstructured, deploy_semantic_view, deploy_streamlit, ask_agent)
  data/docs/      knowledge corpus (8 policy / product / offer documents)
  data/audio/     synthetic call recordings (Windows TTS) for AI_TRANSCRIBE
  tests/          pytest suite + evaluation benchmark runner
  config/         action360.yaml (mirrors CORE.APP_CONFIG)
  docs/           HACKATHON_DEMO.md, DEMO_SCRIPT.md, ARCHITECTURE.md, COST_OPTIMIZATION.md
```

| SQL file | Purpose |
|---|---|
| `snowflake_setup.sql` | DB/schemas, XS warehouse + resource monitor, stages, APP_CONFIG, RBAC role |
| `customer_data.sql` | deterministic synthetic generator (10k customers, archetype-driven) |
| `personas.sql` | 6 hand-crafted demo personas |
| `signal_engine.sql` | dynamic tables CUSTOMER_FEATURES → CUSTOMER_SIGNAL → CUSTOMER_RISK |
| `nba_engine.sql` | offers + rules, OFFER_ELIGIBILITY, action catalog, weights, guardrails, NBA_CANDIDATE, CUSTOMER_360, audit tables |
| `cortex_functions.sql` | custom AI FUNCTIONs, AI_TRANSCRIBE ingestion, cost-routed enrichment, stream + task |
| `run_ai_pipeline.sql` | executes the paid AI steps (re-runnable, incremental) |
| `cortex_search.sql` | INTERACTION_SEARCH + KNOWLEDGE_SEARCH |
| `semantic_view.yaml` | governed semantic view CUSTOMER_360_SV with verified queries |
| `decision_tools.sql` | agent/app tools (get_customer_360, check_offer_eligibility, calculate_next_best_action, generate_personalized_outreach, log_action) |
| `cortex_agent.sql` | ACTION360_AGENT + least-privilege grants |
| `evaluation.sql` | benchmark cases, results table, routing economics views |

## Run it

Prerequisites: Python 3.11+ and `pip install -r requirements.txt`. You need an ACCOUNTADMIN-capable connection in `~/.snowflake/connections.toml`. Key-pair auth (`action360_dev`) avoids repeated browser sign-ins.

```bash
python scripts/deploy_all.py            # full build incl. AI enrichment (~5 credits)
python scripts/deploy_all.py --skip-ai  # everything except paid enrichment
python -m pytest tests -q               # 32 deterministic tests
ACTION360_RUN_AI_TESTS=1 python -m pytest tests -q   # + LLM/agent tests
python tests/run_evaluation.py --with-outreach --with-agent
python scripts/ask_agent.py "Why is C10238 high risk?"
```

Open the app in Snowsight: **Projects → Streamlit → ACTION360_APP**.

To run it locally:

```bash
SNOWFLAKE_DEFAULT_CONNECTION_NAME=action360_dev streamlit run app/streamlit_app.py
```

## Demo personas

| ID | Story | Deterministic NBA | Offer | AI route |
|---|---|---|---|---|
| C10238 | Premier, 3 products, 3 unresolved complaints, competitor offer, rate reset in 21 days | Service recovery (before price) | OFF_FEE_WAIVER | FULL_AGENT |
| C10417 | Job loss, 2 missed EMIs | Payment-plan discussion | OFF_HARDSHIP_PLAN (cashback **not eligible**) | FULL_AGENT |
| C10555 | Promotion, rising card spend, clean repayment | Product upgrade | OFF_CARD_UPGRADE | SELECTIVE_AI |
| C10789 | Newborn, individual health only, no life cover | Coverage review | OFF_FAMILY_FLOATER | SELECTIVE_AI |
| C10901 | Stable, low risk | No action / monitor (LLM skipped) | none | RULES_ONLY |
| C11024 | Delayed claim, motor renewal in 28 days | Claim follow-up | loyalty discount **not eligible** (2 claims) | SELECTIVE_AI |

See [docs/HACKATHON_DEMO.md](docs/HACKATHON_DEMO.md), [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md), [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and [docs/COST_OPTIMIZATION.md](docs/COST_OPTIMIZATION.md).
