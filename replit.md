# LawAgent

## Project Overview
LawAgent is a Python M&A Corrective RAG engine and pipeline accessible via a locally hosted, shareable browser demo. It supports paste-in contract issue spotting, guided Q&A template-filling for merger agreements, a database-backed document corpus with automatic classification, and SEC EDGAR API integration for training data.

## Runtime Setup
- Python runtime: 3.12 via `.replit`
- Dependencies: `requirements.txt`
- Replit workflow: `Start application` runs `gunicorn -c gunicorn.conf.py app:app` (no `--preload` to avoid fork-unsafe C extension issues).
- The web app binds to `0.0.0.0:5000` for the Replit preview.
- PostgreSQL database provisioned via `DATABASE_URL` env var; SQLite fallback for local/GitHub replication.

## Architecture

### V1 — Static CRAG Engine (`scripts/ma_crag_engine.py`)
- Deterministic issue spotting against a curated local M&A knowledge base.
- Retrieves guidance, grades contract text, corrects weak provisions, generates reports.
- No external API or model required for the demo path.

### V2 — Database-Backed LangChain CRAG Engine (`scripts/ma_db_crag_engine.py`)
- Uses a centralized PostgreSQL corpus database (`scripts/ma_corpus_db.py`).
- LangChain `RecursiveCharacterTextSplitter` (1400-char chunks, 180 overlap).
- Automatic document classification into M&A categories.
- Keyword-based retrieval with relevance grading and query rewriting.
- Each issue gets corpus support citations from real training documents.

### SEC EDGAR Integration (`scripts/edgar_fetcher.py`)
- Searches the SEC EDGAR full-text search index (EFTS API) for M&A exhibits.
- Downloads filing text, cleans HTML, and ingests into the corpus database.
- Supports configurable queries, date ranges, and filing counts.

### Corpus Database (`scripts/ma_corpus_db.py`)
- Thread-safe singleton via `get_db()` — all modules share one `CorpusDatabase` instance per process.
- Schema initialization is cached with double-checked locking (`threading.Lock`).
- Dual-backend: PostgreSQL (via `DATABASE_URL`) or SQLite fallback.
- Tables: `lawagent_documents` and `lawagent_chunks`.
- Document extraction: PDF (pypdf), DOCX (python-docx), TXT, MD.
- Automatic classification into categories: ancillary_agreements, asset_acquisition, due_diligence, purchase_agreement, ip_technology, employment_benefits, regulatory, environmental, real_estate, general_ma.
- Source system detection: LexisNexis, SEC EDGAR, user-provided.

## Web App Sections
1. **Hero** — CRAG pipeline overview with navigation buttons.
2. **V2 Corpus** — Ingest deposited files, upload training documents, search corpus, view status.
3. **SEC EDGAR** — Search and ingest real merger agreements from SEC public filings.
4. **Contract Analyzer** — Paste-in issue spotting (V1 static or V2 database CRAG).
5. **Template Assistant** — Guided Q&A to fill a draft Agreement and Plan of Merger.
6. **Knowledge Base** — Public-reference drafting corpus cards.

## API Routes
- `GET /` — Main page
- `GET /health` — Health check
- `GET /api/sample-contract` — Sample contract text
- `POST /api/analyze` — V1 static issue spotting
- `GET /api/template/questions` — Template Q&A fields
- `POST /api/template/generate` — Generate V1 draft agreement
- `GET /api/retrieve?q=` — V1 knowledge base retrieval
- `GET /api/v2/corpus/status` — Corpus database stats
- `POST /api/v2/corpus/ingest-deposits` — Ingest deposited files
- `POST /api/v2/corpus/upload` — Upload and ingest a file
- `GET /api/v2/retrieve?q=&category=` — V2 corpus retrieval
- `POST /api/v2/analyze` — V2 database CRAG issue spotting
- `POST /api/v2/template/generate` — V2 template generation
- `GET /api/edgar/search?q=&max=&start_date=&end_date=` — Search EDGAR filings
- `POST /api/edgar/ingest` — Search, download, and ingest EDGAR filings

## Important Files
- `app.py` — Flask web server with all API routes
- `scripts/ma_crag_engine.py` — V1 deterministic CRAG engine
- `scripts/ma_db_crag_engine.py` — V2 database-backed CRAG engine
- `scripts/ma_corpus_db.py` — Corpus database and ingestion utilities
- `scripts/edgar_fetcher.py` — SEC EDGAR API integration
- `templates/index.html` — Main page template
- `static/app.js` — Frontend JavaScript
- `static/styles.css` — Styles

## Deposit Directories
- `attached_assets/` — Auto-scanned for ingestion
- `training_docs_inbox/` — Auto-scanned for ingestion
- `training_docs_inbox/uploads/` — File upload target
- `training_docs_inbox/edgar/` — EDGAR download target

## Security
- No third-party AI API required for the demo path.
- Uploaded documents stay in the project database/local filesystem.
- Only text extracted from user-deposited documents is retrieved into answers.
- Flask MAX_CONTENT_LENGTH set to 25MB for uploads.

## Notes
- The web demo path runs without Ollama so it can be demonstrated locally or through a Replit preview/published link.
- The original Chroma/Ollama CLI scripts remain available for local model-backed workflows.
- Outputs are educational drafting support only and are not legal advice.
