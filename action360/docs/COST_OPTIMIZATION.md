# Cost optimization

The budget is about $400 of trial credits. Measured spend for the complete build, including enrichment, the agent, evaluation and tests, was about **6.6 credits**: AI functions 4.65, warehouse 1.53, Cortex Agents 0.30, AI services 0.13. Source: `SNOWFLAKE.ACCOUNT_USAGE.METERING_DAILY_HISTORY`. CoCo Desktop development usage is billed separately.

## Cost-aware AI routing

| Route | Rule (APP_CONFIG) | What runs | Share of book |
|---|---|---|---|
| RULES_ONLY | risk < 0.35 and opportunity < 0.6 | Deterministic signals, rule sentiment and keyword intent. No search and no LLM. Outreach generation is skipped for "monitor" customers. | ~67% |
| SELECTIVE_AI | risk ≥ 0.35, or opportunity ≥ 0.6 | AI_SENTIMENT + AI_CLASSIFY on the **latest 1** transcript; Cortex Search evidence | ~19% |
| FULL_AGENT | risk ≥ 0.60 | Latest 2 transcripts enriched, LLM summary (claude-haiku-4-5, batched for the top-100 by value and generated on demand otherwise), full agent, outreach with claude-sonnet-4-6 | ~13% |

Measured effect:

* Roughly 3.9k transcripts were enriched.
* **19,242 AI function calls were avoided** by routing (logged in `AI_USAGE_METRICS` with `SKIPPED = TRUE`).
* About 8.7k customers (87%) never touch a large LLM.

## Other levers

* **Right-sized models:**
  * Managed, task-specific functions (AI_SENTIMENT, AI_CLASSIFY) handle classification.
  * Haiku handles batch summaries.
  * Sonnet is used only for customer-facing text and agent orchestration.
* **Deterministic first:** risk, eligibility and the NBA decision never call an LLM, so they cost warehouse seconds only.
* **Small, targeted search corpora:** about 32k interaction docs plus 34 knowledge chunks, with a 1-day target lag.
* **Incremental enrichment:** a stream + task only wakes on new transcripts, and `ENRICH_TRANSCRIPTS` skips anything already enriched.
* **No synthetic-text LLM generation:** transcripts come from templates. Only two short TTS audio files exercise AI_TRANSCRIBE (about 50 tokens per second).
* **Compute limits:** XS warehouse with 60 s auto-suspend. `ACTION360_RM` resource monitor at 60 credits (notify at 75%, suspend at 95/100%).
* **Token estimates before batches:** AI_COUNT_TOKENS was run before the enrichment batch (about 2M input tokens).

## Observability

* The **AI & cost** page shows instrumented calls, calls avoided, estimated tokens and latency per component, plus metered credits from ACCOUNT_USAGE.
* `CORE.V_AI_COST_PER_ENRICHED_CUSTOMER` and `CORE.V_ROUTING_ECONOMICS` give the same numbers in SQL.
