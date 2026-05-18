"""Bulk ingestion of CUAD and MAUD datasets into clause_chunks via pgvector.

Writes only to clause_chunks via PgvectorCorpusStore.add_chunks().
Does NOT touch lawagent_documents or any legacy ChromaDB schema.

Cohere Embed v4 caps batch at 96 inputs per call. This module slices
before calling add_chunks() so the store never receives an oversized batch.

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

    Uses theatticusproject/cuad-qa (HuggingFace). Each QA row contains a
    contract title, question label, and extracted clause span (answers.text).
    """
    from datasets import load_dataset

    logger.info("CUAD ingest: loading dataset (max_contracts=%d)…", max_contracts)
    ds = load_dataset("theatticusproject/cuad-qa", split="train")

    # Defensive: print first-row keys once so drift is visible in logs
    if len(ds) > 0:
        logger.info("CUAD row keys: %s", list(ds[0].keys()))

    chunks: list[dict] = []
    seen_contracts: set[str] = set()

    for row in ds:
        contract_title: str = str(row.get("title") or row.get("id") or "unknown")

        if contract_title not in seen_contracts:
            if len(seen_contracts) >= max_contracts:
                break
            seen_contracts.add(contract_title)

        # Question format varies: "Category__Description" or "Category_YesNo"
        question: str = str(row.get("question") or "")
        if "__" in question:
            category_raw = question.split("__")[0]
        elif "_" in question:
            category_raw = question.rsplit("_", 1)[0]
        else:
            category_raw = question

        category = (
            category_raw.lower()
            .replace("-", "_")
            .replace(" ", "_")
            .strip("_")[:60]
            or "general"
        )

        # answers field: {"text": [...], "answer_start": [...]}
        answers_field = row.get("answers") or {}
        spans: list[str] = answers_field.get("text") or []
        ans = spans[0].strip() if spans else ""
        if not ans or len(ans) < 50:
            continue

        chunks.append({
            "title": f"CUAD: {contract_title[:80]} — {category}",
            "category": category,
            "source_system": "cuad_v1",
            "posture": "neutral",
            "text": ans[:2000],   # truncate runaway spans
        })

    logger.info("CUAD: built %d chunks from %d contracts", len(chunks), len(seen_contracts))
    return _ingest_in_batches(chunks, dataset_label="cuad")


# ── MAUD ─────────────────────────────────────────────────────────────────────

def ingest_maud_to_pgvector(max_contracts: int = 200) -> dict[str, Any]:
    """Ingest MAUD passage-level merger annotations into clause_chunks."""
    from datasets import load_dataset

    logger.info("MAUD ingest: loading dataset (max_contracts=%d)…", max_contracts)
    ds = load_dataset("theatticusproject/maud", split="train")

    if len(ds) > 0:
        logger.info("MAUD row keys: %s", list(ds[0].keys()))

    chunks: list[dict] = []
    seen_contracts: set[str] = set()

    for row in ds:
        contract_id: str = str(
            row.get("deal_id") or row.get("contract_id") or row.get("id") or "unknown"
        )

        if contract_id not in seen_contracts:
            if len(seen_contracts) >= max_contracts:
                break
            seen_contracts.add(contract_id)

        question: str = str(row.get("question") or "")
        if ":" in question:
            category_raw = question.split(":")[0]
        else:
            category_raw = question or "maud_general"

        category = (
            category_raw.lower()
            .replace(" ", "_")
            .replace("-", "_")
            .strip("_")[:60]
            or "maud_general"
        )

        text: str = str(row.get("text") or row.get("passage") or row.get("context") or "")
        if not text or len(text) < 50:
            continue

        chunks.append({
            "title": f"MAUD: {contract_id[:60]} — {category[:50]}",
            "category": category,
            "source_system": "maud_v1",
            "posture": "neutral",
            "text": text[:2000],
        })

    logger.info("MAUD: built %d chunks from %d contracts", len(chunks), len(seen_contracts))
    return _ingest_in_batches(chunks, dataset_label="maud")


# ── Shared batch ingestor ─────────────────────────────────────────────────────

def _ingest_in_batches(
    chunks: list[dict],
    dataset_label: str,
    batch_size: int = _BATCH_SIZE,
    sleep_s: float = _SLEEP_BETWEEN_BATCHES,
) -> dict[str, Any]:
    """Slice chunks into ≤90-item batches and call add_chunks() on each.

    add_chunks() passes the entire list to Cohere in one call so batching
    MUST happen here, not inside the store.
    """
    from scripts.pgvector_store import PgvectorCorpusStore

    store = PgvectorCorpusStore()
    total_inserted = 0
    batch_count = 0
    errors = 0

    for i in range(0, len(chunks), batch_size):
        batch = chunks[i : i + batch_size]
        batch_num = i // batch_size + 1
        total_batches = (len(chunks) + batch_size - 1) // batch_size
        logger.info(
            "%s ingest: batch %d/%d (%d chunks, cumulative %d inserted)",
            dataset_label, batch_num, total_batches, len(batch), total_inserted,
        )
        try:
            n = store.add_chunks(batch)
            total_inserted += n
        except Exception as exc:
            logger.error("%s ingest batch %d failed: %s", dataset_label, batch_num, exc)
            errors += 1

        batch_count += 1
        if i + batch_size < len(chunks):
            time.sleep(sleep_s)

    result = {
        "dataset": dataset_label,
        "batches": batch_count,
        "chunks_proposed": len(chunks),
        "chunks_inserted": total_inserted,
        "errors": errors,
    }
    logger.info("%s ingest complete: %s", dataset_label, result)
    return result
