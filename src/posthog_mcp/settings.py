"""Non-credential configuration. Credentials never live here (PRD-21316, SOP S3.1)."""

from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_HOST = "https://us.posthog.com"

CONNECT_TIMEOUT_SECONDS = 5.0
READ_TIMEOUT_SECONDS = 30.0


class Settings(BaseSettings):
    """Process-level configuration, sourced from the environment.

    `extra="ignore"` is required: the runtime injects environment variables
    this project never declared, and a strict model would crash on startup.
    """

    model_config = SettingsConfigDict(extra="ignore")

    mcp_http_host: str = "0.0.0.0"
    mcp_http_port: int = 8080


def get_settings() -> Settings:
    return Settings()
