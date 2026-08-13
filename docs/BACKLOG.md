# Post-v1.1.1 Backlog

Items deferred from v1.0 → v1.1.1 launch, captured here so they don't get rediscovered. Grouped by category, ranked by user-visible impact.

---

## A. Quality of life (no user impact, low effort)

### A1. Diagnostic endpoint warmup query
**Symptom:** First call of the day to `/api/v2/corpus/diagnostic` takes ~5.7 sec; subsequent calls ~200ms.

**Cause:** `_eager_warmup()` initializes the pgvector pool and Vertex client at import time, but the first actual Cohere embed + pgvector query pays a cold-path cost (Cohere edge region warmup, query planner first-touch).

**Fix:** Add a one-line sample query inside `_eager_warmup()`:
```python
try:
    store = get_demo_vector_store()
    store.query("warmup query", top_k=1)  # forces first-query lazy init
except Exception as exc:
    logger.warning("Warmup: sample query failed (continuing): %s", exc)
```
Adds ~500ms to deploy time, eliminates the first-of-day latency on the diagnostic endpoint.

**Priority:** Low. End users don't hit `/api/v2/corpus/diagnostic`. The user-facing `/chat` and `/hub` already do fresh queries on each request and are fast.

---

### A2. Duplicate `db-url` secrets in Secret Manager
**Symptom:** Two secrets exist for the same database URL:
- `lawagent-db-url` (created 2026-05-13)
- `lawagent-database-url` (created 2026-05-14)

**Cause:** Likely a deploy-script tweak created the second one without removing the first.

**Fix:** Identify which one the deploy script actually references (`scripts/deploy.sh` line 45 — `lawagent-db-url`), then delete the unused duplicate:
```bash
gcloud secrets delete lawagent-database-url --project=lawagent-prod-494818
```

**Priority:** Low. Cleanup, not blocking.

---

### A3. Anonymizer per-session client cache (currently re-instantiates each call)
**Symptom:** Every chat submission creates a new `_SessionAnonymizer` and rebuilds the placeholder map from session memory. The map IS persisted across messages within a session via the module-level `_sessions` dict in `scripts/anonymizer.py`, but the LLM call to populate `existing_map` for new entities runs every time.

**Cause:** Working as designed, but a small efficiency gain is available — cache successful placeholders longer than a single request.

**Priority:** Low. Latency benefit is ~50-100ms per chat. Real users won't notice.

---

## B. Cosmetic / documentation drift (no functional impact)

### B1. CUAD category labels are verbose-truncated HF question strings
**Symptom:** CUAD chunks in `clause_chunks` have `category` values like:
```
highlight_the_parts_(if_any)_of_this_contract_related_to_"ex
```
instead of clean labels like `exclusivity`.

**Cause:** The CUAD ingest function slugified the HF question string and truncated at 60 chars before extracting the concept. The closing quote got chopped, so the concept name is unrecoverable from the stored data.

**Fix:** Two-step.
1. Patch `scripts/corpus/ingest_datasets.py` to extract the concept BEFORE slugify/truncate:
   ```python
   if '"' in question:
       concept = question.split('"')[1]   # e.g. "Anti-Assignment"
       category = concept.lower().replace(" ", "_").replace("-", "_")[:60]
   ```
2. Re-ingest CUAD with the new code:
   ```sql
   DELETE FROM clause_chunks WHERE source_system = 'cuad_v1';
   ```
   Then `POST /api/v2/corpus/ingest-datasets` with `{"dataset":"cuad","max_contracts":510}`.

**Risk:** Re-ingest has historically had restart-from-zero behavior on the streaming HuggingFace dataset. Expect partial completion; monitor `vector_count` and re-trigger if it stalls.

**Priority:** Cosmetic-only. Retrieval works fine (cosine similarity ignores category strings). The category surfaces only in citation tooltips that few users see.

---

### B2. Observability — no `generation_latency_ms` log markers
**Symptom:** Cloud Run logs don't contain structured latency telemetry. Cannot run log-based percentile analysis (p50/p95/p99 latency) for Vertex Gemini calls.

**Fix:** Add a wrapping helper in `scripts/llm_provider.py` that times each `_generate()` call and emits a structured log:
```python
import time
def _generate(self, prompt, ...):
    t0 = time.time()
    try:
        result = ...  # existing logic
        return result
    finally:
        logger.info("generation_latency_ms=%d model=%s", int((time.time() - t0) * 1000), model)
```

**Priority:** Low until traffic justifies SLO dashboards. For a portfolio demo with ~5-10 visits/day, percentile analysis is noise.

---

## C. Operational hygiene (deferred from v1.0 plan)

### C1. Cloud Scheduler session-sweep job
**Why deferred:** Hub sessions already expose an authenticated sweep endpoint, but the scheduler wiring remains an operational decision.

**When to revisit:** Before wider traffic or whenever Hub-session cleanup must be enforced independently of explicit user deletion.

**Implementation outline:** Hit the existing `/api/v2/hub/sweep` endpoint every hour via Cloud Scheduler. Auth via the existing `lawagent-scheduler-secret`:
```bash
gcloud scheduler jobs create http lawagent-hourly-sweep \
  --location=us-central1 \
  --schedule="0 * * * *" \
  --uri="https://lawagent.nickvbattaglia.com/api/v2/hub/sweep" \
  --http-method=POST \
  --headers="X-Scheduler-Secret=$SCHEDULER_SECRET" \
  --time-zone=UTC
```

**Priority:** Defer until traffic warrants.

---

### C2. Research-only Session-source retention decision
**Why:** The application performs explicit remove and Hub session delete/sweep cleanup, but standalone Research sessions are not tracked in `hub_sessions`. The application therefore does not enforce a 24-hour lifetime for Research-only uploads.

**Status:** Provider/account retention has not been verified. Do not claim an account-level policy is absent or configured until it is inspected separately.

**Decision options:**
1. Verify and, if appropriate, configure provider account-level retention.
2. Track Research-only sessions so scheduled application cleanup can remove their uploaded sources.
3. Evaluate a later Neon design for Session sources using measured provider reliability and latency evidence.

**Priority:** Medium. Until one option is selected, the UI tells users to remove uploaded Session sources when finished and continues to prohibit confidential or identifying material.

---

### C3. $50 Cloud Billing alert
**Why:** The v1.0 plan called for a $50/mo budget alert as a kill-switch. Sweep confirms no active budgets exist.

**Fix:** In https://console.cloud.google.com/billing → Budgets & alerts → Create budget with thresholds at 50%/90%/100%/120%, notify `dvbattag@iu.edu`.

**Priority:** Worth doing soon now that the apex is public. ~5 min in the console.

---

## D. Major architectural items (out of scope for v1.x)

### D1. Multi-document Hub support
Current Hub supports one document at a time. v2.x could support comparing two contracts side-by-side, or ingesting a related Document A (e.g., MSA) when reviewing Document B (e.g., SOW).

### D2. Provenance citations in chat answers
Chat answers cite source titles like `[1] CUAD: MOELIS_CO_03_24_2014-EX-10.19-STRATEGIC ALLIANCE AGREEMENT`, but no jump-to-source. v2.x could surface a side panel with the actual snippet that justified each citation, with cosine similarity score.

### D3. Comparison mode
"What's different between this NDA and the standard playbook?" — semantic diff against a golden template. Would require a second pgvector index keyed by golden templates.

### D4. Enterprise version
Multi-tenant authentication, per-firm corpus, audit logs, SSO. Out of scope for a portfolio demo but is the natural commercialization path.

---

## Branching note (post-v1.1.1)

All development happens on `main`. The historical `phase-2-hub` branch was deleted on 2026-05-21 after v1.1.1 launch to eliminate the branch-confusion class of bugs that caused a stale-image deploy during v1.1.1 validation.
