# CI/CD: GitHub Actions → Snowflake

Workflow: `.github/workflows/action360-deploy.yml`

## No secrets anywhere
The pipeline uses **OIDC workload identity federation**:

1. Each run asks GitHub for a short-lived OIDC token, with audience `snowflakecomputing.com`. This needs `permissions: id-token: write`.
2. `scripts/run_sql.py` exchanges the token with Snowflake (`authenticator=WORKLOAD_IDENTITY`, `workload_identity_provider=OIDC`).
3. Snowflake service user `SVC_GITHUB_ACTIONS` has no password and no key. It trusts exactly one subject: `repo:bakiyaswanth@63598964/Nexus-360@1401278976:ref:refs/heads/main`. This is GitHub's **immutable-ID** subject format: numeric owner and repo IDs, so a renamed or re-created repo with the same name cannot impersonate this one.

So:
* **Nothing** is stored in GitHub secrets or in the repo.
* Pull requests, forks and other branches cannot authenticate, because their token subject differs. They only run offline checks.
* The account identifier is not kept in the repo. The workflow reads it from the repository **Variable** `SNOWFLAKE_ACCOUNT` (Settings → Secrets and variables → Actions → Variables), with a value like `ORGNAME-ACCOUNTNAME`. The deploy job fails fast with a clear message if the Variable is missing.
* `scripts/check_no_secrets.py` runs on every PR and push. It fails the build if a private key, password, token, `.p8`/`.pem` file or `secrets.toml` is committed.

## Least privilege
CI runs as role `ACTION360_DEPLOYER`. This role:

* owns `ACTION360_DB`,
* can use `ACTION360_WH` and the Streamlit compute pool,
* has `SNOWFLAKE.CORTEX_USER` and `EXECUTE TASK`.

It has no account-level admin rights. The account-level objects (database, warehouse, resource monitor, roles, service user) are created once by an ACCOUNTADMIN via `sql/ci_bootstrap.sql` and `sql/snowflake_setup.sql`.

## Pipeline
| Trigger | Jobs |
|---|---|
| Pull request touching `action360/**` | `validate`: secret scan, byte-compile, YAML parse, artifact check. No Snowflake access. |
| Push to `main` | `validate` → `deploy --app-layer` (engine, AI functions, search, semantic view, tools, agent, eval cases, Streamlit, post-deploy refresh) → deterministic pytest suite |
| Manual *Run workflow* | Choose the `mode` (`app-layer`, `skip-ai`, or `full` incl. paid AI enrichment) and, optionally, `run_ai_eval` (LLM/agent tests plus the 11-case benchmark) |

Deploys are serialised with a `concurrency` group, so they never run in parallel. Test results are uploaded as an artifact.

## One-time bootstrap (already done for this account)
```sql
-- as ACCOUNTADMIN
-- action360/sql/ci_bootstrap.sql : role ACTION360_DEPLOYER, ownership transfer, SVC_GITHUB_ACTIONS (OIDC)
```
If you rename the repo or deploy from another branch, update the subject:
```sql
ALTER USER SVC_GITHUB_ACTIONS SET WORKLOAD_IDENTITY = (TYPE = OIDC
  ISSUER = 'https://token.actions.githubusercontent.com' SUBJECT = 'repo:<owner>@<owner_id>/<repo>@<repo_id>:ref:refs/heads/<branch>');
```

## Troubleshooting
* **`Unable to get ACTIONS_ID_TOKEN_REQUEST_URL` / KeyError:** the job is missing `permissions: id-token: write`.
* **`394729 ... subject or issuer claims were not recognized`:** the subject doesn't match. The error message prints the exact subject GitHub sent. Copy it into `ALTER USER SVC_GITHUB_ACTIONS SET WORKLOAD_IDENTITY = (... SUBJECT = '<that value>')`. Subjects are exact and case-sensitive, with no wildcards.
* **Network policy added later:** allow GitHub runners with the managed rule `SNOWFLAKE.NETWORK_SECURITY.GITHUBACTIONS_GLOBAL`.
