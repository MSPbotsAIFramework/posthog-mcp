"""Thin async wrapper around the PostHog REST API (PRD-21316 AC13, tech design S5).

One client per tool call, built from the credentials already resolved by
middleware.py for the current request -- never a shared/global client holding
a specific tenant's token or base URL.
"""

import asyncio

import httpx

from posthog_mcp.errors import PostHogApiError
from posthog_mcp.middleware import PostHogCredentials
from posthog_mcp.settings import CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS

MAX_RETRIES = 3
DEFAULT_BACKOFF_SECONDS = 1.0
MAX_BACKOFF_SECONDS = 20.0
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class PostHogClient:
    """Issues one request per call; the caller (a tool) owns its lifecycle
    via `async with PostHogClient(creds) as client: ...`."""

    def __init__(self, creds: PostHogCredentials, transport: httpx.BaseTransport | None = None):
        # `transport` is test-only: it lets tests/test_tools.py point this
        # client at an `httpx.MockTransport` instead of the real network,
        # without duplicating the header/timeout setup below.
        self.project_id = creds.project_id
        self._http = httpx.AsyncClient(
            base_url=creds.host,
            transport=transport,
            headers={
                "Authorization": "Bearer %s" % creds.api_key,
                "Accept": "application/json",
            },
            timeout=httpx.Timeout(
                connect=CONNECT_TIMEOUT_SECONDS, read=READ_TIMEOUT_SECONDS,
                write=READ_TIMEOUT_SECONDS, pool=READ_TIMEOUT_SECONDS,
            ),
        )

    async def __aenter__(self) -> "PostHogClient":
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self._http.aclose()

    def project_path(self, suffix: str) -> str:
        """Build a `/api/projects/{project_id}/...` path. `suffix` must
        start with `/` and end with `/` per PostHog's own API convention
        (trailing slash is significant -- PostHog redirects otherwise)."""
        return "/api/projects/%s%s" % (self.project_id, suffix)

    async def request(self, method: str, path: str, **kwargs) -> dict:
        """Send one PostHog API call, retrying 429/5xx with backoff
        (honouring `Retry-After` when present). Raises `PostHogApiError` on
        a non-2xx response that survives retries, or on a network/timeout
        failure (mapped to `upstream_error` by errors.code_for_status)."""
        last_exc: Exception | None = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                response = await self._http.request(method, path, **kwargs)
            except httpx.TimeoutException as exc:
                last_exc = exc
                if attempt == MAX_RETRIES:
                    raise PostHogApiError(599, "Timed out calling PostHog: %s" % exc) from exc
                await asyncio.sleep(self._backoff(attempt))
                continue
            except httpx.HTTPError as exc:
                last_exc = exc
                if attempt == MAX_RETRIES:
                    raise PostHogApiError(599, "Network error calling PostHog: %s" % exc) from exc
                await asyncio.sleep(self._backoff(attempt))
                continue

            if response.status_code < 400:
                if response.status_code == 204 or not response.content:
                    return {}
                return response.json()

            if response.status_code in RETRYABLE_STATUS and attempt < MAX_RETRIES:
                await asyncio.sleep(self._retry_delay(response, attempt))
                continue

            raise PostHogApiError(response.status_code, _message_from(response))

        # Unreachable in practice: the loop above always returns or raises.
        raise PostHogApiError(599, "Exhausted retries calling PostHog: %s" % last_exc)

    def _backoff(self, attempt: int) -> float:
        return min(DEFAULT_BACKOFF_SECONDS * (2 ** attempt), MAX_BACKOFF_SECONDS)

    def _retry_delay(self, response: httpx.Response, attempt: int) -> float:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return min(float(retry_after), MAX_BACKOFF_SECONDS)
            except ValueError:
                pass
        return self._backoff(attempt)


def _message_from(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return "PostHog returned HTTP %d" % response.status_code
    if isinstance(body, dict):
        detail = body.get("detail") or body.get("message")
        if detail:
            return str(detail)
    return "PostHog returned HTTP %d" % response.status_code
