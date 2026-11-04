"""Credential middleware tests (PRD-21316 AC10, AC11, AC12).

AC11 (multi-tenant isolation) is the highest-stakes test in this repo: it is
the thing that proves a regression here would be a cross-tenant data leak,
not a cosmetic bug.
"""

import asyncio
import json

import httpx
import pytest

from posthog_mcp.middleware import (
    API_KEY_HEADER,
    HOST_HEADER,
    PROJECT_ID_HEADER,
    CredentialMiddleware,
    current_credentials,
)
from posthog_mcp.settings import DEFAULT_HOST


async def _echo_app(scope, receive, send):
    """Minimal downstream ASGI app: replies with the credentials it sees in
    the ContextVar, so tests can assert what the middleware set."""
    creds = current_credentials()
    body = json.dumps(
        {
            "api_key": creds.api_key if creds else None,
            "project_id": creds.project_id if creds else None,
            "host": creds.host if creds else None,
        }
    ).encode()
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": body})


def _client(app) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.asyncio
async def test_missing_both_headers_returns_401_naming_both():
    app = CredentialMiddleware(_echo_app)
    async with _client(app) as client:
        resp = await client.post("/mcp", json={})
    assert resp.status_code == 401
    body = resp.json()
    assert body["error"]["code"] == "not_configured"
    assert API_KEY_HEADER in body["error"]["message"]
    assert PROJECT_ID_HEADER in body["error"]["message"]


@pytest.mark.asyncio
async def test_missing_project_id_only_names_it():
    app = CredentialMiddleware(_echo_app)
    async with _client(app) as client:
        resp = await client.post("/mcp", json={}, headers={API_KEY_HEADER: "phx_abc"})
    assert resp.status_code == 401
    body = resp.json()
    assert body["error"]["message"] == "Missing required header(s): %s" % PROJECT_ID_HEADER


@pytest.mark.asyncio
async def test_missing_api_key_only_names_it():
    """TC-PH-012: X-PostHog-Api-Key absent, X-PostHog-Project-Id present."""
    app = CredentialMiddleware(_echo_app)
    async with _client(app) as client:
        resp = await client.post("/mcp", json={}, headers={PROJECT_ID_HEADER: "123"})
    assert resp.status_code == 401
    body = resp.json()
    assert body["error"]["message"] == "Missing required header(s): %s" % API_KEY_HEADER


@pytest.mark.asyncio
async def test_health_path_bypasses_credential_check():
    app = CredentialMiddleware(_echo_app, guarded_path="/mcp")
    async with _client(app) as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"api_key": None, "project_id": None, "host": None}


@pytest.mark.asyncio
async def test_valid_headers_populate_context_with_default_host():
    app = CredentialMiddleware(_echo_app)
    async with _client(app) as client:
        resp = await client.post(
            "/mcp",
            json={},
            headers={API_KEY_HEADER: "phx_abc", PROJECT_ID_HEADER: "123"},
        )
    assert resp.status_code == 200
    assert resp.json() == {"api_key": "phx_abc", "project_id": "123", "host": DEFAULT_HOST}


@pytest.mark.asyncio
async def test_host_header_overrides_default():
    app = CredentialMiddleware(_echo_app)
    async with _client(app) as client:
        resp = await client.post(
            "/mcp",
            json={},
            headers={
                API_KEY_HEADER: "phx_abc",
                PROJECT_ID_HEADER: "123",
                HOST_HEADER: "https://eu.posthog.com/",
            },
        )
    body = resp.json()
    # Trailing slash is stripped so client.py can safely join paths onto it.
    assert body["host"] == "https://eu.posthog.com"


@pytest.mark.asyncio
async def test_concurrent_requests_never_cross_tenants():
    """AC11: two concurrent requests with different credentials must each
    only ever observe their own credentials inside the handler."""

    results = {}

    async def _capturing_app(scope, receive, send):
        creds = current_credentials()
        # Yield control so the two concurrent calls actually interleave
        # instead of running sequentially inside a single event-loop tick.
        await asyncio.sleep(0)
        results[creds.project_id] = creds.api_key
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"{}"})

    app = CredentialMiddleware(_capturing_app)

    async def _call(api_key: str, project_id: str):
        async with _client(app) as client:
            await client.post(
                "/mcp",
                json={},
                headers={API_KEY_HEADER: api_key, PROJECT_ID_HEADER: project_id},
            )

    await asyncio.gather(
        _call("tenant-a-key", "100"),
        _call("tenant-b-key", "200"),
    )

    assert results == {"100": "tenant-a-key", "200": "tenant-b-key"}
