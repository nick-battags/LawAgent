"""Safety and behavior tests for the context-only SessionMemory facade."""

from __future__ import annotations

import pytest

from scripts.session_memory import (
    SessionContextValidationError,
    SessionMemory,
    get_session_memory,
)
from scripts.supermemory_adapter import SupermemoryUnavailableError


class AdapterFake:
    def __init__(self) -> None:
        self.add_result = {"id": "doc-1", "processing_status": "processing"}
        self.recall_result: list[dict] = []
        self.clear_result = True
        self.raise_on_add = False
        self.raise_on_clear = False
        self.added: list[dict] = []

    def add_context(self, session_id, content, metadata):
        if self.raise_on_add:
            raise SupermemoryUnavailableError("unavailable")
        self.added.append(
            {
                "session_id": session_id,
                "content": content,
                "metadata": metadata,
            }
        )
        return self.add_result

    def list_context(self, session_id):
        return []

    def recall_context(self, session_id, query, limit=4):
        return self.recall_result

    def delete_context(self, session_id, document_id):
        return True

    def clear_session(self, session_id):
        if self.raise_on_clear:
            raise SupermemoryUnavailableError("unavailable")
        return self.clear_result


def test_anonymized_context_is_accepted():
    adapter = AdapterFake()
    memory = SessionMemory("session-a", adapter=adapter)

    result = memory.add_context(
        "Anonymized context for [PARTY_A].",
        {"anonymized": True, "source": "playbook.pdf"},
    )

    assert result["id"] == "doc-1"
    assert adapter.added[0]["metadata"]["kind"] == "context"


def test_unanonymized_metadata_is_rejected():
    memory = SessionMemory("session-a", adapter=AdapterFake())

    with pytest.raises(SessionContextValidationError):
        memory.add_context("Safe content", {"anonymized": False})


def test_context_limit_accepts_boundary_and_rejects_above(monkeypatch):
    monkeypatch.setenv("SESSION_CONTEXT_MAX_CHARS", "40")
    adapter = AdapterFake()
    memory = SessionMemory("session-a", adapter=adapter)

    memory.add_context("x" * 40, {"anonymized": True})
    with pytest.raises(SessionContextValidationError):
        memory.add_context("x" * 41, {"anonymized": True})


@pytest.mark.parametrize(
    "content",
    [
        "Contact user@example.com for the source.",
        "This came from my client and must remain private.",
    ],
)
def test_pii_heuristic_and_firewall_reject_actual_payload(content):
    memory = SessionMemory("session-a", adapter=AdapterFake())

    with pytest.raises(SessionContextValidationError):
        memory.add_context(content, {"anonymized": True})


def test_provider_failure_is_stable_and_predictable():
    adapter = AdapterFake()
    adapter.raise_on_add = True
    memory = SessionMemory("session-a", adapter=adapter)

    with pytest.raises(SupermemoryUnavailableError):
        memory.add_context("Safe context", {"anonymized": True})


def test_recall_returns_only_nonempty_strings():
    adapter = AdapterFake()
    adapter.recall_result = [
        {"content": "Useful source text", "metadata": {}, "score": 1.0},
        {"content": "  ", "metadata": {}, "score": 0.5},
        {"content": None, "metadata": {}, "score": 0.1},
    ]
    memory = SessionMemory("session-a", adapter=adapter)

    assert memory.recall_context("query") == [adapter.recall_result[0]]


def test_clear_reports_actual_success_and_failure():
    adapter = AdapterFake()
    memory = SessionMemory("session-a", adapter=adapter)

    assert memory.clear() is True
    adapter.clear_result = False
    assert memory.clear() is False
    adapter.raise_on_clear = True
    assert memory.clear() is False


def test_factory_returns_new_context_facades():
    first = get_session_memory("session-a")
    second = get_session_memory("session-a")

    assert isinstance(first, SessionMemory)
    assert first.session_id == "session-a"
    assert first is not second
