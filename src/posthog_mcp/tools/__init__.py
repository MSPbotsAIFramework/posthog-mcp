"""Registers every resource domain's tools onto a FastMCP instance."""

from posthog_mcp.tools import annotations, cohorts, events, feature_flags, insights, persons

_MODULES = (feature_flags, insights, events, persons, cohorts, annotations)


def register_all(mcp) -> None:
    for module in _MODULES:
        module.register(mcp)
