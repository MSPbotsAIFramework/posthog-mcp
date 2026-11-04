"""ASGI app: FastMCP server (stateless Streamable HTTP) + a local /health probe.

PRD-21316 contract notes:
- `/health` is registered via `FastMCP.custom_route`, so it lives on the same
  Starlette app `http_app()` returns -- no `Mount()` is involved, so there is
  no "child app lifespan never runs" trap (SOP S7) to begin with.
- `stateless_http=True`: no session affinity, no per-instance state.
- DNS-rebinding Host/Origin checks: the installed `mcp` SDK
  (`mcp.server.transport_security.TransportSecurityMiddleware`) disables this
  check by default when no `TransportSecuritySettings` are supplied, which is
  what `create_streamable_http_app` does here. That default is correct for
  this service (SOP S7): it sits behind the MSPbots gateway, not exposed
  directly, so a Host-header check written for a browser-facing + ancestor
  service would only break legitimate gateway traffic.
"""

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from posthog_mcp.middleware import CredentialMiddleware
from posthog_mcp.tools import register_all


def _build_mcp_server():
    from fastmcp import FastMCP

    mcp = FastMCP(
        name="posthog-mcp",
        instructions=(
            "Tools for PostHog product analytics: feature flags, insights "
            "(saved analyses/charts), raw events, persons, cohorts, and "
            "annotations. Use posthog_list_feature_flags / "
            "posthog_get_feature_flag to inspect rollout state, "
            "posthog_list_insights for a lightweight catalog of saved "
            "analyses (metadata only) then posthog_get_insight with "
            "include_result=true for one insight's chart data, "
            "posthog_list_events for raw event search, and "
            "posthog_list_persons / posthog_get_person to look up a user. "
            "All tools need a PostHog Personal API Key and numeric Project "
            "ID in request headers; X-PostHog-Host defaults to PostHog US "
            "Cloud if omitted."
        ),
    )

    @mcp.custom_route("/health", methods=["GET"])
    async def health(_request: Request) -> JSONResponse:
        # Deliberately independent of PostHog: never calls client.py.
        return JSONResponse({"status": "ok"})

    register_all(mcp)
    return mcp


def create_app() -> Starlette:
    mcp = _build_mcp_server()
    return mcp.http_app(
        path="/mcp",
        transport="streamable-http",
        stateless_http=True,
        middleware=[Middleware(CredentialMiddleware)],
    )


app = create_app()
