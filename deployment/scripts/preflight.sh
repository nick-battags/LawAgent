#!/usr/bin/env bash
set -euo pipefail

echo "== LawAgent hybrid preflight =="

if [[ ! -f "../deployment/.env.vps" ]]; then
  echo "Missing ../deployment/.env.vps"
  echo "Copy deployment/.env.vps.example to deployment/.env.vps and fill values."
  exit 1
fi

source ../deployment/.env.vps

echo "Checking required commands..."
for cmd in docker docker compose curl; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "Missing command: $cmd"
    exit 1
  fi
done

echo "Checking local app health endpoint after stack starts..."
echo "Checking Ollama endpoint from VPS: ${OLLAMA_BASE_URL}"
if curl -fsS "${OLLAMA_BASE_URL}/api/tags" >/dev/null 2>&1; then
  echo "Ollama reachable."
else
  echo "WARNING: Ollama not reachable now. AUTO mode will use deterministic fallback."
fi

echo "Preflight complete."
