"""Ollama LLM provider for the 2-model CRAG pipeline.

Llama 3.1 8B — grader/gatekeeper (strict JSON relevance scoring, query rewriting).
Command-R 7B — generator (synthesis with inline citations, contract analysis).
Designed for local Ollama deployment with graceful deterministic fallback.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import requests

logger = logging.getLogger(__name__)

_provider: OllamaProvider | None = None


def get_llm() -> OllamaProvider:
    global _provider
    if _provider is None:
        _provider = OllamaProvider()
    return _provider


class OllamaProvider:
    def __init__(self) -> None:
        self.base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
        self.grader_model = os.environ.get("GRADER_MODEL", "llama3.1:8b")
        self.generator_model = os.environ.get("GENERATOR_MODEL", "command-r:7b")
        self.timeout = int(os.environ.get("LLM_TIMEOUT", "120"))
        self._available: bool | None = None
        self._models: list[str] = []

    def is_available(self) -> bool:
        if self._available is None:
            try:
                r = requests.get(f"{self.base_url}/api/tags", timeout=3)
                self._available = r.ok
                if self._available:
                    self._models = [m["name"] for m in r.json().get("models", [])]
                    logger.info("Ollama online. Models: %s", ", ".join(self._models))
            except Exception:
                self._available = False
                logger.info(
                    "Ollama not reachable at %s — deterministic fallback active",
                    self.base_url,
                )
        return self._available

    def reset_availability(self) -> None:
        self._available = None
        self._models = []

    def model_status(self) -> dict[str, Any]:
        available = self.is_available()
        return {
            "ollama_available": available,
            "ollama_url": self.base_url,
            "grader_model": self.grader_model,
            "generator_model": self.generator_model,
            "loaded_models": self._models if available else [],
            "mode": "llm" if available else "deterministic",
        }

    def _chat(
        self,
        model: str,
        messages: list[dict[str, str]],
        format_json: bool = False,
        temperature: float = 0.0,
    ) -> str:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": temperature},
        }
        if format_json:
            payload["format"] = "json"
        resp = requests.post(
            f"{self.base_url}/api/chat",
            json=payload,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()["message"]["content"]

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
            raw = self._chat(self.grader_model, messages, format_json=True, temperature=0.0)
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.warning("Grading returned non-JSON for query '%s': %s", query[:80], exc)
            return {"score": "yes"}
        except requests.RequestException as exc:
            logger.warning("Grading request failed for query '%s': %s — switching to deterministic", query[:80], exc)
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
            rewritten = self._chat(self.grader_model, messages, temperature=0.3)
            return rewritten.strip().strip('"').strip()
        except requests.RequestException as exc:
            logger.warning("Query rewrite failed: %s", exc)
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
                    '  "citations": [{"source": "filename", "page": "N", '
                    '"excerpt": "relevant text"}]\n'
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
            raw = self._chat(
                self.generator_model, messages, format_json=True, temperature=0.2,
            )
            result = json.loads(raw)
            return result
        except json.JSONDecodeError:
            return {
                "analysis": raw if "raw" in dir() else "Generation produced non-JSON output",
                "key_findings": [],
                "corrective_suggestions": [],
                "risk_level": "unknown",
                "citations": [],
            }
        except requests.RequestException as exc:
            logger.error("Generation failed: %s", exc)
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
            raw = self._chat(
                self.generator_model, messages, format_json=True, temperature=0.2,
            )
            return json.loads(raw)
        except (json.JSONDecodeError, requests.RequestException) as exc:
            logger.warning("Issue enhancement failed for '%s': %s", issue_title, exc)
            return {}
