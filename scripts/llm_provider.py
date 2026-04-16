"""Ollama LLM provider for the 2-model CRAG pipeline.

Llama 3.1 8B: grader/gatekeeper (strict JSON relevance scoring, query rewriting).
Command-R 7B: generator (synthesis with inline citations, contract analysis).
Supports app-level endpoint failover via OLLAMA_BASE_URLS.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any

import requests

from scripts.ollama_endpoints import endpoint_label, fetch_tags, parse_ollama_base_urls

logger = logging.getLogger(__name__)

_provider: OllamaProvider | None = None


def get_llm() -> OllamaProvider:
    global _provider
    if _provider is None:
        _provider = OllamaProvider()
    return _provider


class OllamaProvider:
    def __init__(self) -> None:
        self.base_urls = parse_ollama_base_urls()
        self.base_url = self.base_urls[0]
        self.requested_grader_model = "llama3.1:8b"
        self.requested_generator_model = "command-r:7b"
        self.requested_grader_model = os.environ.get("GRADER_MODEL", self.requested_grader_model)
        self.requested_generator_model = os.environ.get("GENERATOR_MODEL", self.requested_generator_model)
        self.grader_model = self.requested_grader_model
        self.generator_model = self.requested_generator_model
        self.timeout = int(os.environ.get("LLM_TIMEOUT", "120"))
        self.failure_cooldown_sec = int(os.environ.get("LLM_FAILURE_COOLDOWN_SEC", "45"))
        self.endpoint_backoff_sec = int(os.environ.get("LLM_ENDPOINT_BACKOFF_SEC", "30"))
        self.memory_cooldown_sec = int(os.environ.get("LLM_MEMORY_COOLDOWN_SEC", "300"))
        self._available: bool | None = None
        self._models: list[str] = []
        self._endpoint_models: dict[str, list[str]] = {}
        self._endpoint_backoff_until: dict[str, float] = {}
        self._active_url: str | None = None
        self._active_backend: str = "none"
        self._cooldown_until: float = 0.0
        self._last_error: str = ""
        self._chat_endpoint = "/api/chat"
        self._lock = threading.RLock()

    @staticmethod
    def _now() -> float:
        return time.time()

    def _cooldown_remaining(self) -> int:
        return max(0, int(self._cooldown_until - self._now()))

    def _healthy_urls(self) -> list[str]:
        now = self._now()
        return [url for url in self.base_urls if self._endpoint_backoff_until.get(url, 0.0) <= now]

    def _iter_urls(self) -> list[str]:
        healthy = self._healthy_urls()
        if not healthy:
            return []
        if not self._active_url:
            return healthy
        ordered = []
        if self._active_url in healthy:
            ordered.append(self._active_url)
        for url in healthy:
            if url != self._active_url:
                ordered.append(url)
        return ordered

    def _set_active(self, url: str, models: list[str]) -> None:
        self._active_url = url
        self.base_url = url
        self._available = True
        self._models = models
        self._endpoint_models[url] = models
        try:
            index = self.base_urls.index(url)
        except ValueError:
            index = 0
        self._active_backend = endpoint_label(index)
        self._endpoint_backoff_until[url] = 0.0
        self._cooldown_until = 0.0
        self._last_error = ""
        self.grader_model = self._resolve_model_name(self.requested_grader_model, models=models)
        self.generator_model = self._resolve_model_name(self.requested_generator_model, models=models)

    def _set_global_cooldown(self, seconds: int, reason: str) -> None:
        self._cooldown_until = max(self._cooldown_until, self._now() + max(1, seconds))
        self._last_error = reason
        self._available = False
        self._active_backend = "cooldown"
        self._active_url = None

    def _register_failure(self, url: str, exc: requests.RequestException) -> None:
        detail = self._format_request_error(exc)
        lower = detail.lower()
        cooldown = self.endpoint_backoff_sec
        if "requires more system memory" in lower or "insufficient memory" in lower:
            cooldown = max(cooldown, self.memory_cooldown_sec)

        self._endpoint_backoff_until[url] = self._now() + cooldown
        self._last_error = detail

        if len(self.base_urls) == 1:
            self._set_global_cooldown(max(cooldown, self.failure_cooldown_sec), detail)

    def is_available(self) -> bool:
        with self._lock:
            if self._cooldown_remaining() > 0:
                self._available = False
                self._active_backend = "cooldown"
                return False

            for url in self._iter_urls():
                try:
                    models, _payload = fetch_tags(url, timeout=3)
                    self._set_active(url, models)
                    if len(self.base_urls) > 1 and self._active_backend != "primary":
                        logger.warning("LLM provider failover active: using %s endpoint (%s)", self._active_backend, url)
                    return True
                except requests.RequestException:
                    continue
            self._available = False
            self._models = []
            self._active_url = None
            self._active_backend = "none"
            logger.info("No reachable Ollama endpoints in OLLAMA_BASE_URLS; deterministic fallback active")
            return False

    def reset_availability(self) -> None:
        with self._lock:
            self._available = None
            self._models = []
            self._endpoint_models = {}
            self._endpoint_backoff_until = {}
            self._active_url = None
            self._active_backend = "none"
            self._cooldown_until = 0.0
            self._last_error = ""

    def model_status(self) -> dict[str, Any]:
        available = self.is_available()
        cooldown_remaining = self._cooldown_remaining()
        endpoint_backoff = {}
        now = self._now()
        for url in self.base_urls:
            remaining = max(0, int(self._endpoint_backoff_until.get(url, 0.0) - now))
            if remaining:
                try:
                    idx = self.base_urls.index(url)
                except ValueError:
                    idx = 0
                endpoint_backoff[endpoint_label(idx)] = remaining
        return {
            "ollama_available": available,
            "ollama_url": self._active_url or self.base_urls[0],
            "ollama_urls_configured": len(self.base_urls),
            "active_backend": self._active_backend,
            "requested_grader_model": self.requested_grader_model,
            "requested_generator_model": self.requested_generator_model,
            "grader_model": self.grader_model,
            "generator_model": self.generator_model,
            "loaded_models": self._models if available else [],
            "chat_endpoint": self._chat_endpoint,
            "failover_enabled": len(self.base_urls) > 1,
            "cooldown_active": cooldown_remaining > 0,
            "cooldown_seconds_remaining": cooldown_remaining,
            "endpoint_backoff_seconds": endpoint_backoff,
            "last_error": self._last_error if not available else "",
            "mode": "llm" if available else "deterministic",
        }

    @staticmethod
    def _model_prefix(model_name: str) -> str:
        return model_name.split(":", 1)[0].strip().lower()

    def _resolve_model_name(
        self,
        requested: str,
        models: list[str] | None = None,
    ) -> str:
        available_models = models or self._models
        if not available_models:
            return requested

        requested_lower = requested.lower().strip()

        for model in available_models:
            if model.lower() == requested_lower:
                return model

        aliases: dict[str, list[str]] = {
            "llama3.1:8b": [
                "llama3.1:8b",
                "llama3.1:8b-instruct",
                "llama3.1:8b-instruct-q4_k_m",
                "llama3.1",
            ],
            "command-r:7b": [
                "command-r:7b",
                "command-r7b:latest",
                "command-r7b",
                "command-r:latest",
                "command-r",
            ],
        }

        candidate_aliases = aliases.get(requested_lower, [requested_lower])
        installed_lower = {m.lower(): m for m in available_models}
        for alias in candidate_aliases:
            if alias in installed_lower:
                return installed_lower[alias]

        requested_prefix = self._model_prefix(requested_lower)
        for model in available_models:
            if self._model_prefix(model) == requested_prefix:
                return model

        return requested

    @staticmethod
    def _messages_to_prompt(messages: list[dict[str, str]]) -> str:
        prompt_parts: list[str] = []
        for msg in messages:
            role = msg.get("role", "user").upper()
            content = msg.get("content", "")
            prompt_parts.append(f"{role}:\n{content}")
        prompt_parts.append("ASSISTANT:")
        return "\n\n".join(prompt_parts)

    @staticmethod
    def _format_request_error(exc: requests.RequestException) -> str:
        if getattr(exc, "response", None) is not None:
            status = exc.response.status_code
            body = (exc.response.text or "")[:350]
            return f"{exc} (status={status}, body={body})"
        return str(exc)

    def _chat(
        self,
        requested_model: str,
        messages: list[dict[str, str]],
        format_json: bool = False,
        temperature: float = 0.0,
    ) -> str:
        if not self.is_available():
            raise requests.RequestException("No reachable Ollama endpoints")

        errors: list[str] = []
        for url in self._iter_urls():
            try:
                models = self._endpoint_models.get(url)
                if not models:
                    models, _ = fetch_tags(url, timeout=3)
                    self._endpoint_models[url] = models
                model = self._resolve_model_name(requested_model, models=models)

                payload: dict[str, Any] = {
                    "model": model,
                    "messages": messages,
                    "stream": False,
                    "options": {"temperature": temperature},
                }
                if format_json:
                    payload["format"] = "json"

                resp = requests.post(f"{url}/api/chat", json=payload, timeout=self.timeout)

                # Some Ollama versions do not expose /api/chat.
                if resp.status_code == 404:
                    generate_payload: dict[str, Any] = {
                        "model": model,
                        "prompt": self._messages_to_prompt(messages),
                        "stream": False,
                        "options": {"temperature": temperature},
                    }
                    if format_json:
                        generate_payload["format"] = "json"
                    resp = requests.post(
                        f"{url}/api/generate",
                        json=generate_payload,
                        timeout=self.timeout,
                    )
                    self._chat_endpoint = "/api/generate"
                    resp.raise_for_status()
                    self._set_active(url, models)
                    return str(resp.json().get("response", ""))

                self._chat_endpoint = "/api/chat"
                resp.raise_for_status()
                self._set_active(url, models)
                return resp.json()["message"]["content"]

            except requests.RequestException as exc:
                detail = self._format_request_error(exc)
                errors.append(f"{url}: {detail}")
                self._register_failure(url, exc)
                continue

        self._available = False
        if not self._cooldown_remaining():
            self._set_global_cooldown(self.failure_cooldown_sec, "all endpoints failed")
        raise requests.RequestException("All Ollama endpoints failed. " + " | ".join(errors))

    def grade_document(self, query: str, document_text: str) -> dict[str, str]:
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a legal document relevance grader. You will receive a "
                    "user query and a document excerpt from an M&A legal corpus. "
                    "Determine whether the document contains information relevant to "
                    "answering the query. Output ONLY valid JSON: "
                    '{"score": "yes"} if relevant, or {"score": "no"} if not. '
                    "No explanation, no other text."
                ),
            },
            {
                "role": "user",
                "content": f"Query: {query}\n\nDocument:\n{document_text[:3000]}",
            },
        ]
        try:
            raw = self._chat(self.requested_grader_model, messages, format_json=True, temperature=0.0)
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.warning("Grading returned non-JSON for query '%s': %s", query[:80], exc)
            return {"score": "yes"}
        except requests.RequestException as exc:
            logger.warning(
                "Grading request failed for query '%s': %s; switching to deterministic",
                query[:80],
                self._format_request_error(exc),
            )
            self._available = False
            return {"score": "fallback"}

    def rewrite_query(self, original_query: str, failed_context: str = "") -> str:
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a legal search query optimizer. The user's original "
                    "search query did not return relevant results from an M&A legal "
                    "document corpus. Rewrite the query using alternative legal "
                    "terminology, synonyms, and related M&A concepts to improve "
                    "retrieval. Output ONLY the rewritten query text."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Original query: {original_query}\n\n"
                    f"Context (not relevant): {failed_context[:500] if failed_context else 'None'}\n\n"
                    "Rewritten query:"
                ),
            },
        ]
        try:
            rewritten = self._chat(self.requested_grader_model, messages, temperature=0.3)
            return rewritten.strip().strip('"').strip()
        except requests.RequestException as exc:
            logger.warning("Query rewrite failed: %s", self._format_request_error(exc))
            return f"{original_query} merger acquisition agreement legal provisions"

    def generate_analysis(
        self,
        query: str,
        documents: list[dict[str, Any]],
        contract_text: str = "",
    ) -> dict[str, Any]:
        doc_context = ""
        for i, doc in enumerate(documents):
            source = f"[Source: {doc.get('title', 'Unknown')}, Page {doc.get('page', 'N/A')}]"
            doc_context += f"\n\nDOCUMENT {i + 1} {source}:\n{doc.get('text', '')[:2000]}"

        contract_section = ""
        if contract_text:
            contract_section = f"\n\nUSER'S CONTRACT (for analysis):\n{contract_text[:4000]}"

        messages = [
            {
                "role": "system",
                "content": (
                    "You are an expert M&A legal analyst performing Corrective RAG "
                    "analysis. You have been given: (1) a user query, (2) verified "
                    "relevant documents from an M&A legal corpus, and optionally "
                    "(3) the user's contract text for issue spotting.\n\n"
                    "Your task:\n"
                    "- Synthesize the retrieved documents to answer the query.\n"
                    "- For every factual claim, include an inline citation: "
                    "[Source: filename, Page N].\n"
                    "- If analyzing a contract, identify missing or weak provisions "
                    "and suggest corrective language.\n"
                    "- Be precise, cite specific clause language, use professional "
                    "legal drafting tone.\n\n"
                    "Output valid JSON with this structure:\n"
                    "{\n"
                    '  "analysis": "Your detailed analysis with inline citations",\n'
                    '  "key_findings": ["finding 1", "finding 2"],\n'
                    '  "corrective_suggestions": ["suggestion 1", "suggestion 2"],\n'
                    '  "risk_level": "low|medium|high",\n'
                    '  "citations": [{"source": "filename", "page": "N", "excerpt": "relevant text"}]\n'
                    "}"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Query: {query}{contract_section}\n\n"
                    f"VERIFIED RELEVANT DOCUMENTS:{doc_context}"
                ),
            },
        ]
        try:
            raw = self._chat(self.requested_generator_model, messages, format_json=True, temperature=0.2)
            return json.loads(raw)
        except json.JSONDecodeError:
            return {
                "analysis": raw if "raw" in dir() else "Generation produced non-JSON output",
                "key_findings": [],
                "corrective_suggestions": [],
                "risk_level": "unknown",
                "citations": [],
            }
        except requests.RequestException as exc:
            logger.error("Generation failed: %s", self._format_request_error(exc))
            return {
                "analysis": f"LLM generation unavailable: {exc}",
                "key_findings": [],
                "corrective_suggestions": [],
                "risk_level": "unknown",
                "citations": [],
            }

    def enhance_issue(
        self,
        issue_title: str,
        issue_description: str,
        corpus_excerpts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        excerpts_text = ""
        for i, doc in enumerate(corpus_excerpts):
            source = f"[Source: {doc.get('title', 'Unknown')}, Page {doc.get('page', 'N/A')}]"
            excerpts_text += f"\n{i + 1}. {source}: {doc.get('text', '')[:800]}"

        messages = [
            {
                "role": "system",
                "content": (
                    "You are an M&A legal analyst. Given a contract issue and "
                    "supporting corpus excerpts, provide a concise enhanced analysis. "
                    "Output valid JSON:\n"
                    "{\n"
                    '  "enhanced_analysis": "2-3 sentence analysis with citations",\n'
                    '  "recommended_language": "Suggested corrective clause text",\n'
                    '  "precedent_basis": "Brief note on market practice"\n'
                    "}"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Issue: {issue_title}\n"
                    f"Description: {issue_description}\n\n"
                    f"Supporting corpus excerpts:{excerpts_text}"
                ),
            },
        ]
        try:
            raw = self._chat(self.requested_generator_model, messages, format_json=True, temperature=0.2)
            return json.loads(raw)
        except (json.JSONDecodeError, requests.RequestException) as exc:
            logger.warning("Issue enhancement failed for '%s': %s", issue_title, exc)
            return {}
