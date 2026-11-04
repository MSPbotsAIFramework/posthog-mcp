"""tools/list snapshot + per-tool happy-path and error-mapping against a
mocked PostHog API (PRD-21316 Test strategy: "tests/test_tools.py:
tools/list returns exactly 9 tools ... each tool's happy path and
404/401/429 mapping against a mocked PostHog API")."""

import asyncio
import json
import re

import httpx
import pytest

import posthog_mcp.tools._shared as shared
from posthog_mcp.app import _build_mcp_server, create_app
from posthog_mcp.client import PostHogClient
from posthog_mcp.errors import (
    INVALID_ARGUMENT,
    NOT_FOUND,
    RATE_LIMITED,
    UNAUTHORIZED,
    UPSTREAM_ERROR,
    PostHogApiError,
    code_for_status,
)
from posthog_mcp.middleware import PostHogCredentials, credentials_scope

EXPECTED_TOOL_COUNT = 9
SENTENCE_RE = re.compile(r"^[A-Z][^.\n]*\.$")

CREDS = PostHogCredentials(api_key="phx_test", project_id="123", host="https://us.posthog.com")


async def _tools_list():
    mcp = _build_mcp_server()
    return await mcp.get_tools()


def _mock_client_factory(handler):
    """Patches `posthog_mcp.tools._shared.PostHogClient` (the binding every
    tool goes through via `execute()`) so a tool call hits an
    `httpx.MockTransport` instead of the real network."""

    def factory(creds):
        return PostHogClient(creds, transport=httpx.MockTransport(handler))

    return factory


async def _call_tool(name: str, **kwargs) -> str:
    """Call a registered tool's underlying function with `CREDS` already in
    scope. The caller must monkeypatch `shared.PostHogClient` to a mock
    transport factory first -- this helper does not do that itself, since
    the mock handler is specific to each test."""
    tools = await _tools_list()
    tool = tools[name]
    with credentials_scope(CREDS):
        return await tool.fn(**kwargs)


def test_tools_list_snapshot():
    tools = asyncio.run(_tools_list())
    assert len(tools) == EXPECTED_TOOL_COUNT
    for name, tool in tools.items():
        assert name.startswith("posthog_"), name
        description = tool.description.strip()
        assert SENTENCE_RE.match(description), "not a single verb-first sentence: %r" % description
        assert len(description) <= 500
        assert tool.annotations.readOnlyHint is True, "%s must be readOnlyHint" % name


@pytest.mark.parametrize(
    "status_code,expected_code",
    [
        (401, UNAUTHORIZED),
        (403, UNAUTHORIZED),
        (404, NOT_FOUND),
        (400, INVALID_ARGUMENT),
        (422, INVALID_ARGUMENT),
        (429, RATE_LIMITED),
        (500, UPSTREAM_ERROR),
        (503, UPSTREAM_ERROR),
    ],
)
def test_status_to_error_code_mapping(status_code, expected_code):
    assert code_for_status(status_code) == expected_code


def test_429_is_retried_with_backoff_before_surfacing():
    """AC13/TC-PH-017: retries honoring Retry-After before surfacing."""
    attempts = []

    async def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(request)
        if len(attempts) < 3:
            return httpx.Response(429, headers={"Retry-After": "0"}, json={"detail": "slow down"})
        return httpx.Response(200, json={"ok": True})

    async def run():
        async with PostHogClient(CREDS, transport=httpx.MockTransport(handler)) as client:
            return await client.request("GET", "/api/projects/123/feature_flags/")

    result = asyncio.run(run())
    assert result == {"ok": True}
    assert len(attempts) == 3


def test_429_surfaces_as_rate_limited_after_exhausting_retries():
    """AC13/TC-PH-017: structured rate_limited error once the budget is exhausted."""

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "0"}, json={"detail": "slow down"})

    async def run():
        async with PostHogClient(CREDS, transport=httpx.MockTransport(handler)) as client:
            await client.request("GET", "/api/projects/123/feature_flags/")

    with pytest.raises(PostHogApiError) as exc_info:
        asyncio.run(run())
    assert code_for_status(exc_info.value.status_code) == RATE_LIMITED


def test_health_endpoint_ok_without_any_credentials():
    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async def run():
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/health")

    response = asyncio.run(run())
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# --- per-tool happy path / empty / not_found coverage (monkeypatched client) ---


def test_list_feature_flags_happy_path_with_pagination(monkeypatch):
    """AC1/TC-PH-001."""

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/projects/123/feature_flags/"
        return httpx.Response(
            200,
            json={
                "next": "https://us.posthog.com/api/projects/123/feature_flags/?offset=20",
                "results": [
                    {"id": 1, "key": "new-nav", "name": "New nav", "active": True, "deleted": False, "filters": {}}
                ],
            },
        )

    monkeypatch.setattr(shared, "PostHogClient", _mock_client_factory(handler))
    result = json.loads(asyncio.run(_call_tool("posthog_list_feature_flags")))
    assert result["has_more"] is True
    assert result["next_offset"] == 20
    assert result["items"][0]["key"] == "new-nav"


def test_list_feature_flags_no_match_returns_empty_array(monkeypatch):
    """AC1/AC9/TC-PH-002: no match -> [] not an error, not null."""

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"next": None, "results": []})

    monkeypatch.setattr(shared, "PostHogClient", _mock_client_factory(handler))
    result = json.loads(asyncio.run(_call_tool("posthog_list_feature_flags", search="nope")))
    assert result == {"items": [], "has_more": False}


def test_get_feature_flag_happy_path_includes_filters(monkeypatch):
    """AC2/TC-PH-003."""

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/projects/123/feature_flags/42/"
        return httpx.Response(
            200,
            json={"id": 42, "key": "beta", "name": "Beta", "active": True, "filters": {"groups": []}},
        )

    monkeypatch.setattr(shared, "PostHogClient", _mock_client_factory(handler))
    result = json.loads(asyncio.run(_call_tool("posthog_get_feature_flag", id=42)))
    assert result["key"] == "beta"
    assert result["filters"] == {"groups": []}


def test_get_feature_flag_not_found_is_structured(monkeypatch):
    """AC3/TC-PH-004: structured not_found, not a raw 404 or a crash."""

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "Not found."})

    monkeypatch.setattr(shared, "PostHogClient", _mock_client_factory(handler))
    result = json.loads(asyncio.run(_call_tool("posthog_get_feature_flag", id=999)))
    assert result == {"error": {"code": "not_found", "message": "Not found.", "retryable": False}}


def test_list_insights_omits_result_field(monkeypatch):
    """AC4/TC-PH-005: metadata only, no `result` chart-data payload."""

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params.get("basic") == "true"
        return httpx.Response(
            200,
            json={
                "next": None,
                "results": [
                    {
                        "id": 7,
                        "short_id": "abc123",
                        "name": "Signups",
                        "description": "Daily signups",
                        "filters": {},
                        "saved": True,
                        "favorited": False,
                        "tags": [],
                        "result": [{"huge": "chart-data"}],
                    }
                ],
            },
        )

    monkeypatch.setattr(shared, "PostHogClient", _mock_client_factory(handler))
    result = json.loads(asyncio.run(_call_tool("posthog_list_insights")))
    assert "result" not in result["items"][0]
    assert result["items"][0]["short_id"] == "abc123"


def test_get_insight_without_include_result_omits_result(monkeypatch):
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params.get("basic") == "true"
        return httpx.Response(200, json={"id": 7, "short_id": "abc123", "name": "Signups"})

    monkeypatch.setattr(shared, "PostHogClient", _mock_client_factory(handler))
    result = json.loads(asyncio.run(_call_tool("posthog_get_insight", id=7)))
    assert "result" not in result


def test_get_insight_with_include_result_true_returns_result(monkeypatch):
    """AC5/TC-PH-006 (automatable half): include_result=true adds `result`."""

    async def handler(request: httpx.Request) -> httpx.Response:
        assert "basic" not in request.url.params
        return httpx.Response(
            200,
            json={"id": 7, "short_id": "abc123", "name": "Signups", "result": [{"day": "2026-11-01", "count": 3}]},
        )

    monkeypatch.setattr(shared, "PostHogClient", _mock_client_factory(handler))
    result = json.loads(asyncio.run(_call_tool("posthog_get_insight", id=7, include_result=True)))
    assert result["result"] == [{"day": "2026-11-01", "count": 3}]


def test_get_insight_large_result_is_truncated_not_omitted(monkeypatch):
    """AC5: truncated per the token-economy rule if it exceeds the response cap."""

    big_series = [{"day": "2026-11-%02d" % (i % 28 + 1), "count": i} for i in range(5000)]

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": 7, "short_id": "abc123", "name": "Signups", "result": big_series})

    monkeypatch.setattr(shared, "PostHogClient", _mock_client_factory(handler))
    raw = asyncio.run(_call_tool("posthog_get_insight", id=7, include_result=True))
    assert len(raw) <= shared.MAX_RESPONSE_CHARS + 200  # small slack for the truncation-marker fields themselves
    result = json.loads(raw)
    assert result.get("result_truncated") is True
    assert len(result["result"]) < len(big_series)


def test_list_events_filters_passed_through(monkeypatch):
    """AC6/TC-PH-007."""

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params.get("event") == "signup"
        assert request.url.params.get("distinct_id") == "user-1"
        return httpx.Response(
            200,
            json={
                "next": None,
                "results": [
                    {"id": "e1", "event": "signup", "distinct_id": "user-1", "timestamp": "2026-11-01T00:00:00Z", "properties": {}}
                ],
            },
        )

    monkeypatch.setattr(shared, "PostHogClient", _mock_client_factory(handler))
    result = json.loads(
        asyncio.run(_call_tool("posthog_list_events", event="signup", distinct_id="user-1"))
    )
    assert len(result["items"]) == 1
    assert result["items"][0]["event"] == "signup"


def test_list_persons_search_match(monkeypatch):
    """AC7/TC-PH-008."""

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params.get("search") == "jane"
        return httpx.Response(
            200,
            json={
                "next": None,
                "results": [
                    {
                        "id": "p1",
                        "distinct_ids": ["jane@example.com"],
                        "properties": {"email": "jane@example.com"},
                        "is_identified": True,
                    }
                ],
            },
        )

    monkeypatch.setattr(shared, "PostHogClient", _mock_client_factory(handler))
    result = json.loads(asyncio.run(_call_tool("posthog_list_persons", search="jane")))
    assert result["items"][0]["distinct_ids"] == ["jane@example.com"]


def test_get_person_happy_path(monkeypatch):
    """AC8/TC-PH-009."""

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/projects/123/persons/p1/"
        return httpx.Response(
            200,
            json={"id": "p1", "distinct_ids": ["jane@example.com"], "properties": {"plan": "pro"}},
        )

    monkeypatch.setattr(shared, "PostHogClient", _mock_client_factory(handler))
    result = json.loads(asyncio.run(_call_tool("posthog_get_person", id="p1")))
    assert result["properties"] == {"plan": "pro"}


def test_list_cohorts_no_match_returns_empty_array(monkeypatch):
    """AC9/TC-PH-010."""

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"next": None, "results": []})

    monkeypatch.setattr(shared, "PostHogClient", _mock_client_factory(handler))
    result = json.loads(asyncio.run(_call_tool("posthog_list_cohorts", search="nope")))
    assert result == {"items": [], "has_more": False}


def test_list_cohorts_filters_by_type_client_side(monkeypatch):
    """`type` has no native PostHog query filter (it's derived from the
    `is_static` field), so this tool filters client-side -- covered
    separately from the plain-empty-result case above."""

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "next": None,
                "results": [
                    {"id": 1, "name": "Power users", "is_static": True},
                    {"id": 2, "name": "Active last 7d", "is_static": False},
                ],
            },
        )

    monkeypatch.setattr(shared, "PostHogClient", _mock_client_factory(handler))
    result = json.loads(asyncio.run(_call_tool("posthog_list_cohorts", type="static")))
    assert [c["id"] for c in result["items"]] == [1]


def test_list_annotations_no_match_returns_empty_array(monkeypatch):
    """AC9/TC-PH-011."""

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"next": None, "results": []})

    monkeypatch.setattr(shared, "PostHogClient", _mock_client_factory(handler))
    result = json.loads(asyncio.run(_call_tool("posthog_list_annotations", search="nope")))
    assert result == {"items": [], "has_more": False}
