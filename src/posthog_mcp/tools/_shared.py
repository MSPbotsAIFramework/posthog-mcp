"""Helpers reused by every `tools/<resource>.py` module.

Centralizing the credential check / client lifecycle / error mapping here
means an individual tool function only has to describe its one PostHog call
and how to shape the result -- not repeat the not_configured/try/except
boilerplate that error handling would otherwise require in every tool.
"""

from collections.abc import Awaitable, Callable

from posthog_mcp.client import PostHogClient
from posthog_mcp.errors import (
    PostHogApiError,
    dumps,
    envelope_for_api_error,
    not_configured_envelope,
)
from posthog_mcp.middleware import REQUIRED_HEADERS, current_credentials

DEFAULT_LIMIT = 20
MAX_LIMIT = 100
MAX_RESPONSE_CHARS = 20_000


async def execute(build_result: Callable[[PostHogClient], Awaitable[dict]]) -> str:
    """Resolve the current request's credentials, run `build_result` with a
    fresh `PostHogClient`, and serialize the outcome -- success or mapped
    error -- as the compact JSON string every tool must return (PRD-21316
    tech design: error envelope + S2.5 serialization)."""
    creds = current_credentials()
    if creds is None:
        # Reachable only if a tool is invoked without going through the ASGI
        # middleware (e.g. a unit test calling it directly); in production
        # CredentialMiddleware already rejects the request with 401 before
        # any tool runs.
        return dumps(not_configured_envelope(list(REQUIRED_HEADERS)))
    try:
        async with PostHogClient(creds) as client:
            result = await build_result(client)
    except PostHogApiError as exc:
        return dumps(envelope_for_api_error(exc))
    return dumps(result)


def clamp_limit(limit: int | None) -> int:
    if limit is None:
        return DEFAULT_LIMIT
    return max(1, min(limit, MAX_LIMIT))


def list_query(limit: int | None, offset: int | None, **filters) -> tuple[dict, int, int]:
    """Build a PostHog list-endpoint query string. Returns the params plus
    the effective (clamped) `limit` and `offset` the caller used, so
    `list_result` can compute `next_offset` without re-deriving them."""
    effective_limit = clamp_limit(limit)
    effective_offset = max(0, offset or 0)
    params = {k: v for k, v in filters.items() if v is not None}
    params["limit"] = effective_limit
    params["offset"] = effective_offset
    return params, effective_limit, effective_offset


def list_result(items: list[dict], limit: int, offset: int, next_url: str | None) -> dict:
    """Shared shape for every list tool (PRD-21316 AC1: `has_more` + next
    offset). PostHog's DRF-style pagination returns a full `next` URL or
    `null`; the caller only needs to know whether more pages exist and what
    offset to ask for next, so this collapses that URL to a boolean plus an
    integer rather than exposing PostHog's own URL shape. Also enforces the
    token-economy response-size cap (SOP S2.5) by dropping trailing items."""
    has_more = bool(next_url)
    result: dict = {"items": items, "has_more": has_more}
    if has_more:
        result["next_offset"] = offset + limit
    while len(dumps(result)) > MAX_RESPONSE_CHARS and result["items"]:
        result["items"] = result["items"][:-1]
        result["has_more"] = True
        result["next_offset"] = offset + len(result["items"])
    return result


def truncate_large_field(obj: dict, field: str) -> dict:
    """Keep `obj` under the response-size cap by shrinking `obj[field]`
    (PRD-21316 AC5: `posthog_get_insight(include_result=true)` can return a
    large nested chart-data payload). If the field is a list, trailing items
    are dropped like `list_result` does; otherwise the field is replaced
    with an explicit truncation marker, since there is no generic way to
    shrink an arbitrary nested dict without guessing at its shape."""
    if len(dumps(obj)) <= MAX_RESPONSE_CHARS:
        return obj
    value = obj.get(field)
    if isinstance(value, list):
        items = list(value)
        while items and len(dumps({**obj, field: items})) > MAX_RESPONSE_CHARS:
            items.pop()
        obj[field] = items
        obj["%s_truncated" % field] = True
        return obj
    obj[field] = {
        "truncated": True,
        "message": (
            "Omitted: serialized %s exceeds the ~%d character response cap. "
            "View this insight in the PostHog UI for full data."
        )
        % (field, MAX_RESPONSE_CHARS),
    }
    return obj
