"""Deploy the Streamlit app to Snowflake (container runtime) without the snow CLI.

PUTs app/ files to @ACTION360_DB.APP.APP_STAGE/action360 and (re)creates the STREAMLIT object,
then verifies it exists with SHOW STREAMLITS.
Usage: python scripts/deploy_streamlit.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from run_sql import connect  # noqa: E402

APP = Path(__file__).resolve().parents[1] / "app"
STAGE = "@ACTION360_DB.APP.APP_STAGE/action360"
ARTIFACTS = ["streamlit_app.py", "data.py", "environment.yml", ".streamlit/config.toml"]

# Warehouse runtime: packages from Snowflake's Anaconda channel (environment.yml), no External Access needed.
# (The container runtime installs from PyPI and needs an EAI, which trial accounts cannot create.)
DDL = f"""
CREATE OR REPLACE STREAMLIT ACTION360_DB.APP.ACTION360_APP
  FROM '{STAGE}'
  MAIN_FILE = 'streamlit_app.py'
  QUERY_WAREHOUSE = ACTION360_WH
  TITLE = 'ACTION360 Copilot'
  COMMENT = 'Customer 360 & Next Best Action Copilot (synthetic data, simulated actions)'
"""


def main():
    missing = [a for a in ARTIFACTS if not (APP / a).exists()]
    if missing:
        raise SystemExit(f"MISSING artifacts: {missing}")
    cur = connect().cursor()
    cur.execute(f"REMOVE {STAGE}/pyproject.toml")  # stale container-runtime manifest would be picked up
    for a in ARTIFACTS:
        sub = "/" + str(Path(a).parent).replace("\\", "/") if Path(a).parent != Path(".") else ""
        cur.execute(f"PUT 'file://{(APP / a).as_posix()}' {STAGE}{sub} AUTO_COMPRESS=FALSE OVERWRITE=TRUE")
        print("uploaded", a)
    cur.execute(DDL)
    print(cur.fetchone()[0])
    cur.execute("GRANT USAGE ON STREAMLIT ACTION360_DB.APP.ACTION360_APP TO ROLE ACTION360_ANALYST")
    cur.execute("SHOW STREAMLITS LIKE 'ACTION360_APP' IN SCHEMA ACTION360_DB.APP")
    rows = cur.fetchall()
    if not rows:
        raise SystemExit("Deploy failed: STREAMLIT object not found")
    print("verified:", rows[0][1], "| url: https://app.snowflake.com/ -> Projects > Streamlit > ACTION360_APP")


if __name__ == "__main__":
    main()
