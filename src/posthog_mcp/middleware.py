"""Per-request credential handling (PRD-21316 AC10, AC11, AC12).

Credentials travel only in request headers and only live in a `ContextVar`
for the lifetime of that request (SOP S3.3/S3.4). There is no global or
module-level variable holding a credential anywhere in this codebase -- that
is the one thing a concurrency test (tests/test_middleware.py) must keep
proving, because a regression here is a cross-tenant data leak, not a bug.

`project_id` is read only from a header, never accepted as a tool argument
(PRD-21316 "Decisions made by DEV01"): that is what makes AC11's isolation
guarantee structural rather than conventional.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from posthog_mcp.errors import not_configured_envelope
from posthog_mcp.settings import DEFAULT_HOST

API_KEY_HEADER = "X-PostHog-Api-Key"
PROJECT_ID_HEADER = "X-PostHog-Project-Id"
HOST_HEADER = "X-PostHog-Host"

REQUIRED_HEADERS = (API_KEY_HEADER, PROJECT_ID_HEADER)


@dataclass(frozen=True)
class PostHogCredentials:
    api_key: str
    project_id: str
    host: str


_credentials: ContextVar[PostHogCredentials | None] = ContextVar(
    "posthog_credentials", default=None
)


def current_credentials() -> PostHogCredentials | None:
    """None means no request is in flight on this task, or a required header
    was missing (the ASGI middleware already short-circuited that case
    before any tool runs)."""
    return _credentials.get()


@contextmanager
def credentials_scope(creds: PostHogCredentials):
    """Set `_credentials` for the duration of the `with` block and guarantee
    it is cleared afterwards, success or failure (SOP S3.3)."""
    token = _credentials.set(creds)
    try:
        yield
    finally:
        _credentials.reset(token)


def _normalize_host(raw: str | None) -> str:
    host = (raw or DEFAULT_HOST).strip()
    if not host:
        return DEFAULT_HOST
    return host.rstrip("/")


class CredentialMiddleware:
    """ASGI middleware: only guards `/mcp`. `/health` never touches this --
    the health check must not depend on any credential or on PostHog
    reachability (SOP S1.1)."""

    def __init__(self, app: ASGIApp, guarded_path: str = "/mcp"):
        self.app = app
        self.guarded_path = guarded_path

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith(self.guarded_path):
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive=receive)
        missing = [h for h in REQUIRED_HEADERS if not request.headers.get(h)]
        if missing:
            response = JSONResponse(
                not_configured_envelope(missing),
                status_code=401,
            )
            await response(scope, receive, send)
            return

        creds = PostHogCredentials(
            api_key=request.headers[API_KEY_HEADER],
            project_id=request.headers[PROJECT_ID_HEADER],
            host=_normalize_host(request.headers.get(HOST_HEADER)),
        )
        with credentials_scope(creds):
            await self.app(scope, receive, send)


__all__ = [
    "API_KEY_HEADER",
    "PROJECT_ID_HEADER",
    "HOST_HEADER",
    "REQUIRED_HEADERS",
    "PostHogCredentials",
    "current_credentials",
    "credentials_scope",
    "CredentialMiddleware",
]
