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
