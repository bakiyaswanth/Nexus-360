"""Validate and deploy the semantic view from sql/semantic_view.yaml.

Usage: python scripts/deploy_semantic_view.py [--verify-only]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from run_sql import connect  # noqa: E402

YAML = Path(__file__).resolve().parents[1] / "sql" / "semantic_view.yaml"


def main(verify_only: bool):
    conn = connect()
    cur = conn.cursor()
    text = YAML.read_text(encoding="utf-8")
    cur.execute("CALL SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML('ACTION360_DB.AI', %s, TRUE)", (text,))
    print("verify:", cur.fetchone()[0])
    if not verify_only:
        cur.execute("DROP SEMANTIC VIEW IF EXISTS ACTION360_DB.AI.CUSTOMER_360_SV")
        cur.execute("CALL SYSTEM$CREATE_SEMANTIC_VIEW_FROM_YAML('ACTION360_DB.AI', %s)", (text,))
        print("deploy:", cur.fetchone()[0])
    conn.close()


if __name__ == "__main__":
    main("--verify-only" in sys.argv)
