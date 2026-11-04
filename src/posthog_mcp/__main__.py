"""Entry point: run the ASGI app with uvicorn."""

import uvicorn

from posthog_mcp.app import app
from posthog_mcp.settings import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(app, host=settings.mcp_http_host, port=settings.mcp_http_port)


if __name__ == "__main__":
    main()
