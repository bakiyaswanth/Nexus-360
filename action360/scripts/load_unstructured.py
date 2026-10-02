"""Load unstructured content into Snowflake.

1. PUT knowledge documents (data/docs/*.md) to @RAW.DOCS_STAGE and chunk them into
   CORE.KNOWLEDGE_DOCUMENT / CORE.KNOWLEDGE_CHUNK (heading-level chunks + metadata header).
2. PUT any call recordings (data/audio/*.wav|mp3) to @RAW.AUDIO_STAGE for AI_TRANSCRIBE.

Usage: python scripts/load_unstructured.py
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from run_sql import connect  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "data" / "docs"
AUDIO = ROOT / "data" / "audio"

DDL = """
CREATE TABLE IF NOT EXISTS ACTION360_DB.CORE.KNOWLEDGE_DOCUMENT (
  DOC_ID STRING PRIMARY KEY, TITLE STRING, DOC_TYPE STRING, INDUSTRY_TYPE STRING, PRODUCT STRING,
  VERSION STRING, SOURCE_FILE STRING, FULL_TEXT STRING, LOADED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP())
"""
DDL_CHUNK = """
CREATE TABLE IF NOT EXISTS ACTION360_DB.CORE.KNOWLEDGE_CHUNK (
  CHUNK_ID STRING PRIMARY KEY, DOC_ID STRING, TITLE STRING, SECTION STRING, DOC_TYPE STRING,
  INDUSTRY_TYPE STRING, PRODUCT STRING, SOURCE_FILE STRING, CHUNK_TEXT STRING, OFFER_IDS STRING)
"""


def parse(path: Path):
    text = path.read_text(encoding="utf-8")
    title = text.splitlines()[0].lstrip("# ").strip()
    meta = dict(re.findall(r"(DOC_TYPE|INDUSTRY|PRODUCT|VERSION):\s*([^|\n]+)", text))
    meta = {k: v.strip() for k, v in meta.items()}
    sections = re.split(r"\n## ", text)
    chunks = []
    for i, sec in enumerate(sections[1:], start=1):
        head, _, body = sec.partition("\n")
        body = body.strip()
        offers = ",".join(sorted(set(re.findall(r"OFF_[A-Z_]+", body))))
        chunks.append((f"{path.stem}#{i}", head.strip(), f"{title} - {head.strip()}\n{body}", offers))
    return title, meta, text, chunks


def main():
    conn = connect()
    cur = conn.cursor()
    cur.execute(DDL)
    cur.execute(DDL_CHUNK)
    cur.execute("TRUNCATE TABLE ACTION360_DB.CORE.KNOWLEDGE_CHUNK")
    cur.execute("TRUNCATE TABLE ACTION360_DB.CORE.KNOWLEDGE_DOCUMENT")
    for f in sorted(DOCS.glob("*.md")):
        cur.execute(f"PUT 'file://{f.as_posix()}' @ACTION360_DB.RAW.DOCS_STAGE/knowledge AUTO_COMPRESS=FALSE OVERWRITE=TRUE")
        title, meta, full, chunks = parse(f)
        src = f"@ACTION360_DB.RAW.DOCS_STAGE/knowledge/{f.name}"
        cur.execute(
            "INSERT INTO ACTION360_DB.CORE.KNOWLEDGE_DOCUMENT (DOC_ID, TITLE, DOC_TYPE, INDUSTRY_TYPE, PRODUCT, VERSION, SOURCE_FILE, FULL_TEXT) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (f.stem, title, meta.get("DOC_TYPE"), meta.get("INDUSTRY"), meta.get("PRODUCT"), meta.get("VERSION"), src, full))
        cur.executemany(
            "INSERT INTO ACTION360_DB.CORE.KNOWLEDGE_CHUNK VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            [(cid, f.stem, title, sec, meta.get("DOC_TYPE"), meta.get("INDUSTRY"), meta.get("PRODUCT"), src, txt, offers)
             for cid, sec, txt, offers in chunks])
        print(f"doc {f.name}: {len(chunks)} chunks")
    for f in sorted(list(AUDIO.glob("*.wav")) + list(AUDIO.glob("*.mp3"))):
        cur.execute(f"PUT 'file://{f.as_posix()}' @ACTION360_DB.RAW.AUDIO_STAGE AUTO_COMPRESS=FALSE OVERWRITE=TRUE")
        print(f"audio {f.name} uploaded")
    cur.execute("ALTER STAGE ACTION360_DB.RAW.DOCS_STAGE REFRESH")
    cur.execute("ALTER STAGE ACTION360_DB.RAW.AUDIO_STAGE REFRESH")
    conn.close()


if __name__ == "__main__":
    main()
