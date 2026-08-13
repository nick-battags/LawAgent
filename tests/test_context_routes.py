"""Route, cache, retrieval, and cleanup tests for Session sources."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("WARMUP_DISABLED", "true")

import app as app_module


class RouteMemory:
    def __init__(self) -> None:
        self.sources: list[dict] = []
        self.recalled: list[dict] = []
        self.deleted_result = True
        self.clear_result = True
        self.deleted_ids: list[str] = []

    def list_context(self):
        return self.sources

    def recall_context(self, query, limit=4):
        return self.recalled

    def delete_context(self, document_id):
        self.deleted_ids.append(document_id)
        return self.deleted_result

    def clear(self):
        return self.clear_result


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(app_module, "DEMO_MODE", False)
    monkeypatch.setattr(app_module, "HUB_ENABLED", True)
    monkeypatch.setattr(app_module, "ADMIN_PIN", "")
    app_module._SESSION_CONTEXT_CACHE.clear()
    app_module.app.config.update(
        TESTING=True,
        SECRET_KEY="context-route-test-key",
    )
    with app_module.app.test_client() as test_client:
        yield test_client
    app_module._SESSION_CONTEXT_CACHE.clear()


@pytest.mark.parametrize(
    ("processing_status", "expected_code"),
    [("processing", 202), ("ready", 200)],
)
def test_attach_queued_and_ready_status_codes(
    client,
    monkeypatch,
    processing_status,
    expected_code,
):
    monkeypatch.setattr(
        "scripts.context_loader.attach_context",
        lambda *_args, **_kwargs: {
            "status": "ok",
            "id": "doc-1",
            "memory_id": "doc-1",
            "processing_status": processing_status,
        },
    )

    response = client.post(
        "/api/v2/context/attach?session_id=session-a",
        data={"content": "Public fictional source."},
    )

    assert response.status_code == expected_code
    assert response.get_json()["processing_status"] == processing_status
    assert app_module._session_might_have_context("session-a") is True


@pytest.mark.parametrize(
    ("error_code", "expected_code"),
    [
        ("invalid_source", 400),
        ("provider_rejected", 502),
        ("provider_unavailable", 503),
    ],
)
def test_attach_failure_types_are_truthful(
    client,
    monkeypatch,
    error_code,
    expected_code,
):
    monkeypatch.setattr(
        "scripts.context_loader.attach_context",
        lambda *_args, **_kwargs: {
            "status": "error",
            "error_code": error_code,
            "error": "Stable public message",
        },
    )

    response = client.post(
        "/api/v2/context/attach?session_id=session-a",
        data={"content": "Public fictional source."},
    )

    assert response.status_code == expected_code
    assert "session-a" not in app_module._SESSION_CONTEXT_CACHE


def test_list_includes_processing_ready_and_failed_sources(
    client,
    monkeypatch,
):
    memory = RouteMemory()
    memory.sources = [
        {
            "id": "queued",
            "filename": "queued.pdf",
            "char_count": 10,
            "processing_status": "processing",
        },
        {
            "id": "ready",
            "filename": "ready.docx",
            "char_count": 20,
            "processing_status": "ready",
        },
        {
            "id": "failed",
            "filename": "failed.pdf",
            "char_count": 30,
            "processing_status": "failed",
        },
    ]
    monkeypatch.setattr(
        "scripts.session_memory.get_session_memory",
        lambda _session_id: memory,
    )

    response = client.get("/api/v2/context/list?session_id=session-a")

    assert response.status_code == 200
    assert response.get_json()["sources"] == memory.sources
    assert app_module._session_might_have_context("session-a") is True


def test_list_provider_error_is_visible_and_does_not_poison_cache(
    client,
    monkeypatch,
):
    class BrokenMemory:
        def list_context(self):
            raise RuntimeError("raw provider secret")

    app_module._mark_session_context_state("session-a", True)
    monkeypatch.setattr(
        "scripts.session_memory.get_session_memory",
        lambda _session_id: BrokenMemory(),
    )

    response = client.get("/api/v2/context/list?session_id=session-a")

    assert response.status_code == 503
    assert b"raw provider secret" not in response.data
    assert app_module._session_might_have_context("session-a") is True


def test_empty_successful_list_authoritatively_marks_session_empty(
    client,
    monkeypatch,
):
    monkeypatch.setattr(
        "scripts.session_memory.get_session_memory",
        lambda _session_id: RouteMemory(),
    )

    response = client.get("/api/v2/context/list?session_id=session-a")

    assert response.status_code == 200
    assert app_module._session_might_have_context("session-a") is False


def test_delete_verifies_ownership_result_and_invalidates_cache(
    client,
    monkeypatch,
):
    memory = RouteMemory()
    app_module._mark_session_context_state("session-a", True)
    monkeypatch.setattr(
        "scripts.session_memory.get_session_memory",
        lambda _session_id: memory,
    )

    response = client.delete(
        "/api/v2/context/owned?session_id=session-a"
    )

    assert response.status_code == 200
    assert response.get_json() == {"deleted": "owned"}
    assert memory.deleted_ids == ["owned"]
    assert "session-a" not in app_module._SESSION_CONTEXT_CACHE
    assert app_module._session_might_have_context("session-a") is True


def test_cross_session_delete_returns_404_without_marking_empty(
    client,
    monkeypatch,
):
    memory = RouteMemory()
    memory.deleted_result = False
    app_module._mark_session_context_state("session-a", True)
    monkeypatch.setattr(
        "scripts.session_memory.get_session_memory",
        lambda _session_id: memory,
    )

    response = client.delete(
        "/api/v2/context/cross-session?session_id=session-a"
    )

    assert response.status_code == 404
    assert app_module._session_might_have_context("session-a") is True


def test_delete_provider_error_hides_raw_exception(
    client,
    monkeypatch,
):
    class BrokenMemory:
        def delete_context(self, _document_id):
            raise RuntimeError("raw provider secret")

    monkeypatch.setattr(
        "scripts.session_memory.get_session_memory",
        lambda _session_id: BrokenMemory(),
    )

    response = client.delete(
        "/api/v2/context/doc-1?session_id=session-a"
    )

    assert response.status_code == 503
    assert b"raw provider secret" not in response.data


def test_research_recall_uses_normalized_session_chunk_text(
    client,
    monkeypatch,
):
    memory = RouteMemory()
    memory.recalled = [
        {
            "content": "Normalized text from chunks.",
            "metadata": {"source": "session-playbook.pdf"},
            "score": 0.9,
            "document_id": "doc-1",
        }
    ]
    app_module._mark_session_context_state("session-a", True)
    monkeypatch.setenv("ANONYMIZER_PROVIDER", "regex_only")
    monkeypatch.setattr(
        "scripts.session_memory.get_session_memory",
        lambda _session_id: memory,
    )
    monkeypatch.setattr(
        "scripts.vector_store.get_demo_vector_store",
        lambda: SimpleNamespace(query=lambda *_args, **_kwargs: []),
    )
    monkeypatch.setattr(
        "scripts.llm_provider.get_llm",
        lambda: SimpleNamespace(),
    )

    response = client.post(
        "/api/v2/chat",
        json={"query": "What is the cap?", "session_id": "session-a"},
    )

    assert response.status_code == 200
    assert b"session-playbook.pdf" in response.data
    assert b"session_context" in response.data


def test_empty_recall_does_not_mark_queued_session_empty(
    client,
    monkeypatch,
):
    memory = RouteMemory()
    app_module._mark_session_context_state("session-a", True)
    monkeypatch.setenv("ANONYMIZER_PROVIDER", "regex_only")
    monkeypatch.setattr(
        "scripts.session_memory.get_session_memory",
        lambda _session_id: memory,
    )
    monkeypatch.setattr(
        "scripts.vector_store.get_demo_vector_store",
        lambda: SimpleNamespace(
            query=lambda *_args, **_kwargs: [
                {
                    "text": "Library context",
                    "title": "Library source",
                    "category": "indemnification",
                }
            ]
        ),
    )
    monkeypatch.setattr(
        "scripts.llm_provider.get_llm",
        lambda: SimpleNamespace(),
    )

    response = client.post(
        "/api/v2/chat",
        json={"query": "What is the cap?", "session_id": "session-a"},
    )

    assert response.status_code == 200
    assert app_module._session_might_have_context("session-a") is True


def test_hub_clause_ask_consumes_normalized_context_text(monkeypatch):
    memory = RouteMemory()
    memory.recalled = [
        {
            "content": "Chunk-derived clause context.",
            "metadata": {"source": "term-sheet.docx"},
        }
    ]
    monkeypatch.setattr(
        "scripts.session_memory.get_session_memory",
        lambda _session_id: memory,
    )

    from scripts.hub_chat import _get_context_attachments

    assert _get_context_attachments("session-a", "cap") == [
        {
            "text": "Chunk-derived clause context.",
            "title": "term-sheet.docx",
            "page": "",
        }
    ]


def test_hub_delete_succeeds_when_optional_cleanup_fails(
    client,
    monkeypatch,
    caplog,
):
    memory = RouteMemory()
    memory.clear_result = False
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(
        "scripts.session_memory.get_session_memory",
        lambda _session_id: memory,
    )

    response = client.delete("/api/v2/hub/session-a")

    assert response.status_code == 200
    assert response.get_json()["deleted"] is True
    assert "cleanup failure" in caplog.text


def test_hub_sweep_counts_clear_successes_and_failures(
    client,
    monkeypatch,
):
    class FakeCursor:
        rowcount = 0

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, query, _params=None):
            if "SELECT id FROM hub_sessions" in query:
                self.rows = [("session-ok",), ("session-fail",)]
            elif "DELETE FROM hub_sessions" in query:
                self.rowcount = 2

        def fetchall(self):
            return self.rows

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def cursor(self):
            return FakeCursor()

        def commit(self):
            return None

    monkeypatch.setenv("DATABASE_URL", "postgresql://fake")
    monkeypatch.setattr(app_module, "_SCHEDULER_SECRET", "scheduler-test")
    monkeypatch.setitem(
        sys.modules,
        "psycopg",
        SimpleNamespace(connect=lambda _url: FakeConnection()),
    )

    def memory_for(session_id):
        memory = RouteMemory()
        memory.clear_result = session_id == "session-ok"
        return memory

    monkeypatch.setattr(
        "scripts.session_memory.get_session_memory",
        memory_for,
    )

    response = client.post(
        "/api/v2/hub/sweep",
        headers={"X-Scheduler-Secret": "scheduler-test"},
    )

    assert response.status_code == 200
    assert response.get_json() == {
        "deleted": 2,
        "supermemory_cleared": 1,
        "supermemory_errors": 1,
    }


def test_unused_supermemory_writes_are_absent():
    root = Path(__file__).resolve().parents[1]

    assert "chat_exchange" not in (root / "app.py").read_text(encoding="utf-8")
    assert "chat_exchange" not in (
        root / "scripts" / "hub_chat.py"
    ).read_text(encoding="utf-8")
    assert "review_summary" not in (
        root / "scripts" / "hub_export.py"
    ).read_text(encoding="utf-8")
    assert "session_summary" not in (
        root / "scripts" / "session_memory.py"
    ).read_text(encoding="utf-8")
