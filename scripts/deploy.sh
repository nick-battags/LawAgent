#!/usr/bin/env bash
# deploy.sh — authoritative Cloud Run deploy wrapper for lawagent-app
#
# IMPORTANT: gcloud --set-env-vars and --set-secrets REPLACE the entire map.
# Never run `gcloud run services update` with those flags directly —
# it will silently drop whichever side you omit. Use this script so the
# full config is always in one place.
#
# Usage:
#   ./scripts/deploy.sh                   # update env+secrets only (fast, no build)
#   ./scripts/deploy.sh --build           # submit a Cloud Build + update env+secrets
#   ./scripts/deploy.sh --build --push    # build, update, then confirm traffic
#
# Requires: gcloud CLI authenticated as nickvbattaglia@gmail.com

set -euo pipefail

PROJECT_ID=$(gcloud config get-value project 2>/dev/null)
REGION=us-central1
SERVICE=lawagent-app
IMAGE="us-central1-docker.pkg.dev/${PROJECT_ID}/lawagent/${SERVICE}"

BUILD=false
for arg in "$@"; do
  [[ "$arg" == "--build" ]] && BUILD=true
done

if $BUILD; then
  echo "==> Submitting Cloud Build…"
  gcloud builds submit \
    --tag "${IMAGE}:$(git rev-parse --short HEAD)" \
    --project "$PROJECT_ID"
  echo "==> Deploying new image…"
  gcloud run deploy "$SERVICE" \
    --image "${IMAGE}:$(git rev-parse --short HEAD)" \
    --region "$REGION" \
    --project "$PROJECT_ID"
fi

echo "==> Applying full env + secrets map…"
gcloud run services update "$SERVICE" \
  --region "$REGION" \
  --project "$PROJECT_ID" \
  --set-env-vars="DEMO_MODE=true,HUB_ENABLED=true,NODE_ENV=production,LLM_PROVIDER=vertex,VERTEX_LOCATION=${REGION},GCP_PROJECT=${PROJECT_ID},VECTOR_BACKEND=pgvector,SUPERMEMORY_CORPUS_TAG=lawagent-corpus,HUB_PROMPT_MAX_CHARS=5000" \
  --set-secrets="DATABASE_URL=lawagent-db-url:latest,FLASK_SECRET_KEY=lawagent-flask-secret:latest,CONSENT_SECRET=lawagent-consent-secret:latest,SUPERMEMORY_API_KEY=lawagent-supermemory-key:latest,COHERE_API_KEY=lawagent-cohere-key:latest,SCHEDULER_SECRET=lawagent-scheduler-secret:latest"

echo ""
echo "==> Verifying…"
sleep 5
curl -sf "https://lawagent-app-987904849203.us-central1.run.app/api/v2/llm/status" | python3 -m json.tool
curl -sf "https://lawagent-app-987904849203.us-central1.run.app/api/v2/corpus/diagnostic" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print('vector_count:', d['status']['vector_count'])"
echo "==> Done."
