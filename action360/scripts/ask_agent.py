"""Ask the ACTION360 Cortex Agent a question via SNOWFLAKE.CORTEX.DATA_AGENT_RUN.

Usage: python scripts/ask_agent.py "Why is C10238 high risk?"
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from run_sql import connect  # noqa: E402


def ask(cur, question: str) -> dict:
    body = json.dumps({"messages": [{"role": "user", "content": [{"type": "text", "text": question}]}]})
    t0 = time.time()
    cur.execute("SELECT SNOWFLAKE.CORTEX.DATA_AGENT_RUN('ACTION360_DB.AI.ACTION360_AGENT', %s)", (body,))
    resp = json.loads(cur.fetchone()[0])
    resp["_latency_s"] = round(time.time() - t0, 1)
    return resp


def summarize(resp: dict) -> dict:
    tools = [c["tool_use"]["name"] for c in resp.get("content", []) if c.get("type") == "tool_use"]
    text = "\n".join(c.get("text", "") for c in resp.get("content", []) if c.get("type") == "text")
    return {"tools": tools, "text": text, "latency_s": resp["_latency_s"], "warnings": resp.get("warnings")}


if __name__ == "__main__":
    r = summarize(ask(connect().cursor(), sys.argv[1]))
    print("TOOLS:", r["tools"], "| latency", r["latency_s"], "s | warnings", r["warnings"])
    print(r["text"])
