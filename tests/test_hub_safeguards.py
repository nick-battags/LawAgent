"""Safety invariants for anonymized Session-source storage and Hub artifacts."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from scripts import context_loader
from scripts.session_memory import SessionMemory
from scripts.supermemory_adapter import SupermemoryAdapter


class CapturingClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def add(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(id="doc-safe", status="done")


def test_anonymizer_map_and_original_values_never_reach_provider(
    monkeypatch,
):
    monkeypatch.setenv("ANONYMIZER_PROVIDER", "vertex_flash_lite")
    session_id = "map-persist-test"

    from scripts.anonymizer import get_session_anonymizer

    anonymizer = get_session_anonymizer(session_id)

    def anonymize_with_map(text: str):
        anonymizer._map = {
            "[PARTY_A]": "Acme Corporation",
            "[PARTY_B]": "Beta Holdings",
        }
        anonymizer._reverse = {
            original.lower(): placeholder
            for placeholder, original in anonymizer._map.items()
        }
        return (
            text.replace("Acme Corporation", "[PARTY_A]").replace(
                "Beta Holdings", "[PARTY_B]"
            ),
            anonymizer.snapshot(),
        )

    provider = CapturingClient()
    memory = SessionMemory(
        session_id,
        adapter=SupermemoryAdapter(client=provider),
    )
    with (
        patch.object(
            anonymizer,
            "_anonymize_via_llm",
            side_effect=anonymize_with_map,
        ),
        patch.object(
            context_loader,
            "get_session_memory",
            return_value=memory,
        ),
    ):
        result = context_loader.attach_context(
            session_id,
            content="Acme Corporation negotiated a public form with Beta Holdings.",
        )

    assert result["status"] == "ok"
    map_snapshot = anonymizer.snapshot()
    assert map_snapshot
    captured = provider.calls[0]
    captured_text = captured["content"]
    captured_metadata = repr(captured["metadata"])

    for placeholder, original in map_snapshot.items():
        assert original not in captured_text
        assert original not in captured_metadata
        assert placeholder in captured_text
    assert captured["metadata"]["anonymized"] is True
    assert captured["metadata"]["kind"] == "context"


def test_post_anonymization_firewall_blocks_actual_provider_payload(
    monkeypatch,
):
    provider = CapturingClient()
    from scripts.session_memory import SessionContextValidationError

    facade = SessionMemory(
        "session-safe",
        adapter=SupermemoryAdapter(client=provider),
    )

    try:
        facade.add_context(
            "Anonymizer failed open: user@example.com",
            {"anonymized": True},
        )
    except SessionContextValidationError:
        pass
    else:
        raise AssertionError("PII-bearing provider payload must be rejected")

    assert provider.calls == []


def test_optional_session_memory_failure_never_blocks_artifact_downloads(
    monkeypatch,
):
    monkeypatch.delenv("GCS_BUCKET", raising=False)

    def fail_if_called(_session_id):
        raise AssertionError("Bake must not write summaries to Supermemory")

    monkeypatch.setattr(
        "scripts.session_memory.get_session_memory",
        fail_if_called,
    )

    from scripts.hub_export import bake_session

    artifacts = bake_session(
        session_id="artifact-session",
        draft_text="Section 1. Public fictional agreement.",
        changes=[],
        decisions=[],
    )

    assert set(artifacts) == {
        "redline.docx_bytes",
        "clean.docx_bytes",
        "memo.docx_bytes",
        "register.json_bytes",
    }
    assert all(artifacts.values())


def test_anonymizer_lives_only_in_process_memory():
    from scripts.anonymizer import _sessions, get_session_anonymizer

    session_id = "in-memory-only-test"
    anonymizer = get_session_anonymizer(session_id)

    assert session_id in _sessions
    assert isinstance(anonymizer.snapshot(), dict)


def test_change_records_use_anonymized_text_before_rehydration():
    anonymized = "[PARTY_A] shall indemnify [COMPANY_1] up to 20%."

    assert "Acme Corporation" not in anonymized
    assert "[PARTY_A]" in anonymized
