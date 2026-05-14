"""Tests for the multi-provider LLM abstraction (Brief 2.1)."""

from __future__ import annotations

import importlib
import json
import os
import sys
import types
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reload_provider():
    """Reload llm_provider after env-var mutation."""
    import scripts.llm_provider as mod
    mod.reset_llm()
    return mod


# ---------------------------------------------------------------------------
# get_llm() factory
# ---------------------------------------------------------------------------

class TestGetLlmFactory:
    def test_defaults_to_ollama_provider(self, monkeypatch):
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        mod = _reload_provider()
        from scripts.llm_provider import OllamaProvider
        assert isinstance(mod.get_llm(), OllamaProvider)

    def test_vertex_provider_selected(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "vertex")
        monkeypatch.setenv("GCP_PROJECT", "test-project")
        monkeypatch.setenv("COHERE_API_KEY", "co_test")
        mod = _reload_provider()
        from scripts.llm_provider import VertexProvider
        assert isinstance(mod.get_llm(), VertexProvider)

    def test_singleton_returns_same_instance(self, monkeypatch):
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        mod = _reload_provider()
        assert mod.get_llm() is mod.get_llm()

    def test_reset_llm_clears_singleton(self, monkeypatch):
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        mod = _reload_provider()
        first = mod.get_llm()
        mod.reset_llm()
        second = mod.get_llm()
        assert first is not second


# ---------------------------------------------------------------------------
# OllamaProvider — existing public interface preserved
# ---------------------------------------------------------------------------

class TestOllamaProviderInterface:
    def setup_method(self):
        from scripts.llm_provider import OllamaProvider
        with patch("scripts.llm_provider.parse_ollama_base_urls", return_value=["http://localhost:11434"]):
            self.provider = OllamaProvider()

    def test_has_required_methods(self):
        for method in ("is_available", "grade_document", "rewrite_query", "generate_analysis",
                       "enhance_issue", "model_status"):
            assert callable(getattr(self.provider, method))

    def test_grade_document_fallback_on_no_server(self):
        with patch.object(self.provider, "is_available", return_value=False):
            result = self.provider.grade_document("test query", "test document text")
        assert result.get("score") in ("yes", "no", "fallback")

    def test_rewrite_query_fallback_on_no_server(self):
        with patch.object(self.provider, "is_available", return_value=False):
            result = self.provider.rewrite_query("indemnification cap")
        assert "indemnification cap" in result or "merger" in result

    def test_generate_analysis_fallback_on_no_server(self):
        with patch.object(self.provider, "is_available", return_value=False):
            result = self.provider.generate_analysis("test query", [])
        assert "analysis" in result

    def test_model_status_keys(self):
        with patch.object(self.provider, "is_available", return_value=False):
            status = self.provider.model_status()
        assert "mode" in status
        assert "grader_model" in status
        assert "generator_model" in status


# ---------------------------------------------------------------------------
# VertexProvider — unit tests with mocked SDKs
# ---------------------------------------------------------------------------

class TestVertexProviderInterface:
    def _make_provider(self, monkeypatch):
        monkeypatch.setenv("GCP_PROJECT", "test-project")
        monkeypatch.setenv("COHERE_API_KEY", "co_test")
        monkeypatch.setenv("VERTEX_LOCATION", "us-central1")
        from scripts.llm_provider import VertexProvider
        return VertexProvider()

    def test_has_required_methods(self, monkeypatch):
        p = self._make_provider(monkeypatch)
        for method in ("is_available", "grade_document", "rewrite_query", "generate_analysis",
                       "enhance_issue", "model_status", "embed", "rerank", "anonymize", "rehydrate"):
            assert callable(getattr(p, method))

    def test_model_status_keys(self, monkeypatch):
        p = self._make_provider(monkeypatch)
        with patch.object(p, "is_available", return_value=False):
            status = p.model_status()
        assert status["provider"] == "vertex"
        assert "generator_model" in status
        assert "grader_model" in status
        assert "embed_model" in status

    def test_grade_document_returns_valid_score(self, monkeypatch):
        p = self._make_provider(monkeypatch)
        with patch.object(p, "_generate_json", return_value='{"score": "yes"}'):
            result = p.grade_document("indemnification cap", "Some clause text")
        assert result["score"] == "yes"

    def test_grade_document_bad_json_defaults_to_yes(self, monkeypatch):
        p = self._make_provider(monkeypatch)
        with patch.object(p, "_generate_json", return_value="not json"):
            result = p.grade_document("test", "text")
        assert result["score"] == "yes"

    def test_grade_document_exception_returns_fallback(self, monkeypatch):
        p = self._make_provider(monkeypatch)
        with patch.object(p, "_generate_json", side_effect=RuntimeError("API error")):
            result = p.grade_document("test", "text")
        assert result["score"] == "fallback"

    def test_rewrite_query_returns_string(self, monkeypatch):
        p = self._make_provider(monkeypatch)
        with patch.object(p, "_generate", return_value="MAC clause material adverse change"):
            result = p.rewrite_query("MAC definition")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_rewrite_query_fallback_on_exception(self, monkeypatch):
        p = self._make_provider(monkeypatch)
        with patch.object(p, "_generate", side_effect=RuntimeError("fail")):
            result = p.rewrite_query("test query")
        assert "test query" in result

    def test_generate_analysis_parses_json(self, monkeypatch):
        p = self._make_provider(monkeypatch)
        mock_response = json.dumps({
            "analysis": "The clause is standard.",
            "key_findings": ["Finding 1"],
            "corrective_suggestions": [],
            "risk_level": "low",
            "citations": [],
        })
        with patch.object(p, "_generate_json", return_value=mock_response):
            result = p.generate_analysis("test", [{"title": "doc", "page": 1, "text": "text"}])
        assert result["risk_level"] == "low"
        assert result["analysis"] == "The clause is standard."

    def test_generate_analysis_error_returns_safe_dict(self, monkeypatch):
        p = self._make_provider(monkeypatch)
        with patch.object(p, "_generate_json", side_effect=RuntimeError("API down")):
            result = p.generate_analysis("test", [])
        assert "analysis" in result
        assert result["risk_level"] == "unknown"

    def test_enhance_issue_returns_dict(self, monkeypatch):
        p = self._make_provider(monkeypatch)
        mock_response = json.dumps({
            "enhanced_analysis": "Standard market practice.",
            "recommended_language": "Party A shall indemnify...",
            "precedent_basis": "Common in buy-side NDAs.",
        })
        with patch.object(p, "_generate_json", return_value=mock_response):
            result = p.enhance_issue("Indemnification Cap", "Cap is too low", [])
        assert "enhanced_analysis" in result

    def test_enhance_issue_returns_empty_on_exception(self, monkeypatch):
        p = self._make_provider(monkeypatch)
        with patch.object(p, "_generate_json", side_effect=RuntimeError("fail")):
            result = p.enhance_issue("title", "desc", [])
        assert result == {}

    def test_anonymize_updates_map(self, monkeypatch):
        p = self._make_provider(monkeypatch)
        mock_response = json.dumps({
            "anonymized_text": "Agreement between [PARTY_A] and [COMPANY_1].",
            "updated_map": {"[PARTY_A]": "Acme Corp", "[COMPANY_1]": "Target Inc"},
        })
        with patch.object(p, "_generate_json", return_value=mock_response):
            anon_text, updated_map = p.anonymize("Agreement between Acme Corp and Target Inc.", {})
        assert "[PARTY_A]" in anon_text
        assert updated_map["[PARTY_A]"] == "Acme Corp"

    def test_anonymize_passthrough_on_exception(self, monkeypatch):
        p = self._make_provider(monkeypatch)
        original = "Acme Corp agreed to pay $1M."
        with patch.object(p, "_generate_json", side_effect=RuntimeError("fail")):
            anon_text, updated_map = p.anonymize(original, {})
        assert anon_text == original

    def test_rehydrate_replaces_placeholders(self, monkeypatch):
        p = self._make_provider(monkeypatch)
        session_map = {"[PARTY_A]": "Acme Corp", "[AMOUNT_1]": "$1,000,000"}
        result = p.rehydrate("[PARTY_A] agreed to pay [AMOUNT_1].", session_map)
        assert result == "Acme Corp agreed to pay $1,000,000."

    def test_embed_calls_cohere(self, monkeypatch):
        p = self._make_provider(monkeypatch)
        mock_co = MagicMock()
        mock_co.embed.return_value.embeddings.float = [[0.1, 0.2], [0.3, 0.4]]
        with patch.object(p, "_get_cohere", return_value=mock_co):
            result = p.embed(["text one", "text two"])
        assert len(result) == 2
        mock_co.embed.assert_called_once()

    def test_rerank_calls_cohere(self, monkeypatch):
        p = self._make_provider(monkeypatch)
        mock_result = MagicMock()
        mock_result.index = 0
        mock_result.relevance_score = 0.95
        mock_co = MagicMock()
        mock_co.rerank.return_value.results = [mock_result]
        with patch.object(p, "_get_cohere", return_value=mock_co):
            result = p.rerank("query", ["doc one"], top_n=1)
        assert result[0]["relevance_score"] == 0.95

    def test_is_available_false_when_clients_fail(self, monkeypatch):
        p = self._make_provider(monkeypatch)
        with patch.object(p, "_get_genai", side_effect=RuntimeError("no vertex")):
            assert not p.is_available()
        assert p._last_error != ""

    def test_missing_cohere_key_raises(self, monkeypatch):
        monkeypatch.setenv("GCP_PROJECT", "test-project")
        monkeypatch.delenv("COHERE_API_KEY", raising=False)
        from scripts.llm_provider import VertexProvider
        p = VertexProvider()
        with pytest.raises(RuntimeError, match="COHERE_API_KEY"):
            p._resolve_cohere_key()
