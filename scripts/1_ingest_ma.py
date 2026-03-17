"""Ingest public or deal-room PDFs into a local Chroma collection."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from typing import Sequence

from langchain_chroma import Chroma
from langchain_community.document_loaders import PyPDFDirectoryLoader
from langchain_ollama import OllamaEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

DEFAULT_DATA_DIR = Path("data")
DEFAULT_CHROMA_DIR = Path("chroma_db")
DEFAULT_COLLECTION = "ma_test"
DEFAULT_EMBED_MODEL = "nomic-embed-text"
DEFAULT_CHUNK_SIZE = 2000
DEFAULT_CHUNK_OVERLAP = 200


def clear_db(chroma_dir: Path) -> None:
    if chroma_dir.exists():
        shutil.rmtree(chroma_dir)
    chroma_dir.mkdir(parents=True, exist_ok=True)


def load_documents(data_dir: Path):
    data_dir.mkdir(parents=True, exist_ok=True)
    pdf_files = sorted(data_dir.glob("*.pdf"))
    if not pdf_files:
        print(f"No PDF files found in {data_dir.resolve()}")
        return []

    loader = PyPDFDirectoryLoader(str(data_dir))
    docs = loader.load()
    print(f"Loaded {len(docs)} document pages from {len(pdf_files)} PDFs.")
    return docs


def chunk_documents(docs: Sequence, chunk_size: int, chunk_overlap: int):
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", ".", ";", " ", ""],
    )
    chunks = splitter.split_documents(docs)
    print(f"Created {len(chunks)} chunks (size={chunk_size}, overlap={chunk_overlap}).")
    return chunks


def ingest(
    data_dir: Path,
    chroma_dir: Path,
    collection_name: str,
    embed_model: str,
    chunk_size: int,
    chunk_overlap: int,
    reset_db: bool,
) -> int:
    if reset_db:
        clear_db(chroma_dir)
    else:
        chroma_dir.mkdir(parents=True, exist_ok=True)

    docs = load_documents(data_dir)
    if not docs:
        print("No documents were loaded; ingestion skipped.")
        return 1

    chunks = chunk_documents(docs, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    embeddings = OllamaEmbeddings(model=embed_model)
    Chroma.from_documents(
        documents=chunks,
        embedding=embeddings,
        persist_directory=str(chroma_dir),
        collection_name=collection_name,
    )
    print(
        "Ingestion complete.\n"
        f"Collection: {collection_name}\n"
        f"Persisted at: {chroma_dir.resolve()}"
    )
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest M&A contract PDFs into Chroma.")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--chroma-dir", type=Path, default=DEFAULT_CHROMA_DIR)
    parser.add_argument("--collection", default=DEFAULT_COLLECTION)
    parser.add_argument("--embed-model", default=DEFAULT_EMBED_MODEL)
    parser.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE)
    parser.add_argument("--chunk-overlap", type=int, default=DEFAULT_CHUNK_OVERLAP)
    parser.add_argument(
        "--no-reset",
        action="store_true",
        help="Do not delete existing chroma directory before ingesting.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.chunk_size <= 0:
        raise SystemExit("chunk-size must be > 0")
    if args.chunk_overlap < 0:
        raise SystemExit("chunk-overlap must be >= 0")
    if args.chunk_overlap >= args.chunk_size:
        raise SystemExit("chunk-overlap must be smaller than chunk-size")

    return ingest(
        data_dir=args.data_dir,
        chroma_dir=args.chroma_dir,
        collection_name=args.collection,
        embed_model=args.embed_model,
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
        reset_db=not args.no_reset,
    )


if __name__ == "__main__":
    sys.exit(main())

