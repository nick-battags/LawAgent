"""MAUD and CUAD dataset ingestion pipelines for LawAgent corpus."""

from __future__ import annotations

import csv
import json
import logging
import re
import threading
from pathlib import Path
from typing import Any

from langchain_text_splitters import RecursiveCharacterTextSplitter

from scripts.ma_corpus_db import (
    CorpusDatabase,
    get_db,
    classify_document,
    detect_tags,
    detect_source_system,
    normalize_ws,
    tokenize,
    now_iso,
    file_checksum,
)

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
DATASET_CACHE_DIR = ROOT / "training_docs_inbox" / "datasets"

_ingest_status: dict[str, dict[str, Any]] = {}
_status_lock = threading.Lock()


def get_ingest_status(dataset_name: str) -> dict[str, Any]:
    with _status_lock:
        return dict(_ingest_status.get(dataset_name, {"status": "idle"}))


def _set_status(dataset_name: str, **kwargs: Any) -> None:
    with _status_lock:
        _ingest_status[dataset_name] = kwargs


def _download_maud_csv(split: str = "train") -> Path:
    from huggingface_hub import hf_hub_download
    filename = f"MAUD_v1/MAUD_{split}.csv"
    local_path = hf_hub_download("theatticusproject/maud", filename, repo_type="dataset")
    return Path(local_path)


def _download_maud_contract(contract_name: str) -> str | None:
    from huggingface_hub import hf_hub_download
    filename = f"MAUD_v1/contracts/{contract_name}.txt"
    try:
        local_path = hf_hub_download("theatticusproject/maud", filename, repo_type="dataset")
        return Path(local_path).read_text(encoding="utf-8", errors="ignore")
    except Exception:
        logger.debug("Could not download MAUD contract %s", contract_name)
        return None


def _download_cuad_json() -> Path:
    from huggingface_hub import hf_hub_download
    local_path = hf_hub_download("theatticusproject/cuad", "CUAD_v1/CUAD_v1.json", repo_type="dataset")
    return Path(local_path)


MAUD_CATEGORIES = {
    "Conditions to Closing": "due_diligence",
    "Deal Protection and Related Provisions": "purchase_agreement",
    "General Information": "general_ma",
    "Knowledge": "due_diligence",
    "Material Adverse Effect": "purchase_agreement",
    "Operating and Efforts Covenant": "purchase_agreement",
    "Remedies": "purchase_agreement",
}

CUAD_QUESTION_TO_CATEGORY = {
    "Document Name": "general_ma",
    "Parties": "general_ma",
    "Agreement Date": "general_ma",
    "Effective Date": "general_ma",
    "Expiration Date": "general_ma",
    "Renewal Term": "general_ma",
    "Notice Period To Terminate Renewal": "general_ma",
    "Governing Law": "regulatory",
    "Most Favored Nation": "purchase_agreement",
    "Non-Compete": "employment_benefits",
    "Exclusivity": "purchase_agreement",
    "No-Solicit Of Customers": "employment_benefits",
    "No-Solicit Of Employees": "employment_benefits",
    "Non-Disparagement": "employment_benefits",
    "Termination For Convenience": "purchase_agreement",
    "Change Of Control": "purchase_agreement",
    "Anti-Assignment": "ancillary_agreements",
    "Revenue/Profit Sharing": "purchase_agreement",
    "Price Restrictions": "purchase_agreement",
    "Minimum Commitment": "purchase_agreement",
    "Volume Restriction": "purchase_agreement",
    "IP Ownership Assignment": "ip_technology",
    "Joint IP Ownership": "ip_technology",
    "License Grant": "ip_technology",
    "Non-Transferable License": "ip_technology",
    "Affiliate License-Loss Of IP Rights Upon Bankruptcy": "ip_technology",
    "Uncapped Liability": "purchase_agreement",
    "Cap On Liability": "purchase_agreement",
    "Liquidated Damages": "purchase_agreement",
    "Warranty Duration": "purchase_agreement",
    "Insurance": "ancillary_agreements",
    "Covenant Not To Sue": "purchase_agreement",
    "Third Party Beneficiary": "purchase_agreement",
    "Audit Rights": "due_diligence",
    "Unlimited/All-You-Can-Eat-License": "ip_technology",
    "Irrevocable Or Perpetual License": "ip_technology",
    "Source Code Escrow": "ip_technology",
    "Post-Termination Services": "ancillary_agreements",
    "Competing Contract Limitation": "purchase_agreement",
    "ROFR/ROFO/ROFN": "purchase_agreement",
}


def ingest_maud(
    max_contracts: int = 50,
    splits: list[str] | None = None,
) -> dict[str, Any]:
    if splits is None:
        splits = ["train"]

    _set_status("maud", status="downloading", progress=0, total=0, message="Downloading MAUD dataset from HuggingFace...")

    try:
        contract_annotations: dict[str, list[dict[str, str]]] = {}
        total_rows = 0

        for split in splits:
            csv_path = _download_maud_csv(split)
            with open(csv_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    contract_name = row.get("contract_name", "")
                    if not contract_name:
                        continue
                    if contract_name not in contract_annotations:
                        contract_annotations[contract_name] = []
                    contract_annotations[contract_name].append({
                        "text": row.get("text", ""),
                        "question": row.get("question", ""),
                        "answer": row.get("answer", ""),
                        "category": row.get("category", ""),
                        "subquestion": row.get("subquestion", ""),
                    })
                    total_rows += 1

        contract_names = sorted(contract_annotations.keys())[:max_contracts]
        _set_status("maud", status="ingesting", progress=0, total=len(contract_names), message=f"Processing {len(contract_names)} MAUD contracts...")

        db = get_db()
        db.init_schema()
        splitter = RecursiveCharacterTextSplitter(chunk_size=1400, chunk_overlap=180)
        results = []

        for idx, contract_name in enumerate(contract_names):
            _set_status("maud", status="ingesting", progress=idx + 1, total=len(contract_names), message=f"Ingesting {contract_name}...")

            annotations = contract_annotations[contract_name]

            contract_text = _download_maud_contract(contract_name)

            annotation_block = "\n\n".join(
                f"[MAUD Q: {ann['question']}] [Category: {ann['category']}]\n"
                f"Answer: {ann['answer']}\n"
                f"Clause: {ann['text'][:800]}"
                for ann in annotations[:40]
            )

            if contract_text:
                full_text = f"=== MAUD Merger Agreement: {contract_name} ===\n\n{contract_text}\n\n=== MAUD Annotations ===\n\n{annotation_block}"
            else:
                full_text = f"=== MAUD Deal Point Annotations: {contract_name} ===\n\n{annotation_block}"

            if len(full_text.strip()) < 200:
                continue

            maud_categories = set(ann["category"] for ann in annotations if ann.get("category"))
            primary_category = "purchase_agreement"
            for cat in maud_categories:
                if cat in MAUD_CATEGORIES:
                    primary_category = MAUD_CATEGORIES[cat]
                    break

            tags = detect_tags(contract_name, full_text)
            tags["deal_structure"] = tags["deal_structure"] or "merger"

            metadata = {
                "original_filename": f"maud_{contract_name}.txt",
                "extension": ".txt",
                "word_count": len(re.findall(r"\w+", full_text)),
                "ingested_at": now_iso(),
                "jurisdiction": tags["jurisdiction"],
                "deal_stance": tags["deal_stance"],
                "deal_structure": tags["deal_structure"],
                "dataset_source": "MAUD",
                "maud_categories": sorted(maud_categories),
                "annotation_count": len(annotations),
            }

            chunks = []
            for split_doc in splitter.split_text(full_text):
                text = normalize_ws(split_doc)
                if len(text) >= 80:
                    chunks.append({"text": text, "page": 1})

            if not chunks:
                continue

            source_path = f"maud://{contract_name}"
            _ingest_dataset_document(
                db=db,
                title=f"MAUD_{contract_name}",
                source_path=source_path,
                category=primary_category,
                document_type="MAUD Annotated Agreement",
                source_system="MAUD Dataset (Atticus Project / HuggingFace)",
                metadata=metadata,
                chunks=chunks,
            )
            results.append({
                "title": f"MAUD_{contract_name}",
                "category": primary_category,
                "chunk_count": len(chunks),
                "annotation_count": len(annotations),
                "jurisdiction": tags["jurisdiction"],
                "deal_stance": tags["deal_stance"],
                "deal_structure": tags["deal_structure"],
            })

        _set_status("maud", status="complete", progress=len(results), total=len(contract_names),
                     message=f"Done. {len(results)} contracts ingested.")

        return {
            "status": "complete",
            "dataset": "MAUD",
            "contracts_processed": len(results),
            "total_annotations": total_rows,
            "results": results,
            "corpus_status": db.stats(),
        }

    except Exception as exc:
        logger.exception("MAUD ingestion failed")
        _set_status("maud", status="error", message=str(exc))
        return {"status": "error", "dataset": "MAUD", "message": str(exc)}


def ingest_cuad(max_contracts: int = 50) -> dict[str, Any]:
    _set_status("cuad", status="downloading", progress=0, total=0, message="Downloading CUAD dataset from HuggingFace...")

    try:
        json_path = _download_cuad_json()
        with open(json_path, "r", encoding="utf-8") as f:
            cuad_data = json.load(f)

        entries = cuad_data.get("data", [])[:max_contracts]
        _set_status("cuad", status="ingesting", progress=0, total=len(entries), message=f"Processing {len(entries)} CUAD contracts...")

        db = get_db()
        db.init_schema()
        splitter = RecursiveCharacterTextSplitter(chunk_size=1400, chunk_overlap=180)
        results = []

        for idx, entry in enumerate(entries):
            title_raw = entry.get("title", f"cuad_contract_{idx}")
            _set_status("cuad", status="ingesting", progress=idx + 1, total=len(entries), message=f"Ingesting {title_raw[:60]}...")

            paragraphs = entry.get("paragraphs", [])
            if not paragraphs:
                continue

            context = paragraphs[0].get("context", "")
            qas = paragraphs[0].get("qas", [])

            answered_qas = [qa for qa in qas if not qa.get("is_impossible") and qa.get("answers")]
            annotation_block = ""
            clause_categories: set[str] = set()

            if answered_qas:
                annotation_parts = []
                for qa in answered_qas[:41]:
                    question = qa.get("question", "")
                    answers = qa.get("answers", [])
                    answer_texts = [a.get("text", "") for a in answers if a.get("text")]

                    q_short = question.split('"')[1] if '"' in question else question[:60]
                    cuad_cat = CUAD_QUESTION_TO_CATEGORY.get(q_short, "general_ma")
                    clause_categories.add(cuad_cat)

                    if answer_texts:
                        annotation_parts.append(
                            f"[CUAD: {q_short}]\n"
                            f"Clause: {answer_texts[0][:600]}"
                        )
                annotation_block = "\n\n".join(annotation_parts)

            full_text = f"=== CUAD Contract: {title_raw} ===\n\n{context}"
            if annotation_block:
                full_text += f"\n\n=== CUAD Annotations ({len(answered_qas)} clauses identified) ===\n\n{annotation_block}"

            if len(full_text.strip()) < 200:
                continue

            classification = classify_document(title_raw, full_text)
            if clause_categories:
                ma_cats = clause_categories - {"general_ma"}
                if ma_cats:
                    classification["category"] = sorted(ma_cats)[0]

            tags = detect_tags(title_raw, full_text)

            metadata = {
                "original_filename": f"cuad_{title_raw[:80]}.txt",
                "extension": ".txt",
                "word_count": len(re.findall(r"\w+", full_text)),
                "ingested_at": now_iso(),
                "jurisdiction": tags["jurisdiction"],
                "deal_stance": tags["deal_stance"],
                "deal_structure": tags["deal_structure"],
                "dataset_source": "CUAD",
                "cuad_clauses_found": len(answered_qas),
                "cuad_clause_categories": sorted(clause_categories),
            }

            chunks = []
            for split_doc in splitter.split_text(full_text):
                text = normalize_ws(split_doc)
                if len(text) >= 80:
                    chunks.append({"text": text, "page": 1})

            if not chunks:
                continue

            safe_title = re.sub(r"[^\w\-]", "_", title_raw)[:100]
            source_path = f"cuad://{safe_title}"

            _ingest_dataset_document(
                db=db,
                title=f"CUAD_{safe_title}",
                source_path=source_path,
                category=classification["category"],
                document_type="CUAD Annotated Contract",
                source_system="CUAD Dataset (Atticus Project / HuggingFace)",
                metadata=metadata,
                chunks=chunks,
            )
            results.append({
                "title": f"CUAD_{safe_title}",
                "category": classification["category"],
                "chunk_count": len(chunks),
                "clauses_found": len(answered_qas),
                "jurisdiction": tags["jurisdiction"],
                "deal_stance": tags["deal_stance"],
                "deal_structure": tags["deal_structure"],
            })

        _set_status("cuad", status="complete", progress=len(results), total=len(entries),
                     message=f"Done. {len(results)} contracts ingested.")

        return {
            "status": "complete",
            "dataset": "CUAD",
            "contracts_processed": len(results),
            "results": results,
            "corpus_status": db.stats(),
        }

    except Exception as exc:
        logger.exception("CUAD ingestion failed")
        _set_status("cuad", status="error", message=str(exc))
        return {"status": "error", "dataset": "CUAD", "message": str(exc)}


def _ingest_dataset_document(
    db: CorpusDatabase,
    title: str,
    source_path: str,
    category: str,
    document_type: str,
    source_system: str,
    metadata: dict[str, Any],
    chunks: list[dict[str, Any]],
) -> int:
    import hashlib

    chunk_text_concat = "".join(c["text"] for c in chunks)
    checksum = hashlib.sha256(chunk_text_concat.encode("utf-8", errors="ignore")).hexdigest()[:32]

    with db.connect() as connection:
        existing = db._fetch_one(connection, "SELECT id FROM lawagent_documents WHERE source_path = %s", (source_path,))
        if existing:
            document_id = existing["id"]
            db._execute(connection, "DELETE FROM lawagent_chunks WHERE document_id = %s", (document_id,))
            if db.backend == "postgres":
                db._execute(
                    connection,
                    "UPDATE lawagent_documents SET title=%s, category=%s, document_type=%s, source_system=%s, checksum=%s, metadata=%s::jsonb WHERE id=%s",
                    (title, category, document_type, source_system, checksum, json.dumps(metadata), document_id),
                )
            else:
                db._execute(
                    connection,
                    "UPDATE lawagent_documents SET title=%s, category=%s, document_type=%s, source_system=%s, checksum=%s, metadata=%s WHERE id=%s",
                    (title, category, document_type, source_system, checksum, json.dumps(metadata), document_id),
                )
        else:
            document_id = db._insert_document(
                connection, title, source_path, category, document_type,
                source_system, checksum, metadata,
            )

        for index, chunk in enumerate(chunks):
            keywords = " ".join(sorted(tokenize(chunk["text"]))[:120])
            if db.backend == "postgres":
                db._execute(
                    connection,
                    """INSERT INTO lawagent_chunks (document_id, chunk_index, page, text, keywords, keywords_tsv, created_at)
                       VALUES (%s, %s, %s, %s, %s, to_tsvector('english', %s), %s)""",
                    (document_id, index, chunk["page"], chunk["text"], keywords, keywords, now_iso()),
                )
            else:
                db._execute(
                    connection,
                    """INSERT INTO lawagent_chunks (document_id, chunk_index, page, text, keywords, created_at)
                       VALUES (%s, %s, %s, %s, %s, %s)""",
                    (document_id, index, chunk["page"], chunk["text"], keywords, now_iso()),
                )
        connection.commit()
    return document_id


def dataset_summary() -> dict[str, Any]:
    db = get_db()
    docs = db.list_documents()
    maud_docs = [d for d in docs if "MAUD" in d.source_system]
    cuad_docs = [d for d in docs if "CUAD" in d.source_system]
    return {
        "maud": {
            "document_count": len(maud_docs),
            "chunk_count": sum(d.chunk_count for d in maud_docs),
            "status": get_ingest_status("maud"),
        },
        "cuad": {
            "document_count": len(cuad_docs),
            "chunk_count": sum(d.chunk_count for d in cuad_docs),
            "status": get_ingest_status("cuad"),
        },
    }
