"""Feature flag tools (PRD-21316 AC1, AC2, AC3).

Tool descriptions are a single verb-first sentence (SOP S2.2): parameter
names carry the rest of the self-description, not restated prose.
"""

from posthog_mcp.client import PostHogClient
from posthog_mcp.tools._shared import execute, list_query, list_result


def _shape_flag(raw: dict) -> dict:
    return {
        "id": raw.get("id"),
        "key": raw.get("key"),
        "name": raw.get("name"),
        "active": raw.get("active"),
        "archived": raw.get("deleted", raw.get("archived")),
        "filters": raw.get("filters"),
        "rollout_percentage": raw.get("rollout_percentage"),
        "created_at": raw.get("created_at"),
    }


def register(mcp) -> None:
    @mcp.tool(
        description="List feature flags in the project, newest first.",
        annotations={"readOnlyHint": True, "idempotentHint": True},
    )
    async def posthog_list_feature_flags(
        key: str | None = None,
        search: str | None = None,
        active: bool | None = None,
        archived: bool | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> str:
        async def _run(client: PostHogClient) -> dict:
            params, eff_limit, eff_offset = list_query(
                limit, offset, key=key, search=search, active=active, archived=archived
            )
            data = await client.request(
                "GET", client.project_path("/feature_flags/"), params=params
            )
            flags = [_shape_flag(f) for f in data.get("results", [])]
            return list_result(flags, eff_limit, eff_offset, data.get("next"))

        return await execute(_run)

    @mcp.tool(
        description="Get a single feature flag's full definition, including rollout filters.",
        annotations={"readOnlyHint": True, "idempotentHint": True},
    )
    async def posthog_get_feature_flag(id: int) -> str:
        async def _run(client: PostHogClient) -> dict:
            data = await client.request(
                "GET", client.project_path("/feature_flags/%s/" % id)
            )
            return _shape_flag(data)

        return await execute(_run)
