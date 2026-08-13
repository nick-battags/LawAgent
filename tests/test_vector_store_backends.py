"""Shared-corpus backend selection tests."""

from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.fixture
def vector_store_module():
    import scripts.vector_store as vector_store

    vector_store._demo_store = None
    vector_store._store = None
    yield vector_store
    vector_store._demo_store = None
    vector_store._store = None


def test_supermemory_backend_is_explicitly_rejected(
    monkeypatch,
    vector_store_module,
):
    monkeypatch.setenv("VECTOR_BACKEND", "supermemory")

    with pytest.raises(RuntimeError, match="use VECTOR_BACKEND=pgvector"):
        vector_store_module.get_demo_vector_store()


def test_pgvector_backend_still_uses_pgvector_store(
    monkeypatch,
    vector_store_module,
):
    marker = object()
    monkeypatch.setenv("VECTOR_BACKEND", "pgvector")

    with patch(
        "scripts.pgvector_store.PgvectorCorpusStore",
        return_value=marker,
    ):
        assert vector_store_module.get_demo_vector_store() is marker


def test_local_backend_still_uses_local_vector_store(
    monkeypatch,
    vector_store_module,
):
    marker = object()
    monkeypatch.setenv("VECTOR_BACKEND", "chromadb")
    monkeypatch.setattr(
        vector_store_module,
        "get_vector_store",
        lambda: marker,
    )

    assert vector_store_module.get_demo_vector_store() is marker
