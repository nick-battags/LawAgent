# LawAgent

## Project Overview
LawAgent is a Python command-line M&A due-diligence RAG scaffold. It ingests local legal documents from `data/`, stores vectors in `chroma_db/`, and runs LangChain/LangGraph workflows using local Ollama models.

## Runtime Setup
- Python runtime: 3.12 via `.replit`
- Dependencies: `requirements.txt`
- Replit workflow: `Start application` runs `python scripts/replit_runner.py`
- The workflow is a console runner, not a web frontend. It validates the core modules and keeps the Replit process alive with usage instructions.

## Important Commands
- Ingest documents: `python scripts/1_ingest_ma.py`
- Run a single query: `python scripts/2_agent_ma.py --query "What are the assignment restrictions?"`
- Run batch tests: `python scripts/4_batch_test_ma.py --skip-eval`

## Notes
- Full ingestion/query execution requires Ollama to be running with the expected local models (`qwen2.5:7b` and `nomic-embed-text`).
- `data/`, `chroma_db/`, `outputs/`, and `training_docs_inbox/` are treated as local/runtime directories.