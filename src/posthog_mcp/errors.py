"""Structured error envelope shared by every tool (PRD-21316 AC3, AC10).

Tools never raise. Every failure path returns `error_envelope(...)` serialized
to a JSON string, so the agent can branch on `code` and `retryable` instead of
catching exceptions.
"""

import json

# Fixed, finite vocabulary -- do not invent new codes.
NOT_CONFIGURED = "not_configured"
UNAUTHORIZED = "unauthorized"
NOT_FOUND = "not_found"
INVALID_ARGUMENT = "invalid_argument"
RATE_LIMITED = "rate_limited"
UPSTREAM_ERROR = "upstream_error"

_RETRYABLE = {RATE_LIMITED, UPSTREAM_ERROR}


class PostHogApiError(Exception):
    """Raised by client.py; carries enough context for errors.py to map it."""

    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def code_for_status(status_code: int) -> str:
    if status_code in (401, 403):
        return UNAUTHORIZED
    if status_code == 404:
        return NOT_FOUND
    if status_code in (400, 422):
        return INVALID_ARGUMENT
    if status_code == 429:
        return RATE_LIMITED
    if status_code >= 500:
        return UPSTREAM_ERROR
    return UPSTREAM_ERROR


def error_envelope(code: str, message: str, retryable: bool | None = None) -> dict:
    """The envelope as a dict. Callers serialize it for their own transport
    (tools dump it to a compact JSON string; HTTP middleware returns it as a
    JSON response body)."""
    if retryable is None:
        retryable = code in _RETRYABLE
    return {"error": {"code": code, "message": message, "retryable": retryable}}


def dumps(envelope: dict) -> str:
    """Compact, non-ASCII-escaped serialization for tool return values
    (PRD-21316 tech design: no indent, ensure_ascii=False)."""
    return json.dumps(envelope, ensure_ascii=False, separators=(",", ":"))


def envelope_for_api_error(exc: PostHogApiError) -> dict:
    code = code_for_status(exc.status_code)
    return error_envelope(code, exc.message)


def not_configured_envelope(missing_headers: list[str]) -> dict:
    names = ", ".join(missing_headers)
    return error_envelope(
        NOT_CONFIGURED,
        "Missing required header(s): %s" % names,
    )
