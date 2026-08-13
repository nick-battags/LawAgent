"""Server-rendered route contracts for supported and disabled surfaces."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("WARMUP_DISABLED", "true")

import app as app_module


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(app_module, "ADMIN_PIN", "")
    monkeypatch.setattr(app_module, "HUB_ENABLED", True)
    app_module.app.config.update(
        TESTING=True,
        SECRET_KEY="route-contract-test-key",
    )
    with app_module.app.test_client() as test_client:
        yield test_client


@pytest.mark.parametrize(
    "path",
    ["/", "/hub", "/review", "/research", "/chat", "/health"],
)
def test_supported_routes_smoke(client, path):
    response = client.get(path)

    assert response.status_code == 200


def test_research_and_chat_render_the_same_surface(client):
    research_response = client.get("/research")
    chat_response = client.get("/chat")

    assert research_response.status_code == 200
    assert chat_response.status_code == 200
    assert research_response.data == chat_response.data


def test_public_navigation_prefers_research_desk(client):
    landing_html = client.get("/").get_data(as_text=True)
    hub_html = client.get("/hub").get_data(as_text=True)
    research_html = client.get("/research").get_data(as_text=True)

    assert 'href="/research"' in landing_html
    assert 'href="/research"' in hub_html
    assert "M&amp;A Research Desk" in landing_html
    assert "M&amp;A Research Desk" in research_html
    assert "Ask the Corpus" not in landing_html
    assert "Ask the Corpus" not in research_html
    assert 'href="/admin"' not in landing_html
    assert "Generate without a document" in landing_html
    assert "before any LLM or vector-store call" not in landing_html
    assert "sources retrieved for each answer" in landing_html
    assert "sources supporting each answer" not in landing_html


def test_research_uses_neutral_retrieval_label(client):
    script_response = client.get("/static/chat.js")

    assert script_response.status_code == 200
    script = script_response.get_data(as_text=True)
    assert "Retrieved sources:" in script
    assert "Supporting sources:" not in script


def test_research_session_source_statuses_and_polling_are_bounded(client):
    html = client.get("/research").get_data(as_text=True)
    script = client.get("/static/chat.js").get_data(as_text=True)

    assert 'id="sourcesStatus"' in html
    assert 'role="status"' in html
    assert 'aria-live="polite"' in html
    assert "Sessions auto-expire in 24h" not in html
    assert "Remove uploaded Session sources when you are finished." in html

    assert "if (!r.ok)" in script
    assert "Session sources unavailable — try again shortly." in script
    assert "Session source accepted and processing…" in script
    assert "Session sources ready." in script
    assert "failed to process." in script
    assert "Session source could not be removed — try again." in script
    assert "SOURCE_POLL_MAX_ATTEMPTS = 15" in script
    assert "SOURCE_POLL_INTERVAL_MS = 2000" in script
    assert "Still processing — try again shortly." in script
    assert "sourceRefreshGeneration" in script
    assert "cancelSourcePolling" in script
    assert "beforeunload" in script
    assert "sourceKind = c.category === 'session_context' ? 'Session' : 'Library'" in script


def test_conversation_surfaces_keep_threads_and_composers_width_stable(client):
    research_html = client.get("/research").get_data(as_text=True)
    chat_css = client.get("/static/chat.css").get_data(as_text=True)
    chat_script = client.get("/static/chat.js").get_data(as_text=True)
    hub_html = client.get("/hub").get_data(as_text=True)
    hub_css = client.get("/static/hub.css").get_data(as_text=True)
    hub_script = client.get("/static/hub.js").get_data(as_text=True)

    assert 'class="chat-main" aria-labelledby="researchHeading"' in research_html
    assert 'id="chatThread" class="chat-thread" role="log"' in research_html
    assert "grid-template-columns: 300px minmax(0, 1fr);" in chat_css
    assert "scrollbar-gutter: stable;" in chat_css
    assert ".chat-main" in chat_css and "min-width: 0;" in chat_css
    assert "data-research-prompt" in research_html
    assert "promptSuggestions.forEach" in chat_script

    assert 'id="askAnswer" class="ask-answer" role="log"' in hub_html
    assert "grid-template-rows: auto auto minmax(0, 1fr) auto auto;" in hub_css
    assert ".ask-input-row" in hub_css and "grid-template-columns: minmax(0, 1fr) auto;" in hub_css
    assert "appendAskMessage('user', question)" in hub_script
    assert "appendAskMessage('assistant', '')" in hub_script


def test_document_workspace_secondary_text_uses_readable_contrast(client):
    hub_css = client.get("/static/hub.css").get_data(as_text=True)

    assert "--workspace-secondary-ink: var(--ink-muted, #5C5247);" in hub_css
    assert "color: var(--workspace-secondary-ink);" in hub_css
    assert "background: var(--oxblood, #722F37);" in hub_css
    assert "#saveBakeBtn:disabled" in hub_css
    assert ".hub-download-bar .btn-download:disabled" in hub_css


def _collapse(html: str) -> str:
    """Collapse template whitespace/newlines so copy checks ignore wrapping."""
    return " ".join(html.split())


def test_landing_and_hub_describe_anonymization_as_best_effort(client):
    landing_html = _collapse(client.get("/").get_data(as_text=True))
    hub_html = _collapse(client.get("/hub").get_data(as_text=True))

    # Best-effort framing is present on the public overview and the Hub intake.
    assert "best effort" in landing_html
    assert "best effort" in hub_html

    # Categorical anonymization promises must not return on either surface.
    for categorical in (
        "anonymize input before retrieval",
        "workflows anonymize input",
        "are anonymized",
        "anonymized writes only",
    ):
        assert categorical not in landing_html
        assert categorical not in hub_html


def test_public_pickers_do_not_advertise_unsupported_txt(client):
    # scripts/hub_pipeline.extract_text() accepts only PDF/DOCX bytes, so the
    # public context/source pickers must not advertise .txt.
    hub_html = client.get("/hub").get_data(as_text=True)
    research_html = client.get("/research").get_data(as_text=True)

    assert 'accept=".pdf,.docx,.txt"' not in hub_html
    assert 'accept=".pdf,.docx,.txt"' not in research_html
    assert 'accept=".pdf,.docx"' in hub_html
    assert 'accept=".pdf,.docx"' in research_html


def test_hub_review_does_not_submit_a_hidden_prompt(client):
    script = client.get("/static/hub.js").get_data(as_text=True)

    # A prompt retained after switching from Generate/Revise must not influence
    # Review, whose intake deliberately has no prompt control.
    assert "const prompt = currentMode === 'review'" in script
    assert "if (mode !== 'review' && prompt) fd.append('prompt', prompt);" in script


def test_hub_rejects_unsupported_context_files_and_surfaces_upload_failures(client):
    hub_html = client.get("/hub").get_data(as_text=True)
    script = client.get("/static/hub.js").get_data(as_text=True)

    assert "SUPPORTED_DOCUMENT_EXTENSIONS = ['.pdf', '.docx']" in script
    assert "if (!isSupportedDocument(file))" in script
    assert 'id="workspaceNotice"' in hub_html
    assert "pendingWorkspaceWarnings.push(warning)" in script
    assert "workspaceNotice.textContent = pendingWorkspaceWarnings.join" in script

    upload_context = script.split("async function uploadContext", 1)[1].split(
        "async function submitHub", 1
    )[0]
    assert "if (!r.ok)" in upload_context
    assert "throw await window.argusConsent.errorFromResponse" in upload_context
    assert "some context files could not be attached" in script


def test_hub_workspace_is_document_first_without_claiming_saved_matters(client):
    html = client.get("/hub").get_data(as_text=True)

    for required_id in (
        "editingHub",
        "workspaceActionStatus",
        "matterRailTitle",
        "matterTitle",
        "docViewer",
        "inspectorTitle",
        "issuesList",
        "missingList",
        "askQuestion",
        "workspaceExports",
    ):
        assert f'id="{required_id}"' in html

    for target in ("document", "issues", "missing", "ask", "exports"):
        assert f'data-workspace-target="{target}"' in html

    assert 'aria-label="Document review workspace"' in html
    assert 'aria-label="Review inspector"' in html
    assert "saved matters" not in html.lower()
    assert "resume this matter" not in html.lower()

    for artifact_name in ("redline.docx", "clean.docx", "memo.docx", "register.json"):
        assert html.count(artifact_name) == 1


def test_hub_workspace_tracks_reversible_decisions_and_accessible_tabs(client):
    script = client.get("/static/hub.js").get_data(as_text=True)

    assert "function canonicalAction(action)" in script
    assert "change.current_action = canonicalAction(result.action || action)" in script
    assert "updateWorkspaceSummary()" in script
    assert "railPendingCount.textContent" in script
    assert "railDecidedCount.textContent" in script
    assert "button.setAttribute('aria-pressed'" in script
    assert "tab.setAttribute('aria-selected'" in script
    assert "panel.hidden = !selected" in script
    assert "['ArrowLeft', 'ArrowRight', 'Home', 'End']" in script
    assert "Decision could not be saved:" in script
    assert "Some decisions could not be saved." in script
    assert "Exports could not be created:" in script
    assert "let batchInProgress = false" in script
    assert "if (batchInProgress) return" in script
    assert "acceptAllBtn.disabled = batchInProgress || pendingCount === 0" in script
    assert "rejectAllBtn.disabled = batchInProgress || pendingCount === 0" in script
    assert "batchInProgress = false" in script
    assert "acceptAllBtn.dataset.state = 'working'" in script
    assert "rejectAllBtn.dataset.state = 'working'" in script
    assert "saveBakeBtn.dataset.state = 'ready'" in script
    assert "btn.dataset.state = 'downloaded'" in script
    assert "download started" in script


def test_consent_gate_is_shared_and_manages_focus(client):
    hub_html = client.get("/hub").get_data(as_text=True)
    research_html = client.get("/research").get_data(as_text=True)

    assert 'src="/static/consent.js"' in hub_html
    assert 'src="/static/consent.js"' in research_html
    assert 'id="consentError"' in hub_html
    assert 'id="consentError"' in research_html

    script_response = client.get("/static/consent.js")
    assert script_response.status_code == 200
    script = script_response.get_data(as_text=True)
    # Focus starts inside the dialog and the background is made inert.
    assert "acceptBtn.focus" in script
    assert "inert" in script
    # Failed issuance remains fail-closed; stale tokens are removed and the
    # shared gate can reopen itself from API error handling.
    assert "|| 'accepted'" not in script
    assert "sessionStorage.removeItem(KEY)" in script
    assert "invalidate: invalidate" in script
    assert "errorFromResponse: errorFromResponse" in script

    hub_script = client.get("/static/hub.js").get_data(as_text=True)
    research_script = client.get("/static/chat.js").get_data(as_text=True)
    assert "argus:consent-invalid" in hub_script
    assert "argus:consent-invalid" in research_script
    assert "argusConsent.errorFromResponse" in hub_script
    assert "argusConsent.errorFromResponse" in research_script
    # An expired token must not strand the optimistic Research message: remove
    # it and restore the exact query for explicit resubmission after consent.
    assert "const pendingMessage = appendUserMessage(query)" in research_script
    assert "pendingMessage.remove()" in research_script
    assert "restoreQuery(query)" in research_script
    assert "chatInput.value = current ?" in research_script


def test_public_copy_avoids_deprecated_and_unimplemented_links(client):
    for path in ("/", "/hub", "/research"):
        html = client.get(path).get_data(as_text=True)
        assert "Ask the Corpus" not in html
        assert "Clause Q&amp;A" not in html
        assert 'href="/legal"' not in html
        assert 'href="/admin"' not in html

    landing_html = client.get("/").get_data(as_text=True)
    assert "Supporting sources" not in landing_html


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/admin"),
        ("get", "/admin/login"),
        ("post", "/admin/login"),
        ("get", "/admin/logout"),
        ("get", "/api/v2/runtime/status"),
    ],
)
def test_admin_routes_are_unavailable_when_pin_is_unset(client, method, path):
    response = getattr(client, method)(path)

    assert response.status_code == 404
    assert response.headers.get("Location") is None


def test_disabled_admin_rejects_a_stale_authenticated_session(client):
    with client.session_transaction() as flask_session:
        flask_session["admin_authed"] = True

    assert client.get("/admin").status_code == 404
    assert client.get("/api/v2/runtime/status").status_code == 404


def test_enabled_admin_requires_login_for_pages_and_apis(client, monkeypatch):
    monkeypatch.setattr(app_module, "ADMIN_PIN", "2468")

    page_response = client.get("/admin")
    api_response = client.get("/api/v2/runtime/status")

    assert page_response.status_code == 302
    assert page_response.headers["Location"].endswith("/admin/login")
    assert api_response.status_code == 401
    assert api_response.get_json() == {"error": "Admin authentication required."}


def test_enabled_admin_login_and_logout_round_trip(client, monkeypatch):
    monkeypatch.setattr(app_module, "ADMIN_PIN", "2468")

    login_page = client.get("/admin/login")
    bad_login = client.post("/admin/login", data={"pin": "wrong"})
    good_login = client.post("/admin/login", data={"pin": "2468"})
    admin_page = client.get("/admin")
    logout = client.get("/admin/logout")
    logged_out_page = client.get("/admin")

    assert login_page.status_code == 200
    assert bad_login.status_code == 200
    assert b"Incorrect PIN" in bad_login.data
    assert good_login.status_code == 302
    assert good_login.headers["Location"].endswith("/admin")
    assert admin_page.status_code == 200
    assert b"Backend Management" in admin_page.data
    assert logout.status_code == 302
    assert logout.headers["Location"].endswith("/admin/login")
    assert logged_out_page.status_code == 302
    assert logged_out_page.headers["Location"].endswith("/admin/login")
