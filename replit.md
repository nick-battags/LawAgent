# LawAgent

## Project Overview
LawAgent is a Python M&A Corrective RAG engine with a 2-model LLM architecture, accessible via a locally hosted browser demo. It has two interfaces: a **frontend demo** (single-contract analysis with deal-specific document context) and a **backend management page** (global corpus pipeline, vector index management, SEC EDGAR ingestion, document management). PostgreSQL-backed with SQLite fallback. Designed for local Ollama deployment as a portfolio project with graceful deterministic fallback when no LLM is available.

## Runtime Setup
- Python runtime: 3.12 via `.replit`
- Dependencies: `requirements.txt`
- Replit workflow: `Start application` runs `gunicorn -c gunicorn.conf.py app:app` (no `--preload` to avoid fork-unsafe C extension issues).
- The web app binds to `0.0.0.0:5000` for the Replit preview.
- PostgreSQL database provisioned via `DATABASE_URL` env var; SQLite fallback for local/GitHub replication.
- ChromaDB persistent vector store at `./chroma_data/`.

## Architecture

### Two-Interface Design
- **Frontend Demo** (`/`) — Single-contract analysis with session-scoped document context. Users paste contracts, upload deal-specific docs (session only, not persisted), and run issue spotting. Clean demo flow for sharing.
- **Backend Management** (`/admin`) — Global corpus pipeline. Dashboard with stats, vector index management, LLM status, document management, corpus ingest/upload, SEC EDGAR search and ingest, document inventory table. Sidebar navigation between panels.

### 2-Model CRAG Pipeline
The V2 engine uses a Corrective RAG pipeline with two local LLM models via Ollama:

1. **Embedding & Retrieval** — User query embedded via `nomic-embed-text` (Ollama) or `all-MiniLM-L6-v2` (default fallback). Top-k vectors retrieved from ChromaDB.
2. **Grading** — `Llama 3.1 8B` scores each retrieved chunk for relevance with strict JSON output (`{"score": "yes"}` / `{"score": "no"}`).
3. **CRAG Loop** — If no chunks pass grading, Llama rewrites the query using alternative legal terminology and retries retrieval (max 2 attempts).
4. **Generation** — `Command-R 7B` synthesizes approved chunks into analysis with inline citations (`[Source: filename, Page N]`).
5. **Deterministic Fallback** — When Ollama is unavailable, keyword-based grading and the existing regex/knowledge-base analysis engine still run.

### Pipeline Files
- `scripts/vector_store.py` — ChromaDB vector store wrapper. Singleton via `get_vector_store()`. Supports Ollama nomic-embed-text embeddings with automatic default fallback. Syncs from PostgreSQL (source of truth).
- `scripts/llm_provider.py` — Ollama HTTP API client. Singleton via `get_llm()`. Grader prompts (Llama 3.1), query rewriting, generation prompts (Command-R7B), issue enhancement. Availability detection.
- `scripts/crag_pipeline.py` — CRAG orchestrator. `retrieve_and_grade()` (retrieve → grade → rewrite → retry), `generate_with_context()` (Command-R7B synthesis), `enhance_issue_with_llm()` (per-issue analysis), `pipeline_status()`.

### V1 — Static CRAG Engine (`scripts/ma_crag_engine.py`)
- Deterministic issue spotting against a curated local M&A knowledge base.
- Retrieves guidance, grades contract text, corrects weak provisions, generates reports.
- No external API or model required for the demo path.

### V2 — Database + LLM CRAG Engine (`scripts/ma_db_crag_engine.py`)
- Uses the 2-model CRAG pipeline for retrieval, grading, and generation.
- ChromaDB vector retrieval with PostgreSQL full-text search fallback.
- LLM-enhanced issue analysis with recommended corrective language and precedent basis.
- Deterministic clause map and regex issue detection always runs (LLM enhances, never replaces).
- Each issue gets corpus support citations from real training documents plus optional LLM enhancement.
- Accepts optional `session_context` parameter — session-uploaded chunks are mixed into retrieval results.

### Session Context System
- In-memory `_session_store` keyed by client-generated UUID, protected by `threading.Lock`.
- Session documents are extracted, classified, chunked (same pipeline as corpus), but NOT persisted to the database.
- Session chunks are mixed into V2 analysis: combined with corpus results and used for per-issue topical support matching.
- Limits: 50 concurrent sessions, 10 documents per session.
- Session data is discarded on server restart.

### SEC EDGAR Integration (`scripts/edgar_fetcher.py`)
- Searches the SEC EDGAR full-text search index (EFTS API) for M&A exhibits.
- Downloads filing text, cleans HTML, and ingests into the corpus database.
- Supports configurable queries, date ranges, and filing counts.
- Retry logic with exponential backoff for HTTP requests.
- Rate-limiting to respect SEC's 10 req/sec limit.

### MAUD Dataset Integration (`scripts/dataset_fetcher.py`)
- Ingests expert-annotated merger agreements from the Atticus Project's MAUD dataset (CC BY 4.0, HuggingFace).
- 153 real merger agreements with 92 labeled deal point categories.
- Background thread ingestion with real-time progress polling.

### CUAD Dataset Integration (`scripts/dataset_fetcher.py`)
- Ingests 510 expert-annotated commercial contracts from the Atticus Project's CUAD dataset (CC BY 4.0, HuggingFace).
- 41 clause types including change of control, IP ownership, non-compete, indemnification, governing law, etc.

### Corpus Database (`scripts/ma_corpus_db.py`)
- Thread-safe singleton via `get_db()` — all modules share one `CorpusDatabase` instance per process.
- Schema initialization is cached with double-checked locking (`threading.Lock`).
- Dual-backend: PostgreSQL (via `DATABASE_URL`) or SQLite fallback.
- Tables: `lawagent_documents` and `lawagent_chunks`.
- `get_all_chunks()` method returns all chunks with metadata for ChromaDB sync.
- Automatic classification into categories and tag detection.

### Vector Store (`scripts/vector_store.py`)
- ChromaDB persistent client at `./chroma_data/`.
- PostgreSQL is the source of truth; ChromaDB syncs from it at startup (if empty) and on demand.
- Embedding: Ollama nomic-embed-text when available, ChromaDB default (all-MiniLM-L6-v2) otherwise.
- Collection: `lawagent_corpus` with cosine similarity.
- Batch upsert with deduplication (500-chunk batches).

## Web App Pages

### Frontend Demo (`/`)
1. **Hero** — CRAG pipeline overview with 2-model architecture description and live pipeline status indicator.
2. **Session Context** — Upload deal-specific documents for this analysis session only.
3. **Contract Analyzer** — Paste-in issue spotting (V1 static or V2 CRAG with LLM enhancement and session context).
4. **Template Assistant** — Guided Q&A to fill a draft Agreement and Plan of Merger.

### Backend Management (`/admin`)
1. **Dashboard** — Corpus stats, vector count, LLM mode, pipeline info grid (Ollama status, grader, generator, embedding, vectors, mode), vector sync/clear controls.
2. **Corpus Management** — Ingest deposited files, upload training documents, test corpus retrieval.
3. **SEC EDGAR** — Search and ingest real merger agreements from SEC public filings.
4. **Documents** — Full document inventory table with category, type, source, chunk count.

## API Routes

### Frontend (Demo)
- `GET /` — Frontend demo page
- `GET /health` — Health check
- `GET /api/sample-contract` — Sample contract text
- `POST /api/analyze` — V1 static issue spotting
- `GET /api/template/questions` — Template Q&A fields
- `POST /api/template/generate` — Generate V1 draft agreement
- `GET /api/retrieve?q=` — V1 knowledge base retrieval
- `POST /api/v2/analyze` — V2 CRAG issue spotting with LLM enhancement (accepts `session_id`)
- `POST /api/session/upload` — Upload deal-specific doc to session
- `POST /api/session/extract-details` — Extract deal details from session docs
- `GET /api/v2/pipeline/status` — Pipeline status (vector store + LLM info)
- `GET /api/v2/llm/status` — LLM availability and model info

### Backend (Admin)
- `GET /admin` — Backend management page
- `GET /api/v2/corpus/status` — Corpus database stats
- `POST /api/v2/corpus/ingest-deposits` — Ingest deposited files
- `POST /api/v2/corpus/upload` — Upload and ingest files to global corpus
- `DELETE /api/v2/corpus/document/<id>` — Delete a document
- `POST /api/v2/corpus/document/<id>/tags` — Update tags
- `GET /api/v2/retrieve?q=&category=` — V2 corpus retrieval
- `POST /api/v2/template/generate` — V2 template generation
- `POST /api/v2/vectors/sync` — Sync PostgreSQL chunks to ChromaDB
- `POST /api/v2/vectors/clear` — Clear ChromaDB vector index
- `GET /api/edgar/search` — Search EDGAR filings
- `POST /api/edgar/ingest` — Download and ingest EDGAR filings
- `GET /api/datasets/status` — Dataset stats
- `POST /api/datasets/maud/ingest` — Start MAUD ingestion
- `GET /api/datasets/maud/status` — Poll MAUD progress
- `POST /api/datasets/cuad/ingest` — Start CUAD ingestion
- `GET /api/datasets/cuad/status` — Poll CUAD progress

## Important Files
- `app.py` — Flask web server with all API routes, session store, startup vector sync
- `gunicorn.conf.py` — Gunicorn configuration (gthread workers, graceful timeout)
- `scripts/ma_crag_engine.py` — V1 deterministic CRAG engine
- `scripts/ma_db_crag_engine.py` — V2 database + LLM CRAG engine
- `scripts/ma_corpus_db.py` — Corpus database and ingestion utilities
- `scripts/vector_store.py` — ChromaDB vector store wrapper
- `scripts/llm_provider.py` — Ollama LLM provider (Llama 3.1 + Command-R7B)
- `scripts/crag_pipeline.py` — CRAG pipeline orchestrator
- `scripts/edgar_fetcher.py` — SEC EDGAR API integration
- `scripts/dataset_fetcher.py` — MAUD/CUAD dataset ingestion
- `templates/index.html` — Frontend demo page
- `templates/admin.html` — Backend management page
- `static/app.js` — Frontend demo JavaScript
- `static/admin.js` — Backend management JavaScript
- `static/styles.css` — Shared styles
- `static/admin.css` — Admin-specific styles

## Environment Variables
- `DATABASE_URL` — PostgreSQL connection string (auto-provisioned on Replit)
- `ADMIN_PIN` — Required secret for admin access
- `OLLAMA_BASE_URL` — Ollama server URL (default: `http://localhost:11434`)
- `GRADER_MODEL` — Grader model name (default: `llama3.1:8b`)
- `GENERATOR_MODEL` — Generator model name (default: `command-r:7b`)
- `EMBEDDING_MODEL` — Embedding model name (default: `nomic-embed-text`)
- `LLM_TIMEOUT` — LLM request timeout in seconds (default: `120`)

## Security
- **Admin PIN protection**: The `/admin` page and all admin API routes require PIN authentication via `ADMIN_PIN` env secret.
- All LLM models run locally via Ollama — no data leaves the machine.
- Graceful deterministic fallback when Ollama is unavailable.
- Uploaded documents stay in the project database/local filesystem.
- Flask MAX_CONTENT_LENGTH set to 25MB for uploads.

## Deployment Notes
- The web demo runs without Ollama (deterministic fallback) for Replit preview/published links.
- For full LLM pipeline: install Ollama locally, pull `llama3.1:8b`, `command-r:7b`, and `nomic-embed-text`.
- ChromaDB data persists at `./chroma_data/` — survives restarts.
- Outputs are educational drafting support only and are not legal advice.
