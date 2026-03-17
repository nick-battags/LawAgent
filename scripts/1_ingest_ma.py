"""Ingest legal documents into a local Chroma collection with rich metadata."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Sequence

from docx import Document as DocxDocument
from langchain_chroma import Chroma
from langchain_community.document_loaders import PyPDFLoader
from langchain_core.documents import Document
from langchain_ollama import OllamaEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

DEFAULT_DATA_DIR = Path("data")
DEFAULT_CHROMA_DIR = Path("chroma_db")
DEFAULT_COLLECTION = "ma_test"
DEFAULT_EMBED_MODEL = "nomic-embed-text"
DEFAULT_CHUNK_SIZE = 2000
DEFAULT_CHUNK_OVERLAP = 200
SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}

LEGAL_SEPARATORS = [
    r"\n\s*Section\s+\d+[A-Za-z]?\.",
    r"\n\s*Article\s+[IVXLC0-9]+",
    r"\n\s*\d+(?:\.\d+)*\.\s+",
    r"\n\s*\([a-z]\)\s+",
    r"\n\n",
    r"\n",
    r"\.\s+",
    r";\s+",
    r"\s+",
    "",
]

PAGE_NUMBER_RE = re.compile(r"^\s*(?:page\s+)?\d+\s*(?:of\s+\d+)?\s*$", flags=re.IGNORECASE)

JURISDICTION_HINTS = {
    "delaware": "Delaware",
    "newyork": "New York",
    "ny": "New York",
    "california": "California",
    "texas": "Texas",
    "uk": "UK",
    "unitedkingdom": "UK",
    "england": "UK",
    "eu": "EU",
    "europeanunion": "EU",
}

DOCUMENT_TYPE_HINTS = [
    ("sharepurchaseagreement", "Share Purchase Agreement"),
    ("assetpurchaseagreement", "Asset Purchase Agreement"),
    ("stockpurchaseagreement", "Stock Purchase Agreement"),
    ("mergeragreement", "Merger Agreement"),
    ("practice_note", "Practice Note"),
    ("practicenote", "Practice Note"),
    ("checklist", "Checklist"),
    ("clause", "Clause"),
    ("agreement", "Agreement"),
    ("table", "Comparison Table"),
]

PRACTICE_AREA_HINTS = [
    ("employment", "Employment"),
    ("ip", "IP"),
    ("privacy", "Privacy"),
    ("tax", "Tax"),
    ("regulatory", "Regulatory"),
    ("merger", "M&A"),
    ("acquisition", "M&A"),
    ("spa", "M&A"),
    ("apa", "M&A"),
]

CLAUSE_TYPE_HINTS = [
    ("indemn", "Indemnification"),
    ("changeofcontrol", "Change of Control"),
    ("assignment", "Assignment"),
    ("assignability", "Assignment"),
    ("materialadverse", "Material Adverse Change"),
    ("mac", "Material Adverse Change"),
    ("termination", "Termination"),
    ("governinglaw", "Governing Law"),
    ("noncompete", "Non-Compete"),
    ("nonsolicit", "Non-Solicit"),
]


def clear_db(chroma_dir: Path) -> None:
    if chroma_dir.exists():
        shutil.rmtree(chroma_dir)
    chroma_dir.mkdir(parents=True, exist_ok=True)


def normalize_token(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return slug or "document"


def extract_tokens(relative_path: Path) -> list[str]:
    cleaned = str(relative_path.with_suffix("")).lower().replace("&", " and ")
    return [token for token in re.split(r"[^a-z0-9]+", cleaned) if token]


def pick_first_match(
    haystack: str,
    tokens: set[str],
    hints: list[tuple[str, str]],
    default: str,
) -> str:
    for key, value in hints:
        normalized_key = normalize_token(key)
        if not normalized_key:
            continue
        if len(normalized_key) <= 3:
            if normalized_key in tokens:
                return value
            continue
        if normalized_key in haystack:
            return value
    return default


def infer_jurisdiction(haystack: str, tokens: set[str]) -> str:
    for key, value in JURISDICTION_HINTS.items():
        normalized_key = normalize_token(key)
        if len(normalized_key) <= 3:
            if normalized_key in tokens:
                return value
            continue
        if normalized_key in haystack:
            return value
    return "Unspecified"


def infer_source(relative_path: Path) -> str:
    parts = [part.lower() for part in relative_path.parts]
    if "westlaw" in parts or "practical_law" in parts or "practicallaw" in parts:
        return "Westlaw Practical Law"
    if parts:
        return parts[0].replace("_", " ").title()
    return "Unknown"


def normalize_metadata_value(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def load_metadata_overrides(metadata_json: Path | None) -> dict[str, dict[str, Any]]:
    if not metadata_json:
        return {}
    if not metadata_json.exists():
        raise FileNotFoundError(f"Metadata file not found: {metadata_json.resolve()}")

    payload = json.loads(metadata_json.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Metadata override file must be a JSON object.")

    normalized: dict[str, dict[str, Any]] = {}
    for key, value in payload.items():
        if isinstance(value, dict):
            normalized[str(key)] = {k: normalize_metadata_value(v) for k, v in value.items()}
    return normalized


def build_base_metadata(
    file_path: Path,
    data_dir: Path,
    metadata_overrides: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    relative_path = file_path.relative_to(data_dir)
    relative_posix = relative_path.as_posix()
    token_list = extract_tokens(relative_path)
    token_set = set(token_list)
    haystack = "".join(token_list)

    metadata = {
        "source": infer_source(relative_path),
        "source_file": relative_posix,
        "doc_id": slugify(str(relative_path.with_suffix(""))),
        "document_type": pick_first_match(
            haystack, token_set, DOCUMENT_TYPE_HINTS, "General Document"
        ),
        "jurisdiction": infer_jurisdiction(haystack, token_set),
        "practice_area": pick_first_match(haystack, token_set, PRACTICE_AREA_HINTS, "M&A"),
        "clause_type": pick_first_match(haystack, token_set, CLAUSE_TYPE_HINTS, "General"),
        "ingested_date": datetime.fromtimestamp(file_path.stat().st_mtime, tz=UTC).strftime(
            "%Y-%m-%d"
        ),
        "file_extension": file_path.suffix.lower(),
    }

    override = metadata_overrides.get(relative_posix) or metadata_overrides.get(file_path.name)
    if override:
        metadata.update({k: normalize_metadata_value(v) for k, v in override.items()})
    return metadata


def clean_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    cleaned_lines = []
    for line in text.split("\n"):
        squashed = re.sub(r"[ \t]+", " ", line).strip()
        if PAGE_NUMBER_RE.match(squashed):
            continue
        cleaned_lines.append(squashed)
    cleaned = "\n".join(cleaned_lines)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def trim_repeated_boundary_lines(text: str, noisy_lines: set[str]) -> str:
    lines = text.splitlines()
    while lines and lines[0].strip() in noisy_lines:
        lines.pop(0)
    while lines and lines[-1].strip() in noisy_lines:
        lines.pop()
    return "\n".join(lines)


def remove_repeated_pdf_headers_footers(docs: list[Document]) -> list[Document]:
    grouped: dict[str, list[Document]] = defaultdict(list)
    for doc in docs:
        if str(doc.metadata.get("file_extension", "")).lower() == ".pdf":
            grouped[str(doc.metadata.get("source_file", "unknown"))].append(doc)

    for _, page_docs in grouped.items():
        if len(page_docs) < 3:
            continue

        boundary_counts: Counter[str] = Counter()
        for page_doc in page_docs:
            lines = [line.strip() for line in page_doc.page_content.splitlines() if line.strip()]
            if not lines:
                continue
            if len(lines[0]) <= 120:
                boundary_counts[lines[0]] += 1
            if len(lines[-1]) <= 120:
                boundary_counts[lines[-1]] += 1

        threshold = max(2, int(len(page_docs) * 0.6))
        noisy_lines = {line for line, count in boundary_counts.items() if count >= threshold}
        if not noisy_lines:
            continue

        for page_doc in page_docs:
            page_doc.page_content = trim_repeated_boundary_lines(page_doc.page_content, noisy_lines)
    return docs


def load_pdf(file_path: Path, data_dir: Path, metadata_overrides: dict[str, dict[str, Any]]) -> list[Document]:
    loader = PyPDFLoader(str(file_path))
    docs = loader.load()
    base_metadata = build_base_metadata(file_path, data_dir, metadata_overrides)
    for doc in docs:
        doc.metadata.update(base_metadata)
        page = doc.metadata.get("page")
        if isinstance(page, int):
            doc.metadata["page"] = page + 1
    return docs


def load_docx(
    file_path: Path,
    data_dir: Path,
    metadata_overrides: dict[str, dict[str, Any]],
) -> list[Document]:
    docx_file = DocxDocument(str(file_path))
    paragraphs = [p.text.strip() for p in docx_file.paragraphs if p.text and p.text.strip()]
    text = "\n\n".join(paragraphs).strip()
    if not text:
        return []
    metadata = build_base_metadata(file_path, data_dir, metadata_overrides)
    metadata["page"] = "n/a"
    return [Document(page_content=text, metadata=metadata)]


def load_text_file(
    file_path: Path,
    data_dir: Path,
    metadata_overrides: dict[str, dict[str, Any]],
) -> list[Document]:
    text = file_path.read_text(encoding="utf-8", errors="ignore").strip()
    if not text:
        return []
    metadata = build_base_metadata(file_path, data_dir, metadata_overrides)
    metadata["page"] = "n/a"
    return [Document(page_content=text, metadata=metadata)]


def detect_section_heading(text: str) -> str:
    preview = text[:1200]
    patterns = [
        r"(?im)^\s*((?:Section|Article)\s+[0-9IVXLC]+[^\n]{0,140})$",
        r"(?im)^\s*(\d+(?:\.\d+)*\.\s+[^\n]{0,140})$",
        r"(?im)^\s*([A-Z][A-Z \-/]{5,120})$",
    ]
    for pattern in patterns:
        match = re.search(pattern, preview)
        if match:
            return " ".join(match.group(1).split())[:160]

    first_line = next((line.strip() for line in preview.splitlines() if line.strip()), "")
    return first_line[:160] if first_line else "Unspecified"


def load_documents(
    data_dir: Path,
    metadata_overrides: dict[str, dict[str, Any]],
    skip_clean: bool,
) -> list[Document]:
    data_dir.mkdir(parents=True, exist_ok=True)
    files = sorted(path for path in data_dir.rglob("*") if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS)
    if not files:
        supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        print(f"No files found under {data_dir.resolve()} (supported: {supported})")
        return []

    docs: list[Document] = []
    for file_path in files:
        try:
            suffix = file_path.suffix.lower()
            if suffix == ".pdf":
                docs.extend(load_pdf(file_path, data_dir, metadata_overrides))
            elif suffix == ".docx":
                docs.extend(load_docx(file_path, data_dir, metadata_overrides))
            else:
                docs.extend(load_text_file(file_path, data_dir, metadata_overrides))
        except Exception as exc:  # pragma: no cover - runtime loader errors
            print(f"Skipped {file_path}: {exc}")

    docs = remove_repeated_pdf_headers_footers(docs)
    if not skip_clean:
        for doc in docs:
            doc.page_content = clean_text(doc.page_content)
        docs = [doc for doc in docs if doc.page_content.strip()]

    print(f"Loaded {len(docs)} raw document units from {len(files)} files.")
    return docs


def chunk_documents(docs: Sequence[Document], chunk_size: int, chunk_overlap: int) -> list[Document]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=LEGAL_SEPARATORS,
        is_separator_regex=True,
        add_start_index=True,
    )
    chunks = splitter.split_documents(docs)

    chunk_counter_by_doc: Counter[str] = Counter()
    for chunk in chunks:
        doc_id = str(chunk.metadata.get("doc_id", "unknown"))
        chunk_counter_by_doc[doc_id] += 1
        chunk.metadata["chunk_index"] = chunk_counter_by_doc[doc_id]
        chunk.metadata["section_heading"] = detect_section_heading(chunk.page_content)

    doc_type_counts = Counter(str(chunk.metadata.get("document_type", "Unknown")) for chunk in chunks)
    print(f"Created {len(chunks)} chunks (size={chunk_size}, overlap={chunk_overlap}).")
    print("Chunk distribution by document_type:")
    for doc_type, count in doc_type_counts.most_common():
        print(f"  - {doc_type}: {count}")
    return chunks


def ingest(
    data_dir: Path,
    chroma_dir: Path,
    collection_name: str,
    embed_model: str,
    chunk_size: int,
    chunk_overlap: int,
    reset_db: bool,
    metadata_overrides: dict[str, dict[str, Any]],
    skip_clean: bool,
) -> int:
    if reset_db:
        clear_db(chroma_dir)
    else:
        chroma_dir.mkdir(parents=True, exist_ok=True)

    docs = load_documents(
        data_dir=data_dir,
        metadata_overrides=metadata_overrides,
        skip_clean=skip_clean,
    )
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
    parser = argparse.ArgumentParser(description="Ingest legal documents into Chroma.")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--chroma-dir", type=Path, default=DEFAULT_CHROMA_DIR)
    parser.add_argument("--collection", default=DEFAULT_COLLECTION)
    parser.add_argument("--embed-model", default=DEFAULT_EMBED_MODEL)
    parser.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE)
    parser.add_argument("--chunk-overlap", type=int, default=DEFAULT_CHUNK_OVERLAP)
    parser.add_argument(
        "--metadata-json",
        type=Path,
        default=None,
        help="Optional JSON file with per-document metadata overrides.",
    )
    parser.add_argument(
        "--skip-clean",
        action="store_true",
        help="Skip text cleanup and keep raw extracted text.",
    )
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

    metadata_overrides = load_metadata_overrides(args.metadata_json)
    return ingest(
        data_dir=args.data_dir,
        chroma_dir=args.chroma_dir,
        collection_name=args.collection,
        embed_model=args.embed_model,
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
        reset_db=not args.no_reset,
        metadata_overrides=metadata_overrides,
        skip_clean=args.skip_clean,
    )


if __name__ == "__main__":
    sys.exit(main())
