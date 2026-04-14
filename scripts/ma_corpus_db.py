"""Centralized training corpus database and ingestion utilities."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from docx import Document as DocxDocument
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SQLITE_PATH = ROOT / "instance" / "lawagent_training.sqlite3"
DEPOSIT_DIRS = [ROOT / "attached_assets", ROOT / "training_docs_inbox"]
SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}


@dataclass
class CorpusDocument:
    id: int
    title: str
    source_path: str
    category: str
    document_type: str
    source_system: str
    checksum: str
    chunk_count: int
    created_at: str


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def file_checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def extract_text(path: Path) -> list[Document]:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        reader = PdfReader(str(path))
        docs = []
        for page_index, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            if text.strip():
                docs.append(Document(page_content=text, metadata={"page": page_index}))
        return docs
    if suffix == ".docx":
        doc = DocxDocument(path)
        text = "\n".join(paragraph.text for paragraph in doc.paragraphs if paragraph.text.strip())
        return [Document(page_content=text, metadata={"page": 1})] if text.strip() else []
    if suffix in {".txt", ".md"}:
        return [Document(page_content=path.read_text(encoding="utf-8", errors="ignore"), metadata={"page": 1})]
    return []


def classify_document(title: str, text: str) -> dict[str, str]:
    haystack = f"{title}\n{text[:8000]}".lower()
    rules = [
        ("ancillary_agreements", "Resource Kit", ["ancillary", "escrow agreements", "transition services", "assignment and assumption"]),
        ("asset_acquisition", "Resource Kit", ["asset acquisition", "asset purchase", "bill of sale", "assumed liabilities"]),
        ("due_diligence", "Resource Kit", ["due diligence", "request list", "diligence checklist", "specialist areas"]),
        ("corporate_templates_market_data", "Template Resource", ["market data", "templates integrated", "practical guidance content type"]),
        ("ip_technology", "Specialist Diligence", ["intellectual property", "software", "open source", "cybersecurity", "privacy"]),
        ("employment_benefits", "Specialist Diligence", ["employment", "employee benefits", "executive compensation", "change-in-control"]),
        ("regulatory", "Specialist Diligence", ["antitrust", "fcpa", "regulatory", "sanctions", "export controls"]),
        ("environmental", "Specialist Diligence", ["environmental", "climate change", "esg"]),
        ("real_estate", "Specialist Diligence", ["real estate", "reit", "property"]),
        ("purchase_agreement", "Agreement Template", ["agreement and plan", "purchase agreement", "merger agreement", "representations and warranties"]),
    ]
    for category, doc_type, keywords in rules:
        if any(keyword in haystack for keyword in keywords):
            return {"category": category, "document_type": doc_type}
    return {"category": "general_ma", "document_type": "Training Document"}


def detect_source_system(text: str, path: Path | None = None) -> str:
    lower = text[:3000].lower()
    if "lexisnexis" in lower or "practical guidance" in lower:
        return "LexisNexis Practical Guidance user-provided export"
    if "sec.gov" in lower or "edgar" in lower or "securities and exchange commission" in lower:
        return "SEC EDGAR public filing"
    if path and "edgar" in str(path).lower():
        return "SEC EDGAR public filing"
    if "securities exchange act" in lower or "form 8-k" in lower or "form 10-k" in lower:
        return "SEC EDGAR public filing"
    return "User-provided local document"


def tokenize(text: str) -> set[str]:
    return {token for token in re.findall(r"[a-zA-Z][a-zA-Z0-9_]{2,}", text.lower())}


class CorpusDatabase:
    def __init__(self) -> None:
        self.database_url = os.environ.get("DATABASE_URL")
        self.sqlite_path = Path(os.environ.get("LAWAGENT_SQLITE_PATH", DEFAULT_SQLITE_PATH))
        self.backend = "postgres" if self.database_url else "sqlite"

    def connect(self):
        if self.backend == "postgres":
            import psycopg
            from psycopg.rows import dict_row

            return psycopg.connect(self.database_url, row_factory=dict_row)
        self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.sqlite_path)
        connection.row_factory = sqlite3.Row
        return connection

    def init_schema(self) -> None:
        with self.connect() as connection:
            if self.backend == "postgres":
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS lawagent_documents (
                        id SERIAL PRIMARY KEY,
                        title TEXT NOT NULL,
                        source_path TEXT UNIQUE NOT NULL,
                        category TEXT NOT NULL,
                        document_type TEXT NOT NULL,
                        source_system TEXT NOT NULL,
                        checksum TEXT NOT NULL,
                        metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS lawagent_chunks (
                        id SERIAL PRIMARY KEY,
                        document_id INTEGER NOT NULL REFERENCES lawagent_documents(id) ON DELETE CASCADE,
                        chunk_index INTEGER NOT NULL,
                        page INTEGER NOT NULL,
                        text TEXT NOT NULL,
                        keywords TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                connection.execute("CREATE INDEX IF NOT EXISTS idx_lawagent_chunks_document_id ON lawagent_chunks(document_id)")
                connection.execute("CREATE INDEX IF NOT EXISTS idx_lawagent_documents_category ON lawagent_documents(category)")
            else:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS lawagent_documents (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        title TEXT NOT NULL,
                        source_path TEXT UNIQUE NOT NULL,
                        category TEXT NOT NULL,
                        document_type TEXT NOT NULL,
                        source_system TEXT NOT NULL,
                        checksum TEXT NOT NULL,
                        metadata TEXT NOT NULL DEFAULT '{}',
                        created_at TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS lawagent_chunks (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        document_id INTEGER NOT NULL,
                        chunk_index INTEGER NOT NULL,
                        page INTEGER NOT NULL,
                        text TEXT NOT NULL,
                        keywords TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        FOREIGN KEY(document_id) REFERENCES lawagent_documents(id) ON DELETE CASCADE
                    )
                    """
                )
            connection.commit()

    def upsert_document(self, path: Path) -> dict[str, Any]:
        self.init_schema()
        path = path.resolve()
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            return {"status": "skipped", "reason": "unsupported_file", "path": str(path)}

        checksum = file_checksum(path)
        extracted = extract_text(path)
        full_text = "\n\n".join(doc.page_content for doc in extracted)
        if not full_text.strip():
            return {"status": "skipped", "reason": "no_text_extracted", "path": str(path)}

        classification = classify_document(path.stem, full_text)
        source_system = detect_source_system(full_text, path)
        metadata = {
            "original_filename": path.name,
            "extension": path.suffix.lower(),
            "word_count": len(re.findall(r"\w+", full_text)),
            "ingested_at": now_iso(),
        }

        splitter = RecursiveCharacterTextSplitter(chunk_size=1400, chunk_overlap=180)
        chunks = []
        for doc in extracted:
            for split in splitter.split_documents([doc]):
                text = normalize_ws(split.page_content)
                if len(text) >= 80:
                    chunks.append({"text": text, "page": int(split.metadata.get("page", 1) or 1)})

        with self.connect() as connection:
            existing = self._fetch_one(connection, "SELECT id, checksum FROM lawagent_documents WHERE source_path = %s", (str(path),))
            if existing and existing["checksum"] == checksum:
                return {"status": "unchanged", "document_id": existing["id"], "path": str(path)}
            if existing:
                document_id = existing["id"]
                self._execute(
                    connection,
                    """
                    UPDATE lawagent_documents
                    SET title = %s, category = %s, document_type = %s, source_system = %s, checksum = %s, metadata = %s::jsonb
                    WHERE id = %s
                    """,
                    (
                        path.stem,
                        classification["category"],
                        classification["document_type"],
                        source_system,
                        checksum,
                        json.dumps(metadata),
                        document_id,
                    ),
                )
                self._execute(connection, "DELETE FROM lawagent_chunks WHERE document_id = %s", (document_id,))
            else:
                document_id = self._insert_document(
                    connection,
                    path.stem,
                    str(path),
                    classification["category"],
                    classification["document_type"],
                    source_system,
                    checksum,
                    metadata,
                )

            for index, chunk in enumerate(chunks):
                keywords = " ".join(sorted(tokenize(chunk["text"]))[:120])
                self._execute(
                    connection,
                    """
                    INSERT INTO lawagent_chunks (document_id, chunk_index, page, text, keywords, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (document_id, index, chunk["page"], chunk["text"], keywords, now_iso()),
                )
            connection.commit()

        return {
            "status": "ingested" if not existing else "updated",
            "document_id": document_id,
            "title": path.stem,
            "category": classification["category"],
            "document_type": classification["document_type"],
            "source_system": source_system,
            "chunk_count": len(chunks),
            "path": str(path),
        }

    def ingest_deposit_dirs(self) -> list[dict[str, Any]]:
        results = []
        for directory in DEPOSIT_DIRS:
            if not directory.exists():
                continue
            for path in sorted(directory.rglob("*")):
                if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
                    results.append(self.upsert_document(path))
        return results

    def retrieve(self, query: str, top_k: int = 8, category: str | None = None) -> list[dict[str, Any]]:
        self.init_schema()
        query_tokens = tokenize(query)
        if not query_tokens:
            return []
        with self.connect() as connection:
            if category:
                rows = self._fetch_all(
                    connection,
                    """
                    SELECT c.id, c.document_id, c.chunk_index, c.page, c.text, c.keywords,
                           d.title, d.category, d.document_type, d.source_system, d.source_path
                    FROM lawagent_chunks c
                    JOIN lawagent_documents d ON d.id = c.document_id
                    WHERE d.category = %s
                    """,
                    (category,),
                )
            else:
                rows = self._fetch_all(
                    connection,
                    """
                    SELECT c.id, c.document_id, c.chunk_index, c.page, c.text, c.keywords,
                           d.title, d.category, d.document_type, d.source_system, d.source_path
                    FROM lawagent_chunks c
                    JOIN lawagent_documents d ON d.id = c.document_id
                    """,
                    (),
                )

        scored = []
        for row in rows:
            text_tokens = tokenize(f"{row['title']} {row['category']} {row['keywords']} {row['text'][:2500]}")
            overlap = query_tokens & text_tokens
            score = len(overlap)
            if row["category"].replace("_", " ") in query.lower():
                score += 4
            if score:
                scored.append((score, row, overlap))
        ranked = sorted(scored, key=lambda item: item[0], reverse=True)[:top_k]
        return [
            {
                "score": score,
                "document_id": row["document_id"],
                "chunk_id": row["id"],
                "title": row["title"],
                "category": row["category"],
                "document_type": row["document_type"],
                "source_system": row["source_system"],
                "source_path": row["source_path"],
                "page": row["page"],
                "matched_terms": sorted(overlap)[:20],
                "text": row["text"],
            }
            for score, row, overlap in ranked
        ]

    def list_documents(self) -> list[CorpusDocument]:
        self.init_schema()
        with self.connect() as connection:
            rows = self._fetch_all(
                connection,
                """
                SELECT d.id, d.title, d.source_path, d.category, d.document_type, d.source_system,
                       d.checksum, d.created_at, COUNT(c.id) AS chunk_count
                FROM lawagent_documents d
                LEFT JOIN lawagent_chunks c ON c.document_id = d.id
                GROUP BY d.id, d.title, d.source_path, d.category, d.document_type, d.source_system, d.checksum, d.created_at
                ORDER BY d.created_at DESC
                """,
                (),
            )
        return [
            CorpusDocument(
                id=int(row["id"]),
                title=row["title"],
                source_path=row["source_path"],
                category=row["category"],
                document_type=row["document_type"],
                source_system=row["source_system"],
                checksum=row["checksum"],
                chunk_count=int(row["chunk_count"]),
                created_at=str(row["created_at"]),
            )
            for row in rows
        ]

    def stats(self) -> dict[str, Any]:
        documents = self.list_documents()
        categories: dict[str, int] = {}
        total_chunks = 0
        for doc in documents:
            categories[doc.category] = categories.get(doc.category, 0) + 1
            total_chunks += doc.chunk_count
        return {
            "backend": self.backend,
            "document_count": len(documents),
            "chunk_count": total_chunks,
            "categories": categories,
            "documents": [doc.__dict__ for doc in documents[:20]],
        }

    def _execute(self, connection, sql: str, params: tuple[Any, ...]):
        if self.backend == "sqlite":
            sql = sql.replace("%s", "?").replace("JSONB", "TEXT")
            sql = re.sub(r"::\w+", "", sql)
        return connection.execute(sql, params)

    def _fetch_one(self, connection, sql: str, params: tuple[Any, ...]):
        cursor = self._execute(connection, sql, params)
        row = cursor.fetchone()
        return dict(row) if row else None

    def _fetch_all(self, connection, sql: str, params: tuple[Any, ...]):
        cursor = self._execute(connection, sql, params)
        return [dict(row) for row in cursor.fetchall()]

    def _insert_document(
        self,
        connection,
        title: str,
        source_path: str,
        category: str,
        document_type: str,
        source_system: str,
        checksum: str,
        metadata: dict[str, Any],
    ) -> int:
        if self.backend == "postgres":
            row = connection.execute(
                """
                INSERT INTO lawagent_documents
                    (title, source_path, category, document_type, source_system, checksum, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
                RETURNING id
                """,
                (title, source_path, category, document_type, source_system, checksum, json.dumps(metadata)),
            ).fetchone()
            return int(row["id"])
        cursor = connection.execute(
            """
            INSERT INTO lawagent_documents
                (title, source_path, category, document_type, source_system, checksum, metadata, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (title, source_path, category, document_type, source_system, checksum, json.dumps(metadata), now_iso()),
        )
        return int(cursor.lastrowid)