# LawAgent

Local M&A due-diligence agent scaffold using Ollama + LangChain + LangGraph + Chroma.

This repo supports a structured Westlaw/Practical Law corpus workflow: recursive ingestion, legal-aware chunking, and metadata-based retrieval filters.

## What is included

- `scripts/1_ingest_ma.py`  
  Ingests `PDF`, `DOCX`, `TXT`, and `MD` files recursively from `data/`, adds metadata, performs format-aware cleanup, chunks by legal structure, and writes vectors to `chroma_db/`.
- `scripts/2_agent_ma.py`  
  Runs a CRAG-like LangGraph flow (`retrieve -> grade -> rewrite? -> generate`) with optional metadata filters.
- `scripts/3_eval_ma.py`  
  Scores answer faithfulness against provided excerpts.
- `scripts/4_batch_test_ma.py`  
  Runs a query suite and writes JSON regression-style results.
- `training_docs_inbox/`  
  Drop-zone for raw incoming documents before sorting into `data/`.
- `tests/ma_queries.json`  
  Starter batch query set.
- `tests/westlaw_metadata.sample.json`  
  Example metadata override file.

## 1) Local setup (Windows PowerShell)

```powershell
Set-Location "C:\Users\nickv\Documents\GitHub\LawAgent"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

If PowerShell blocks activation:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

## 2) Pull local Ollama models

```powershell
ollama pull qwen2.5:7b
ollama pull nomic-embed-text
ollama list
```

## 3) Organize incoming documents

1. Drop new raw files in `training_docs_inbox/`.
2. Sort selected files into `data/` using a structure like:

```text
data/
  westlaw/
    agreements/
    practice_notes/
    clauses/
    checklists/
```

3. Name files descriptively, for example:
- `spa_delaware_2023.pdf`
- `due_diligence_checklist.docx`
- `change_of_control_clause.docx`

## 4) Optional metadata overrides

If a filename/folder does not capture enough detail, add manual metadata overrides.

Example file: `tests/westlaw_metadata.sample.json`

Run ingestion with overrides:

```powershell
python scripts/1_ingest_ma.py --metadata-json .\tests\westlaw_metadata.sample.json
```

## 5) Ingest into Chroma

Default:

```powershell
python scripts/1_ingest_ma.py
```

Notes:
- PDF extraction prefers layout-aware parsing and merges short adjacent pages for better clause continuity.
- DOCX extraction preserves heading/list cues and converts tables into markdown-style text blocks.

Chunking tuning:

```powershell
python scripts/1_ingest_ma.py --chunk-size 1800 --chunk-overlap 180 --collection ma_test
```

PDF merge tuning:

```powershell
python scripts/1_ingest_ma.py --pdf-merge-min-chars 1200
```

Keep existing vector DB instead of reset:

```powershell
python scripts/1_ingest_ma.py --no-reset
```

## 6) Run the CRAG agent

Basic query:

```powershell
python scripts/2_agent_ma.py --query "What are the change of control provisions in the supply agreement?"
```

With metadata filters:

```powershell
python scripts/2_agent_ma.py `
  --query "What indemnification cap applies?" `
  --filter-source "Westlaw Practical Law" `
  --filter-document-type "Share Purchase Agreement" `
  --filter-jurisdiction "Delaware"
```

Save full run output:

```powershell
python scripts/2_agent_ma.py --query "What are assignment restrictions?" --json-output .\outputs\single_run.json
```

## 7) Run answer faithfulness evaluation

```powershell
python scripts/3_eval_ma.py
```

Custom input:

```powershell
python scripts/3_eval_ma.py `
  --query "What is the indemnification cap?" `
  --context "Section 5. Indemnification. The Seller shall indemnify the Buyer for losses up to $10 million." `
  --answer "The indemnification cap is $10 million."
```

## 8) Batch test multiple diligence questions

```powershell
python scripts/4_batch_test_ma.py
```

Custom run with filters:

```powershell
python scripts/4_batch_test_ma.py `
  --queries-file .\tests\ma_queries.json `
  --filter-source "Westlaw Practical Law" `
  --filter-practice-area "M&A" `
  --output-file .\outputs\batch_westlaw.json
```

## 9) Switch from placeholder to real deal data

1. Remove placeholder files from `data/`.
2. Keep old data isolated by switching collection name, for example `--collection ma_deal_abc`.
3. Re-run ingestion.
4. Run query/batch scripts with the new collection.

## Troubleshooting

- If ingestion loads no files, confirm documents are under `data/` and extensions are `pdf/docx/txt/md`.
- If agent script says vector store is missing, run ingestion first.
- If Ollama connection fails, confirm Ollama is running and models are pulled.
- If answers are weak, tune:
  - chunking (`--chunk-size`, `--chunk-overlap`)
  - retrieval depth (`--k`)
  - rewrite retries (`--max-rewrites`)
  - metadata filters (`--filter-*`)
