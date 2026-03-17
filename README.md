# LawAgent

Local M&A due-diligence agent scaffold using Ollama + LangChain + LangGraph + Chroma.

This repo is configured so you can test the full pipeline with placeholder public contracts before proprietary deal documents arrive.

## What is included

- `scripts/1_ingest_ma.py`  
  Loads PDFs from `data/`, chunks them, and writes vectors to `chroma_db/`.
- `scripts/2_agent_ma.py`  
  Runs a CRAG-like LangGraph flow (`retrieve -> grade -> rewrite? -> generate`).
- `scripts/3_eval_ma.py`  
  Scores answer faithfulness against provided excerpts.
- `scripts/4_batch_test_ma.py`  
  Runs a query suite and writes JSON results for regression-style review.
- `data/` and `chroma_db/`  
  Local corpus and local vector persistence directories.
- `tests/ma_queries.json`  
  Starter batch query set.

## 1) Local setup (Windows PowerShell)

```powershell
Set-Location "C:\Users\nickv\Documents\GitHub\LawAgent"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## 2) Pull local Ollama models

```powershell
ollama pull qwen2.5:7b
ollama pull nomic-embed-text
ollama list
```

## 3) Add placeholder PDFs

Drop 5-10 public contract PDFs into:

`C:\Users\nickv\Documents\GitHub\LawAgent\data\`

Example filenames:
- `supply_agreement_acme.pdf`
- `employment_agreement_exec.pdf`
- `ip_license_contoso.pdf`
- `asset_purchase_agreement.pdf`

## 4) Ingest into Chroma

```powershell
python scripts/1_ingest_ma.py
```

Optional tuning:

```powershell
python scripts/1_ingest_ma.py --chunk-size 1800 --chunk-overlap 180 --collection ma_test
```

## 5) Run the CRAG agent

```powershell
python scripts/2_agent_ma.py --query "What are the change of control provisions in the supply agreement?"
```

Optional tuning:

```powershell
python scripts/2_agent_ma.py --query "What termination rights exist?" --k 6 --max-rewrites 2
```

Save full run output to JSON (query, rewrites, sources, answer):

```powershell
python scripts/2_agent_ma.py --query "What are assignment restrictions?" --json-output .\outputs\single_run.json
```

## 6) Run answer faithfulness evaluation

Quick built-in sample:

```powershell
python scripts/3_eval_ma.py
```

Custom inputs:

```powershell
python scripts/3_eval_ma.py `
  --query "What is the indemnification cap?" `
  --context "Section 5. Indemnification. The Seller shall indemnify the Buyer for losses up to $10 million." `
  --answer "The indemnification cap is $10 million."
```

Or with files:

```powershell
python scripts/3_eval_ma.py --query "..." --context-file .\context.txt --answer-file .\answer.txt
```

## 7) Batch test multiple diligence questions

```powershell
python scripts/4_batch_test_ma.py
```

This reads `tests/ma_queries.json` and writes a timestamped JSON report to `outputs/`.

Custom run:

```powershell
python scripts/4_batch_test_ma.py `
  --queries-file .\tests\ma_queries.json `
  --collection ma_test `
  --k 6 `
  --output-file .\outputs\batch_custom.json
```

## 8) Switch from placeholder to real deal data

1. Remove placeholder files from `data/`.
2. Option A: re-use the same collection by re-ingesting (default resets `chroma_db/`).
3. Option B: keep side-by-side collections with `--collection ma_deal_abc`.
4. Re-run ingestion, then run the agent.

## Troubleshooting

- If agent script says vector store is missing, run ingestion first.
- If Ollama connection fails, confirm Ollama is running and models are pulled.
- If answers are weak, tune:
  - chunking (`--chunk-size`, `--chunk-overlap`)
  - retrieval depth (`--k`)
  - rewrite retries (`--max-rewrites`)
