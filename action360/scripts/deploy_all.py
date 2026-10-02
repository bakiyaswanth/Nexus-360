"""One-command, reproducible deployment of ACTION360 into the connected Snowflake account.

Usage: python scripts/deploy_all.py [--skip-ai | --app-layer]
  --skip-ai    build everything except the paid AI enrichment step (sql/run_ai_pipeline.sql)
  --app-layer  CI default: redeploy engine, AI functions, search, semantic view, tools, agent, eval cases
               and the Streamlit app. Does NOT regenerate data or re-run paid enrichment.
Connection: OIDC in GitHub Actions; ACTION360_CONNECTION locally (default: action360_dev key-pair connection).
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable


def run(*args):
    print(f"\n=== {' '.join(args)}")
    subprocess.run([PY, *args], cwd=ROOT, check=True)


def main(skip_ai: bool, app_layer: bool):
    sql = lambda *f: run("scripts/run_sql.py", *[f"sql/{x}" for x in f])  # noqa: E731
    if app_layer:
        sql("signal_engine.sql", "nba_engine.sql", "cortex_functions.sql", "cortex_search.sql")
        run("scripts/deploy_semantic_view.py")
        sql("decision_tools.sql", "cortex_agent.sql", "evaluation.sql", "post_deploy.sql")
        run("scripts/deploy_streamlit.py")
        return
    sql("snowflake_setup.sql", "customer_data.sql", "personas.sql")
    if not list((ROOT / "data" / "audio").glob("*.wav")) and sys.platform == "win32":
        subprocess.run(["powershell", "-ExecutionPolicy", "Bypass", "-File", "scripts/generate_audio.ps1"], cwd=ROOT, check=True)
    run("scripts/load_unstructured.py")
    sql("signal_engine.sql", "nba_engine.sql", "cortex_functions.sql")
    if not skip_ai:
        sql("run_ai_pipeline.sql")
    sql("cortex_search.sql")
    run("scripts/deploy_semantic_view.py")
    sql("decision_tools.sql", "cortex_agent.sql", "evaluation.sql", "post_deploy.sql")
    run("scripts/deploy_streamlit.py")
    print("\nDone. Next: python -m pytest tests -q  and  python tests/run_evaluation.py")


if __name__ == "__main__":
    main("--skip-ai" in sys.argv, "--app-layer" in sys.argv)
