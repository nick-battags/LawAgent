"""Bulk ingestion of CUAD and MAUD datasets into clause_chunks via pgvector.

Writes only to clause_chunks via PgvectorCorpusStore.add_chunks().
Does NOT touch lawagent_documents or any legacy ChromaDB schema.

Cohere Embed v4 caps batch at 96 inputs per call. This module flushes each
batch as soon as it fills (streaming pipeline) so the first DB write happens
within seconds of the job starting, not after the full dataset is scanned.

Idempotent: chunk_uid is a sha256 of source_system:document_id:page:text[:240]
so re-running the ingest updates in place rather than duplicating rows.
"""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

_BATCH_SIZE = 90          # stay safely under Cohere's 96-input cap
_SLEEP_BETWEEN_BATCHES = 0.6  # ~150 batches/min → well under 2000 inputs/min


# ── CUAD ─────────────────────────────────────────────────────────────────────

def ingest_cuad_to_pgvector(max_contracts: int = 510) -> dict[str, Any]:
    """Ingest CUAD clause-answer spans into clause_chunks via Cohere Embed v4.

    Uses theatticusproject/cuad-qa (HuggingFace). Flushes each batch as rows
    arrive so the first DB write happens within seconds.
    """
    from datasets import load_dataset
    from scripts.pgvector_store import PgvectorCorpusStore

    logger.info("CUAD ingest: loading dataset (max_contracts=%d)…", max_contracts)
    ds = load_dataset(
        "theatticusproject/cuad-qa", split="train",
        streaming=True, trust_remote_code=True,
    )

    store = PgvectorCorpusStore()
    buf: list[dict] = []
    seen_contracts: set[str] = set()
    total_inserted = 0
    total_proposed = 0
    batch_count = 0
    errors = 0

    def flush() -> None:
        nonlocal total_inserted, batch_count, errors
        batch_count += 1
        logger.info(
            "cuad ingest: batch %d (%d chunks, cumulative %d inserted)",
            batch_count, len(buf), total_inserted,
        )
        try:
            n = store.add_chunks(list(buf))
            total_inserted += n
        except Exception as exc:
            logger.error("cuad ingest batch %d failed: %s", batch_count, exc)
            errors += 1
        buf.clear()
        time.sleep(_SLEEP_BETWEEN_BATCHES)

    for row in ds:
        contract_title = str(row.get("title") or row.get("id") or "unknown")
        if contract_title not in seen_contracts:
            if len(seen_contracts) >= max_contracts:
                break
            seen_contracts.add(contract_title)

        question = str(row.get("question") or "")
        if "__" in question:
            category_raw = question.split("__")[0]
        elif "_" in question:
            category_raw = question.rsplit("_", 1)[0]
        else:
            category_raw = question
        category = (
            category_raw.lower().replace("-", "_").replace(" ", "_").strip("_")[:60]
            or "general"
        )

        answers_field = row.get("answers") or {}
        spans: list[str] = answers_field.get("text") or []
        ans = spans[0].strip() if spans else ""
        if not ans or len(ans) < 50:
            continue

        buf.append({
            "title": f"CUAD: {contract_title[:80]} — {category}",
            "category": category,
            "source_system": "cuad_v1",
            "posture": "neutral",
            "text": ans[:2000],
        })
        total_proposed += 1

        if len(buf) >= _BATCH_SIZE:
            flush()

    if buf:
        flush()

    result = {
        "dataset": "cuad",
        "batches": batch_count,
        "chunks_proposed": total_proposed,
        "chunks_inserted": total_inserted,
        "errors": errors,
    }
    logger.info("cuad ingest complete: %s", result)
    return result


# ── MAUD ─────────────────────────────────────────────────────────────────────

def ingest_maud_to_pgvector(max_contracts: int = 200) -> dict[str, Any]:
    """Ingest MAUD passage-level merger annotations into clause_chunks.

    Flushes each batch as rows arrive so the first DB write happens within
    seconds.
    """
    from datasets import load_dataset
    from scripts.pgvector_store import PgvectorCorpusStore

    logger.info("MAUD ingest: loading dataset (max_contracts=%d)…", max_contracts)
    ds = load_dataset(
        "theatticusproject/maud", split="train",
        streaming=True, trust_remote_code=True,
    )

    store = PgvectorCorpusStore()
    buf: list[dict] = []
    seen_contracts: set[str] = set()
    total_inserted = 0
    total_proposed = 0
    batch_count = 0
    errors = 0

    def flush() -> None:
        nonlocal total_inserted, batch_count, errors
        batch_count += 1
        logger.info(
            "maud ingest: batch %d (%d chunks, cumulative %d inserted)",
            batch_count, len(buf), total_inserted,
        )
        try:
            n = store.add_chunks(list(buf))
            total_inserted += n
        except Exception as exc:
            logger.error("maud ingest batch %d failed: %s", batch_count, exc)
            errors += 1
        buf.clear()
        time.sleep(_SLEEP_BETWEEN_BATCHES)

    for row in ds:
        contract_id = str(
            row.get("deal_id") or row.get("contract_id") or row.get("id") or "unknown"
        )
        if contract_id not in seen_contracts:
            if len(seen_contracts) >= max_contracts:
                break
            seen_contracts.add(contract_id)

        question = str(row.get("question") or "")
        if ":" in question:
            category_raw = question.split(":")[0]
        else:
            category_raw = question or "maud_general"
        category = (
            category_raw.lower().replace(" ", "_").replace("-", "_").strip("_")[:60]
            or "maud_general"
        )

        text = str(row.get("text") or row.get("passage") or row.get("context") or "")
        if not text or len(text) < 50:
            continue

        buf.append({
            "title": f"MAUD: {contract_id[:60]} — {category[:50]}",
            "category": category,
            "source_system": "maud_v1",
            "posture": "neutral",
            "text": text[:2000],
        })
        total_proposed += 1

        if len(buf) >= _BATCH_SIZE:
            flush()

    if buf:
        flush()

    result = {
        "dataset": "maud",
        "batches": batch_count,
        "chunks_proposed": total_proposed,
        "chunks_inserted": total_inserted,
        "errors": errors,
    }
    logger.info("maud ingest complete: %s", result)
    return result
