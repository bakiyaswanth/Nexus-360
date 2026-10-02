# ACTION360: Hackathon submission

## 1. Problem
Insurers and lenders hold customer facts in many separate systems: core banking, policy admin, payments and CRM. What customers actually say lives in call recordings and transcripts. Relationship managers can't see the whole picture, so they:

* offer discounts to customers who really need service recovery or hardship support,
* miss life-event moments when protection matters,
* call stable customers for no reason,

and every one of those mistakes costs attrition or money.

## 2. Target users
* Relationship managers and retention desks: who to call today, and what to say.
* Servicing, collections (hardship) and claims teams.
* CX and portfolio leaders: risk by segment, action pipeline, cost.
* Risk and compliance: an auditable, rule-bound decision trail.

## 3. Solution
ACTION360 is a Customer 360 and next-best-action copilot. A business user asks a question in natural language and moves straight to an evidence-backed, eligibility-checked, personalised and **logged** action, all in one Snowflake-native experience.

## 4. Architecture
See [ARCHITECTURE.md](ARCHITECTURE.md). The layers are:

RAW → CURATED → SIGNALS (dynamic tables) → CUSTOMER 360 → SEMANTIC VIEW + CORTEX SEARCH → DECISION ENGINE → CORTEX AGENT → STREAMLIT → ACTION AUDIT

Snowflake isn't just the database here. Every step runs inside the governed account:

* AI_TRANSCRIBE transcription
* AI_SENTIMENT and AI_CLASSIFY extraction
* Cortex Search retrieval
* Cortex Analyst text-to-SQL over a governed semantic view
* custom AI FUNCTIONs for generation
* stored procedures for business rules
* Cortex Agents for orchestration
* Streamlit for the UI
* tables for the audit trail

RBAC covers all of it.

## 5. Snowflake services used
| Service | Use |
|---|---|
| Dynamic tables | Declarative features → signals → risk → eligibility → candidates → Customer 360 |
| AI_TRANSCRIBE | Staged call audio → speaker-diarized transcript in CALL_TRANSCRIPT |
| AI_SENTIMENT, AI_CLASSIFY | Transcript sentiment, customer intent and complaint category (cost-routed) |
| Custom AI FUNCTION (AI Function Studio) | `SUMMARIZE_CUSTOMER_RISK` (Haiku) and `GENERATE_PERSONALIZED_ACTION` (Sonnet), with structured JSON output |
| AI_COUNT_TOKENS | Token estimates before batch runs and for usage metrics |
| Cortex Search (×2) | Interaction evidence filtered by CUSTOMER_ID; policy / product / offer knowledge |
| Semantic view + Cortex Analyst | Governed business definitions and 6 verified queries |
| Cortex Agent | Orchestrates Analyst, Search and 5 governed custom tools |
| Streams + tasks | Incremental, event-driven enrichment of new transcripts |
| Streamlit in Snowflake (warehouse runtime) | Enterprise operations cockpit |
| Resource monitor, ACCOUNT_USAGE | Cost guardrails and metered-credit observability |

## 6. Data flow
1. A synthetic generator, seeded by hash and driven by archetypes, produces 10k customers, 12.9k accounts, 155k payments, 161k transactions, 21.6k interactions, 10.8k transcripts and 2.6k events, plus 6 hand-crafted personas.
2. Policy documents are PUT to a stage and chunked by heading. Audio files are PUT to a stage and transcribed by AI_TRANSCRIBE.
3. Dynamic tables compute features and normalise 25 signals. Configurable weights turn them into risk.
4. Rules evaluate 11 offers × 41 hard rules for each customer, recording every outcome.
5. The NBA engine scores 13 candidate actions per customer and applies the guardrails.
6. All of this feeds CUSTOMER_360.

## 7. AI flow
Cost-aware routing decides how much AI each customer gets (see [COST_OPTIMIZATION.md](COST_OPTIMIZATION.md)):

* **RULES_ONLY:** none.
* **SELECTIVE_AI:** sentiment and intent on the latest transcript.
* **FULL_AGENT:** plus an LLM summary, the full agent and outreach.

The agent's order is fixed by its instructions: facts → interaction evidence → policy evidence → hard eligibility → deterministic NBA → personalisation → log, and the log step runs only on explicit approval.

## 8. Next-best-action logic
`score(action) = BASE_SCORE + Σ weight(action, signal) × signal_value`

The weights live in `NBA_WEIGHT`. Negative weights encode explicit policy, for example `RETENTION_OFFER × UNRESOLVED = -0.30`, meaning "service before price". The selection then works like this:

* A candidate is **blocked** when an `NBA_GUARDRAIL` condition is true. Examples: no upsell when payment risk ≥ 0.3, no pricing incentive during distress.
* A candidate is **not eligible** when its required offer category has no offer that passes every hard rule.
* A candidate is **below threshold** when its score is under MIN_ACTION_SCORE (default 0.40).
* The top eligible candidate wins. NO_ACTION_MONITOR (base 0.15) wins if nothing else qualifies.
* Confidence comes from the score margin over the runner-up and the amount of available evidence.

Every candidate, its contributions, block reasons, failed rules and evidence are persisted to `NBA_RECOMMENDATION`.

## 9. Cost optimization
Measured spend was about 6.6 credits for the full build and test cycle. Routing avoided 19k AI function calls, and 87% of customers never hit an LLM. See [COST_OPTIMIZATION.md](COST_OPTIMIZATION.md).

## 10. Governance
* The data is synthetic and de-identified: masked emails (`@example.invalid`) and masked phones.
* FACT, AI INTERPRETATION and RECOMMENDATION are labelled separately throughout the app and in agent answers.
* The LLM can't override eligibility. Three checks enforce this: the decision is locked in the prompt, a post-generation guardrail screens the message, and `LOG_ACTION` re-checks eligibility.
* Unknown customers return `found=false`, so facts are never invented. Missing evidence is stated explicitly as "evidence gaps".
* `ACTION360_ANALYST` is a least-privilege role. The audit table is append-only through an owner's-rights procedure and has a SHA-256 hash chain.
* Downstream execution is SIMULATED and labelled as such.

## 11. Evaluation
* `tests/run_evaluation.py` covers 11 scenarios: 6 personas and 5 negative cases.
* Result: **11/11** on action correctness, eligibility correctness and recommendation consistency. All cases have citation coverage. Every outreach that was generated was grounded, meaning it referenced no ineligible offers.
* The agent refused ineligible requests and cited the failed rules.
* The pytest suite has **34 tests**, all passing.
* Results appear on the app's Evaluation page.

| Negative test | Expected behaviour |
|---|---|
| Not eligible for an offer | Rules tool returns NOT ELIGIBLE with the failed rules; log attempt is BLOCKED |
| Conflicting information | Customer asks for a loyalty discount the rules forbid; the rules win |
| Insufficient evidence | No interaction evidence; reflected in confidence and evidence gaps |
| Nonexistent customer | `found=false` from every tool; the agent says the customer doesn't exist |
| Action that violates eligibility | Upsell blocked by guardrail; ineligible top-up blocked at log time |

## 12. Business impact (directional, on synthetic data)
* Prioritised worklist: 5.3k customers who need action, ranked by risk × value. The other 4.7k are deliberately left alone, which saves contact cost and customer fatigue.
* Service-first retention for high-value complainers, instead of leading with a discount.
* Responsible lending: hardship plans for customers in distress, and no upsell to them.
* Protection cross-sell triggered by life events found in calls.
* Faster RM preparation: about 3 s for a deterministic NBA with evidence, plus a personalised script.

## 13. Future integrations
* CRM / case management through an external access integration, replacing the SIMULATED task.
* Event-driven calls via Snowpipe Streaming from the contact centre.
* Real speech-to-text from telephony recordings at scale.
* Uplift modelling (Snowflake ML) to learn NBA weights from outcomes.
* Snowflake Intelligence, so business users can reach the agent directly.
* Masking policies and row access policies by region or portfolio.
