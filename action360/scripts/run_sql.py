"""Run one or more Snowflake SQL files in order.

No secrets live in the repo. Authentication is resolved at runtime:
  * GitHub Actions: OIDC workload identity federation. A short-lived token is requested from GitHub
    (requires `permissions: id-token: write`) and exchanged with Snowflake. Nothing is stored.
  * Local: a named connection from ~/.snowflake/connections.toml (default `action360_dev`, key-pair).
Usage:  python scripts/run_sql.py sql/customer_data.sql [more.sql ...]
Env:    ACTION360_CONNECTION, SNOWFLAKE_ACCOUNT (CI), SNOWFLAKE_ROLE (CI, default ACTION360_DEPLOYER)
"""
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

import snowflake.connector


def _github_oidc_token() -> str:
    """Fetch a GitHub Actions OIDC JWT with audience snowflakecomputing.com."""
    url = os.environ["ACTIONS_ID_TOKEN_REQUEST_URL"] + "&audience=snowflakecomputing.com"
    req = urllib.request.Request(url, headers={"Authorization": f"bearer {os.environ['ACTIONS_ID_TOKEN_REQUEST_TOKEN']}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)["value"]


def connect():
    wh = os.environ.get("SNOWFLAKE_WAREHOUSE", "ACTION360_WH")
    if os.environ.get("ACTIONS_ID_TOKEN_REQUEST_URL"):
        conn = snowflake.connector.connect(
            account=os.environ["SNOWFLAKE_ACCOUNT"],
            authenticator="WORKLOAD_IDENTITY",
            workload_identity_provider="OIDC",
            token=_github_oidc_token(),
            role=os.environ.get("SNOWFLAKE_ROLE", "ACTION360_DEPLOYER"),
            warehouse=wh,
        )
    else:
        # local: key-pair connection (no browser prompts); override with ACTION360_CONNECTION
        conn = snowflake.connector.connect(connection_name=os.environ.get("ACTION360_CONNECTION", "action360_dev"),
                                           client_store_temporary_credential=True)
    conn.cursor().execute(f"USE WAREHOUSE {wh}")
    return conn


def run_file(conn, path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    t0 = time.time()
    n = 0
    from snowflake.connector.util_text import split_statements
    import io
    for stmt, _ in split_statements(io.StringIO(text), remove_comments=True):
        n += 1
        first = stmt.strip().splitlines()[0][:90]
        try:
            conn.cursor().execute(stmt)
        except Exception as e:
            print(f"  [{n:03}] FAILED  {first}\n{stmt[:1500]}\n--> {e}")
            raise SystemExit(1)
        print(f"  [{n:03}] ok  {first}")
    print(f"{path.name}: {n} statements in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    c = connect()
    try:
        for f in sys.argv[1:]:
            run_file(c, Path(f))
    finally:
        c.close()
