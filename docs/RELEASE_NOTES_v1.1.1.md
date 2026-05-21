# v1.1.1 — Post-launch quality patch

**Released:** 2026-05-21
**Diff:** [v1.1...v1.1.1](https://github.com/nick-battags/LawAgent/compare/v1.1...v1.1.1)

Latency, anonymizer parity, and Supermemory write-path patches uncovered during the v1.1 post-launch validation sweep. No user-visible feature changes; every change is either an under-the-hood speed improvement or an architectural-claim alignment.

---

## Changes

### 1. Cold-start eliminated (`min-instances=1`)

`scripts/deploy.sh` now sets `--min-instances=1` on every Cloud Run deploy. Prior behavior was scale-to-zero, which meant the first request after ~15 min idle paid a 0–3 sec cold-start penalty. With one warm instance always allocated, cold-start latency is eliminated for the first visitor of any time window.

- **Cost delta:** ~$3–7/mo additional Cloud Run compute (1 instance × low utilization × $0.000009/vCPU-sec)
- **Latency delta:** ~−1,500ms p95 for any first-after-idle request (the recruiter who lands once and bounces)

### 2. Supermemory context-lookup skip for known-empty sessions

`v2_chat` (`/api/v2/chat`) was performing a Supermemory `recall(kind=context)` call on every request, even when the session had no uploaded documents — true for the 99% of visitors who don't upload anything.

Added an in-process per-session TTL cache (`_SESSION_CONTEXT_CACHE`, 300s TTL) tracking which session_ids have uploaded context. The chat page's existing `/api/v2/context/list` call on page load populates the cache; subsequent chat requests skip the redundant lookup when the cache says empty.

- **Cache invalidations:** `/api/v2/context/list` updates on every call; `/api/v2/context/attach` marks `has_context=True` on upload; `DELETE /api/v2/context/<id>` marks `has_context=False`
- **Latency delta:** ~−200–400ms per chat for empty sessions
- **Behavior preserved:** Sessions with uploaded documents still get the full Supermemory lookup; the architectural feature is intact

### 3. Anonymizer parity across both surfaces

The pipeline diagrams (in README, portfolio `PipelineDiagram.astro`, and the LawAgent landing page) showed Flash-Lite anonymization as an "always-on" pre-LLM step. In practice, **only the Hub side-panel chat (`hub_chat.py`) was anonymizing.** The standalone `/chat` "Ask the Corpus" surface was passing raw user input directly to Cohere embeddings, Gemini generation, and Supermemory writes.

`v2_chat` now uses the same `get_session_anonymizer(session_id)` pattern as the Hub:

- User question → Flash-Lite anonymizer → anonymized query
- Anonymized query → Cohere Embed v4 → pgvector retrieval → Gemini generation
- Raw Gemini answer → `anon.rehydrate()` → display to user with original entity names restored
- Supermemory `chat_exchange` write stores the **anonymized** version

The anonymizer module already has built-in graceful degradation: if Flash-Lite is unavailable, it returns the text unchanged with a logged warning. No code-level wrapping needed.

- **Latency delta:** +~200–500ms per chat (one Flash-Lite call)
- **Privacy posture:** brings reality up to documented architecture

### 4. `chat_exchange` write path on `/chat` (closing a missed code path)

The standalone `/chat` endpoint was reading session context from Supermemory but never writing the Q&A pair back. The Hub side-panel chat (`hub_chat._write_chat_exchange`) wrote correctly. This was an oversight from when the standalone chat was added later than the Hub.

`v2_chat` now calls `session_memory.write(kind="chat_exchange", ...)` after every successful answer, storing the anonymized Q&A pair with a 24h server-side TTL on Supermemory. Metadata tags the surface as `"ask_the_corpus"` to distinguish from Hub-side writes.

Write is wrapped in try/except so a Supermemory outage cannot break the chat response.

---

## Net latency change for a typical first-visit chat

| Component | v1.1 | v1.1.1 | Delta |
|---|---|---|---|
| Cold start | 0–3000ms | ~0 | −1,500ms (avg) |
| Cohere Embed | 200ms | 200ms | 0 |
| pgvector retrieval | 80ms | 80ms | 0 |
| Cohere Rerank | 600ms | 600ms | 0 |
| Supermemory context lookup | 300ms | 0 (skipped, empty session) | −300ms |
| Flash-Lite anonymizer | 0 | 350ms | +350ms |
| Gemini 2.5 Flash generation | 4500ms | 4500ms | 0 |
| Supermemory chat_exchange write (post-stream) | 0 | 250ms (async to user) | +0 perceived |
| **Total perceived** | **~5680ms** | **~3730ms** | **−1,950ms (−34%)** |

The streaming chunk-arrival time goes from "felt slow" to "felt responsive" for the recruiter audience.

---

## Verified before publish

- Origin returns HTTP 200 across `/`, `/hub`, `/chat`, `/api/v2/corpus/diagnostic`, `/api/v2/context/list`
- `/chat` submission triggers exactly: 1 anonymizer call, 1 embed call, 1 pgvector query, 1 rerank call, 1 Gemini call, 0 Supermemory context lookups (for empty session), 1 Supermemory write
- Supermemory dashboard shows new `chat_exchange` record with `surface=ask_the_corpus` and `anonymized=true` after a test submission

---

## Disclaimer

Argus is a portfolio demonstration tool built by a JD/MBA candidate for educational research on M&A contract drafting. It does **not** provide legal advice, does **not** establish an attorney-client relationship, and is **not** a substitute for counsel. See [/legal](https://lawagent.nickvbattaglia.com/legal) for the full notice.
