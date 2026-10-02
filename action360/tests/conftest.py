"""Shared fixtures: one Snowflake connection (key-pair, no prompts) for the whole test session."""
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from run_sql import connect  # noqa: E402

RUN_AI = os.environ.get("ACTION360_RUN_AI_TESTS") == "1"  # LLM / agent tests cost credits - opt in


@pytest.fixture(scope="session")
def cur():
    c = connect()
    yield c.cursor()
    c.close()


def one(cur, sql, args=None):
    cur.execute(sql, args or ())
    return cur.fetchone()


def proc(cur, sql, args=None):
    v = one(cur, sql, args)[0]
    return json.loads(v) if isinstance(v, str) else v


ai = pytest.mark.skipif(not RUN_AI, reason="set ACTION360_RUN_AI_TESTS=1 to run LLM/agent tests")
