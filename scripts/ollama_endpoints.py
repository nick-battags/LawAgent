"""Helpers for multi-endpoint Ollama routing and failover."""

from __future__ import annotations

import os
import re
from typing import Any

import requests


def parse_ollama_base_urls() -> list[str]:
    raw_multi = os.environ.get("OLLAMA_BASE_URLS", "").strip()
    if raw_multi:
        parts = [p.strip() for p in re.split(r"[,\s;]+", raw_multi) if p.strip()]
    else:
        parts = [os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434").strip()]

    deduped: list[str] = []
    seen: set[str] = set()
    for part in parts:
        normalized = part.rstrip("/")
        if normalized and normalized not in seen:
            seen.add(normalized)
            deduped.append(normalized)
    return deduped


def endpoint_label(index: int) -> str:
    if index == 0:
        return "primary"
    if index == 1:
        return "secondary"
    return f"fallback-{index + 1}"


def fetch_tags(base_url: str, timeout: int = 3) -> tuple[list[str], dict[str, Any]]:
    response = requests.get(f"{base_url}/api/tags", timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    models = [m.get("name", "") for m in payload.get("models", []) if m.get("name")]
    return models, payload
