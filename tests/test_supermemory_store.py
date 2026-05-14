"""Tests for SupermemoryCorpusStore (Brief 2.2)."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest


class TestSupermemoryCorpusStore:
    def _make_store(self, monkeypatch):
        monkeypatch.setenv("SUPERMEMORY_API_KEY", "sm_test")
        monkeypatch.setenv("SUPERMEMORY_CORPUS_TAG", "test-corpus")
        from scripts.supermemory_store import SupermemoryCorpusStore
        return SupermemoryCorpusStore()

    def test_is_available_true_when_client_initializes(self, monkeypatch):
        store = self._make_store(monkeypatch)
        mock_client = MagicMock()
        with patch.object(store, "_get_client", return_value=mock_client):
            assert store.is_available()

    def test_is_available_false_without_api_key(self, monkeypatch):
        monkeypatch.delenv("SUPERMEMORY_API_KEY", raising=False)
        from scripts.supermemory_store import SupermemoryCorpusStore
        store = SupermemoryCorpusStore()
        assert not store.is_available()

    def test_query_returns_normalized_results(self, monkeypatch):
        store = self._make_store(monkeypatch)
        mock_result = MagicMock()
        mock_result.content = "Indemnification clause text."
        mock_result.metadata = {"title": "NDA v1", "category": "indemnification", "page": "3"}
        mock_result.score = 0.85

        mock_client = MagicMock()
        mock_client.search.execute.return_value.results = [mock_result]

        with patch.object(store, "_get_client", return_value=mock_client):
            results = store.query("indemnification cap", top_k=5)

        assert len(results) == 1
        r = results[0]
        assert r["text"] == "Indemnification clause text."
        assert r["title"] == "NDA v1"
        assert r["category"] == "indemnification"
        assert r["page"] == "3"
        assert r["score"] == 8  # int(0.85 * 10)
        assert r["distance"] == pytest.approx(0.15, abs=0.01)

    def test_query_returns_empty_on_exception(self, monkeypatch):
        store = self._make_store(monkeypatch)
        with patch.object(store, "_get_client", side_effect=RuntimeError("API error")):
            results = store.query("test query")
        assert results == []

    def test_query_passes_category_filter(self, monkeypatch):
        store = self._make_store(monkeypatch)
        mock_client = MagicMock()
        mock_client.search.execute.return_value.results = []
        with patch.object(store, "_get_client", return_value=mock_client):
            store.query("test", category="indemnification")
        call_kwargs = mock_client.search.execute.call_args[1]
        filters = call_kwargs.get("filters", {})
        conditions = filters.get("AND", [])
        assert any(c.get("key") == "category" for c in conditions)

    def test_add_returns_memory_id(self, monkeypatch):
        store = self._make_store(monkeypatch)
        mock_client = MagicMock()
        mock_client.memories.add.return_value.id = "mem-abc123"
        with patch.object(store, "_get_client", return_value=mock_client):
            mem_id = store.add("Some clause text.", metadata={"title": "Test Doc"})
        assert mem_id == "mem-abc123"

    def test_add_returns_none_on_exception(self, monkeypatch):
        store = self._make_store(monkeypatch)
        with patch.object(store, "_get_client", side_effect=RuntimeError("fail")):
            mem_id = store.add("text")
        assert mem_id is None

    def test_normalize_result_handles_missing_fields(self, monkeypatch):
        from scripts.supermemory_store import SupermemoryCorpusStore
        mock_result = MagicMock()
        mock_result.content = "text"
        mock_result.metadata = {}
        mock_result.score = None
        result = SupermemoryCorpusStore._normalize_result(mock_result)
        assert result["text"] == "text"
        assert result["score"] >= 1

    def test_status_returns_dict(self, monkeypatch):
        store = self._make_store(monkeypatch)
        with patch.object(store, "is_available", return_value=True):
            status = store.status()
        assert status["backend"] == "supermemory"
        assert status["corpus_tag"] == "test-corpus"


class TestGetDemoVectorStore:
    def test_returns_supermemory_store_when_backend_env_set(self, monkeypatch):
        monkeypatch.setenv("VECTOR_BACKEND", "supermemory")
        monkeypatch.setenv("SUPERMEMORY_API_KEY", "sm_test")
        import scripts.vector_store as vs
        vs._demo_store = None  # reset singleton
        from scripts.supermemory_store import SupermemoryCorpusStore
        store = vs.get_demo_vector_store()
        assert isinstance(store, SupermemoryCorpusStore)
        vs._demo_store = None  # cleanup

    def test_returns_vector_store_for_other_backends(self, monkeypatch):
        monkeypatch.setenv("VECTOR_BACKEND", "chromadb")
        import scripts.vector_store as vs
        vs._demo_store = None
        with patch("scripts.vector_store.VectorStore.__init__", return_value=None):
            # Patch to avoid ChromaDB init
            vs._store = MagicMock()
            store = vs.get_demo_vector_store()
        assert store is vs._store
        vs._demo_store = None
        vs._store = None
