"""Unit tests for truthful Session-source attachment results."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from scripts import context_loader
from scripts.supermemory_adapter import (
    SupermemoryRejectedError,
    SupermemoryUnavailableError,
)


class MemoryFake:
    def __init__(self, result=None, error=None):
        self.max_chars = 4000
        self.result = result or {
            "id": "doc-1",
            "processing_status": "processing",
        }
        self.error = error
        self.calls: list[dict] = []

    def add_context(self, content, metadata):
        self.calls.append({"content": content, "metadata": metadata})
        if self.error:
            raise self.error
        return self.result


@pytest.fixture(autouse=True)
def fake_anonymizer(monkeypatch):
    monkeypatch.setattr(
        context_loader,
        "get_session_anonymizer",
        lambda _session_id: SimpleNamespace(
            anonymize=lambda text: (text, {}),
        ),
        raising=False,
    )
    monkeypatch.setattr(
        "scripts.anonymizer.get_session_anonymizer",
        lambda _session_id: SimpleNamespace(
            anonymize=lambda text: (text, {}),
        ),
    )


@pytest.mark.parametrize(
    ("provider_status", "expected_status"),
    [("processing", "processing"), ("ready", "ready")],
)
def test_attach_returns_id_and_processing_status(
    monkeypatch,
    provider_status,
    expected_status,
):
    memory = MemoryFake(
        {"id": "doc-accepted", "processing_status": provider_status}
    )
    monkeypatch.setattr(context_loader, "get_session_memory", lambda _: memory)

    result = context_loader.attach_context(
        "session-a",
        content="Public fictional playbook terms.",
    )

    assert result["status"] == "ok"
    assert result["id"] == "doc-accepted"
    assert result["memory_id"] == "doc-accepted"
    assert result["processing_status"] == expected_status


def test_attach_with_no_returned_id_never_claims_success(monkeypatch):
    memory = MemoryFake({"id": "", "processing_status": "processing"})
    monkeypatch.setattr(context_loader, "get_session_memory", lambda _: memory)

    result = context_loader.attach_context(
        "session-a",
        content="Public fictional source.",
    )

    assert result["status"] == "error"
    assert result["error_code"] == "provider_rejected"


@pytest.mark.parametrize(
    ("error", "expected_code"),
    [
        (
            SupermemoryUnavailableError("raw provider details"),
            "provider_unavailable",
        ),
        (
            SupermemoryRejectedError("raw provider details"),
            "provider_rejected",
        ),
    ],
)
def test_provider_errors_are_stable_and_hide_raw_details(
    monkeypatch,
    error,
    expected_code,
):
    memory = MemoryFake(error=error)
    monkeypatch.setattr(context_loader, "get_session_memory", lambda _: memory)

    result = context_loader.attach_context(
        "session-a",
        content="Public fictional source.",
    )

    assert result["status"] == "error"
    assert result["error_code"] == expected_code
    assert "raw provider details" not in result["error"]


def test_failed_provider_status_is_not_reported_as_accepted(monkeypatch):
    memory = MemoryFake(
        {"id": "doc-failed", "processing_status": "failed"}
    )
    monkeypatch.setattr(context_loader, "get_session_memory", lambda _: memory)

    result = context_loader.attach_context(
        "session-a",
        content="Public fictional source.",
    )

    assert result["status"] == "error"
    assert result["processing_status"] == "failed"


def test_long_context_is_truncated_before_validation_with_truthful_metadata(
    monkeypatch,
):
    memory = MemoryFake()
    monkeypatch.setattr(context_loader, "get_session_memory", lambda _: memory)

    result = context_loader.attach_context(
        "session-a",
        content="x" * 5000,
    )

    captured = memory.calls[0]
    assert result["status"] == "ok"
    assert result["truncated"] is True
    assert len(captured["content"]) == memory.max_chars
    assert captured["metadata"]["char_count"] == len(
        captured["content"].split("\n", 1)[1]
    )


def test_validation_and_extraction_failures_are_user_errors(monkeypatch):
    assert context_loader.attach_context("session-a")["error_code"] == "invalid_source"
    assert context_loader.attach_context(
        "session-a", content="   "
    )["error_code"] == "invalid_source"

    monkeypatch.setattr(
        "scripts.hub_pipeline.extract_text",
        lambda *_args: (_ for _ in ()).throw(ValueError("raw parser error")),
    )
    result = context_loader.attach_context(
        "session-a",
        file_bytes=b"not-a-docx",
        filename="source.docx",
    )
    assert result["error_code"] == "invalid_source"
    assert "raw parser error" not in result["error"]
