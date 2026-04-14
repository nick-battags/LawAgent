# LawAgent

## Project Overview
LawAgent is a Python M&A Corrective RAG engine and pipeline accessible via a locally hosted, shareable browser demo. It has two distinct interfaces: a **frontend demo** (single-contract, session-scoped analysis with deal-specific document context) and a **backend management page** (global corpus pipeline, SEC EDGAR ingestion, document management). PostgreSQL-backed with SQLite fallback.

## Runtime Setup
- Python runtime: 3.12 via `.replit`
- Dependencies: `requirements.txt`
- Replit workflow: `Start application` runs `gunicorn -c gunicorn.conf.py app:app` (no `--preload` to avoid fork-unsafe C extension issues).
- The web app binds to `0.0.0.0:5000` for the Replit preview.
- PostgreSQL database provisioned via `DATABASE_URL` env var; SQLite fallback for local/GitHub replication.

## Architecture

### Two-Interface Design
- **Frontend Demo** (`/`) — Single-contract analysis with session-scoped document context. Users paste contracts, upload deal-specific docs (session only, not persisted), and run issue spotting. Clean demo flow for sharing.
- **Backend Management** (`/admin`) — Global corpus pipeline. Dashboard with stats, document management, corpus ingest/upload, SEC EDGAR search and ingest, document inventory table. Sidebar navigation between panels.

### V1 — Static CRAG Engine (`scripts/ma_crag_engine.py`)
- Deterministic issue spotting against a curated local M&A knowledge base.
- Retrieves guidance, grades contract text, corrects weak provisions, generates reports.
- No external API or model required for the demo path.

### V2 — Database-Backed LangChain CRAG Engine (`scripts/ma_db_crag_engine.py`)
- Uses a centralized PostgreSQL corpus database (`scripts/ma_corpus_db.py`).
- LangChain `RecursiveCharacterTextSplitter` (1400-char chunks, 180 overlap).
- Automatic document classification into M&A categories.
- Postgres: GIN-indexed `tsvector` full-text search with `ts_rank` scoring and SQL-level `LIMIT`; SQLite: `LIKE`-based keyword filtering fallback.
- Python-side relevance scoring and grading on the pre-filtered candidate set.
- Each issue gets corpus support citations from real training documents.
- Accepts optional `session_context` parameter — session-uploaded chunks are mixed into retrieval results and per-issue topical matching.

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

### Corpus Database (`scripts/ma_corpus_db.py`)
- Thread-safe singleton via `get_db()` — all modules share one `CorpusDatabase` instance per process.
- Schema initialization is cached with double-checked locking (`threading.Lock`).
- Dual-backend: PostgreSQL (via `DATABASE_URL`) or SQLite fallback.
- Tables: `lawagent_documents` and `lawagent_chunks`.
- Document extraction: PDF (pypdf), DOCX (python-docx), TXT, MD.
- Automatic classification into categories: ancillary_agreements, asset_acquisition, due_diligence, purchase_agreement, ip_technology, employment_benefits, regulatory, environmental, real_estate, general_ma.
- Source system detection: LexisNexis, SEC EDGAR, user-provided.

## Web App Pages

### Frontend Demo (`/`)
1. **Hero** — CRAG pipeline overview with navigation buttons.
2. **Session Context** — Upload deal-specific documents for this analysis session only.
3. **Contract Analyzer** — Paste-in issue spotting (V1 static or V2 database CRAG with session context).
4. **Template Assistant** — Guided Q&A to fill a draft Agreement and Plan of Merger. "Pre-fill from session context" button extracts deal details (party names, transaction type, purchase price, etc.) from uploaded session documents via regex and auto-populates form fields. Automatically routes to V2 generation endpoint when session docs are present.

### Backend Management (`/admin`)
1. **Dashboard** — Corpus stats (backend type, document count, chunk count, categories), document list.
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
- `POST /api/v2/analyze` — V2 database CRAG issue spotting (accepts `session_id`)
- `POST /api/session/upload` — Upload deal-specific doc to session (not persisted to corpus)
- `POST /api/session/extract-details` — Extract deal details from session docs for template auto-fill

### Backend (Admin)
- `GET /admin` — Backend management page
- `GET /api/v2/corpus/status` — Corpus database stats
- `POST /api/v2/corpus/ingest-deposits` — Ingest deposited files
- `POST /api/v2/corpus/upload` — Upload and ingest a file to global corpus
- `GET /api/v2/retrieve?q=&category=` — V2 corpus retrieval (admin-gated)
- `POST /api/v2/template/generate` — V2 template generation
- `GET /api/edgar/search?q=&max=&start_date=&end_date=` — Search EDGAR filings
- `POST /api/edgar/ingest` — Search, download, and ingest EDGAR filings

## Important Files
- `app.py` — Flask web server with all API routes, session store
- `gunicorn.conf.py` — Gunicorn configuration (gthread workers, graceful timeout, lifecycle hooks)
- `scripts/ma_crag_engine.py` — V1 deterministic CRAG engine
- `scripts/ma_db_crag_engine.py` — V2 database-backed CRAG engine (accepts session_context)
- `scripts/ma_corpus_db.py` — Corpus database and ingestion utilities
- `scripts/edgar_fetcher.py` — SEC EDGAR API integration
- `templates/index.html` — Frontend demo page
- `templates/admin.html` — Backend management page
- `static/app.js` — Frontend demo JavaScript (session upload, analysis, template)
- `static/admin.js` — Backend management JavaScript (dashboard, corpus, EDGAR, documents)
- `static/styles.css` — Shared styles
- `static/admin.css` — Admin-specific styles

## Deposit Directories
- `attached_assets/` — Auto-scanned for ingestion
- `training_docs_inbox/` — Auto-scanned for ingestion
- `training_docs_inbox/uploads/` — File upload target
- `training_docs_inbox/edgar/` — EDGAR download target

## Security
- **Admin PIN protection**: The `/admin` page and all admin API routes (`/api/v2/corpus/*`, `/api/edgar/*`) require PIN authentication via `ADMIN_PIN` env secret. Uses Flask sessions with `secrets.compare_digest` for timing-safe comparison. Login at `/admin/login`, logout at `/admin/logout`.
- No third-party AI API required for the demo path.
- Uploaded documents stay in the project database/local filesystem.
- Only text extracted from user-deposited documents is retrieved into answers.
- Flask MAX_CONTENT_LENGTH set to 25MB for uploads.
- Session uploads are temporary and not persisted to the corpus.

## Notes
- The web demo path runs without Ollama so it can be demonstrated locally or through a Replit preview/published link.
- The original Chroma/Ollama CLI scripts remain available for local model-backed workflows.
- Outputs are educational drafting support only and are not legal advice.
