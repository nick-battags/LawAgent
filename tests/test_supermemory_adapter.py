"""Contract tests for the pinned Supermemory v3.56.0 Session-source adapter."""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from scripts.supermemory_adapter import (
    DEFAULT_MAX_RETRIES,
    DEFAULT_TIMEOUT_SECONDS,
    SupermemoryAdapter,
    SupermemoryRejectedError,
    SupermemoryUnavailableError,
)


class DocumentsFake:
    def __init__(self) -> None:
        self.memories: list[object] = []
        self.list_error: Exception | None = None
        self.delete_error: Exception | None = None
        self.clear_error: Exception | None = None
        self.list_calls: list[dict] = []
        self.deleted: list[str] = []
        self.bulk_deleted: list[dict] = []

    def list(self, **kwargs):
        self.list_calls.append(kwargs)
        if self.list_error:
            raise self.list_error
        return SimpleNamespace(
            memories=self.memories,
            pagination=SimpleNamespace(total_pages=1),
        )

    def delete(self, document_id: str):
        if self.delete_error:
            raise self.delete_error
        self.deleted.append(document_id)

    def delete_bulk(self, **kwargs):
        if self.clear_error:
            raise self.clear_error
        self.bulk_deleted.append(kwargs)
        return SimpleNamespace(success=True)


class SearchFake:
    def __init__(self) -> None:
        self.results: list[object] = []
        self.error: Exception | None = None
        self.calls: list[dict] = []

    def execute(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return SimpleNamespace(results=self.results)


class ClientFake:
    """Strict shape: intentionally has no containers resource or memories.forget."""

    def __init__(self) -> None:
        self.documents = DocumentsFake()
        self.search = SearchFake()
        self.add_response = SimpleNamespace(id="doc-1", status="queued")
        self.add_error: Exception | None = None
        self.add_calls: list[dict] = []

    def add(self, **kwargs):
        self.add_calls.append(kwargs)
        if self.add_error:
            raise self.add_error
        return self.add_response


def context_document(
    document_id: str,
    status: str = "done",
    *,
    source: str = "playbook.pdf",
    char_count: object = 123,
    kind: str = "context",
):
    return SimpleNamespace(
        id=document_id,
        status=status,
        title=None,
        metadata={
            "kind": kind,
            "source": source,
            "char_count": char_count,
        },
    )


def test_top_level_add_surfaces_queued_and_done_statuses():
    client = ClientFake()
    adapter = SupermemoryAdapter(client=client)

    queued = adapter.add_context(
        "session-a",
        "safe content",
        {"kind": "context", "anonymized": True},
    )
    client.add_response = SimpleNamespace(id="doc-2", status="done")
    ready = adapter.add_context(
        "session-a",
        "safe content",
        {"kind": "context", "anonymized": True},
    )

    assert queued == {"id": "doc-1", "processing_status": "processing"}
    assert ready == {"id": "doc-2", "processing_status": "ready"}
    assert client.add_calls[0]["container_tag"] == "session-a"
    assert client.add_calls[0]["metadata"]["kind"] == "context"


def test_add_without_id_is_rejected_and_failed_status_is_surfaced():
    client = ClientFake()
    adapter = SupermemoryAdapter(client=client)

    client.add_response = SimpleNamespace(id="", status="queued")
    with pytest.raises(SupermemoryRejectedError):
        adapter.add_context("session-a", "safe", {"anonymized": True})

    client.add_response = SimpleNamespace(id="doc-failed", status="failed")
    assert adapter.add_context(
        "session-a", "safe", {"anonymized": True}
    ) == {"id": "doc-failed", "processing_status": "failed"}


def test_client_construction_failure_is_contained():
    def fail_factory():
        raise RuntimeError("secret provider detail")

    adapter = SupermemoryAdapter(client_factory=fail_factory)
    with pytest.raises(SupermemoryUnavailableError) as exc_info:
        adapter.add_context("session-a", "safe", {"anonymized": True})

    assert "secret provider detail" not in str(exc_info.value)


def test_add_search_list_delete_and_clear_exceptions_are_normalized():
    client = ClientFake()
    adapter = SupermemoryAdapter(client=client)

    client.add_error = RuntimeError("raw add error")
    with pytest.raises(SupermemoryUnavailableError):
        adapter.add_context("session-a", "safe", {"anonymized": True})
    client.add_error = None

    client.search.error = RuntimeError("raw search error")
    with pytest.raises(SupermemoryUnavailableError):
        adapter.recall_context("session-a", "query")
    client.search.error = None

    client.documents.list_error = RuntimeError("raw list error")
    with pytest.raises(SupermemoryUnavailableError):
        adapter.list_context("session-a")
    client.documents.list_error = None

    client.documents.memories = [context_document("owned")]
    client.documents.delete_error = RuntimeError("raw delete error")
    with pytest.raises(SupermemoryUnavailableError):
        adapter.delete_context("session-a", "owned")
    client.documents.delete_error = None

    client.documents.clear_error = RuntimeError("raw clear error")
    with pytest.raises(SupermemoryUnavailableError):
        adapter.clear_session("session-a")


def test_search_joins_chunks_when_full_content_is_none():
    client = ClientFake()
    client.search.results = [
        SimpleNamespace(
            chunks=[
                SimpleNamespace(content="First chunk"),
                SimpleNamespace(content=""),
                SimpleNamespace(content="Second chunk"),
            ],
            content=None,
            metadata={"kind": "context", "source": "source.docx"},
            score=0.91,
            document_id="doc-1",
        )
    ]

    results = SupermemoryAdapter(client=client).recall_context(
        "session-a", "indemnification"
    )

    assert results[0]["content"] == "First chunk\nSecond chunk"
    assert results[0]["document_id"] == "doc-1"
    assert client.search.calls[0]["filters"] == {
        "AND": [{"key": "kind", "value": "context"}]
    }


def test_search_discards_empty_chunks_and_content():
    client = ClientFake()
    client.search.results = [
        SimpleNamespace(
            chunks=[SimpleNamespace(content="  ")],
            content=None,
            metadata={"kind": "context"},
            score=0.5,
            document_id="empty",
        )
    ]

    assert SupermemoryAdapter(client=client).recall_context(
        "session-a", "query"
    ) == []


def test_list_reads_memories_and_normalizes_all_provider_statuses():
    client = ClientFake()
    client.documents.memories = [
        context_document("queued", "queued", char_count="12"),
        context_document("ready", "done"),
        context_document("failed", "failed"),
        context_document("ignored", "done", kind="chat_exchange"),
    ]

    sources = SupermemoryAdapter(client=client).list_context("session-a")

    assert [source["id"] for source in sources] == ["queued", "ready", "failed"]
    assert [source["processing_status"] for source in sources] == [
        "processing",
        "ready",
        "failed",
    ]
    assert sources[0]["char_count"] == 12
    assert client.documents.list_calls == [
        {"container_tags": ["session-a"], "limit": 100, "page": 1}
    ]


def test_delete_verifies_ownership_then_uses_documents_delete():
    client = ClientFake()
    client.documents.memories = [context_document("owned")]
    adapter = SupermemoryAdapter(client=client)

    assert adapter.delete_context("session-a", "owned") is True
    assert client.documents.deleted == ["owned"]


def test_delete_refuses_document_not_in_session():
    client = ClientFake()
    client.documents.memories = [context_document("different")]
    adapter = SupermemoryAdapter(client=client)

    assert adapter.delete_context("session-a", "cross-session") is False
    assert client.documents.deleted == []


def test_clear_uses_documents_delete_bulk_by_container():
    client = ClientFake()

    assert SupermemoryAdapter(client=client).clear_session("session-a") is True
    assert client.documents.bulk_deleted == [{"container_tags": ["session-a"]}]
    assert not hasattr(client, "containers")
    assert not hasattr(client, "memories")


def test_configured_timeout_and_retries_reach_client_constructor(
    monkeypatch,
):
    captured: dict = {}

    def constructor(**kwargs):
        captured.update(kwargs)
        return ClientFake()

    monkeypatch.setenv("SUPERMEMORY_API_KEY", "sm_test")
    monkeypatch.setenv("SUPERMEMORY_TIMEOUT_SECONDS", "2.5")
    monkeypatch.setenv("SUPERMEMORY_MAX_RETRIES", "3")
    monkeypatch.setitem(
        sys.modules,
        "supermemory",
        SimpleNamespace(Supermemory=constructor),
    )

    SupermemoryAdapter().list_context("session-a")

    assert captured["api_key"] == "sm_test"
    assert captured["timeout"] == 2.5
    assert captured["max_retries"] == 3


def test_malformed_timeout_and_retries_use_safe_defaults(monkeypatch):
    monkeypatch.setenv("SUPERMEMORY_TIMEOUT_SECONDS", "not-a-number")
    monkeypatch.setenv("SUPERMEMORY_MAX_RETRIES", "-2")

    adapter = SupermemoryAdapter(client=ClientFake())

    assert adapter.timeout_seconds == DEFAULT_TIMEOUT_SECONDS
    assert adapter.max_retries == DEFAULT_MAX_RETRIES
