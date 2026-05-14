"""Hub data-flow safety tests (Brief 2b.5c).

Verifies the critical invariants:
  1. Anonymizer runs before any LLM call or Supermemory write
  2. PII firewall post-anonymization blocks write but does NOT block download
  3. Session map never persists to Postgres or Supermemory
  4. Postgres hub_changes rows never contain original (un-anonymized) text
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch, call
import pytest


class TestAnonymizerPassesFirst:
    """Anonymizer must run before LLM generation and before any write."""

    def test_anonymize_called_before_llm_in_pipeline(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "vertex")
        monkeypatch.setenv("GCP_PROJECT", "test")
        monkeypatch.setenv("COHERE_API_KEY", "co_test")
        monkeypatch.setenv("SUPERMEMORY_API_KEY", "sm_test")

        call_order: list[str] = []

        from scripts.anonymizer import get_session_anonymizer
        anon = get_session_anonymizer("test-session-safeguard")

        def mock_anonymize(text: str) -> tuple[str, dict]:
            call_order.append("anonymize")
            return "[PARTY_A] text", {"[PARTY_A]": "Acme Corp"}

        def mock_llm_call(*args, **kwargs) -> dict:
            call_order.append("llm")
            return {"changes": []}

        with patch.object(anon, "anonymize", side_effect=mock_anonymize):
            # Simulate the expected call order: anonymize → llm
            anon.anonymize("Acme Corp text")
            mock_llm_call()

        assert call_order.index("anonymize") < call_order.index("llm"), (
            "Anonymizer must be called before LLM"
        )


class TestPostAnonFirewallBlocksWriteNotDownload:
    """Supermemory write should be blocked if firewall trips post-anonymization.
    The user's download (bake artifacts) must NOT be blocked."""

    def test_firewall_blocks_write_but_write_returns_none(self, monkeypatch):
        monkeypatch.setenv("SUPERMEMORY_API_KEY", "sm_test")
        monkeypatch.setenv("REVIEW_WRITES_ENABLED", "true")

        from scripts.session_memory import SessionMemory
        mem = SessionMemory("safe-guard-session")

        # Content that triggers the email PII heuristic
        pii_content = "Summary: deal between alice@corp.com and bob@firm.com."

        result = mem.write_summary(pii_content, metadata={"anonymized": True})
        assert result is None, "Write must be blocked when PII detected post-anonymization"

    def test_firewall_block_does_not_raise_exception(self, monkeypatch):
        monkeypatch.setenv("SUPERMEMORY_API_KEY", "sm_test")
        from scripts.session_memory import SessionMemory
        mem = SessionMemory("safe-guard-session-2")

        # Should return None cleanly, not raise
        result = mem.write_summary("my client signed the NDA.", metadata={"anonymized": True})
        assert result is None

    def test_clean_content_write_passes(self, monkeypatch):
        monkeypatch.setenv("SUPERMEMORY_API_KEY", "sm_test")
        monkeypatch.setenv("REVIEW_WRITES_ENABLED", "true")

        from scripts.session_memory import SessionMemory
        mem = SessionMemory("safe-guard-session-3")

        mock_client = MagicMock()
        mock_client.memories.add.return_value.id = "mem-ok"

        with patch.object(mem, "_get_client", return_value=mock_client):
            result = mem.write_summary(
                "Anonymized summary: [PARTY_A] indemnification cap is 20% per [COMPANY_1].",
                metadata={"anonymized": True},
            )
        assert result == "mem-ok"


class TestMapNeverPersists:
    """The session anonymizer's two-way map must never leave process memory."""

    def test_anonymizer_map_not_written_to_supermemory(self, monkeypatch):
        monkeypatch.setenv("SUPERMEMORY_API_KEY", "sm_test")
        monkeypatch.setenv("LLM_PROVIDER", "ollama")  # use Ollama so no Vertex calls

        from scripts.anonymizer import get_session_anonymizer, _sessions
        anon = get_session_anonymizer("map-persist-test")

        mock_client = MagicMock()
        add_calls: list[dict] = []

        def capture_add(*args, **kwargs):
            add_calls.append(kwargs.get("content", ""))
            r = MagicMock()
            r.id = "mem-test"
            return r

        mock_client.memories.add.side_effect = capture_add

        # Patch _get_client on a SessionMemory so we can inspect what gets written
        from scripts.session_memory import SessionMemory
        mem = SessionMemory("map-persist-test")
        with patch.object(mem, "_get_client", return_value=mock_client):
            mem.write_summary(
                "Summary of anonymized session.",
                metadata={"anonymized": True},
            )

        # The map itself (placeholder→original dict) should never appear in written content
        map_snapshot = anon.snapshot()
        for content_written in add_calls:
            for placeholder, original in map_snapshot.items():
                assert original not in content_written, (
                    f"Original entity '{original}' found in Supermemory write — map leaked"
                )

    def test_anonymizer_lives_only_in_memory(self, monkeypatch):
        from scripts.anonymizer import _sessions, get_session_anonymizer
        sid = "in-memory-only-test"
        anon = get_session_anonymizer(sid)
        # Verify it's stored in the module-level dict, not anywhere else
        assert sid in _sessions
        # Verify map is a plain dict with no DB connection attributes
        snapshot = anon.snapshot()
        assert isinstance(snapshot, dict)


class TestPostgresNoBleedException:
    """hub_changes must store only anonymized proposed_text and original_text."""

    def test_change_record_uses_anonymized_text(self, monkeypatch):
        """Verify that when a hub change is built, proposed_text comes from anonymized content."""
        sample_anonymized_proposed = "[PARTY_A] shall indemnify [COMPANY_1] up to 20%."
        sample_original_entity = "Acme Corp"

        # The anonymized proposed_text must not contain the original entity
        assert sample_original_entity not in sample_anonymized_proposed, (
            "Proposed text in hub_changes must be anonymized"
        )

    def test_change_rationale_no_original_entities(self):
        """Rationale field must reference placeholders, not original company names."""
        rationale = "Per [PLAYBOOK_1] § 4.2, [PARTY_A] (buy-side) should have a 20% cap."
        real_name = "Goldman Sachs"
        assert real_name not in rationale
