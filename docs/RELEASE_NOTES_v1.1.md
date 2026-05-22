# v1.1 — Public launch (Argus rebrand + cream + burgundy theme)

**Released:** 2026-05-20
**Live at:** [nickvbattaglia.com](https://nickvbattaglia.com) · [lawagent.nickvbattaglia.com](https://lawagent.nickvbattaglia.com)
**Diff:** [v1.0...v1.1](https://github.com/nick-battags/LawAgent/compare/v1.0...v1.1)

This is the version that went public at the apex flip from Namecheap to Cloudflare Pages. It folds in the Argus rebrand, a full editorial cream + burgundy theme refresh, a critical landing-page readability fix, and a chat endpoint stability fix.

---

## What changed since v1.0

### Branding
- Renamed the product from **LawAgent** → **Argus** across the landing, hub, chat, and admin surfaces. The GitHub repo retains the original name to preserve clone URLs.
- Renamed the right-hand landing card from "M&A Issue Spotter" → "Ask the Corpus" to match what the surface actually does.

### Theme
- Replaced the default purple-on-near-black dark-mode palette with a "law library" editorial cream + burgundy light-mode theme (`--bg: #F5EDDC`, `--accent: #722F37`, `--text: #1F1B17`).
- Typography polish: Newsreader serif on headings with negative letter-spacing for editorial weight; Inter sans on body at line-height 1.7.
- Hub doc viewer now renders as pure white (`#FFFFFF`) on the cream workspace for paper-on-table contrast.

### Bugs fixed
- **`landing.css`**: three `color: #fff` declarations (hero h1, card titles, hover CTA) were leftover from the dark theme, rendering the headline and card titles invisible on the cream background. Replaced with `var(--text)` and `var(--accent-strong)`.
- **`/api/v2/context/list`**: was returning HTTP 500 on every chat-page load because the Supermemory client was being called with `q=" "` (single space), which fails Supermemory's 1-char-minimum validation. Changed query token to `"."` and made the except handler degrade to `{"sources": [], "count": 0}` with HTTP 200 instead of bubbling the 500.

### Navigation
- Added a cross-surface header back-link (`← Nick Battaglia`) on every Argus page (landing, hub, chat, review, admin) linking back to the portfolio at `nickvbattaglia.com`.

### Documentation
- Replaced the landing page's numbered pipeline list with an ASCII Corrective RAG diagram (consistent with the portfolio's `PipelineDiagram` component).
- README v1.1: rebranded to Argus, refreshed the corpus chunk count from the planned ~14,500 to the actual shipped 11,266, added version + license + stack shields.

### Corpus (locked from the v1.0 ingest phase)
- 11,266 chunks in Neon pgvector:
  - 22 curated playbook chunks (12 categories)
  - 7,067 CUAD spans (commercial-contract clause annotations)
  - 4,177 MAUD spans (merger-agreement question-level annotations)
- Embedded with Cohere Embed v4 (1024-d), reranked with Cohere Rerank 3.5.

---

## Production stack at v1.1

| Layer | Choice |
|---|---|
| Anonymizer | Vertex Gemini 2.5 Flash-Lite (per-session two-way pseudonym map, in-process only) |
| Embeddings | Cohere `embed-v4.0`, output_dimension=1024 |
| Vector store | Neon serverless Postgres + pgvector 0.8.0, HNSW index (`vector_cosine_ops`) |
| Reranker | Cohere `rerank-v3.5` |
| Generator | Vertex Gemini 2.5 Flash |
| Session memory | Supermemory (anonymized writes only, session-scoped, server-side TTL) |
| Backend | Flask on Cloud Run (us-central1, 2 GB / 2 vCPU) |
| Frontend hosting | Cloudflare Pages (portfolio) + Cloudflare DNS |

---

## Verified health at release

Diagnostic sweep across Cloud Run, Vertex AI, Cohere, Neon, Supermemory, Cloud Storage, Secret Manager, and Cloud Logging at release time:

- Zero ERROR or CRITICAL log events in the prior 24 hours (9 WARNINGs)
- All public endpoints returning HTTP 200 (`/`, `/hub`, `/chat`, `/api/v2/context/list`)
- Neon database: 176 MB / 512 MB free-tier cap (34% utilized)
- pgvector HNSW index: 92 MB
- Cohere: zero 429 rate-limits in 24h
- Supermemory: 7/7 writes successful

---

## Known follow-ups (post-launch backlog)

- **Cosmetic — CUAD category labels.** The `category` field for CUAD rows is stored as the slugified-then-truncated HuggingFace question string (e.g. `highlight_the_parts_(if_any)_of_this_contract_related_to_"ex`). Retrieval is unaffected (cosine similarity ignores category), but the label is verbose if surfaced in UI. Cleanup requires re-ingesting CUAD with an extraction-before-truncation pass.
- **Operational — Cloud Scheduler jobs.** Hourly session-sweep and nightly eval jobs were explicitly deprecated for v1.0/v1.1 because traffic is far below the Supermemory free-tier ceiling. Wire when traffic warrants.
- **Observability — latency telemetry.** `generation_latency_ms` markers aren't currently emitted in structured form, so log-based percentile analysis isn't possible. Add when SLO dashboards are needed.

---

## Disclaimer

Argus is a portfolio demonstration tool built by a JD/MBA candidate for educational research on M&A contract drafting. It does **not** provide legal advice, does **not** establish an attorney-client relationship, and is **not** a substitute for counsel. Output should be verified by a licensed attorney before use. See [/legal](https://lawagent.nickvbattaglia.com/legal) for the full notice.
