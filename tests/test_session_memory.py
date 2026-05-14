"""Tests for SessionMemory (Brief 2.2)."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest


class TestSessionMemory:
    SESSION_ID = "test-session-abc123"

    def _make_mem(self, monkeypatch):
        monkeypatch.setenv("SUPERMEMORY_API_KEY", "sm_test")
        monkeypatch.setenv("SESSION_MEMORY_TTL_HOURS", "24")
        monkeypatch.setenv("SESSION_MEMORY_MAX_SUMMARY_CHARS", "2000")
        monkeypatch.setenv("REVIEW_WRITES_ENABLED", "true")
        from scripts.session_memory import SessionMemory
        return SessionMemory(self.SESSION_ID)

    # -- write_summary validation --

    def test_write_summary_succeeds_with_valid_content(self, monkeypatch):
        mem = self._make_mem(monkeypatch)
        mock_client = MagicMock()
        mock_client.memories.add.return_value.id = "mem-xyz"
        with patch.object(mem, "_get_client", return_value=mock_client):
            mem_id = mem.write_summary(
                content="Anonymized review summary of NDA between [PARTY_A] and [COMPANY_1].",
                metadata={"anonymized": True, "kind": "review_summary"},
            )
        assert mem_id == "mem-xyz"

    def test_write_summary_blocked_when_writes_disabled(self, monkeypatch):
        mem = self._make_mem(monkeypatch)
        monkeypatch.setenv("REVIEW_WRITES_ENABLED", "false")
        result = mem.write_summary("content", metadata={"anonymized": True})
        assert result is None

    def test_write_summary_blocked_when_not_anonymized(self, monkeypatch):
        mem = self._make_mem(monkeypatch)
        result = mem.write_summary("content", metadata={"anonymized": False})
        assert result is None

    def test_write_summary_blocked_when_too_long(self, monkeypatch):
        monkeypatch.setenv("SESSION_MEMORY_MAX_SUMMARY_CHARS", "10")
        mem = self._make_mem(monkeypatch)
        result = mem.write_summary("x" * 11, metadata={"anonymized": True})
        assert result is None

    def test_write_summary_blocked_on_pii_token(self, monkeypatch):
        mem = self._make_mem(monkeypatch)
        result = mem.write_summary(
            "Party agreed, email: user@example.com for notifications.",
            metadata={"anonymized": True},
        )
        assert result is None

    def test_write_summary_returns_none_on_api_error(self, monkeypatch):
        mem = self._make_mem(monkeypatch)
        with patch.object(mem, "_get_client", side_effect=RuntimeError("API down")):
            result = mem.write_summary("Safe content", metadata={"anonymized": True})
        assert result is None

    # -- write (kind-gated) --

    def test_write_context_kind_succeeds(self, monkeypatch):
        mem = self._make_mem(monkeypatch)
        mock_client = MagicMock()
        mock_client.memories.add.return_value.id = "mem-ctx"
        with patch.object(mem, "_get_client", return_value=mock_client):
            result = mem.write("Anonymized context chunk.", kind="context",
                               metadata={"anonymized": True})
        assert result == "mem-ctx"

    def test_write_rejects_unknown_kind(self, monkeypatch):
        mem = self._make_mem(monkeypatch)
        result = mem.write("content", kind="raw_pii_dump", metadata={"anonymized": True})
        assert result is None

    # -- recall --

    def test_recall_returns_list(self, monkeypatch):
        mem = self._make_mem(monkeypatch)
        mock_result = MagicMock()
        mock_result.content = "Prior session context."
        mock_result.metadata = {"kind": "session_summary"}
        mock_result.score = 0.9
        mock_client = MagicMock()
        mock_client.search.execute.return_value.results = [mock_result]
        with patch.object(mem, "_get_client", return_value=mock_client):
            results = mem.recall(query="indemnification", kind="session_summary")
        assert len(results) == 1
        assert results[0]["content"] == "Prior session context."

    def test_recall_returns_empty_on_error(self, monkeypatch):
        mem = self._make_mem(monkeypatch)
        with patch.object(mem, "_get_client", side_effect=RuntimeError("fail")):
            results = mem.recall()
        assert results == []

    # -- clear --

    def test_clear_calls_supermemory_delete(self, monkeypatch):
        mem = self._make_mem(monkeypatch)
        mock_client = MagicMock()
        with patch.object(mem, "_get_client", return_value=mock_client):
            result = mem.clear()
        assert result is True
        mock_client.containers.delete.assert_called_once_with(container_tag=self.SESSION_ID)

    def test_clear_returns_false_on_error(self, monkeypatch):
        mem = self._make_mem(monkeypatch)
        with patch.object(mem, "_get_client", side_effect=RuntimeError("fail")):
            result = mem.clear()
        assert result is False


class TestGetSessionMemory:
    def test_factory_returns_session_memory(self, monkeypatch):
        monkeypatch.setenv("SUPERMEMORY_API_KEY", "sm_test")
        from scripts.session_memory import get_session_memory, SessionMemory
        mem = get_session_memory("session-123")
        assert isinstance(mem, SessionMemory)
        assert mem.session_id == "session-123"

    def test_factory_returns_new_instance_each_call(self, monkeypatch):
        monkeypatch.setenv("SUPERMEMORY_API_KEY", "sm_test")
        from scripts.session_memory import get_session_memory
        a = get_session_memory("s1")
        b = get_session_memory("s1")
        assert a is not b
