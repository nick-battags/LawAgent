"""One-shot ingestion: applies migration 008 if needed, seeds the curated
M&A playbook into clause_chunks, and reports the resulting Cohere call
counts so you can verify usage in the Cohere dashboard.

Usage (locally or via Cloud Run Job):
    LLM_PROVIDER=vertex \\
    DATABASE_URL=... \\
    COHERE_API_KEY=... \\
    GCP_PROJECT=... \\
    python -m scripts.corpus.ingest_seed [--reset]

Idempotent: re-runs are safe because PgvectorCorpusStore.add_chunks
upserts on the chunk_uid (sha256 of source+offset+text prefix). Use
--reset to TRUNCATE and rebuild from scratch.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

MIGRATION_FILE = Path(__file__).resolve().parents[1] / "migrations" / "008_clause_chunks_pgvector.sql"


def apply_migration(database_url: str) -> None:
    """Apply migration 008 (CREATE EXTENSION + table + indexes). Idempotent."""
    import psycopg
    sql = MIGRATION_FILE.read_text(encoding="utf-8")
    logger.info("Applying migration: %s", MIGRATION_FILE.name)
    with psycopg.connect(database_url) as conn, conn.cursor() as cur:
        cur.execute(sql)
        conn.commit()
    logger.info("Migration applied")


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed the curated M&A playbook into pgvector.")
    parser.add_argument("--reset", action="store_true",
                        help="TRUNCATE clause_chunks before seeding")
    parser.add_argument("--skip-migration", action="store_true",
                        help="Skip applying migration 008 (assume already applied)")
    args = parser.parse_args()

    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        logger.error("DATABASE_URL env var is required")
        return 2

    if os.environ.get("LLM_PROVIDER", "").lower() != "vertex":
        logger.error(
            "LLM_PROVIDER must be 'vertex' so Cohere Embed v4 is reachable. "
            "Currently: %s", os.environ.get("LLM_PROVIDER", "<unset>"),
        )
        return 2

    if not os.environ.get("COHERE_API_KEY"):
        logger.error("COHERE_API_KEY env var is required")
        return 2

    if not args.skip_migration:
        apply_migration(database_url)

    from scripts.pgvector_store import PgvectorCorpusStore
    from scripts.corpus.seed_playbook import get_seed_chunks

    store = PgvectorCorpusStore()
    if args.reset:
        logger.warning("--reset: truncating clause_chunks")
        store.clear()

    chunks = get_seed_chunks()
    logger.info("Seeding %d curated playbook chunks (this calls Cohere Embed v4)…", len(chunks))
    inserted = store.add_chunks(chunks)
    logger.info("Inserted/updated: %d chunks", inserted)

    final_count = store.count()
    logger.info("Final clause_chunks row count: %d", final_count)
    logger.info("Confirm Cohere usage at https://dashboard.cohere.com (1 Embed v4 batch call expected)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
