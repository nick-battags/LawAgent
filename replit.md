# LawAgent

## Project Overview
LawAgent is a Python M&A Corrective RAG demo for legal diligence and drafting. It now includes a browser interface where users can paste an M&A contract for issue spotting, retrieve corrective drafting guidance, and generate a first-draft agreement from a guided Q&A.

## Runtime Setup
- Python runtime: 3.12 via `.replit`
- Dependencies: `requirements.txt`
- Replit workflow: `Start application` runs `python app.py`
- The web app binds to `0.0.0.0:5000` for the Replit preview.
- Production publish command is configured to run the Flask app with Gunicorn.

## Web App Features
- Contract paste-in issue spotting for merger, stock purchase, asset purchase, LOI, and term-sheet style documents.
- Deterministic Corrective RAG pipeline in `scripts/ma_crag_engine.py`:
  - Retrieves M&A clause guidance from a curated local knowledge base.
  - Grades contract text against expected legal coverage.
  - Corrects missing or weak provisions with suggested clauses and follow-up actions.
  - Generates a source-backed risk summary, issue list, clause map, diligence checklist, and references.
- Guided Q&A template assistant that fills a draft Agreement and Plan of Merger.
- Public-reference drafting corpus based on common clauses and organization patterns from public SEC EDGAR M&A filings.

## Important Commands
- Start web app: `python app.py`
- Ingest documents: `python scripts/1_ingest_ma.py`
- Run a single query: `python scripts/2_agent_ma.py --query "What are the assignment restrictions?"`
- Run batch tests: `python scripts/4_batch_test_ma.py --skip-eval`

## Notes
- The web demo path runs without Ollama so it can be demonstrated locally or through a Replit preview/published link.
- The original Chroma/Ollama CLI ingestion and CRAG scripts remain available for local model-backed workflows and require Ollama models (`qwen2.5:7b` and `nomic-embed-text`).
- `data/`, `chroma_db/`, `outputs/`, and `training_docs_inbox/` are treated as local/runtime directories.
- Outputs are educational drafting support only and are not legal advice.